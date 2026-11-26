"""Feishin's output goes through a fifo to a reader that keeps only the
inspector url, not to an unlinked file in the (tmpfs) runtime dir that
grows for the whole session."""

import os
import shutil
import subprocess
import tempfile
import unittest

from fixtures.shimcase import ShimCase

L = ".local/lib/appglass/feishin/"


class FeishinFifo(ShimCase, unittest.TestCase):
    FAMILY = "feishin"
    KEY = "org.jeffvli.feishin"
    FLATPAK = KEY
    SYSTEM = "org.jeffvli.feishin.desktop"
    LAUNCHER = ".local/share/applications/org.jeffvli.feishin.desktop"
    FILES = {L + "agl-hook.js": 0o644, L + "agl-inject.py": 0o644,
             L + "feishin-glass.css.tmpl": 0o644, L + "feishin-glass.css": 0o644,
             ".local/bin/appglass-feishin": 0o755}
    CSS = L + "feishin-glass.css"

    # the app's stdout: a pipe (the fifo), never a regular file
    FAKE = """#!/bin/sh
echo "$*" >> "%s"
[ "$1" = ps ] && exit 0
case "$*" in *--inspect*) echo "Debugger listening on ws://127.0.0.1:9/0000-aaaa" >&2
  sleep 1; [ -p /dev/stdout ] && echo STDOUT-PIPE >> "%s"; echo "later output" ;; esac
exit 0
"""

    def test_output_through_a_fifo(self):
        self.enable()
        self.apply()
        rt = self.w.sb.path("run")
        os.makedirs(rt, mode=0o700)
        tmp = tempfile.mkdtemp(prefix="appglass-fp-")
        self.addCleanup(shutil.rmtree, tmp, True)
        calls, fp = os.path.join(tmp, "calls"), os.path.join(tmp, "flatpak")
        with open(fp, "w") as f:
            f.write(self.FAKE % (calls, calls))
        os.chmod(fp, 0o755)
        env = dict(self.w.sb.env, APPGLASS_FLATPAK=fp, XDG_RUNTIME_DIR=rt)
        r = subprocess.run([self.w.user(".local/bin/appglass-feishin")], env=env,
                           capture_output=True, text=True, timeout=60)
        with open(calls) as f:
            calls = f.read().splitlines()
        self.assertIn("injection failed", r.stderr)       # the url was found; nothing listens on :9
        self.assertIn("STDOUT-PIPE", calls)
        self.assertNotIn("later output", r.stdout + r.stderr)
        self.assertEqual(os.listdir(os.path.join(rt, "appglass")), [])


if __name__ == "__main__":
    unittest.main()
