"""The table of native terminal writers: foot, kitty, ghostty, wezterm, konsole.

Each one: the alpha at the content level, opaque text readable on the glass,
the main config edited once (idempotent), a native and a flatpak target,
remove gives the tree back byte-identical, a changed main config is kept.
"""

import os
import re
import shutil
import subprocess
import unittest

from fixtures.sandbox import Sandbox
from appglass import core
from appglass.families import _term, foot, ghostty, kitty, konsole, wezterm


class World:
    def __init__(self, bins=(), flatpaks=()):
        self.sb = sb = Sandbox()
        sb.seed_dms()
        sb.seed_niri()
        self.bin = sb.path("bin")
        os.makedirs(self.bin)
        for b in bins:
            self.exe(b)
        sb.env["PATH"] = self.bin + os.pathsep + sb.env["PATH"]
        sb.env["FLATPAK_SYSTEM_DIR"] = sb.path("flatpak")
        sb.env["FLATPAK_USER_DIR"] = sb.path("no-user-flatpak")
        for app_id, version in flatpaks:
            self.flatpak(app_id, version)

    def exe(self, name, text="#!/bin/sh\nexit 0\n"):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, 0o755)
        return p

    def flatpak(self, app_id, version=None):
        d = self.sb.path("flatpak", "app", app_id, "current", "active")
        os.makedirs(os.path.join(d, "files", "share", "metainfo"))
        with open(os.path.join(d, "metadata"), "w") as f:
            f.write("[Application]\nname=%s\nruntime=org.freedesktop.Platform/x86_64/25.08\n"
                    % app_id)
        if version:
            with open(os.path.join(d, "files", "share", "metainfo",
                                   app_id + ".metainfo.xml"), "w") as f:
                f.write('<component><releases><release version="%s" date="2025-01-01"/>'
                        '</releases></component>\n' % version)

    def var(self, app_id, *p):
        return os.path.join(self.sb.home, ".var", "app", app_id, *p)

    def run(self, *argv):
        return self.sb.run(*argv)

    def cleanup(self):
        self.sb.cleanup()


class TermCase:
    FAMILY = None
    BINS = ()
    FLATPAKS = ()

    def setUp(self):
        self.w = World(self.BINS, self.FLATPAKS)
        self.sb = self.w.sb
        self.seed()
        self.before = self.sb.tree_hash()

    def seed(self):
        pass

    def tearDown(self):
        self.w.cleanup()

    def apply(self):
        code, out, err = self.w.run("apply", "--only", self.FAMILY)
        self.assertEqual(code, 0, err)
        self.assertNotIn("skipped", err)
        return out, err

    def pal(self):
        env = core.Env(self.sb.env)
        return core.Palette(env)

    def assert_readable(self, colours, alpha=0.6):
        bg = self.pal().get("surface")
        for c in colours:
            self.assertGreaterEqual(core.worst_contrast(c, bg, alpha), 2.2, c)

    def test_idempotent_and_remove(self):
        self.apply()
        h = self.sb.tree_hash()
        out, _ = self.apply()
        self.assertIn("%s: up to date" % self.FAMILY, out)
        self.assertEqual(self.sb.tree_hash(), h)
        code, out, err = self.w.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_not_installed_writes_nothing(self):
        shutil.rmtree(self.w.bin)
        shutil.rmtree(self.sb.path("flatpak"), ignore_errors=True)
        code, out, err = self.w.run("apply", "--only", self.FAMILY)
        self.assertEqual(code, 0, err)
        self.assertIn("not installed", out + err)


