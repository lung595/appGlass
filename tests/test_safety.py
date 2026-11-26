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
import unittest.mock

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
            core._engine_plan(app)
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


class UserLinkOverOwned(Base):
    """A file appglass created, replaced since by a link of yours (to a
    dotfiles folder): remove leaves the link and what it points to."""

    def test_remove_keeps_a_link_you_put_over_a_created_file(self):
        self.apply()
        mine = os.path.join(self.sb.home, "dotfiles", "appglass.toml")
        os.makedirs(os.path.dirname(mine))
        with open(mine, "w") as f:
            f.write("# mine\n")
        os.remove(self.owned())
        os.symlink(mine, self.owned())
        code, out, err = self.sb.run("remove", assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.islink(self.owned()))
        self.assertEqual(os.readlink(self.owned()), mine)
        self.assertEqual(self.sb.read(mine), "# mine\n")
        self.assertIn("is a link now", err)

    def _link_over_owned(self):
        self.apply()
        mine = os.path.join(self.sb.home, "dotfiles", "appglass.toml")
        os.makedirs(os.path.dirname(mine))
        shutil.move(self.owned(), mine)
        os.symlink(mine, self.owned())
        data = self.sb.readb(mine)
        self.sb.seed_dms(light=True)       # the colours change after the link
        return mine, data

    def _assert_link_kept(self, mine, data):
        self.assertTrue(os.path.islink(self.owned()))
        self.assertEqual(os.readlink(self.owned()), mine)
        self.assertEqual(self.sb.readb(mine), data)
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.owned()))
                          if "appglass-changed" in n], [])

    def test_apply_and_hook_runs_leave_a_link_you_put_over_a_created_file(self):
        mine, data = self._link_over_owned()
        code, out, err = self.sb.run("apply", "--from-hook", assume="alacritty")
        self.assertEqual(code, 0, err)
        self._assert_link_kept(mine, data)
        code, out, err = self.apply()
        self._assert_link_kept(mine, data)
        self.assertIn("is a link now", err)
        code, out, err = self.sb.run("apply", "--only", "alacritty", "--dry-run",
                                     assume="alacritty")
        self.assertNotIn(self.env.tilde(self.owned()), out)
        code, out, err = self.sb.run("remove", assume="alacritty")
        self.assertEqual(code, 0, err)
        self._assert_link_kept(mine, data)

    def test_restore_leaves_a_link_you_put_over_a_created_file(self):
        # the pre-apply entry (the file was absent), with or without state.json
        for drop_state in (False, True):
            with self.subTest(drop_state=drop_state):
                self.tearDown()
                self.setUp()
                mine, data = self._link_over_owned()
                first = self.entries()[0]
                if drop_state:
                    os.remove(self.state_json)
                code, out, err = self.sb.run("restore", first, assume="alacritty")
                self.assertEqual(code, 0, err)
                self.assertTrue(os.path.islink(self.owned()))
                self.assertEqual(os.readlink(self.owned()), mine)
                self.assertEqual(self.sb.readb(mine), data)
                self.assertIn("is a link now", err)

    def test_restore_of_a_newer_entry_leaves_the_link_too(self):
        self.apply()
        code, out, err = self.sb.run("set", "levels.content", "0.7", "--apply",
                                     assume="alacritty")
        self.assertEqual(code, 0, err)
        mine = os.path.join(self.sb.home, "dotfiles", "appglass.toml")
        os.makedirs(os.path.dirname(mine))
        shutil.move(self.owned(), mine)
        os.symlink(mine, self.owned())
        with open(mine, "ab") as f:
            f.write(b"# my tweak\n")
        data = self.sb.readb(mine)
        code, out, err = self.sb.run("restore", assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.islink(self.owned()))
        self.assertEqual(self.sb.readb(mine), data)
        self.assertIn("is a link now", err)
        code, out, err = self.sb.run("remove", assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.islink(self.owned()))
        self.assertEqual(self.sb.readb(mine), data)

    def test_doctor_does_not_report_a_link_you_put_over_a_created_file(self):
        mine, data = self._link_over_owned()
        with open(mine, "ab") as f:
            f.write(b"# my tweak\n")
        code, out, err = self.sb.run("doctor", assume="alacritty")
        self.assertNotIn(self.env.tilde(self.owned()), out + err)


class HandEditOfOwned(Base):
    """A file appglass owns whole, edited by hand since apply: the next
    apply (or hook run) writes it again, the hand version saved beside it
    first, as doctor --fix does."""

    def test_apply_saves_a_hand_edit_aside(self):
        self.apply()
        render = self.sb.readb(self.owned())
        with open(self.owned(), "ab") as f:
            f.write(b"# my tweak\n")
        mine = self.sb.readb(self.owned())
        code, out, err = self.apply()
        self.assertEqual(self.sb.readb(self.owned()), render)
        self.assertEqual(self.sb.readb(self.owned() + ".appglass-changed"), mine)
        self.assertIn("your version saved as", err)
        # once: the next run finds its own bytes again
        self.apply()
        self.assertFalse(os.path.exists(self.owned() + ".appglass-changed.1"))

    def test_doctor_fix_saves_a_hand_edit_once(self):
        self.apply()
        with open(self.owned(), "ab") as f:
            f.write(b"# my tweak\n")
        mine = self.sb.readb(self.owned())
        code, out, err = self.sb.run("doctor", "--fix", assume="alacritty")
        self.assertEqual(self.sb.readb(self.owned() + ".appglass-changed"), mine)
        self.assertFalse(os.path.exists(self.owned() + ".appglass-changed.1"), err)
        self.assertEqual(err.count("your version saved as"), 1, err)

    def test_a_hand_edit_of_settings_is_no_aside(self):
        self.assertEqual(self.sb.run("set", "fallback.mode", "off")[0], 0)
        sp = self.sb.cfg("appglass", "settings.json")
        obj = json.loads(self.sb.read(sp))
        obj["fallback"]["value"] = 0.75
        with open(sp, "w") as f:
            json.dump(obj, f)
        code, out, err = self.sb.run("set", "fallback.mode", "value")
        self.assertEqual(code, 0, err)
        self.assertNotIn("written again", err)
        self.assertEqual(json.loads(self.sb.read(sp))["fallback"]["value"], 0.75)
        self.assertFalse(os.path.exists(sp + ".appglass-changed"))
        self.assertEqual(self.sb.run("remove")[0], 0)
        self.assertFalse(os.path.lexists(sp + ".appglass-changed"))


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

    def test_remove_refuses_after_the_whole_state_dir_is_gone(self):
        # no state.json, no ring, no backup/: the marked files are the only
        # trace, and remove (full or --only) writes nothing, cache included
        self.apply()
        cache = os.path.join(self.sb.cache, "appglass")
        os.makedirs(cache, exist_ok=True)
        with open(os.path.join(cache, "keep"), "w") as f:
            f.write("x")
        shutil.rmtree(self.state_dir)
        os.makedirs(os.path.join(self.state_dir, "ring"))
        os.makedirs(os.path.join(self.state_dir, "backup"))
        # the core lock is the one file a refusal leaves (as apply's does:
        # unlinking a lock another run may hold would break the flock)
        lock = os.path.join(self.state_dir, ".lock")
        open(lock, "w").close()
        before = self.sb.tree_hash()
        for argv in (("remove",), ("remove", "--only", "alacritty")):
            with self.subTest(argv=argv):
                code, out, err = self.sb.run(*argv, assume="alacritty")
                self.assertEqual(code, 1, out + err)
                self.assertIn(self.env.tilde(self.owned()), err)
                self.assertIn("adopt --rescue", err)
                self.assertEqual(self.sb.tree_hash(), before)

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


