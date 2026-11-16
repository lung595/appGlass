"""GTK4 family: dank-glass.css, gtk.css ownership/merge, installed-only niri ids."""

import json
import os
import shutil
import subprocess
import unittest

from fixtures.sandbox import Sandbox, fixture
from appglass import core
from appglass.families import gtk4 as fam

DMS_GTK_SH = "/usr/share/quickshell/dms/scripts/gtk.sh"
DMS_IMPORT = '@import url("dank-colors.css");\n'


def has_gi(version):
    r = subprocess.run(["python3", "-c", "import gi; gi.require_version('Gtk', '%s')" % version],
                       capture_output=True)
    return r.returncode == 0


class EpiphanyDocs(unittest.TestCase):
    """The gtk4 rule gives Epiphany opacity 1.0; the docs must not call it a fallback."""

    def test_docs_agree_with_the_rule(self):
        self.assertIn(r"^org\.gnome\.Epiphany(\.WebApp_.*)?$", fam.APP_IDS)
        docs = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
        with open(os.path.join(docs, "README.md")) as f:
            readme = f.read()
        with open(os.path.join(docs, "webkit.md")) as f:
            webkit = f.read()
        self.assertIn(r'match app-id=r#"^org\.gnome\.Epiphany(\.WebApp_.*)?$"#', readme)
        for text in (readme, webkit):
            for line in text.splitlines():
                if "GNOME Web" in line or "Epiphany" in line:
                    low = line.lower()
                    self.assertNotIn("left out on purpose", low, line)
                    self.assertNotIn("fallback recommended", low, line)
                    self.assertNotIn("recommended: fallback", low, line)
                    self.assertNotIn("recommended fallback", low, line)
        fallback = readme.split("### Fallback apps", 1)[1].split("## Findings", 1)[0]
        self.assertNotIn("GNOME Web", fallback)