class Foot(TermCase, unittest.TestCase):
    FAMILY = "foot"
    BINS = ("foot",)
    FLATPAKS = (("page.codeberg.dnkl.foot", "1.25.0"),)

    def seed(self):
        self.w.exe("foot", "#!/bin/sh\necho 'foot version: 1.26.1 +pgo +ime'\n")
        self.sb.write("foot/foot.ini", "include=~/.config/foot/dank-colors.ini\n\n"
                      "[main]\nfont=monospace:size=11\n\n[colors]\nalpha=1.0\n")

    def ini(self, p):
        import configparser
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.read_string("[top]\n" + self.sb.read(p))
        return cp

    def test_native_and_flatpak(self):
        self.apply()
        nat = self.ini(self.sb.cfg("foot", "appglass.ini"))
        self.assertEqual(nat["colors-dark"]["alpha"], "0.60")   # foot 1.26: colors-dark
        fp = self.ini(self.w.var("page.codeberg.dnkl.foot", "config", "foot", "appglass.ini"))
        self.assertEqual(fp["colors"]["alpha"], "0.60")          # foot 1.25: colors
        self.assertNotIn("colors-dark", fp)
        ansi = ["#" + nat["colors-dark"]["regular%d" % i] for i in range(8)]
        ansi += ["#" + nat["colors-dark"]["bright%d" % i] for i in range(8)]
        self.assert_readable(ansi + ["#" + nat["colors-dark"]["foreground"]])
        self.assertEqual(nat["colors-dark"]["regular0"],
                         core.readable(self.pal().get("outline"), self.pal().get("surface"), 0.6).lstrip("#"))

    def test_main_edit(self):
        self.apply()
        text = self.sb.read(self.sb.cfg("foot", "foot.ini"))
        lines = text.splitlines()
        inc = "include=" + self.sb.cfg("foot", "appglass.ini")
        # after the DMS include, before [main]
        self.assertEqual(lines[:2], ["include=~/.config/foot/dank-colors.ini", inc])
        self.assertIn("# appglass-off: alpha=1.0", lines)
        # the flatpak foot.ini (absent before) includes its own copy by absolute path
        fp = self.sb.read(self.w.var("page.codeberg.dnkl.foot", "config", "foot", "foot.ini"))
        self.assertEqual(fp, "include=%s\n" % self.w.var("page.codeberg.dnkl.foot", "config",
                                                         "foot", "appglass.ini"))

    def test_level_follows(self):
        self.sb.set_level(0.8)
        self.apply()
        self.assertIn("alpha=0.80", self.sb.read(self.sb.cfg("foot", "appglass.ini")))

    def test_user_change_kept_and_undo(self):
        self.apply()
        p = self.sb.cfg("foot", "foot.ini")
        self.sb.write("foot/foot.ini", self.sb.read(p) + "\n[cursor]\nstyle=beam\n")
        self.apply()
        self.assertIn("style=beam", self.sb.read(p))
        code, out, err = self.w.run("remove")
        self.assertEqual(code, 0, err)
        text = self.sb.read(p)
        self.assertNotIn("appglass", text)
        self.assertIn("\nalpha=1.0", text)
        self.assertIn("style=beam", text)

    def test_section_by_version(self):
        self.assertEqual(foot.section((1, 25, 0)), "colors")
        self.assertEqual(foot.section((1, 26, 0)), "colors-dark")
        self.assertEqual(foot.section(None), "colors")


class Kitty(TermCase, unittest.TestCase):
    FAMILY = "kitty"
    BINS = ("kitty",)

    def seed(self):
        self.sb.write("kitty/kitty.conf", "include dank-theme.conf\nbackground_opacity 1.0\n"
                      "font_size 11")

    def test_render_and_include_last(self):
        self.apply()
        ours = self.sb.read(self.sb.cfg("kitty", "appglass.conf"))
        self.assertIn("background_opacity 0.60", ours)
        cols = re.findall(r"(?m)^color\d+ (#[0-9a-f]{6})$", ours)
        self.assertEqual(len(cols), 16)
        self.assert_readable(cols)
        main = self.sb.read(self.sb.cfg("kitty", "kitty.conf"))
        self.assertTrue(main.endswith("font_size 11\ninclude appglass.conf\n"), main)


