"""The engine (engine spec 2.2, B5 and B5c): every app is handled on install
with no command run, and glass that breaks after an app update heals.

B5: the detect classes (root, game sticky, sensitive, game-launcher), the
AppImage magic, the fingerprint cache, generic routing (gtk3, qtstyle,
gtk4 records), the gate, the units, learn's X11 _NET_WM_PID.
B5c: stale after an update, appglass verify (a stub harness), launch-check
and appglass fail, colour keys as data, verify waiting for a game.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

from fixtures.sandbox import Sandbox, fixture  # noqa: F401  (sets sys.path)
from fixtures.apps import World, elf, desktop, _w, _ln
from fixtures.shimworld import ShimWorld
from appglass import adapters, core, detect, engine, learn, verify

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GTK3 = ["libgtk-3.so.0", "libc.so.6"]
QT6 = ["libQt6Widgets.so.6", "libQt6Gui.so.6", "libQt6Core.so.6"]
GTK4 = ["libgtk-4.so.1", "libc.so.6"]
LS = "org.localsend.localsend_app"


def bin_elf(w, name, needed):
    p = os.path.join(w.bin, name)
    _w(p, elf(needed), 0o755)
    return p


def routes(sb, *extra):
    code, out, err = sb.run("status", "--json", *extra)
    assert code == 0, err
    return {a["key"]: a for a in json.loads(out)["apps"]}


class Classes(unittest.TestCase):
    """detect: the classes of spec 1.3, each with its reason."""

    def setUp(self):
        self.sb = Sandbox()
        self.w = World(self.sb)
        self.sb.env.update(self.w.env())

    def tearDown(self):
        self.sb.cleanup()

    def recs(self):
        return {r["key"]: r for r in detect.scan(core.Env(self.sb.env))}

    def route(self, key):
        app = core.App(self.sb.env, quiet=True)
        return adapters.resolve(self.recs()[key], app.families, app.settings)

    def test_pkexec_runs_as_root(self):
        self.w.exe("gparted", elf(GTK3))
        self.w.app("gparted.desktop", "GParted", "pkexec %s/gparted %%f" % self.w.bin)
        r = self.recs()["gparted"]
        self.assertIn("pkexec", r["classes"]["root"])
        self.assertEqual(r["toolkit"], "gtk3")          # still probed past pkexec
        route = self.route("gparted")
        self.assertEqual(route["state"], "opaque")
        self.assertIn("runs as root", route["reason"])
        self.assertNotEqual(route["effective"], "glass")

    def test_wrapper_script_with_pkexec(self):
        # Timeshift: the launcher runs a script that runs pkexec
        self.w.exe("tool-gtk", elf(GTK3))
        self.w.exe("tool-launcher", "#!/bin/bash\napp_command='tool-gtk'\n"
                                    "if [ \"$(id -u)\" -eq 0 ]; then\n  ${app_command}\nelse\n"
                                    "  pkexec ${app_command}\nfi\n")
        self.w.app("tool-gtk.desktop", "Tool", "tool-launcher")
        r = self.recs()["tool-gtk"]
        self.assertIn("pkexec in tool-launcher", r["classes"]["root"])
        self.assertIn("runs as root", self.route("tool-gtk")["reason"])

    def test_sudo_and_su_c(self):
        self.w.exe("ed1", elf(GTK3))
        self.w.app("a.desktop", "A", "sudo %s/ed1" % self.w.bin)
        self.w.app("b.desktop", "B", "su -c ed1")
        recs = self.recs()
        self.assertIn("sudo", recs["a"]["classes"]["root"])
        self.assertIn("su", recs["b"]["classes"]["root"])

    def test_elevator_flags_that_take_no_value(self):
        # sudo -E/-H/-P take no value; systemd-run -E (--setenv) and -H (--host) do
        rt = detect.root_target
        self.assertEqual(rt(["sudo", "-E", "gparted"]), ("sudo", "gparted"))
        self.assertEqual(rt(["sudo", "-H", "gparted"]), ("sudo", "gparted"))
        self.assertEqual(rt(["sudo", "-P", "gparted"]), ("sudo", "gparted"))
        self.assertEqual(rt(["sudo", "-u", "bob", "gparted"]), ("sudo", "gparted"))
        self.assertEqual(rt(["systemd-run", "-E", "A=1", "--uid=0", "gparted"]),
                         ("systemd-run", "gparted"))
        self.assertEqual(rt(["systemd-run", "--uid=0", "-H", "box", "-P", "gparted"]),
                         ("systemd-run", "gparted"))

    def test_umu_run_and_wine_are_games(self):
        self.w.app("g1.desktop", "G1", "umu-run /home/u/Games/x/game.exe")
        self.w.app("g2.desktop", "G2", "env WINEPREFIX=/p wine C:\\\\x.exe")
        self.w.app("g3.desktop", "G3", "lutris lutris:rungameid/4")
        recs = self.recs()
        for k in ("g1", "g2", "g3"):
            self.assertEqual(recs[k]["toolkit"], "game", k)
            self.assertIn("game", recs[k]["classes"])
            self.assertEqual(self.route(k)["state"], "excluded")
        self.assertIn("umu-run", recs["g1"]["classes"]["game"])

    def test_steamapps_common_is_a_game(self):
        exe = _w(self.sb.path("lib", "steamapps", "common", "Foo", "foo"), elf(GTK3), 0o755)
        self.w.app("foo.desktop", "Foo", exe)
        r = self.recs()["foo"]
        self.assertEqual(r["toolkit"], "game")
        self.assertIn("steamapps/common", r["classes"]["game"])

    def test_sdl_alone_is_a_game(self):
        self.w.exe("sdlgame", elf(["libSDL2-2.0.so.0", "libc.so.6"]))
        self.w.app("sdlgame.desktop", "S", "sdlgame")
        r = self.recs()["sdlgame"]
        self.assertEqual(r["toolkit"], "game")
        self.assertIn("SDL", r["classes"]["game"])

    def test_sensitive_and_game_launcher(self):
        self.w.exe("keepassxc", elf(QT6))
        self.w.app("org.keepassxc.KeePassXC.desktop", "KeePassXC", "keepassxc")
        self.w.exe("lutris", "#!/usr/bin/python3\nimport gi\ngi.require_version('Gtk', '3.0')\n")
        self.w.app("net.lutris.Lutris.desktop", "Lutris", "lutris %U")
        recs = self.recs()
        self.assertIn("sensitive", recs["org.keepassxc.KeePassXC"]["classes"])
        self.assertIn("game-launcher", recs["net.lutris.Lutris"]["classes"])
        self.assertNotIn("game", recs["net.lutris.Lutris"]["classes"])

    def test_sensitive_never_takes_an_injected_route(self):
        app = core.App(self.sb.env, quiet=True)
        rec = {"key": LS, "names": [LS], "toolkit": "flutter", "fp": "x",
               "classes": {"sensitive": "password or secrets app"}}
        r = adapters.resolve(rec, app.families, {"apps": {LS: {"enabled": True}}})
        self.assertEqual(r["state"], "opaque")
        self.assertIn("native routes only", r["reason"])
        rec["classes"] = {"game-launcher": "game launcher"}
        r = adapters.resolve(rec, app.families, {"apps": {LS: {"enabled": True}}})
        self.assertIn("never a preload", r["reason"])

    def test_appimage_magic_weak_evidence(self):
        img = _w(self.sb.path("home", "Applications", "Gimp-3.0.AppImage"),
                 b"\x7fELF\x02\x01\x01\x00AI\x02" + b"\0" * 64, 0o755)
        _w(self.sb.path("home", "Applications", "NotAnImage"), elf(GTK3), 0o755)
        self.w.app("gimp-appimage.desktop", "GIMP", img)
        r = self.recs()["gimp-appimage"]
        self.assertTrue(r["appimage"])
        self.assertFalse(r["strong"])
        self.assertEqual(r["toolkit"], "gtk3")
        route = self.route("gimp-appimage")
        self.assertEqual(route["state"], "opaque")
        self.assertIn("weak evidence", route["reason"])
        self.assertFalse(detect.is_appimage(self.sb.path("home", "Applications", "NotAnImage")))

    def test_strong_evidence(self):
        self.w.exe("g3", elf(GTK3))
        self.w.app("g3.desktop", "G3", "g3")
        r = self.recs()["g3"]
        self.assertTrue(r["strong"])
        self.assertEqual(self.route("g3")["state"], "glass")
        self.assertEqual(self.route("g3")["family"], "gtk3")

    def test_missing_launcher_target_is_not_installed(self):
        """A launcher left behind: one names a client that is not on PATH,
        the other an absolute path that is gone (and its TryExec too)."""
        gone = os.path.join(self.sb.root, "opt", "gone-launcher")
        self.w.app("gone.desktop", "Gone", "gone-client", user=True)
        self.w.app("gone-launcher.desktop", "Gone", '"%s"' % gone, user=True, TryExec=gone)
        self.w.exe("real-tool", elf(GTK3))
        self.w.app("tryexec.desktop", "Try", "%s/real-tool" % self.w.bin, TryExec="no-such-tool")
        recs = self.recs()
        for k in ("gone", "gone-launcher", "tryexec"):
            self.assertFalse(recs[k]["installed"], k)
        self.assertNotEqual(self.route("gone-launcher")["effective"], "glass")

    def test_chromium_browser_is_opaque_with_a_reason(self):
        """Chrome (a flatpak on the Chromium BaseApp): no route, opaque, said why."""
        self.w.flatpak_app("com.google.Chrome", "chrome", {"bin/chrome": elf(["libc.so.6"])},
                           base="app/org.chromium.Chromium.BaseApp/x86_64/25.08")
        self.assertEqual(self.recs()["com.google.Chrome"]["toolkit"], "chromium")
        route = self.route("com.google.Chrome")
        self.assertEqual(route["state"], "opaque")
        self.assertIn("web content has no window alpha", route["reason"])
        self.assertFalse(route["enabled"])

    @unittest.skipUnless(os.path.isfile("/usr/share/applications/timeshift-gtk.desktop"),
                         "no Timeshift on this host")
    def test_real_timeshift_dry(self):
        """B5 Accept 8: the real Timeshift launcher, read only (a throwaway
        HOME; the system dirs are only read)."""
        env = dict(self.sb.env, XDG_DATA_DIRS="/usr/share", PATH="/usr/bin:/bin")
        e = core.Env(env)
        r = detect.detect_desktop(e, "timeshift-gtk.desktop",
                                  ["/usr/share/applications/timeshift-gtk.desktop"])
        self.assertIn("root", r["classes"])
        app = core.App(env, quiet=True)
        route = adapters.resolve(r, app.families, app.settings)
        self.assertEqual(route["state"], "opaque")
        self.assertIn("runs as root", route["reason"])
        self.assertEqual(os.listdir(self.sb.data), [])


class Sticky(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.w = World(self.sb)
        self.sb.env.update(self.w.env())

    def tearDown(self):
        self.sb.cleanup()

    def test_game_once_seen_wins(self):
        self.w.exe("odd", elf(GTK3))
        self.w.app("odd.desktop", "Odd", "odd")
        app = core.App(self.sb.env, quiet=True)
        recs = engine.records(app, write=True)
        r = next(x for x in recs if x["key"] == "odd")
        self.assertEqual(r["toolkit"], "gtk3")
        r["classes"]["game"] = "runtime: wine64-preloader"
        engine.sticky(app, recs, save=True)
        engine.store(app).save()
        app = core.App(self.sb.env, quiet=True)          # a later run: no runtime signal
        r = engine.record_for(app, "odd")
        self.assertEqual(r["toolkit"], "game")
        self.assertIn("game seen before", r["classes"]["game"])
        self.assertEqual(routes(self.sb)["odd"]["state"], "excluded")


class Cache(unittest.TestCase):
    """B5 Accept 6: the fingerprint pass and a run with no change."""

    def setUp(self):
        self.w = ShimWorld()
        for i in range(100):
            p = bin_elf(self.w, "app%03d" % i, GTK3)
            self.w.launcher("org.example.App%03d.desktop" % i, desktop("App %d" % i, p))
        self.env = core.Env(self.w.sb.env)

    def tearDown(self):
        self.w.cleanup()

    def test_cache_reuses_unchanged_records(self):
        recs, changed = engine.scan(self.env, write=True)
        self.assertEqual(len(changed), 100)
        self.assertTrue(os.path.isfile(engine.cache_path(self.env)))
        recs2, changed = engine.scan(self.env)
        self.assertEqual(changed, [])
        self.assertEqual(recs, recs2)
        p = os.path.join(self.w.bin, "app007")
        st = os.stat(p)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))   # a binary update
        recs3, changed = engine.scan(self.env)
        self.assertEqual(changed, ["org.example.App007.desktop"])
        fp = {r["key"]: r["fp"] for r in recs}
        fp3 = {r["key"]: r["fp"] for r in recs3}
        self.assertNotEqual(fp["org.example.App007"], fp3["org.example.App007"])
        self.assertEqual(fp["org.example.App008"], fp3["org.example.App008"])

    def test_a_binary_that_comes_after_its_launcher_is_probed(self):
        # an rpm can write the .desktop file before the binary
        self.w.launcher("org.example.Late.desktop", desktop("Late", "latebin %U"))
        opt = self.w.sb.path("opt", "late")
        self.w.launcher("org.example.LateAbs.desktop", desktop("LateAbs", opt + "/lateabs"))
        recs, _ = engine.scan(self.env, write=True)
        by = {r["key"]: r for r in recs}
        self.assertFalse(by["org.example.Late"]["installed"])
        self.assertFalse(by["org.example.LateAbs"]["installed"])
        bin_elf(self.w, "latebin", GTK3)
        _w(os.path.join(opt, "lateabs"), elf(GTK3), 0o755)
        recs, changed = engine.scan(self.env, write=True)
        by = {r["key"]: r for r in recs}
        self.assertEqual(sorted(changed), ["org.example.Late.desktop",
                                           "org.example.LateAbs.desktop"])
        self.assertTrue(by["org.example.Late"]["installed"])
        self.assertEqual(by["org.example.Late"]["toolkit"], "gtk3")
        self.assertTrue(by["org.example.LateAbs"]["installed"])

    def test_fingerprint_pass_under_10ms(self):
        recs, _ = engine.scan(self.env, write=True)
        files = dict(detect.desktop_files(self.env))
        best = min(self._time(lambda: [engine.fingerprint(self.env, r, files[r["desktop_id"]])
                                       for r in recs]) for _ in range(5))
        self.assertLess(best, 0.010)

    HOOK = ("apply", "--from-hook", "--quiet", "--list-changed")

    def hook_proc(self):
        """The sync script's run, as a process (Python start and imports
        count against the budget)."""
        return subprocess.run([sys.executable, os.path.join(REPO, "bin", "appglass")]
                              + list(self.HOOK), env=self.w.sb.env, capture_output=True,
                              text=True, stdin=subprocess.DEVNULL)

    def full_run(self):
        """A hook run that did the work (it saved its inputs again), not
        the early exit."""
        from appglass import inputs
        p = inputs.path(core.Env(self.w.sb.env))
        before = inputs.sig(p)
        r = self.hook_proc()
        self.assertEqual(r.returncode, 0, r.stderr)
        return inputs.sig(p) != before

    def settle(self):
        self.assertEqual(self.w.run("apply")[0], 0)
        for _ in range(2):
            r = self.hook_proc()
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_change_run_under_50ms(self):
        self.settle()
        runs = []
        for _ in range(5):
            t = time.perf_counter()
            r = self.hook_proc()
            runs.append(time.perf_counter() - t)
            self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertLess(min(runs), 0.050)

    def test_quiet_hook_run_prints_no_warning(self):
        # ~/.config/gtk-4.0/dank-colors.css is missing here: gtk4 warns
        self.assertEqual(self.w.run("apply")[0], 0)
        r = self.hook_proc()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_input_changes_after_a_quiet_run_are_applied(self):
        self.settle()
        sb = self.w.sb
        # a palette change
        dms = os.path.join(sb.cache, "dms", "dms-colors.json")
        doc = sb.json(dms)
        for k in ("primary", "background", "surface", "surface_container"):
            doc["colors"]["dark"][k] = "#102030"
        with open(dms, "w") as f:
            json.dump(doc, f)
        r = self.hook_proc()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("gtk-4.0/dank-glass.css", r.stdout)
        self.assertEqual(self.hook_proc().stdout, "")
        # a file that was missing appears (DMS writes the GTK4 colours)
        self.assertFalse(self.full_run())
        d = os.path.join(sb.config, "gtk-4.0")
        with open(os.path.join(d, "dank-colors.css"), "w") as f:
            f.write("@define-color accent_color #ff0000;\n")
        self.assertTrue(self.full_run())
        self.assertFalse(self.full_run())
        # a launcher added
        p = bin_elf(self.w, "late", GTK3)
        self.w.launcher("org.example.Late.desktop", desktop("Late", p))
        r = self.hook_proc()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("org.example.Late", sb.json(engine.cache_path(core.Env(sb.env))).__repr__())
        # a setting changed by hand
        st = os.path.join(sb.config, "appglass", "settings.json")
        os.makedirs(os.path.dirname(st), exist_ok=True)
        with open(st, "w") as f:
            json.dump({"levels": {"content": 0.42}}, f)
        r = self.hook_proc()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(r.stdout, "")

    def test_a_hook_run_after_a_full_remove_leaves_no_cache(self):
        """remove takes ~/.cache/appglass out; a hook run that comes after
        it (the path unit fired on the way out) has nothing to apply and
        writes no digest back."""
        from appglass import inputs
        self.settle()
        self.assertEqual(self.w.run("remove")[0], 0)
        p = inputs.path(core.Env(self.w.sb.env))
        self.assertFalse(os.path.exists(p))
        for _ in range(2):
            r = self.hook_proc()
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(p))
        self.assertFalse(os.path.exists(os.path.dirname(p)),
                         [os.path.join(d, f) for d, _, fs in os.walk(os.path.dirname(
                             os.path.dirname(p))) for f in fs])

    def test_a_new_appglass_version_runs_in_full(self):
        from appglass import inputs
        self.settle()
        env = core.Env(self.w.sb.env)
        self.assertTrue(inputs.fresh(env, list(self.HOOK)))
        src = os.path.join(REPO, "appglass", "engine.py")
        st = os.stat(src)
        try:
            os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
            self.assertFalse(inputs.fresh(env, list(self.HOOK)))
        finally:
            os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns))

    @staticmethod
    def _time(fn):
        t = time.perf_counter()
        fn()
        return time.perf_counter() - t


class Gate(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.st = engine.Store(core.Env(self.sb.env))

    def tearDown(self):
        self.sb.cleanup()

    def g(self, injected=True, explicit=False, fp="f2"):
        return engine.gate(self.st, {"key": "k", "fp": fp}, injected, explicit)[0]

    def test_states(self):
        self.assertEqual(self.g(), "waiting")
        self.assertEqual(self.g(explicit=True), "glass")
        self.assertEqual(self.g(injected=False), "glass")
        self.st.app("k")["verify"] = {"fp": "f2", "result": "pass"}
        self.assertEqual(self.g(), "glass")
        self.assertEqual(self.g(fp="f3"), "stale")
        self.assertEqual(self.g(fp="f3", explicit=True), "stale")
        self.st.app("k")["verify"] = {"fp": "f2", "result": "fail", "reason": "opaque"}
        self.assertEqual(self.g(), "opaque")
        self.st.app("k")["verify"] = {"fp": "f2", "result": "unverifiable", "reason": "x"}
        self.assertEqual(self.g(), "opaque")
        self.assertEqual(self.g(injected=False), "glass")
        self.st.app("k")["plain"] = {"fp": "f2", "reason": "paused"}
        self.assertEqual(self.g(injected=False), "opaque")


class Routing(unittest.TestCase):
    """B5 Accept 1-4: new apps through the hook, no command typed."""

    def setUp(self):
        self.w = ShimWorld()
        self.world = World(self.w.sb)
        self.sb = self.w.sb
        self.sb.env["APPGLASS_POWER_SUPPLY"] = self.sb.path("no-power")

    def tearDown(self):
        self.w.cleanup()

    def run_ok(self, *argv):
        code, out, err = self.w.run(*argv)
        self.assertEqual(code, 0, err)
        return out + err

    def user_launcher(self, did):
        return self.w.user(".local/share/applications", did)

    def kdl(self):
        return self.sb.read(self.sb.cfg("niri", "appglass.kdl"))

    def test_new_gtk3_and_qt6_apps_glass_on_the_hook(self):
        self.run_ok("apply")                         # the user's one typed apply
        g = bin_elf(self.w, "gtkthing", GTK3)
        q = bin_elf(self.w, "qtthing", QT6)
        self.w.launcher("org.example.GtkThing.desktop",
                        desktop("Gtk Thing", g + " %U", StartupWMClass="org.example.GtkThing"))
        self.w.launcher("org.example.QtThing.desktop", desktop("Qt Thing", q))
        t = time.monotonic()
        self.run_ok("apply", "--from-hook")          # what the path unit runs
        took = time.monotonic() - t
        self.assertLess(took, 1.0)
        gt = self.sb.read(self.user_launcher("org.example.GtkThing.desktop"))
        self.assertIn("GTK_THEME=", gt)
        qt = self.sb.read(self.user_launcher("org.example.QtThing.desktop"))
        self.assertIn("QT_STYLE_OVERRIDE=appglass", qt)
        self.assertIn(q, qt)
        self.assertEqual(len(self.w.tc.builds()), 1)          # the Qt 6 style plugin
        self.assertIn("org\\.example\\.GtkThing", self.kdl())
        r = routes(self.sb)
        self.assertEqual(r["org.example.GtkThing"]["state"], "glass")
        self.assertEqual(r["org.example.QtThing"]["family"], "qtstyle")
        self.run_ok("remove")
        self.assertFalse(os.path.exists(self.user_launcher("org.example.QtThing.desktop")))

    def test_a_qt6_widgets_app_that_also_links_qt_quick_is_not_styled(self):
        """docs/engine.md and routes.md: the Qt style reaches a Widgets app,
        not one that also links Qt Quick/QML (classed qt-quick: its QML
        scene does not draw through a widget style), which keeps the
        fallback."""
        self.run_ok("apply")
        q = bin_elf(self.w, "qmlthing", QT6 + ["libQt6Quick.so.6", "libQt6Qml.so.6"])
        self.w.launcher("org.example.QmlThing.desktop", desktop("Qml Thing", q))
        self.run_ok("apply", "--from-hook")
        self.assertFalse(os.path.exists(self.user_launcher("org.example.QmlThing.desktop")))
        r = routes(self.sb)["org.example.QmlThing"]
        self.assertNotEqual(r.get("family"), "qtstyle")
        self.assertNotEqual(r["state"], "glass")

    def test_a_new_qt_app_gets_the_unfocused_fade(self):
        """The engine's generic Qt launcher passes the fade like the
        hand-listed ones (qtstyle.launcher)."""
        self.sb.set_level(0.8)
        self.run_ok("apply")
        q = bin_elf(self.w, "qtthing", QT6)
        self.w.launcher("org.example.QtThing.desktop", desktop("Qt Thing", q))
        self.run_ok("apply", "--from-hook")
        qt = self.sb.read(self.user_launcher("org.example.QtThing.desktop"))
        self.assertIn(" APPGLASS_CONTENT=0.8 APPGLASS_INACTIVE=0.72 APPGLASS_FADE_MS=180 "
                      "APPGLASS_FADE_EASING=ease-out-cubic " + q, qt)
        self.assertEqual(self.run_ok("set", "inactive.enabled", "false").count("error"), 0)
        self.run_ok("apply", "--from-hook")
        qt = self.sb.read(self.user_launcher("org.example.QtThing.desktop"))
        self.assertIn(" APPGLASS_INACTIVE=0.8 APPGLASS_FADE_MS=0 ", qt)

    def test_stage_carries_what_the_glass_files_import(self):
        """The AppGlass theme imports ~/.config/gtk-3.0/dank-colors.css by
        file:// URL: the hidden session gets it too (else its colours are
        undefined and the window draws clear)."""
        g = bin_elf(self.w, "gtkapp", GTK3)
        self.w.launcher("gtkapp.desktop", desktop("Gtk App", g))
        colours = self.sb.write("gtk-3.0/dank-colors.css", "@define-color window_bg_color #101418;\n")
        self.run_ok("apply", "--only", "gtk3")
        app = core.App(self.sb.env, quiet=True)
        run = self.sb.path("stage-run")
        os.makedirs(run)
        home = verify.stage(app, engine.record_for(app, "gtkapp"), run)
        css = os.path.join(home, ".local/share/themes/AppGlass/gtk-3.0/gtk.css")
        with open(css) as f:
            self.assertIn("file://%s/.config/gtk-3.0/dank-colors.css" % home, f.read())
        with open(os.path.join(home, os.path.relpath(colours, self.sb.home))) as f:
            self.assertIn("window_bg_color", f.read())

    def test_xdg_data_home_outside_home_is_staged_under_the_throwaway_home(self):
        """XDG_DATA_HOME outside HOME: the theme goes to the default data dir
        under the throwaway HOME, where the hidden session looks for it."""
        outside = self.sb.path("outside-data")
        os.makedirs(outside)
        self.sb.env["XDG_DATA_HOME"] = outside
        g = bin_elf(self.w, "gtkapp", GTK3)
        self.w.launcher("gtkapp.desktop", desktop("Gtk App", g))
        self.run_ok("apply", "--only", "gtk3")
        app = core.App(self.sb.env, quiet=True)
        self.assertFalse(app.env.data_home.startswith(app.env.home + os.sep))
        run = self.sb.path("stage-run")
        os.makedirs(run)
        home = verify.stage(app, engine.record_for(app, "gtkapp"), run)
        self.assertTrue(os.path.isfile(
            os.path.join(home, ".local/share/themes/AppGlass/gtk-3.0/gtk.css")))

    def test_glass_files_outside_home_and_xdg_make_the_check_unverifiable(self):
        """A glass file outside HOME and every XDG dir: the throwaway HOME
        cannot hold it, so the check would shoot the plain app. It says it
        cannot check instead of failing the route."""
        g = bin_elf(self.w, "gtkapp", GTK3)
        self.w.launcher("gtkapp.desktop", desktop("Gtk App", g))
        self.run_ok("apply", "--only", "gtk3")
        app = core.App(self.sb.env, quiet=True)
        stray = os.path.join(self.sb.root, "elsewhere", "glass.css")
        os.makedirs(os.path.dirname(stray))
        with open(stray, "w") as f:
            f.write("x")
        app.state.owners["gtk3"]["files"][stray] = {}
        run = self.sb.path("stage-run")
        os.makedirs(run)
        with self.assertRaises(verify.Unstageable) as cm:
            verify.stage(app, engine.record_for(app, "gtkapp"), run)
        self.assertIn("outside", str(cm.exception))

    def test_no_new_family_without_a_full_apply(self):
        self.run_ok("apply", "--only", "gtk4")
        bin_elf(self.w, "qtthing", QT6)
        self.w.launcher("org.example.QtThing.desktop",
                        desktop("Qt Thing", os.path.join(self.w.bin, "qtthing")))
        self.run_ok("apply", "--from-hook")
        self.assertFalse(os.path.exists(self.user_launcher("org.example.QtThing.desktop")))
        self.assertEqual(self.w.tc.builds(), [])

    def test_gtk4_flatpak_gets_the_config_dir_per_launch(self):
        self.world.flatpak_app("org.example.Gtk4App", "gtk4app",
                               {"bin/gtk4app": elf(["libgtk-4.so.1", "libadwaita-1.so.0"])},
                               runtime="org.gnome.Platform/x86_64/49")
        self.run_ok("apply")
        text = self.sb.read(self.user_launcher("org.example.Gtk4App.desktop"))
        execs = re.findall(r"(?m)^Exec=(.*)$", text)
        self.assertTrue(execs[0].startswith(
            "/usr/bin/flatpak run --filesystem=xdg-config/gtk-4.0:ro "), execs)
        self.assertNotIn("ignored-", execs[0])
        # never a persistent flatpak override
        self.assertFalse(os.path.exists(self.w.user(".local/share/flatpak/overrides")))
        self.assertFalse(os.path.exists(self.sb.path("flatpak", "overrides")))
        self.run_ok("apply", "--from-hook")
        self.assertEqual(self.sb.read(self.user_launcher("org.example.Gtk4App.desktop")), text)

    def test_pkexec_app_is_opaque_and_untouched(self):
        bin_elf(self.w, "gparted", GTK3)
        self.w.launcher("gparted.desktop", desktop("GParted",
                                                   "pkexec %s/gparted" % self.w.bin))
        self.run_ok("apply")
        self.assertFalse(os.path.exists(self.user_launcher("gparted.desktop")))
        r = routes(self.sb)["gparted"]
        self.assertEqual(r["state"], "opaque")
        self.assertIn("runs as root", r["reason"])

    def test_games_excluded_no_override(self):
        _w(os.path.join(self.w.bin, "umu-run"), "#!/usr/bin/python3\nimport umu\n", 0o755)
        self.w.launcher("umugame.desktop", desktop("U", "umu-run /x/Games/g/game.exe"))
        exe = _w(self.sb.path("lib", "steamapps", "common", "Foo", "foo"), elf(GTK3), 0o755)
        self.w.launcher("foo.desktop", desktop("Foo", exe, StartupWMClass="foo"))
        self.run_ok("apply")
        self.run_ok("apply", "--from-hook")
        for d in ("umugame.desktop", "foo.desktop"):
            self.assertFalse(os.path.exists(self.user_launcher(d)))
        r = routes(self.sb)
        self.assertEqual(r["umugame"]["state"], "excluded")
        self.assertEqual(r["foo"]["state"], "excluded")
        glass = self.kdl().split("// games")[0]
        self.assertNotIn("foo", glass)

    def test_flatpak_qt_and_user_only_stay_as_they_are(self):
        self.w.launcher("mine.desktop", "")
        os.remove(os.path.join(self.w.usr, "share", "applications", "mine.desktop"))
        q = bin_elf(self.w, "qt5", ["libQt5Widgets.so.5"])
        self.w.launcher("qt5app.desktop", desktop("Q5", q))
        self.run_ok("apply")
        r = routes(self.sb)["qt5app"]
        self.assertEqual(r["state"], "opaque")
        self.assertIn("Qt 5", r["reason"])
        self.assertFalse(os.path.exists(self.user_launcher("qt5app.desktop")))


class Units(unittest.TestCase):
    """B5 Accept 7 (static part): the path unit follows the app dirs and the
    rpm database, with limits; the script waits for the rpm db to settle."""

    def read(self, n):
        with open(os.path.join(REPO, "shims", "sync", n)) as f:
            return f.read()

    def test_path_unit(self):
        t = self.read("appglass-sync.path")
        for p in ("/usr/share/applications", "/usr/lib/sysimage/rpm/rpmdb.sqlite",
                  "/var/lib/flatpak/.changed", "%h/.local/share/flatpak/.changed",
                  "%h/.local/share/applications"):
            self.assertIn("PathChanged=" + p, t)
        # systemd.path(5): a hit trigger limit puts the path unit into a
        # failure mode that stops every watch until a restart (the DMS follow
        # too). A burst must never stop it: no limit; the service settles
        # and coalesces (flock, the rpm db quiet wait)
        self.assertRegex(t, r"(?m)^TriggerLimitBurst=0$")
        self.assertNotRegex(t, r"(?m)^TriggerLimitBurst=[1-9]")
        s = self.read("appglass-sync.service")
        # a start limit hit on the service also fails the path unit
        # (unit-start-limit-hit): none either
        self.assertRegex(s, r"(?m)^StartLimitIntervalSec=0$")
        self.assertNotRegex(s, r"(?m)^StartLimitBurst=")
        self.assertIn("OnCalendar=daily", self.read("appglass-sync.timer"))
        v = self.read("appglass-verify.service")
        self.assertIn("IOSchedulingClass=idle", v)
        self.assertIn("--verify", v)
        # an Electron or WebKit app alone takes more than 512M: an OOM kill
        # there would end verify itself, the queue never done
        m = re.search(r"(?m)^MemoryMax=(\d+)([MG])$", v)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)) * (1024 if m.group(2) == "G" else 1), 2048)

    def test_sync_waits_for_a_quiet_rpmdb(self):
        sb = Sandbox()
        try:
            db = sb.path("rpmdb.sqlite")
            open(db, "w").close()
            fake = sb.path("fake-appglass")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\necho \"$*\" >> %s\n" % sb.path("calls"))
            os.chmod(fake, 0o755)
            env = dict(sb.env, APPGLASS_BIN=fake, APPGLASS_RPMDB=db, APPGLASS_RPMDB_QUIET="2")
            t = time.monotonic()
            r = subprocess.run(["sh", os.path.join(REPO, "bin", "appglass-sync")], env=env,
                               capture_output=True, text=True, timeout=30)
            took = time.monotonic() - t
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertGreaterEqual(took, 1.5)
            with open(sb.path("calls")) as f:
                self.assertIn("--from-hook", f.read())
        finally:
            sb.cleanup()


class X11(unittest.TestCase):
    """learn: an X11 window (niri names xwayland-satellite) is probed by its
    _NET_WM_PID; a Wine process is a game."""

    def setUp(self):
        self.sb = Sandbox()
        self.proc = self.sb.path("proc")
        bridge = _w(self.sb.path("usr", "bin", "xwayland-satellite"), elf(), 0o755)
        client = _w(self.sb.path("usr", "bin", "gimp"), elf(GTK3), 0o755)
        game = _w(self.sb.path("usr", "bin", "wine64-preloader"), elf(), 0o755)
        self.pid(300, bridge, ["/usr/lib64/libxcb.so.1"])
        self.pid(301, client, ["/usr/lib64/libgtk-3.so.0.2400.1"])
        self.pid(302, game, ["/usr/bin/wine64-preloader", "/usr/lib64/wine/ntdll.so",
                             "/usr/lib64/libgtk-3.so.0"])
        wins = [{"id": 1, "app_id": "Gimp", "pid": 300},
                {"id": 2, "app_id": "unmapped-x11", "pid": 300},
                {"id": 3, "app_id": "explorer.exe", "pid": 302}]
        self.sb.env["APPGLASS_NIRI_WINDOWS"] = self.sb.write(
            "w.json", json.dumps(wins), base=self.sb.root)
        self.sb.env["APPGLASS_X11_CLIENTS"] = self.sb.write(
            "x.json", json.dumps([{"pid": 301, "class": "Gimp", "instance": "gimp"}]),
            base=self.sb.root)
        self.sb.env["APPGLASS_PROC"] = self.proc

    def pid(self, pid, exe, libs):
        d = os.path.join(self.proc, str(pid))
        os.makedirs(d)
        with open(os.path.join(d, "maps"), "w") as f:
            for i, lib in enumerate(libs):
                f.write("7f%010x-7f%010x r-xp 00000000 00:1f 1 %s\n" % (i, i + 1, lib))
        os.symlink(exe, os.path.join(d, "exe"))
        with open(os.path.join(d, "cgroup"), "w") as f:
            f.write("0::/user.slice/app.slice/x.scope\n")

    def tearDown(self):
        self.sb.cleanup()

    def test_net_wm_pid_and_wine(self):
        found = learn.learn(core.Env(self.sb.env))
        self.assertEqual(found["Gimp"]["toolkit"], "gtk3")
        self.assertEqual(found["Gimp"]["pid"], 301)
        self.assertTrue(any("_NET_WM_PID 301" in e for e in found["Gimp"]["evidence"]))
        self.assertNotIn("unmapped-x11", found)          # never the bridge's own toolkit
        self.assertEqual(found["explorer.exe"]["toolkit"], "game")

    def test_no_clients_no_guess(self):
        os.remove(self.sb.env["APPGLASS_X11_CLIENTS"])
        found = learn.learn(core.Env(self.sb.env))
        self.assertNotIn("Gimp", found)


class RetiredStatus(unittest.TestCase):
    """status: the retired vencord hand pieces are not listed as hand files."""

    def test_retired_not_listed(self):
        w = ShimWorld()
        try:
            res = w.user(".config/discord/app-1.0.9/resources")
            os.makedirs(res)
            for n in ("app.asar", "_app.asar"):
                open(os.path.join(res, n), "w").close()
            w.hand(".config/Vencord/settings/settings.json", "{}\n")
            script = w.hand(".local/bin/appglass-vencord", "#!/bin/sh\nold\n", 0o755)
            w.hand(".local/share/appglass/appglass-discord.css.tmpl", "old {{x}}\n")
            self.assertEqual(w.run("set", "apps.vencord.enabled", "true")[0], 0)
            self.assertEqual(w.run("adopt")[0], 0)
            self.assertEqual(w.run("apply", "--only", "vencord")[0], 0)
            self.assertFalse(os.path.exists(script))
            code, out, err = w.run("status")
            self.assertEqual(code, 0, err)
            self.assertNotIn("appglass-vencord", out)
            self.assertNotIn("appglass-discord.css.tmpl", out)
        finally:
            w.cleanup()


HARNESS = """#!/bin/sh
echo "$*" >> "%(log)s"
cat "%(res)s"
"""
NOTIFY = """#!/bin/sh
printf '%%s|' "$@" >> "%(log)s"; echo >> "%(log)s"
"""


class Heal(unittest.TestCase):
    """B5c: LocalSend (an injected route) through stale, verify, fail and
    launch-check, with a stub harness and a stub notify-send."""

    def setUp(self):
        self.w = ShimWorld()
        self.sb = self.w.sb
        self.world = World(self.sb)
        self.world.flatpak_app(LS, "localsend", {
            "bin/localsend": elf(["libflutter_linux_gtk.so", "libgtk-3.so.0"])},
            runtime="org.freedesktop.Platform/x86_64/25.08")
        self.hlog, self.res, self.nlog = (self.sb.path(n) for n in ("harness", "res", "notify"))
        for n, t, log in (("stub-harness", HARNESS, self.hlog), ("stub-notify", NOTIFY, self.nlog)):
            p = self.sb.path(n)
            with open(p, "w") as f:
                f.write(t % {"log": log, "res": self.res})
            os.chmod(p, 0o755)
        open(self.nlog, "w").close()
        self.sb.env.update(APPGLASS_VERIFY_HARNESS=self.sb.path("stub-harness"),
                           APPGLASS_NOTIFY=self.sb.path("stub-notify"),
                           APPGLASS_POWER_SUPPLY=self.sb.path("no-power"),
                           APPGLASS_NIRI_WINDOWS=self.sb.write("no-windows.json", "[]",
                                                               base=self.sb.root),
                           APPGLASS_PROC=self.sb.path("empty-proc"))
        os.makedirs(self.sb.path("empty-proc"), exist_ok=True)
        self.result("pass", "background 204 (want 204)")

    def tearDown(self):
        self.w.cleanup()

    def result(self, r, why):
        with open(self.res, "w") as f:
            f.write(json.dumps({"result": r, "reason": why}) + "\n")

    def run_ok(self, *argv, env=None):
        code, out, err = self.w.run(*argv, env=env)
        self.assertEqual(code, 0, err)
        return out + err

    def state(self):
        return routes(self.sb)[LS]

    def store(self):
        return self.sb.json(os.path.join(self.sb.state, "appglass", "engine.json"))

    def marker(self):
        return os.path.join(self.sb.state, "appglass", "plain", LS)

    def notes(self):
        with open(self.nlog) as f:
            return [ln for ln in f.read().splitlines() if ln]

    def harness_calls(self):
        try:
            with open(self.hlog) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def update(self, commit):
        """A flatpak update: a new deploy, the active link moved."""
        d = self.sb.path("flatpak", "app", LS, "x86_64", "stable")
        shutil.copytree(os.path.join(d, "0123abcd"), os.path.join(d, commit), symlinks=True)
        os.remove(os.path.join(d, "active"))
        os.symlink(commit, os.path.join(d, "active"))

    def live(self):
        self.run_ok("apply")
        self.assertEqual(self.state()["state"], "waiting")
        self.assertIn(LS, self.store()["queue"])
        out = self.run_ok("verify", "--queue")
        self.assertIn("pass", out)
        self.assertEqual(self.state()["state"], "glass")
        self.assertTrue(os.path.exists(self.w.user(".local/bin/appglass-localsend")))

    def test_verify_takes_a_family_name(self):
        self.run_ok("apply")
        out = self.run_ok("verify", "localsend")
        self.assertIn("verify: %s: pass" % LS, out)
        self.assertNotIn("no launcher", out)
        self.assertEqual(self.state()["state"], "glass")
        # an unknown name says what verify expects
        code, out, err = self.w.run("verify", "no-such-app")
        self.assertIn("no launcher for no-such-app", out + err)
        self.assertIn("appglass status", out + err)

    def test_stale_then_reverified(self):
        """B5c Accept 1."""
        self.live()
        fp1 = self.state()
        self.update("4567cdef")
        self.run_ok("apply", "--from-hook")
        self.assertEqual(self.state()["state"], "stale")
        self.assertTrue(os.path.exists(self.marker()))
        self.assertIn(LS, self.store()["queue"])
        # glass files are kept (S6): the wrapper reads the marker
        self.assertTrue(os.path.exists(self.w.user(".local/bin/appglass-localsend")))
        self.run_ok("verify", "--queue")
        self.assertEqual(self.state()["state"], "glass")
        self.assertFalse(os.path.exists(self.marker()))
        self.assertEqual(len(self.harness_calls()), 2)
        self.assertNotEqual(self.harness_calls()[0].split()[1], self.harness_calls()[1].split()[1])
        self.assertEqual(self.notes(), [])
        del fp1

    def glass_rule(self):
        t = self.sb.read(self.sb.cfg("niri", "appglass.kdl"))
        return t.split("// glass:", 1)[1].split("// games")[0] if "// glass:" in t else ""

    def test_waiting_again_with_files_on_disk_runs_plain(self):
        """E3: an injected route whose check record is lost (engine.json
        broken, then an update) is "waiting" again with its wrapper on disk:
        it runs plain and has no niri rule until it passes again."""
        self.live()
        self.assertIn("LD_PRELOAD", self.wrapper_argv())
        self.assertIn("localsend_app", self.glass_rule())
        with open(os.path.join(self.sb.state, "appglass", "engine.json"), "w") as f:
            f.write("{broken")
        self.update("feedc0de")
        self.run_ok("apply", "--from-hook")
        s = self.state()
        self.assertEqual(s["state"], "waiting")
        self.assertIn("waiting for a check", s["reason"])
        self.assertTrue(os.path.exists(self.marker()))
        self.assertEqual(self.store()["apps"][LS]["plain"]["why"], "waiting")
        self.assertTrue(os.path.exists(self.w.user(".local/bin/appglass-localsend")))
        argv = self.wrapper_argv()
        self.assertNotIn("LD_PRELOAD", argv)
        self.assertIn("--command=localsend", argv)
        self.assertNotIn("localsend_app", self.glass_rule())
        self.assertIn(LS, self.store()["queue"])
        # a second hook run keeps it so (no flip-flop of the marker)
        self.run_ok("apply", "--from-hook")
        self.assertTrue(os.path.exists(self.marker()))
        # its check passes: glass again, the marker goes
        self.run_ok("verify", "--queue")
        self.assertEqual(self.state()["state"], "glass")
        self.assertFalse(os.path.exists(self.marker()))
        self.assertIn("LD_PRELOAD", self.wrapper_argv())
        self.assertIn("localsend_app", self.glass_rule())
        self.assertEqual(self.notes(), [])

    def test_waiting_marker_survives_a_second_reset(self):
        """E3: a waiting marker read back from plain/ after engine.json is
        lost again stays a waiting one (checked, not paused for good)."""
        self.live()
        with open(os.path.join(self.sb.state, "appglass", "engine.json"), "w") as f:
            f.write("{broken")
        self.update("feedc0de")
        self.run_ok("apply", "--from-hook")
        self.assertTrue(os.path.exists(self.marker()))
        os.remove(os.path.join(self.sb.state, "appglass", "engine.json"))
        with open(os.path.join(self.sb.state, "appglass", "engine.json"), "w") as f:
            f.write("{broken again")
        self.run_ok("apply", "--from-hook")
        self.assertEqual(self.state()["state"], "waiting")
        self.assertIn(LS, self.store()["queue"])
        self.run_ok("verify", "--queue")
        self.assertEqual(self.state()["state"], "glass")
        self.assertFalse(os.path.exists(self.marker()))

    def test_verify_fail_pauses_with_one_notification(self):
        """B5c Accept 2: a broken shim."""
        self.result("fail", "the window is opaque (no glass)")
        self.run_ok("apply")
        self.run_ok("verify", "--queue")
        s = self.state()
        self.assertEqual(s["state"], "opaque")
        self.assertIn("check failed", s["reason"])
        self.assertTrue(os.path.exists(self.marker()))
        self.assertEqual(len(self.notes()), 1)
        self.assertIn("glass paused", self.notes()[0])
        self.assertEqual(self.store()["queue"], [])
        for _ in range(2):                           # no retry on this fingerprint
            self.run_ok("apply", "--from-hook")
            self.assertIn("nothing queued", self.run_ok("verify", "--queue"))
        self.assertEqual(len(self.harness_calls()), 1)
        self.assertEqual(len(self.notes()), 1)
        self.result("pass", "ok")
        self.update("89abcdef")                      # the next fingerprint: checked again
        self.run_ok("apply", "--from-hook")
        self.run_ok("verify", "--queue")
        self.assertEqual(len(self.harness_calls()), 2)
        self.assertEqual(self.state()["state"], "glass")

    def launch_check(self, windows):
        wf = self.sb.write("windows.json", json.dumps(windows), base=self.sb.root)
        proc = self.sb.path("proc")
        os.makedirs(proc, exist_ok=True)
        return self.run_ok("launch-check", LS, "4242", env={
            "APPGLASS_NIRI_WINDOWS": wf, "APPGLASS_PROC": proc, "APPGLASS_LAUNCH_WAIT": "0.2",
            "APPGLASS_LAUNCH_STEP": "0.05"})

    def wrapper_argv(self):
        """Run the installed wrapper with /usr/bin/flatpak replaced by a stub
        that prints its argv."""
        src = self.sb.read(self.w.user(".local/bin/appglass-localsend"))
        fake = self.sb.path("fake-flatpak")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\nprintf '%s\\n' \"$*\"\n")
        os.chmod(fake, 0o755)
        p = self.sb.path("wrapper-copy")
        with open(p, "w") as f:
            f.write(src.replace("/usr/bin/flatpak", fake).replace("setsid -f", "true"))
        env = dict(self.sb.env)
        env["PATH"] = os.path.dirname(shutil.which("jq") or "/usr/bin/jq") + ":/usr/bin:/bin"
        r = subprocess.run(["sh", p], env=env, capture_output=True, text=True, timeout=30)
        return r.stdout.strip()

    def test_launch_with_no_window_twice_then_plain(self):
        """B5c Accept 3."""
        self.live()
        self.assertIn("LD_PRELOAD", self.wrapper_argv())          # first launch: glass
        out = self.launch_check([])
        self.assertIn("failed launch 1", out)
        self.assertFalse(os.path.exists(self.marker()))
        self.assertIn("LD_PRELOAD", self.wrapper_argv())          # second launch: glass
        out = self.launch_check([{"app_id": "other", "pid": 1}])
        self.assertIn("failed launch 2, glass paused", out)
        self.assertTrue(os.path.exists(self.marker()))
        self.assertEqual(len(self.notes()), 1)
        third = self.wrapper_argv()                               # third launch: plain
        self.assertNotIn("LD_PRELOAD", third)
        self.assertIn("--command=localsend", third)
        self.assertEqual(self.state()["state"], "opaque")
        self.launch_check([])
        self.assertEqual(len(self.notes()), 1)

    def test_a_window_clears_the_count(self):
        self.live()
        self.launch_check([])
        self.launch_check([{"app_id": LS, "pid": 999}])
        self.assertNotIn("fails", self.store()["apps"][LS])

    def test_appglass_fail(self):
        self.live()
        self.run_ok("fail", LS, "white window")
        out = self.run_ok("fail", LS, "white window")
        self.assertIn("paused", out)
        self.assertTrue(os.path.exists(self.marker()))
        self.assertEqual(len(self.notes()), 1)
        self.assertIn("white window", self.notes()[0])

    def test_verify_waits_for_a_game(self):
        """B5c Accept 5."""
        self.run_ok("apply")
        wf = self.sb.write("windows.json", json.dumps([{"app_id": "steam_app_570", "pid": 7}]),
                           base=self.sb.root)
        code, out, err = self.w.run("verify", "--queue", env={"APPGLASS_NIRI_WINDOWS": wf})
        self.assertEqual(code, verify.EX_TEMPFAIL)
        self.assertIn("game window", out + err)
        self.assertEqual(self.harness_calls(), [])
        self.assertIn(LS, self.store()["queue"])

    def test_verify_waits_for_a_wine_process(self):
        # a game with no window yet (or one niri does not name) still runs
        self.run_ok("apply")
        _w(self.sb.path("proc-game", "50", "comm"), "bash\n")
        for pid, comm in ((51, "wineserver"), (52, "pressure-vessel")):
            _w(self.sb.path("proc-game", str(pid), "comm"), comm + "\n")
            code, out, err = self.w.run("verify", "--queue",
                                        env={"APPGLASS_PROC": self.sb.path("proc-game")})
            self.assertEqual(code, verify.EX_TEMPFAIL, comm)
            self.assertIn(comm, out + err)
            shutil.rmtree(self.sb.path("proc-game", str(pid)))
        self.assertEqual(self.harness_calls(), [])

    def test_verify_waits_when_niri_cannot_be_asked(self):
        self.run_ok("apply")
        env = {"APPGLASS_NIRI_WINDOWS": self.sb.path("no-such-windows.json")}
        code, out, err = self.w.run("verify", "--queue", env=env)
        self.assertEqual(code, verify.EX_TEMPFAIL)
        self.assertIn("niri", out + err)
        self.assertEqual(self.harness_calls(), [])

    def test_verify_waits_on_low_battery(self):
        self.run_ok("apply")
        bat = self.sb.path("power", "BAT0")
        for n, v in (("type", "Battery"), ("status", "Discharging"), ("capacity", "12")):
            _w(os.path.join(bat, n), v + "\n")
        code, out, err = self.w.run("verify", "--queue",
                                    env={"APPGLASS_POWER_SUPPLY": self.sb.path("power")})
        self.assertEqual(code, verify.EX_TEMPFAIL)
        self.assertEqual(self.harness_calls(), [])

    def test_keys_are_data_per_mode(self):
        lv = json.loads(self.run_ok("levels").strip().splitlines()[-1])
        code, out, err = self.w.run("keys", LS, "dark")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "0e1513:%s,1a2120:%s" % (lv["content"], lv["bar"]))
        code, out, err = self.w.run("keys", LS, "light")
        self.assertEqual(out.strip(), "f4fbf8:%s,e9efed:%s" % (lv["content"], lv["bar"]))
        fp = engine.record_for(core.App(self.sb.env, quiet=True), LS)["fp"]
        p = verify.keys_file(core.Env(self.sb.env), LS, fp, "dark")
        self.assertEqual(self.sb.json(p)["source"], "family defaults")
        with open(p, "w") as f:
            json.dump({"keys": [["101010", "content"]], "source": "measured"}, f)
        self.assertEqual(self.w.run("keys", LS, "dark")[1].strip(), "101010:%s" % lv["content"])
        with open(p, "w") as f:
            json.dump({"keys": [["nothex", "content"]]}, f)
        self.assertEqual(self.w.run("keys", LS, "dark")[0], 1)
        with self.assertRaises(SystemExit) as cm:              # argparse: a usage error
            self.w.run("keys", LS, "sepia")
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.w.run("keys", "org.example.None", "dark")[0], 1)
        self.assertEqual(self.w.run("remove")[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.sb.cache, "appglass")))

    def test_stage_renders_a_waiting_family(self):
        """Spec 1.7: a family that waits for its first check has no files
        yet: verify renders its candidate files into the throwaway HOME
        only, the real one stays as it was."""
        self.run_ok("apply")
        self.assertEqual(self.state()["state"], "waiting")
        wrapper = self.w.user(".local/bin/appglass-localsend")
        self.assertFalse(os.path.exists(wrapper))
        app = core.App(self.sb.env, quiet=True)
        run = self.sb.path("stage-run")
        os.makedirs(run)
        home = verify.stage(app, engine.record_for(app, LS), run)
        staged = os.path.join(home, ".local", "bin", "appglass-localsend")
        self.assertTrue(os.path.isfile(staged))
        self.assertTrue(os.access(staged, os.X_OK))
        with open(staged) as f:
            self.assertNotIn(self.sb.home + "/", f.read())
        self.assertFalse(os.path.exists(wrapper))
        self.assertNotIn("localsend", core.App(self.sb.env, quiet=True).state.owners)
        # the hidden session starts the staged glass launcher
        self.assertIn(staged, verify.launcher_exec(app, engine.record_for(app, LS), home))

    def hidden_wrapper_argv(self, run):
        """Stage the throwaway HOME for LocalSend and run its staged wrapper
        in the hidden session's environment (flatpak a stub)."""
        app = core.App(self.sb.env, quiet=True)
        rec = engine.record_for(app, LS)
        os.makedirs(run)
        home = verify.stage(app, rec, run)
        e = verify.session_env(app.env, home, run, fp=rec.get("fp"))
        e["PATH"] = os.path.dirname(shutil.which("jq") or "/usr/bin/jq") + ":/usr/bin:/bin"
        for k in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
            os.makedirs(e[k], exist_ok=True)
        src = self.sb.read(os.path.join(home, ".local", "bin", "appglass-localsend"))
        fake = self.sb.path("fake-flatpak")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\nprintf '%s\\n' \"$*\"\n")
        os.chmod(fake, 0o755)
        p = os.path.join(run, "wrapper-copy")
        with open(p, "w") as f:
            f.write(src.replace("/usr/bin/flatpak", fake).replace("setsid -f", "true"))
        r = subprocess.run(["sh", p], env=e, capture_output=True, text=True, timeout=30)
        return r.stdout.strip(), home

    def test_hidden_session_reaches_appglass_with_the_repo_under_home(self):
        """The repo under HOME (~/Projects/appGlass): the wrappers call
        "$HOME/Projects/appGlass/bin/appglass". In the hidden session HOME
        is the throwaway one, which holds no repo: without care the wrapper
        finds no appglass, starts the plain app and verify FAILs every
        injected family. The staged wrapper must reach the real repo, and the
        throwaway HOME must not look like a lost state (keys refused)."""
        from unittest import mock
        from appglass import shims
        under = os.path.join(self.sb.home, "Projects", "appGlass")
        os.makedirs(os.path.dirname(under))
        os.symlink(shims.REPO, under)
        with mock.patch.object(shims, "REPO", under), \
                mock.patch.object(shims, "APPGLASS", os.path.join(under, "bin", "appglass")):
            self.live()
            mine = self.sb.read(self.w.user(".local/bin/appglass-localsend"))
            self.assertIn('"$HOME/Projects/appGlass/bin/appglass" keys', mine)
            argv, home = self.hidden_wrapper_argv(self.sb.path("run"))
            self.assertIn("LD_PRELOAD", argv)          # glass: keys and levels answered
            staged = self.sb.read(os.path.join(home, ".local", "bin", "appglass-localsend"))
            self.assertIn('"%s/bin/appglass" keys' % under, staged)

    def test_hidden_session_uses_the_learned_keys(self):
        """Keys learned for this app version are what verify must check,
        not the family defaults: the hidden session reads the same file."""
        self.live()
        app = core.App(self.sb.env, quiet=True)
        fp = engine.record_for(app, LS)["fp"]
        for mode in ("dark", "light"):
            p = verify.keys_file(app.env, LS, fp, mode)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                json.dump({"keys": [["abcdef", "content"]], "source": "measured"}, f)
        argv, _ = self.hidden_wrapper_argv(self.sb.path("run"))
        self.assertIn("APPGLASS_KEYS=abcdef:", argv)

    def test_the_hidden_session_runs_without_the_lock(self):
        """A queue run can last 25 min: the user's apply/set, the plugin's
        sync and the hook run must not wait behind it. The lock is taken
        only around each result (the record and the hook apply)."""
        lock = os.path.join(self.sb.state, "appglass", ".lock")
        probe = self.sb.path("lock-probe")
        stub = self.sb.path("stub-harness")
        with open(stub, "w") as f:
            f.write("#!/bin/sh\n/usr/bin/flock -n -E 9 %s /usr/bin/true 2>>%s.err; echo $? >> %s\ncat %s\n"
                    % (lock, probe, probe, self.res))
        self.run_ok("apply")
        self.assertIn("pass", self.run_ok("verify", "--queue"))
        with open(probe) as f:
            self.assertEqual(f.read().split(), ["0"])
        self.assertEqual(self.state()["state"], "glass")

    def test_a_change_made_while_verify_runs_is_kept(self):
        """The apply after a result runs on the state as it is then, not on
        the one verify read at its start."""
        stub = self.sb.path("stub-harness")
        with open(stub, "w") as f:
            f.write("#!/bin/sh\n%s set apps.gtk3.enabled false >/dev/null 2>&1\ncat %s\n"
                    % (os.path.join(REPO, "bin", "appglass"), self.res))
        self.run_ok("apply")
        self.run_ok("verify", "--queue")
        st = self.sb.json(os.path.join(self.sb.config, "appglass", "settings.json"))
        self.assertIs(st["apps"]["gtk3"]["enabled"], False)
        self.assertEqual(self.state()["state"], "glass")

    def test_one_verify_at_a_time(self):
        import fcntl
        self.run_ok("apply")
        d = os.path.join(self.sb.state, "appglass")
        with open(os.path.join(d, "verify.lock"), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            code, out, err = self.w.run("verify", "--queue")
        self.assertEqual(code, verify.EX_TEMPFAIL)
        self.assertIn("another check", out + err)
        self.assertEqual(self.harness_calls(), [])

    def test_typed_apply_does_not_queue(self):
        self.run_ok("apply", "--only", "gtk3")
        p = os.path.join(self.sb.state, "appglass", "engine.json")
        self.assertFalse(os.path.exists(p) and LS in self.sb.json(p)["queue"])


class Judge(unittest.TestCase):
    """verify.judge: the window shot against the content level."""

    def j(self, hist, level=0.8):
        import collections
        return verify.judge(None, None, level, hist=collections.Counter(hist))

    def test_pass(self):
        self.assertEqual(self.j({204: 9000, 255: 400, 0: 100})["result"], "pass")

    def test_opaque_window(self):
        r = self.j({255: 10000})
        self.assertEqual(r["result"], "fail")
        self.assertIn("opaque", r["reason"])

    def test_wrong_level(self):
        r = self.j({150: 9000, 255: 400})
        self.assertIn("expected 204", r["reason"])

    def test_text_faded_with_the_window(self):
        r = self.j({204: 9000, 200: 300})
        self.assertIn("no opaque text", r["reason"])

    def test_glass_only_in_a_corner(self):
        r = self.j({204: 1000, 120: 900, 255: 8000})
        self.assertEqual(r["result"], "fail")

    def test_bare_holes_fail(self):
        """Native chrome around one glassed WebView: the chrome is alpha 0
        (labels on the bare blur), the view alone at the level."""
        r = self.j({0: 1210915, 153: 838972, 255: 46323}, level=0.60)
        self.assertEqual(r["result"], "fail")
        self.assertIn("alpha 0", r["reason"])
        self.assertEqual(r["bare"], 0.578)
        # the rounded corners and CSD margins of a normal window pass
        self.assertEqual(self.j({0: 117192, 153: 1863983, 255: 8919}, level=0.60)["result"],
                         "pass")

    @staticmethod
    def plane(w, h, bare=(), opaque=(), margin=0):
        """An alpha plane: content 153, the boxes (x0, y0, x1, y1) in bare at
        alpha 0 and those in opaque at 255, a margin of alpha 0 all round."""
        rows = []
        for y in range(h):
            r = bytearray([153]) * w
            for x0, y0, x1, y1 in bare:
                if y0 <= y < y1:
                    r[x0:x1] = bytes(x1 - x0)
            for x0, y0, x1, y1 in opaque:
                if y0 <= y < y1:
                    r[x0:x1] = b"\xff" * (x1 - x0)
            if y < margin or y >= h - margin:
                r = bytearray(w)
            else:
                r[:margin] = bytes(margin)
                r[w - margin:] = bytes(margin)
            rows.append(bytes(r))
        return w, h, b"".join(rows)

    def jp(self, plane, level=0.60):
        return verify.judge(None, None, level, plane=plane)

    def test_a_native_sidebar_shown_after_the_map_is_a_hole(self):
        """A WebView glassed at map, then a native sidebar shown: the sidebar
        is alpha 0 with its labels at 255, a fifth of the window (under the
        quarter of BARE), and the check must still fail."""
        labels = [(30, 10 + 37 * i, 100, 26 + 37 * i) for i in range(7)]
        text = [(160, 40 + 30 * i, 500, 52 + 30 * i) for i in range(4)]
        r = self.jp(self.plane(640, 800, bare=[(0, 0, 130, 800)], opaque=labels + text))
        self.assertEqual(r["result"], "fail")
        self.assertIn("hole", r["reason"])
        self.assertLess(r["bare"], verify.BARE)
        self.assertGreater(r["hole"], 0.10)
        # a narrower one, inside a CSD margin, too
        r = self.jp(self.plane(955, 1200, bare=[(20, 20, 90, 1180)], opaque=text, margin=20))
        self.assertEqual(r["result"], "fail")
        self.assertIn("hole", r["reason"])

    def test_margins_corners_and_thin_gaps_are_not_holes(self):
        text = [(160, 140 + 30 * i, 500, 152 + 30 * i) for i in range(4)]
        corners = [(20, 20, 32, 32), (608, 20, 620, 32), (20, 768, 32, 780), (608, 768, 620, 780)]
        for margin in (20, 40):     # GTK4's CSD shadow margin, at scale 1 and 2
            r = self.jp(self.plane(640, 800, bare=corners, opaque=text, margin=margin))
            self.assertEqual(r["result"], "pass", (margin, r))
            self.assertEqual(r["hole"], 0)
        # a small CSD dialog (GIMP's measured 17.6 %): its margin is a big
        # share, still under BARE, and no hole
        r = self.jp(self.plane(581, 321, opaque=[(60, 60, 400, 80)], margin=20))
        self.assertEqual(r["result"], "pass", r)
        self.assertGreater(r["bare"], 0.15)
        # Qt's window background between the widgets: 10 px gaps
        gaps = [(200, 0, 210, 800), (0, 60, 640, 70), (0, 700, 640, 710)]
        r = self.jp(self.plane(640, 800, bare=gaps, opaque=text))
        self.assertEqual(r["result"], "pass", r)
        self.assertEqual(r["hole"], 0)

    @unittest.skipUnless(shutil.which("ffmpeg"), "no ffmpeg")
    def test_the_shot_is_read_whole(self):
        """judge(png): the plane decoded (width, height, alpha), holes found."""
        w, h, a = self.plane(320, 200, bare=[(0, 0, 90, 200)], opaque=[(120, 20, 300, 40)])
        d = tempfile.mkdtemp()
        try:
            png = os.path.join(d, "w.png")
            rgba = b"".join(b"\x40\x40\x40" + bytes([v]) for v in a)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                            "-s", "%dx%d" % (w, h), "-i", "-", png], input=rgba, check=True)
            self.assertEqual(verify.alpha_plane(None, png), (w, h, a))
            r = verify.judge(None, png, 0.60)
            self.assertEqual(r["result"], "fail")
            self.assertIn("hole", r["reason"])
        finally:
            shutil.rmtree(d)


