"""B3: the unfocused fade on the forced routes (Discord, Feishin, Jellyfin,
Lian Li, VLC). Each app fades its own content background on focus loss;
the amount, duration and easing come from settings.json "inactive" through
`appglass levels` (wrappers) or the apply context (rendered files)."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from fixtures.sandbox import fixture
from fixtures.shimcase import ShimCase
from fixtures.shimworld import ShimWorld
from appglass import inactive

EASE = "cubic-bezier(0.33, 1, 0.68, 1)"
FADE = "180ms " + EASE


class Levels(unittest.TestCase):
    def setUp(self):
        self.w = ShimWorld()
        self.addCleanup(self.w.cleanup)

    def levels(self):
        code, out, err = self.w.run("levels")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_default_fade_in_levels(self):
        self.w.sb.set_level(0.8)
        lv = self.levels()
        self.assertEqual((lv["content"], lv["inactive"]), (0.8, 0.72))
        self.assertEqual((lv["fade_ms"], lv["fade_easing"], lv["fade"]),
                         (180, "ease-out-cubic", FADE))

    def test_settings_change_the_fade(self):
        self.w.sb.set_level(0.8)
        for k, v in (("inactive.factor", "0.8"), ("inactive.durationMs", "300"),
                     ("inactive.easing", "linear")):
            self.assertEqual(self.w.run("set", k, v)[0], 0)
        lv = self.levels()
        self.assertEqual((lv["inactive"], lv["fade_ms"], lv["fade"]), (0.64, 300, "300ms linear"))

    def test_off_or_at_the_floor_no_change(self):
        self.w.sb.set_level(0.6)
        lv = self.levels()
        self.assertEqual((lv["inactive"], lv["fade_ms"]), (0.6, 0))
        self.w.sb.set_level(0.8)
        self.assertEqual(self.w.run("set", "inactive.enabled", "false")[0], 0)
        lv = self.levels()
        self.assertEqual((lv["inactive"], lv["fade_ms"]), (0.8, 0))
        self.assertTrue(lv["fade"].startswith("0ms "))


class LeverFamilies(unittest.TestCase):
    def test_forced_routes_fade_themselves(self):
        for name in ("vencord", "feishin", "jellyfin", "lianli", "qtstyle"):
            self.assertIn(name, inactive.LEVER_FAMILIES)


class Vencord(unittest.TestCase):
    THEME = ".config/Vencord/themes/appglass-discord.css"

    def setUp(self):
        self.w = ShimWorld()
        self.addCleanup(self.w.cleanup)
        res = self.w.user(".config/discord/app-1.0.9/resources")
        os.makedirs(res)
        for n in ("app.asar", "_app.asar"):
            open(os.path.join(res, n), "w").close()
        self.w.hand(".config/Vencord/settings/settings.json", "{}\n")

    def css(self):
        self.assertEqual(self.w.run("set", "apps.vencord.enabled", "true")[0], 0)
        code, out, err = self.w.run("apply", "--only", "vencord")
        self.assertEqual(code, 0, err)
        return self.w.sb.read(self.w.user(self.THEME))

    def test_unfocused_discord_fades_its_content(self):
        """Discord sets html.app-focused on its own window focus: the theme
        lowers --ag-content without it and #app-mount eases the change."""
        self.w.sb.set_level(0.8)
        css = self.css()
        self.assertNotIn("{{", css)
        surface = re.search(r"--ag-content: color-mix\(in srgb, (#[0-9a-fA-F]{6}) 80%", css).group(1)
        self.assertIn("html:not(.app-focused) { --ag-content: color-mix(in srgb, %s 72%%, "
                      "transparent); }" % surface, css)
        self.assertIn("#app-mount { background: var(--ag-content) !important; "
                      "transition: background-color %s !important; }" % FADE, css)

    def test_fade_off_keeps_one_level(self):
        self.w.sb.set_level(0.8)
        self.assertEqual(self.w.run("set", "inactive.enabled", "false")[0], 0)
        css = self.css()
        self.assertIn("html:not(.app-focused) { --ag-content: color-mix(in srgb, ", css)
        self.assertRegex(css, r"html:not\(\.app-focused\) \{ --ag-content: color-mix\(in srgb, "
                              r"#[0-9a-fA-F]{6} 80%")
        self.assertIn("transition: background-color 0ms", css)


L_FEISHIN = ".local/lib/appglass/feishin/"


