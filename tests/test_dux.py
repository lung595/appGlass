"""Dux family (dfiles, dcal): ui-settings.json merges, per-app detection, restore."""

import json
import os
import shutil
import subprocess
import unittest

from fixtures.sandbox import Sandbox
from appglass import core
from appglass.families import dux as fam

KEYS = ("floatingWindowTransparency", "floatingWindowForegroundTransparency",
        "floatingWindowForegroundLayers", "blurEnabled")
DFILES = ("dfiles", "ui-settings.json")
DCAL = ("dankcal", "ui-settings.json")


class Dux(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.seed()

    def seed(self, light=False):
        self.sb.seed_dms(light=light)
        self.sb.seed_niri()
        self.before = self.sb.tree_hash()

    def tearDown(self):
        self.sb.cleanup()

    def apply(self, assume="dux", assume_not=None):
        code, out, err = self.sb.run("apply", "--only", "dux", assume=assume,
                                     assume_not=assume_not)
        self.assertEqual(code, 0, err)
        return out, err

    def remove(self):
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        return out, err

    def settings(self, which):
        return self.sb.json(self.sb.cfg(*which))

    def kdl(self):
        return self.sb.read(self.sb.cfg("niri", "appglass.kdl"))

    # lost state
    def test_rescue_after_the_whole_state_dir_is_gone(self):
        # both files made by apply: with no ring and no backup/, a file that
        # holds only the keys the merge sets is appglass's
        self.apply()
        shutil.rmtree(os.path.join(self.sb.state, "appglass"))
        code, out, err = self.sb.run("adopt", "--rescue", assume="dux")
        self.assertEqual(code, 0, out + err)
        self.assertIn("ui-settings.json", out + err)
        self.remove()
        for which in (DFILES, DCAL):
            self.assertFalse(os.path.exists(self.sb.cfg(*which)), which)

    def test_rescue_keeps_a_file_with_a_key_of_the_user(self):
        p = self.sb.cfg(*DFILES)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write('{"iconTheme": "mine"}\n')
        self.apply()
        shutil.rmtree(os.path.join(self.sb.state, "appglass"))
        code, out, err = self.sb.run("adopt", "--rescue", assume="dux")
        self.assertEqual(code, 0, out + err)
        self.remove()
        self.assertEqual(self.settings(DFILES)["iconTheme"], "mine")
        self.assertFalse(os.path.exists(self.sb.cfg(*DCAL)))

    # content
    def test_content_and_keys(self):
        self.apply()
        f = self.settings(DFILES)
        c = self.settings(DCAL)
        self.assertEqual(sorted(f), sorted(KEYS))
        self.assertEqual(f, {"floatingWindowTransparency": 0.6,
                             "floatingWindowForegroundTransparency": 0.0,
                             "floatingWindowForegroundLayers": True,
                             "blurEnabled": True})
        self.assertEqual(c, dict(f, floatingWindowForegroundTransparency=0.65))
        # themeMode is not set: the apps keep following DMS (auto)
        self.assertNotIn("themeMode", f)
        kdl = self.kdl()
        self.assertIn(r'match app-id=r#"^dev\.duxlabs\.files$"#', kdl)
        self.assertIn(r'match app-id=r#"^dev\.duxlabs\.calendar$"#', kdl)
        self.assertIn("opacity 1.0", kdl)

    def test_window_alpha_follows_dms_setting(self):
        self.sb.set_level(0.75)
        self.apply()
        self.assertEqual(self.settings(DFILES)["floatingWindowTransparency"], 0.75)
        self.assertEqual(self.settings(DCAL)["floatingWindowTransparency"], 0.75)

    def test_default_level_without_setting(self):
        os.remove(self.sb.cfg("dms", "settings.json"))
        self.apply()
        self.assertEqual(self.settings(DFILES)["floatingWindowTransparency"], 0.6)

    def test_layer_raised_when_text_would_fail(self):
        # a very thin window: the panes must carry the text
        self.sb.set_level(0.2)
        out, err = self.apply()
        f = self.settings(DFILES)
        self.assertGreater(f["floatingWindowForegroundTransparency"], 0.0)
        a = fam.stacked(0.2, f["floatingWindowForegroundTransparency"])
        for role in ("#e0e2e8", "#c2c7cf", "#9acbfa"):
            self.assertGreaterEqual(core.worst_contrast(role, "#101418", a), 2.25)
        self.assertIn("header text", err)

    # files
    def test_existing_file_merged_in_place(self):
        p = self.sb.write("dankcal/ui-settings.json",
                          '{"themeMode": "auto", "floatingWindowTransparency": 1.0,\n'
                          ' "weekStart": 1}\n')
        before = self.sb.tree_hash()
        ino = os.stat(p).st_ino
        self.apply()
        self.assertEqual(os.stat(p).st_ino, ino)
        c = self.settings(DCAL)
        self.assertEqual(c["themeMode"], "auto")
        self.assertEqual(c["weekStart"], 1)
        self.assertEqual(c["floatingWindowTransparency"], 0.6)
        self.remove()
        self.assertEqual(os.stat(p).st_ino, ino)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_missing_files_created_and_deleted(self):
        self.assertFalse(os.path.exists(self.sb.cfg("dfiles")))
        self.apply()
        self.assertTrue(os.path.isfile(self.sb.cfg(*DFILES)))
        self.remove()
        self.assertFalse(os.path.exists(self.sb.cfg("dfiles")))
        self.assertFalse(os.path.exists(self.sb.cfg("dankcal")))

    def test_idempotent(self):
        self.apply()
        h1 = self.sb.tree_hash()
        out, _ = self.apply()
        self.assertEqual(self.sb.tree_hash(), h1)
        self.assertIn("dux: up to date", out)

    def test_remove_byte_identical(self):
        self.sb.write("dfiles/bookmarks.json", '[{"path": "/tmp"}]\n')
        self.before = self.sb.tree_hash()
        self.apply()
        self.assertNotEqual(self.sb.tree_hash(), self.before)
        self.remove()
        self.assertEqual(self.sb.tree_hash(), self.before)
        self.assertFalse(os.path.exists(core.Env(self.sb.env).state_dir))

    def test_remove_only_dux(self):
        self.apply()
        code, out, err = self.sb.run("remove", "--only", "dux")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_app_rewrote_file_keeps_its_keys(self):
        p = self.sb.write("dankcal/ui-settings.json", '{"themeMode": "auto"}\n')
        self.apply()
        # the app's Settings page rewrites the file with a new key of its own
        c = self.settings(DCAL)
        c["weekStart"] = 1
        with open(p, "w") as f:
            json.dump(c, f)
        self.remove()
        self.assertEqual(self.sb.json(p), {"themeMode": "auto", "weekStart": 1})

    def test_app_rewrote_then_reapply_then_remove_keeps_its_keys(self):
        p = self.sb.write("dankcal/ui-settings.json", '{"themeMode": "auto"}\n')
        self.apply()
        c = self.settings(DCAL)
        c["weekStart"] = 1
        c["themeMode"] = "dark"
        with open(p, "w") as f:
            json.dump(c, f)
        self.apply()                    # the matugen hook
        self.apply()
        self.remove()
        self.assertEqual(self.sb.json(p), {"themeMode": "dark", "weekStart": 1})

    def test_directory_target_is_conflict(self):
        os.makedirs(self.sb.cfg(*DFILES))
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "dux", assume="dux",
                                     assume_not="dcal")
        self.assertEqual(code, 0, err)
        self.assertIn("not a regular file", err)
        self.assertIn("dux: skipped", err)
        self.assertEqual(self.sb.tree_hash(), before)
        # the other app is still configured
        out, err = self.apply()
        self.assertIn("dfiles skipped", err)
        self.assertEqual(self.settings(DCAL)["floatingWindowTransparency"], 0.6)
        self.remove()
        self.assertEqual(self.sb.tree_hash(), before)

    def test_settings_became_directory_after_apply(self):
        # remove (and the hook) must not crash on a merged file that is now a
        # directory: warn, leave it, keep going with the rest
        self.sb.write("dfiles/ui-settings.json", '{"a": 1}\n')
        self.apply()
        p = self.sb.cfg(*DFILES)
        os.remove(p)
        os.makedirs(p)
        code, out, err = self.sb.run("apply", "--from-hook", "--quiet", assume="dux")
        self.assertEqual(code, 0, err)
        self.assertIn("dfiles skipped", err)
        self.assertTrue(os.path.isdir(p))
        self.assertNotIn("files", self.kdl())                 # dropped from the rule
        self.apply()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertTrue(os.path.isdir(p))
        self.assertFalse(os.path.exists(self.sb.cfg(*DCAL)))
        self.assertFalse(os.path.exists(self.sb.path("home", ".local", "state", "appglass")))

    def test_settings_became_directory_then_remove(self):
        self.apply()
        p = self.sb.cfg(*DFILES)
        os.remove(p)
        os.makedirs(p)
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertIn("no longer a regular file", err)
        self.assertTrue(os.path.isdir(p))
        self.assertFalse(os.path.exists(self.sb.cfg(*DCAL)))
        self.assertFalse(os.path.exists(self.sb.path("home", ".local", "state", "appglass")))

    @unittest.skipIf(os.geteuid() == 0, "root reads mode 000 files")
    def test_unreadable_settings_skips_that_app_only(self):
        p = self.sb.write("dfiles/ui-settings.json", '{"a": 1}\n')
        before = self.sb.tree_hash()
        os.chmod(p, 0)
        try:
            code, out, err = self.sb.run("apply", "--only", "dux", assume="dux")
            self.assertEqual(code, 0, err)
            self.assertIn("dfiles skipped", err)
            self.assertIn("cannot be read", err)
            self.assertEqual(self.settings(DCAL)["floatingWindowTransparency"], 0.6)
            self.assertNotIn("files", self.kdl())
            code, out, err = self.sb.run("remove")
            self.assertEqual(code, 0, err)
        finally:
            os.chmod(p, 0o644)
        self.assertEqual(self.sb.read(p), '{"a": 1}\n')
        self.assertEqual(self.sb.tree_hash(), before)

    # foreign files
    def test_invalid_json_left_alone(self):
        p = self.sb.write("dankcal/ui-settings.json", "{not json\n")
        out, err = self.apply()
        self.assertEqual(self.sb.read(p), "{not json\n")
        self.assertIn("dcal skipped", err)
        # dfiles still done, and only its app-id is in the rule
        self.assertTrue(os.path.isfile(self.sb.cfg(*DFILES)))
        kdl = self.kdl()
        self.assertIn("files", kdl)
        self.assertNotIn("calendar", kdl)

    def test_non_object_json_left_alone(self):
        self.sb.write("dfiles/ui-settings.json", "[1, 2]\n")
        self.sb.write("dankcal/ui-settings.json", '"x"\n')
        before = self.sb.tree_hash()
        out, err = self.apply()
        self.assertIn("dux: skipped", err)
        self.assertEqual(self.sb.tree_hash(), before)
        self.assertFalse(os.path.exists(self.sb.cfg("niri", "appglass.kdl")))

    # install detection
    def test_per_app_detection(self):
        self.apply(assume="dux", assume_not="dfiles")
        self.assertFalse(os.path.exists(self.sb.cfg(*DFILES)))
        self.assertTrue(os.path.isfile(self.sb.cfg(*DCAL)))
        kdl = self.kdl()
        self.assertNotIn("files", kdl)
        self.assertIn("calendar", kdl)
        # dfiles appears later: picked up, rule extended
        self.apply(assume="dux")
        self.assertIn("files", self.kdl())
        # dcal goes away: its file is restored, its rule dropped
        self.apply(assume="dux", assume_not="dcal")
        self.assertFalse(os.path.exists(self.sb.cfg(*DCAL)))
        self.assertNotIn("calendar", self.kdl())
        self.remove()
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_not_installed(self):
        code, out, err = self.sb.run("apply", "--only", "dux", assume_not="dux")
        self.assertIn("not installed", out)
        self.assertEqual(self.sb.tree_hash(), self.before)
        code, out, err = self.sb.run("apply", "--only", "dux", assume_not="dfiles,dcal")
        self.assertIn("not installed", out)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_real_detection(self):
        env = core.Env(dict(self.sb.env, PATH=""))
        self.assertFalse(fam.installed(env))
        env = core.Env(self.sb.env)
        self.assertEqual(fam.installed(env),
                         bool(shutil.which("dfiles") or shutil.which("dcal")))

    def test_dry_run_writes_nothing(self):
        code, out, err = self.sb.run("apply", "--only", "dux", "--dry-run", assume="dux")
        self.assertEqual(code, 0, err)
        self.assertIn("would write", out)
        self.assertEqual(self.sb.tree_hash(), self.before)

    # readability
    def _check_readable(self, surface, roles, on_surface):
        for which, app in ((DFILES, fam.APPS[0]), (DCAL, fam.APPS[1])):
            s = self.settings(which)
            w = s["floatingWindowTransparency"]
            a = fam.stacked(w, s["floatingWindowForegroundTransparency"])
            for r in roles:
                # pane text, and header text straight on the window glass
                self.assertGreaterEqual(core.worst_contrast(r, surface, a), 2.0, (which, r))
                self.assertGreaterEqual(core.worst_contrast(r, surface, w), 2.0, (which, r))
            if app.dim_text:
                self.assertGreaterEqual(fam.dim_contrast(on_surface, surface, a), 2.0)

    def test_dark_readability(self):
        self.apply()
        self._check_readable("#101418", ("#e0e2e8", "#c2c7cf", "#9acbfa"), "#e0e2e8")
        # without the dcal pane layer the dim digits fail (the reason for config B)
        self.assertLess(fam.dim_contrast("#e0e2e8", "#101418", 0.6), 2.0)

    def test_light_mode_readability(self):
        self.sb.cleanup()
        self.sb = Sandbox()
        self.seed(light=True)
        self.apply()
        self._check_readable("#f7f9ff", ("#181c20", "#42474e", "#235a83"), "#181c20")
        self.remove()
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_hook_colours_used(self):
        # the dim-digit check reads the palette through ctx: a palette whose
        # on_surface is close to the surface forces a thicker dcal layer
        env = core.Env(self.sb.env)
        os.makedirs(env.state_dir)
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "dms",
                               "dms-colors.json")) as f:
            cols = json.load(f)["colors"]["dark"]
        cols = dict(cols, on_surface="#9a9ea4")
        with open(os.path.join(env.state_dir, "colors.json"), "w") as f:
            json.dump({"mode": "dark", "colors": cols}, f)
        self.apply()
        f = self.settings(DCAL)["floatingWindowForegroundTransparency"]
        self.assertGreater(f, 0.65)
        a = fam.stacked(0.6, f)
        self.assertGreaterEqual(fam.dim_contrast("#9a9ea4", cols["surface"], a), 2.0)

    # niri
    @unittest.skipUnless(shutil.which("niri"), "niri not installed")
    def test_niri_rule_validates(self):
        self.apply()
        r = subprocess.run(["niri", "validate", "-c", self.sb.cfg("niri", "config.kdl")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = self.sb.read(self.sb.cfg("niri", "config.kdl"))
        i = cfg.index('include "dms/windowrules.kdl"')
        j = cfg.index('include optional=true "appglass.kdl"')
        self.assertLess(i, j)


if __name__ == "__main__":
    unittest.main()
