"""adopt --rescue after a lost state, case by case.

Each case: a home with the user's files, apply, the state lost (the whole
state dir, or only state.json with the ring kept), adopt --rescue, remove.
The rescue claims only what it can prove is appglass's: a file it only
edited keeps the rest (the file minus appglass's lines), a file reached
through a symlinked dir is left alone, a plain copy of a file appglass
reads is never taken for its own without the ring. The refusal, doctor and
the rescue all name the same files."""

import io
import os
import shutil
import unittest

from fixtures.sandbox import Sandbox
from appglass import core
from appglass.families import gtk3, gtk4

DMS_IMPORT = '@import url("dank-colors.css");\n'
ALAC_IMPORT = '[general]\nimport = ["~/.config/alacritty/dank-theme.toml"]\n'
SOLAAR = "[Desktop Entry]\nType=Application\nName=Solaar\nExec=solaar --window=hide\n"
TE, MC, RS = "org.gnome.TextEditor", "io.missioncenter.MissionCenter", "net.nokyan.Resources"


def var_gtk(sb, app_id, *p):
    return os.path.join(sb.home, ".var", "app", app_id, "config", "gtk-4.0", *p)


def flatpak(sb, app_id):
    d = sb.path("flatpak", "app", app_id, "current", "active")
    os.makedirs(os.path.join(d, "files"))
    with open(os.path.join(d, "metadata"), "w") as f:
        f.write("[Application]\nname=%s\nruntime=org.gnome.Platform/x86_64/50\n" % app_id)


def link_var_gtk(sb, app_id):
    """The user points a flatpak's gtk-4.0 at the host one (Flatseal
    guides, dotfiles)."""
    d = os.path.dirname(var_gtk(sb, app_id))
    os.makedirs(d)
    os.symlink(sb.cfg("gtk-4.0"), os.path.join(d, "gtk-4.0"))


def copy_var_gtk(sb, app_id):
    """The user themes a flatpak by hand: a plain copy of DMS's colours."""
    d = var_gtk(sb, app_id)
    os.makedirs(d)
    with open(os.path.join(d, "keep.txt"), "w") as f:
        f.write("mine\n")
    shutil.copy(sb.cfg("gtk-4.0", "dank-colors.css"), os.path.join(d, "dank-colors.css"))


def autostart(sb):
    xd = sb.path("xdg")
    os.makedirs(os.path.join(xd, "autostart"))
    with open(os.path.join(xd, "autostart", "solaar.desktop"), "w") as f:
        f.write(SOLAAR)
    sb.write("autostart/solaar.desktop", SOLAAR)    # Solaar's own "start at login"
    sb.env["XDG_CONFIG_DIRS"] = xd


def launcher(sb):
    """A system launcher appglass copies (gtk3: GTK_THEME on Exec=)."""
    sb.write("applications/solaar.desktop", SOLAAR, base=sb.path("sysdata"))


def uninstall(sb, app_id):
    shutil.rmtree(sb.path("flatpak", "app", app_id))


# name: (families, seed(sb), after_apply(sb) or None, lose: "dir" | "json",
#        leftovers {rel to home: bytes the file holds after remove})
CASES = {
    # (1) a file appglass only edited is recorded as edited
    "dms gtk.css with only the dank import": (
        "gtk4", lambda sb: sb.write("gtk-4.0/gtk.css", DMS_IMPORT), None, "dir", {}),
    "alacritty.toml with only the dank import": (
        "alacritty", lambda sb: sb.write("alacritty/alacritty.toml", ALAC_IMPORT), None,
        "dir", {}),
    "matugen config.toml with only [config]": (
        "alacritty", lambda sb: sb.write("matugen/config.toml", "[config]\n"), "hook", "dir",
        {".local/bin/": "dir"}),
    "the user's own solaar autostart": ("gtk3", autostart, None, "dir", {}),
    "gtk3 launcher copy, ring kept": ("gtk3", launcher, None, "json", {}),
    # a gtk3 copy carries appglass's header (a user's own launcher never does)
    "gtk3 launcher copy, whole state lost": (
        "gtk3", launcher, None, "dir", {".local/share/applications/": "dir"}),
    # (2) nothing through a symlinked dir, no plain copy of a file appglass reads
    "installed flatpak gtk-4.0 symlinked to the host one": (
        "alacritty,gtk4", lambda sb: (sb.write("gtk-4.0/gtk.css", DMS_IMPORT), flatpak(sb, TE),
                                      link_var_gtk(sb, TE)), None, "dir", {}),
    "missioncenter gtk-4.0 symlinked, not installed": (
        "gtk4", lambda sb: (sb.write("gtk-4.0/gtk.css", DMS_IMPORT), link_var_gtk(sb, MC)),
        None, "dir", {}),
    "resources holding a copy of dank-colors.css, not installed": (
        "gtk4", lambda sb: (sb.write("gtk-4.0/gtk.css", DMS_IMPORT), copy_var_gtk(sb, RS)),
        None, "dir", {}),
    # what appglass made from nothing: the ring proves it, else the rest stays
    "gtk.css appglass made, ring kept": ("gtk4", lambda sb: None, None, "json", {}),
    "gtk.css appglass made, whole state lost": (
        "gtk4", lambda sb: None, None, "dir", {".config/gtk-4.0/gtk.css": DMS_IMPORT}),
    # an app uninstalled since apply: its marked files go, the rest is listed
    "missioncenter uninstalled since apply": (
        "gtk4", lambda sb: (sb.write("gtk-4.0/gtk.css", DMS_IMPORT), flatpak(sb, MC)),
        lambda sb: uninstall(sb, MC), "dir", None),
    "missioncenter uninstalled since apply, ring kept": (
        "gtk4", lambda sb: (sb.write("gtk-4.0/gtk.css", DMS_IMPORT), flatpak(sb, MC)),
        lambda sb: uninstall(sb, MC), "json", {}),
}


