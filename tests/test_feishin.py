import os
import re
import shutil
import subprocess
import tempfile
import unittest

from fixtures.shimcase import ShimCase

L = ".local/lib/appglass/feishin/"


class Feishin(ShimCase, unittest.TestCase):
    FAMILY = "feishin"
    KEY = "org.jeffvli.feishin"
    FLATPAK = KEY
    SYSTEM = "org.jeffvli.feishin.desktop"
    LAUNCHER = ".local/share/applications/org.jeffvli.feishin.desktop"
    FILES = {L + "agl-hook.js": 0o644, L + "agl-inject.py": 0o644,
             L + "feishin-glass.css.tmpl": 0o644, L + "feishin-glass.css": 0o644,
             ".local/bin/appglass-feishin": 0o755}
    CSS = L + "feishin-glass.css"

    def test_inspector_local_only(self):
        self.enable()
        self.apply()
        w = self.w.sb.read(self.w.user(".local/bin/appglass-feishin"))
        self.assertIn("--inspect=127.0.0.1:0", w)
        self.assertIn("--inspect-publish-uid=stderr", w)
        self.assertIn("mkdir -m 700", w)
        text = self.w.sb.read(self.w.user(self.LAUNCHER))
        self.assertEqual(re.findall(r"(?m)^Exec=(.*)$", text),
                         [self.w.user(".local/bin/appglass-feishin")])

    def test_css_levels_raw(self):
        self.enable()
        self.w.sb.set_level(0.7)
        self.apply()
        self.assertIn("0.7", self.w.sb.read(self.w.user(self.CSS)))

    FAKE = """#!/bin/sh
echo "$*" >> "%s"
[ "$1" = ps ] && exit 0
case "$*" in *--inspect*) echo "Debugger listening on ws://127.0.0.1:9/0000-aaaa" >&2; sleep 1 ;; esac
exit 0
"""

    def wrapper(self, rt):
        tmp = tempfile.mkdtemp(prefix="appglass-fp-")
        self.addCleanup(shutil.rmtree, tmp, True)
        calls, fp = os.path.join(tmp, "calls"), os.path.join(tmp, "flatpak")
        with open(fp, "w") as f:
            f.write(self.FAKE % calls)
        os.chmod(fp, 0o755)
        env = dict(self.w.sb.env, APPGLASS_FLATPAK=fp, XDG_RUNTIME_DIR=rt)
        r = subprocess.run([self.w.user(".local/bin/appglass-feishin")], env=env,
                           capture_output=True, text=True, timeout=60)
        with open(calls) as f:
            return r, f.read().splitlines()

    def test_log_deleted_whatever_the_injection(self):
        self.enable()
        self.apply()
        rt = self.w.sb.path("run")
        os.makedirs(rt, mode=0o700)
        r, calls = self.wrapper(rt)
        self.assertIn("injection failed", r.stderr)       # nothing listens on :9
        self.assertTrue(any("--inspect=127.0.0.1:0" in c for c in calls), calls)
        self.assertEqual(os.listdir(os.path.join(rt, "appglass")), [])
        self.assertEqual(os.stat(os.path.join(rt, "appglass")).st_mode & 0o777, 0o700)

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
        self.assertEqual(os.listdir(rt), [])


if __name__ == "__main__":
    unittest.main()
