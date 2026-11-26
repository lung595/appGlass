"""The generic WebKitGTK route (families/webkit.py): any host app whose
binary links libwebkit2gtk-4.x and libgtk-3 is routed by toolkit, waits for
its check (an injected preload), goes glass when switched on, and keeps its
own family when it has one (Lian Li)."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock

from fixtures.sandbox import Sandbox, fixture  # noqa: F401  (sets sys.path)
from fixtures.apps import elf, desktop, _w
from fixtures.shimworld import ShimWorld
from appglass import adapters, core, engine, verify
from appglass.families import webkit

WK41 = ["libwebkit2gtk-4.1.so.0", "libjavascriptcoregtk-4.1.so.0", "libgtk-3.so.0", "libc.so.6"]
WK6 = ["libwebkitgtk-6.0.so.4", "libgtk-4.so.1", "libc.so.6"]
KEY = "org.example.WebThing"
DID = KEY + ".desktop"
L = ".local/lib/appglass/webkit/"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAPPER = os.path.join(REPO, "shims", "webkit-shim", "appglass-webkit")


def rec(**kw):
    r = {"key": "kiri", "names": ["kiri", "kiri-window"], "toolkit": "webkitgtk",
         "evidence": ["links libwebkit2gtk-4.1.so.0 -> webkitgtk", "links libgtk-3.so.0 -> gtk3"],
         "fp": "f1", "classes": {}, "flatpak": None, "user_only": False,
         "desktop_id": "kiri.desktop", "app_ids": ["^kiri$"]}
    r.update(kw)
    return r


class Accepts(unittest.TestCase):
    def test_gtk3_webkit_host_app(self):
        self.assertIsNone(webkit.accepts(rec()))

    def test_refusals(self):
        self.assertIn("flatpak", webkit.accepts(rec(flatpak="org.x.Y")))
        self.assertIn("launcher of yours", webkit.accepts(rec(user_only=True)))
        self.assertIn("GTK4", webkit.accepts(rec(evidence=["links libwebkitgtk-6.0.so.4 -> webkitgtk"])))
        self.assertIn("libgtk-3", webkit.accepts(rec(evidence=["links libwebkit2gtk-4.1.so.0 -> webkitgtk"])))

    def test_a_script_launcher_is_refused_with_its_reason(self):
        # the shim stays in the first process (the shell) and scrubs itself
        # from what it starts: the app would start plain, and fail its check
        # as "opaque" with no word on why
        with tempfile.TemporaryDirectory() as d:
            sh, bin_ = os.path.join(d, "thing"), os.path.join(d, "thing-bin")
            with open(sh, "w") as f:
                f.write("#!/bin/sh\nexec %s \"$@\"\n" % bin_)
            with open(bin_, "wb") as f:
                f.write(b"\x7fELF" + b"\0" * 60)
            self.assertIn("launcher is a script", webkit.accepts(rec(exec=sh)))
            self.assertIsNone(webkit.accepts(rec(exec=bin_)))
            self.assertIsNone(webkit.accepts(rec(exec=os.path.join(d, "gone"))))

    def test_an_env_launcher_with_an_option_is_refused_with_its_reason(self):
        """Exec=env -u X app: the wrapper makes only plain assignments and
        leaves an option to env, which the shim then loads in and scrubs
        itself from: the app would start plain."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "kiri.desktop")
            for line, ok in (("env -u FOO kiri %U", False), ("env --unset=FOO kiri", False),
                             ("env -i kiri", False), ("env FOO=1 BAR= kiri %U", True),
                             ("kiri --flag -u x", True), ("/usr/bin/env FOO=1 kiri", True)):
                with open(p, "w") as f:
                    f.write("[Desktop Entry]\nType=Application\nName=Kiri\nExec=%s\n" % line)
                why = webkit.accepts(rec(path=p))
                if ok:
                    self.assertIsNone(why, line)
                else:
                    self.assertIn("env with an option", why or "", line)
        self.assertIsNone(webkit.accepts(rec(path=os.path.join(d, "gone.desktop"))))

    def test_resolve_by_toolkit(self):
        fams = core.discover()
        r = adapters.resolve(rec(), fams)
        self.assertEqual((r["adapter"], r["family"], r["state"], r["generic"]),
                         ("webkit-shim", "webkit", "waiting", True))
        on = {"apps": {"kiri": {"enabled": True}}}
        self.assertEqual(adapters.resolve(rec(), fams, on)["state"], "glass")
        off = {"apps": {"kiri": {"enabled": False}}}
        self.assertEqual(adapters.resolve(rec(), fams, off)["state"], "off")
        gtk4 = adapters.resolve(rec(evidence=["links libwebkitgtk-6.0.so.4 -> webkitgtk"]), fams)
        self.assertEqual((gtk4["state"], gtk4["family"]), ("opaque", None))
        self.assertIn("webkit-shim", adapters.routes(rec(), fams))

    def test_the_app_switch_wins_over_the_family_switch(self):
        """apps.webkit (the generic family) is a default for its apps: an
        app's own switch wins, and a family on is no check passed for apps
        that may only appear later."""
        fams = core.discover()
        st = lambda s: adapters.resolve(rec(), fams, s)["state"]
        self.assertEqual(st({"apps": {"webkit": {"enabled": False}, "kiri": {"enabled": True}}}),
                         "glass")
        self.assertEqual(st({"apps": {"webkit": {"enabled": True}}}), "waiting")
        self.assertEqual(st({"apps": {"webkit": {"enabled": False}}}), "off")
        self.assertEqual(st({"apps": {"webkit": {"enabled": True}, "kiri": {"enabled": False}}}),
                         "off")

        class A:
            families = fams
            settings = {"apps": {"webkit": {"enabled": True}}}
        self.assertFalse(engine.explicit_on(A, "webkit", "kiri"))
        A.settings = {"apps": {"webkit": {"enabled": False}, "kiri": {"enabled": True}}}
        self.assertTrue(engine.explicit_on(A, "webkit", "kiri"))

    def test_routes_only_where_the_generic_family_takes_the_app(self):
        """A root app (Timeshift) or one the family refuses gets no route
        chip from a generic family it never reaches."""
        fams = core.discover()
        root = {"key": "timeshift-gtk", "names": ["timeshift-gtk"], "toolkit": "gtk3",
                "classes": {"root": "pkexec"}, "evidence": ["links libgtk-3.so.0 -> gtk3"]}
        self.assertEqual(adapters.routes(root, fams), [])
        self.assertEqual(adapters.routes(rec(classes={"root": "pkexec"}), fams), [])
        self.assertNotIn("webkit-shim", adapters.routes(rec(flatpak="org.x.Y"), fams))
        gtk3 = dict(root, classes={})
        self.assertEqual(adapters.routes(gtk3, fams), ["gtk3"])

    def test_lian_li_keeps_its_family(self):
        r = adapters.resolve(rec(key="com.sgtaziz.lianlilinux",
                                 names=["com.sgtaziz.lianlilinux", "lianli-gui"]), core.discover())
        self.assertEqual((r["adapter"], r["family"]), ("webkit-shim", "lianli"))

    def test_game_launcher_never_preloaded(self):
        r = adapters.resolve(rec(classes={"game-launcher": "x"}), core.discover())
        self.assertEqual(r["state"], "opaque")

    def test_launcher_rewrite_is_idempotent(self):
        t = "[Desktop Entry]\nExec=/usr/lib/kiri/kiri-window ui\n\n[Desktop Action n]\nExec=k --new\nExec=\n"
        once = webkit.launcher(t, "/h/.local/bin/appglass-webkit", "kiri")
        self.assertIn("Exec=/h/.local/bin/appglass-webkit kiri /usr/lib/kiri/kiri-window ui\n", once)
        self.assertIn("Exec=/h/.local/bin/appglass-webkit kiri k --new\n", once)
        self.assertIn("Exec=\n", once)
        self.assertEqual(webkit.launcher(once, "/h/.local/bin/appglass-webkit", "kiri"), once)


