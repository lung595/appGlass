"""electron-hook: VSCodium (the Feishin route, a VS Code stylesheet, the
settings.json block for the canvas-painted parts)."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from fixtures.shimcase import ShimCase
from appglass.families import zed

L = ".local/lib/appglass/vscodium/"
SETTINGS = ".var/app/com.vscodium.codium/config/VSCodium/User/settings.json"


class VSCodium(ShimCase, unittest.TestCase):
    FAMILY = "vscodium"
    KEY = "com.vscodium.codium"
    FLATPAK = KEY
    SYSTEM = "com.vscodium.codium.desktop"
    LAUNCHER = ".local/share/applications/com.vscodium.codium.desktop"
    FILES = {L + "agl-hook.js": 0o644, L + "agl-inject.py": 0o644,
             L + "vscode-glass.css.tmpl": 0o644, L + "vscode-glass.css": 0o644,
             ".local/bin/appglass-vscodium": 0o755}
    CSS = L + "vscode-glass.css"

    def settings_text(self):
        return self.w.sb.read(self.w.user(SETTINGS))

    def write_settings(self, text):
        p = self.w.user(SETTINGS)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        self.before = self.w.sb.tree_hash()

    def test_hand_files_conflict_then_adopt(self):
        # no hand-made VSCodium files predate appglass (none in HAND_FILES):
        # a file in the way is a conflict, the family is skipped, nothing written
        self.w.hand(self.LAUNCHER, b"[Desktop Entry]\nExec=codium\n", 0o644)
        self.w.hand(".local/bin/appglass-vscodium", b"#!/bin/sh\nexec codium\n", 0o700)
        self.enable()
        out, err = self.apply()
        self.assertIn("vscodium: skipped", err)
        self.assertEqual(self.w.sb.read(self.w.user(self.LAUNCHER)), "[Desktop Entry]\nExec=codium\n")
        self.assertFalse(os.path.exists(self.w.user(SETTINGS)))
        self.assertNotIn(self.FAMILY, self.w.state()["owners"])

    def test_launcher_keeps_the_arguments(self):
        self.enable()
        self.apply()
        text = self.w.sb.read(self.w.user(self.LAUNCHER))
        w = self.w.user(".local/bin/appglass-vscodium")
        self.assertEqual(re.findall(r"(?m)^Exec=(.*)$", text), [w + " %F", w + " --new-window %F"])

    def test_wrapper_flags(self):
        self.enable()
        self.apply()
        w = self.w.sb.read(self.w.user(".local/bin/appglass-vscodium"))
        self.assertIn('"$ID" --verbose --inspect=127.0.0.1:0 --inspect-publish-uid=stderr "$@"', w)
        self.assertIn("--command=$ID", w)
        self.assertIn("mkdir -m 700", w)

    def test_css_workbench_once_popups_untouched(self):
        self.enable()
        self.w.sb.set_level(0.8)
        self.apply()
        css = self.w.sb.read(self.w.user(self.CSS))
        self.assertRegex(css, r"\.monaco-workbench \{\n  background-color: rgba\(\d+, \d+, \d+, 0\.8\) "
                              r"!important;")
        for sel in ("quick-input-widget", "monaco-menu", "suggest-widget", "notification-toast"):
            self.assertNotIn(sel, css)
        # the breadcrumb widget and xterm set their theme colour inline on these
        clear = css[css.index("background-color: transparent !important") - 2000:]
        for sel in (".monaco-breadcrumbs", ".xterm,", ".xterm-scrollable-element"):
            self.assertIn(".monaco-workbench " + sel, clear)
        self.assertNotIn("{{", css)

    def test_settings_block_new_file(self):
        self.enable()
        self.apply()
        text = self.settings_text()
        got = json.loads(zed.strip_jsonc(text))
        self.assertEqual(got, {"workbench.colorCustomizations": {
            "minimap.background": "#00000000", "editorOverviewRuler.background": "#00000000",
            "editor.lineHighlightBorder": "#00000000", "editor.lineHighlightBackground": "#ffffff0d",
            "terminal.background": "#00000000"},
            # xterm's WebGL renderer paints an opaque canvas (and dark-fringed glyphs on a clear one)
            "terminal.integrated.gpuAcceleration": "off"})
        self.assertIn(zed.BEGIN, text)

    def test_settings_user_keys_kept_and_restored(self):
        user = '{\n  // mine\n  "editor.fontSize": 15,\n  "workbench.colorTheme": "Default Dark Modern"\n}\n'
        self.write_settings(user)
        self.enable()
        self.apply()
        got = json.loads(zed.strip_jsonc(self.settings_text()))
        self.assertEqual(got["editor.fontSize"], 15)
        self.assertEqual(len(got["workbench.colorCustomizations"]), 5)
        self.assertEqual(got["terminal.integrated.gpuAcceleration"], "off")
        self.assertIn("// mine", self.settings_text())
        self.apply()                                     # idempotent
        self.assertEqual(self.settings_text().count(zed.BEGIN), 1)
        self.run_ok("remove")
        self.assertEqual(self.settings_text(), user)

    def test_settings_own_colour_customizations_left(self):
        user = '{\n  "workbench.colorCustomizations": {"editor.background": "#000000"}\n}\n'
        self.write_settings(user)
        self.enable()
        out, err = self.apply()
        self.assertIn("minimap.background", err)
        self.assertEqual(self.settings_text(), user)
        self.assertTrue(os.path.isfile(self.w.user(".local/bin/appglass-vscodium")))

    FAKE = """#!/bin/sh
