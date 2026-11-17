"""Step 0 safety floor: the backup ring, the refusal without state.json,
appglass restore and appglass doctor [--fix]."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import time
import unittest

from fixtures.sandbox import Sandbox, REPO
from appglass import core, hook, niri, plugin


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        self.env = core.Env(self.sb.env)
        self.state_dir = os.path.join(self.sb.state, "appglass")
        self.state_json = os.path.join(self.state_dir, "state.json")
        self.ring = os.path.join(self.state_dir, "ring")

    def tearDown(self):
        self.sb.cleanup()

    def apply(self, *extra, ok=True):
        code, out, err = self.sb.run("apply", "--only", "alacritty", *extra, assume="alacritty")
        if ok:
            self.assertEqual(code, 0, err)
        return code, out, err

    def owned(self):
        return self.sb.cfg("alacritty", "appglass.toml")

    def entries(self):
        return sorted(os.listdir(self.ring)) if os.path.isdir(self.ring) else []

    def manifest(self, entry):
        with open(os.path.join(self.ring, entry, "manifest.json")) as f:
            return json.load(f)

    def sync_file(self, enabled=True):
        code, out, err = self.sb.run("get")
        self.assertEqual(code, 0, err)
        obj = dict(json.loads(out), enabled=enabled)
        p = self.sb.path("plugin-settings.json")
        with open(p, "w") as f:
            json.dump(obj, f)
        return p


class Ring(Base):
    def test_every_writing_apply_snapshots_and_the_ring_keeps_five(self):
        firsts = []
        for i, v in enumerate((0.50, 0.55, 0.60, 0.65, 0.70, 0.75)):
            self.sb.set_level(v)
            before = self.sb.readb(self.owned()) if i else None
            self.apply()
            ents = self.entries()
            self.assertEqual(len(ents), min(i + 1, 5), ents)
            newest = ents[-1]
            firsts.append(newest)
            m = self.manifest(newest)
            rec = m["files"][self.owned()]
            if i == 0:
                # the first apply created the file: the snapshot says absent
                self.assertTrue(rec.get("absent"), rec)
                self.assertFalse(os.path.exists(os.path.join(self.ring, newest, "state.json")))
            else:
                self.assertEqual(rec["sha256"], hashlib.sha256(before).hexdigest())
                with open(os.path.join(self.ring, newest, rec["blob"]), "rb") as f:
                    self.assertEqual(f.read(), before)
                self.assertTrue(os.path.isfile(os.path.join(self.ring, newest, "state.json")))
        self.assertEqual(len(set(firsts)), 6)
        self.assertNotIn(firsts[0], self.entries(), "the oldest is pruned")
        self.assertEqual(self.entries(), firsts[1:])

    def test_a_run_that_writes_nothing_takes_no_snapshot(self):
        self.apply()
        self.apply()
        self.assertEqual(len(self.entries()), 1)

    def test_dry_run_takes_no_snapshot(self):
        self.apply("--dry-run")
        self.assertEqual(self.entries(), [])

    def test_sync_snapshots_too(self):
        self.apply()
        self.sb.set_level(0.6)
        code, out, err = self.sb.run("sync", "--settings-file", self.sync_file(),
                                     assume="alacritty", assume_not="gtk3,gtk4")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.entries()), 2)

    def test_full_remove_leaves_the_tree_byte_identical(self):
        self.sb.set_level(0.6)
        before = self.sb.tree_hash()
        self.sb.set_level(0.5)
        self.apply()
        self.sb.set_level(0.6)
        self.apply()
        self.assertEqual(len(self.entries()), 2)
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_restore_puts_the_files_and_state_back(self):
        self.sb.set_level(0.5)
        self.apply()
        first = self.sb.readb(self.owned())
        state1 = self.sb.readb(self.state_json)
        self.sb.set_level(0.7)
        self.apply()
        self.assertNotEqual(self.sb.readb(self.owned()), first)
        code, out, err = self.sb.run("restore", "--list")
        self.assertEqual(code, 0, err)
        newest = self.entries()[-1]
        self.assertIn(newest, out)
        code, out, err = self.sb.run("restore", newest)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.readb(self.owned()), first)
        self.assertEqual(self.sb.readb(self.state_json), state1)
        # the restore itself is undoable: the state before it is a new entry
        self.assertEqual(len(self.entries()), 3)
        self.assertIn(newest, self.entries())

    def test_ring_order_survives_a_clock_going_back(self):
        # a DST fall-back or a timezone change: local time goes back, and
        # the newest entry must still be the one restore puts back
        old = os.environ.get("TZ")
        try:
            for i, (tz, v) in enumerate((("UTC0", 0.5), ("XXX10", 0.6), ("YYY-10", 0.7))):
                os.environ["TZ"] = tz
                time.tzset()
                self.sb.set_level(v)
                self.apply()
                states = self.sb.readb(self.state_json)
                self.assertEqual(len(self.entries()), i + 1)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
        self.sb.set_level(0.8)
        self.apply()
        code, out, err = self.sb.run("restore")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.readb(self.state_json), states, "the newest entry put back")

    def test_a_dropped_backup_goes_into_the_ring(self):
        # remove --only drops the backup of alacritty.toml: restoring the
        # state before it must find that backup again
        self.assertEqual(self.sb.run("hook", "install")[0], 0)
        main = self.sb.cfg("alacritty", "alacritty.toml")
        orig = self.sb.readb(main)
        self.apply()
        code, out, err = self.sb.run("remove", "--only", "alacritty")
        self.assertEqual(code, 0, err)
        code, out, err = self.sb.run("restore")
        self.assertEqual(code, 0, err)
        self.assertNotEqual(self.sb.readb(main), orig)
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.readb(main), orig)

    def test_restore_unknown_entry_fails(self):
        self.apply()
        code, out, err = self.sb.run("restore", "nope")
        self.assertNotEqual(code, 0)
        self.assertIn("nope", err)


class Refusal(Base):
    HINT = ("appglass doctor", "appglass restore")

    def assertHint(self, err):
        for h in self.HINT:
            self.assertIn(h, err)

    def test_apply_refuses_when_state_json_is_gone_but_owned_files_exist(self):
        self.apply()
        os.remove(self.state_json)
        data = self.sb.readb(self.owned())
        code, out, err = self.apply(ok=False)
        self.assertNotEqual(code, 0)
        self.assertHint(err)
        self.assertIn(self.env.tilde(self.owned()), err)
        self.assertEqual(self.sb.readb(self.owned()), data)
        self.assertFalse(os.path.exists(self.state_json), "nothing recorded")

    def test_apply_all_and_from_hook_and_sync_refuse_too(self):
        self.apply()
        os.remove(self.state_json)
        for argv in (("apply", "--all"), ("apply", "--from-hook"),
                     ("sync", "--settings-file", self.sync_file())):
            code, out, err = self.sb.run(*argv, assume="alacritty")
            self.assertNotEqual(code, 0, argv)
            self.assertHint(err)

    def test_niri_fragment_alone_counts(self):
        self.apply()
        frag = self.sb.cfg("niri", niri.FILE)
        self.assertTrue(os.path.exists(frag))
        os.remove(self.owned())
        os.remove(self.state_json)
        code, out, err = self.apply(ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn(self.env.tilde(frag), err)

    def test_hook_units_count(self):
        code, out, err = self.sb.run("hook", "install")
        self.assertEqual(code, 0, err)
        os.remove(self.state_json)
        code, out, err = self.apply(ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("appglass-vibrancy.service", err)

    def test_unreadable_state_gives_the_hint(self):
        self.apply()
        with open(self.state_json, "w") as f:
            f.write("{garbage")
        code, out, err = self.apply(ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("unreadable state", err)
        self.assertHint(err)

    def test_backups_without_state_json_count_as_lost_state(self):
        # no marker file left (a family whose files carry none, the niri
        # fragment gone): backup/ still says appglass had state here
        self.apply()
        for p in (self.owned(), self.sb.cfg("niri", niri.FILE)):
            os.remove(p)
        os.remove(self.state_json)
        main = self.sb.cfg("alacritty", "alacritty.toml")
        data = self.sb.readb(main)
        code, out, err = self.apply(ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("backup", err)
        self.assertHint(err)
        self.assertEqual(self.sb.readb(main), data)
        code, out, err = self.sb.run("doctor")
        self.assertEqual(code, 1)
        self.assertIn("appglass restore", out)

    def test_restore_to_before_the_first_apply_applies_again(self):
        # the oldest entry has no state.json: after it, the backups of the
        # later state go into the ring too, and apply runs again
        self.sb.set_level(0.5)
        self.apply()
        self.sb.set_level(0.6)
        self.apply()
        first = self.entries()[0]
        code, out, err = self.sb.run("restore", first)
        self.assertEqual(code, 0, err)
        with open(self.state_json) as f:
            self.assertEqual(json.load(f)["owners"], {}, "an empty state, nothing lost")
        self.assertFalse(os.listdir(os.path.join(self.state_dir, "backup"))
                         if os.path.isdir(os.path.join(self.state_dir, "backup")) else [])
        self.apply()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)

    def test_a_probe_that_raises_is_reported(self):
        from unittest import mock
        from appglass.families import alacritty
        self.apply()
        os.remove(self.state_json)
        err = io.StringIO()
        app = core.App(dict(self.sb.env, APPGLASS_ASSUME_INSTALLED="alacritty"),
                       out=io.StringIO(), err=err)
        with mock.patch.object(alacritty, "apply", side_effect=RuntimeError("boom")):
            core._engine_paths(app)
        self.assertIn("alacritty", err.getvalue())
        self.assertIn("boom", err.getvalue())

    def test_remove_on_a_lost_state_refuses(self):
        self.apply()
        os.remove(self.state_json)
        code, out, err = self.sb.run("remove")
        self.assertNotEqual(code, 0)
        self.assertIn("appglass restore", err)
        self.assertTrue(self.entries())

    def test_a_clean_home_applies(self):
        self.apply()
        self.assertTrue(os.path.isfile(self.state_json))

    def test_restore_after_a_lost_state_json(self):
        self.sb.set_level(0.5)
        self.apply()
        self.sb.set_level(0.6)
        self.apply()
        os.remove(self.state_json)
        code, out, err = self.sb.run("restore")      # newest
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(self.state_json))
        self.apply()

    def lost_state_with_an_adopted_file(self):
        hand = self.sb.write("niri/appglass-test.kdl", "// my rules\nwindow-rule { opacity 1.0; }\n")
        mine = self.sb.readb(hand)
        code, out, err = self.sb.run("adopt", hand, assume="alacritty")
        self.assertEqual(code, 0, err)
        self.sb.set_level(0.5)
        self.apply()
        self.sb.set_level(0.6)
        self.apply()
        backup = os.path.join(self.state_dir, "backup")
        self.assertTrue(os.listdir(backup))
        os.remove(self.state_json)
        return hand, mine, backup

    def test_a_refusal_keeps_the_ring_and_the_backups(self):
        # the refusal itself must not wipe the only saved state.json and the
        # originals of the adopted files (the sync path unit runs
        # apply --from-hook on the next DMS change, unasked)
        for argv in (("apply", "--from-hook", "--quiet"), ("apply", "--only", "alacritty"),
                     ("apply", "--all"), ("sync", None), ("doctor", "--fix"), ("doctor",),
                     ("remove",)):
            with self.subTest(argv=argv):
                self.tearDown()
                self.setUp()
                hand, mine, backup = self.lost_state_with_an_adopted_file()
                ring = self.entries()
                origs = sorted(os.listdir(backup))
                if argv[0] == "sync":
                    argv = ("sync", "--settings-file", self.sync_file())
                code, out, err = self.sb.run(*argv, assume="alacritty")
                if argv[0] != "remove":
                    self.assertNotEqual(code, 0, argv)
                self.assertEqual(self.entries(), ring, argv)
                self.assertEqual(sorted(os.listdir(backup)), origs, argv)
                code, out, err = self.sb.run("restore", assume="alacritty")
                self.assertEqual(code, 0, err)
                self.assertTrue(os.path.isfile(self.state_json))
                code, out, err = self.sb.run("remove")
                self.assertEqual(code, 0, err)
                self.assertEqual(self.sb.readb(hand), mine, "the adopted file's own rules")

    def test_restore_on_an_unreadable_state(self):
        self.sb.set_level(0.5)
        self.apply()
        self.sb.set_level(0.6)
        self.apply()
        good = self.sb.readb(self.state_json)
        for bad in (b"{garbage", b"", b'{"version": 99}'):
            with self.subTest(bad=bad):
                with open(self.state_json, "wb") as f:
                    f.write(bad)
                code, out, err = self.apply(ok=False)
                self.assertNotEqual(code, 0)
                self.assertIn("appglass restore", err)
                # the hinted commands work, and change nothing but restore
                for argv in (("restore", "--list"), ("doctor",), ("get",)):
                    code, out, err = self.sb.run(*argv, assume="alacritty")
                    self.assertNotIn("Traceback", err)
                    self.assertNotIn("unreadable state", err, argv)
                    self.assertTrue(os.path.isdir(self.ring), argv)
                    self.assertEqual(self.sb.readb(self.state_json), bad, argv)
                code, out, err = self.sb.run("doctor")
                self.assertEqual(code, 1)
                self.assertIn("unreadable", out)
                code, out, err = self.sb.run("doctor", "--fix")
                self.assertEqual(code, 1)
                self.assertEqual(self.sb.readb(self.state_json), bad)
                n = len(self.entries())
                code, out, err = self.sb.run("restore")
                self.assertEqual(code, 0, err)
                self.assertNotEqual(self.sb.readb(self.state_json), bad)
                # the bad bytes went into the ring entry the restore made
                newest = self.entries()[-1]
                self.assertTrue(self.manifest(newest)["state"])
                with open(os.path.join(self.ring, newest, "state.json"), "rb") as f:
                    self.assertEqual(f.read(), bad)
                self.assertGreaterEqual(len(self.entries()), min(n + 1, core.RING_KEEP))
                self.apply()
                with open(self.state_json, "wb") as f:
                    f.write(good)


class EventsRemoveNothing(Base):
    """S6 at run time: a family not detected for a moment keeps its files
    on an event (the hook's apply --from-hook, the plugin's sync); only a
    typed appglass apply, or the user's switch, takes them out."""

    def test_from_hook_keeps_a_family_not_detected(self):
        self.apply()
        data = self.sb.readb(self.owned())
        code, out, err = self.sb.run("apply", "--from-hook", assume_not="alacritty")
        self.assertEqual(code, 0, err)
        self.assertIn("alacritty: not installed, left as is", out)
        self.assertEqual(self.sb.readb(self.owned()), data)

    def test_from_hook_keeps_a_family_switched_off(self):
        self.apply()
        code, out, err = self.sb.run("set", "apps.alacritty.enabled", "false")
        self.assertEqual(code, 0, err)
        code, out, err = self.sb.run("apply", "--from-hook", assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(self.owned()))

    def test_plugin_sync_keeps_a_family_not_detected(self):
        self.apply()
        p = self.sync_file()
        code, out, err = self.sb.run("sync", "--settings-file", p, assume_not="alacritty")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(self.owned()))
        self.assertIn("left as is", out)

    def test_typed_apply_still_removes_a_family_gone(self):
        self.apply()
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume_not="alacritty")
        self.assertEqual(code, 0, err)
        self.assertIn("not installed, files removed", out)
        self.assertFalse(os.path.exists(self.owned()))


