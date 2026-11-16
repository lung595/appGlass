"""appglass vibrancy: the Alacritty fade (state machine, socket, daemon loop)."""

import io
import json
import os
import socket
import stat
import threading
import unittest

from fixtures.sandbox import Sandbox
from appglass import core, vibrancy
from appglass.vibrancy import RESET, Fader


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

    def test_focus_change_eases_and_ends_with_reset(self):
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
        self.assertEqual(end, {101: 0.72, 102: RESET})
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
        self.assertEqual(f.configure(False, 0.8, 0.9, 180), [(102, RESET)])
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
        self.assertEqual(sorted(f.release()), [(102, RESET), (103, RESET)])
        self.assertEqual(f.release(), [])

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
        self.rt = self.sb.path("run")
        os.makedirs(self.rt)

    def tearDown(self):
        self.sb.cleanup()

    def test_message_format(self):
        self.assertEqual(json.loads(vibrancy.message(0.72)), {"Config": {
            "window_id": -1, "options": ["window.opacity=0.720"], "reset": False}})
        self.assertEqual(json.loads(vibrancy.message(RESET)), {"Config": {
            "window_id": -1, "options": [], "reset": True}})

    def test_sends_to_the_window_socket(self):
        env = core.Env(dict(self.sb.env, XDG_RUNTIME_DIR=self.rt, WAYLAND_DISPLAY="wayland-1"))
        a = Listener(os.path.join(self.rt, "Alacritty-wayland-1-101.sock"))
        b = Listener(os.path.join(self.rt, "Alacritty-wayland-9-102.sock"))
        try:
            send = vibrancy.Sender(env)
            self.assertTrue(send(101, 0.72))
            self.assertTrue(send(102, RESET))           # another display name: globbed
            self.assertFalse(send(103, 0.72))           # no socket: skipped
            for _ in range(100):
                if a.msgs and b.msgs:
                    break
                threading.Event().wait(0.02)
            self.assertEqual(a.msgs[0]["Config"]["options"], ["window.opacity=0.720"])
            self.assertTrue(b.msgs[0]["Config"]["reset"])
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

    def test_fades_and_resets_at_the_end(self):
        self.sb.set_level(0.8)
        self.state({"alacritty": {"files": {}, "app_ids": ["^Alacritty$"]}})
        self.fake_niri(self.EVENTS)
        code, sent, err = self.run_daemon()
        self.assertEqual(code, 1, err)
        self.assertIn("event stream ended", err)
        self.assertEqual(sent[0], (102, 0.72))
        vals101 = [v for p, v in sent if p == 101 and v is not RESET]
        self.assertGreater(len(vals101), 3, sent)      # several frames, not a jump
        self.assertEqual(vals101[-1], 0.72)
        self.assertIn((102, RESET), sent)
        self.assertEqual(sent[-1], (101, RESET))       # released on exit

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
