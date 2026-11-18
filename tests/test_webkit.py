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
                mock.patch.object(verify, "system_paths", lambda run="/run": []):
            m = webkit.verify_mask(rec())
        self.assertEqual(m, {"hide": ["/run/kiri"], "nonet": True})
        self.assertEqual(seen, [["kiri", "kiri", "kiri-window"]])

    def test_lianli_hides_its_daemon(self):
        from unittest import mock
        from appglass.families import lianli
        with mock.patch.object(verify, "run_paths",
                               lambda r, keys=(), run="/run": ["/run/" + k for k in keys]), \
                mock.patch.object(verify, "system_paths", lambda run="/run": []):
            self.assertEqual(lianli.verify_mask({"key": "x"}),
                             {"hide": ["/run/lianli"], "nonet": True})

    def test_the_system_manager_out_of_reach(self):
        """Lian Li's GUI starts a root unit (systemctl start
        lianli-control-recovery.service, allowed by its polkit rule) over the
        system bus: the check of a WebKitGTK app hides the system bus socket
        and systemd's private socket."""
        from appglass.families import lianli
        d = tempfile.mkdtemp()
        try:
            for rel in ("dbus/system_bus_socket", "systemd/private"):
                os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
                open(os.path.join(d, rel), "w").close()
            self.assertEqual(verify.system_paths(run=d),
                             [d + "/dbus/system_bus_socket", d + "/systemd/private"])
            os.unlink(os.path.join(d, "systemd/private"))
            self.assertEqual(verify.system_paths(run=d), [d + "/dbus/system_bus_socket"])
        finally:
            shutil.rmtree(d)
        from unittest import mock
        with mock.patch.object(verify, "run_paths", lambda r, keys=(), run="/run": []), \
                mock.patch.object(verify, "system_paths", lambda run="/run": ["/run/s"]):
            self.assertEqual(lianli.verify_mask({"key": "x"})["hide"], ["/run/s"])
            self.assertEqual(webkit.verify_mask(rec())["hide"], ["/run/s"])

    def test_the_real_kiri_binary(self):
        b = "/usr/lib/kiri/kiri-window"
        if not os.path.isfile(b) or not os.path.isdir("/run/kiri"):
            self.skipTest("no Kiri here")
        self.assertIn("/run/kiri", verify.run_paths({"exec": b, "seen": [b]}, keys=("kiri",)))


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
        r = self.run_w("k", fake, "-u", "FOO", app, "x")
        self.assertTrue(r.stdout.startswith("via-env|x|"), r.stdout)
        r = self.run_w("k", fake, "1X=y", app)
        self.assertTrue(r.stdout.startswith("via-env|"), r.stdout)


if __name__ == "__main__":
    unittest.main()