class RestoreThroughALink(Base):
    """w2 r2 B/C: a config file that is a symlink into dotfiles (stow):
    apply edits it through the link, so the ring holds the bytes behind the
    link and restore puts them back there."""

    def dotfiles(self, rels):
        dots = os.path.join(self.sb.home, "dotfiles")
        os.makedirs(dots)
        for rel in rels:
            src = self.sb.cfg(rel)
            dst = os.path.join(dots, os.path.basename(rel))
            shutil.move(src, dst)
            os.symlink(dst, src)
        return dots

    def test_restore_oldest_undoes_the_edits_behind_the_links(self):
        dots = self.dotfiles(("alacritty/alacritty.toml", "niri/config.kdl"))
        before = self.sb.tree_hash(dots)
        self.apply()
        self.assertNotEqual(self.sb.tree_hash(dots), before)
        self.sb.set_level(0.5)
        self.apply()
        code, out, err = self.sb.run("restore", self.entries()[0])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.tree_hash(dots), before)
        for rel in ("alacritty/alacritty.toml", "niri/config.kdl"):
            self.assertTrue(os.path.islink(self.sb.cfg(rel)), rel)
        for argv in (("doctor",), ("apply", "--only", "alacritty"), ("remove",)):
            code, out, err = self.sb.run(*argv, assume="alacritty")
            self.assertEqual(code, 0, (argv, out + err))
        self.assertEqual(self.sb.tree_hash(dots), before)

    def test_restore_newest_after_a_lost_state_json(self):
        dots = self.dotfiles(("alacritty/alacritty.toml", "niri/config.kdl"))
        before = self.sb.tree_hash(dots)
        self.apply()
        os.remove(self.state_json)
        code, out, err = self.sb.run("restore")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.tree_hash(dots), before)
        code, out, err = self.sb.run("remove", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.tree_hash(dots), before)

    def test_a_dux_file_behind_a_link_keeps_the_users_values(self):
        mine = (b'{\n    "floatingWindowTransparency": 0.9,\n    "blurEnabled": false,\n'
                b'    "sidebarWidth": 240\n}')
        dots = os.path.join(self.sb.home, "dotfiles")
        os.makedirs(dots)
        with open(os.path.join(dots, "ui-settings.json"), "wb") as f:
            f.write(mine)
        p = self.sb.cfg("dfiles", "ui-settings.json")
        os.makedirs(os.path.dirname(p))
        os.symlink(os.path.join(dots, "ui-settings.json"), p)
        for lose in (False, True):
            with self.subTest(lose=lose):
                code, out, err = self.sb.run("apply", "--only", "dux", assume="dux")
                self.assertEqual(code, 0, out + err)
                self.assertNotEqual(self.sb.readb(p), mine)
                if lose:
                    os.remove(self.state_json)
                code, out, err = self.sb.run("restore", assume="dux")
                self.assertEqual(code, 0, out + err)
                self.assertEqual(self.sb.readb(p), mine, out + err)
                code, out, err = self.sb.run("apply", "--only", "dux", assume="dux")
                self.assertEqual(code, 0, out + err)
                code, out, err = self.sb.run("remove", assume="dux")
                self.assertEqual(code, 0, out + err)
                self.assertEqual(self.sb.readb(p), mine, out + err)
                self.assertTrue(os.path.islink(p))

    def test_restore_keeps_an_original_it_did_not_put_back(self):
        # an entry that cannot give a file back (its record taken out): the
        # original in backup/ stays, and the state folder with it
        main = self.sb.cfg("alacritty", "alacritty.toml")
        mine = self.sb.readb(main)
        self.apply()
        first = self.entries()[0]
        mp = os.path.join(self.ring, first, "manifest.json")
        m = self.manifest(first)
        del m["files"][main]
        with open(mp, "w") as f:
            json.dump(m, f)
        code, out, err = self.sb.run("restore", first)
        self.assertEqual(code, 0, out + err)
        self.assertIn(self.env.tilde(main), out + err)
        bdir = os.path.join(self.state_dir, "backup")
        self.assertIn(mine, [self.sb.readb(os.path.join(bdir, n)) for n in os.listdir(bdir)])
        # no state.json before that entry: the rescue records the edit
        # again from that original, remove takes it out
        for argv in (("adopt", "--rescue"), ("remove",)):
            code, out, err = self.sb.run(*argv)
            self.assertEqual(code, 0, (argv, out + err))
        self.assertEqual(self.sb.readb(main), mine)
        self.assertFalse(os.path.exists(self.state_dir))


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

    def test_fix_saves_an_edited_hook_section_aside(self):
        self.assertEqual(self.sb.run("hook", "install")[0], 0)
        cfg = hook.config_path(self.env)
        text = self.sb.read(cfg).replace(hook.HOOK_ARGS, hook.HOOK_ARGS + " --my-flag")
        with open(cfg, "w") as f:
            f.write(text)
        code, out, err = self.doctor()
        self.assertEqual(code, 1, out + err)
        self.assertIn("config.toml", out)
        code, out, err = self.doctor("--fix")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("--my-flag", self.sb.read(cfg))
        self.assertEqual(self.sb.read(cfg + ".appglass-changed"), text)
        self.assertIn("config.toml.appglass-changed", err)

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

    def test_an_event_save_cannot_drop_a_record(self):
        self.apply()
        for name, drop in (
                ("a file", lambda st: st.owners["alacritty"]["files"].clear()),
                ("an owner", lambda st: st.owners.pop("alacritty")),
                ("every owner", lambda st: st.data.update(owners={}))):
            with self.subTest(name):
                app = core.App(self.sb.env, out=io.StringIO(), err=io.StringIO())
                app.event = True
                drop(app.state)
                with self.assertRaises(core.EventRemove):
                    app.state.save()
                with open(self.state_json) as f:
                    self.assertIn(self.owned(),
                                  json.load(f)["owners"]["alacritty"]["files"])
        # the user's own switch may, and a later event save keeps what it saved
        app = core.App(self.sb.env, out=io.StringIO(), err=io.StringIO())
        app.event = True
        with app.user_action():
            app.state.owners["alacritty"]["files"].clear()
            app.state.save()
        app.state.save()

    def test_an_event_save_cannot_change_what_a_record_owes(self):
        # what remove needs to give a file back: its kind and how, its
        # backup and the original's sha, adopted. A record that keeps its
        # key but loses one (a dropped backup: a later remove had no
        # original) is a forget too
        self.apply()
        p = self.owned()
        app = core.App(self.sb.env, out=io.StringIO(), err=io.StringIO())
        app.state.owners["alacritty"]["files"][p].update(
            kind="modified", how="edit", backup="backup/x.toml", orig_sha256="0" * 64,
            adopted=True)
        app.state.save()
        for name, change in (
                ("the backup dropped", lambda r: r.pop("backup")),
                ("the backup renamed", lambda r: r.update(backup="backup/y.toml")),
                ("modified made created", lambda r: r.update(kind="created")),
                ("edit made owned", lambda r: r.update(how="owned")),
                ("another original", lambda r: r.update(orig_sha256="1" * 64)),
                ("no longer adopted", lambda r: r.pop("adopted")),
                ("a record put new", lambda r: (r.clear(), r.update(kind="created", how="owned")))):
            with self.subTest(name):
                ev = core.App(self.sb.env, out=io.StringIO(), err=io.StringIO())
                ev.event = True
                change(ev.state.owners["alacritty"]["files"][p])
                with self.assertRaises(core.EventRemove):
                    ev.state.save()
                with open(self.state_json) as f:
                    rec = json.load(f)["owners"]["alacritty"]["files"][p]
                self.assertEqual((rec["kind"], rec["how"], rec["backup"], rec["orig_sha256"],
                                  rec["adopted"]),
                                 ("modified", "edit", "backup/x.toml", "0" * 64, True))
        # the rest of a record is the event's to write (its sha, a mark)
        ev = core.App(self.sb.env, out=io.StringIO(), err=io.StringIO())
        ev.event = True
        ev.state.owners["alacritty"]["files"][p].update(sha256="2" * 64, unplanned=True)
        ev.state.save()
        # and the user's own switch may change it
        with ev.user_action():
            ev.state.owners["alacritty"]["files"][p].pop("backup")
            ev.state.save()
        ev.state.save()

    def test_an_event_run_cannot_restore_or_rescue(self):
        self.apply()
        app = core.App(self.sb.env, out=io.StringIO(), err=io.StringIO())
        app.event = True
        for name, fn in (("cmd_restore", lambda: core.cmd_restore(app)),
                         ("cmd_rescue", lambda: core.cmd_rescue(app))):
            with self.subTest(name):
                with self.assertRaises(core.EventRemove):
                    fn()

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

    def test_a_start_sync_switches_nothing(self):
        # the plugin's start sync (--no-switch) hands its stored data, which
        # may have drifted from settings.json (a restore, a hand edit): it
        # saves the settings and takes nothing out
        self.apply()
        code, out, err = self.sb.run("get")
        obj = json.loads(out)
        p = self.sb.path("plugin-settings.json")
        for name, drift in (("a family off", dict(obj, apps={"alacritty": {"enabled": False}})),
                            ("glass off", dict(obj, enabled=False))):
            with self.subTest(name):
                with open(p, "w") as f:
                    json.dump(drift, f)
                code, out, err = self.sb.run("sync", "--no-switch", "--settings-file", p,
                                             assume="alacritty")
                self.assertEqual(code, 0, err)
                self.assertTrue(os.path.exists(self.owned()), out + err)
                self.assertIn("not a switch", out + err)
                with open(p, "w") as f:
                    json.dump(obj, f)
                code, out, err = self.sb.run("sync", "--settings-file", p, assume="alacritty")
                self.assertEqual(code, 0, err)
                self.assertTrue(os.path.exists(self.owned()))

    def test_a_start_sync_finishes_a_switch_that_failed(self):
        # a switch whose sync failed (sync_pending kept) is the user's: the
        # start sync after it still takes the family out
        from unittest import mock
        self.apply()
        code, out, err = self.sb.run("get")
        obj = json.loads(out)
        p = self.sb.path("plugin-settings.json")
        with open(p, "w") as f:
            json.dump(dict(obj, apps={"alacritty": {"enabled": False}}), f)

        def boom(*a, **k):
            raise core.AppglassError("interrupted")
        with mock.patch.object(core, "cmd_apply_all", boom):
            code, out, err = self.sb.run("sync", "--settings-file", p, assume="alacritty")
        self.assertNotEqual(code, 0)
        code, out, err = self.sb.run("sync", "--no-switch", "--settings-file", p,
                                     assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.owned()), out + err)

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