class Doctor(Base):
    def doctor(self, *extra):
        return self.sb.run("doctor", *extra, assume="alacritty")

    def unit(self, name=hook.PATH_UNIT):
        return self.sb.cfg("systemd", "user", name)

    def repo_unit(self, name=hook.PATH_UNIT):
        return os.path.join(REPO, "shims", "sync", name)

    def test_clean_install_has_no_drift(self):
        self.assertEqual(self.sb.run("hook", "install")[0], 0)
        self.apply()
        code, out, err = self.doctor()
        self.assertEqual(code, 0, out + err)
        self.assertIn("no drift", out)

    def test_hand_edited_sync_path_is_reported_and_fixed(self):
        code, out, err = self.sb.run("hook", "install")
        self.assertEqual(code, 0, err)
        p = self.unit()
        self.assertEqual(sha_file(p), sha_file(self.repo_unit()))
        with open(p, "a") as f:
            f.write("PathModified=%h/.config/discord\n")
        hand = self.sb.readb(p)
        code, out, err = self.doctor()
        self.assertEqual(code, 1, out + err)
        lines = [ln for ln in out.splitlines() if hook.PATH_UNIT in ln]
        self.assertEqual(len(lines), 1, out)
        self.assertEqual(self.sb.readb(p), hand, "doctor without --fix changes nothing")
        n = len(self.entries())
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(sha_file(p), sha_file(self.repo_unit()))
        # the hand edit went into the ring first
        self.assertEqual(len(self.entries()), n + 1)
        rec = self.manifest(self.entries()[-1])["files"][p]
        self.assertEqual(rec["sha256"], hashlib.sha256(hand).hexdigest())
        code, out, err = self.doctor()
        self.assertEqual(code, 0, out + err)

    def test_stale_hand_made_unit_is_reported_not_overwritten(self):
        p = self.unit()
        os.makedirs(os.path.dirname(p))
        with open(p, "w") as f:
            f.write("[Path]\nPathChanged=%h/.config/discord\n")
        hand = self.sb.readb(p)
        code, out, err = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn(hook.PATH_UNIT, out)
        self.assertIn("appglass adopt", out)
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 1, "a hand file is not fixed")
        self.assertEqual(self.sb.readb(p), hand)

    def test_missing_unit_is_drift(self):
        self.assertEqual(self.sb.run("hook", "install")[0], 0)
        os.remove(self.unit(hook.VIBRANCY_UNIT))
        code, out, err = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn(hook.VIBRANCY_UNIT, out)
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(sha_file(self.unit(hook.VIBRANCY_UNIT)),
                         sha_file(self.repo_unit(hook.VIBRANCY_UNIT)))

    def test_niri_fragment_drift(self):
        self.apply()
        frag = self.sb.cfg("niri", niri.FILE)
        good = self.sb.readb(frag)
        with open(frag, "a") as f:
            f.write("// hand\n")
        code, out, err = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(len([ln for ln in out.splitlines() if niri.FILE in ln]), 1, out)
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.readb(frag), good)

    def test_owned_file_drift(self):
        self.apply()
        good = self.sb.readb(self.owned())
        with open(self.owned(), "a") as f:
            f.write("# hand\n")
        code, out, err = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("appglass.toml", out)
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.readb(self.owned()), good)

    def test_plugin_link_dangling_is_fixed(self):
        dst = plugin.target(self.env)
        os.makedirs(os.path.dirname(dst))
        os.symlink(self.sb.path("gone"), dst)
        code, out, err = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("plugin", out)
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(os.path.realpath(dst), os.path.realpath(plugin.source()))

    def test_plugin_link_elsewhere_is_reported(self):
        dst = plugin.target(self.env)
        other = self.sb.path("other-plugin")
        os.makedirs(other)
        os.makedirs(os.path.dirname(dst))
        os.symlink(other, dst)
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 1)
        self.assertIn("plugin", out)
        self.assertEqual(os.readlink(dst), other)

    def test_lost_state_is_drift(self):
        self.apply()
        os.remove(self.state_json)
        code, out, err = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("appglass restore", out)

    def test_doctor_in_help_and_readme(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            core.main(["--help"], environ=self.sb.env)
        self.assertIn("doctor", buf.getvalue())
        self.assertIn("restore", buf.getvalue())
        with open(os.path.join(REPO, "docs", "README.md")) as f:
            readme = f.read()
        self.assertIn("appglass doctor", readme)
        self.assertIn("appglass restore", readme)


class LostStaysLost(Base):
    """A lost state (state.json gone, the ring or backup/ still there) is
    sticky: no command saves a fresh state.json over it, so no later apply
    edits the files twice and no remove takes the originals out with the
    state dir."""

    def test_commands_that_save_state_refuse_while_lost(self):
        for argv in (("set", "fallback.mode", "opaque"), ("hook", "install"),
                     ("hook", "remove")):
            with self.subTest(argv=argv):
                self.tearDown()
                self.setUp()
                self.sb.set_level(0.6)
                before = self.sb.tree_hash()
                hand, mine, backup = Refusal.lost_state_with_an_adopted_file(self)
                origs = sorted(os.listdir(backup))
                code, out, err = self.sb.run(*argv, assume="alacritty")
                self.assertNotEqual(code, 0, argv)
                self.assertIn("appglass restore", err)
                self.assertFalse(os.path.exists(self.state_json), argv)
                for later in (("apply", "--only", "alacritty"), ("remove",)):
                    code, out, err = self.sb.run(*later, assume="alacritty")
                    self.assertNotEqual(code, 0, later)
                self.assertEqual(sorted(os.listdir(backup)), origs, argv)
                code, out, err = self.sb.run("restore", assume="alacritty")
                self.assertEqual(code, 0, err)
                code, out, err = self.sb.run("remove")
                self.assertEqual(code, 0, err)
                self.assertEqual(self.sb.readb(hand), mine)
                os.remove(hand)         # written after `before`
                self.assertEqual(self.sb.tree_hash(), before, (argv, self.sb.files()))

    def test_a_backup_never_overwrites_an_original_no_record_names(self):
        p = self.sb.cfg("alacritty", "alacritty.toml")
        os.makedirs(os.path.join(self.state_dir, "backup"))
        bpath = os.path.join(self.state_dir, "backup",
                             hashlib.sha1(p.encode()).hexdigest()[:16] + ".orig")
        with open(bpath, "wb") as f:
            f.write(b"the only original\n")
        with open(self.state_json, "w") as f:
            json.dump({"version": core.STATE_VERSION, "owners": {}, "state_parents": []}, f)
        app = core.App(self.sb.env, out=io.StringIO(), err=io.StringIO())
        with self.assertRaises(core.AppglassError) as cm:
            app.backup(p, b"something else\n")
        self.assertIn("appglass restore", str(cm.exception))
        self.assertEqual(self.sb.readb(bpath), b"the only original\n")
        # the same bytes again (a run stopped right after its backup): fine
        app.backup(p, b"the only original\n")

    def test_full_remove_keeps_originals_no_record_names(self):
        self.apply()
        stray = os.path.join(self.state_dir, "backup", "0123456789abcdef.orig")
        with open(stray, "wb") as f:
            f.write(b"precious\n")
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.readb(stray), b"precious\n")
        self.assertTrue(self.entries(), "the ring stays with it")
        self.assertIn("0123456789abcdef.orig", err)


