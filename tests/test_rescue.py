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


class RescueBase(unittest.TestCase):
    def setUp(self):
        self.sb = sb = Sandbox()
        sb.seed_dms()
        sb.seed_niri()
        b = sb.path("bin")
        os.makedirs(b)
        with open(os.path.join(b, "vlc"), "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(os.path.join(b, "vlc"), 0o755)
        os.makedirs(sb.path("sysdata", "applications"))
        with open(sb.path("sysdata", "applications", "vlc.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=VLC\nExec=vlc %U\n")
        sb.env.update(PATH=b + ":/usr/bin:/bin", XDG_DATA_DIRS=sb.path("sysdata"),
                      FLATPAK_SYSTEM_DIR=sb.path("flatpak"),
                      FLATPAK_USER_DIR=sb.path("no-user-flatpak"))
        self.state_dir = os.path.join(sb.state, "appglass")
        self.addCleanup(sb.cleanup)

    def ok(self, *argv, fams):
        code, out, err = self.sb.run(*argv, assume=fams)
        self.assertEqual(code, 0, out + err)
        return out + err

    def kept(self, data):
        """The state dir holds data (the original) somewhere."""
        for dp, _dns, fns in os.walk(self.state_dir):
            for fn in fns:
                if self.sb.readb(os.path.join(dp, fn)) == data:
                    return True
        return False


DUX_MINE = (b'{\n    "floatingWindowTransparency": 0.9,\n    "blurEnabled": false,\n'
            b'    "theme": "mine"\n}')
VLC_MINE = b"[Desktop Entry]\nType=Application\nName=My VLC\nExec=vlc --no-video-title %U\n"


class LinkedOriginal(RescueBase):
    """w2 B1: a file reached through a symlinked dir is left as is by the
    rescue; its original in backup/ is the user's only copy and must
    survive the remove the rescue points to."""

    def dux(self):
        sb = self.sb
        dot = os.path.join(sb.home, "dotfiles", "dfiles")
        os.makedirs(dot)
        with open(os.path.join(dot, "ui-settings.json"), "wb") as f:
            f.write(DUX_MINE)
        os.symlink(dot, sb.cfg("dfiles"))
        return sb.cfg("dfiles", "ui-settings.json"), DUX_MINE, "dux"

    def vlc(self):
        sb = self.sb
        dot = os.path.join(sb.home, "dotfiles", "applications")
        os.makedirs(dot)
        with open(os.path.join(dot, "vlc.desktop"), "wb") as f:
            f.write(VLC_MINE)
        os.symlink(dot, os.path.join(sb.data, "applications"))
        p = os.path.join(sb.data, "applications", "vlc.desktop")
        self.ok("apply", "--only", "qtstyle", fams="qtstyle")
        self.ok("adopt", p, fams="qtstyle")
        return p, VLC_MINE, "qtstyle"

    def check(self, setup):
        sb = self.sb
        p, mine, fams = setup()
        self.ok("apply", "--only", fams, fams=fams)
        self.assertNotEqual(sb.readb(p), mine)
        os.remove(os.path.join(self.state_dir, "state.json"))
        out = self.ok("adopt", "--rescue", fams=fams)
        self.assertIn(core.Env(sb.env).tilde(p), out)
        out = self.ok("remove", fams=fams)
        # never lost: back in place, or kept in backup/ and named
        if sb.readb(p) != mine:
            self.assertTrue(self.kept(mine), out)
            self.assertIn(core.Env(sb.env).tilde(p), out)
            # put back by hand: the next remove takes the state dir out
            with open(p, "wb") as f:
                f.write(mine)
            self.ok("remove", fams=fams)
            self.assertFalse(os.path.exists(self.state_dir))
        self.assertEqual(sb.readb(p), mine)

    def test_merged_json_through_a_linked_dir(self):
        self.check(self.dux)

    def test_adopted_launcher_in_a_linked_dir(self):
        self.check(self.vlc)


class DamagedOriginal(RescueBase):
    """w2 B2: with only state.json lost, a damaged original in backup/ is
    checked against the record the ring's last state.json holds: the good
    copy in the ring goes back, never the damaged bytes."""

    def test_the_rings_copy_goes_back(self):
        sb = self.sb
        p = os.path.join(sb.data, "applications", "vlc.desktop")
        sb.write("applications/vlc.desktop", VLC_MINE.decode(), base=sb.data)
        fams = "qtstyle"
        self.ok("apply", "--only", fams, fams=fams)
        self.ok("adopt", p, fams=fams)
        self.ok("apply", "--only", fams, fams=fams)
        bp = os.path.join(self.state_dir, "backup", core._bname(p))
        with open(bp, "wb") as f:
            f.write(VLC_MINE[:20])
        os.remove(os.path.join(self.state_dir, "state.json"))
        out = self.ok("adopt", "--rescue", fams=fams)
        out += self.ok("remove", fams=fams)
        self.assertEqual(sb.readb(p), VLC_MINE, out)
        self.assertIn("does not match", out)


OBS_MINE = '{\n    "theme": "obsidian",\n    "cssTheme": "Mine"\n}\n'


class ObsidianStateJsonLost(RescueBase):
    """w2 m2: with only state.json lost, the original in backup/ (when the
    file still holds what appglass made of it) and the ring's dir records
    are used: the file comes back byte for byte, the user's empty snippets
    folder stays."""

    def test_backup_and_ring_dirs(self):
        sb = self.sb
        vault = os.path.join(sb.home, "Notes")
        os.makedirs(os.path.join(vault, ".obsidian", "snippets"))
        ap = os.path.join(vault, ".obsidian", "appearance.json")
        with open(ap, "w") as f:
            f.write(OBS_MINE)
        sb.write("obsidian/obsidian.json", '{"vaults": {"a": {"path": "%s", "ts": 1, '
                 '"open": true}}}' % vault)
        fams = "obsidian"
        self.ok("apply", "--only", fams, fams=fams)
        self.assertNotEqual(sb.read(ap), OBS_MINE)
        os.remove(os.path.join(self.state_dir, "state.json"))
        out = self.ok("adopt", "--rescue", fams=fams)
        out += self.ok("remove", fams=fams)
        self.assertEqual(sb.read(ap), OBS_MINE, out)
        self.assertTrue(os.path.isdir(os.path.join(vault, ".obsidian", "snippets")), out)


class AllLinkedStateLost(RescueBase):
    """w2 M1: every file appglass wrote is reached through a symlinked dir
    (dotfiles) and the whole state folder is gone: nothing can be recorded,
    but the files are still appglass's; every command names them."""

    def test_named_everywhere_until_cleaned_by_hand(self):
        sb = self.sb
        dots = os.path.join(sb.home, "dotfiles")
        os.makedirs(os.path.join(dots, "alacritty"))
        mine = b'[general]\nimport = ["~/.config/alacritty/dank-theme.toml"]\n'
        with open(os.path.join(dots, "alacritty", "alacritty.toml"), "wb") as f:
            f.write(mine)
        shutil.move(sb.cfg("niri"), os.path.join(dots, "niri"))
        for d in ("alacritty", "niri"):
            os.symlink(os.path.join(dots, d), sb.cfg(d))
        before = sb.tree_hash(dots)
        shutil.copytree(dots, sb.path("dots-before"), symlinks=True)
        p = sb.cfg("alacritty", "alacritty.toml")
        self.ok("apply", "--only", "alacritty", fams="alacritty")
        self.assertNotEqual(sb.readb(p), mine)
        shutil.rmtree(self.state_dir)
        tp = core.Env(sb.env).tilde(p)
        for argv in (("doctor",), ("remove",), ("apply", "--only", "alacritty"),
                     ("adopt", "--rescue")):
            code, out, err = sb.run(*argv, assume="alacritty")
            self.assertEqual(code, 1, (argv, out + err))
            self.assertIn(tp, out + err, argv)
        code, out, err = sb.run("adopt", "--rescue", assume="alacritty")
        self.assertIn("by hand", out + err)
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "state.json")))
        # cleaned by hand: everything runs again
        shutil.rmtree(dots)
        shutil.copytree(sb.path("dots-before"), dots, symlinks=True)
        self.ok("doctor", fams="alacritty")
        self.ok("apply", "--only", "alacritty", fams="alacritty")
        self.ok("remove", fams="alacritty")
        self.assertEqual(sb.tree_hash(dots), before)

if __name__ == "__main__":
    unittest.main()