class RescueXdgOutsideHome(Base):
    """The XDG dirs outside HOME (a test session, a custom layout): the
    dirs appglass made there go with remove after a rescue too."""

    def setUp(self):
        self.sb = Sandbox()
        xdg = os.path.join(self.sb.root, "xdg")
        for attr, var in (("config", "XDG_CONFIG_HOME"), ("data", "XDG_DATA_HOME"),
                          ("state", "XDG_STATE_HOME"), ("cache", "XDG_CACHE_HOME")):
            d = os.path.join(xdg, attr)
            os.makedirs(d)
            setattr(self.sb, attr, d)
            self.sb.env[var] = d
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        self.env = core.Env(self.sb.env)
        self.state_dir = os.path.join(self.sb.state, "appglass")

    def test_rescue_then_remove_leaves_no_dir_appglass_made(self):
        units = os.path.join(self.sb.config, "systemd")
        self.assertFalse(os.path.exists(units))
        self.apply()
        code, out, err = self.sb.run("hook", "install")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isdir(units))
        shutil.rmtree(self.state_dir)
        code, out, err = self.sb.run("adopt", "--rescue", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, out + err)
        self.assertFalse(os.path.exists(units), os.listdir(self.sb.config))
        # the base dirs themselves stay
        self.assertTrue(os.path.isdir(self.sb.config))


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

    def test_rescue_keeps_the_last_state_the_ring_can_restore(self):
        # the oldest entry holds the last state.json (the newer ones were
        # made with the state already lost): the rescue's own entry pushes
        # the ring past RING_KEEP, and the prune must not take that one
        self.apply()
        shutil.rmtree(self.ring)

        def entry(name, seq, state):
            d = os.path.join(self.ring, name)
            os.makedirs(d)
            if state:
                shutil.copy(self.state_json, os.path.join(d, "state.json"))
            with open(os.path.join(d, "manifest.json"), "w") as f:
                json.dump({"created": "2026-01-01T00:00:00", "files": {}, "state": state,
                           "seq": seq}, f)
        entry("20260101-000000-000000", 1, True)
        for i in range(core.RING_KEEP):
            entry("20260102-000000-00000%d" % i, 2 + i, False)
        with open(self.state_json, "rb") as f:
            saved = f.read()
        os.remove(self.state_json)
        code, out, err = self.sb.run("adopt", "--rescue", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        ents = self.entries()
        self.assertIn("20260101-000000-000000", ents)
        with open(os.path.join(self.ring, "20260101-000000-000000", "state.json"), "rb") as f:
            self.assertEqual(f.read(), saved)
        self.assertEqual(len(ents), core.RING_KEEP, ents)

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


class Stop(BaseException):
    """A kill: no except clause catches it."""


class InterruptedRemove(Base):
    """A remove stopped between any two of its steps (a SIGTERM, a DMS
    restart) is finished by the next remove: the tree ends byte-identical
    to the one before apply."""

    ASSUME = "alacritty"

    def cut(self, where, k, applied):
        # the applied tree back in place (one apply for every cut)
        shutil.rmtree(self.sb.root)
        shutil.copytree(applied, self.sb.root, symlinks=True)
        real = getattr(core.App, where)
        n = [0]

        def wrapped(app, *a, **kw):
            r = real(app, *a, **kw)
            n[0] += 1
            if n[0] == k:
                raise Stop()
            return r
        hit = False
        with unittest.mock.patch.object(core.App, where, wrapped):
            try:
                self.sb.run("remove", assume=self.ASSUME)
            except Stop:
                hit = True
        code, out, err = self.sb.run("remove", assume=self.ASSUME)
        return hit, code, out + err

    def test_a_remove_cut_at_any_step_is_finished_by_the_next(self):
        before = self.sb.tree_hash()
        self.apply()
        code, out, err = self.sb.run("hook", "install", assume=self.ASSUME)
        self.assertEqual(code, 0, err)
        applied = self.sb.root.rstrip(os.sep) + ".applied"
        shutil.copytree(self.sb.root, applied, symlinks=True)
        self.addCleanup(shutil.rmtree, applied, True)
        # after each file put back, and after each backup dropped (before
        # the state saved without its record)
        for where in ("_revert", "_drop_backup"):
            k = 1
            while True:
                hit, code, msg = self.cut(where, k, applied)
                if not hit:
                    break
                with self.subTest(where=where, k=k):
                    self.assertEqual(code, 0, msg)
                    self.assertNotIn("is missing", msg)
                    self.assertEqual(self.sb.tree_hash(), before, msg)
                k += 1
            self.assertGreater(k, 2, where)

    def test_a_record_already_back_to_its_original_needs_no_backup(self):
        main = self.sb.cfg("alacritty", "alacritty.toml")
        text = self.sb.readb(main)
        self.apply()
        with open(self.state_json) as f:
            rec = json.load(f)["owners"]["alacritty"]["files"][main]
        # a remove cut after it put the original back and dropped the backup
        with open(main, "wb") as f:
            f.write(text)
        os.remove(os.path.join(self.state_dir, rec["backup"]))
        code, out, err = self.sb.run("doctor")
        self.assertIn(self.env.tilde(main), out + err)
        self.assertIn("appglass remove finishes it", out + err)
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.readb(main), text)
        self.assertFalse(os.path.exists(self.state_dir))


