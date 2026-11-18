"""The engine, fix round 1: every failure ends opaque (S7), env routes stop
at one hop (S3, S8), checks are bounded and clean up after themselves, the
root class knows the elevation front-ends, the gate checks routes the user
switched on (S4).
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import unittest

from fixtures.sandbox import Sandbox, fixture  # noqa: F401  (sets sys.path)
from fixtures.apps import World, elf, desktop, _w
from fixtures.shimworld import ShimWorld
from appglass import adapters, core, detect, engine, niri, verify

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GTK3 = ["libgtk-3.so.0", "libc.so.6"]
QT6 = ["libQt6Widgets.so.6", "libQt6Gui.so.6", "libQt6Core.so.6"]
LS = "org.localsend.localsend_app"

HARNESS = """#!/bin/sh
echo "$*" >> "%(log)s"
cat "%(res)s"
"""
NOTIFY = """#!/bin/sh
printf '%%s|' "$@" >> "%(log)s"; echo >> "%(log)s"
"""


def bin_elf(w, name, needed):
    p = os.path.join(w.bin, name)
    _w(p, elf(needed), 0o755)
    return p


def routes(sb):
    code, out, err = sb.run("status", "--json")
    assert code == 0, err
    return {a["key"]: a for a in json.loads(out)["apps"]}


def execs(text):
    return re.findall(r"(?m)^Exec=(.*)$", text)


class Stubbed(unittest.TestCase):
    """A ShimWorld with a stub harness (one result for every app) and a
    stub notify-send."""

    def setUp(self):
        self.w = ShimWorld()
        self.sb = self.w.sb
        self.world = World(self.sb)
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

    def notes(self):
        with open(self.nlog) as f:
            return [ln for ln in f.read().splitlines() if ln]

    def harness_calls(self):
        try:
            with open(self.hlog) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def store(self):
        return self.sb.json(os.path.join(self.sb.state, "appglass", "engine.json"))

    def marker(self, key):
        return os.path.join(self.sb.state, "appglass", "plain", key)

    def user_launcher(self, did):
        return self.w.user(".local/share/applications", did)

    def kdl(self):
        return self.sb.read(self.sb.cfg("niri", "appglass.kdl"))


class NativePlain(Stubbed):
    """S7: a native route (GTK_THEME, the Qt style, the GTK4 flatpak flag)
    that fails its check goes back to the plain app, on its launcher too."""

    def setUp(self):
        super().setUp()
        self.g = bin_elf(self.w, "gtkthing", GTK3)
        self.q = bin_elf(self.w, "qtthing", QT6)
        self.w.launcher("org.example.GtkThing.desktop",
                        desktop("Gtk Thing", self.g + " %U", StartupWMClass="org.example.GtkThing",
                                Actions="new;"))
        self.w.launcher("org.example.QtThing.desktop", desktop("Qt Thing", self.q))
        # Solaar: listed by hand, autostarted from XDG_CONFIG_DIRS
        self.w.exe("solaar", "#!/usr/bin/python3\nimport gi\ngi.require_version('Gtk', '3.0')\n")
        self.w.launcher("solaar.desktop", desktop("Solaar", "solaar"))
        self.sysconf = self.sb.path("etc-xdg")
        _w(os.path.join(self.sysconf, "autostart", "solaar.desktop"),
           desktop("Solaar", "solaar --window=hide"))
        self.sb.env["XDG_CONFIG_DIRS"] = self.sysconf

    def glass_then_fail(self):
        self.run_ok("apply")
        self.assertIn("GTK_THEME=", self.sb.read(self.user_launcher("org.example.GtkThing.desktop")))
        self.assertIn("QT_STYLE_OVERRIDE=", self.sb.read(self.user_launcher("org.example.QtThing.desktop")))
        self.assertIn("GTK_THEME=", self.sb.read(self.sb.cfg("autostart", "solaar.desktop")))
        self.result("fail", "no opaque text on screen")
        out = self.run_ok("verify", "--queue")
        self.assertIn("fail", out)

    def assert_plain(self):
        for p in (self.user_launcher("org.example.GtkThing.desktop"),
                  self.user_launcher("solaar.desktop"), self.sb.cfg("autostart", "solaar.desktop")):
            for ex in execs(self.sb.read(p)):
                self.assertNotIn("GTK_THEME", ex, p)
        for ex in execs(self.sb.read(self.user_launcher("org.example.QtThing.desktop"))):
            self.assertNotRegex(ex, r"QT_|APPGLASS_")
        self.assertNotIn("GtkThing", self.kdl().split("// games")[0])

    def test_fail_then_hook_launchers_run_plain(self):
        self.glass_then_fail()
        for k in ("org.example.GtkThing", "org.example.QtThing", "solaar"):
            self.assertTrue(os.path.exists(self.marker(k)), k)
        # verify ran the hook apply itself: plain already
        self.assert_plain()
        self.run_ok("apply", "--from-hook")
        self.assert_plain()
        r = routes(self.sb)
        self.assertEqual(r["org.example.GtkThing"]["state"], "opaque")
        # the launcher still runs the app
        ex = execs(self.sb.read(self.user_launcher("org.example.GtkThing.desktop")))
        self.assertEqual(ex, [self.g + " %U", "ignored-Gtk Thing"])

    def test_a_broken_engine_json_keeps_the_plain_apps_and_games(self):
        self.glass_then_fail()
        eng = os.path.join(self.sb.state, "appglass", "engine.json")
        for broken in ("{not json", "old"):
            if broken == "old":
                doc = self.sb.json(eng)
                doc["version"] = 0
                doc["games"] = {"some.game": "wine"}
                broken = json.dumps(doc)
            with open(eng, "w") as f:
                f.write(broken)
            self.run_ok("apply", "--from-hook")
            self.assertEqual(self.sb.read(eng + ".bad"), broken)
            for k in ("org.example.GtkThing", "org.example.QtThing", "solaar"):
                self.assertTrue(os.path.exists(self.marker(k)), (k, broken[:9]))
            self.assert_plain()
            self.assertEqual(routes(self.sb)["org.example.GtkThing"]["state"], "opaque")
        self.assertIn("some.game", self.store()["games"])

    def test_two_failed_launches_take_the_launcher_plain(self):
        self.run_ok("apply")
        self.run_ok("fail", "org.example.GtkThing", "white window")
        self.assertIn("GTK_THEME=", self.sb.read(self.user_launcher("org.example.GtkThing.desktop")))
        self.run_ok("fail", "org.example.GtkThing", "white window")
        for ex in execs(self.sb.read(self.user_launcher("org.example.GtkThing.desktop"))):
            self.assertNotIn("GTK_THEME", ex)
        n = [x for x in self.notes() if "Gtk Thing" in x]
        self.assertEqual(len(n), 1)
        self.assertIn("two failed launches", n[0])

    def test_plain_family_is_still_installed(self):
        """Every gtk3 app plain and the listed one gone: a typed apply does
        not take the theme out as 'not installed'."""
        self.glass_then_fail()
        os.remove(os.path.join(self.w.bin, "solaar"))
        self.run_ok("apply", "--from-hook")
        out = self.run_ok("apply")
        self.assertNotIn("gtk3: not installed", out)
        self.assertIn("gtk3", self.w.state()["owners"])
        self.assertTrue(os.path.exists(self.w.user(".local/share/themes/AppGlass/gtk-3.0/gtk.css")))
        for ex in execs(self.sb.read(self.user_launcher("org.example.GtkThing.desktop"))):
            self.assertNotIn("GTK_THEME", ex)

    def test_next_fingerprint_brings_the_glass_back(self):
        self.glass_then_fail()
        self.result("pass", "ok")
        bin_elf(self.w, "gtkthing", GTK3 + ["libm.so.6"])         # an update
        self.run_ok("apply", "--from-hook")
        self.assertFalse(os.path.exists(self.marker("org.example.GtkThing")))
        self.assertIn("GTK_THEME=AppGlass",
                      execs(self.sb.read(self.user_launcher("org.example.GtkThing.desktop")))[0])
        self.assertIn("GtkThing", self.kdl())

    def test_notice_says_why(self):
        """A first check that fails does not say 'after an update'; one
        after an update does."""
        self.glass_then_fail()
        first = [n for n in self.notes() if "Gtk Thing" in n]
        self.assertEqual(len(first), 1)
        self.assertNotIn("after an update", first[0])
        self.assertIn("check failed", first[0])
        self.result("pass", "ok")
        bin_elf(self.w, "gtkthing", GTK3 + ["libm.so.6"])
        self.run_ok("apply", "--from-hook")
        self.run_ok("verify", "--queue")
        self.result("fail", "background alpha 255")
        bin_elf(self.w, "gtkthing", GTK3 + ["libz.so.1"])
        self.run_ok("apply", "--from-hook")
        self.run_ok("verify", "--queue")
        second = [n for n in self.notes() if "Gtk Thing" in n]
        self.assertEqual(len(second), 2)
        self.assertIn("after an update", second[1])

    def test_user_launcher_edited_by_typed_apply_goes_plain(self):
        """A launcher of the user's (shadowing the system one) that a typed
        apply edited: a FAIL takes our prefix out again, theirs stays."""
        mine = self.w.hand(".local/share/applications/org.example.GtkThing.desktop",
                           desktop("My Thing", "env FOO=1 " + self.g))
        before = self.sb.read(mine)
        self.run_ok("apply")
        self.assertIn("GTK_THEME=AppGlass", self.sb.read(mine))
        self.result("fail", "no opaque text on screen")
        self.run_ok("verify", "--queue")
        self.assertEqual(self.sb.read(mine), before)
        self.run_ok("remove")
        self.assertEqual(self.sb.read(mine), before)

    def test_hook_leaves_a_user_launcher_alone(self):
        """S6: an event does not take over a launcher the user made; a typed
        apply does (backed up)."""
        self.run_ok("apply")
        h = bin_elf(self.w, "other", GTK3)
        self.w.launcher("org.example.Other.desktop", desktop("Other", h))
        mine = self.w.hand(".local/share/applications/org.example.Other.desktop",
                           desktop("Other (mine)", h + " --mine"))
        before = self.sb.read(mine)
        out = self.run_ok("apply", "--from-hook")
        self.assertEqual(self.sb.read(mine), before)
        self.assertIn("org.example.Other", out)
        self.run_ok("apply")
        self.assertIn("GTK_THEME=AppGlass", self.sb.read(mine))

    def test_gtk4_flatpak_goes_plain(self):
        self.world.flatpak_app("org.example.Gtk4App", "gtk4app",
                               {"bin/gtk4app": elf(["libgtk-4.so.1", "libadwaita-1.so.0"])},
                               runtime="org.gnome.Platform/x86_64/49")
        self.run_ok("apply")
        p = self.user_launcher("org.example.Gtk4App.desktop")
        self.assertIn("--filesystem=xdg-config/gtk-4.0:ro", self.sb.read(p))
        self.result("fail", "background alpha 255")
        self.run_ok("verify", "--queue")
        self.assertNotIn("--filesystem=xdg-config/gtk-4.0", self.sb.read(p))


class Spawners(unittest.TestCase):
    """S3/S8: no generic env route for an app whose children are other apps
    (terminals, file managers, game launchers); a game with a toolkit is a
    game."""

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

    def test_terminal_by_category(self):
        self.w.exe("xfce4-terminal", elf(GTK3 + ["libvte-2.91.so.0"]))
        self.w.app("xfce4-terminal.desktop", "Xfce Terminal", "xfce4-terminal",
                   Categories="GTK;System;TerminalEmulator;")
        self.w.exe("qterminal", elf(QT6))
        self.w.app("qterminal.desktop", "QTerminal", "qterminal", Categories="Qt;System;")
        for k in ("xfce4-terminal", "qterminal"):
            r = self.route(k)
            self.assertNotEqual(r["effective"], "glass", k)
            self.assertIn("starts other apps", r["reason"], k)

    def test_an_older_detect_cache_is_redone(self):
        """A record cached by the code before these classes gets them: the
        cache version moved on."""
        self.w.exe("xfce4-terminal", elf(GTK3))
        self.w.app("xfce4-terminal.desktop", "Xfce Terminal", "xfce4-terminal",
                   Categories="GTK;System;TerminalEmulator;")
        env = core.Env(self.sb.env)
        recs, _ = engine.scan(env, write=True)
        p = engine.cache_path(env)
        doc = self.sb.json(p)
        for e in doc["apps"].values():
            e["record"]["classes"].pop("spawner", None)
        doc["version"] = 1
        with open(p, "w") as f:
            json.dump(doc, f)
        recs, changed = engine.scan(env, write=True)
        self.assertIn("spawner", {r["key"]: r for r in recs}["xfce4-terminal"]["classes"])

    def test_file_manager(self):
        self.w.exe("thunar", elf(GTK3))
        self.w.app("thunar.desktop", "Thunar", "thunar %F", Categories="System;Utility;FileManager;")
        self.w.exe("pcmanfm-qt", elf(QT6))
        self.w.app("pcmanfm-qt.desktop", "PCManFM-Qt", "pcmanfm-qt", Categories="System;")
        for k in ("thunar", "pcmanfm-qt"):
            r = self.route(k)
            self.assertNotEqual(r["effective"], "glass", k)
            self.assertIn("starts other apps", r["reason"], k)

    def test_game_launchers_get_no_env_route(self):
        self.w.exe("lutris", "#!/usr/bin/python3\nimport gi\ngi.require_version('Gtk', '3.0')\n")
        self.w.app("net.lutris.Lutris.desktop", "Lutris", "lutris %U", Categories="Game;")
        self.w.exe("prismlauncher", elf(QT6))
        self.w.app("org.prismlauncher.PrismLauncher.desktop", "Prism Launcher", "prismlauncher",
                   Categories="Game;ActionGame;")
        for k in ("net.lutris.Lutris", "org.prismlauncher.PrismLauncher"):
            r = self.route(k)
            self.assertIn("game-launcher", self.recs()[k]["classes"], k)
            self.assertNotEqual(r["effective"], "glass", k)

    def test_ides_and_more_game_launchers_get_no_env_route(self):
        self.w.exe("steamtinkerlaunch", "#!/usr/bin/python3\nimport gi\n"
                   "gi.require_version('Gtk', '3.0')\n")
        self.w.app("steamtinkerlaunch.desktop", "STL", "steamtinkerlaunch", Categories="Utility;")
        self.w.exe("gamescope-session", elf(GTK3))
        self.w.app("gamescope-session.desktop", "GS", "gamescope-session", Categories="System;")
        self.w.exe("ide", elf(QT6))
        self.w.app("org.example.Ide.desktop", "IDE", "ide", Categories="Qt;Development;IDE;")
        self.w.exe("cardgame", elf(GTK3))
        self.w.app("org.example.Cards.desktop", "Cards", "cardgame", Categories="GTK;Game;CardGame;")
        for k in ("steamtinkerlaunch", "gamescope-session", "org.example.Ide",
                  "org.example.Cards"):
            r = self.route(k)
            self.assertNotEqual(r["effective"], "glass", k)
            self.assertEqual(r["state"], "opaque", k)
        self.assertIn("game-launcher", self.recs()["steamtinkerlaunch"]["classes"])
        self.assertIn("starts other apps", self.route("org.example.Ide")["reason"])
        self.assertIn("game", self.route("org.example.Cards")["reason"])

    def test_game_category_with_sdl_or_gl_is_a_game(self):
        self.w.exe("sdlgtk", elf(["libSDL2-2.0.so.0"] + GTK3))
        self.w.app("sdlgtk.desktop", "SG", "sdlgtk", Categories="Game;")
        self.w.exe("glqt", elf(["libGL.so.1"] + QT6))
        self.w.app("glqt.desktop", "GQ", "glqt", Categories="Game;ArcadeGame;")
        recs = self.recs()
        for k in ("sdlgtk", "glqt"):
            self.assertEqual(recs[k]["toolkit"], "game", k)
            self.assertIn("game", recs[k]["classes"], k)
            self.assertEqual(self.route(k)["state"], "excluded")
        # a GL app that is not a game stays what it is
        self.w.exe("glview", elf(["libGL.so.1"] + QT6))
        self.w.app("glview.desktop", "GV", "glview", Categories="Graphics;")
        self.assertEqual(self.recs()["glview"]["toolkit"], "qt-widgets")

    def test_a_gtk4_game_stays_out_of_the_games_block(self):
        # w2 r2: a host GTK4 app reads the global gtk.css (the glass CSS)
        # whatever its route; the games block (blur off) would leave it
        # see-through with nothing behind. A GTK3 or Qt game stays in it
        self.w.exe("sdlgtk4", elf(["libSDL2-2.0.so.0", "libgtk-4.so.1", "libc.so.6"]))
        self.w.app("org.example.Gtk4Game.desktop", "G4", "sdlgtk4", Categories="Game;")
        self.w.exe("sdlgtk", elf(["libSDL2-2.0.so.0"] + GTK3))
        self.w.app("sdlgtk.desktop", "SG", "sdlgtk", Categories="Game;")
        app = core.App(self.sb.env, quiet=True)
        recs = self.recs()
        rs = [(recs[k], adapters.resolve(recs[k], app.families, app.settings))
              for k in ("org.example.Gtk4Game", "sdlgtk")]
        self.assertEqual([r["state"] for _, r in rs], ["excluded", "excluded"])
        fb, games, glass, _ = core._niri_ids(rs)
        self.assertNotIn(recs["org.example.Gtk4Game"]["app_ids"][0], games)
        self.assertIn(recs["org.example.Gtk4Game"]["app_ids"][0], glass)
        self.assertIn(recs["sdlgtk"]["app_ids"][0], games)
        self.assertNotIn(recs["sdlgtk"]["app_ids"][0], glass)

    def test_a_plain_gtk4_app_gets_the_fallback(self):
        # w2 r3: GTK4 with no libadwaita draws the Default theme, which does
        # not read the glass colours (measured 255): not Glass, the fallback
        self.w.exe("plaingtk4", elf(["libgtk-4.so.1", "libc.so.6"]))
        self.w.app("org.example.Plain.desktop", "P4", "plaingtk4", Categories="Utility;")
        self.w.exe("adwgtk4", elf(["libgtk-4.so.1", "libadwaita-1.so.0", "libc.so.6"]))
        self.w.app("org.example.Adw.desktop", "A4", "adwgtk4", Categories="Utility;")
        r = self.route("org.example.Plain")
        self.assertEqual(r["effective"], "fallback")
        self.assertIn("without libadwaita", r["reason"])
        self.assertEqual(self.route("org.example.Adw")["effective"], "glass")

    def test_a_gtk4_game_is_in_the_glass_block_in_every_mode(self):
        # w2 r3: out of every block, value and off mode left it under the
        # global opacity on top of the glass CSS (double alpha, text at 0.60)
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.w.exe("sdlgtk4", elf(["libSDL2-2.0.so.0", "libgtk-4.so.1", "libc.so.6"]))
        self.w.app("org.example.Gtk4Game.desktop", "G4", "sdlgtk4", Categories="Game;")
        aid = self.recs()["org.example.Gtk4Game"]["app_ids"][0]
        for mode in ("value", "off", "opaque"):
            with self.subTest(mode=mode):
                self.assertEqual(self.sb.run("set", "fallback.mode", mode)[0], 0)
                code, out, err = self.sb.run("apply", "--all")
                self.assertEqual(code, 0, err)
                kdl = self.sb.read(self.sb.cfg("niri", "appglass.kdl"))
                blk = kdl.split("// glass: apps that paint their own glass")[1].split("}")[0]
                self.assertIn("match app-id=%s" % niri._kdl_string(aid), blk)
                self.assertIn("opacity 1.0", blk)
                self.assertEqual(kdl.count(aid), 1, kdl)
                # a later run (the theme hook) keeps it
                code, out, err = self.sb.run("apply", "--from-hook")
                self.assertEqual(code, 0, err)
                self.assertEqual(self.sb.read(self.sb.cfg("niri", "appglass.kdl")), kdl)


class Elevators(unittest.TestCase):
    """S9: every elevation front-end is the root class, in Exec or in a
    wrapper script."""

    CASES = (
        ("kdesu", "kdesu %(app)s"),
        ("kdesu-c", "kdesu -c %(app)s"),
        ("kdesudo", "kdesudo %(app)s"),
        ("lxqt-sudo", "lxqt-sudo %(app)s"),
        ("lxsudo", "lxsudo %(app)s"),
        ("gksu", "gksu %(app)s"),
        ("gksudo", "gksudo -u root %(app)s"),
        ("beesu", "beesu %(app)s"),
        ("su-to-root", "su-to-root -X -c %(app)s"),
        ("systemd-run", "systemd-run --uid=0 %(app)s"),
        ("systemd-run-p", "systemd-run -p User=root %(app)s"),
        ("libexec-kdesu", "/usr/libexec/kf6/kdesu -c %(app)s"),
    )

    def setUp(self):
        self.sb = Sandbox()
        self.w = World(self.sb)
        self.sb.env.update(self.w.env())
        self.w.exe("tool", elf(QT6))

    def tearDown(self):
        self.sb.cleanup()

    def recs(self):
        return {r["key"]: r for r in detect.scan(core.Env(self.sb.env))}

    def test_exec(self):
        for k, ex in self.CASES:
            self.w.app("%s.desktop" % k, k, ex % {"app": "tool"})
        recs = self.recs()
        app = core.App(self.sb.env, quiet=True)
        for k, _ in self.CASES:
            self.assertIn("root", recs[k]["classes"], k)
            r = adapters.resolve(recs[k], app.families, app.settings)
            self.assertIn("runs as root", r["reason"], k)
            self.assertNotEqual(r["effective"], "glass", k)

    def test_wrapper_script(self):
        for k, ex in self.CASES:
            self.w.exe("w-%s" % k, "#!/bin/sh\nexec %s \"$@\"\n" % (ex % {"app": "tool"}))
            self.w.app("%s.desktop" % k, k, "w-%s" % k)
        recs = self.recs()
        for k, _ in self.CASES:
            self.assertIn("root", recs[k]["classes"], k)

    def test_systemd_run_user_is_not_root(self):
        self.w.app("u.desktop", "U", "systemd-run --user --scope tool")
        self.assertNotIn("root", self.recs()["u"]["classes"])


@unittest.skipUnless(shutil.which("g++") and shutil.which("pkg-config") and
                     subprocess.run(["pkg-config", "--exists", "Qt6Widgets"]).returncode == 0,
                     "no Qt 6 toolchain")
class QtStyleScrub(unittest.TestCase):
    """S8 ship gate for the Qt style: a child of the styled app sees no
    QT_PLUGIN_PATH, QT_STYLE_OVERRIDE or APPGLASS_*; the style still got
    its levels."""

    APP = r"""
