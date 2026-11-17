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

    def test_ring_order_is_a_sequence_not_the_clock(self):
        # eleven entries in the same microsecond (or a clock that stands
        # still): the newest is still the one restore puts back, and pruning
        # drops the oldest
        from unittest import mock
        with mock.patch("appglass.core.time.time", return_value=1.0e9):
            for i in range(12):
                self.sb.set_level(0.5 if i % 2 else 0.6)
                if i == 11:
                    states = self.sb.readb(self.state_json)
                self.apply()
            names = core.ring_entries(self.env)
            self.assertEqual(len(names), 5, names)
            seqs = [self.manifest(n)["seq"] for n in names]
            self.assertEqual(seqs, sorted(seqs))
            self.assertEqual(seqs, list(range(seqs[-1] - 4, seqs[-1] + 1)))
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
    HINT = ("appglass doctor", "appglass restore", "appglass adopt --rescue")

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
        # the units are hand files too (a hand copy of the repo unit is the
        # same bytes); the wrappers hook install writes carry its marker
        self.assertIn(self.env.tilde(hook.vibrancy_path(self.env)), err)
        self.assertIn(self.env.tilde(hook.config_path(self.env)), err)

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

    def test_fix_never_overwrites_a_saved_aside_version(self):
        self.apply()
        aside = self.owned() + ".appglass-changed"
        with open(aside, "wb") as f:
            f.write(b"older\n")
        with open(self.owned(), "a") as f:
            f.write("# hand\n")
        hand = self.sb.readb(self.owned())
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.readb(aside), b"older\n")
        self.assertEqual(self.sb.readb(aside + ".1"), hand)

    def test_fix_leaves_out_a_hook_section_the_user_took_out(self):
        code, out, err = self.sb.run("hook", "install")
        self.assertEqual(code, 0, err)
        cfg = hook.config_path(self.env)
        text = hook.strip(self.sb.read(cfg))
        with open(cfg, "w") as f:
            f.write(text)
        code, out, err = self.doctor()
        self.assertEqual(code, 1, out + err)
        self.assertIn(self.env.tilde(cfg), out)
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 1, out + err)
        self.assertIn("yours to decide", out)
        self.assertEqual(self.sb.read(cfg), text)

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


class HandHookFiles(Base):
    """The hook's files made by hand before appglass (the vibrancy and
    discord units, the vibrancy wrapper) are hand files, not appglass files
    whose record is gone."""

    UNITS = (hook.VIBRANCY_UNIT, "appglass-discord.path", "appglass-discord.service")

    def hand(self):
        paths = []
        for n in self.UNITS:
            p = self.sb.cfg("systemd", "user", n)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            shutil.copyfile(os.path.join(REPO, "shims", "sync", n), p)
            paths.append(p)
        p = os.path.join(self.sb.home, ".local", "bin", "appglass-vibrancy")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("#!/bin/sh\nAPPGLASS_HAND=1 exec ~/.local/bin/appglass-sync vibrancy\n")
        return paths + [p]

    def test_a_fresh_install_with_hand_made_hook_files_applies(self):
        paths = self.hand()
        data = {p: self.sb.readb(p) for p in paths}
        code, out, err = self.apply()
        self.assertNotIn("state.json is missing", err)
        code, out, err = self.sb.run("status", "--json")
        self.assertEqual(code, 0, err)
        st = {h["path"]: h["status"] for h in json.loads(out)["hand_files"]}
        for p in paths:
            self.assertEqual(st[self.env.tilde(p)], "conflict", p)
            self.assertEqual(self.sb.readb(p), data[p])

    def test_doctor_names_an_adopt_that_runs(self):
        p = self.sb.cfg("systemd", "user", hook.VIBRANCY_UNIT)
        os.makedirs(os.path.dirname(p))
        with open(p, "w") as f:
            f.write("[Service]\nExecStart=%h/.local/bin/appglass-vibrancy\n")
        code, out, err = self.sb.run("doctor")
        self.assertEqual(code, 1, out + err)
        cmd = "appglass adopt %s" % self.env.tilde(p)
        self.assertIn(cmd, out)
        code, out, err = self.sb.run(*cmd.split()[1:])
        self.assertEqual(code, 0, out + err)
        with open(self.state_json) as f:
            self.assertIn(p, json.load(f)["owners"]["hook"]["files"])
        code, out, err = self.sb.run("doctor")
        self.assertEqual(code, 0, out + err)

    def test_the_named_adopt_runs_with_other_hand_units(self):
        # one hand unit adopted by path, a sibling hand unit there too: the
        # hook install that follows must not stop at the sibling
        p = self.sb.cfg("systemd", "user", hook.VIBRANCY_UNIT)
        os.makedirs(os.path.dirname(p))
        with open(p, "w") as f:
            f.write("[Service]\nExecStart=%h/.local/bin/appglass-vibrancy\n")
        q = self.sb.cfg("systemd", "user", "appglass-discord.service")
        with open(q, "w") as f:
            f.write("[Service]\nExecStart=/usr/bin/true\n")
        code, out, err = self.sb.run("doctor")
        cmd = "appglass adopt %s" % self.env.tilde(p)
        self.assertIn(cmd, out)
        code, out, err = self.sb.run(*cmd.split()[1:])
        self.assertEqual(code, 0, out + err)
        self.assertTrue(hook.installed(core.App(self.sb.env, out=io.StringIO(),
                                                err=io.StringIO())))
        code, out, err = self.sb.run("doctor")
        self.assertEqual(code, 0, out + err)
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.read(q), "[Service]\nExecStart=/usr/bin/true\n")


