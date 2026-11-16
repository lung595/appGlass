"""GTK3 family (mode B): AppGlass theme, launcher/autostart overrides, niri ids."""

import json
import os
import shutil
import subprocess
import unittest
import urllib.parse

from fixtures.sandbox import Sandbox, fixture
from appglass import core
from appglass.families import gtk3 as fam


def has_gi(version):
    r = subprocess.run(["python3", "-c", "import gi; gi.require_version('Gtk', '%s')" % version],
                       capture_output=True)
    return r.returncode == 0


class Gtk3(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.bin = self.sb.path("bin")
        os.makedirs(self.bin)
        for c in ("solaar", "nvidia-settings"):
            self.exe(c)
        # system dirs (XDG_DATA_DIRS / XDG_CONFIG_DIRS) inside the sandbox
        self.sysdata = self.sb.path("usr-share")
        self.sysconf = self.sb.path("etc-xdg")
        for n in ("solaar.desktop", "nvidia-settings.desktop"):
            self.sb.seed("gtk/applications/" + n, "applications/" + n, base=self.sysdata)
        self.sb.seed("gtk/autostart/solaar.desktop", "autostart/solaar.desktop",
                     base=self.sysconf)
        self.seed()

    def tearDown(self):
        self.sb.cleanup()

    def exe(self, name):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)

    def seed(self, light=False):
        self.sb.seed_dms(light=light)
        self.sb.seed_niri()
        self.sb.seed("gtk/dank-colors-light.css" if light else "gtk/dank-colors.css",
                     "gtk-3.0/dank-colors.css")
        self.before = self.sb.tree_hash()

    def run_ag(self, *argv, **kw):
        env = {"PATH": self.bin, "XDG_DATA_DIRS": self.sysdata, "XDG_CONFIG_DIRS": self.sysconf}
        env.update(kw.pop("env", {}))
        return self.sb.run(*argv, env=env, **kw)

    def test_missing_dank_colors_warned_once(self):
        # the matugen hook may run before DMS has rendered dank-colors.css
        os.remove(self.sb.cfg("gtk-3.0", "dank-colors.css"))
        _, err = self.apply()
        self.assertIn("dank-colors.css not found", err)
        theme = self.sb.read(self.sb.path("home", ".local", "share", "themes", fam.THEME,
                                          "gtk-3.0", "gtk.css"))
        _, err = self.apply()
        self.assertNotIn("dank-colors.css not found", err)
        self.sb.seed("gtk/dank-colors.css", "gtk-3.0/dank-colors.css")
        _, err = self.apply()
        self.assertNotIn("not found", err)
        # the theme is the same either way (imported by URL at run time)
        self.assertEqual(self.sb.read(self.sb.path("home", ".local", "share", "themes",
                                                   fam.THEME, "gtk-3.0", "gtk.css")), theme)
        os.remove(self.sb.cfg("gtk-3.0", "dank-colors.css"))
        _, err = self.apply()
        self.assertIn("dank-colors.css not found", err)

    def apply(self, *extra):
        code, out, err = self.run_ag("apply", "--only", "gtk3", *extra, assume="gtk3")
        self.assertEqual(code, 0, err)
        return out, err

    def theme(self):
        return self.sb.read(os.path.join(self.sb.data, "themes", "AppGlass", "gtk-3.0",
                                         "gtk.css"))

    def launcher(self, name):
        return os.path.join(self.sb.data, "applications", name)

    def autostart(self):
        return self.sb.cfg("autostart", "solaar.desktop")

    def exec_lines(self, p):
        return [ln for ln in self.sb.read(p).splitlines() if ln.startswith("Exec=")]

    # theme
    def test_theme_imports_and_levels(self):
        self.apply()
        t = self.theme()
        lines = t.splitlines()
        imports = [ln for ln in lines if ln.startswith("@import")]
        self.assertEqual(imports, [
            '@import url("resource:///org/gtk/libgtk/theme/Adwaita/gtk-contained-dark.css");',
            '@import url("file://%s");'
            % urllib.parse.quote(self.sb.cfg("gtk-3.0", "dank-colors.css"))])
        self.assertTrue(t.index("gtk-contained-dark") < t.index("dank-colors.css")
                        < t.index("window.background"))
        for frag in (
                "window.background, window.background:backdrop "
                "{ background-color: alpha(@window_bg_color, 0.60); }",
                "background-color: alpha(@headerbar_bg_color, 0.65); background-image: none; }",
                "background-color: alpha(@sidebar_bg_color, 0.125); background-image: none; }",
                "tooltip, tooltip.background, .csd.popup decoration "
                "{ background-color: @popover_bg_color; }",
                "notebook > header, notebook > header:backdrop "
                "{ background-color: alpha(@sidebar_bg_color, 0.125); }",
                "dialog.background, dialog.background:backdrop "
                "{ background-color: alpha(@window_bg_color, 0.60); }",
                "treeview.view header button, treeview.view header button:backdrop "
                "{ color: @window_fg_color; }"):
            self.assertIn(frag, t)
        # colours only by name: no hex in the rules
        import re
        rules = re.sub(r"/\*.*?\*/", "", t[t.index("window.background"):], flags=re.S)
        self.assertNotRegex(rules, r"#[0-9a-fA-F]{6}")
        self.assertNotIn("window_fg_color #", t)

    def test_levels_follow_dms_setting(self):
        self.sb.set_level(0.7)
        self.apply()
        t = self.theme()
        self.assertIn("alpha(@window_bg_color, 0.70)", t)
        self.assertIn("alpha(@headerbar_bg_color, 0.70)", t)   # bar = max(content, 0.65)
        self.assertIn("alpha(@sidebar_bg_color, 0.00)", t)

    def test_light_mode_imports_light_adwaita(self):
        self.seed(light=True)
        self.apply()
        t = self.theme()
        self.assertIn("Adwaita/gtk-contained.css", t)
        self.assertNotIn("gtk-contained-dark", t)
        d = self.sb.json(fixture("dms", "dms-colors-light.json"))
        c = d["colors"][d["mode"]]
        self.assertGreaterEqual(core.worst_contrast(c["on_surface"], c["surface_container"], 0.6),
                                2.25)
        self.assertNotIn("window_fg_color #", t)

    def test_unreadable_text_moved(self):
        d = self.sb.json(fixture("dms", "dms-colors.json"))
        d["colors"][d["mode"]]["on_surface"] = "#6a6e74"
        self.sb.write("dms/dms-colors.json", json.dumps(d), base=self.sb.cache)
        self.apply()
        t = self.theme()
        line = [ln for ln in t.splitlines() if ln.startswith("@define-color window_fg_color")]
        self.assertEqual(len(line), 1)
        fg = line[0].split()[-1].rstrip(";")
        self.assertGreaterEqual(
            core.worst_contrast(fg, d["colors"][d["mode"]]["surface_container"], 0.6), 2.25)
        # after the dank-colors import, so it wins
        self.assertGreater(t.index("@define-color window_fg_color"), t.index("dank-colors.css"))

    def test_no_global_gtk_css(self):
        self.apply()
        self.assertFalse(os.path.exists(self.sb.cfg("gtk-3.0", "gtk.css")))
        self.assertFalse(os.path.exists(self.sb.cfg("gtk-4.0")))

    # launchers
    def test_launcher_overrides(self):
        self.apply()
        self.assertEqual(self.exec_lines(self.launcher("solaar.desktop")),
                         ["Exec=env GTK_THEME=AppGlass solaar"])
        self.assertEqual(self.exec_lines(self.launcher("nvidia-settings.desktop")),
                         ["Exec=env GTK_THEME=AppGlass nvidia-settings"])
        nv = self.sb.read(self.launcher("nvidia-settings.desktop"))
        self.assertIn("TryExec=nvidia-settings", nv)
        self.assertIn("Name=NVIDIA X Server Settings", nv)
        self.assertTrue(nv.startswith(fam.MARK + "\n[Desktop Entry]\n"))
        self.assertEqual(self.exec_lines(self.autostart()),
                         ["Exec=env GTK_THEME=AppGlass solaar --window=hide"])

    def test_only_installed_apps(self):
        os.remove(os.path.join(self.bin, "nvidia-settings"))
        self.apply()
        self.assertFalse(os.path.exists(self.launcher("nvidia-settings.desktop")))
        self.assertTrue(os.path.exists(self.launcher("solaar.desktop")))
        k = self.sb.read(self.sb.cfg("niri", "appglass.kdl"))
        self.assertIn('match app-id=r#"^(solaar)$"#', k)
        self.assertNotIn("nvidia", k)

    def test_niri_ids_both(self):
        self.apply()
        k = self.sb.read(self.sb.cfg("niri", "appglass.kdl"))
        self.assertIn('match app-id=r#"^(solaar|nvidia-settings)$"#', k)
        self.assertEqual(fam.APP_IDS, [r"^(solaar|nvidia-settings)$"])

    def test_no_system_autostart_no_user_autostart(self):
        os.remove(os.path.join(self.sysconf, "autostart", "solaar.desktop"))
        self.apply()
        self.assertFalse(os.path.exists(self.autostart()))
        self.assertTrue(os.path.exists(self.launcher("solaar.desktop")))

    def test_existing_user_autostart_edited_and_restored(self):
        user = ("[Desktop Entry]\nName=Solaar\nExec=solaar --window=hide --restart-on-wake-up\n"
                "Type=Application\nX-GNOME-Autostart-enabled=true\n")
        p = self.sb.write("autostart/solaar.desktop", user)
        before = self.sb.tree_hash()
        self.apply()
        txt = self.sb.read(p)
        self.assertEqual(self.exec_lines(p),
                         ["Exec=env GTK_THEME=AppGlass solaar --window=hide --restart-on-wake-up"])
        self.assertIn("X-GNOME-Autostart-enabled=true", txt)
        self.assertNotIn(fam.MARK, txt)          # a user file: minimal edit
        self.apply()
        self.assertEqual(self.sb.read(p), txt)   # idempotent
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(p), user)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_existing_user_launcher_edited_and_user_change_kept(self):
        user = "[Desktop Entry]\nName=My NVIDIA\nExec=env __GL_SYNC=1 nvidia-settings\n"
        p = self.sb.write("applications/nvidia-settings.desktop", user, base=self.sb.data)
        self.apply()
        self.assertEqual(self.exec_lines(p),
                         ["Exec=env GTK_THEME=AppGlass env __GL_SYNC=1 nvidia-settings"])
        with open(p, "a") as f:
            f.write("Icon=mine\n")
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(p), user + "Icon=mine\n")

    def test_user_change_to_our_autostart_kept(self):
        p = self.autostart()
        self.apply()
        with open(p, "a") as f:
            f.write("Hidden=true\n")
        self.apply()
        txt = self.sb.read(p)
        self.assertTrue(txt.endswith("Hidden=true\n"))
        self.assertEqual(self.exec_lines(p),
                         ["Exec=env GTK_THEME=AppGlass solaar --window=hide"])
        with open(p, "a") as f:
            f.write("X-GNOME-Autostart-enabled=false\n")
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertIn("kept", err)
        self.assertTrue(self.sb.read(p).endswith("Hidden=true\nX-GNOME-Autostart-enabled=false\n"))

    def test_user_change_to_our_launcher_kept_on_reapply(self):
        p = self.launcher("nvidia-settings.desktop")
        self.apply()
        with open(p, "a") as f:
            f.write("NoDisplay=true\n")
        self.apply()
        self.assertTrue(self.sb.read(p).endswith("NoDisplay=true\n"))

    def test_user_change_to_our_copy_removed_cleanly(self):
        # remove takes our part out of a copy the user changed since
        p = self.autostart()
        self.apply()
        with open(p, "a") as f:
            f.write("Hidden=true\n")
        self.apply()
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        txt = self.sb.read(p)
        self.assertNotIn("GTK_THEME", txt)
        self.assertNotIn(fam.MARK, txt)
        self.assertTrue(txt.endswith("Hidden=true\n"))
        self.assertFalse(os.path.exists(self.launcher("solaar.desktop")))

    def test_opt_out_launcher_kept_and_remove_clean(self):
        for name, path in (("nvidia-settings", self.launcher("nvidia-settings.desktop")),
                           ("solaar", self.autostart())):
            self.apply()
            txt = self.sb.read(path).replace(fam.ENV_PREFIX, "")
            with open(path, "w") as f:
                f.write(txt)
            _, err = self.apply()
            self.assertEqual(self.sb.read(path), txt, name)
            self.assertIn("no longer runs with GTK_THEME=AppGlass", err)
            code, _, err = self.run_ag("apply", "--from-hook", "--quiet")
            self.assertEqual(code, 0, err)
            self.assertEqual(self.sb.read(path), txt, name)
            self.assertNotIn("no longer runs", err)
            code, _, err = self.run_ag("remove")
            self.assertEqual(code, 0, err)
            self.assertEqual(self.sb.tree_hash(), self.before, name)

    def test_deleted_copies_stay_deleted(self):
        # a launcher/autostart copy the user deleted is an opt-out: the hook
        # and a manual apply leave it deleted; remove is clean
        paths = (self.launcher("solaar.desktop"), self.launcher("nvidia-settings.desktop"),
                 self.autostart())
        for path in paths:
            self.apply()
            os.remove(path)
            for i in range(2):
                code, _, err = self.run_ag("apply", "--from-hook", "--quiet")
                self.assertEqual(code, 0, err)
                self.assertFalse(os.path.lexists(path), path)
                self.assertEqual(err.count("deleted since apply"), 1 - i, err)
                self.assertNotIn("no longer runs", err)
            self.apply()
            self.assertFalse(os.path.lexists(path), path)
            code, _, err = self.run_ag("remove")
            self.assertEqual(code, 0, err)
            self.assertEqual(self.sb.tree_hash(), self.before, path)

    def test_deleted_existing_user_launcher_not_restored(self):
        user = "[Desktop Entry]\nName=My NVIDIA\nExec=nvidia-settings\n"
        p = self.sb.write("applications/nvidia-settings.desktop", user, base=self.sb.data)
        self.apply()
        os.remove(p)
        code, _, err = self.run_ag("apply", "--from-hook", "--quiet")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(p))
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(p))       # the backup is not put back

    def test_opt_out_existing_user_launcher_kept(self):
        user = "[Desktop Entry]\nName=My NVIDIA\nExec=nvidia-settings\n"
        p = self.sb.write("applications/nvidia-settings.desktop", user, base=self.sb.data)
        self.apply()
        with open(p, "w") as f:
            f.write(user + "Icon=mine\n")
        self.apply()
        self.assertEqual(self.sb.read(p), user + "Icon=mine\n")
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(p), user + "Icon=mine\n")

    def test_has_theme(self):
        self.assertTrue(fam.has_theme("Exec=env GTK_THEME=AppGlass x\n"))
        self.assertFalse(fam.has_theme("Exec=x\n# GTK_THEME=AppGlass\n"))
        self.assertFalse(fam.has_theme("Exec=env GTK_THEME=AppGlassOld x\n"))

    def test_symlinked_launcher_left_alone(self):
        target = self.sb.write("dotfiles/solaar.desktop",
                               "[Desktop Entry]\nName=Solaar\nExec=solaar\n", base=self.sb.home)
        os.makedirs(os.path.join(self.sb.data, "applications"), exist_ok=True)
        os.symlink(target, self.launcher("solaar.desktop"))
        before = self.sb.readb(target)
        _, err = self.apply()
        self.assertIn("symlink", err)
        self.assertEqual(self.sb.readb(target), before)
        self.assertTrue(os.path.islink(self.launcher("solaar.desktop")))
        self.assertEqual(self.exec_lines(self.launcher("nvidia-settings.desktop")),
                         ["Exec=env GTK_THEME=AppGlass nvidia-settings"])
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.readb(target), before)

    def test_themed_exec_cases(self):
        t = fam.themed("[Desktop Entry]\nExec=GTK_THEME=Other foo\nDBusActivatable=true\n"
                       "[Desktop Action new]\nExec=foo --new\n")
        self.assertIn("Exec=GTK_THEME=AppGlass foo\n", t)
        self.assertIn("Exec=env GTK_THEME=AppGlass foo --new\n", t)
        self.assertIn("DBusActivatable=false\n", t)
        self.assertEqual(fam.themed(t), t)
        self.assertEqual(fam.themed("Exec=env GTK_THEME=AppGlass x\n"),
                         "Exec=env GTK_THEME=AppGlass x\n")
        self.assertEqual(fam.undo(None, "x.desktop", fam.themed("[Desktop Entry]\nExec=foo\n",
                                                                 mark=True)),
                         "[Desktop Entry]\nExec=foo\n")

    def test_foreign_theme_protected(self):
        self.sb.write("themes/AppGlass/gtk-3.0/gtk.css", "/* mine */\n", base=self.sb.data)
        before = self.sb.tree_hash()
        code, out, err = self.run_ag("apply", "--only", "gtk3", assume="gtk3")
        self.assertEqual(code, 0, err)
        self.assertIn("gtk3: skipped", err)
        self.assertEqual(self.sb.tree_hash(), before)

    # idempotency / remove
    def test_idempotent(self):
        self.apply()
        h1 = self.sb.tree_hash()
        out, _ = self.apply()
        self.assertIn("gtk3: up to date", out)
        self.assertEqual(self.sb.tree_hash(), h1)

    def test_remove_byte_identical(self):
        self.apply()
        self.assertNotEqual(self.sb.tree_hash(), self.before)
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_app_uninstalled_override_dropped(self):
        self.apply()
        os.remove(os.path.join(self.bin, "nvidia-settings"))
        self.apply()
        self.assertFalse(os.path.exists(self.launcher("nvidia-settings.desktop")))
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.exe("nvidia-settings")
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_installed_detection(self):
        self.assertTrue(fam.installed(core.Env(dict(self.sb.env, PATH=self.bin))))
        empty = self.sb.path("empty")
        os.makedirs(empty)
        self.assertFalse(fam.installed(core.Env(dict(self.sb.env, PATH=empty))))

    @unittest.skipUnless(shutil.which("niri"), "niri not installed")
    def test_niri_validate(self):
        self.apply()
        r = subprocess.run(["niri", "validate", "-c", self.sb.cfg("niri", "config.kdl")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipUnless(shutil.which("desktop-file-validate"), "desktop-file-utils missing")
    def test_desktop_files_valid(self):
        self.apply()
        for p in (self.launcher("solaar.desktop"), self.launcher("nvidia-settings.desktop"),
                  self.autostart()):
            r = subprocess.run(["desktop-file-validate", p], capture_output=True, text=True)
            errors = [ln for ln in (r.stdout + r.stderr).splitlines() if "error:" in ln]
            self.assertEqual(errors, [], p)

    @unittest.skipUnless(has_gi("3.0"), "python3-gobject with GTK 3 not installed")
    def test_gtk_parses_theme(self):
        self.apply()
        code = ("import gi, sys; gi.require_version('Gtk', '3.0'); "
                "from gi.repository import Gtk; p = Gtk.CssProvider(); e = []; "
                "p.connect('parsing-error', lambda p, s, err: e.append(err.message)); "
                "p.load_from_path(sys.argv[1]); print('\\n'.join(e)); sys.exit(1 if e else 0)")
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY")}
        env.update(self.sb.env)
        p = os.path.join(self.sb.data, "themes", "AppGlass", "gtk-3.0", "gtk.css")
        r = subprocess.run(["python3", "-c", code, p], capture_output=True, text=True, env=env,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