#include <QApplication>
#include <QStyle>
#include <QWidget>
#include <cstdio>
#include <cstdlib>
int main(int argc, char **argv) {
    QApplication a(argc, argv);
    QWidget w; w.ensurePolished();
    printf("style=%s\n", a.style()->name().toUtf8().constData());
    fflush(stdout);
    return system("env");
}
"""

    def test_children_get_no_style_env(self):
        tmp = Sandbox()
        try:
            d = tmp.path("build")
            os.makedirs(os.path.join(d, "styles"))
            src = os.path.join(REPO, "shims", "qt-style")
            for n in ("glassstyle.cpp", "appglass.json"):
                shutil.copy(os.path.join(src, n), d)
            moc = subprocess.run(["pkg-config", "--variable=libexecdir", "Qt6Core"],
                                 capture_output=True, text=True).stdout.strip() + "/moc"
            inc = subprocess.run(["pkg-config", "--cflags", "Qt6Widgets"], capture_output=True,
                                 text=True).stdout.split()
            libs = subprocess.run(["pkg-config", "--libs", "Qt6Widgets"], capture_output=True,
                                  text=True).stdout.split()
            subprocess.run([moc] + [x for x in inc if x.startswith("-I")] +
                           ["glassstyle.cpp", "-o", "glassstyle.moc"], cwd=d, check=True)
            subprocess.run(["g++", "-O0", "-shared", "-fPIC", "-std=c++17", "-I.", "glassstyle.cpp",
                            "-o", "styles/libappglass.so", "-w"] + inc + libs, cwd=d, check=True)
            with open(os.path.join(d, "app.cpp"), "w") as f:
                f.write(self.APP)
            subprocess.run(["g++", "-fPIC", "-std=c++17", "-w", "app.cpp", "-o", "app"] + inc + libs,
                           cwd=d, check=True)
            env = {"PATH": "/usr/bin:/bin", "HOME": tmp.home, "QT_QPA_PLATFORM": "offscreen",
                   "QT_PLUGIN_PATH": d, "QT_STYLE_OVERRIDE": "appglass",
                   "APPGLASS_CONTENT": "0.70", "APPGLASS_COLORS": tmp.path("none.json"),
                   "XDG_RUNTIME_DIR": tmp.path("rt")}
            os.makedirs(env["XDG_RUNTIME_DIR"], mode=0o700)
            r = subprocess.run([os.path.join(d, "app")], env=env, capture_output=True,
                               text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("style=appglass", r.stdout)
            child = [ln for ln in r.stdout.splitlines() if "=" in ln and not ln.startswith("style=")]
            self.assertTrue(any(ln.startswith("HOME=") for ln in child), r.stdout)
            for ln in child:
                self.assertFalse(ln.startswith(("QT_PLUGIN_PATH=", "QT_STYLE_OVERRIDE=",
                                                "APPGLASS_")), ln)
        finally:
            tmp.cleanup()


class ExplicitInjected(Stubbed):
    """S4: an injected route the user switched on is checked, and goes
    stale after an update like an automatic one."""

    def setUp(self):
        super().setUp()
        self.world.flatpak_app(LS, "localsend", {
            "bin/localsend": elf(["libflutter_linux_gtk.so", "libgtk-3.so.0"])},
            runtime="org.freedesktop.Platform/x86_64/25.08")

    def state(self):
        return routes(self.sb)[LS]

    def update(self, commit):
        d = self.sb.path("flatpak", "app", LS, "x86_64", "stable")
        shutil.copytree(os.path.join(d, "0123abcd"), os.path.join(d, commit), symlinks=True)
        os.remove(os.path.join(d, "active"))
        os.symlink(commit, os.path.join(d, "active"))

    def test_enabled_by_you_is_checked_then_stale(self):
        self.run_ok("set", "apps.localsend.enabled", "true")
        self.run_ok("apply")
        self.assertEqual(self.state()["state"], "glass")          # kept on (migration)
        self.assertIn(LS, self.store()["queue"])
        self.run_ok("verify", "--queue")
        self.assertEqual(len(self.harness_calls()), 1)
        self.assertEqual(self.state()["state"], "glass")
        self.update("4567cdef")
        self.run_ok("apply", "--from-hook")
        self.assertEqual(self.state()["state"], "stale")
        self.assertTrue(os.path.exists(self.marker(LS)))
        self.assertIn(LS, self.store()["queue"])
        self.run_ok("verify", "--queue")
        self.assertEqual(len(self.harness_calls()), 2)
        self.assertEqual(self.state()["state"], "glass")
        self.assertFalse(os.path.exists(self.marker(LS)))

    def test_unverifiable_keeps_your_on_and_tells_you(self):
        self.run_ok("set", "apps.localsend.enabled", "true")
        self.run_ok("apply")
        self.result("unverifiable", "no window within 10 s")
        self.run_ok("verify", "--queue")
        self.assertEqual(self.state()["state"], "glass")
        self.assertFalse(os.path.exists(self.marker(LS)))
        self.assertEqual(len(self.notes()), 1)
        self.assertIn("could not be checked", self.notes()[0])
        self.run_ok("verify", "--queue")
        self.assertEqual(len(self.notes()), 1)

    def test_unverifiable_without_your_on_runs_plain(self):
        """E3: your on taken back by hand (no longer in settings.json) after
        a check that could not run: opaque, and its wrapper still on disk
        starts the plain app."""
        self.run_ok("set", "apps.localsend.enabled", "true")
        self.run_ok("apply")
        self.result("unverifiable", "no window within 10 s")
        self.run_ok("verify", "--queue")
        p = self.sb.cfg("appglass", "settings.json")
        s = self.sb.json(p)
        s.get("apps", {}).pop("localsend", None)
        with open(p, "w") as f:
            json.dump(s, f)
        self.run_ok("apply", "--from-hook")
        st = self.state()
        self.assertEqual(st["state"], "opaque")
        self.assertIn("could not be checked", st["reason"])
        self.assertTrue(os.path.exists(self.w.user(".local/bin/appglass-localsend")))
        self.assertTrue(os.path.exists(self.marker(LS)))
        self.assertNotIn("localsend_app", self.kdl().split("// games")[0])


class LostState(Stubbed):
    """The lost-state guard covers the engine's commands too."""

    def setUp(self):
        super().setUp()
        bin_elf(self.w, "gtkthing", GTK3)
        self.w.launcher("org.example.GtkThing.desktop", desktop("Gtk Thing", self.w.bin + "/gtkthing"))

    def test_every_command_lists_the_same_orphans(self):
        # the hook run's scan names the launcher appglass wrote too
        self.run_ok("apply")
        launcher = os.path.join(self.sb.home, ".local", "share", "applications",
                                "org.example.GtkThing.desktop")
        self.assertTrue(os.path.exists(launcher))
        os.remove(os.path.join(self.sb.state, "appglass", "state.json"))
        texts = {}
        for argv in (("apply", "--from-hook"), ("fail", "org.example.GtkThing"),
                     ("verify", "--queue"), ("apply",)):
            code, out, err = self.w.run(*argv)
            self.assertNotEqual(code, 0, argv)
            self.assertIn("appglass files are on disk: ", out + err, argv)
            found = (out + err).split("appglass files are on disk: ", 1)[1]
            texts[argv] = found.split(". Nothing written")[0].split("; and ")[0]
        self.assertEqual(len(set(texts.values())), 1, texts)
        self.assertIn("org.example.GtkThing.desktop", texts[("apply",)])

    def test_verify_fail_keys_refuse(self):
        self.run_ok("apply")
        st = os.path.join(self.sb.state, "appglass", "state.json")
        os.remove(st)
        eng = os.path.join(self.sb.state, "appglass", "engine.json")
        before = self.sb.read(eng) if os.path.exists(eng) else None
        for argv in (("verify", "--queue"), ("verify", "org.example.GtkThing"),
                     ("fail", "org.example.GtkThing"), ("fail", "org.example.GtkThing"),
                     ("keys", LS, "dark")):
            code, out, err = self.w.run(*argv)
            self.assertNotEqual(code, 0, argv)
        self.assertEqual(self.harness_calls(), [])
        self.assertEqual(self.sb.read(eng) if os.path.exists(eng) else None, before)
        self.assertFalse(os.path.exists(self.marker("org.example.GtkThing")))
        self.assertFalse(os.path.exists(os.path.join(self.sb.cache, "appglass", "keys")))
        # launch-check stays lenient but writes nothing
        wf = self.sb.write("windows.json", "[]", base=self.sb.root)
        proc = self.sb.path("proc")
        os.makedirs(proc, exist_ok=True)
        for _ in range(2):
            code, out, err = self.w.run("launch-check", "org.example.GtkThing", "4242", env={
                "APPGLASS_NIRI_WINDOWS": wf, "APPGLASS_PROC": proc,
                "APPGLASS_LAUNCH_WAIT": "0.1", "APPGLASS_LAUNCH_STEP": "0.05"})
            self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(eng) if os.path.exists(eng) else None, before)


