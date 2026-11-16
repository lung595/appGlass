"""electron-vencord: the Discord theme, Vencord settings, retired hand pieces."""

import json
import os
import unittest

from fixtures.shimworld import ShimWorld

THEME = ".config/Vencord/themes/appglass-discord.css"
SETTINGS = ".config/Vencord/settings/settings.json"
OLD_SETTINGS = '{\n    "autoUpdate": true,\n    "enabledThemes": ["dank-discord.css"]\n}\n'


class Vencord(unittest.TestCase):
    def setUp(self):
        self.w = ShimWorld()
        res = self.w.user(".config/discord/app-1.0.9/resources")
        os.makedirs(res)
        for n in ("app.asar", "_app.asar"):
            open(os.path.join(res, n), "w").close()
        os.makedirs(self.w.user(".config/discord/app-1.0.10/resources"))
        self.newest = self.w.user(".config/discord/app-1.0.10/resources")
        for n in ("app.asar", "_app.asar"):
            open(os.path.join(self.newest, n), "w").close()
        self.w.hand(SETTINGS, OLD_SETTINGS)
        self.before = self.w.sb.tree_hash()

    def tearDown(self):
        self.w.cleanup()

    def run_ok(self, *argv):
        code, out, err = self.w.run(*argv)
        self.assertEqual(code, 0, err)
        return out, err

    def enable(self):
        self.run_ok("set", "apps.vencord.enabled", "true")
        self.before = self.w.sb.tree_hash()

    def niri(self):
        return self.w.sb.read(os.path.join(self.w.sb.config, "niri", "appglass.kdl"))

    def test_off_by_default(self):
        out, err = self.run_ok("apply", "--only", "vencord")
        self.assertIn("vencord: off in settings", out + err)
        self.assertFalse(os.path.exists(self.w.user(THEME)))

    def test_apply_and_remove(self):
        self.enable()
        self.run_ok("apply", "--only", "vencord")
        css = self.w.sb.read(self.w.user(THEME))
        self.assertNotIn("{{", css)
        s = self.w.sb.json(self.w.user(SETTINGS))
        self.assertIs(s["transparent"], True)
        self.assertEqual(s["enabledThemes"], ["dank-discord.css", "appglass-discord.css"])
        self.assertTrue(s["autoUpdate"])
        self.assertIn("discord", self.niri())
        self.run_ok("remove")
        self.assertEqual(self.w.sb.read(self.w.user(SETTINGS)), OLD_SETTINGS)
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_settings_already_right_not_touched(self):
        done = '{"enabledThemes":["appglass-discord.css","dank-discord.css"],"transparent":true}'
        self.w.hand(SETTINGS, done)
        self.enable()
        self.run_ok("apply", "--only", "vencord")
        self.assertEqual(self.w.sb.read(self.w.user(SETTINGS)), done)
        self.assertNotIn(self.w.user(SETTINGS),
                         self.w.state()["owners"]["vencord"]["files"])

    def test_not_injected_drops_the_rule(self):
        os.remove(os.path.join(self.newest, "_app.asar"))
        self.enable()
        out, err = self.run_ok("apply", "--only", "vencord")
        self.assertIn("Vencord is not in", err)
        self.assertNotIn("discord", self.niri())
        self.assertTrue(os.path.exists(self.w.user(THEME)))

    def test_no_vencord(self):
        import shutil
        shutil.rmtree(self.w.user(".config/Vencord"))
        self.enable()
        out, err = self.run_ok("apply", "--only", "vencord")
        self.assertIn("vencord: skipped: Vencord is not installed", err)

    def test_level_change_rerenders(self):
        self.enable()
        self.run_ok("apply", "--only", "vencord")
        css = self.w.sb.read(self.w.user(THEME))
        self.w.sb.set_level(0.5)
        self.run_ok("apply", "--from-hook")
        self.assertNotEqual(self.w.sb.read(self.w.user(THEME)), css)

    def test_hand_pieces_adopted_and_retired(self):
        script = self.w.hand(".local/bin/appglass-vencord", "#!/bin/sh\nold\n", 0o755)
        tmpl = self.w.hand(".local/share/appglass/appglass-discord.css.tmpl", "old {{x}}\n")
        installer = self.w.hand(".local/share/appglass/VencordInstallerCli-linux", "bin", 0o755)
        theme = self.w.hand(THEME, "hand theme\n")
        self.enable()
        out, err = self.run_ok("apply", "--only", "vencord")
        self.assertIn("vencord: skipped", err)
        self.assertEqual(self.w.sb.read(theme), "hand theme\n")
        self.run_ok("adopt")
        out, err = self.run_ok("apply", "--only", "vencord", "--dry-run")
        self.assertIn("vencord: would delete %s, %s (retired" % (script, tmpl), out + err)
        self.assertTrue(os.path.exists(script))
        self.run_ok("apply", "--only", "vencord")
        self.assertFalse(os.path.exists(script))
        self.assertFalse(os.path.exists(tmpl))
        self.assertTrue(os.path.exists(installer))            # never ours
        self.assertNotEqual(self.w.sb.read(theme), "hand theme\n")
        self.run_ok("apply", "--only", "vencord")             # stays retired
        self.assertFalse(os.path.exists(script))
        self.run_ok("remove")
        self.assertEqual(self.w.sb.read(script), "#!/bin/sh\nold\n")
        self.assertEqual(self.w.mode(script), 0o755)
        self.assertEqual(self.w.sb.read(tmpl), "old {{x}}\n")
        self.assertEqual(self.w.sb.read(theme), "hand theme\n")


if __name__ == "__main__":
    unittest.main()
