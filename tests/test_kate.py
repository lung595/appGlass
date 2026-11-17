"""Kate: the AppGlass KSyntaxHighlighting theme and the katerc keys."""

import json
import os
import unittest

from appglass import core
from test_terminals import TermCase, World  # noqa: F401  (World: used by TermCase)

THEME = "org.kde.syntax-highlighting/themes/appglass.theme"
RC = "[General]\nShow Full Path in Title=true\n\n[KTextEditor Renderer]\nColor Theme=Breeze Dark\nShow Indentation Lines=true\n"


class Kate(TermCase, unittest.TestCase):
    FAMILY = "kate"
    BINS = ("kate",)
    FLATPAKS = (("org.kde.kate", None),)

    def seed(self):
        self.sb.write("katerc", RC)

    def theme(self, base=None):
        p = os.path.join(base or self.sb.data, THEME)
        with open(p) as f:
            return json.load(f)

    def test_theme_clear_background(self):
        self.apply()
        t = self.theme()
        self.assertEqual(t["metadata"]["name"], "AppGlass")
        ed = t["editor-colors"]
        self.assertTrue(ed["BackgroundColor"].startswith("#00"))
        self.assertTrue(ed["IconBorder"].startswith("#00"))
        self.assertEqual(len(ed["TextSelection"]), 9)            # #AARRGGBB
        self.assertEqual(len(t["text-styles"]["Normal"]["text-color"]), 7)
        self.assert_readable([s["text-color"] for s in t["text-styles"].values()]
                             + [ed["LineNumbers"]])

    def test_user_katerc_untouched(self):
        # the theme is chosen only for the glass start (the qt-style launcher):
        # a plain Kate keeps the user's theme, an alpha-0 background without
        # the style is never cleared (black, smeared text)
        self.apply()
        self.assertEqual(self.sb.read(self.sb.cfg("katerc")), RC)
        self.assertFalse(os.path.exists(self.w.var("org.kde.kate", "config", "katerc")))

    def test_flatpak_glass_config(self):
        # the launcher puts this dir in front of XDG_CONFIG_DIRS: KConfig
        # cascades it under the user's katerc, [$i] keeps the user's own
        # Color Theme from overriding it
        self.apply()
        self.assertEqual(self.theme(self.w.var("org.kde.kate", "data"))["metadata"]["name"], "AppGlass")
        rc = self.sb.read(self.w.var("org.kde.kate", "config", "appglass", "katerc"))
        self.assertEqual(rc.splitlines()[-3:], ["[KTextEditor Renderer]",
                                                "Auto Color Theme Selection[$i]=false",
                                                "Color Theme[$i]=AppGlass"])
        from appglass.families import kate
        self.assertEqual(kate.xdg_dir(core.Env(self.sb.env)),
                         self.w.var("org.kde.kate", "config", "appglass"))


if __name__ == "__main__":
    unittest.main()
