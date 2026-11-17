"""Step 0 safety floor: the backup ring, the refusal without state.json,
appglass restore and appglass doctor [--fix]."""

import contextlib
import hashlib
import io
import json
import os
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

    def test_restore_unknown_entry_fails(self):
        self.apply()
        code, out, err = self.sb.run("restore", "nope")
        self.assertNotEqual(code, 0)
        self.assertIn("nope", err)


class Refusal(Base):
    HINT = ("appglass adopt", "appglass restore")

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


if __name__ == "__main__":
    unittest.main()