class VerifyMask(unittest.TestCase):
    """The hidden check of a WebKitGTK app: off the network, and the /run
    entries its binary names hidden (Kiri: /run/kiri/docker.sock)."""

    def test_the_mask_of_the_family(self):
        from unittest import mock
        seen = []

        def rp(r, keys=(), run="/run"):
            seen.append(list(keys))
            return ["/run/kiri"]
        with mock.patch.object(verify, "run_paths", rp), \
                mock.patch.object(verify, "system_paths", lambda run="/run": []), \
                mock.patch.object(verify, "session_paths", lambda rt=None, prefix=None: []):
            m = webkit.verify_mask(rec())
        self.assertEqual(m, {"hide": ["/run/kiri"], "nonet": True})
        self.assertEqual(seen, [["kiri", "kiri", "kiri-window"]])

    def test_lianli_hides_its_daemon(self):
        from unittest import mock
        from appglass.families import lianli
        with mock.patch.object(verify, "run_paths",
                               lambda r, keys=(), run="/run": ["/run/" + k for k in keys]), \
                mock.patch.object(verify, "system_paths", lambda run="/run": []), \
                mock.patch.object(verify, "session_paths", lambda rt=None, prefix=None: []):
            self.assertEqual(lianli.verify_mask({"key": "x"}),
                             {"hide": ["/run/lianli"], "nonet": True})

    def test_the_system_manager_out_of_reach(self):
        """Lian Li's GUI starts a root unit (systemctl start
        lianli-control-recovery.service, allowed by its polkit rule) over the
        system bus: the check of a WebKitGTK app hides the system bus socket
        and all of /run/systemd (the manager's private socket, its varlink
        sockets under io.systemd.*, and resolved's io.systemd.Resolve, DNS
        out of the namespace without a network)."""
        from appglass.families import lianli
        d = tempfile.mkdtemp()
        try:
            for rel in ("dbus/system_bus_socket", "systemd/private", "systemd/io.systemd.Manager",
                        "systemd/resolve/io.systemd.Resolve"):
                os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
                open(os.path.join(d, rel), "w").close()
            self.assertEqual(verify.system_paths(run=d),
                             [d + "/dbus/system_bus_socket", d + "/systemd"])
            shutil.rmtree(os.path.join(d, "systemd"))
            self.assertEqual(verify.system_paths(run=d), [d + "/dbus/system_bus_socket"])
        finally:
            shutil.rmtree(d)
        from unittest import mock
        with mock.patch.object(verify, "run_paths", lambda r, keys=(), run="/run": []), \
                mock.patch.object(verify, "system_paths", lambda run="/run": ["/run/s"]), \
                mock.patch.object(verify, "session_paths", lambda rt=None, prefix=None: []):
            self.assertEqual(lianli.verify_mask({"key": "x"})["hide"], ["/run/s"])
            self.assertEqual(webkit.verify_mask(rec())["hide"], ["/run/s"])

    def test_the_session_bus_and_lian_li_locks_out_of_reach(self):
        """The check runs its own session bus: the real one's socket and Lian
        Li's session locks in $XDG_RUNTIME_DIR are hidden too."""
        from appglass.families import lianli
        d = tempfile.mkdtemp()
        try:
            for n in ("bus", "lianli-session-3.lock", "lianli-session-3_capture.lock", "other"):
                open(os.path.join(d, n), "w").close()
            self.assertEqual(verify.session_paths(rt=d), [d + "/bus"])
            self.assertEqual(verify.session_paths(rt=d, prefix="lianli"),
                             [d + "/bus", d + "/lianli-session-3.lock",
                              d + "/lianli-session-3_capture.lock"])
            self.assertEqual(verify.session_paths(rt=""), [])
        finally:
            shutil.rmtree(d)
        from unittest import mock
        with mock.patch.object(verify, "run_paths", lambda r, keys=(), run="/run": []), \
                mock.patch.object(verify, "system_paths", lambda run="/run": []), \
                mock.patch.object(verify, "session_paths",
                                  lambda rt=None, prefix=None: ["/rt/bus"] + (["/rt/" + prefix] if prefix else [])):
            self.assertEqual(lianli.verify_mask({"key": "x"})["hide"], ["/rt/bus", "/rt/lianli"])
            self.assertEqual(webkit.verify_mask(rec())["hide"], ["/rt/bus"])

    def test_the_real_kiri_binary(self):
        b = "/usr/lib/kiri/kiri-window"
        if not os.path.isfile(b) or not os.path.isdir("/run/kiri"):
            self.skipTest("no Kiri here")
        self.assertIn("/run/kiri", verify.run_paths({"exec": b, "seen": [b]}, keys=("kiri",)))