echo "$*" >> "%s"
[ "$1" = ps ] && { [ -n "${FAKE_RUNNING:-}" ] && echo com.vscodium.codium; exit 0; }
case "$*" in *--inspect*) i=0; while [ $i -lt 300 ]; do echo "[main] verbose line $i"; i=$((i+1)); done
  echo "Debugger listening on ws://127.0.0.1:9/0000-aaaa" >&2; echo "more output"; sleep 1 ;; esac
exit 0
"""

    def wrapper(self, rt, **extra):
        tmp = tempfile.mkdtemp(prefix="appglass-fp-")
        self.addCleanup(shutil.rmtree, tmp, True)
        calls, fp = os.path.join(tmp, "calls"), os.path.join(tmp, "flatpak")
        with open(fp, "w") as f:
            f.write(self.FAKE % calls)
        os.chmod(fp, 0o755)
        env = dict(self.w.sb.env, APPGLASS_FLATPAK=fp, XDG_RUNTIME_DIR=rt, **extra)
        r = subprocess.run([self.w.user(".local/bin/appglass-vscodium")], env=env,
                           capture_output=True, text=True, timeout=60)
        with open(calls) as f:
            return r, f.read().splitlines()

    def test_url_read_through_fifo_nothing_left(self):
        self.enable()
        self.apply()
        rt = self.w.sb.path("run")
        os.makedirs(rt, mode=0o700)
        r, calls = self.wrapper(rt)
        self.assertIn("injection failed", r.stderr)       # the url was found; nothing listens on :9
        self.assertNotIn("verbose line", r.stdout + r.stderr)
        self.assertTrue(any("--command=com.vscodium.codium" in c and "--verbose" in c for c in calls),
                        calls)
        self.assertEqual(os.listdir(os.path.join(rt, "appglass")), [])

    def test_no_private_runtime_dir_no_inspector(self):
        self.enable()
        self.apply()
        rt = self.w.sb.path("run-shared")
        os.makedirs(rt)
        os.chmod(rt, 0o777)
        for d in (rt, ""):
            r, calls = self.wrapper(d)
            self.assertFalse(any("--inspect" in c for c in calls), calls)
            self.assertTrue(any(c.startswith("run ") for c in calls), calls)
            self.assertIn("appglass-vscodium: no private XDG_RUNTIME_DIR", r.stderr)
        self.assertEqual(os.listdir(rt), [])

    def test_every_fallback_says_why(self):
        # a start without glass names its reason on stderr (the journal)
        self.enable()
        self.apply()
        rt = self.w.sb.path("run")
        os.makedirs(rt, mode=0o700)
        r, calls = self.wrapper(rt, FAKE_RUNNING="1")
        self.assertIn("appglass-vscodium: VSCodium already runs", r.stderr)
        os.remove(self.w.user(L + "agl-hook.js"))
        r, calls = self.wrapper(rt)
        self.assertIn("appglass-vscodium: agl-hook.js or agl-inject.py missing", r.stderr)

    def test_plain_marker_starts_it_plain(self):
        # the engine's plain/ marker (verify failed, two launches with no window)
        self.enable()
        self.apply()
        rt = self.w.sb.path("run")
        os.makedirs(rt, mode=0o700)
        m = os.path.join(self.w.sb.state, "appglass", "plain", self.KEY)
        os.makedirs(os.path.dirname(m), exist_ok=True)
        open(m, "w").close()
        r, calls = self.wrapper(rt)
        self.assertFalse(any("--inspect" in c for c in calls), calls)
        self.assertTrue(any(c.startswith("run ") and "--command=com.vscodium.codium" in c
                            for c in calls), calls)
        self.assertIn("appglass-vscodium: glass paused by appglass", r.stderr)

    def test_injection_logged(self):
        self.enable()
        self.apply()
        rt = self.w.sb.path("run")
        os.makedirs(rt, mode=0o700)
        r, calls = self.wrapper(rt)
        self.assertIn("appglass-vscodium: inspector url after", r.stderr)


if __name__ == "__main__":
    unittest.main()
