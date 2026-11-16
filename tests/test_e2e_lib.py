"""tests/e2e/lib.sh: ag_start with a fake harness (no niri is started)."""

import os
import subprocess
import textwrap
import unittest

from fixtures.sandbox import Sandbox

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e", "lib.sh")

# start prints the run env; WL stays empty for the first <misses> starts
FAKE = textwrap.dedent("""\
    #!/bin/bash
    d=$(dirname "$0"); log=$d/calls
    echo "$*" >> "$log"
    case $1 in
    start)
        n=$(grep -c '^start' "$log"); t=$d/tmp-$n; mkdir -p "$t"
        wl=wayland-9; [ "$n" -le "$(cat "$d/misses")" ] && wl=
        printf 'PID=1\\nSOCK=x\\nWL=%s\\nTMP=%s\\nCFG=x\\n' "$wl" "$t";;
    stop) echo "stopped $2";;
    esac
    """)


class AgStart(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.dir = self.sb.path("harness")
        os.makedirs(self.dir)
        self.h = os.path.join(self.dir, "harness.sh")
        with open(self.h, "w") as f:
            f.write(FAKE)
        os.chmod(self.h, 0o755)

    def tearDown(self):
        self.sb.cleanup()

    def start(self, misses):
        with open(os.path.join(self.dir, "misses"), "w") as f:
            f.write(str(misses))
        script = ('. "%s"; ag_cleanup() { :; }; ag_start s1 "";'
                  ' echo "WL=$AG_WL TMP=$AG_TMP SESSIONS=${AG_SESSIONS[*]}"' % LIB)
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                           env=dict(os.environ, APPGLASS_HARNESS=self.h))
        with open(os.path.join(self.dir, "calls")) as f:
            calls = f.read().split()
        return r, calls

    def test_display_found(self):
        r, calls = self.start(0)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("WL=wayland-9 TMP=%s/tmp-1 SESSIONS=s1" % self.dir, r.stdout)
        self.assertEqual(calls, ["start", "s1"])

    def test_empty_wl_retried_once(self):
        r, calls = self.start(1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no wayland display", r.stderr)
        self.assertIn("WL=wayland-9 TMP=%s/tmp-2 SESSIONS=s1" % self.dir, r.stdout)
        self.assertEqual(calls, ["start", "s1", "stop", "s1", "start", "s1"])

    def test_empty_wl_twice_fails_clearly(self):
        r, calls = self.start(2)
        self.assertEqual(r.returncode, 1)
        self.assertIn("never got a wayland display", r.stderr)
        self.assertNotIn("WL=", r.stdout)
        # both sessions stopped, none left to launch into
        self.assertEqual(calls, ["start", "s1", "stop", "s1", "start", "s1", "stop", "s1"])


if __name__ == "__main__":
    unittest.main()
