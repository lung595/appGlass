"""niri: the fallback / glass / inactive / games blocks and the browserGlass
exclusion (golden KDL, niri validate on the rendered file)."""

import os
import shutil
import subprocess
import tempfile
import unittest

from fixtures.sandbox import Sandbox, fixture
from appglass import core, niri

HAVE_NIRI = shutil.which("niri") is not None


def golden(name):
    with open(fixture("niri", name)) as f:
        return f.read()


FULL = dict(app_ids=[r"^Alacritty$", r"^firefox$", r"^org\.gnome\.Nautilus$"],
            fallback="opaque", fallback_ids=[r"^google-chrome$"],
            games=[r"^Pinball\.exe$"], inactive=0.55)
VALUE = dict(app_ids=[r"^Alacritty$"], fallback="value", value=0.7,
             fallback_ids=[r"^google-chrome$", r"^Alacritty$", r"^librewolf$"], games=[])


class Render(unittest.TestCase):
    def test_golden_full(self):
        self.assertEqual(niri.render(**FULL), golden("golden-full.kdl"))

    def test_golden_value(self):
        self.assertEqual(niri.render(**VALUE), golden("golden-value.kdl"))

    def test_order_and_blocks(self):
        t = niri.render(**FULL)
        i_fb, i_gl = t.index("exclude app-id"), t.index('match app-id=r#"^Alacritty$"#\n')
        i_in, i_gm = t.index("is-active=false"), t.index("steam_app_")
        self.assertLess(i_fb, i_gl)
        self.assertLess(i_gl, i_in)
        self.assertLess(i_in, i_gm)
        self.assertEqual(t.count("window-rule {"), 4)
        # opaque mode: the per-app fallback list is not needed
        self.assertNotIn("google-chrome", t)
        self.assertIn("blur false", t)

    def test_browserglass_excluded_everywhere(self):
        t = niri.render(**FULL)
        self.assertNotIn('match app-id=r#"^firefox$"#', t)
        self.assertNotIn("librewolf$", niri.render(**VALUE))
        self.assertIn("exclude app-id=r#\"%s\"#" % niri.BROWSERGLASS_RE, t)
        self.assertTrue(niri.delegated(r"^(firefox|librewolf)$"))
        self.assertTrue(niri.delegated(r"^io\.gitlab\.librewolf-community$"))
        self.assertFalse(niri.delegated(r"^Alacritty$"))

    def test_off_mode(self):
        t = niri.render([r"^Alacritty$"], fallback="off", fallback_ids=[r"^x$"], games=[])
        self.assertNotIn("exclude", t)
        self.assertNotIn("^x$", t)
        self.assertIn("steam_app_", t)
        with self.assertRaises(ValueError):
            niri.render([], fallback="0.70")

    def test_old_single_block_by_default(self):
        t = niri.render([r"^Alacritty$"])
        self.assertEqual(t.count("window-rule {"), 1)

    @unittest.skipUnless(HAVE_NIRI, "niri not installed")
    def test_niri_validates_rendered(self):
        d = tempfile.mkdtemp(prefix="appglass-kdl-")
        try:
            for name, kw in (("full", FULL), ("value", VALUE)):
                with open(os.path.join(d, "appglass.kdl"), "w") as f:
                    f.write(niri.render(**kw))
                cfg = os.path.join(d, "config.kdl")
                with open(cfg, "w") as f:
                    f.write('include "appglass.kdl"\n')
                r = subprocess.run(["niri", "validate", "-c", cfg],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, (name, r.stdout + r.stderr))
        finally:
            shutil.rmtree(d)


class Sync(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.others = ",".join(n for n in core.discover() if n != "alacritty")

    def tearDown(self):
        self.sb.cleanup()

    def apply(self, *argv):
        return self.sb.run("apply", *argv, assume="alacritty", assume_not=self.others)

    def rules(self):
        return self.sb.read(self.sb.cfg("niri", "appglass.kdl"))

    def test_default_is_opaque_fallback(self):
        code, out, err = self.apply()
        self.assertEqual(code, 0, err)
        t = self.rules()
        self.assertIn("exclude app-id", t)
        self.assertIn('match app-id=r#"^Alacritty$"#', t)
        self.assertIn("steam_app_", t)

    def test_settings_switch_mode(self):
        self.apply()
        self.sb.run("set", "fallback.mode", "off")
        self.sb.run("set", "fallback.inactive", "0.55")
        code, out, err = self.apply()
        self.assertEqual(code, 0, err)
        t = self.rules()
        self.assertNotIn("exclude app-id", t)
        self.assertIn("is-active=false", t)
        self.assertIn("opacity 0.55", t)

    def test_settings_without_apps_writes_rules(self):
        self.sb.run("set", "fallback.mode", "opaque")
        code, out, err = self.sb.run("apply", assume_not="alacritty," + self.others)
        self.assertEqual(code, 0, err)
        t = self.rules()
        self.assertIn("exclude app-id", t)
        self.assertNotIn("Alacritty", t)
        code, out, err = self.sb.run("remove")
        self.assertFalse(os.path.exists(self.sb.cfg("niri", "appglass.kdl")))
        self.assertNotIn("appglass.kdl", self.sb.read(self.sb.cfg("niri", "config.kdl")))

    @unittest.skipUnless(HAVE_NIRI, "niri not installed")
    def test_validates(self):
        self.sb.run("set", "fallback.inactive", "0.55")
        self.apply()
        r = subprocess.run(["niri", "validate", "-c", self.sb.cfg("niri", "config.kdl")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