class Harness(unittest.TestCase):
    def test_session_env_is_clean_but_keeps_the_toolkit_hints(self):
        """The hidden session starts from nothing (env -i), but apps must
        pick the same backend as in the real session: Electron's ozone hint."""
        sb = Sandbox()
        try:
            sb.env.update(ELECTRON_OZONE_PLATFORM_HINT="auto", NIRI_SOCKET="/run/x/niri.sock",
                          WAYLAND_DISPLAY="wayland-1", DBUS_SESSION_BUS_ADDRESS="unix:path=/x",
                          SECRET="1")
            app = core.App(sb.env, quiet=True)
            e = verify.session_env(app.env, sb.path("h"), sb.path("run"))
            self.assertEqual(e["ELECTRON_OZONE_PLATFORM_HINT"], "auto")
            # Electron 38+ picks Wayland from the session type, not the hint
            self.assertEqual(e["XDG_SESSION_TYPE"], "wayland")
            self.assertEqual(e["XDG_CURRENT_DESKTOP"], "niri")
            self.assertEqual(e["XDG_RUNTIME_DIR"], sb.path("run", "rt"))
            self.assertEqual(e["TMPDIR"], sb.path("run", "tmp"))      # not the real /tmp
            self.assertEqual(e["HOME"], sb.path("h"))
            for k in ("WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "SECRET", "DISPLAY"):
                self.assertNotIn(k, e)
            self.assertEqual(e["AGV_REAL_NIRI"], "/run/x/niri.sock")
        finally:
            sb.cleanup()

    def test_sandbox_can_ask_for_the_real_session(self):
        """APPGLASS_VERIFY_HARNESS=builtin: the hidden session itself, with
        the sandbox HOME as the real one (an end-to-end proof)."""
        sb = Sandbox()
        try:
            empty = sb.path("nobin")
            os.makedirs(empty)
            sb.env.update(APPGLASS_VERIFY_HARNESS="builtin", PATH=empty)
            app = core.App(sb.env, quiet=True)
            r = verify.run_harness(app, {"key": "x", "fp": "1"}, 0.6)
            self.assertEqual(r, {"result": "unverifiable", "reason": "gamescope not installed"})
        finally:
            sb.cleanup()

    def test_script_is_valid_and_refuses_the_real_runtime_dir(self):
        p = verify.harness_script()
        self.assertTrue(os.access(p, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", p]).returncode, 0)
        sb = Sandbox()
        try:
            r = subprocess.run(["bash", p, sb.path("run"), "^x$", sb.path("s.png"), "1"],
                               env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": "/run/user/UID"},
                               capture_output=True, text=True, timeout=10)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("refus", r.stdout + r.stderr)
        finally:
            sb.cleanup()

    def test_teardown_kills_gamescope_never_terms_it(self):
        # w2 r2: headless gamescope segfaults on SIGTERM and on its own
        # shutdown after niri ends; either leaves a crash record. SIGKILL
        # dumps nothing: the run kills gamescope, niri ends with its display
        sb = Sandbox()
        try:
            run = sb.path("run")
            rt = os.path.join(run, "rt")
            fake = sb.path("fakebin")
            for d in (rt, fake):
                os.makedirs(d)
            log = os.path.join(run, "gs.log")
            with open(os.path.join(fake, "gamescope"), "w") as f:
                f.write('#!/bin/sh\necho "core=$(ulimit -c)" >>"%s"\n'
                        'trap \'echo TERM >>"%s"; exit 139\' TERM\n'
                        'while [ "$1" != "--" ]; do shift; done; shift\n'
                        '"$@" &\nwait $!\necho own-shutdown >>"%s"\nexit 139\n' % (log, log, log))
            with open(os.path.join(fake, "niri"), "w") as f:
                f.write('#!/bin/sh\n[ "$1" = msg ] && { echo "[]"; exit 0; }\n'
                        's="$XDG_RUNTIME_DIR/niri.wayland-9.$$.sock"; : >"$s"\n'
                        'echo "niri=$$" >>"%s"\n'
                        'while kill -0 $PPID 2>/dev/null; do sleep 0.05; done\n'
                        'rm -f "$s"\n' % log)
            for n in ("gamescope", "niri"):
                os.chmod(os.path.join(fake, n), 0o755)
            with open(os.path.join(run, "cmd.sh"), "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            r = subprocess.run(["bash", verify.harness_script(), run, "^x$", sb.path("s.png"), "1"],
                               env={"PATH": fake + ":/usr/bin:/bin", "XDG_RUNTIME_DIR": rt},
                               capture_output=True, text=True, timeout=30)
            self.assertIn("window=none", r.stdout)
            with open(log) as f:
                got = f.read()
            self.assertIn("core=0", got)
            self.assertNotIn("TERM", got)
            self.assertNotIn("own-shutdown", got)
            npid = int(re.search(r"niri=(\d+)", got).group(1))
            for _ in range(40):
                if not os.path.exists("/proc/%d" % npid):
                    break
                time.sleep(0.05)
            self.assertFalse(os.path.exists("/proc/%d" % npid), "niri left running")
        finally:
            sb.cleanup()


if __name__ == "__main__":
    unittest.main()