class EditMarkers(Base):
    """The files appglass edits (not only the ones it writes) count as its
    files when their record is gone."""

    def test_edited_files_refuse_after_the_owned_ones_are_gone(self):
        self.apply()
        main = self.sb.cfg("alacritty", "alacritty.toml")
        cfg = self.sb.cfg("niri", "config.kdl")
        shutil.rmtree(self.state_dir)       # the whole state dir moved away
        code, out, err = self.apply(ok=False)
        self.assertNotEqual(code, 0)
        named = [p for p in (self.owned(), self.sb.cfg("niri", niri.FILE))
                 if self.env.tilde(p) in err]
        self.assertEqual(len(named), 2, err)
        for p in named:
            os.remove(p)
        data = {p: self.sb.readb(p) for p in (main, cfg)}
        code, out, err = self.apply(ok=False)
        self.assertNotEqual(code, 0, "an edited file is still on disk")
        for p in (main, cfg):
            self.assertIn(self.env.tilde(p), err)
            self.assertEqual(self.sb.readb(p), data[p])
        self.assertFalse(os.path.exists(self.state_json))

    def test_a_clean_edited_file_does_not_count(self):
        self.apply()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.apply()

    def test_launcher_overrides_carry_a_marker(self):
        from appglass import shims
        from appglass.families import qtstyle
        qt = qtstyle.launcher(self.env, "[Desktop Entry]\nExec=vlc %U\n", "vlc", 0.6)
        wrapped = shims.exec_to("[Desktop Entry]\nExec=/usr/bin/foo %U\n",
                                self.sb.home + "/.local/bin/appglass-foo", command="foo")
        for text in (qt, wrapped):
            self.assertTrue(core.MARK.search(text.encode()), text)
        self.assertFalse(core.MARK.search(b"[Desktop Entry]\nExec=vlc %U\n"))