class Budget(Stubbed):
    """The verify unit: a run checks what fits its time budget, applies after
    each result, and leaves the rest queued."""

    def setUp(self):
        super().setUp()
        for i in range(3):
            g = bin_elf(self.w, "g%d" % i, GTK3)
            self.w.launcher("org.example.G%d.desktop" % i, desktop("G%d" % i, g))
        slow = self.sb.path("slow-harness")
        with open(slow, "w") as f:
            f.write("#!/bin/sh\necho \"$*\" >> %s\nsleep 0.6\ncat %s\n" % (self.hlog, self.res))
        os.chmod(slow, 0o755)
        self.sb.env["APPGLASS_VERIFY_HARNESS"] = slow

    def test_budget_leaves_the_rest_queued(self):
        self.run_ok("apply")
        self.assertEqual(len(self.store()["queue"]), 3)
        self.result("fail", "no opaque text on screen")
        out = self.run_ok("verify", "--queue", env={"APPGLASS_VERIFY_BUDGET": "1"})
        n = len(self.harness_calls())
        self.assertGreaterEqual(n, 1)
        self.assertLess(n, 3)
        self.assertEqual(len(self.store()["queue"]), 3 - n)
        self.assertIn("left queued", out)
        # what was checked is applied already (plain launchers)
        done = [k for k in ("org.example.G0", "org.example.G1", "org.example.G2")
                if k not in self.store()["queue"]]
        for k in done:
            ex = execs(self.sb.read(self.user_launcher(k + ".desktop")))
            self.assertNotIn("GTK_THEME", ex[0])

    def test_unit_timeout_fits_the_budget(self):
        with open(os.path.join(REPO, "shims", "sync", "appglass-verify.service")) as f:
            t = f.read()
        m = re.search(r"(?m)^TimeoutSec=(\d+)(min)?$", t)
        secs = int(m.group(1)) * (60 if m.group(2) else 1)
        self.assertGreaterEqual(secs, verify.BUDGET + 2 * verify.APP_MAX)
        # a stop sends SIGTERM to verify alone (it SIGKILLs the hidden session
        # itself); a SIGTERM to the whole cgroup makes headless gamescope segfault
        self.assertRegex(t, r"(?m)^KillMode=mixed$")
        self.assertEqual(t.count("KillMode="), 1)


