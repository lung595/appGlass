"""mpv (background colour include) and GIMP (gimp.css block)."""

import json
import os
import unittest

from test_terminals import TermCase
from appglass import core


class Mpv(TermCase, unittest.TestCase):
    FAMILY = "mpv"
    BINS = ("mpv",)
    FLATPAKS = (("io.mpv.Mpv", "0.42.0"),)

    def seed(self):
        self.sb.write("mpv/mpv.conf", "hwdec=auto\nbackground-color='#ff000000'\n")

    def test_include_and_colour(self):
        self.apply()
        ours = self.sb.cfg("mpv", "appglass.conf")
        conf = self.sb.read(self.sb.cfg("mpv", "mpv.conf"))
        self.assertEqual(conf, 'include="%s"\nhwdec=auto\nbackground-color=\'#ff000000\'\n' % ours)
        text = self.sb.read(ours)
        surface = self.pal().get("surface_container").lstrip("#")
        content = json.loads(self.w.run("levels")[1])["content"]
        body = [ln for ln in text.splitlines() if not ln.startswith("#")]
        self.assertEqual(body, ["background=color",
                                'background-color="#%s%s"' % (core.alpha_hex(content), surface),
                                "border-background=color",
                                "script-opts-append=console-background_alpha=00"])

    def test_flatpak_target(self):
        self.apply()
        d = self.w.var("io.mpv.Mpv", "config", "mpv")
        self.assertEqual(self.sb.read(os.path.join(d, "mpv.conf")),
                         'include="%s"\n' % os.path.join(d, "appglass.conf"))

    def test_user_change_kept(self):
        self.apply()
        p = self.sb.cfg("mpv", "mpv.conf")
        text = self.sb.read(p) + "volume=50\n"
        with open(p, "w") as f:
            f.write(text)
        self.apply()
        self.assertEqual(self.sb.read(p), text)
        self.w.run("remove")
        self.assertEqual(self.sb.read(p), "hwdec=auto\nbackground-color='#ff000000'\nvolume=50\n")


THEME = ("@define-color bg-color               rgb(60,60,60);\n"
         "@define-color widget-bg-color        rgb(42,42,42);\n")
GRAY = ("@define-color bg-color               rgb(119,119,119);\n"
        "@define-color widget-bg-color        rgb(100,100,100);\n")


class Gimp(TermCase, unittest.TestCase):
    FAMILY = "gimp"
    FLATPAKS = (("org.gimp.GIMP", "3.2.8"),)

    def seed(self):
        d = self.sb.path("flatpak", "app", "org.gimp.GIMP", "current", "active", "files",
                         "share", "gimp", "3.0", "themes", "Default")
        os.makedirs(d)
        for name, text in (("gimp-dark.css", THEME), ("gimp-gray.css", GRAY)):
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        self.sb.write("GIMP/3.2/gimp.css", "/* mine */\nbutton { padding: 2px; }\n")

    def css(self):
        return self.sb.read(self.sb.cfg("GIMP", "3.2", "gimp.css"))

    def test_block_after_user_rules(self):
        self.apply()
        css = self.css()
        self.assertTrue(css.startswith("/* mine */\nbutton { padding: 2px; }\n\n/* appglass: begin."))
        self.assertIn("@define-color bg-color transparent;", css)
        self.assertIn("@define-color widget-bg-color rgba(42, 42, 42, 0.45);", css)
        self.assertRegex(css, r"\.background, window, dialog \{ background-color: "
                              r"rgba\(60, 60, 60, 0\.\d+\); \}")
        self.assertIn("tooltip, tooltip.background { background-color: rgba(60, 60, 60, 1.00); }", css)

    def test_scheme_from_gimprc(self):
        self.sb.write("GIMP/3.2/gimprc", "(theme \"Default\")\n(theme-color-scheme gray)\n")
        self.apply()
        self.assertIn("rgba(119, 119, 119, 1.00)", self.css())
        self.assertIn("rgba(100, 100, 100, 0.45)", self.css())

    def test_version_dir_follows_gimp(self):
        meta = self.sb.path("flatpak", "app", "org.gimp.GIMP", "current", "active", "files",
                            "share", "metainfo", "org.gimp.GIMP.metainfo.xml")
        with open(meta, "w") as f:
            f.write('<component><releases><release version="3.4.0"/></releases></component>\n')
        self.apply()
        self.assertTrue(os.path.isfile(self.sb.cfg("GIMP", "3.4", "gimp.css")))
        self.assertFalse(os.path.exists(self.sb.cfg("GIMP", "3.4", "gimprc")))

if __name__ == "__main__":
    unittest.main()