class RestoreOlder(Base):
    def test_restoring_an_older_entry_undoes_every_newer_one(self):
        self.sb.set_level(0.6)
        before = self.sb.tree_hash()
        self.sb.set_level(0.5)
        self.apply()
        self.sb.set_level(0.6)
        self.apply()
        older = self.entries()[-1]
        state = self.sb.readb(self.state_json)
        code, out, err = self.sb.run("hook", "install")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.entries()), 3)
        code, out, err = self.sb.run("restore", older)
        self.assertEqual(code, 0, err)
        # the state before `older`: the hook's files went with its entry
        self.assertFalse(os.path.exists(hook.unit_path(self.env, hook.PATH_UNIT)))
        self.assertNotEqual(self.sb.readb(self.state_json), state)
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_restoring_the_first_entry_leaves_a_valid_state(self):
        self.apply()
        self.sb.set_level(0.6)
        self.apply()
        code, out, err = self.sb.run("restore", self.entries()[0])
        self.assertEqual(code, 0, err)
        with open(self.state_json) as f:
            self.assertEqual(json.load(f)["owners"], {})
        # nothing lost: remove and glass off run
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        code, out, err = self.sb.run("sync", "--settings-file", self.sync_file(False),
                                     assume="alacritty")
        self.assertEqual(code, 0, err)

    def test_an_event_after_a_restore_keeps_the_ring(self):
        self.apply()
        self.sb.set_level(0.6)
        self.apply()
        code, out, err = self.sb.run("restore", self.entries()[0])
        self.assertEqual(code, 0, err)
        entries = self.entries()
        # the matugen hook wrote nothing: the way back stays
        code, out, err = self.sb.run("apply", "--from-hook", "--quiet")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.entries(), entries)
        # the user's remove ends it
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.ring))

    def test_every_entry_has_a_manifest(self):
        self.apply()
        self.sb.set_level(0.6)
        self.apply()
        os.makedirs(os.path.join(self.ring, "20000101-000000-000000"))
        code, out, err = self.sb.run("restore")
        self.assertEqual(code, 0, err)
        for e in os.listdir(self.ring):
            self.assertTrue(os.path.isfile(os.path.join(self.ring, e, "manifest.json")), e)


