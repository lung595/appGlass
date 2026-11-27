"""appglass vibrancy: the Alacritty fade (state machine, socket, daemon loop)."""

import io
import json
import os
import shutil
import signal
import socket
import stat
import tempfile
import threading
import time
import unittest

from fixtures.sandbox import Sandbox
from appglass import core, vibrancy
from appglass.vibrancy import Fader


def win(i, pid, focused=False, app="Alacritty"):
    return {"id": i, "pid": pid, "app_id": app, "is_focused": focused}


def on(f, content=0.8, ratio=0.9, ms=180, easing="ease-out-cubic"):
    return f.configure(True, content, ratio, ms, easing)


class FaderTest(unittest.TestCase):
    def test_first_sight_jumps(self):
        f = Fader()
        on(f)
        out = f.on_event({"WindowsChanged": {"windows": [
            win(1, 101, True), win(2, 102), win(3, 103, app="org.gnome.Nautilus")]}}, 0)
        self.assertEqual(out, [(102, 0.72)])       # the focused one is left at its file opacity
        self.assertFalse(f.animating)

    def test_focus_change_eases_and_ends_at_the_file_opacity(self):
        f = Fader()
        on(f)
        f.on_event({"WindowsChanged": {"windows": [win(1, 101, True), win(2, 102)]}}, 0)
        self.assertEqual(f.on_event({"WindowFocusChanged": {"id": 2}}, 10.0), [])
        self.assertTrue(f.animating)
        mid = dict(f.tick(10.09))
        # 101 fades out, 102 fades in, both strictly between the two levels
        self.assertTrue(0.72 < mid[101] < 0.8, mid)
        self.assertTrue(0.72 < mid[102] < 0.8, mid)
        # ease-out-cubic: more than half the way at half the time
        self.assertLess(mid[101], 0.76)
        end = dict(f.tick(10.2))
        self.assertEqual(end, {101: 0.72, 102: 0.8})   # window.opacity, not a reset
        self.assertFalse(f.animating)
        self.assertEqual(f.tick(10.3), [])

    def test_layer_shell_focus_ignored(self):
        f = Fader()
        on(f)
        f.on_event({"WindowsChanged": {"windows": [win(1, 101, True), win(2, 102)]}}, 0)
        self.assertEqual(f.on_event({"WindowFocusChanged": {"id": None}}, 1), [])
        self.assertFalse(f.animating)

    def test_open_close(self):
        f = Fader()
        on(f, ms=0)
        f.on_event({"WindowsChanged": {"windows": [win(1, 101, True)]}}, 0)
        out = f.on_event({"WindowOpenedOrChanged": {"window": win(2, 102, True)}}, 1)
        self.assertEqual(out, [])
        self.assertEqual(f.tick(1), [(101, 0.72)])     # 0 ms: straight to the level
        f.on_event({"WindowClosed": {"id": 1}}, 2)
        self.assertNotIn(1, f.win)
        self.assertEqual(f.release(), [])              # 102 was never changed

    def test_off_resets_and_idles(self):
        f = Fader()
        on(f)
        f.on_event({"WindowsChanged": {"windows": [win(1, 101, True), win(2, 102)]}}, 0)
        self.assertEqual(f.configure(False, 0.8, 0.9, 180), [(102, 0.8)])
        self.assertEqual(f.on_event({"WindowFocusChanged": {"id": 2}}, 1), [])
        self.assertEqual(f.tick(2), [])
        # at the floor (ratio 1) it is off too
        f.configure(True, 0.6, 1.0, 180)
        self.assertFalse(f.on)

    def test_settings_change_jumps(self):
        f = Fader()
        on(f)
        f.on_event({"WindowsChanged": {"windows": [win(1, 101, True), win(2, 102)]}}, 0)
        self.assertEqual(on(f, content=0.9, ratio=0.8), [(102, 0.72)])

    def test_release(self):
        f = Fader()
        on(f)
        f.on_event({"WindowsChanged": {"windows": [win(1, 101, True), win(2, 102),
                                                   win(3, 103)]}}, 0)
        self.assertEqual(sorted(f.release()), [(102, 0.8), (103, 0.8)])
        self.assertEqual(f.release(), [])

    def test_windows_of_one_process_fade_together(self):
        """window_id -1 sets every window of the process: it fades only when
        none of them is focused (no flip-flop between two of its windows)."""
        f = Fader()
        on(f, ms=0)
        out = f.on_event({"WindowsChanged": {"windows": [
            win(1, 101, True), win(2, 101), win(3, 103)]}}, 0)
        self.assertEqual(out, [(103, 0.72)])      # 101 has a focused window
        f.on_event({"WindowFocusChanged": {"id": 2}}, 1)
        self.assertFalse(f.animating)
        self.assertEqual(f.tick(1), [])           # still focused: nothing sent
        f.on_event({"WindowFocusChanged": {"id": 3}}, 2)
        self.assertEqual(sorted(f.tick(2)), [(101, 0.72), (103, 0.8)])
        f.on_event({"WindowOpenedOrChanged": {"window": win(4, 101)}}, 3)
        self.assertEqual(f.tick(3), [])           # a new unfocused window of 101
        f.on_event({"WindowClosed": {"id": 1}}, 4)
        f.on_event({"WindowClosed": {"id": 2}}, 4)
        self.assertIn(101, f.anim)                # window 4 is still open
        f.on_event({"WindowFocusChanged": {"id": 4}}, 5)
        self.assertEqual(sorted(f.tick(5)), [(101, 0.8), (103, 0.72)])
        f.on_event({"WindowClosed": {"id": 4}}, 6)
        self.assertNotIn(101, f.anim)
        self.assertNotIn(101, f.touched)

    def test_back_to_the_configured_opacity(self):
        f = Fader()
        f.configure(True, 0.8, 0.9, 0, configured=0.95)
        f.on_event({"WindowsChanged": {"windows": [win(1, 101, True), win(2, 102)]}}, 0)
        f.on_event({"WindowFocusChanged": {"id": 2}}, 1)
        self.assertEqual(dict(f.tick(1)), {101: 0.72, 102: 0.95})
        # a level change reaches 102 too: our runtime option outlives a file reload
        self.assertEqual(sorted(f.configure(True, 0.7, 0.9, 0, configured=0.7)),
                         [(101, 0.63), (102, 0.7)])

    def test_file_opacity(self):
        sb = Sandbox()
        try:
            env = core.Env(sb.env)
            self.assertEqual(vibrancy.file_opacity(env, 0.8049, True), 0.8)
            self.assertEqual(vibrancy.file_opacity(env, 0.8, False), 1.0)
            sb.write("alacritty/alacritty.toml", "[window]\nopacity = 0.95\n")
            self.assertEqual(vibrancy.file_opacity(env, 0.8, False), 0.95)
            sb.write("alacritty/alacritty.toml", "[window]\nopacity = 'x'\n")
            self.assertEqual(vibrancy.file_opacity(env, 0.8, False), 1.0)
        finally:
            sb.cleanup()

    def test_junk_events(self):
        f = Fader()
        on(f)
        for ev in ([], "x", {"Nope": {}}, {"WindowsChanged": {}},
                   {"WindowOpenedOrChanged": {"window": {"id": 4, "app_id": "Alacritty"}}}):
            self.assertEqual(f.on_event(ev, 0), [])
        self.assertEqual(f.win, {})


