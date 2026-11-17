"""Zed: theme_overrides for the active theme between appglass comment lines."""

import json
import os
import unittest

from appglass import core
from appglass.families import zed
from test_terminals import TermCase, World  # noqa: F401  (World: the fake installs)

ZED_DEFAULT = """// Zed settings
//
// For information on how to configure Zed, see the Zed
// documentation: https://zed.dev/docs/configuring-zed
{
  "ui_font_size": 16, // big
  "theme": {
    "mode": "system",
    "light": "One Light",
    "dark": "Ayu Dark",
  },
}
"""


class Zed(TermCase, unittest.TestCase):
    FAMILY = "zed"
    BINS = ("zeditor",)
    FLATPAKS = (("dev.zed.Zed", "1.28.1"),)

    def seed(self):
        self.sb.write("zed/settings.json", ZED_DEFAULT)

    def settings(self, p):
        return json.loads(zed.strip_jsonc(self.sb.read(p)))

    def test_overrides_for_active_dark_theme(self):
        self.apply()
        p = self.sb.cfg("zed", "settings.json")
        s = self.settings(p)
        self.assertEqual(s["ui_font_size"], 16)
        o = s["theme_overrides"]["Ayu Dark"]
        pal = self.pal()
        self.assertEqual(o["background.appearance"], "transparent")
        self.assertEqual(o["background"], pal.get("surface") + "99")          # 0.60
        self.assertEqual(o["title_bar.background"], pal.get("surface") + "a6")  # 0.65 bar
        self.assertEqual(o["status_bar.background"], pal.get("surface") + "a6")
        for k in zed.CLEAR_KEYS:
            self.assertEqual(o[k], "#00000000", k)
        self.assertEqual(o["elevated_surface.background"], pal.get("surface_container") + "ff")
        self.assertEqual(o["element.selected"], "#ffffff1f")
        text = self.sb.read(p)
        self.assertTrue(text.startswith(ZED_DEFAULT[:ZED_DEFAULT.index("{") + 1] + "\n  "
                                        + zed.BEGIN), text)
        self.assertIn('"ui_font_size": 16, // big', text)

    def test_flatpak_and_default_theme(self):
        self.apply()
        p = self.w.var("dev.zed.Zed", "config", "zed", "settings.json")
        s = self.settings(p)
        self.assertEqual(list(s), ["theme_overrides"])
        self.assertIn("One Dark", s["theme_overrides"])

    def test_user_edit_keeps_block_fresh(self):
        self.apply()
        p = self.sb.cfg("zed", "settings.json")
        self.sb.write("zed/settings.json", self.sb.read(p).replace("16", "17"))
        self.sb.set_level(0.8)
        self.apply()
        s = self.settings(p)
        self.assertEqual(s["ui_font_size"], 17)
        self.assertEqual(s["theme_overrides"]["Ayu Dark"]["background"],
                         self.pal().get("surface") + "cc")
        self.assertEqual(self.sb.read(p).count(zed.BEGIN), 1)
        code, out, err = self.w.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(p), ZED_DEFAULT.replace("16", "17"))

    def test_user_theme_overrides_conflict(self):
        self.sb.write("zed/settings.json", '{"theme_overrides": {"One Dark": {}}}\n')
        code, out, err = self.w.run("apply", "--only", "zed")
        self.assertIn("zed: skipped", err)
        self.assertIn("theme_overrides of its own", err)

    def test_jsonc(self):
        self.assertEqual(json.loads(zed.strip_jsonc('{"a": "x//y", /* c */ "b": [1,],}')),
                         {"a": "x//y", "b": [1]})


if __name__ == "__main__":
    unittest.main()