class DoctorRound2(Base):
    def doctor(self, *extra):
        return self.sb.run("doctor", *extra, assume="alacritty")

    def test_missing_niri_include_is_drift_for_the_user(self):
        self.apply()
        cfg = self.sb.cfg("niri", "config.kdl")
        text = niri.strip_include(self.sb.read(cfg))
        with open(cfg, "w") as f:
            f.write(text)
        code, out, err = self.doctor()
        self.assertEqual(code, 1, out + err)
        self.assertIn("config.kdl", out)
        self.assertIn(niri.FILE, out)
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 1)
        self.assertIn("yours to decide", out)
        self.assertEqual(self.sb.read(cfg), text)

    def test_fix_saves_the_hand_version_aside(self):
        self.apply()
        with open(self.owned(), "a") as f:
            f.write("# hand\n")
        hand = self.sb.readb(self.owned())
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.readb(self.owned() + ".appglass-changed"), hand)

    def test_relink_snapshots_the_link(self):
        self.apply()
        dst = plugin.target(self.env)
        os.makedirs(os.path.dirname(dst))
        gone = self.sb.path("gone")
        os.symlink(gone, dst)
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 0, out + err)
        rec = self.manifest(self.entries()[-1])["files"][dst]
        self.assertEqual(rec, {"link": gone})


class Hints(Base):
    def test_the_hint_names_only_what_works(self):
        self.apply()
        os.remove(self.state_json)
        code, out, err = self.apply(ok=False)
        self.assertNotIn("appglass adopt <file>", err)
        self.assertIn("appglass doctor", err)
        code, out, err = self.sb.run("adopt", self.owned())
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
