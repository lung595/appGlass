import re
import unittest

from fixtures.shimcase import ShimCase

L = ".local/lib/appglass/feishin/"


class Feishin(ShimCase, unittest.TestCase):
    FAMILY = "feishin"
    KEY = "org.jeffvli.feishin"
    FLATPAK = KEY
    SYSTEM = "org.jeffvli.feishin.desktop"
    LAUNCHER = ".local/share/applications/org.jeffvli.feishin.desktop"
    FILES = {L + "agl-hook.js": 0o644, L + "agl-inject.py": 0o644,
             L + "feishin-glass.css.tmpl": 0o644, L + "feishin-glass.css": 0o644,
             ".local/bin/appglass-feishin": 0o755}
    CSS = L + "feishin-glass.css"

    def test_inspector_local_only(self):
        self.enable()
        self.apply()
        w = self.w.sb.read(self.w.user(".local/bin/appglass-feishin"))
        self.assertIn("--inspect=127.0.0.1:0", w)
        self.assertIn("--inspect-publish-uid=stderr", w)
        self.assertIn("mkdir -p -m 700", w)
        text = self.w.sb.read(self.w.user(self.LAUNCHER))
        self.assertEqual(re.findall(r"(?m)^Exec=(.*)$", text),
                         [self.w.user(".local/bin/appglass-feishin")])

    def test_css_levels_raw(self):
        self.enable()
        self.w.sb.set_level(0.7)
        self.apply()
        self.assertIn("0.7", self.w.sb.read(self.w.user(self.CSS)))


if __name__ == "__main__":
    unittest.main()
