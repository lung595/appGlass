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


class SessionDoors(unittest.TestCase):
    """The doors to the real session an e2e app must not reach: the user
    manager ($XDG_RUNTIME_DIR/systemd), the session bus socket, and the
    system manager. Fakes on PATH: nothing real is asked."""

    def setUp(self):
        self.sb = Sandbox()
        self.rt = self.sb.path("rt")
        self.bin = self.sb.path("bin")
        os.makedirs(os.path.join(self.rt, "systemd"))
        os.makedirs(self.bin)
        open(os.path.join(self.rt, "bus"), "w").close()
        open(os.path.join(self.rt, "lianli-session-3.lock"), "w").close()

    def tearDown(self):
        self.sb.cleanup()

    def fake(self, name, body):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write("#!/bin/bash\n" + body)
        os.chmod(p, 0o755)

    def sh(self, script):
        return subprocess.run(["bash", "-c", '. "%s"; ag_cleanup() { :; }; %s' % (LIB, script)],
                              capture_output=True, text=True,
                              env=dict(os.environ, XDG_RUNTIME_DIR=self.rt,
                                       PATH=self.bin + ":" + os.environ["PATH"]))

    def test_the_user_manager_and_the_session_bus_are_hidden(self):
        r = self.sh('ag_hide_args "${AG_SESSION_SOCKETS[@]}" "$XDG_RUNTIME_DIR"/lianli-*.lock')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split("\n"), [
            "--tmpfs", self.rt + "/systemd",
            "--ro-bind", "/dev/null", self.rt + "/bus",
            "--ro-bind", "/dev/null", self.rt + "/lianli-session-3.lock", ""])

    def run_mask(self, mask):
        # the real bwrap is not run: the fake applies a --tmpfs over the user
        # manager's dir by answering "no socket" for paths under it
        self.fake("bwrap", 'm=(); while [ "$1" != -- ]; do m+=("$1"); shift; done; shift\n'
                  'echo "$*" >> "%s/asked"\n'
                  'for x in "${m[@]}"; do case "$3" in "$x"/*|"$x") exit 1;; esac; done\n'
                  '[ "$3" = "%s/systemd/private" ]\n' % (self.sb.path(), self.rt))
        return self.sh("ag_out_of_reach %s; echo reached-the-end" % mask)

    def test_out_of_reach_passes_when_no_door_is_left(self):
        r = self.run_mask('--tmpfs "$XDG_RUNTIME_DIR/systemd"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("reached-the-end", r.stdout)
        with open(self.sb.path("asked")) as f:
            self.assertEqual(f.read().splitlines(), [
                "test -S %s/systemd/private" % self.rt, "test -S %s/bus" % self.rt,
                "test -S /run/systemd/private", "test -S /run/dbus/system_bus_socket"])

    def test_out_of_reach_dies_when_the_user_manager_is_in_reach(self):
        r = self.run_mask("--tmpfs /run/lianli")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("reached-the-end", r.stdout)
        self.assertIn("systemd user manager", r.stderr)

    def test_both_e2e_masks_keep_the_session_out(self):
        for name in ("lianli.sh", "webkit.sh"):
            with open(os.path.join(os.path.dirname(LIB), name)) as f:
                src = f.read()
            self.assertIn('"${AG_SESSION_SOCKETS[@]}"', src, name)
            self.assertIn('ag_out_of_reach "${HIDE[@]}"', src, name)
        with open(os.path.join(os.path.dirname(LIB), "lianli.sh")) as f:
            src = f.read()
        self.assertIn('"$RT"/lianli*', src)
        self.assertIn('grep -qx /run/lianli || ag_die', src)
        self.assertIn("ag_user_journal_since", src)

    def test_the_user_journal_is_read_by_user_unit(self):
        self.fake("journalctl", 'echo "$*"\n')
        r = self.sh("ag_user_journal_since c1 'lianli-*'")
        self.assertEqual(r.stdout.strip(),
                         "--user -q --no-pager --after-cursor=c1 --user-unit lianli-*")
        self.assertEqual(self.sh("ag_user_journal_since '' 'lianli-*'").stdout, "")
        self.fake("journalctl", 'echo "$*" > "%s/asked"; echo "-- cursor: s=abc"\n' % self.sb.path())
        r = self.sh("ag_user_journal_mark")
        self.assertEqual(r.stdout.strip(), "s=abc")
        with open(self.sb.path("asked")) as f:
            self.assertTrue(f.read().startswith("--user "))


if __name__ == "__main__":
    unittest.main()