class Listener:
    """A fake Alacritty IPC socket that records every message."""

    def __init__(self, path):
        self.path, self.msgs = path, []
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.bind(path)
        self.s.listen(8)
        self.s.settimeout(5)
        self.t = threading.Thread(target=self.loop, daemon=True)
        self.t.start()

    def loop(self):
        while True:
            try:
                c, _ = self.s.accept()
            except OSError:
                return
            data = b""
            while not data.endswith(b"\n"):
                chunk = c.recv(4096)
                if not chunk:
                    break
                data += chunk
            c.close()
            self.msgs.append(json.loads(data))

    def close(self):
        self.s.close()


class SenderTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        # a short runtime dir: an AF_UNIX path holds at most 107 bytes, and
        # the sandbox under a long TMPDIR goes past it
        self.rt = tempfile.mkdtemp(prefix="agv", dir="/tmp")

    def tearDown(self):
        shutil.rmtree(self.rt, ignore_errors=True)
        self.sb.cleanup()

    def test_message_format(self):
        self.assertEqual(json.loads(vibrancy.message(0.72)), {"Config": {
            "window_id": -1, "options": ["window.opacity=0.720"], "reset": False}})
        self.assertEqual(json.loads(vibrancy.message(1.0)), {"Config": {
            "window_id": -1, "options": ["window.opacity=1.000"], "reset": False}})

    def test_sends_to_the_window_socket(self):
        env = core.Env(dict(self.sb.env, XDG_RUNTIME_DIR=self.rt, WAYLAND_DISPLAY="wayland-1"))
        a = Listener(os.path.join(self.rt, "Alacritty-wayland-1-101.sock"))
        b = Listener(os.path.join(self.rt, "Alacritty-wayland-9-102.sock"))
        try:
            send = vibrancy.Sender(env)
            self.assertTrue(send(101, 0.72))
            self.assertTrue(send(102, 0.8))             # another display name: globbed
            self.assertFalse(send(103, 0.72))           # no socket: skipped
            for _ in range(100):
                if a.msgs and b.msgs:
                    break
                threading.Event().wait(0.02)
            self.assertEqual(a.msgs[0]["Config"]["options"], ["window.opacity=0.720"])
            self.assertEqual(b.msgs[0]["Config"]["options"], ["window.opacity=0.800"])
            self.assertFalse(b.msgs[0]["Config"]["reset"])
        finally:
            a.close()
            b.close()

    def test_niri_socket_fallback(self):
        env = core.Env(dict(self.sb.env, XDG_RUNTIME_DIR=self.rt))
        p = os.path.join(self.rt, "niri.wayland-1.1234.sock")
        open(p, "w").close()
        self.assertEqual(vibrancy.niri_env(env)["NIRI_SOCKET"], p)
        env = core.Env(dict(self.sb.env, XDG_RUNTIME_DIR=self.rt, NIRI_SOCKET="/x"))
        self.assertEqual(vibrancy.niri_env(env)["NIRI_SOCKET"], "/x")


