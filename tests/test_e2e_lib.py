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
    echo "$DBUS_SESSION_BUS_ADDRESS $DBUS_SYSTEM_BUS_ADDRESS" > "$d/bus"
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

    def test_the_nested_niri_and_the_helpers_get_no_bus(self):
        """The nested niri (harness start) and the e2e's own helpers (python3
        importing Gtk) run with both bus addresses on a missing socket, never
        the real session's or system's bus."""
        real = "unix:path=" + self.sb.path("bus")
        open(self.sb.path("bus"), "w").close()
        script = ('. "%s"; ag_cleanup() { :; }; ag_start s1 "";'
                  ' echo "HELPERS=$DBUS_SESSION_BUS_ADDRESS $DBUS_SYSTEM_BUS_ADDRESS"' % LIB)
        with open(os.path.join(self.dir, "misses"), "w") as f:
            f.write("0")
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                           env=dict(os.environ, APPGLASS_HARNESS=self.h,
                                    DBUS_SESSION_BUS_ADDRESS=real, DBUS_SYSTEM_BUS_ADDRESS=real))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.dir, "bus")) as f:
            niri = f.read().split()
        helpers = r.stdout.split("HELPERS=")[1].split()
        for addr in niri + helpers:
            self.assertNotEqual(addr, real)
            self.assertTrue(addr.startswith("unix:path="), addr)
            self.assertFalse(os.path.exists(addr[len("unix:path="):]), addr)
        self.assertEqual(len(niri), 2)
        self.assertEqual(len(helpers), 2)

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
        # the real bwrap is not run: the fake knows two sockets (the user
        # manager's and resolved's varlink one) and answers as if a --tmpfs or
        # --ro-bind in the mask covered the paths under it
        self.fake("bwrap", 'm=(); while [ "$1" != -- ]; do m+=("$1"); shift; done; shift\n'
                  'echo "$*" >> "%s/asked"\n'
                  'hid() { for x in "${m[@]}"; do case "$1" in "$x"/*|"$x") return 0;; esac; done; return 1; }\n'
                  'socks=("%s/systemd/private" /run/systemd/resolve/io.systemd.Resolve)\n'
                  'case $1 in\n'
                  'test) for s in "${socks[@]}"; do [ "$3" = "$s" ] && ! hid "$s" && exit 0; done; exit 1;;\n'
                  'find) for s in "${socks[@]}"; do case "$s" in "$2"/*) hid "$s" || { echo "$s"; exit 0; };; esac; done;;\n'
                  'esac\n' % (self.sb.path(), self.rt))
        return self.sh("ag_out_of_reach %s; echo reached-the-end" % mask)

    def test_out_of_reach_passes_when_no_door_is_left(self):
        r = self.run_mask('--tmpfs "$XDG_RUNTIME_DIR/systemd" --tmpfs /run/systemd')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("reached-the-end", r.stdout)
        with open(self.sb.path("asked")) as f:
            self.assertEqual(f.read().splitlines(), [
                "test -S %s/bus" % self.rt, "test -S /run/dbus/system_bus_socket",
                "find %s/systemd -type s -print -quit" % self.rt,
                "find /run/systemd -type s -print -quit"])

    def test_out_of_reach_dies_when_the_user_manager_is_in_reach(self):
        r = self.run_mask("--tmpfs /run/lianli --tmpfs /run/systemd")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("reached-the-end", r.stdout)
        self.assertIn("%s/systemd/private" % self.rt, r.stderr)
        self.assertIn("systemd manager", r.stderr)

    def test_out_of_reach_dies_on_any_socket_left_in_run_systemd(self):
        """The system manager's private socket alone is not enough: its
        varlink sockets and resolved's (DNS out of a network namespace) are
        under /run/systemd too."""
        r = self.run_mask('--tmpfs "$XDG_RUNTIME_DIR/systemd" --ro-bind /dev/null /run/systemd/private')
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("reached-the-end", r.stdout)
        self.assertIn("/run/systemd/resolve/io.systemd.Resolve", r.stderr)

    def test_the_system_doors_are_the_bus_and_all_of_run_systemd(self):
        r = self.sh('echo "${AG_SYSTEM_SOCKETS[*]}"')
        self.assertEqual(r.stdout.strip(), "/run/dbus/system_bus_socket /run/systemd")

    def test_no_dns_dies_when_a_name_resolves(self):
        self.fake("getent", 'echo "1.2.3.4 $3"\n')
        r = self.sh("ag_no_dns env; echo reached-the-end")
        self.assertEqual(r.returncode, 1)
        self.assertIn("resolves", r.stderr)
        self.fake("getent", "exit 2\n")
        r = self.sh("ag_no_dns env; echo reached-the-end")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("reached-the-end", r.stdout)

    def test_both_e2e_masks_keep_the_session_out(self):
        for name in ("lianli.sh", "webkit.sh"):
            with open(os.path.join(os.path.dirname(LIB), name)) as f:
                src = f.read()
            self.assertIn('"${AG_SESSION_SOCKETS[@]}"', src, name)
            self.assertIn('ag_out_of_reach "${HIDE[@]}"', src, name)
            self.assertIn('ag_no_dns bwrap --dev-bind / / "${HIDE[@]}"', src, name)
            self.assertNotIn("read-only question", src, name)   # only paths are looked at
        with open(os.path.join(os.path.dirname(LIB), "lianli.sh")) as f:
            src = f.read()
        self.assertIn('"$RT"/lianli*', src)
        self.assertIn("ag_hide_args /run/lianli* ", src)     # the daemon's dir and its locks
        self.assertIn('grep -qx /run/lianli || ag_die', src)
        self.assertIn("ag_user_journal_since", src)

    # one entry of each kind: the daemon's own log, a manager's job line
    DAEMON = '{"_PID":"812","_COMM":"lianli-daemon","_SYSTEMD_UNIT":"lianli-daemon.service","MESSAGE":"fan 2 rpm 900"}'
    PID1 = '{"_PID":"1","_COMM":"systemd","UNIT":"lianli-control-recovery.service","MESSAGE":"Starting lianli-control-recovery.service..."}'
    GUI = '{"_PID":"9001","_COMM":"lianli-gui","_SYSTEMD_USER_UNIT":"lianli-gui.scope","MESSAGE":"window up"}'
    USERMGR = '{"_PID":"1500","_COMM":"systemd","USER_UNIT":"lianli-session.service","MESSAGE":"Starting lianli-session.service..."}'

    def journal(self, lines):
        # the fake ignores the matches it is given: the filter must hold alone
        self.fake("journalctl", 'echo "$*" >> "%s/jargs"\ncat <<\'J\'\n%s\nJ\n'
                  % (self.sb.path(), "\n".join(lines)))

    def test_the_system_journal_gate_sees_only_the_managers_job_lines(self):
        """The real daemon logging (fans, lights) is no unit start: only the
        system manager's own lines about a lianli-* unit fail the gate."""
        self.journal([self.DAEMON])
        self.assertEqual(self.sh("ag_journal_since c1 'lianli-*'").stdout, "")
        self.journal([self.DAEMON, self.PID1])
        r = self.sh("ag_journal_since c1 'lianli-*'")
        self.assertEqual(r.stdout.strip(),
                         "lianli-control-recovery.service: Starting lianli-control-recovery.service...")
        with open(self.sb.path("jargs")) as f:
            self.assertEqual(f.read().splitlines()[-1],
                             "-q --no-pager --after-cursor=c1 -o json _PID=1")
        self.assertEqual(self.sh("ag_journal_since '' 'lianli-*'").stdout, "")

    def test_the_user_journal_is_read_by_user_unit(self):
        self.journal([self.GUI, self.DAEMON])
        self.assertEqual(self.sh("ag_user_journal_since c1 'lianli-*'").stdout, "")
        self.journal([self.GUI, self.USERMGR])
        r = self.sh("ag_user_journal_since c1 'lianli-*'")
        self.assertEqual(r.stdout.strip(), "lianli-session.service: Starting lianli-session.service...")
        with open(self.sb.path("jargs")) as f:
            self.assertEqual(f.read().splitlines()[-1],
                             "--user -q --no-pager --after-cursor=c1 -o json _COMM=systemd")
        self.assertEqual(self.sh("ag_user_journal_since '' 'lianli-*'").stdout, "")
        self.fake("journalctl", 'echo "$*" > "%s/asked"; echo "-- cursor: s=abc"\n' % self.sb.path())
        r = self.sh("ag_user_journal_mark")
        self.assertEqual(r.stdout.strip(), "s=abc")
        with open(self.sb.path("asked")) as f:
            self.assertTrue(f.read().startswith("--user "))

    def test_the_harness_does_not_pass_the_e2e_variables_on(self):
        """APPGLASS_HARNESS and APPGLASS_E2E_OUT are the e2e's, not the app's."""
        h = os.path.join(self.bin, "harness.sh")
        with open(h, "w") as f:
            f.write("#!/bin/bash\nenv | grep ^APPGLASS_ || true\necho args \"$*\"\n")
        os.chmod(h, 0o755)
        r = subprocess.run(["bash", "-c", '. "%s"; ag_harness run n -- app' % LIB],
                           capture_output=True, text=True,
                           env=dict(os.environ, APPGLASS_HARNESS=h, APPGLASS_E2E_OUT="/x"))
        self.assertEqual(r.stdout.splitlines(), ["args run n -- app"], r.stderr)

if __name__ == "__main__":
    unittest.main()