class InterruptedApply(Base):
    """An apply stopped just before or just after any write of a user file
    or folder, or after a backup (a SIGTERM at logout, a unit stop: no handler, so it
    is a kill): every file it touches is recorded first, so the next remove
    gives the tree back byte for byte, and so does an apply then a remove."""

    ASSUME = "alacritty,dux"
    WRITES = ("_inplace_write", "_atomic_write", "_write_durable")

    def cut(self, k, base, then):
        shutil.rmtree(self.sb.root)
        shutil.copytree(base, self.sb.root, symlinks=True)
        n = [0]

        def wrap(fn, where=core):
            real = getattr(where, fn)

            def wrapped(path, *a, **kw):
                state = path.startswith(self.state_dir + os.sep)
                if state and not (fn == "_write_durable" and path.endswith(".orig")):
                    return real(path, *a, **kw)
                if not state:
                    n[0] += 1
                    if n[0] == k:
                        raise Stop()   # before the write
                r = real(path, *a, **kw)
                n[0] += 1
                if n[0] == k:
                    raise Stop()       # after it
                return r
            return unittest.mock.patch.object(where, fn, wrapped)
        hit = False
        with wrap(self.WRITES[0]), wrap(self.WRITES[1]), wrap(self.WRITES[2]), \
                wrap("mkdir", core.os):
            try:
                self.sb.run("apply", "--only", self.ASSUME, assume=self.ASSUME)
            except Stop:
                hit = True
        if hit:
            for argv in then:
                code, out, err = self.sb.run(*argv, assume=self.ASSUME)
                self.assertEqual(code, 0, "%s: %s" % (argv, out + err))
        return hit

    def every_cut(self, then):
        before = self.sb.tree_hash()
        base = self.sb.root.rstrip(os.sep) + ".base"
        shutil.copytree(self.sb.root, base, symlinks=True)
        self.addCleanup(shutil.rmtree, base, True)
        k = 1
        while True:
            with self.subTest(k=k):
                hit = self.cut(k, base, then)
                if hit:
                    self.assertEqual(self.sb.tree_hash(), before)
            if not hit:
                break
            k += 1
        self.assertGreater(k, 8)

    def test_an_apply_cut_at_any_write_is_undone_by_remove(self):
        # (doctor names what the cut left half done: not checked here)
        self.every_cut([("remove",)])

    def test_an_apply_cut_at_any_write_is_finished_by_the_next(self):
        self.every_cut([("apply", "--only", self.ASSUME), ("doctor",), ("remove",)])

    def test_a_write_that_fails_leaves_no_backup(self):
        """A read-only config: apply fails on it, and leaves no original in
        backup/ that no record names (it would block the next apply and
        keep the state folder after remove)."""
        main = self.sb.cfg("alacritty", "alacritty.toml")
        text = self.sb.readb(main)
        before = self.sb.tree_hash()
        os.chmod(main, 0o444)
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertNotEqual(code, 0)
        os.chmod(main, 0o644)
        with open(main, "ab") as f:
            f.write(b"# mine\n")
        code, out, err = self.sb.run("doctor", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        code, out, err = self.sb.run("remove", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.readb(main), text + b"# mine\n")
        self.assertFalse(os.path.exists(self.state_dir))
        with open(main, "wb") as f:
            f.write(text)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_doctor_names_an_original_no_record_names(self):
        self.apply()
        b = os.path.join(self.state_dir, "backup", "0123456789abcdef.orig")
        with open(b, "wb") as f:
            f.write(b"some original\n")
        code, out, err = self.sb.run("doctor", assume="alacritty")
        self.assertEqual(code, 1, out + err)
        self.assertIn(self.env.tilde(b), out + err)


class MidWrite(Base):
    """A kill inside one write, not between two (the new bytes half on the
    disk, an empty file made, a backup cut short): State.settle reads the
    pending record against the disk, and a file that holds neither its old
    bytes nor its new ones is cut, not the user's edit. remove then gives
    the original back whole (what the cut left saved aside) and deletes a
    file appglass created; the next apply writes it again from the
    original."""

    ASSUME = "alacritty,dux"

    def cut(self, mode, k, base, phase):
        shutil.rmtree(self.sb.root)
        shutil.copytree(base, self.sb.root, symlinks=True)
        n = [0]
        real_inplace, real_durable = core._inplace_write, core._write_durable

        def user(path):
            return not path.startswith(self.state_dir + os.sep)

        def hit(path):
            n[0] += 1
            return n[0] == k

        def inplace(path, data):
            if user(path) and hit(path):
                if mode == "empty":
                    if not os.path.exists(path):
                        open(path, "wb").close()
                else:
                    part = data if mode == "notrunc" else data[:len(data) // 2]
                    with open(path, "r+b" if os.path.exists(path) else "wb") as f:
                        f.write(part)
                raise Stop()
            return real_inplace(path, data)

        def durable(path, data):
            if mode == "orig" and path.endswith(".orig") and hit(path):
                with open(path, "wb") as f:
                    f.write(data[:len(data) // 3])
                raise Stop()
            return real_durable(path, data)
        hit_ = False
        with unittest.mock.patch.object(core, "_inplace_write", inplace), \
                unittest.mock.patch.object(core, "_write_durable", durable):
            try:
                if phase == "apply":
                    self.sb.run("apply", "--only", self.ASSUME, assume=self.ASSUME)
                else:
                    self.sb.run("remove", assume=self.ASSUME)
            except Stop:
                hit_ = True
        return hit_

    def asides(self):
        # (a folder appglass made stays while it holds a saved copy: it goes
        # with the copy here)
        out = [f for f in self.sb.files() if ".appglass-changed" in f]
        for f in out:
            os.remove(self.sb.path(f))
            d = os.path.dirname(self.sb.path(f))
            while d != self.sb.root.rstrip(os.sep) and not os.listdir(d):
                os.rmdir(d)
                d = os.path.dirname(d)
        return out

    def every_cut(self, phase, then):
        before = self.sb.tree_hash()
        if phase == "remove":
            code, out, err = self.sb.run("apply", "--only", self.ASSUME, assume=self.ASSUME)
            self.assertEqual(code, 0, out + err)
        base = self.sb.root.rstrip(os.sep) + ".base"
        shutil.copytree(self.sb.root, base, symlinks=True)
        self.addCleanup(shutil.rmtree, base, True)
        hits = 0
        for mode in (("half", "notrunc", "empty", "orig") if phase == "apply"
                     else ("half", "notrunc")):
            k = 1
            while self.cut(mode, k, base, phase):
                hits += 1
                with self.subTest(mode=mode, k=k):
                    for argv in then:
                        code, out, err = self.sb.run(*argv, assume=self.ASSUME)
                        self.assertEqual(code, 0, "%s: %s" % (argv, out + err))
                    self.asides()
                    self.assertEqual(self.sb.tree_hash(), before)
                    self.assertFalse(os.path.exists(self.state_dir))
                k += 1
        self.assertGreaterEqual(hits, 4)

    def test_an_apply_cut_inside_a_write_is_undone_by_remove(self):
        self.every_cut("apply", [("remove",)])

    def test_an_apply_cut_inside_a_write_is_finished_by_the_next(self):
        self.every_cut("apply", [("apply", "--only", self.ASSUME), ("remove",)])

    def test_a_remove_cut_inside_a_write_is_finished_by_the_next(self):
        self.every_cut("remove", [("remove",)])

    def test_doctor_names_a_cut_file_and_remove_sets_it_aside(self):
        main = self.sb.cfg("alacritty", "alacritty.toml")
        text = self.sb.readb(main)
        base = self.sb.root.rstrip(os.sep) + ".base"
        shutil.copytree(self.sb.root, base, symlinks=True)
        self.addCleanup(shutil.rmtree, base, True)
        k = 1
        while self.cut("half", k, base, "apply"):
            if self.sb.readb(main) != text:
                break
            k += 1
        cut = self.sb.readb(main)
        self.assertNotEqual(cut, text)
        code, out, err = self.sb.run("doctor", assume=self.ASSUME)
        self.assertEqual(code, 1, out + err)
        self.assertIn("%s was cut" % self.env.tilde(main), out + err)
        code, out, err = self.sb.run("remove", assume=self.ASSUME)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.readb(main), text)
        self.assertEqual(self.sb.readb(main + ".appglass-changed"), cut)

    def test_a_hand_edit_of_a_cut_created_file_is_saved_aside(self):
        """A file appglass created, cut half way by a kill, then edited by
        hand before the next run: remove deletes it, but the bytes it held
        (the user's edit among them) are saved aside first."""
        base = self.sb.root.rstrip(os.sep) + ".base"
        shutil.copytree(self.sb.root, base, symlinks=True)
        self.addCleanup(shutil.rmtree, base, True)
        k, target = 1, None
        while target is None and self.cut("half", k, base, "apply"):
            with open(self.state_json) as f:
                st = json.load(f)
            for o in st["owners"].values():
                for p, r in (o.get("files") or {}).items():
                    if r.get("pending") and r.get("kind") == "created" \
                            and os.path.isfile(p) and os.path.getsize(p):
                        target = p
            k += 1
        self.assertIsNotNone(target, "no cut of a created file")
        edited = self.sb.readb(target) + b"\n# my own line\n"
        with open(target, "wb") as f:
            f.write(edited)
        code, out, err = self.sb.run("remove", assume=self.ASSUME)
        self.assertEqual(code, 0, out + err)
        self.assertFalse(os.path.exists(target))
        self.assertEqual(self.sb.readb(target + ".appglass-changed"), edited)
        self.assertIn(target + ".appglass-changed", out + err)

    def test_a_dir_mkdir_could_not_make_is_not_recorded(self):
        # (a folder appglass makes for a file: dux's ~/.config/dfiles)
        real = core.os.mkdir
        refused = []

        def mkdir(d, *a, **kw):
            d2 = os.path.abspath(d) + os.sep
            if not d2.startswith(self.state_dir + os.sep):
                refused.append(d)
                raise PermissionError(13, "Permission denied", d)
            return real(d, *a, **kw)
        with unittest.mock.patch.object(core.os, "mkdir", mkdir):
            code, out, err = self.sb.run("apply", "--only", self.ASSUME, assume=self.ASSUME)
        self.assertTrue(refused)
        self.assertNotEqual(code, 0)
        with open(self.state_json) as f:
            st = json.load(f)
        dirs = [d for o in st["owners"].values() for d in o.get("dirs", [])]
        self.assertFalse([d for d in dirs if d in refused], out + err)
        # (one made by hand since is the user's: remove leaves it)
        for d in refused:
            os.makedirs(d, exist_ok=True)
        code, out, err = self.sb.run("remove", assume=self.ASSUME)
        self.assertEqual(code, 0, out + err)
        for d in refused:
            self.assertTrue(os.path.isdir(d), d)


class UninstalledSinceApply(Base):
    """An app uninstalled after apply, then the state lost: its marked
    files still count (the refusal, doctor and adopt --rescue find them),
    and rescue then remove gives the original tree back."""

    def test_a_family_gone_is_still_scanned(self):
        main = self.sb.cfg("alacritty", "alacritty.toml")
        text = self.sb.readb(main)
        self.apply()
        shutil.rmtree(self.state_dir)
        gone = dict(assume="niri", assume_not="alacritty")
        code, out, err = self.sb.run("apply", **gone)
        self.assertNotEqual(code, 0)
        for p in (main, self.owned()):
            self.assertIn(self.env.tilde(p), err)
        code, out, err = self.sb.run("doctor", **gone)
        for p in (main, self.owned()):
            self.assertIn(self.env.tilde(p), out + err)
        code, out, err = self.sb.run("adopt", "--rescue", **gone)
        self.assertEqual(code, 0, out + err)
        with open(self.state_json) as f:
            self.assertIn(main, json.load(f)["owners"].get("alacritty", {}).get("files", {}))
        code, out, err = self.sb.run("remove", **gone)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.readb(main), text)
        self.assertFalse(os.path.exists(self.owned()))
        self.assertFalse(os.path.exists(self.state_dir))


class UninstalledForReal(unittest.TestCase):
    maxDiff = None
    """Apps uninstalled the way a package manager does it (the binary, the
    system launcher and the flatpak gone; ~/.var/app stays), then the state
    lost: the refusal and doctor name every file appglass wrote for them,
    and rescue then remove gives the tree before apply back, but for what
    nothing proves appglass's once the ring is gone (a plain copy of the
    host colours, the DMS import in a gtk.css), which rescue lists and
    leaves."""

    FLATPAKS = (("org.kde.kate", "kate"), ("org.kde.konsole", "konsole"),
                ("org.gnome.TextEditor", "gnome-text-editor"))

    def setUp(self):
        from fixtures.shimworld import ShimWorld
        self.w = w = ShimWorld(bins=("vlc", "solaar"))
        sb = w.sb
        sb.seed("gtk/dank-colors.css", "gtk-3.0/dank-colors.css")
        sb.seed("gtk/dank-colors.css", "gtk-4.0/dank-colors.css")
        desk = "[Desktop Entry]\nType=Application\nName=%s\nExec=%s\n"
        w.launcher("vlc.desktop", desk % ("VLC", os.path.join(w.bin, "vlc") + " %U"))
        w.launcher("solaar.desktop", desk % ("Solaar", "solaar"))
        sb.env["XDG_CONFIG_DIRS"] = sb.path("etc", "xdg")
        sb.write("solaar.desktop", desk % ("Solaar", "solaar --window=hide"),
                 base=sb.path("etc", "xdg", "autostart"))
        for app_id, cmd in self.FLATPAKS:
            w.launcher(app_id + ".desktop", desk % (
                app_id, "/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=%s %s"
                % (cmd, app_id)), flatpak=True)
            d = sb.path("flatpak", "app", app_id, "current", "active")
            os.makedirs(os.path.join(d, "files"))
            sb.write("metadata", "[Application]\nname=%s\nruntime=org.kde.Platform/x86_64/6.11\n"
                     "command=%s\n" % (app_id, cmd), base=d)

    def tearDown(self):
        self.w.cleanup()

    def files(self):
        out = set()
        for dp, dns, fns in os.walk(self.w.sb.home):
            out |= {os.path.join(dp, n) for n in fns}
        return out

    def test_their_files_are_found_and_taken_out(self):
        sb, w = self.w.sb, self.w
        tilde = core.Env(sb.env).tilde
        before = sb.tree_hash(sb.home)
        pre = self.files()
        code, out, err = w.run("apply", "--only", "qtstyle,kate,konsole,gtk3,gtk4")
        self.assertEqual(code, 0, err)
        state = os.path.join(sb.state, "appglass")
        theirs = sorted(p for p in self.files() - pre if not p.startswith(state + os.sep)
                        and not p.startswith(sb.cache + os.sep))
        for part in ("applications/vlc.desktop", "applications/solaar.desktop",
                     "applications/org.kde.kate.desktop", "libappglass.so",
                     "org.kde.kate/config/appglass/katerc", "AppGlass.colorscheme",
                     "org.gnome.TextEditor/config/gtk-4.0/dank-glass.css"):
            self.assertTrue(any(p.endswith(part) for p in theirs), (part, theirs))
        shutil.rmtree(state)
        # the uninstall: binaries, system launchers and flatpaks gone
        shutil.rmtree(w.bin)
        os.makedirs(w.bin)
        shutil.rmtree(os.path.join(w.usr, "share", "applications"))
        shutil.rmtree(sb.path("flatpak"))
        shutil.rmtree(sb.path("etc"))
        # the host colours copied into the flatpak dir: a plain copy of a file
        # appglass reads, with the ring gone nothing says appglass wrote it
        copy = [p for p in theirs if p.endswith("org.gnome.TextEditor/config/gtk-4.0/"
                                                 "dank-colors.css")]
        self.assertEqual(len(copy), 1, theirs)
        theirs = [p for p in theirs if p not in copy]
        code, out, err = w.run("apply")
        self.assertNotEqual(code, 0, err)
        self.assertEqual([p for p in theirs if tilde(p) not in err], [], err)
        code, out, err = w.run("doctor")
        self.assertEqual([p for p in theirs if tilde(p) not in out + err], [], out + err)
        code, out, err = w.run("adopt", "--rescue")
        self.assertEqual(code, 0, out + err)
        self.assertIn(tilde(copy[0]) + " is a copy of a file appglass reads", err)
        self.assertNotIn("recorded " + tilde(copy[0]), out)
        # a gtk.css appglass made from nothing holds DMS's import once its
        # lines are out: with the ring gone that rest may be DMS's, so it
        # is recorded as edited, listed, and stays
        rest = [p for p in theirs if p.endswith("/gtk-4.0/gtk.css")]
        self.assertEqual(len(rest), 2, theirs)
        for p in rest:
            self.assertIn(tilde(p) + " holds what appglass writes from nothing", err)
        code, out, err = w.run("remove")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(sorted(self.files() - pre), sorted(copy + rest))
        for p in rest:
            self.assertEqual(sb.read(p).strip(), '@import url("dank-colors.css");')
        # the user deletes what the rescue listed: the tree before apply is back
        for p in copy + rest:
            os.remove(p)
            try:
                os.removedirs(os.path.dirname(p))
            except OSError:
                pass
        self.assertEqual(sb.tree_hash(sb.home), before)


class Durable(Base):
    """state.json, the ring manifest, the ring blobs and the originals in
    backup/ are on the disk before anything names them (a power loss
    leaves no empty state.json)."""

    def test_each_write_is_synced_before_the_replace(self):
        log = []
        real_fsync, real_replace = os.fsync, os.replace
        with unittest.mock.patch.object(core.os, "fsync",
                                        lambda fd: (log.append(("fsync", fd)), real_fsync(fd))), \
                unittest.mock.patch.object(core.os, "replace",
                                           lambda a, b: (log.append(("replace", b)),
                                                         real_replace(a, b))):
            self.apply()
        replaced = [i for i, (k, _) in enumerate(log) if k == "replace"]
        names = {os.path.basename(log[i][1]) for i in replaced}
        self.assertTrue({"state.json", "manifest.json"} <= names, names)
        for i in replaced:
            self.assertGreater(i, 0)
            self.assertEqual(log[i - 1][0], "fsync", log[i][1])
        with open(self.state_json) as f:
            st = json.load(f)
        self.assertTrue(any(r.get("backup") for o in st["owners"].values()
                            for r in o.get("files", {}).values()))
        # one more fsync per backup and blob than per replace
        self.assertGreater(sum(k == "fsync" for k, _ in log), 2 * len(replaced))

    def backed_up(self):
        with open(self.state_json) as f:
            st = json.load(f)
        return [(p, r) for o in st["owners"].values()
                for p, r in o.get("files", {}).items() if r.get("backup")]

    def test_a_damaged_original_is_never_put_back(self):
        """An original in backup/ that is not the bytes state.json recorded
        (a disk error, a hand edit): remove gives nothing back from it and
        doctor names it."""
        self.apply()
        p, rec = self.backed_up()[0]
        b = os.path.join(self.state_dir, rec["backup"])
        with open(b, "wb") as f:
            f.write(b"not the original\n")
        before = self.sb.readb(p)
        code, out, err = self.sb.run("remove")
        self.assertNotEqual(code, 0)
        self.assertIn("does not match", err)
        self.assertEqual(self.sb.readb(p), before)
        code, out, err = self.sb.run("doctor")
        self.assertEqual(code, 1)
        self.assertIn("does not match the original recorded", out + err)

    def test_a_damaged_original_stops_remove_before_anything_goes(self):
        """w2 m3: one damaged original among several: remove checks every
        backup it will need first, and takes nothing out."""
        self.apply()
        recs = self.backed_up()
        self.assertGreater(len(recs), 1)
        p, rec = [(p, r) for p, r in recs if p.endswith("alacritty.toml")][0]
        with open(os.path.join(self.state_dir, rec["backup"]), "wb") as f:
            f.write(b"not the original\n")
        cfg = os.path.dirname(self.sb.cfg("niri"))
        before = self.sb.tree_hash(cfg)
        with open(self.state_json) as f:
            owners = sorted(json.load(f)["owners"])
        code, out, err = self.sb.run("remove", assume="alacritty")
        self.assertEqual(code, 1)
        self.assertIn(self.env.tilde(p), err)
        self.assertIn("nothing removed", err)
        self.assertEqual(self.sb.tree_hash(cfg), before)
        with open(self.state_json) as f:
            self.assertEqual(sorted(json.load(f)["owners"]), owners)

    def test_rescue_and_save_aside_copies_are_synced(self):
        """The originals adopt --rescue writes into backup/ and a version
        saved aside as <file>.appglass-changed are on the disk before the
        file is overwritten or state.json names them."""
        self.apply()
        p, rec = self.backed_up()[0]
        shutil.rmtree(self.state_dir)
        synced = []
        real = core._write_durable
        with unittest.mock.patch.object(core, "_write_durable",
                                        lambda q, d: (synced.append(q), real(q, d))):
            code, out, err = self.sb.run("adopt", "--rescue")
        self.assertEqual(code, 0, err)
        self.assertIn(os.path.join(self.state_dir, "backup", core._bname(p)), synced)
        # doctor --fix re-renders an owned file changed by hand: its version aside
        o = self.owned()
        with open(o, "a") as f:
            f.write("# mine\n")
        synced.clear()
        with unittest.mock.patch.object(core, "_write_durable",
                                        lambda q, d: (synced.append(q), real(q, d))):
            code, out, err = self.sb.run("doctor", "--fix")
        self.assertIn(o + ".appglass-changed", synced)
        self.assertIn("# mine", self.sb.read(o + ".appglass-changed"))


class LinkedStateDir(Base):
    """w2 r3: the state dir is a symlink to a folder of the user's: a full
    remove takes appglass's own names out of that folder and keeps the
    link, the folder and every other file in it. A link to a base folder
    (HOME, an XDG dir, a parent of one, /) or to nothing is refused."""

    def link_to(self, target):
        os.makedirs(self.sb.state, exist_ok=True)
        os.symlink(target, self.state_dir)

    def test_remove_keeps_the_link(self):
        alt = os.path.join(self.sb.home, "elsewhere", "appglass")
        os.makedirs(alt)
        self.link_to(alt)
        before = self.sb.tree_hash()
        self.apply()
        self.assertTrue(os.path.isfile(os.path.join(alt, "state.json")))
        code, out, err = self.sb.run("remove", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        self.assertTrue(os.path.islink(self.state_dir))
        self.assertEqual(os.listdir(alt), [])
        self.assertEqual(self.sb.tree_hash(), before, self.sb.files())

    def test_remove_keeps_user_files_in_the_target(self):
        alt = os.path.join(self.sb.home, "sync", "appglass")
        os.makedirs(os.path.join(alt, "photos"))
        with open(os.path.join(alt, "my-notes.txt"), "w") as f:
            f.write("mine\n")
        with open(os.path.join(alt, "photos", "a.jpg"), "wb") as f:
            f.write(b"\xff\xd8jpg")
        self.link_to(alt)
        before = self.sb.tree_hash()
        self.apply()
        self.assertTrue(os.path.isfile(os.path.join(alt, "state.json")))
        code, out, err = self.sb.run("remove", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        self.assertTrue(os.path.islink(self.state_dir))
        self.assertEqual(sorted(os.listdir(alt)), ["my-notes.txt", "photos"])
        self.assertEqual(self.sb.read(os.path.join(alt, "my-notes.txt")), "mine\n")
        self.assertEqual(self.sb.readb(os.path.join(alt, "photos", "a.jpg")), b"\xff\xd8jpg")
        self.assertEqual(self.sb.tree_hash(), before, self.sb.files())
        self.assertIn("my-notes.txt", err)

    def test_destroy_takes_only_its_own_names(self):
        alt = os.path.join(self.sb.home, "elsewhere")
        os.makedirs(alt)
        self.link_to(alt)
        st = core.State(self.env)
        for n in ("state.json", ".state.json.appglass-tmp", ".lock", "verify.lock",
                  "colors.json", "engine.json", "keep.txt"):
            with open(os.path.join(alt, n), "w") as f:
                f.write("x")
        for n in ("backup", "ring", "plain", "photos"):
            os.makedirs(os.path.join(alt, n))
        self.assertEqual(st.destroy(), [])
        self.assertEqual(sorted(os.listdir(alt)), ["keep.txt", "photos"])
        self.assertEqual(st.left_in_link, ["keep.txt", "photos"])

    def refused(self, *argv):
        code, out, err = self.sb.run(*argv, assume="alacritty")
        self.assertNotEqual(code, 0, out + err)
        self.assertNotIn("Traceback", err)
        return err

    def user_folder(self, names):
        """A folder of the user's that already holds names appglass uses."""
        alt = os.path.join(self.sb.home, "Documents")
        os.makedirs(alt)
        with open(os.path.join(alt, "my-notes.txt"), "w") as f:
            f.write("user notes\n")
        for n in names:
            if "." in n:
                with open(os.path.join(alt, n), "w") as f:
                    f.write('{"mine": 1}\n')
            else:
                os.makedirs(os.path.join(alt, n))
                with open(os.path.join(alt, n, "tax-2025.pdf"), "wb") as f:
                    f.write(b"%PDF user")
        self.link_to(alt)
        return alt

    def test_first_use_of_a_folder_holding_appglass_names_is_refused(self):
        # w2 r2: a user ring/, plain/, backup/, colors.json or state.json in
        # the link target: appglass would read, prune or delete them. The
        # refusal comes before the lock: no .lock is left in that folder
        for names in (("ring",), ("plain",), ("backup",), ("colors.json",),
                      ("state.json",), ("engine.json",)):
            with self.subTest(names=names):
                self.tearDown()
                self.setUp()
                alt = self.user_folder(names)
                before = self.sb.tree_hash()
                err = self.refused("apply", "--only", "alacritty")
                self.assertIn(names[0], err)
                self.assertIn("empty folder", err)
                self.assertEqual(self.sb.tree_hash(), before, self.sb.files())
                self.assertNotIn(".lock", os.listdir(alt))
                self.refused("adopt", "--rescue")
                self.refused("remove")
                self.assertEqual(self.sb.tree_hash(), before, self.sb.files())
                code, out, err = self.sb.run("doctor")
                self.assertIn(names[0], out + err)
                self.assertNotEqual(code, 0)

    def test_a_folder_appglass_used_before_is_taken(self):
        # its .lock (or a readable state.json of appglass's) says the names
        # in it are appglass's own
        alt = os.path.join(self.sb.home, "elsewhere")
        os.makedirs(alt)
        self.link_to(alt)
        self.apply()
        self.assertIn(".lock", os.listdir(alt))
        self.apply()
        os.remove(os.path.join(alt, ".lock"))
        self.apply()
        code, out, err = self.sb.run("remove", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(os.listdir(alt), [])

    def test_remove_keeps_user_entries_inside_its_own_folders(self):
        # a file of the user's put in ring/, backup/ or plain/ after apply:
        # only appglass-shaped entries go (a ring entry with its manifest,
        # a backup <hash>.orig, a plain marker file)
        alt = os.path.join(self.sb.home, "elsewhere")
        os.makedirs(alt)
        self.link_to(alt)
        self.apply()
        for n in ("ring", "backup", "plain"):
            os.makedirs(os.path.join(alt, n, "mine"))
            with open(os.path.join(alt, n, "mine", "tax-2025.pdf"), "wb") as f:
                f.write(b"%PDF user")
        with open(os.path.join(alt, "backup", "notes.txt"), "w") as f:
            f.write("mine\n")
        code, out, err = self.sb.run("remove", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        for n in ("ring", "backup", "plain"):
            self.assertEqual(self.sb.readb(os.path.join(alt, n, "mine", "tax-2025.pdf")),
                             b"%PDF user")
        self.assertEqual(sorted(os.listdir(os.path.join(alt, "ring"))), ["mine"])
        self.assertEqual(sorted(os.listdir(os.path.join(alt, "backup"))), ["mine", "notes.txt"])
        self.assertNotIn("state.json", os.listdir(alt))
        self.assertIn("ring/mine", err)

    def test_engine_json_bad_is_appglass_s(self):
        self.assertTrue(core._state_own_name("engine.json.bad"))

    def test_link_to_home_is_refused(self):
        self.link_to(self.sb.home)
        before = self.sb.tree_hash()
        err = self.refused("apply", "--only", "alacritty")
        self.assertIn("link", err)
        self.assertEqual(self.sb.tree_hash(), before, self.sb.files())
        self.assertFalse(os.path.exists(os.path.join(self.sb.home, "state.json")))

    def test_link_to_an_xdg_parent_is_refused(self):
        self.link_to(os.path.join(self.sb.home, ".local"))
        before = self.sb.tree_hash()
        self.refused("apply", "--only", "alacritty")
        self.assertEqual(self.sb.tree_hash(), before, self.sb.files())

    def test_link_to_root_is_a_problem(self):
        # (no real link to / in a test: the realpath is faked)
        alt = os.path.join(self.sb.home, "elsewhere")
        os.makedirs(alt)
        self.link_to(alt)
        real = os.path.realpath
        fake = lambda p: "/" if os.path.abspath(p) == self.state_dir else real(p)
        with unittest.mock.patch.object(core.os.path, "realpath", fake):
            self.assertIn("base folder", core.state_link_problem(self.env))
            with self.assertRaises(core.AppglassError):
                core.State(self.env).destroy()

    def test_dangling_link_is_refused_and_doctor_says_so(self):
        self.link_to(os.path.join(self.sb.home, "gone"))
        before = self.sb.tree_hash()
        for argv in (("apply", "--only", "alacritty"), ("remove",), ("adopt", "--rescue")):
            err = self.refused(*argv)
            self.assertIn("gone", err)
        self.assertEqual(self.sb.tree_hash(), before, self.sb.files())
        code, out, err = self.sb.run("doctor")
        self.assertIn("gone", out + err)
        self.assertNotIn("no drift", out + err)
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