class RescueCases(unittest.TestCase):
    def setUp(self):
        self.sb = sb = Sandbox()
        sb.seed_dms()
        sb.seed_niri()
        sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        sb.seed("gtk/dank-colors.css", "gtk-3.0/dank-colors.css")
        sb.seed("gtk/dank-colors.css", "gtk-4.0/dank-colors.css")
        self.bin = sb.path("bin")
        os.makedirs(self.bin)
        for c in ("nautilus", "solaar", "alacritty"):
            p = os.path.join(self.bin, c)
            with open(p, "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(p, 0o755)
        os.makedirs(sb.path("sysdata"))
        sb.env.update(PATH=self.bin, FLATPAK_SYSTEM_DIR=sb.path("flatpak"),
                      XDG_DATA_DIRS=sb.path("sysdata"), XDG_CONFIG_DIRS=sb.path("sysconfig"),
                      FLATPAK_USER_DIR=sb.path("no-user-flatpak"))
        self._libexec = gtk4.LIBEXEC_DIRS
        gtk4.LIBEXEC_DIRS = ()
        self.state_dir = os.path.join(sb.state, "appglass")

    def tearDown(self):
        gtk4.LIBEXEC_DIRS = self._libexec
        self.sb.cleanup()

    def tree(self):
        out = {}
        for dp, dns, fns in os.walk(self.sb.home):
            if dp.startswith(os.path.join(self.sb.cache, "appglass")):
                continue
            out[os.path.relpath(dp, self.sb.home) + "/"] = os.path.islink(dp)
            for fn in fns + [d for d in dns if os.path.islink(os.path.join(dp, d))]:
                q = os.path.join(dp, fn)
                rel = os.path.relpath(q, self.sb.home)
                if os.path.islink(q):
                    out[rel] = "-> " + os.readlink(q)
                elif os.path.isfile(q):
                    out[rel] = self.sb.readb(q)
        return out

    def ok(self, *argv, fams=None):
        code, out, err = self.sb.run(*argv, assume=fams)
        self.assertEqual(code, 0, out + err)
        return out + err

    def claims(self, fams):
        env = dict(self.sb.env, APPGLASS_ASSUME_INSTALLED=fams)
        app = core.App(env, out=io.StringIO(), err=io.StringIO(), quiet=True)
        return app, set(core.orphans(app)), {c["path"] for c in core.lost_claims(app)}

    def run_case(self, name):
        fams, seed, after, lose, leftovers = CASES[name]
        sb = self.sb
        seed(sb)
        pre = self.tree()
        user = {k: v for k, v in pre.items() if isinstance(v, bytes)}
        self.ok("apply", "--only", fams, fams=fams)
        if after == "hook":
            self.ok("hook", "install", fams=fams)
        elif after:
            after(sb)
        if lose == "dir":
            shutil.rmtree(self.state_dir)
        else:
            os.remove(os.path.join(self.state_dir, "state.json"))
        # the refusal, doctor and the rescue name the same files
        app, named, claimed = self.claims(fams)
        self.assertTrue(named, "nothing found after the loss")
        self.assertEqual(named, claimed)
        code, out, err = sb.run("apply", "--only", fams, assume=fams)
        self.assertNotEqual(code, 0)
        for p in named:
            self.assertIn(app.env.tilde(p), err)
        code, out, err = sb.run("doctor", assume=fams)
        for p in named:
            self.assertIn(app.env.tilde(p), out + err)
        out = self.ok("adopt", "--rescue", fams=fams)
        recorded = {ln.split("recorded ", 1)[1].split(" (", 1)[0]
                    for ln in out.splitlines() if "adopt --rescue: recorded " in ln}
        self.assertEqual(recorded, {app.env.tilde(p) for p in claimed}, out)
        out += self.ok("remove", fams=fams)
        post = self.tree()
        # nothing of the user's lost or changed
        for rel, data in user.items():
            want = (leftovers or {}).get(rel, data)
            want = want.encode() if isinstance(want, str) else want
            self.assertEqual(post.get(rel), want, "%s\n%s" % (rel, out))
        if leftovers is None:
            # what is left is listed by the rescue, and none of it is marked
            extra = sorted(k for k in post if k not in pre)
            for rel in extra:
                if isinstance(post[rel], bytes):
                    self.assertFalse(core.MARK.search(post[rel]), rel)
                    self.assertIn("~/" + rel, out, out)
        else:
            diff = sorted(k for k in set(pre) | set(post)
                          if pre.get(k) != post.get(k) and k not in leftovers)
            self.assertEqual(diff, [], out)
        for rel, data in (leftovers or {}).items():
            if data == "dir":
                continue                            # a dir appglass may have made: either way
            self.assertEqual(post.get(rel), data.encode() if isinstance(data, str) else data,
                             rel)
            self.assertIn("~/" + rel, out)       # listed for the user
        return out

    def test_cases(self):
        for name in CASES:
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                self.run_case(name)

    def test_symlinked_dir_keeps_the_host_colours(self):
        """r4 B: through the TextEditor link, remove deleted the host
        dank-colors.css (DMS's)."""
        out = self.run_case("installed flatpak gtk-4.0 symlinked to the host one")
        self.assertTrue(os.path.isfile(self.sb.cfg("gtk-4.0", "dank-colors.css")), out)
        self.assertFalse([ln for ln in out.splitlines()
                          if "recorded " in ln and TE in ln], out)


class RingHole(unittest.TestCase):
    """The oldest ring record says appglass made gtk.css, but appglass took
    it out since and DMS wrote its own: that one is not appglass's."""

    def test_dms_file_written_after_a_remove_stays(self):
        sb = Sandbox()
        self.addCleanup(sb.cleanup)
        sb.seed_dms()
        sb.seed_niri()
        sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        sb.seed("gtk/dank-colors.css", "gtk-4.0/dank-colors.css")
        b = sb.path("bin")
        os.makedirs(b)
        with open(os.path.join(b, "nautilus"), "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(os.path.join(b, "nautilus"), 0o755)
        sb.env["PATH"] = b
        old, gtk4.LIBEXEC_DIRS = gtk4.LIBEXEC_DIRS, ()
        self.addCleanup(setattr, gtk4, "LIBEXEC_DIRS", old)
        fams = "alacritty,gtk4"
        gtk = sb.cfg("gtk-4.0", "gtk.css")

        def ok(*a):
            code, out, err = sb.run(*a, assume=fams)
            self.assertEqual(code, 0, out + err)
            return out + err
        ok("apply", "--only", fams)
        ok("remove", "--only", "gtk4")          # alacritty stays: the ring too
        self.assertFalse(os.path.exists(gtk))
        sb.write("gtk-4.0/gtk.css", DMS_IMPORT)  # DMS writes its own
        ok("apply", "--only", "gtk4")
        os.remove(os.path.join(sb.state, "appglass", "state.json"))
        ok("adopt", "--rescue")
        out = ok("remove")
        self.assertEqual(sb.read(gtk), DMS_IMPORT, out)


class EditCreatedRule(unittest.TestCase):
    """The rule itself: created only when nothing is left of the file once
    appglass's lines are out, or the ring shows appglass made it and it
    still holds exactly what appglass made."""

    def test_rest_decides(self):
        undo = lambda t: "".join(ln for ln in t.splitlines(True) if "glass" not in ln)
        fn = lambda t: (t or DMS_IMPORT) + "@import glass;\n"
        made = DMS_IMPORT + "@import glass;\n"
        self.assertEqual(core._edit_created(undo, fn, "@import glass;\n", False), True)
        self.assertEqual(core._edit_created(undo, fn, made, False), False)
        self.assertEqual(core._edit_created(undo, fn, made, True), True)
        self.assertEqual(core._edit_created(undo, fn, "x\n" + made, True), False)

    def test_a_gtk3_copy_carries_its_header(self):
        """The header goes only on a copy appglass made from a system
        launcher; a launcher of the user's own is edited without it."""
        undo = lambda t: gtk3.undo(None, "x.desktop", t)
        copy = gtk3.themed(SOLAAR, mark=True)
        self.assertTrue(core._edit_created(undo, lambda t: copy, copy, False,
                                           gtk3.CREATED_MARK))
        own = gtk3.themed(SOLAAR)
        self.assertFalse(core._edit_created(undo, lambda t: own, own, False,
                                            gtk3.CREATED_MARK))
        self.assertFalse(core._edit_created(undo, lambda t: copy, copy, False))


if __name__ == "__main__":
    unittest.main()