class Ghostty(TermCase, unittest.TestCase):
    FAMILY = "ghostty"
    BINS = ("ghostty",)

    def seed(self):
        self.sb.write("ghostty/config", "theme = dankcolors\nbackground-opacity = 1\n")

    def test_render_and_config_file_last(self):
        self.apply()
        ours = self.sb.read(self.sb.cfg("ghostty", "appglass"))
        self.assertIn("background-opacity = 0.60", ours)
        self.assertIn("background-opacity-cells = false", ours)
        self.assertEqual(len(re.findall(r"(?m)^palette = \d+=#[0-9a-f]{6}$", ours)), 16)
        main = self.sb.read(self.sb.cfg("ghostty", "config"))
        self.assertTrue(main.endswith("config-file = ?%s\n" % self.sb.cfg("ghostty", "appglass")))

    def test_new_name_preferred(self):
        self.sb.write("ghostty/config.ghostty", "font-size = 11\n")
        self.apply()
        self.assertIn("config-file", self.sb.read(self.sb.cfg("ghostty", "config.ghostty")))
        self.assertNotIn("config-file", self.sb.read(self.sb.cfg("ghostty", "config")))


class WezTerm(TermCase, unittest.TestCase):
    FAMILY = "wezterm"
    BINS = ("wezterm",)
    FLATPAKS = (("org.wezfurlong.wezterm", "20240203"),)

    USER = ("local wezterm = require 'wezterm'\nlocal cfg = wezterm.config_builder()\n"
            "cfg.font_size = 11\nreturn cfg\n-- trailing comment\n")

    def seed(self):
        self.sb.write("wezterm/wezterm.lua", self.USER)

    def test_require_before_return(self):
        self.apply()
        main = self.sb.read(self.sb.cfg("wezterm", "wezterm.lua"))
        self.assertIn("cfg.font_size = 11\nrequire('appglass').apply_to_config(cfg)  -- appglass\n"
                      "return cfg\n", main)
        lua = self.sb.read(self.sb.cfg("wezterm", "appglass.lua"))
        self.assertIn("config.window_background_opacity = 0.60", lua)
        self.assertIn("config.text_background_opacity = 1.0", lua)
        bar = core.hex_to_rgb(self.pal().get("surface"))
        self.assertIn("rgba(%d,%d,%d,0.65)" % bar, lua)
        # the flatpak gets a minimal wezterm.lua of its own
        fp = self.sb.read(self.w.var("org.wezfurlong.wezterm", "config", "wezterm", "wezterm.lua"))
        self.assertIn("require('appglass').apply_to_config(config)", fp)
        self.assertTrue(fp.rstrip().endswith("return config"))

    def test_lua_parses(self):
        luac = shutil.which("luac") or shutil.which("luac5.4") or shutil.which("luac5.3")
        if not luac:
            self.skipTest("no luac")
        self.apply()
        for p in (self.sb.cfg("wezterm", "appglass.lua"), self.sb.cfg("wezterm", "wezterm.lua")):
            r = subprocess.run([luac, "-p", p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_return_conflict(self):
        self.sb.write("wezterm/wezterm.lua", "return { font_size = 11 }\n")
        before = self.sb.tree_hash()
        code, out, err = self.w.run("apply", "--only", "wezterm")
        self.assertIn("wezterm: skipped", err)
        self.assertIn("apply_to_config(config)", err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_undo_after_user_change(self):
        self.apply()
        p = self.sb.cfg("wezterm", "wezterm.lua")
        self.sb.write("wezterm/wezterm.lua", self.sb.read(p).replace("11", "12"))
        code, out, err = self.w.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(p), self.USER.replace("11", "12"))


class Konsole(TermCase, unittest.TestCase):
    FAMILY = "konsole"
    FLATPAKS = (("org.kde.konsole", "25.08.1"),)
    BINS = ("konsole",)

    def seed(self):
        self.sb.write("konsolerc", "[MainWindow]\nToolBarsMovable=Disabled\n")

    def test_scheme_profile_rc(self):
        self.apply()
        d = self.sb.path("home", ".local", "share", "konsole")
        sch = self.sb.read(os.path.join(d, "AppGlass.colorscheme"))
        self.assertIn("Opacity=0.60", sch)
        self.assertIn("Blur=false", sch)
        self.assertIn("[Color7Intense]", sch)
        bg = core.hex_to_rgb(self.pal().get("surface"))
        self.assertIn("[Background]\nColor=%d,%d,%d" % bg, sch)
        prof = self.sb.read(os.path.join(d, "AppGlass.profile"))
        self.assertIn("ColorScheme=AppGlass", prof)
        rc = self.sb.read(self.sb.cfg("konsolerc"))
        self.assertIn("[Desktop Entry]\nDefaultProfile=AppGlass.profile\n", rc)
        self.assertIn("ToolBarsMovable=Disabled", rc)
        fp = self.w.var("org.kde.konsole")
        self.assertTrue(os.path.isfile(os.path.join(fp, "data", "konsole", "AppGlass.colorscheme")))
        self.assertIn("DefaultProfile=AppGlass.profile",
                      self.sb.read(os.path.join(fp, "config", "konsolerc")))

    def test_user_profile_kept(self):
        self.sb.write("konsolerc", "[Desktop Entry]\nDefaultProfile=Mine.profile\n")
        self.before = self.sb.tree_hash()
        out, err = self.apply()
        self.assertIn("Mine.profile (yours, kept)", err)
        self.assertIn("DefaultProfile=Mine.profile", self.sb.read(self.sb.cfg("konsolerc")))

    def test_rewritten_rc_undo(self):
        self.apply()
        # Konsole rewrites konsolerc on exit (another key, same profile)
        self.sb.write("konsolerc", "[Desktop Entry]\nDefaultProfile=AppGlass.profile\n\n"
                      "[MainWindow]\nToolBarsMovable=Disabled\nState=AAA\n")
        code, out, err = self.w.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(self.sb.cfg("konsolerc")),
                         "[MainWindow]\nToolBarsMovable=Disabled\nState=AAA\n")


class Ini(unittest.TestCase):
    def test_set_and_unset(self):
        t = "[A]\nx=1\n\n[B]\ny=2\n"
        t2 = _term.ini_set(t, "A", "z", "3")
        self.assertEqual(t2, "[A]\nx=1\nz=3\n\n[B]\ny=2\n")
        self.assertEqual(_term.ini_set(t2, "A", "z", "4"), "[A]\nx=1\nz=4\n\n[B]\ny=2\n")
        self.assertEqual(_term.ini_set("", "C", "k", "v"), "[C]\nk=v\n")
        self.assertEqual(_term.ini_unset(_term.ini_set(t, "C", "k", "v"), "C", "k"), t)
        self.assertEqual(_term.ini_get(t2, "A", "z"), "3")


if __name__ == "__main__":
    unittest.main()


class FlatpakWindowIds(unittest.TestCase):
    """A flatpak's window app-id is its flatpak id (foot from flathub maps as
    page.codeberg.dnkl.foot, not foot): every family with a FLATPAK lists it,
    so status routes the record to the family and niri gets its 1.0 rule."""

    # native-toolkit apps: the flatpak window app-id is the flatpak id
    # (an Electron app sets its own, feishin, so it is not in the list)
    NATIVE_IDS = ("foot", "mpv", "kate", "zed", "konsole", "gimp", "wezterm")

    def test_every_flatpak_id_is_an_app_id(self):
        from appglass.core import discover
        fams = discover()
        for name in self.NATIVE_IDS:
            mod = fams[name]
            fp = mod.FLATPAK
            with self.subTest(family=name):
                self.assertTrue(any(re.search(rx, fp) for rx in mod.APP_IDS),
                                "%s: %s is not in APP_IDS" % (name, fp))

    def test_flatpak_foot_routes_to_foot(self):
        from appglass import adapters
        from appglass.core import discover
        rec = {"key": "page.codeberg.dnkl.foot", "names": ["page.codeberg.dnkl.foot"],
               "toolkit": "terminal"}
        r = adapters.resolve(rec, discover())
        self.assertEqual((r["family"], r["effective"]), ("foot", "glass"))