class WindowOfTheApp(Stubbed):
    """E2: the hidden session finds the app's window by the pid it started
    (and its children), not only by the first app-id regex; the app-id it
    saw is recorded and used for the niri rule and the launch check."""

    PICK = os.path.join(REPO, "shims", "verify", "agv-pick.py")

    def proc(self, tree, envs=None):
        """A fake /proc: tree {pid: ppid}, envs {pid: [b"K=V"]}."""
        root = self.sb.path("fproc")
        for pid, ppid in tree.items():
            d = os.path.join(root, str(pid))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "stat"), "w") as f:
                f.write("%d (some app) S %d 1 1 0 -1\n" % (pid, ppid))
            with open(os.path.join(d, "environ"), "wb") as f:
                f.write(b"\0".join((envs or {}).get(pid, [b"PATH=/usr/bin"])) + b"\0")
        return root

    def pick(self, windows, apid, rx, proc, rt="/nonexistent/rt"):
        r = subprocess.run([sys.executable, "-I", self.PICK, str(apid), rx],
                           input=json.dumps(windows), capture_output=True, text=True,
                           env={"PATH": "/usr/bin:/bin", "AGV_PROC": proc,
                                "XDG_RUNTIME_DIR": rt}, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_a_child_of_the_launched_pid_with_another_app_id(self):
        # cmd.sh 100 -> sh 101 -> gtkfn 102; 300 is not ours
        proc = self.proc({100: 1, 101: 100, 102: 101, 300: 1})
        ws = [{"id": 7, "app_id": "other", "pid": 300},
              {"id": 9, "app_id": "gtkfn", "pid": 102}]
        self.assertEqual(self.pick(ws, 100, r"^org\.example\.FnGtk2$", proc), "9 gtkfn")

    def test_a_process_of_the_hidden_session_that_left_the_tree(self):
        # a D-Bus activated or double-forked app: reparented, but it carries
        # the private runtime dir
        rt = self.sb.path("run", "rt")
        proc = self.proc({100: 1, 400: 1}, {400: [b"XDG_RUNTIME_DIR=" + rt.encode()]})
        ws = [{"id": 3, "app_id": "fnd", "pid": 400}]
        self.assertEqual(self.pick(ws, 100, r"^x$", proc, rt=rt), "3 fnd")

    def test_the_app_id_regexes_still_count(self):
        proc = self.proc({100: 1, 500: 1})
        ws = [{"id": 4, "app_id": "org.example.FnGtk2", "pid": 500}]
        self.assertEqual(self.pick(ws, 100, r"^nope$|^org\.example\.FnGtk2$", proc),
                         "4 org.example.FnGtk2")
        self.assertEqual(self.pick(ws, 100, r"^nope$", proc), "")

    def test_the_regex_covers_every_name(self):
        rec = {"key": "org.example.FnGtk2", "app_ids": [r"^org\.example\.FnGtk2$"],
               "names": ["org.example.FnGtk2", "gtkfn"]}
        rx = verify.window_rx(rec)
        for n in ("org.example.FnGtk2", "gtkfn"):
            self.assertRegex(n, rx)
        self.assertNotRegex("gtkfnx", rx)
        self.assertEqual(verify.window_rx({"key": "k"}), "^$")

    def test_the_harness_reports_the_app_id(self):
        with open(verify.harness_script()) as f:
            t = f.read()
        self.assertIn("agv-pick.py", t)
        self.assertIn("app_id=", t)
        self.assertEqual(verify.parse_window("noise\nwindow=12 app_id=gtkfn\n"),
                         ("12", "gtkfn"))
        self.assertEqual(verify.parse_window("window=none\n"), (None, None))

    def test_the_seen_app_id_gets_the_niri_rule(self):
        g = bin_elf(self.w, "gtkfn", GTK3)
        self.w.launcher("org.example.FnGtk2.desktop", desktop("Fn Gtk", g))
        self.run_ok("apply")
        self.assertIn(r"org\.example\.FnGtk2", self.kdl())
        self.assertNotIn("^gtkfn$", self.kdl())
        with open(self.res, "w") as f:
            f.write(json.dumps({"result": "pass", "reason": "ok", "app_id": "gtkfn"}) + "\n")
        self.run_ok("verify", "--queue")
        self.assertEqual(self.store()["apps"]["org.example.FnGtk2"]["verify"]["app_id"], "gtkfn")
        glass = self.kdl().split("// glass:", 1)[1].split("// games")[0]
        self.assertIn("^gtkfn$", glass)
        self.assertIn(r"org\.example\.FnGtk2", glass)
        # the launch check knows it too: a window "gtkfn" is a good launch
        app = core.App(self.sb.env, quiet=True)
        self.assertIn("^gtkfn$", engine.record_for(app, "org.example.FnGtk2")["app_ids"])
        # a failed check takes the seen app-id out of the glass rule as well
        with open(self.res, "w") as f:
            f.write(json.dumps({"result": "fail", "reason": "opaque", "app_id": "gtkfn"}) + "\n")
        self.run_ok("verify", "org.example.FnGtk2")
        glass = self.kdl().split("// glass:", 1)[1].split("// games")[0] \
            if "// glass:" in self.kdl() else ""
        self.assertNotIn("gtkfn", glass)

    def test_a_seen_game_app_id_is_a_game_window(self):
        """The app-id seen in the check names the window for the game guard."""
        g = bin_elf(self.w, "gtkfn", GTK3)
        self.w.launcher("org.example.FnGtk2.desktop", desktop("Fn Gtk", g))
        self.run_ok("apply")
        with open(self.res, "w") as f:
            f.write(json.dumps({"result": "pass", "reason": "ok", "app_id": "gtkfn"}) + "\n")
        self.run_ok("verify", "--queue")
        app = core.App(self.sb.env, quiet=True)
        engine.store(app).data["games"]["org.example.FnGtk2"] = "test"
        app._engine_records = None
        wf = self.sb.write("w.json", json.dumps([{"app_id": "gtkfn", "pid": 5}]),
                           base=self.sb.root)
        app.env.environ["APPGLASS_NIRI_WINDOWS"] = wf
        self.assertIn("gtkfn", verify.game_running(app) or "")


class Cleanup(unittest.TestCase):
    """A run stopped by SIGTERM scrubs its private dir; stale agv.* dirs
    are swept; processes of the hidden session do not survive it."""

    def setUp(self):
        self.sb = Sandbox()
        self.base = self.sb.path("rtbase")
        os.makedirs(self.base, mode=0o700)

    def tearDown(self):
        self.sb.cleanup()

    def test_sweep_stale_dirs(self):
        old = os.path.join(self.base, "agv.old1")
        os.makedirs(os.path.join(old, "rt"))
        t = time.time() - 3600
        os.utime(old, (t, t))
        new = os.path.join(self.base, "agv.new1")
        os.makedirs(new)
        other = os.path.join(self.base, "keepme")
        os.makedirs(other)
        os.utime(other, (t, t))
        verify.sweep(self.base)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))
        self.assertTrue(os.path.exists(other))

    def test_kill_session_by_runtime_dir(self):
        run = os.path.join(self.base, "agv.k1")
        rt = os.path.join(run, "rt")
        os.makedirs(rt)
        env = {"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": rt}
        p = subprocess.Popen(["setsid", "sleep", "60"], env=env)
        q = subprocess.Popen(["sleep", "60"], env={"PATH": "/usr/bin:/bin",
                                                   "XDG_RUNTIME_DIR": rt + "x"})
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with open("/proc/%d/cmdline" % p.pid, "rb") as f:
                    if f.read().startswith(b"sleep"):
                        break
                time.sleep(0.02)
            n = verify.kill_session(run)
            self.assertEqual(n, 1)
            self.assertEqual(p.wait(timeout=5), -signal.SIGKILL)
            self.assertIsNone(q.poll())
        finally:
            for x in (p, q):
                if x.poll() is None:
                    x.kill()
                    x.wait()

    def test_sigterm_scrubs_the_private_dir(self):
        """A verify run killed by systemd (SIGTERM) still deletes agv.*."""
        prog = r"""
import os, sys, time
sys.path.insert(0, %(repo)r)
from appglass import verify
verify.install_term_handler()
run = verify.new_run(%(base)r)
print(run, flush=True)
try:
    time.sleep(30)
finally:
    verify._scrub(run)
"""
        p = subprocess.Popen([sys.executable, "-c", prog % {"repo": REPO, "base": self.base}],
                             stdout=subprocess.PIPE, text=True)
        run = p.stdout.readline().strip()
        self.assertTrue(os.path.isdir(run))
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=10)
        self.assertFalse(os.path.exists(run))