class EventGuard(Base):
    """S6 at run time: a run that is an event (the plugin's sync, the hook,
    the path units, doctor, status) cannot revert, remove or forget a file;
    only a command the user typed, or the user's own switch, does."""

    def test_an_event_run_cannot_revert_remove_or_forget(self):
        self.apply()
        data = self.sb.readb(self.owned())
        app = core.App(self.sb.env, out=io.StringIO(), err=io.StringIO())
        app.event = True
        rec = app.state.owners["alacritty"]["files"][self.owned()]
        for name, fn in (
                ("remove_owner", lambda: app.remove_owner("alacritty")),
                ("_revert", lambda: app._revert("alacritty", self.owned(), rec)),
                ("cmd_remove", lambda: core.cmd_remove(app)),
                ("cmd_remove only", lambda: core.cmd_remove(app, "alacritty")),
                ("State.destroy", lambda: app.state.destroy()),
                ("hook.remove", lambda: hook.remove(app)),
                ("plugin.remove", lambda: plugin.remove(app))):
            with self.subTest(name):
                with self.assertRaises(core.EventRemove):
                    fn()
        self.assertEqual(self.sb.readb(self.owned()), data)
        with open(self.state_json) as f:
            self.assertIn(self.owned(), json.load(f)["owners"]["alacritty"]["files"])
        # the user's own switch, inside an event run, is not an event
        with app.user_action():
            self.assertTrue(app.remove_owner("alacritty"))
        self.assertFalse(os.path.exists(self.owned()))
        self.assertTrue(app.event)

    def test_which_runs_are_events(self):
        from unittest import mock
        seen = {}

        def spy(name, rc=None):
            def f(app, *a, **kw):
                seen[name] = app.event
                return rc
            return f
        self.apply()
        p = self.sync_file()
        runs = (
            (("sync", "--settings-file", p), "cmd_sync", True),
            (("apply", "--from-hook"), "cmd_apply", True),
            (("doctor",), "cmd_doctor", True),
            (("doctor", "--fix"), "cmd_doctor", True),
            (("status",), "cmd_status", True),
            (("apply", "--only", "alacritty"), "cmd_apply", False),
            (("apply", "--all"), "cmd_apply_all", False),
            (("remove",), "cmd_remove", False),
            (("set", "fallback.mode", "off"), "cmd_set", False),
            (("adopt",), "cmd_adopt", False),
            (("restore",), "cmd_restore", False),
        )
        for argv, fn, event in runs:
            with self.subTest(argv=argv):
                seen.clear()
                with mock.patch.object(core, fn, spy(fn, 0)):
                    code, out, err = self.sb.run(*argv, assume="alacritty")
                self.assertEqual(code, 0, err)
                self.assertEqual(seen, {fn: event})

    def test_a_sync_that_switches_a_family_off_removes_it(self):
        self.apply()
        code, out, err = self.sb.run("get")
        obj = json.loads(out)
        obj.setdefault("apps", {})["alacritty"] = {"enabled": False}
        p = self.sb.path("plugin-settings.json")
        with open(p, "w") as f:
            json.dump(obj, f)
        code, out, err = self.sb.run("sync", "--settings-file", p, assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertIn("alacritty: off in settings, files removed", out)
        self.assertFalse(os.path.exists(self.owned()))
        # the same settings again: nothing switched, nothing to remove
        code, out, err = self.sb.run("sync", "--settings-file", p, assume="alacritty")
        self.assertEqual(code, 0, err)

    def test_a_sync_that_failed_switches_the_family_off_on_the_next_one(self):
        # the sync saves the settings, then its apply fails: the next sync
        # with the same settings still takes the family out (the switch is
        # against what the last finished sync applied)
        from unittest import mock
        self.apply()
        code, out, err = self.sb.run("get")
        obj = json.loads(out)
        p = self.sb.path("plugin-settings.json")
        for apps, fn in (({"alacritty": {"enabled": False}}, "cmd_apply_all"),
                         (None, "cmd_remove")):
            with self.subTest(fn=fn):
                if apps is None:
                    self.apply()
                    on = dict(obj, enabled=False)
                else:
                    on = dict(obj, apps=dict(obj.get("apps") or {}, **apps))
                with open(p, "w") as f:
                    json.dump(on, f)

                def boom(*a, **k):
                    raise core.AppglassError("interrupted")
                with mock.patch.object(core, fn, boom):
                    code, out, err = self.sb.run("sync", "--settings-file", p,
                                                 assume="alacritty")
                self.assertNotEqual(code, 0)
                self.assertTrue(os.path.exists(self.owned()))
                code, out, err = self.sb.run("sync", "--settings-file", p, assume="alacritty")
                self.assertEqual(code, 0, err)
                self.assertFalse(os.path.exists(self.owned()), out + err)
                # and the one after that switches nothing
                code, out, err = self.sb.run("sync", "--settings-file", p, assume="alacritty")
                self.assertEqual(code, 0, err)
                self.assertFalse(os.path.exists(self.owned()))
                with open(p, "w") as f:
                    json.dump(obj, f)
                code, out, err = self.sb.run("sync", "--settings-file", p, assume="alacritty")
                self.assertEqual(code, 0, err)


class Rescue(Base):
    """adopt --rescue: state.json and the ring both gone, the appglass files
    still on disk. It saves them into a new ring entry, then records them
    again: the files appglass wrote as its own (remove deletes them), the
    files it edited with their originals (its lines taken out)."""

    def test_rescue_after_the_whole_state_dir_is_gone(self):
        main = self.sb.cfg("alacritty", "alacritty.toml")
        cfg = self.sb.cfg("niri", "config.kdl")
        before = {p: self.sb.read(p) for p in (main, cfg)}
        self.apply()
        code, out, err = self.sb.run("hook", "install")
        self.assertEqual(code, 0, err)
        mat = hook.config_path(self.env)
        shutil.rmtree(self.state_dir)           # state.json, backup/ and the ring
        code, out, err = self.apply(ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("appglass adopt --rescue", err)
        self.assertIn("appglass restore", err)
        marked = {p: self.sb.readb(p) for p in (self.owned(), main, cfg, mat)}
        code, out, err = self.sb.run("adopt", "--rescue", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        # every marked file went into a new ring entry first
        ents = self.entries()
        self.assertEqual(len(ents), 1, ents)
        files = self.manifest(ents[0])["files"]
        for p, data in marked.items():
            self.assertIn(p, files)
            with open(os.path.join(self.ring, ents[0], files[p]["blob"]), "rb") as f:
                self.assertEqual(f.read(), data)
        self.apply()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, out + err)
        for p, text in before.items():
            self.assertEqual(self.sb.read(p), text, p)
        self.assertFalse(os.path.exists(self.owned()))
        self.assertFalse(os.path.exists(mat) and hook.BEGIN in self.sb.read(mat))
        for dp, dns, fns in os.walk(self.sb.root):
            for fn in fns:
                q = os.path.join(dp, fn)
                if os.path.islink(q):
                    continue
                data = self.sb.readb(q)
                self.assertFalse(core.MARK.search(data), q)
                self.assertNotIn(b'"appglass.kdl"', data, q)
                self.assertNotIn(core.ADOPTED_MARK, data, q)

    def test_rescue_over_an_unreadable_state(self):
        self.apply()
        with open(self.state_json, "w") as f:
            f.write("{garbage")
        code, out, err = self.apply(ok=False)
        self.assertIn("appglass adopt --rescue", err)
        code, out, err = self.sb.run("adopt", "--rescue", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        # the unreadable state.json is kept in the new ring entry
        ent = self.entries()[-1]
        with open(os.path.join(self.ring, ent, "state.json")) as f:
            self.assertEqual(f.read(), "{garbage")
        self.apply()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, out + err)
        self.assertFalse(os.path.exists(self.owned()))

    def test_rescue_needs_a_lost_state(self):
        self.apply()
        code, out, err = self.sb.run("adopt", "--rescue", assume="alacritty")
        self.assertNotEqual(code, 0)
        self.assertIn("nothing to rescue", err)


HAND_UNIT = b"[Unit]\nDescription=my own sync\n[Service]\nExecStart=/usr/bin/true\n"


class RescueHand(unittest.TestCase):
    """adopt --rescue with backup/ still there: the hand files appglass
    adopted (a unit, a retired script, a theme it renders over) and the
    JSON it merged into get their originals back on remove."""

    def setUp(self):
        from fixtures.shimworld import ShimWorld
        from test_vencord import THEME, SETTINGS, OLD_SETTINGS
        self.w = w = ShimWorld()
        res = w.user(".config/discord/app-1.0.10/resources")
        os.makedirs(res)
        for n in ("app.asar", "_app.asar"):
            open(os.path.join(res, n), "w").close()
        w.hand(SETTINGS, OLD_SETTINGS)
        self.script = w.hand(".local/bin/appglass-vencord", "#!/bin/sh\nold\n", 0o755)
        self.theme = w.hand(THEME, "hand theme\n")
        self.unit = w.hand(".config/systemd/user/appglass-sync.service", HAND_UNIT)
        self.sd = os.path.join(w.sb.state, "appglass")

    def tearDown(self):
        self.w.cleanup()

    def run_ok(self, *a):
        code, out, err = self.w.run(*a)
        self.assertEqual(code, 0, out + err)
        return out + err

    def tree(self):
        out = {}
        for dp, dns, fns in os.walk(self.w.sb.root):
            if dp.startswith(self.sd):
                continue
            out[os.path.relpath(dp, self.w.sb.root) + "/"] = None
            for fn in fns:
                q = os.path.join(dp, fn)
                with open(q, "rb") as f:
                    out[os.path.relpath(q, self.w.sb.root)] = (f.read(), os.stat(q).st_mode)
        return out

    def adopt_apply_lose(self, whole):
        before = self.tree()
        self.run_ok("set", "apps.vencord.enabled", "true")
        self.run_ok("adopt")
        self.run_ok("apply", "--only", "vencord")
        self.assertFalse(os.path.exists(self.script))
        if whole:
            shutil.rmtree(self.sd)
        else:
            os.remove(os.path.join(self.sd, "state.json"))
        return before

    def test_rescue_with_backup_gives_every_original_back(self):
        before = self.adopt_apply_lose(False)
        out = self.run_ok("adopt", "--rescue")
        self.run_ok("apply", "--only", "vencord")
        out += self.run_ok("remove")
        after = self.tree()
        diff = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        self.assertEqual(diff, [], out)

    def test_rescue_without_the_state_dir_leaves_no_appglass_file(self):
        self.adopt_apply_lose(True)
        out = self.run_ok("adopt", "--rescue")
        self.run_ok("apply", "--only", "vencord")
        out += self.run_ok("remove")
        for dp, dns, fns in os.walk(self.w.sb.root):
            for fn in fns:
                q = os.path.join(dp, fn)
                if os.path.islink(q) or "/usr/" in q:
                    continue
                with open(q, "rb") as f:
                    data = f.read()
                self.assertFalse(core.MARK.search(data), q)
                self.assertNotIn(b"@name appGlass", data, q)


class LookalikeLine(Base):
    """A user's own comment that starts like appglass's commented-out line
    is not appglass's edit: a fresh install applies, and remove gives the
    file back as it was."""

    def setUp(self):
        super().setUp()
        self.main = self.sb.cfg("alacritty", "alacritty.toml")
        with open(self.main, "a") as f:
            f.write("# appglass-off: my own note\n")
        self.text = self.sb.read(self.main)

    def test_fresh_install_applies_and_removes(self):
        code, out, err = self.apply(ok=False)
        self.assertEqual(code, 0, err)
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(self.main), self.text)

    def test_rescue_finds_nothing(self):
        code, out, err = self.sb.run("adopt", "--rescue", assume="alacritty")
        self.assertNotEqual(code, 0)
        self.assertIn("nothing to rescue", err)
        self.assertEqual(self.sb.read(self.main), self.text)


class Hints(Base):
    def test_the_hint_names_only_what_works(self):
        self.apply()
        os.remove(self.state_json)
        code, out, err = self.apply(ok=False)
        self.assertNotIn("appglass adopt <file>", err)
        self.assertIn("appglass doctor", err)
        self.assertIn("appglass adopt --rescue", err)
        code, out, err = self.sb.run("adopt", self.owned())
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