class Feishin(unittest.TestCase):
    FAKE = """#!/bin/sh
[ "$1" = ps ] && exit 0
exit 0
"""

    def setUp(self):
        self.w = ShimWorld()
        self.addCleanup(self.w.cleanup)
        meta = self.w.sb.path("flatpak", "app", "org.jeffvli.feishin", "current", "active",
                              "metadata")
        os.makedirs(os.path.dirname(meta))
        with open(meta, "w") as f:
            f.write("[Application]\nname=org.jeffvli.feishin\nruntime=org.freedesktop.Platform/x86_64/24.08\n")
        with open(fixture("launchers/org.jeffvli.feishin.desktop")) as f:
            self.w.launcher("org.jeffvli.feishin.desktop", f.read(), flatpak=True)
        self.w.sb.set_level(0.8)
        os.makedirs(os.path.join(self.w.sb.config, "appglass"), exist_ok=True)
        with open(os.path.join(self.w.sb.config, "appglass", "settings.json"), "w") as f:
            json.dump({"apps": {"org.jeffvli.feishin": {"enabled": True}}}, f)
        code, out, err = self.w.run("apply", "--only", "feishin")
        self.assertEqual(code, 0, err)

    def test_css_fades_root_when_the_window_is_inactive(self):
        css = self.w.sb.read(self.w.user(L_FEISHIN + "feishin-glass.css"))
        self.assertRegex(css, r"#root \{ background: rgba\(\d+, \d+, \d+, 0\.8\) !important; "
                              r"transition: background-color %s !important; \}" % re.escape(FADE))
        self.assertRegex(css, r"html\.agl-inactive #root \{ background: rgba\(\d+, \d+, \d+, "
                              r"0\.72\) !important; \}")

    def test_wrapper_renders_the_same_css(self):
        rendered = self.w.sb.read(self.w.user(L_FEISHIN + "feishin-glass.css"))
        tmp = tempfile.mkdtemp(prefix="appglass-fp-")
        self.addCleanup(shutil.rmtree, tmp, True)
        fp = os.path.join(tmp, "flatpak")
        with open(fp, "w") as f:
            f.write(self.FAKE)
        os.chmod(fp, 0o755)
        os.remove(self.w.user(L_FEISHIN + "feishin-glass.css"))
        env = dict(self.w.sb.env, APPGLASS_FLATPAK=fp, XDG_RUNTIME_DIR="")
        r = subprocess.run([self.w.user(".local/bin/appglass-feishin")], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.w.sb.read(self.w.user(L_FEISHIN + "feishin-glass.css")), rendered)

    def test_hook_follows_the_window_focus(self):
        js = self.w.sb.read(self.w.user(L_FEISHIN + "agl-hook.js"))
        self.assertIn("w.on('focus'", js)
        self.assertIn("w.on('blur'", js)
        self.assertIn("agl-inactive", js)


NODE = shutil.which("node")


@unittest.skipUnless(NODE, "no node")
class FeishinHookNode(unittest.TestCase):
    """agl-hook.js against a fake electron: focus/blur toggle the class."""

    def test_focus_toggles_the_class(self):
        hook = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "shims", "electron-hook", "agl-hook.js")
        tmp = tempfile.mkdtemp(prefix="appglass-node-")
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "node_modules", "electron"))
        with open(os.path.join(tmp, "node_modules", "electron", "index.js"), "w") as f:
            f.write(FAKE_ELECTRON)
        with open(os.path.join(tmp, "main.js"), "w") as f:
            f.write("process.type='browser';require(%s);\n%s" % (json.dumps(hook), DRIVE))
        r = subprocess.run([NODE, "main.js"], cwd=tmp, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ["blur:true", "focus:false"])


FAKE_ELECTRON = """
const EventEmitter = require('events');
class WC extends EventEmitter {
  getURL() { return 'app://x'; } isLoading() { return false; }
  insertCSS() { return Promise.resolve('k'); } removeInsertedCSS() { return Promise.resolve(); }
  executeJavaScript(js) { global.__js.push(js); return Promise.resolve(); }
}
class BrowserWindow extends EventEmitter {
  constructor() { super(); this.webContents = new WC(); this.id = 1; }
  setBackgroundColor() {} getBackgroundColor() { return '#00000000'; } getTitle() { return 't'; }
  isFocused() { return true; }
  static getAllWindows() { return global.__wins; }
}
global.__wins = []; global.__js = [];
const app = new EventEmitter(); app.isReady = () => true;
module.exports = { app, BrowserWindow, webContents: {} };
"""

DRIVE = """
const { app, BrowserWindow } = require('electron');
const w = new BrowserWindow(); global.__wins.push(w); app.emit('browser-window-created', {}, w);
setTimeout(() => {
  const n = global.__js.length;
  w.emit('blur');
  const b = global.__js.slice(n).join(' ');
  w.emit('focus');
  const f = global.__js.slice(n).join(' ').slice(b.length);
  const st = s => /toggle\\('agl-inactive', *true\\)/.test(s) ? 'true' : /toggle\\('agl-inactive', *false\\)/.test(s) ? 'false' : '?';
  console.log('blur:' + st(b)); console.log('focus:' + st(f));
  process.exit(0);
}, 50);
"""


L_JF = ".local/lib/appglass/jellyfin/"


