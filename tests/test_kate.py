"""Kate: the AppGlass KSyntaxHighlighting theme and the katerc keys."""

import json
import os
import unittest

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

    def test_katerc_keys(self):
        self.apply()
        rc = self.sb.read(self.sb.cfg("katerc"))
        self.assertIn("[KTextEditor Renderer]\nColor Theme=AppGlass\nShow Indentation Lines=true\n"
                      "Auto Color Theme Selection=false\n", rc)
        self.assertIn("Show Full Path in Title=true", rc)
        self.assertNotIn("Breeze Dark", rc)

    def test_flatpak_target(self):
        self.apply()
        self.assertEqual(self.theme(self.w.var("org.kde.kate", "data"))["metadata"]["name"], "AppGlass")
        rc = self.sb.read(self.w.var("org.kde.kate", "config", "katerc"))
        self.assertEqual(rc, "[KTextEditor Renderer]\nAuto Color Theme Selection=false\n"
                             "Color Theme=AppGlass\n")

    def test_kate_rewrote_katerc(self):
        # Kate writes katerc on exit: a re-apply keeps its file, remove takes
        # out only the keys that still name AppGlass
        self.apply()
        p = self.sb.cfg("katerc")
        text = self.sb.read(p).replace("Show Indentation Lines=true", "Show Indentation Lines=false")
        with open(p, "w") as f:
            f.write(text)
        self.apply()
        self.assertEqual(self.sb.read(p), text)
        code, out, err = self.w.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(p), "[General]\nShow Full Path in Title=true\n\n"
                                          "[KTextEditor Renderer]\nShow Indentation Lines=false\n")


if __name__ == "__main__":
    unittest.main()