class Fingerprint(unittest.TestCase):
    """The check is per app and version: a WebKitGTK update (the library the
    shim works inside, not in the app's package) is a new version too."""

    def setUp(self):
        self.lib = tempfile.mkdtemp(prefix="agl-lib-")
        self.addCleanup(shutil.rmtree, self.lib)
        self.so = os.path.join(self.lib, "libwebkit2gtk-4.1.so.0")
        self.real("2.50.1")
        self.env = core.Env({"HOME": self.lib, "PATH": "/usr/bin"})

    def real(self, ver):
        t = os.path.join(self.lib, "libwebkit2gtk-4.1.so.0.%s" % ver)
        with open(t, "w") as f:
            f.write(ver)
        if os.path.lexists(self.so):
            os.unlink(self.so)
        os.symlink(os.path.basename(t), self.so)
        return t

    def extras(self, r):
        with unittest.mock.patch.object(engine, "LIB_DIRS", (self.lib,)):
            return engine.extras(self.env, r)

    def test_the_library_counts(self):
        x = self.extras(rec())
        hit = [e for e in x if e.startswith("webkitgtk ")]
        self.assertEqual(len(hit), 1, x)
        self.assertIn("libwebkit2gtk-4.1.so.0.2.50.1", hit[0])
        new = self.real("2.52.0")
        self.assertNotEqual(self.extras(rec()), x)
        self.assertIn(new, " ".join(self.extras(rec())))

    def test_only_for_webkitgtk(self):
        r = rec(toolkit="gtk3", evidence=["links libgtk-3.so.0 -> gtk3"])
        self.assertEqual([e for e in self.extras(r) if e.startswith("webkitgtk ")], [])

    def test_no_library_found(self):
        os.unlink(self.so)
        self.assertEqual([e for e in self.extras(rec()) if e.startswith("webkitgtk ")], [])