class Daemon(unittest.TestCase):
    """run() against a fake niri that prints an event stream and exits."""

    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.rt = self.sb.path("run")
        self.bin = self.sb.path("bin")
        os.makedirs(self.rt)
        os.makedirs(self.bin)

    def tearDown(self):
        self.sb.cleanup()

    def fake_niri(self, events, pause=0.4):
        lines = "\n".join("printf '%%s\\n' '%s'; sleep %s" % (json.dumps(e), pause)
                          for e in events)
        p = os.path.join(self.bin, "niri")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n[ \"$1 $2 $3\" = 'msg -j event-stream' ] || exit 3\n"
                    "sleep 0.7\n%s\n" % lines)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)

    def state(self, owners):
        self.sb.write("appglass/state.json", json.dumps(
            {"version": core.STATE_VERSION, "owners": owners, "state_parents": []}),
            base=self.sb.state)

    def run_daemon(self, extra=None):
        env = dict(self.sb.env, XDG_RUNTIME_DIR=self.rt,
                   PATH=self.bin + os.pathsep + self.sb.env["PATH"])
        env.update(extra or {})
        sent, err = [], io.StringIO()
        code = vibrancy.run(core.Env(env), err=err, send=lambda pid, v: sent.append((pid, v)))
        return code, sent, err.getvalue()

    EVENTS = [{"WindowsChanged": {"windows": [win(1, 101, True), win(2, 102)]}},
              {"WindowFocusChanged": {"id": 2}}]

    def test_fades_and_puts_back_at_the_end(self):
        self.sb.set_level(0.8)
        self.state({"alacritty": {"files": {}, "app_ids": ["^Alacritty$"]}})
        self.fake_niri(self.EVENTS)
        code, sent, err = self.run_daemon()
        self.assertEqual(code, 1, err)
        self.assertIn("event stream ended", err)
        self.assertEqual(sent[0], (102, 0.72))
        vals101 = [v for p, v in sent if p == 101 and v < 0.8]
        self.assertGreater(len(vals101), 3, sent)      # several frames, not a jump
        self.assertEqual(vals101[-1], 0.72)
        self.assertIn((102, 0.8), sent)
        self.assertEqual(sent[-1], (101, 0.8))         # put back on exit

    def test_idle_without_the_family_or_when_off(self):
        self.sb.set_level(0.8)
        self.state({})
        self.fake_niri(self.EVENTS)
        code, sent, err = self.run_daemon()
        self.assertEqual(sent, [])
        self.state({"alacritty": {"files": {}}})
        self.sb.run("set", "inactive.enabled", "false")
        code, sent, err = self.run_daemon()
        self.assertEqual(sent, [])

    def test_idle_means_no_wakeup(self):
        """No polling: the files are stat'ed at start and on each niri event
        only, not while the stream is quiet."""
        self.sb.set_level(0.8)
        self.state({"alacritty": {"files": {}}})
        self.fake_niri(self.EVENTS[:1], pause=2)
        calls = []
        orig = vibrancy.Config._stamp

        def counted(cfg):
            calls.append(1)
            return orig(cfg)
        vibrancy.Config._stamp = counted
        try:
            code, sent, err = self.run_daemon()
        finally:
            vibrancy.Config._stamp = orig
        self.assertEqual(code, 1, err)
        self.assertEqual(len(calls), 2)

    def test_sighup_rereads_the_settings(self):
        """systemctl reload (SIGHUP) while idle: the new settings show at
        once, not at the next niri event."""
        self.sb.set_level(0.8)
        self.state({})
        self.fake_niri(self.EVENTS, pause=1.5)
        t0 = time.monotonic()

        def hup():
            self.state({"alacritty": {"files": {}}})
            os.kill(os.getpid(), signal.SIGHUP)
        timer = threading.Timer(1.2, hup)
        timer.start()
        env = dict(self.sb.env, XDG_RUNTIME_DIR=self.rt,
                   PATH=self.bin + os.pathsep + self.sb.env["PATH"])
        sent = []
        code = vibrancy.run(core.Env(env), err=io.StringIO(),
                            send=lambda pid, v: sent.append((pid, v, time.monotonic() - t0)))
        timer.join()
        self.assertEqual(code, 1)
        first = [t for p, v, t in sent if (p, v) == (102, 0.72)]
        self.assertTrue(first, sent)
        self.assertLess(first[0], 2.0, sent)      # before the 2.2 s focus event
        self.assertEqual(signal.getsignal(signal.SIGHUP), signal.SIG_DFL)

    def test_refuses_real_runtime_dir_in_sandbox(self):
        self.fake_niri([])
        code, sent, err = self.run_daemon({"XDG_RUNTIME_DIR": "/run/user/0"})
        self.assertEqual(code, 2)
        self.assertIn("refusing", err)

    def test_cli_entry(self):
        self.fake_niri([])
        code, out, err = self.sb.run("vibrancy", env={"XDG_RUNTIME_DIR": "/nonexistent-run"})
        self.assertEqual(code, 2, err)


if __name__ == "__main__":
    unittest.main()
