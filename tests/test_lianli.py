import unittest

from fixtures.shimcase import ShimCase

L = ".local/lib/appglass/lianli/"


class Lianli(ShimCase, unittest.TestCase):
    FAMILY = "lianli"
    KEY = "com.sgtaziz.lianlilinux"
    BINS = ("lianli-gui",)
    SYSTEM = "com.sgtaziz.lianlilinux.desktop"
    LAUNCHER = ".local/share/applications/com.sgtaziz.lianlilinux.desktop"
    FILES = {L + "appglass-wk.so": 0o755, L + "appglass-wk.c": 0o644,
             L + "lianli-glass.css.tmpl": 0o644, L + "lianli-glass.css": 0o644,
             ".local/bin/appglass-lianli": 0o755}
    CSS = L + "lianli-glass.css"
    BUILDS = 1

    def test_css_percent(self):
        self.enable()
        self.w.sb.set_level(0.6)
        self.apply()
        css = self.w.sb.read(self.w.user(self.CSS))
        self.assertIn("var(--bg-base) 60%", css)


if __name__ == "__main__":
    unittest.main()
