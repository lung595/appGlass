"""A hook run (apply --from-hook) on an unreadable or invalid settings.json
leaves every file as the last good run wrote it: never the defaults."""

import os
import unittest

from fixtures.sandbox import Sandbox


class HookOnBadSettings(unittest.TestCase):
    def setUp(self):
        sb = self.sb = Sandbox()
        sb.seed_dms()
        sb.seed_niri()
        sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        self.run_ok("set", "levels.content", "0.9")
        self.run_ok("apply", "--only", "alacritty")
        self.owned = sb.cfg("alacritty", "appglass.toml")
        self.assertIn("opacity = 0.90", sb.read(self.owned))

    def tearDown(self):
        self.sb.cleanup()

    def run_ok(self, *argv):
        code, out, err = self.sb.run(*argv, assume="alacritty")
        self.assertEqual(code, 0, err)
        return out, err

    def hook_keeps_files(self):
        before = self.sb.readb(self.owned)
        out, err = self.run_ok("apply", "--from-hook")
        self.assertIn("nothing refreshed", err)
        self.assertEqual(self.sb.readb(self.owned), before)

    def test_invalid_settings(self):
        self.sb.write("appglass/settings.json", '{"levels": {"content": "x"}}')
        self.hook_keeps_files()

    def test_bad_json(self):
        self.sb.write("appglass/settings.json", "{")
        self.hook_keeps_files()

    def test_unreadable_settings(self):
        if os.geteuid() == 0:
            self.skipTest("root reads a mode 000 file")
        p = self.sb.cfg("appglass", "settings.json")
        os.chmod(p, 0)
        try:
            self.hook_keeps_files()
        finally:
            os.chmod(p, 0o644)


if __name__ == "__main__":
    unittest.main()