class Gtk4(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.bin = self.sb.path("bin")
        self.libexec = self.sb.path("libexec")
        os.makedirs(self.bin)
        os.makedirs(self.libexec)
        for c in ("nautilus", "zenity"):
            self.exe(self.bin, c)
        self._libexec = fam.LIBEXEC_DIRS
        fam.LIBEXEC_DIRS = (self.libexec,)
        self.seed()

    def tearDown(self):
        fam.LIBEXEC_DIRS = self._libexec
        self.sb.cleanup()

    def exe(self, d, name):
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)

    def seed(self, light=False):
        self.sb.seed_dms(light=light)
        self.sb.seed_niri()
        self.sb.seed("gtk/dank-colors-light.css" if light else "gtk/dank-colors.css",
                     "gtk-4.0/dank-colors.css")
        self.before = self.sb.tree_hash()

    def run_ag(self, *argv, **kw):
        env = {"PATH": self.bin}
        env.update(kw.pop("env", {}))
        return self.sb.run(*argv, env=env, **kw)

    def apply(self, *extra, ok=True):
        code, out, err = self.run_ag("apply", "--only", "gtk4", *extra, assume="gtk4")
        if ok:
            self.assertEqual(code, 0, err)
        return out, err

    def glass(self):
        return self.sb.read(self.sb.cfg("gtk-4.0", "dank-glass.css"))

    def gtk_css(self):
        return self.sb.read(self.sb.cfg("gtk-4.0", "gtk.css"))

    def roles(self, light=False):
        d = self.sb.json(fixture("dms", "dms-colors-light.json" if light else "dms-colors.json"))
        return d["colors"][d["mode"]]

    # content
    def test_glass_css_levels(self):
        self.apply()
        g = self.glass()
        c = self.roles()
        sc, scl, sch = c["surface_container"], c["surface_container_low"], \
            c["surface_container_high"]
        for line in (
                "@define-color window_bg_color alpha(%s, 0.60);" % sc,
                "@define-color view_bg_color alpha(%s, 0.60);" % scl,
                "@define-color headerbar_bg_color alpha(%s, 0.125);" % sc,
                "@define-color headerbar_backdrop_color alpha(%s, 0.125);" % sc,
                "@define-color secondary_sidebar_bg_color alpha(%s, 0.125);" % sc,
                "@define-color secondary_sidebar_backdrop_color alpha(%s, 0.125);" % sc,
                "@define-color sidebar_bg_color alpha(%s, 0.125);" % sch,
                "@define-color sidebar_backdrop_color alpha(%s, 0.125);" % sch,
                "@define-color card_bg_color alpha(%s, 0.125);" % sch,
                "@define-color overview_bg_color alpha(%s, 0.60);" % sch,
                "@define-color popover_bg_color %s;" % sch,
                "@define-color dialog_bg_color %s;" % sc,
                "dialog sheet { background-color: @dialog_bg_color; }",
                ":root { --dim-opacity: 0.80; }"):
            self.assertIn(line, g.splitlines())
        self.assertIn(fam.BACKDROP_RULE, g)
        self.assertIn("filter: opacity(0.8); }", g)
        # text roles are left to dank-colors.css when readable
        self.assertNotIn("_fg_color", g.replace("--dim-opacity", ""))
        self.assertEqual(self.gtk_css(),
                         '@import url("dank-colors.css");\n@import url("dank-glass.css");\n')

    def test_levels_follow_dms_setting(self):
        self.sb.set_level(0.5)
        self.apply()
        g = self.glass()
        # inner = 1 - (1 - 0.65) / (1 - 0.5) = 0.3
        self.assertIn("window_bg_color alpha(%s, 0.50);" % self.roles()["surface_container"], g)
        self.assertIn("sidebar_bg_color alpha(%s, 0.30);"
                      % self.roles()["surface_container_high"], g)

    def test_inactive_backdrop_fades(self):
        self.apply()
        self.assertNotIn(":backdrop { background-color", self.glass())   # 0.60: the floor
        self.sb.set_level(0.8)
        self.apply()
        g = self.glass()
        self.assertIn("window.background { transition: background-color 180ms "
                      "cubic-bezier(0.33, 1, 0.68, 1); }", g.splitlines())
        # 0.80 x 0.90 = 0.72 net: alpha() multiplies the 0.80 window colour by 0.90
        self.assertIn("window.background:backdrop { background-color: "
                      "alpha(@window_bg_color, 0.90); }", g.splitlines())
        self.run_ag("set", "inactive.factor", "0.8")
        self.run_ag("set", "inactive.durationMs", "0")
        self.apply()
        g = self.glass()
        self.assertIn("alpha(@window_bg_color, 0.80); }", g)   # 0.64 net, above the floor
        self.assertIn("window.background { transition: none; }", g)
        self.run_ag("set", "inactive.enabled", "false")
        self.apply()
        self.assertNotIn("transition", self.glass())

    def test_light_mode(self):
        self.seed(light=True)
        self.apply()
        g = self.glass()
        c = self.roles(light=True)
        self.assertIn("window_bg_color alpha(%s, 0.60);" % c["surface_container"], g)
        self.assertIn("popover_bg_color %s;" % c["surface_container_high"], g)
        # light on_surface is readable on the light glass: untouched
        self.assertNotIn("window_fg_color", g)
        for bg in ("surface_container", "surface_container_low", "surface_container_high"):
            self.assertGreaterEqual(core.worst_contrast(c["on_surface"], c[bg], 0.6), 2.25)

    def test_unreadable_text_moved(self):
        d = self.sb.json(fixture("dms", "dms-colors.json"))
        d["colors"][d["mode"]]["on_surface"] = "#6a6e74"
        self.sb.write("dms/dms-colors.json", json.dumps(d), base=self.sb.cache)
        self.apply()
        g = self.glass()
        line = [ln for ln in g.splitlines() if ln.startswith("@define-color window_fg_color")]
        self.assertEqual(len(line), 1)
        fg = line[0].split()[-1].rstrip(";")
        self.assertNotEqual(fg, "#6a6e74")
        c = d["colors"][d["mode"]]
        for bg in ("surface_container", "surface_container_low", "surface_container_high"):
            self.assertGreaterEqual(core.worst_contrast(fg, c[bg], 0.6), 2.25)

    # niri
    def kdl(self):
        return self.sb.read(self.sb.cfg("niri", "appglass.kdl"))

    def test_app_ids_installed_only(self):
        self.apply()
        k = self.kdl()
        self.assertIn(r'r#"^org\.gnome\.Nautilus$"#', k)
        self.assertIn(r'r#"^org\.gnome\.Zenity$"#', k)
        self.assertNotIn("Software", k)
        self.assertNotIn("xdg-desktop-portal-gnome", k)
        self.assertNotIn("Epiphany", k)
        self.assertIn("opacity 1.0", k)
        state = self.sb.json(self.sb.path("home", ".local", "state", "appglass", "state.json"))
        self.assertEqual(state["owners"]["gtk4"]["app_ids"],
                         [r"^org\.gnome\.Nautilus$", r"^org\.gnome\.Zenity$"])

    def test_portal_found_in_libexec_and_epiphany(self):
        self.exe(self.libexec, "xdg-desktop-portal-gnome")
        self.exe(self.bin, "epiphany")
        self.apply()
        k = self.kdl()
        self.assertIn(r'r#"^xdg-desktop-portal-gnome$"#', k)
        self.assertIn(r'r#"^org\.gnome\.Epiphany(\.WebApp_.*)?$"#', k)

    def test_every_app_listed(self):
        ids = {a[0] for a in fam.APPS}
        for app_id in ("org.gnome.Nautilus", "org.gnome.Software", "org.gnome.Zenity",
                       "xdg-desktop-portal-gnome", "com.github.tchx84.Flatseal",
                       "org.gnome.Epiphany", "org.gnome.Epiphany.WebApp_abc123",
                       "org.gnome.Adwaita1.Demo", "nautilus-autorun-software"):
            import re
            self.assertTrue(any(re.match(i, app_id) for i in ids), app_id)
        self.assertEqual(fam.APP_IDS, [a[0] for a in fam.APPS])
        self.assertIn("partial", [a for a in fam.APPS if "Epiphany" in a[0]][0][2])

    def test_installed_detection(self):
        env = core.Env(dict(self.sb.env, PATH=self.bin))
        self.assertTrue(fam.installed(env))
        empty = self.sb.path("empty")
        os.makedirs(empty)
        fam.LIBEXEC_DIRS = (empty,)
        self.assertFalse(fam.installed(core.Env(dict(self.sb.env, PATH=empty))))

    @unittest.skipUnless(shutil.which("niri"), "niri not installed")
    def test_niri_validate(self):
        self.apply()
        r = subprocess.run(["niri", "validate", "-c", self.sb.cfg("niri", "config.kdl")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    # idempotency / remove
    def test_idempotent(self):
        self.apply()
        h1 = self.sb.tree_hash()
        out, _ = self.apply()
        self.assertIn("gtk4: up to date", out)
        self.assertEqual(self.sb.tree_hash(), h1)

    def test_remove_byte_identical(self):
        self.apply()
        self.assertNotEqual(self.sb.tree_hash(), self.before)
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)

    # an existing gtk.css
    def test_dms_import_merged_and_restored(self):
        p = self.sb.write("gtk-4.0/gtk.css", DMS_IMPORT)
        before = self.sb.tree_hash()
        self.apply()
        self.assertEqual(self.gtk_css(), fam.GTK_CSS)
        self.apply()
        self.assertEqual(self.gtk_css(), fam.GTK_CSS)
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.readb(p), DMS_IMPORT.encode())
        self.assertEqual(self.sb.tree_hash(), before)

    def test_dms_import_without_newline_and_empty(self):
        for text in ('@import url("dank-colors.css");', "", "\n"):
            p = self.sb.write("gtk-4.0/gtk.css", text)
            self.apply()
            self.assertEqual(self.gtk_css(), fam.GTK_CSS)
            self.run_ag("remove")
            self.assertEqual(self.sb.read(p), text)

    def test_foreign_gtk_css_skipped(self):
        user = '@import url("dank-colors.css");\nwindow { border-radius: 0; }\n'
        self.sb.write("gtk-4.0/gtk.css", user)
        before = self.sb.tree_hash()
        out, err = self.apply()
        self.assertIn("gtk4: skipped", err)
        self.assertIn("user stylesheet", err)
        self.assertEqual(self.gtk_css(), user)
        self.assertFalse(os.path.exists(self.sb.cfg("gtk-4.0", "dank-glass.css")))
        self.assertEqual(self.sb.tree_hash(), before)

    def test_symlinked_gtk_css_skipped(self):
        target = self.sb.write("dotfiles/gtk.css", DMS_IMPORT, base=self.sb.home)
        os.symlink(target, self.sb.cfg("gtk-4.0", "gtk.css"))
        before = self.sb.tree_hash()
        _, err = self.apply()
        self.assertIn("gtk4: skipped", err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_foreign_glass_css_protected(self):
        self.sb.write("gtk-4.0/dank-glass.css", "/* mine */\n")
        before = self.sb.tree_hash()
        _, err = self.apply()
        self.assertIn("gtk4: skipped", err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_user_change_after_merge_kept(self):
        p = self.sb.write("gtk-4.0/gtk.css", DMS_IMPORT)
        self.apply()
        with open(p, "a") as f:
            f.write("label { font-weight: bold; }\n")
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(p), DMS_IMPORT + "label { font-weight: bold; }\n")

    def test_reapply_after_user_change_keeps_it(self):
        p = self.sb.write("gtk-4.0/gtk.css", DMS_IMPORT)
        self.apply()
        with open(p, "a") as f:
            f.write("label { font-weight: bold; }\n")
        self.apply()
        self.assertEqual(self.gtk_css(), fam.GTK_CSS + "label { font-weight: bold; }\n")

    # gtk.css created by appglass stays the user's file
    def test_created_gtk_css_user_change_kept_on_reapply(self):
        p = self.sb.cfg("gtk-4.0", "gtk.css")
        self.apply()
        self.assertEqual(self.gtk_css(), fam.GTK_CSS)
        with open(p, "a") as f:
            f.write("headerbar { min-height: 30px; }\n")
        self.apply()
        self.assertEqual(self.gtk_css(), fam.GTK_CSS + "headerbar { min-height: 30px; }\n")

    def test_created_gtk_css_user_change_kept_on_remove(self):
        p = self.sb.cfg("gtk-4.0", "gtk.css")
        self.apply()
        with open(p, "a") as f:
            f.write("headerbar { min-height: 30px; }\n")
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertIn("kept", err)
        # the user's rule stays, the import of the deleted dank-glass.css goes
        self.assertEqual(self.sb.read(p), DMS_IMPORT + "headerbar { min-height: 30px; }\n")
        self.assertFalse(os.path.exists(self.sb.cfg("gtk-4.0", "dank-glass.css")))

    # opt-out: the user takes the glass import out (or empties gtk.css)
    def _opt_out(self, text):
        p = self.sb.cfg("gtk-4.0", "gtk.css")
        with open(p, "w") as f:
            f.write(text)
        return p

    def test_created_gtk_css_opt_out_kept_and_remove_clean(self):
        for text in (DMS_IMPORT, "", "\n"):
            self.apply()
            self._opt_out(text)
            _, err = self.apply()
            self.assertEqual(self.gtk_css(), text)
            self.assertIn("no longer imports dank-glass.css", err)
            code, _, err = self.run_ag("apply", "--from-hook", "--quiet")
            self.assertEqual(code, 0, err)
            self.assertEqual(self.gtk_css(), text)
            self.assertNotIn("no longer imports", err)        # said once
            code, _, err = self.run_ag("remove")
            self.assertEqual(code, 0, err)
            self.assertEqual(self.sb.tree_hash(), self.before, repr(text))

    def test_merged_gtk_css_opt_out_kept_and_restored(self):
        p = self.sb.write("gtk-4.0/gtk.css", DMS_IMPORT)
        before = self.sb.tree_hash()
        self.apply()
        self._opt_out(DMS_IMPORT)
        self.apply()
        self.assertEqual(self.gtk_css(), DMS_IMPORT)
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(p), DMS_IMPORT)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_opt_out_then_remove_and_apply_opts_in_again(self):
        self.apply()
        self._opt_out(DMS_IMPORT)
        self.apply()
        self.run_ag("remove")
        self.apply()
        self.assertEqual(self.gtk_css(), fam.GTK_CSS)

    def test_created_gtk_css_deleted_stays_deleted(self):
        # deleting the gtk.css appglass created is an opt-out: the hook (and a
        # manual apply) leave it deleted, warned once; remove is clean
        self.apply()
        p = self.sb.cfg("gtk-4.0", "gtk.css")
        os.remove(p)
        for i in range(2):
            code, _, err = self.run_ag("apply", "--from-hook", "--quiet")
            self.assertEqual(code, 0, err)
            self.assertFalse(os.path.lexists(p))
            if i == 0:
                self.assertIn("deleted since apply", err)
                self.assertIn("dank-glass.css", err)
                self.assertEqual(err.count("gtk.css"), 1, err)   # one warning
            else:
                self.assertNotIn("deleted", err)                 # said once
        self.apply()
        self.assertFalse(os.path.lexists(p))
        # the record is kept: remove still deletes dank-glass.css
        st = self.sb.json(self.sb.path("home", ".local", "state", "appglass", "state.json"))
        self.assertIn(p, st["owners"]["gtk4"]["files"])
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)
        self.apply()
        self.assertEqual(self.gtk_css(), fam.GTK_CSS)          # remove + apply opts in

    def test_merged_gtk_css_deleted_not_restored(self):
        # a DMS gtk.css appglass merged into, then deleted: never written back
        p = self.sb.write("gtk-4.0/gtk.css", DMS_IMPORT)
        self.apply()
        os.remove(p)
        code, _, err = self.run_ag("apply", "--from-hook", "--quiet")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(p))
        code, _, err = self.run_ag("remove")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(p))
        self.assertIn("deleted since apply", err)
        self.assertFalse(os.path.exists(self.sb.path("home", ".local", "state", "appglass")))

    def test_owned_glass_css_deleted_kept_on_hook_only(self):
        self.apply()
        g = self.sb.cfg("gtk-4.0", "dank-glass.css")
        os.remove(g)
        code, _, err = self.run_ag("apply", "--from-hook", "--quiet")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(g))
        self.assertIn("deleted since apply", err)
        self.apply()                                            # a manual apply writes it
        self.assertTrue(os.path.isfile(g))
        self.run_ag("remove")
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_merge_changed_keeps_text(self):
        self.assertEqual(fam.merge("", "gtk.css"), fam.GTK_CSS)
        self.assertEqual(fam.merge("", "gtk.css", changed=True), "")
        self.assertEqual(fam.merge(DMS_IMPORT, "gtk.css", changed=True), DMS_IMPORT)

    def test_created_gtk_css_dms_remove_not_undone(self):
        # DMS gtk.sh remove drops the dank-colors line: apply must not put it back
        p = self.sb.cfg("gtk-4.0", "gtk.css")
        self.apply()
        with open(p, "w") as f:
            f.write(fam.GLASS_IMPORT + "\n")
        self.apply()
        self.assertEqual(self.gtk_css(), fam.GLASS_IMPORT + "\n")

    def test_libexec_directory_is_not_an_app(self):
        os.makedirs(os.path.join(self.libexec, "epiphany"))
        env = core.Env(dict(self.sb.env, PATH=self.sb.path("empty-path")))
        self.assertNotIn("epiphany", [c for a in fam.installed_apps(env) for c in a[1]])

    def test_not_installed_removes(self):
        self.apply()
        code, out, err = self.run_ag("apply", "--only", "gtk4", assume_not="gtk4")
        self.assertEqual(code, 0, err)
        self.assertIn("not installed, files removed", out)
        self.assertEqual(self.sb.tree_hash(), self.before)

    # DMS gtk.sh leaves our gtk.css alone
    @unittest.skipUnless(os.path.isfile(DMS_GTK_SH) and shutil.which("bash"),
                         "DMS gtk.sh not installed")
    def test_dms_gtk_sh_does_not_clobber(self):
        self.apply()
        self.sb.seed("gtk/dank-colors.css", "gtk-3.0/dank-colors.css")
        mine = self.sb.readb(self.sb.cfg("gtk-4.0", "gtk.css"))
        empty = self.sb.path("no-system-themes")
        os.makedirs(empty)
        env = dict(self.sb.env, XDG_DATA_DIRS=empty, PATH=os.environ.get("PATH", os.defpath))
        r = subprocess.run(["bash", DMS_GTK_SH, self.sb.config, "apply"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("already present", r.stdout)
        self.assertEqual(self.sb.readb(self.sb.cfg("gtk-4.0", "gtk.css")), mine)
        # DMS "remove" drops only its own line; the glass import stays
        r = subprocess.run(["bash", DMS_GTK_SH, self.sb.config, "remove"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.gtk_css(), fam.GLASS_IMPORT + "\n")

    # GTK parses it
    @unittest.skipUnless(has_gi("4.0"), "python3-gobject with GTK 4 not installed")
    def test_gtk_parses_css(self):
        self.apply()
        code = ("import gi, sys; gi.require_version('Gtk', '4.0'); "
                "from gi.repository import Gtk; p = Gtk.CssProvider(); e = []; "
                "p.connect('parsing-error', lambda p, s, err: e.append(err.message)); "
                "p.load_from_path(sys.argv[1]); print('\\n'.join(e)); sys.exit(1 if e else 0)")
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY")}
        env.update(self.sb.env)
        r = subprocess.run(["python3", "-c", code, self.sb.cfg("gtk-4.0", "gtk.css")],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