class Jellyfin(ShimCase, unittest.TestCase):
    FAMILY = "jellyfin"
    KEY = "org.jellyfin.JellyfinDesktop"
    FLATPAK = KEY
    SYSTEM = "org.jellyfin.JellyfinDesktop.desktop"

    # only the fade checks of the ShimCase world (test_jellyfin runs the rest)
    test_off_by_default = test_apply_and_remove = test_hand_files_conflict_then_adopt = None
    test_level_change_rerenders_css_only = test_dry_run = test_build_stamp = None
    test_rescue_after_state_json_lost = test_rescue_after_state_dir_lost = None

    def test_inactive_rule_and_same_css_from_gen(self):
        self.enable()
        self.w.sb.set_level(0.8)
        self.apply()
        css = self.w.sb.read(self.w.user(L_JF + "jellyfin-glass.css"))
        self.assertRegex(css, r"html \{ background: rgba\(\d+, \d+, \d+, 0\.8\) !important; "
                              r"transition: background-color %s !important;" % re.escape(FADE))
        self.assertRegex(css, r"html\.agl-inactive:not\(:has\(\.videoPlayerContainer\)\) \{ "
                              r"background: rgba\(\d+, \d+, \d+, 0\.72\) !important; \}")
        lib = self.w.user(L_JF)
        out = os.path.join(self.w.sb.root, "gen.css")
        r = subprocess.run([os.path.join(lib, "gen-css.sh"),
                            os.path.join(lib, "jellyfin-glass.css.tmpl"), out],
                           env=self.w.sb.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.w.sb.read(out), css)

    def test_shim_follows_the_window_focus(self):
        self.enable()
        self.apply()
        src = self.w.sb.read(self.w.user(L_JF + "jfglass.cpp"))
        self.assertIn("activeChanged", src)
        self.assertIn("agl-inactive", src)


L_LL = ".local/lib/appglass/lianli/"


class Lianli(ShimCase, unittest.TestCase):
    FAMILY = "lianli"
    KEY = "com.sgtaziz.lianlilinux"
    BINS = ("lianli-gui",)
    SYSTEM = "com.sgtaziz.lianlilinux.desktop"

    test_off_by_default = test_apply_and_remove = test_hand_files_conflict_then_adopt = None
    test_level_change_rerenders_css_only = test_dry_run = test_build_stamp = None
    test_rescue_after_state_json_lost = test_rescue_after_state_dir_lost = None

    def test_inactive_rule_and_same_css_from_the_wrapper(self):
        self.enable()
        self.w.sb.set_level(0.8)
        self.apply()
        p = self.w.user(L_LL + "lianli-glass.css")
        css = self.w.sb.read(p)
        self.assertIn("body { background-color: color-mix(in srgb, var(--bg-base) 80%%, "
                      "transparent) !important; transition: background-color %s !important; }"
                      % FADE, css)
        self.assertIn("html.agl-inactive body { background-color: color-mix(in srgb, "
                      "var(--bg-base) 72%, transparent) !important; }", css)
        # the wrapper renders it again at launch: the same bytes
        os.remove(p)
        os.chmod(self.w.user(L_LL + "appglass-wk.so"), 0o755)
        env = dict(self.w.sb.env, APPGLASS_LIANLI=self.w.exe("fake-lianli"))
        r = subprocess.run([self.w.user(".local/bin/appglass-lianli")], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.w.sb.read(p), css)

    def test_shim_marks_the_unfocused_page(self):
        self.enable()
        self.apply()
        src = self.w.sb.read(self.w.user(L_LL + "appglass-wk.c"))
        self.assertIn("agl-inactive", src)
        self.assertIn("hasFocus", src)


class QtStyle(unittest.TestCase):
    LAUNCHER = ".local/share/applications/vlc.desktop"

    def setUp(self):
        self.w = ShimWorld(bins=("vlc",))
        self.addCleanup(self.w.cleanup)
        with open(fixture("launchers/vlc.desktop")) as f:
            self.w.launcher("vlc.desktop", f.read())

    def exec_lines(self):
        code, out, err = self.w.run("apply", "--only", "qtstyle")
        self.assertEqual(code, 0, err)
        return re.findall(r"(?m)^Exec=(.*)$", self.w.sb.read(self.w.user(self.LAUNCHER)))

    def test_launcher_passes_the_fade(self):
        self.w.sb.set_level(0.8)
        for line in self.exec_lines():
            self.assertIn(" APPGLASS_CONTENT=0.8 APPGLASS_INACTIVE=0.72 APPGLASS_FADE_MS=180 "
                          "APPGLASS_FADE_EASING=ease-out-cubic ", line)

    def test_fade_off(self):
        self.w.sb.set_level(0.8)
        self.assertEqual(self.w.run("set", "inactive.enabled", "false")[0], 0)
        for line in self.exec_lines():
            self.assertIn(" APPGLASS_INACTIVE=0.8 APPGLASS_FADE_MS=0 ", line)


if __name__ == "__main__":
    unittest.main()