class HiddenScope(unittest.TestCase):
    """E1: the hidden session runs in a mount namespace (bwrap) where the
    real systemd user manager is not there: flatpak run cannot register an
    app-flatpak-*.scope (it reaches the manager by the hard-coded
    /run/user/UID/systemd/private), so the app stays in the check's own
    cgroup (appglass-verify.service: MemoryMax, CPUQuota, KillMode). The
    hidden X server's socket is not in the shared /tmp/.X11-unix."""

    def setUp(self):
        self.sb = Sandbox()
        self.bin = self.sb.path("fbin")
        os.makedirs(self.bin)
        for t in ("gamescope", "niri", "dbus-run-session", "ffmpeg"):
            self.exe(t, "#!/bin/sh\nexit 0\n")
        self.base = self.sb.path("rtbase")
        os.makedirs(self.base, mode=0o700)
        self.sb.env.update(APPGLASS_VERIFY_HARNESS="builtin", PATH=self.bin,
                           APPGLASS_VERIFY_BASE=self.base)
        self.argv = None

    def tearDown(self):
        self.sb.cleanup()

    def exe(self, name, text):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, 0o755)
        return p

    def harness(self, rec, mask):
        """run_harness up to the session start: its argv and env."""
        from unittest import mock
        seen = {}

        class Stop(Exception):
            pass

        real = subprocess.Popen

        def popen(argv, *a, **kw):
            if seen or argv[0] == "rm" or "fusermount" in argv[0]:   # the scrub
                return real(argv, *a, **kw)
            seen.update(argv=argv, env=kw.get("env"))
            raise Stop()
        app = core.App(self.sb.env, quiet=True)
        with mock.patch.object(verify, "mask_argv", lambda env, *a, **k: mask), \
                mock.patch.object(verify, "launcher_exec", lambda a, r, h: "true"), \
                mock.patch.object(verify.subprocess, "Popen", popen):
            try:
                r = verify.run_harness(app, rec, 0.6)
            except Stop:
                r = None
        return r, seen

    def test_the_session_starts_inside_the_mask(self):
        mask = ["/x/bwrap", "--dev-bind", "/", "/", "--tmpfs", "/run/user/1/systemd", "--"]
        r, seen = self.harness({"key": "org.x.App", "fp": "1", "flatpak": "org.x.App"}, mask)
        self.assertIsNone(r)
        self.assertEqual(seen["argv"][:len(mask)], mask)
        self.assertEqual(seen["argv"][len(mask)], "dbus-run-session")
        self.assertEqual(seen["env"]["GIO_USE_VFS"], "local")   # no gvfsd on the LAN

    def test_a_flatpak_without_the_mask_is_not_started(self):
        r, seen = self.harness({"key": "org.x.App", "fp": "1", "flatpak": "org.x.App"}, None)
        self.assertEqual(r["result"], "unverifiable")
        self.assertIn("bwrap", r["reason"])
        self.assertEqual(seen, {})
        self.assertEqual(os.listdir(self.base), [])          # nothing left behind

    def test_a_host_app_without_the_mask_still_runs(self):
        r, seen = self.harness({"key": "gedit", "fp": "1"}, None)
        self.assertIsNone(r)
        self.assertEqual(seen["argv"][0], "dbus-run-session")

    def test_the_mask_argv(self):
        env = core.App(self.sb.env, quiet=True).env
        self.assertIsNone(verify.mask_argv(env))                # no bwrap on PATH
        real = shutil.which("bwrap", path="/usr/bin:/bin")
        if not real:
            self.skipTest("no bwrap")
        os.symlink(real, os.path.join(self.bin, "bwrap"))
        os.symlink(shutil.which("sh", path="/usr/bin:/bin"), os.path.join(self.bin, "sh"))
        os.symlink(shutil.which("test", path="/usr/bin:/bin"), os.path.join(self.bin, "test"))
        verify._MASK.clear()
        argv = verify.mask_argv(env)
        if argv is None:
            self.skipTest("bwrap cannot make a mount namespace here")
        self.assertEqual(argv[-1], "--")
        sd = "/run/user/%d/systemd" % os.getuid()
        if os.path.isdir(sd):
            self.assertIn(sd, argv)
        r = subprocess.run(argv + ["sh", "-c", 'test ! -e "$1/private" && test -z "$(ls -A '
                                   '/tmp/.X11-unix)"', "sh", sd],
                           env={"PATH": "/usr/bin:/bin"}, capture_output=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_family_mask_reaches_the_session(self):
        from unittest import mock
        asked = []
        mask = ["/x/bwrap", "--unshare-net", "--"]

        def margv(env, hide=(), nonet=False):
            asked.append((tuple(hide), nonet))
            return mask
        want = {"hide": ["/run/kiri"], "nonet": True}
        with mock.patch.object(verify, "verify_mask", lambda app, rec: want), \
                mock.patch.object(verify, "mask_argv", margv):
            r, seen = self.harness_raw({"key": "kiri", "fp": "1"})
        self.assertIsNone(r)
        self.assertEqual(asked, [(("/run/kiri",), True)])
        self.assertEqual(seen["argv"][:len(mask)], mask)

    def test_a_family_mask_that_cannot_be_made_is_unverifiable(self):
        from unittest import mock
        with mock.patch.object(verify, "verify_mask",
                               lambda app, rec: {"hide": ["/run/kiri"], "nonet": True}), \
                mock.patch.object(verify, "mask_argv", lambda env, *a, **k: None):
            r, seen = self.harness_raw({"key": "kiri", "fp": "1"})
        self.assertEqual(r["result"], "unverifiable")
        self.assertEqual(seen, {})                     # the app never started

    def harness_raw(self, rec):
        """harness() with mask_argv left as the test patched it."""
        from unittest import mock
        seen = {}

        class Stop(Exception):
            pass
        real = subprocess.Popen

        def popen(argv, *a, **kw):
            if seen or argv[0] == "rm" or "fusermount" in argv[0]:
                return real(argv, *a, **kw)
            seen.update(argv=argv, env=kw.get("env"))
            raise Stop()
        app = core.App(self.sb.env, quiet=True)
        with mock.patch.object(verify, "launcher_exec", lambda a, r, h: "true"), \
                mock.patch.object(verify.subprocess, "Popen", popen):
            try:
                r = verify.run_harness(app, rec, 0.6)
            except Stop:
                r = None
        return r, seen

    def test_run_paths_from_the_binary(self):
        run = self.sb.path("run")
        for d in ("eng", "user", "dbus", "other"):
            os.makedirs(os.path.join(run, d))
        open(os.path.join(run, "eng", "engine.sock"), "w").close()
        os.symlink(os.path.join(run, "eng", "engine.sock"), os.path.join(run, "engine.sock"))
        open(os.path.join(run, "app.lock"), "w").close()
        b = self.sb.path("app-bin")
        with open(b, "wb") as f:
            f.write(b"\0ELF..%s/engine.sock\0%s/user/1000\0%s/dbus/system_bus_socket\0"
                    b"%s/gone/x\0%s/app.lock\0" % ((run.encode(),) * 5))
        rec = {"exec": b, "seen": [b]}
        got = verify.run_paths(rec, keys=("app",), run=run)
        self.assertEqual(got, [os.path.join(run, "app.lock"), os.path.join(run, "eng")])
        self.assertEqual(verify.run_paths({"exec": b, "seen": [b]}, keys=("other",), run=run),
                         [os.path.join(run, "app.lock"), os.path.join(run, "eng"),
                          os.path.join(run, "other")])
        self.assertEqual(verify.run_paths({"flatpak": {"x": 1}, "exec": b}, run=run), [])

    def test_the_mask_hides_paths_and_cuts_the_network(self):
        env = core.App(self.sb.env, quiet=True).env
        real = shutil.which("bwrap", path="/usr/bin:/bin")
        if not real:
            self.skipTest("no bwrap")
        for t in ("bwrap", "sh", "test", "ls", "grep", "cat"):
            os.symlink(shutil.which(t, path="/usr/bin:/bin"), os.path.join(self.bin, t))
        d = self.sb.path("svc")
        os.makedirs(d)
        open(os.path.join(d, "daemon.sock"), "w").close()
        f = self.sb.path("lone.lock")
        with open(f, "w") as fh:
            fh.write("held")
        verify._MASK.clear()
        # the system paths too: resolved's varlink socket would answer DNS
        argv = verify.mask_argv(env, hide=[d, f] + verify.system_paths(), nonet=True)
        if argv is None:
            self.skipTest("bwrap cannot make a mount namespace here")
        self.assertIn("--unshare-net", argv)
        r = subprocess.run(argv + ["sh", "-c", 'test -z "$(ls -A "$1")" && test -c "$2" && '
                                   'test "$(grep -c : /proc/net/dev)" = 1 && '
                                   '{ ! command -v getent || ! getent hosts example.com; } && '
                                   '! find /run/systemd -type s 2>/dev/null | grep -q .',
                                   "sh", d, f],
                           env={"PATH": "/usr/bin:/bin"}, capture_output=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(d, "daemon.sock")))   # outside: kept
        self.assertIsNot(verify.mask_argv(env), argv)                    # cached per mask

    def test_the_mask_probe_proves_dns_is_cut(self):
        """Without a network the probe also proves a host name does not
        resolve (resolved answers over a varlink socket in /run/systemd, out of
        any network namespace): a mask that still resolves is refused."""
        from unittest import mock
        env = core.App(self.sb.env, quiet=True).env
        os.symlink("/bin/true", os.path.join(self.bin, "bwrap"))
        seen = []

        def run(argv, **k):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0 if "getent" not in argv[argv.index("-c") + 1] else 1)
        verify._MASK.clear()
        with mock.patch.object(verify.subprocess, "run", run):
            self.assertIsNone(verify.mask_argv(env, hide=(), nonet=True))
            self.assertIn("! getent hosts", seen[-1][seen[-1].index("-c") + 1])
            verify._MASK.clear()
            self.assertIsNotNone(verify.mask_argv(env, hide=(), nonet=False))   # no network cut: no DNS probe
        verify._MASK.clear()

    def test_xdg_dirs_out_of_home_are_staged(self):
        """The hidden session's XDG dirs are the defaults under the throwaway
        HOME: a launcher in an XDG_DATA_HOME out of HOME is staged there (else
        the check starts the plain app and fails)."""
        class E:
            home = "/r/home"
            config_home, data_home = "/r/config", "/r/data"
            state_home, cache_home = "/r/home/.local/state", "/r/home/.cache"
        h = "/x/h"
        self.assertEqual(verify.staged_path(E, h, "/r/data/applications/a.desktop"),
                         "/x/h/.local/share/applications/a.desktop")
        self.assertEqual(verify.staged_path(E, h, "/r/config/appglass/settings.json"),
                         "/x/h/.config/appglass/settings.json")
        self.assertEqual(verify.staged_path(E, h, "/r/home/.local/bin/w"), "/x/h/.local/bin/w")
        self.assertIsNone(verify.staged_path(E, h, "/usr/share/x"))
        self.assertEqual(verify._rehome(E, h, "Exec=/r/data/x /r/home/.local/bin/w"),
                         "Exec=/x/h/.local/share/x /x/h/.local/bin/w")

    def test_the_kdl_has_no_xwayland_satellite(self):
        self.assertIn("xwayland-satellite {\n    off\n}", verify.KDL)
        niri = shutil.which("niri", path="/usr/bin:/bin:/usr/local/bin")
        if not niri:
            self.skipTest("no niri")
        p = self.sb.path("v.kdl")
        with open(p, "w") as f:
            f.write(verify.KDL % {"run": self.sb.path("r")})
        r = subprocess.run([niri, "validate", "-c", p], capture_output=True, text=True,
                           env={"PATH": "/usr/bin:/bin", "HOME": self.sb.home}, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class RpmQuiet(unittest.TestCase):
    """A write to rpmdb.sqlite-wal keeps the sync waiting."""

    def test_wal_write_counts(self):
        sb = Sandbox()
        try:
            db = sb.path("rpmdb.sqlite")
            open(db, "w").close()
            old = time.time() - 60
            os.utime(db, (old, old))
            wal = db + "-wal"
            open(wal, "w").close()
            fake = sb.path("fake-appglass")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\necho \"$*\" >> %s\n" % sb.path("calls"))
            os.chmod(fake, 0o755)
            env = dict(sb.env, APPGLASS_BIN=fake, APPGLASS_RPMDB=db, APPGLASS_RPMDB_QUIET="2",
                       APPGLASS_SYNC_SETTLE="0")
            t = time.monotonic()
            r = subprocess.run(["sh", os.path.join(REPO, "bin", "appglass-sync")], env=env,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            # the wait counts whole seconds (stat %Y, date +%s): a quiet of 2
            # is between 1 and 2 s after a write late in its second
            self.assertGreaterEqual(time.monotonic() - t, 0.9)
        finally:
            sb.cleanup()


if __name__ == "__main__":
    unittest.main()