class Route(unittest.TestCase):
    def setUp(self):
        self.w = ShimWorld()
        self.sb = self.w.sb
        self.sb.env["APPGLASS_POWER_SUPPLY"] = self.sb.path("no-power")
        self.exe = os.path.join(self.w.bin, "webthing")
        _w(self.exe, elf(WK41), 0o755)
        self.w.launcher(DID, desktop("Web Thing", self.exe + " ui", StartupWMClass=KEY))

    def tearDown(self):
        self.w.cleanup()

    def run_ok(self, *argv):
        code, out, err = self.w.run(*argv)
        self.assertEqual(code, 0, err)
        return out + err

    def route(self):
        code, out, err = self.sb.run("status", "--json")
        self.assertEqual(code, 0, err)
        return {a["key"]: a for a in json.loads(out)["apps"]}[KEY]

    def launcher(self):
        return self.w.user(".local/share/applications", DID)

    def enable(self, on):
        p = os.path.join(self.sb.config, "appglass", "settings.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump({"apps": {KEY: {"enabled": on}}}, f)

    def test_waiting_until_checked_or_switched_on(self):
        self.run_ok("apply")
        r = self.route()
        self.assertEqual((r["family"], r["state"], r["adapter"]), ("webkit", "waiting", "webkit-shim"))
        self.assertFalse(os.path.exists(self.launcher()))
        self.assertIsNone(engine.family_gate(core.App(self.sb.env, quiet=True), "webkit"))
        self.enable(True)
        self.run_ok("apply")
        self.assertEqual(self.route()["state"], "glass")
        text = self.sb.read(self.launcher())
        wrapper = self.w.user(".local/bin/appglass-webkit")
        self.assertIn("Exec=%s %s %s ui\n" % (wrapper, KEY, self.exe), text)
        for f in ("appglass-wk.so", "appglass-wk.c", "webkit-glass.js", "webkit-glass.css.tmpl"):
            self.assertTrue(os.path.isfile(self.w.user(L + f)), f)
        css = self.sb.read(self.w.user(L + "webkit-glass.css"))
        self.assertIn("rgb(var(--agl-root)) 60%", css)
        self.assertNotIn("{{", css)
        w = self.sb.read(wrapper)
        self.assertNotIn("@APPGLASS@", w)
        self.assertEqual(os.stat(wrapper).st_mode & 0o777, 0o755)
        self.assertIn(re.escape(KEY), self.sb.read(self.sb.cfg("niri", "appglass.kdl")))
        self.assertEqual(len(self.w.tc.builds()), 1)
        # idempotent: a second apply changes nothing, builds nothing
        before = self.sb.read(self.launcher())
        self.run_ok("apply")
        self.assertEqual(self.sb.read(self.launcher()), before)
        self.assertEqual(len(self.w.tc.builds()), 1)
        self.run_ok("remove")
        self.assertFalse(os.path.exists(self.launcher()))
        self.assertFalse(os.path.exists(wrapper))
        self.assertFalse(os.path.exists(self.w.user(L + "appglass-wk.so")))

    def test_an_update_makes_it_stale_and_keeps_its_files(self):
        """webkit the only family: an app checked, then rebuilt, waits for its
        new check as "stale" (the wrapper starts it plain); its files and its
        check record stay."""
        app = core.App(self.sb.env, quiet=True)
        fp = engine.record_for(app, KEY)["fp"]
        engine.verified(app, KEY, fp, "pass", "ok")
        self.run_ok("apply", "--only", "webkit")
        self.assertEqual(self.route()["state"], "glass")
        _w(self.exe, elf(WK41 + ["libm.so.6"]), 0o755)        # the update
        out = self.run_ok("apply", "--only", "webkit")
        self.assertNotIn("files removed", out)
        r = self.route()
        self.assertEqual(r["state"], "stale", r)
        self.assertIn("updated since the last check", r.get("reason") or "")
        self.assertIn("appglass-webkit", self.sb.read(self.launcher()))
        self.assertTrue(os.path.exists(self.w.user(".local/state/appglass/plain", KEY)))
        self.assertTrue(os.path.isfile(self.w.user(L + "appglass-wk.so")))
        kdl = self.sb.cfg("niri", "appglass.kdl")
        self.assertNotIn(re.escape(KEY), self.sb.read(kdl) if os.path.exists(kdl) else "")
        # the new check passes: glass again at the next apply
        app = core.App(self.sb.env, quiet=True)
        engine.verified(app, KEY, engine.record_for(app, KEY)["fp"], "pass", "ok")
        self.run_ok("apply", "--only", "webkit")
        self.assertEqual(self.route()["state"], "glass")
        self.assertFalse(os.path.exists(self.w.user(".local/state/appglass/plain", KEY)))

    def test_switched_off_gets_the_plain_launcher_back(self):
        self.enable(True)
        self.run_ok("apply")
        self.assertTrue(os.path.exists(self.launcher()))
        self.enable(False)
        self.run_ok("apply")
        self.assertFalse("appglass-webkit" in (self.sb.read(self.launcher())
                                                if os.path.exists(self.launcher()) else ""))

    def test_switched_off_in_the_plugin_gets_the_plain_launcher_back(self):
        """The plugin's sync (an event) with the app switched off: the
        launcher no longer starts the wrapper (no preload left behind)."""
        self.enable(True)
        self.run_ok("apply")
        self.assertIn("appglass-webkit", self.sb.read(self.launcher()))
        f = self.sb.write("plugin.json.tmp", json.dumps({"apps": {KEY: {"enabled": False}}}),
                          base=self.sb.root)
        out = self.run_ok("sync", "--settings-file", f)
        self.assertNotIn("not installed, left as is", out)
        self.assertFalse("appglass-webkit" in (self.sb.read(self.launcher())
                                                if os.path.exists(self.launcher()) else ""))
        self.assertEqual(self.route()["state"], "off")

    def test_family_off_app_on(self):
        p = os.path.join(self.sb.config, "appglass", "settings.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump({"apps": {"webkit": {"enabled": False}, KEY: {"enabled": True}}}, f)
        self.run_ok("apply")
        self.assertEqual(self.route()["state"], "glass")
        self.assertIn("appglass-webkit", self.sb.read(self.launcher()))

    def test_a_hand_made_launcher_keeps_it_opaque(self):
        """Glass reaches the app only through appglass's launcher: one of
        yours in its place (apply leaves it) runs the app plain, so the
        route says opaque and why, and the app is a conflict until adopted."""
        mine = desktop("Web Thing", self.exe + " ui --mine", StartupWMClass=KEY)
        _w(self.launcher(), mine.encode() if isinstance(mine, str) else mine)
        self.enable(True)
        out = self.run_ok("apply")
        self.assertIn("hand-made", out)
        r = self.route()
        self.assertEqual((r["effective"], r["state"]), ("fallback", "opaque"), r)
        self.assertIn("hand-made launcher", r["reason"])
        self.assertIn("move ~/.local/share/applications/%s away" % DID, r["reason"])
        self.assertIn("~/.local/share/applications/" + DID, r["conflicts"])
        self.assertNotIn("appglass-webkit", self.sb.read(self.launcher()))
        code, text, err = self.sb.run("status")
        self.assertEqual(code, 0, err)
        line = [l for l in text.splitlines() if l.strip().startswith(KEY)]
        self.assertTrue(line and "fallback" in line[0] and "hand-made" in line[0], text)
        # moved away: glass at the next apply
        os.rename(self.launcher(), self.launcher() + ".mine")
        self.run_ok("apply")
        self.assertEqual(self.route()["state"], "glass")
        self.assertIn("appglass-webkit", self.sb.read(self.launcher()))

    def test_rescue_after_the_state_folder_is_lost_takes_the_build(self):
        """The whole state folder lost: adopt --rescue claims the family's
        build at its own lib path (it renders the launcher proven there), so
        remove takes it and a later apply is not refused by it."""
        self.enable(True)
        self.run_ok("apply")
        so = os.path.join(self.sb.home, L, "appglass-wk.so")
        self.assertTrue(os.path.isfile(so))
        shutil.rmtree(os.path.join(self.sb.state, "appglass"))
        self.run_ok("adopt", "--rescue")
        self.run_ok("remove")
        lib = os.path.join(self.sb.home, L)
        self.assertEqual(sorted(os.listdir(lib)) if os.path.isdir(lib) else [], [])
        out = self.run_ok("apply")
        self.assertNotIn("is not appglass's", out)
        self.assertEqual(self.route()["state"], "glass")

    def test_gtk4_webkit_stays_opaque(self):
        _w(self.exe, elf(WK6), 0o755)
        self.run_ok("apply")
        r = self.route()
        self.assertEqual(r["state"], "opaque")
        self.assertIn("GTK4", r["reason"])
        self.assertFalse(os.path.exists(self.launcher()))

    def test_stage_renders_the_waiting_app(self):
        """The hidden-session check needs the glass launcher of an app that
        still waits for that check: staged in the throwaway HOME only."""
        self.run_ok("apply")
        app = core.App(self.sb.env, quiet=True)
        run = self.sb.path("stage-run")
        os.makedirs(run)
        rec_ = engine.record_for(app, KEY)
        home = verify.stage(app, rec_, run)
        staged = os.path.join(home, ".local/share/applications", DID)
        self.assertTrue(os.path.isfile(staged))
        with open(staged) as f:
            self.assertIn("appglass-webkit %s " % KEY, f.read())
        self.assertTrue(os.path.isfile(os.path.join(home, L, "webkit-glass.js")))
        self.assertFalse(os.path.exists(self.launcher()))
        self.assertIn("appglass-webkit", verify.launcher_exec(app, rec_, home))

    def test_the_check_seeds_what_it_knows(self):
        """Kiri's language step done in the throwaway HOME; an app it does
        not know starts as it is (not unverifiable)."""
        self.run_ok("apply")
        app = core.App(self.sb.env, quiet=True)
        home = self.sb.path("seed-home")
        os.makedirs(home)
        self.assertIsNone(verify.seed(app, engine.record_for(app, KEY), home))
        self.assertEqual(os.listdir(home), [])
        r = dict(engine.record_for(app, KEY), key="kiri")
        self.assertIsNone(verify.seed(app, r, home))
        with open(os.path.join(home, ".kiri", "ui.json")) as f:
            self.assertEqual(json.load(f), {"langAsked": True})

    def test_stage_renders_only_the_app_checked(self):
        """The candidate plan routes the app under check as if it passed,
        not the other apps still waiting (or switched off)."""
        exe2 = os.path.join(self.w.bin, "otherweb")
        _w(exe2, elf(WK41), 0o755)
        did2 = "org.example.Other.desktop"
        self.w.launcher(did2, desktop("Other", exe2, StartupWMClass="org.example.Other"))
        self.run_ok("apply")
        app = core.App(self.sb.env, quiet=True)
        run = self.sb.path("stage-run")
        os.makedirs(run)
        home = verify.stage(app, engine.record_for(app, KEY), run)
        apps = os.path.join(home, ".local/share/applications")
        self.assertTrue(os.path.isfile(os.path.join(apps, DID)))
        self.assertFalse(os.path.exists(os.path.join(apps, did2)))


@unittest.skipUnless(shutil.which("jq"), "no jq")
class Wrapper(unittest.TestCase):
    """The launch wrapper with no shim built, or with a plain marker,
    starts the plain app with its arguments."""

    def setUp(self):
        self.sb = Sandbox()
        self.home = self.sb.home
        self.lib = os.path.join(self.home, ".local/lib/appglass/webkit")
        os.makedirs(self.lib)
        self.w = self.sb.path("appglass-webkit")
        with open(WRAPPER) as f:
            src = f.read().replace("@APPGLASS@", "/bin/false")
        _w(self.w, src, 0o755)
        self.app = self.sb.path("app")
        _w(self.app, "#!/bin/sh\nprintf '%s|' \"$@\"; printf '%s' \"${LD_PRELOAD:-none}\"\n", 0o755)

    def tearDown(self):
        self.sb.cleanup()

    def run_w(self, *argv):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home,
               "XDG_STATE_HOME": os.path.join(self.home, "st")}
        return subprocess.run(["sh", self.w] + list(argv), env=env, capture_output=True,
                              text=True, timeout=30)

    def test_no_shim_plain(self):
        r = self.run_w("k", self.app, "a b", "c")
        self.assertEqual(r.stdout, "a b|c|none")
        self.assertIn("shim missing", r.stderr)

    def test_plain_marker(self):
        for f in ("appglass-wk.so", "webkit-glass.js", "webkit-glass.css.tmpl"):
            _w(os.path.join(self.lib, f), "x", 0o644)
        os.makedirs(os.path.join(self.home, "st/appglass/plain"))
        _w(os.path.join(self.home, "st/appglass/plain/k"), "", 0o644)
        self.assertEqual(self.run_w("k", self.app, "x").stdout, "x|none")

    def test_glass_preload(self):
        for f in ("appglass-wk.so", "webkit-glass.js"):
            _w(os.path.join(self.lib, f), "x", 0o644)
        with open(os.path.join(REPO, "shims/webkit-shim/webkit-glass.css.tmpl")) as f:
            _w(os.path.join(self.lib, "webkit-glass.css.tmpl"), f.read(), 0o644)
        r = self.run_w("k", self.app, "x")
        self.assertEqual(r.stdout, "x|" + os.path.join(self.lib, "appglass-wk.so"))
        with open(os.path.join(self.lib, "webkit-glass.css")) as f:
            css = f.read()
        self.assertIn(" 60%", css)
        self.assertIn(" 12.5%", css)
        self.assertNotIn("{{", css)

    def test_usage(self):
        self.assertEqual(self.run_w("k").returncode, 2)

    def test_an_env_launcher_starts_the_app_itself(self):
        """Exec=env VAR=val app: the shim keeps itself out of the children of
        the first process it loads in, so env would start the app plain; the
        wrapper makes the plain assignments and starts the app itself."""
        for f in ("appglass-wk.so", "webkit-glass.js"):
            _w(os.path.join(self.lib, f), "x", 0o644)
        with open(os.path.join(REPO, "shims/webkit-shim/webkit-glass.css.tmpl")) as f:
            _w(os.path.join(self.lib, "webkit-glass.css.tmpl"), f.read(), 0o644)
        d = self.sb.path("envbin")
        os.makedirs(d)
        fake = os.path.join(d, "env")
        _w(fake, "#!/bin/sh\nprintf 'via-env|'\nexec /usr/bin/env \"$@\"\n", 0o755)
        app = self.sb.path("app2")
        _w(app, "#!/bin/sh\nprintf '%s|' \"$@\" \"${FOO:-}\" \"${BAR:-}\"; "
                "printf '%s' \"${LD_PRELOAD:-none}\"\n", 0o755)
        so = os.path.join(self.lib, "appglass-wk.so")
        r = self.run_w("k", fake, "FOO=a b", "BAR=", app, "x")
        self.assertEqual(r.stdout, "x|a b||" + so)
        # an option (or no command after the assignments): left to env itself
        # (accepts refuses a launcher with an option: the app would run plain)
        r = self.run_w("k", fake, "-u", "FOO", app, "x")
        self.assertTrue(r.stdout.startswith("via-env|x|"), r.stdout)
        r = self.run_w("k", fake, "1X=y", app)
        self.assertTrue(r.stdout.startswith("via-env|"), r.stdout)


DRIVER = r"""
#include <string.h>
void *fk_widget(const char *, void *, int); void fk_map(void *); void fk_show(void *);
void fk_hide(void *); void fk_idle(void); void fk_report(const char *, void *, void *);
void fk_navigate(void *); void fk_frame(void *, unsigned, int); void fk_titlebar(void *, void *);
void fk_hold(void *, int); void fk_commit(void *); void fk_nopaint(void *, int); void fk_paint(void *);
void fk_remove(void *); void fk_add(void *, void *); void fk_related(void *, void *);
void webkit_web_view_load_html(void *, const char *, const char *);
void fk_allocate(void *); void fk_restyle(void *); void fk_region(const char *, void *);
void fk_features(void); void webkit_settings_set_hardware_acceleration_policy(void *, int);
// box[sidebar (hidden), stack[A (hidden page, loaded), B (shown, its page slow)]]; reported: B,
// then A on its page and B again
static int twoview(void) {
    void *win = fk_widget("window", 0, 1), *box = fk_widget("box", win, 0);
    void *side = fk_widget("sidebar", box, 0), *stack = fk_widget("stack", box, 0);
    void *a = fk_widget("view-a", stack, 0), *b = fk_widget("view-b", stack, 0);
    fk_widget("label", side, 0);
    fk_hide(side); fk_hide(a);
    webkit_web_view_load_html(a, "<p>a</p>", 0);
    fk_hold(b, 1); webkit_web_view_load_html(b, "<p>b</p>", 0);
    fk_map(win); fk_idle(); fk_report("mapped", win, b);
    fk_show(side); fk_idle(); fk_report("shown", win, b);
    fk_hold(b, 0); fk_idle(); fk_report("committed", win, b);   // B's page, the sidebar still there
    fk_hide(side); fk_idle(); fk_report("hidden", win, b);
    fk_hide(b); fk_show(a); fk_idle(); fk_report("page-a", win, a);
    fk_hide(a); fk_show(b); fk_idle(); fk_report("page-b", win, b);
    fk_show(side); fk_idle(); fk_report("again", win, b);
    return 0;
}
// win[box[view]], glass; then the view out of it (destroyed, or moved to win2) and a native
// label column packed in its place
static int swap(int move) {
    void *win = fk_widget("window", 0, 1), *box = fk_widget("box", win, 0);
    void *view = fk_widget("view", box, 0), *win2 = fk_widget("window2", 0, 1);
    webkit_web_view_load_html(view, "<p>page</p>", 0);
    fk_map(win); fk_map(win2); fk_idle(); fk_report("glass", win, view);
    fk_remove(view);
    void *labels = fk_widget("labels", 0, 0); fk_widget("label", labels, 0); fk_add(labels, box);
    if (move) fk_add(view, win2);
    fk_idle(); fk_report("swapped", win, view);
    if (move) fk_report("moved", win2, view);
    return 0;
}
// win[view] alone, glass; then the view hidden (nothing left in the window) and shown again
static int viewhide(void) {
    void *win = fk_widget("window", 0, 1), *view = fk_widget("view", win, 0);
    webkit_web_view_load_html(view, "<p>page</p>", 0);
    fk_map(win); fk_idle(); fk_report("glass", win, view);
    fk_hide(view); fk_idle(); fk_report("hidden", win, view);
    fk_show(view); fk_idle(); fk_report("shown", win, view);
    return 0;
}
// win1[view1] glass; then win2 with view2 on view1's content manager (a related view): beside a
// sidebar ("related"), or alone ("relglass"); then the sidebar hidden, and view2 taken out
static int related(int side) {
    void *win = fk_widget("window", 0, 1), *v1 = fk_widget("view", win, 0);
    webkit_web_view_load_html(v1, "<p>one</p>", 0);
    fk_map(win); fk_idle(); fk_report("first", win, v1);
    void *win2 = fk_widget("window2", 0, 1), *box = fk_widget("box", win2, 0);
    void *sb = fk_widget("sidebar", box, 0), *v2 = fk_widget("view2", box, 0);
    fk_widget("label", sb, 0);
    if (!side) fk_hide(sb);
    fk_related(v2, v1); webkit_web_view_load_html(v2, "<p>two</p>", 0);
    fk_map(win2); fk_idle(); fk_report("one", win, v1); fk_report("two", win2, v2);
    fk_hide(sb); fk_idle(); fk_report("one-nosb", win, v1); fk_report("two-nosb", win2, v2);
    fk_show(sb); fk_idle(); fk_report("one-sb", win, v1);
    fk_remove(v2); fk_idle(); fk_report("one-alone", win, v1);
    return 0;
}
// box[sidebar (hidden), view]: the window's opaque region at each step, glass and opaque
static int region(void) {
    void *win = fk_widget("window", 0, 1), *box = fk_widget("box", win, 0);
    void *side = fk_widget("sidebar", box, 0), *view = fk_widget("view", box, 0);
    fk_widget("label", side, 0); fk_hide(side);
    fk_hold(view, 1); webkit_web_view_load_html(view, "<p>page</p>", 0);
    fk_map(win); fk_idle(); fk_region("waiting", win);
    fk_hold(view, 0); fk_idle(); fk_region("glass", win);
    fk_allocate(win); fk_region("resized", win);
    fk_restyle(win); fk_region("restyled", win);
    fk_show(side); fk_idle(); fk_allocate(win); fk_region("opaque", win);
    fk_hide(side); fk_idle(); fk_region("again", win);
    fk_allocate(win); fk_restyle(win); fk_region("again-resized", win);
    return 0;
}
int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "late";
    if (!strcmp(mode, "region")) return region();
    if (!strcmp(mode, "features")) {   // the damage features and the policy of a glass view
        void *win = fk_widget("window", 0, 1), *view = fk_widget("view", win, 0);
        webkit_settings_set_hardware_acceleration_policy(view, 2);   // NEVER, as Kiri sets it
        webkit_web_view_load_html(view, "<p>page</p>", 0);
        fk_map(win); fk_idle(); fk_features();
        return 0;
    }
    if (!strcmp(mode, "twoview")) return twoview();
    if (!strcmp(mode, "swap") || !strcmp(mode, "move")) return swap(mode[0] == 'm');
    if (!strcmp(mode, "viewhide")) return viewhide();
    if (!strcmp(mode, "related") || !strcmp(mode, "relglass")) return related(mode[3] == 'a');
    if (!strcmp(mode, "commit")) {   // committed, not yet painted, then finished
        void *win = fk_widget("window", 0, 1), *view = fk_widget("view", win, 0);
        fk_hold(view, 1); webkit_web_view_load_html(view, "<p>page</p>", 0);
        fk_map(win); fk_idle(); fk_commit(view); fk_report("committed", win, view);
        fk_nopaint(view, 1); fk_hold(view, 0); fk_idle(); fk_report("finished", win, view);
        fk_paint(view); fk_idle(); fk_report("painted", win, view);
        return 0;
    }
    void *win = fk_widget("window", 0, 1), *box = fk_widget("box", win, 0);
    void *side = fk_widget("sidebar", box, 0), *view = fk_widget("view", box, 0);
    fk_widget("label", side, 0);
    if (strcmp(mode, "showall")) fk_hide(side);
    if (!strcmp(mode, "border")) fk_frame(win, 12, 0);     // a bare frame round the view
    if (!strcmp(mode, "margin")) fk_frame(view, 0, 6);
    if (!strcmp(mode, "headerbar") || !strcmp(mode, "titlebox")) {   // gtk_window_set_titlebar
        void *t = fk_widget(mode[0] == 'h' ? "headerbar" : "titlebox", win, 0);
        fk_widget("label", t, 0); fk_titlebar(win, t);
    }
    webkit_web_view_load_html(view, "<p>page</p>", 0);
    fk_map(win); fk_report("painting", win, view);   // the page not there yet
    fk_idle(); fk_report("mapped", win, view);
    if (!strcmp(mode, "nav")) {      // another document while opaque
        fk_show(side); fk_idle(); fk_navigate(view); fk_idle(); fk_report("navigated", win, view);
    }
    if (!strcmp(mode, "late")) {
        void *dlg = fk_widget("dialog", 0, 1); fk_widget("button", dlg, 0);
        fk_map(dlg); fk_idle(); fk_report("dialog", win, view);
        fk_show(side); fk_idle(); fk_report("shown", win, view);
    }
    fk_hide(side); fk_idle(); fk_report("hidden", win, view);
    fk_show(side); fk_idle(); fk_report("again", win, view);
    return 0;
}
"""


@unittest.skipUnless(shutil.which("gcc"), "no gcc")
class ShimDecision(unittest.TestCase):
    """appglass-wk.so on a toy GTK (tests/fixtures/fakegtk.c): the window is
    glass only while the view fills it, whenever a native widget beside the
    view is mapped or unmapped (a sidebar shown after the window mapped is a
    hole on the bare blur), not only at the window's first map."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="appglass-wk-fake-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        d = self.dir
        cc = lambda *a: subprocess.run(["gcc", "-O1", "-Wall"] + list(a), check=True,
                                       capture_output=True, timeout=120)
        cc("-shared", "-fPIC", "-o", os.path.join(d, "appglass-wk.so"),
           os.path.join(REPO, "shims", "webkit-shim", "appglass-wk.c"), "-ldl")
        cc("-shared", "-fPIC", "-o", os.path.join(d, "libfakegtk.so"),
           os.path.join(REPO, "tests", "fixtures", "fakegtk.c"))
        with open(os.path.join(d, "driver.c"), "w") as f:
            f.write(DRIVER)
        cc("-o", os.path.join(d, "driver"), os.path.join(d, "driver.c"), "-L" + d, "-lfakegtk",
           "-Wl,-rpath," + d)
        with open(os.path.join(d, "glass.css"), "w") as f:
            f.write("html { background: rgba(0,0,0,.6) }\n")
        with open(os.path.join(d, "glass.js"), "w") as f:
            f.write("document.documentElement.dataset.aglRoot = '';\n")

    def run_driver(self, mode):
        env = {"PATH": os.environ.get("PATH", os.defpath),
               "LD_PRELOAD": os.path.join(self.dir, "appglass-wk.so"),
               "APPGLASS_CSS": os.path.join(self.dir, "glass.css"),
               "APPGLASS_JS": os.path.join(self.dir, "glass.js")}
        r = subprocess.run([os.path.join(self.dir, "driver"), mode], env=env, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return dict(l.split(" ", 1) for l in r.stdout.splitlines())

    # page: the scripts the shown document ran (the page script and the focus
    # script mark it; every glass rule is gated on those marks). The scripts
    # stay registered while opaque: the marks are inert without the sheet, and
    # a user script runs only on a document that loads after it is added.
    GLASS = "paintable=1 bg_alpha=0 sheets=1 scripts=3 page=3"
    OPAQUE = "paintable=0 bg_alpha=1 sheets=0 scripts=3 page=3"

    def test_a_sidebar_shown_after_the_map_makes_it_opaque(self):
        r = self.run_driver("late")
        self.assertEqual(r["mapped"], self.GLASS)
        self.assertEqual(r["dialog"], self.GLASS)      # another window's widgets: no change
        self.assertEqual(r["shown"], self.OPAQUE)
        self.assertEqual(r["hidden"], self.GLASS)      # the glass back, the page styled once
        self.assertEqual(r["again"], self.OPAQUE)

    def test_show_all_then_hide_gets_the_glass(self):
        """A side widget mapped with the window and hidden just after: opaque
        at the map, glass once it is gone."""
        r = self.run_driver("showall")
        self.assertEqual(r["mapped"], self.OPAQUE)
        self.assertEqual(r["hidden"], self.GLASS)       # the page marked: glass, not bare
        self.assertEqual(r["again"], self.OPAQUE)

    def test_a_document_loaded_while_opaque_is_glass_when_the_widget_goes(self):
        r = self.run_driver("nav")
        self.assertEqual(r["mapped"], self.GLASS)
        self.assertEqual(r["navigated"], self.OPAQUE)
        self.assertEqual(r["hidden"], self.GLASS)

    def test_the_window_waits_for_the_first_document(self):
        """Mapped before the page is loaded: the view is clear already but
        the window keeps its own background (not the bare blur) until then."""
        r = self.run_driver("late")
        self.assertEqual(r["painting"], "paintable=0 bg_alpha=0 sheets=1 scripts=3 page=0")
        self.assertEqual(r["mapped"], self.GLASS)

    def test_the_window_waits_for_the_first_paint(self):
        """Committed, even finished, is not painted yet: the clear view would
        show the bare blur until its first frame, so app-paintable waits for
        the page's paint script (two animation frames after the document)."""
        r = self.run_driver("commit")
        waiting = "paintable=0 bg_alpha=0 sheets=1 scripts=3 page=0"
        self.assertEqual(r["committed"], waiting)
        self.assertEqual(r["finished"], waiting.replace("page=0", "page=3"))
        self.assertEqual(r["painted"], self.GLASS)

    def test_a_border_or_a_margin_round_the_view_is_not_filling(self):
        """A container border-width or a widget margin leaves a frame of the
        bare window round the view: opaque, like a widget beside it."""
        for mode in ("border", "margin"):
            r = self.run_driver(mode)
            self.assertEqual(r["mapped"], self.OPAQUE, mode)
            self.assertEqual(r["hidden"], self.OPAQUE, mode)

    def test_every_view_of_the_window_is_decided_again(self):
        """Two views in a stack: each map or unmap decides every view of
        the window, not only the first one seen, and a page committed while
        a sidebar is up does not glass the window."""
        r = self.run_driver("twoview")
        self.assertEqual(r["mapped"], "paintable=0 bg_alpha=0 sheets=1 scripts=3 page=0")
        self.assertEqual(r["shown"], "paintable=0 bg_alpha=1 sheets=0 scripts=3 page=0")
        self.assertEqual(r["committed"], self.OPAQUE)
        self.assertEqual(r["hidden"], self.GLASS)
        self.assertEqual(r["page-a"], self.GLASS)
        self.assertEqual(r["page-b"], self.GLASS)
        self.assertEqual(r["again"], self.OPAQUE)

    def test_a_header_bar_as_the_titlebar_is_not_beside_the_view(self):
        """GTK3 lists a custom titlebar among the window's children: a
        GtkHeaderBar paints itself (opaque, or at the bar level), so the view
        still fills the window; any other titlebar (a plain box, clear in a
        CSD window) is a widget beside it."""
        r = self.run_driver("headerbar")
        self.assertEqual(r["mapped"], self.GLASS)
        self.assertEqual(r["hidden"], self.GLASS)
        self.assertEqual(r["again"], self.OPAQUE)       # the sidebar still counts
        r = self.run_driver("titlebox")
        self.assertEqual(r["mapped"], self.OPAQUE)
        self.assertEqual(r["hidden"], self.OPAQUE)

    def test_a_view_replaced_by_native_widgets_makes_it_opaque(self):
        """The view destroyed (or moved to another window) and native widgets
        packed in its place: no view is left to fill the window, so it is
        not app-paintable any more (the widgets would be holes on the bare
        blur); a view moved into another window is decided there."""
        r = self.run_driver("swap")
        self.assertEqual(r["glass"], self.GLASS)
        self.assertTrue(r["swapped"].startswith("paintable=0 "), r["swapped"])
        r = self.run_driver("move")
        self.assertTrue(r["swapped"].startswith("paintable=0 "), r["swapped"])
        self.assertEqual(r["moved"], self.GLASS)

    def test_a_hidden_view_does_not_fill_the_window(self):
        """The view hidden with nothing else in the window: an empty bare
        window otherwise; opaque, and glass again once it is shown."""
        r = self.run_driver("viewhide")
        self.assertEqual(r["glass"], self.GLASS)
        self.assertEqual(r["hidden"], self.OPAQUE)
        self.assertEqual(r["shown"], self.GLASS)

    def test_the_glass_window_says_it_is_not_opaque(self):
        """GTK3 sets the window's opaque region whole from its opaque CSS
        background at each realize, size-allocate and style-updated, whatever
        app-paintable says; with the clear view painted in it the region is
        a lie, and at niri opacity 1.0 niri believes it and skips what is
        behind (the background flickers). The glass window clears it after
        GTK each time; an opaque window keeps GTK's."""
        r = self.run_driver("region")
        self.assertEqual(r["waiting"], "opaque=1")      # its own background still drawn
        self.assertEqual(r["glass"], "opaque=0")
        self.assertEqual(r["resized"], "opaque=0")
        self.assertEqual(r["restyled"], "opaque=0")
        self.assertEqual(r["opaque"], "opaque=1")
        self.assertEqual(r["again"], "opaque=0")
        self.assertEqual(r["again-resized"], "opaque=0")

    def test_damage_tracking_is_off(self):
        """WebKitGTK 2.5x damage tracking repaints only the damaged rects of a
        partial frame (a hover) into a buffer that does not keep the last
        frame: on a clear view the rest of the page went bare (Kiri, 2.54,
        NVIDIA). The shim turns both damage features off; others stay on."""
        r = self.run_driver("features")
        self.assertEqual(r["features"],
                         "PropagateDamagingInformation UseDamagingInformationForCompositing lists=0")

    def test_acceleration_never_becomes_always(self):
        """Without compositing (policy NEVER, Kiri) a hover repaints only its
        rects and the rest of the clear page went bare (WebKitGTK 2.54,
        NVIDIA): the shim asks for ALWAYS instead."""
        self.assertEqual(self.run_driver("features")["policy"], "1")

    def test_views_on_one_content_manager_are_glass_together(self):
        """A related view shares the first view's user content manager, so
        the stylesheet styles both pages: glass only while every shown view
        on it fills its window, opaque (the sheet out) as soon as one does
        not; the scripts are added once per content manager."""
        r = self.run_driver("related")
        self.assertEqual(r["first"], self.GLASS)
        self.assertEqual(r["one"], self.OPAQUE)
        self.assertEqual(r["two"], self.OPAQUE)
        self.assertEqual(r["one-nosb"], self.GLASS)
        self.assertEqual(r["two-nosb"], self.GLASS)
        self.assertEqual(r["one-sb"], self.OPAQUE)
        self.assertEqual(r["one-alone"], self.GLASS)
        r = self.run_driver("relglass")
        self.assertEqual(r["one"], self.GLASS)
        self.assertEqual(r["two"], self.GLASS)


if __name__ == "__main__":
    unittest.main()
