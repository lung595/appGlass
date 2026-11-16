"""appglass vibrancy: fade unfocused Alacritty windows (settings inactive).

niri cannot animate a window-rule opacity, and Alacritty has no CSS, so this
small daemon does it: it follows ``niri msg -j event-stream`` and, for every
Alacritty window, eases ``window.opacity`` between the content level
(focused) and the inactive level (appglass/inactive.py) over Alacritty's IPC
socket ($XDG_RUNTIME_DIR/Alacritty-<WAYLAND_DISPLAY>-<pid>.sock). Only the
background changes: Alacritty's opacity never applies to the glyphs.

A focused window ends with ``reset`` (back to the opacity of its config
file, which appglass.toml sets to the content level). Keyboard focus moving
to a layer-shell surface (the DMS launcher, a popup) is ignored, so the
windows stay as they are, like niri's own is-active.

It re-reads settings.json, state.json and the DMS window rules when they
change, so it needs no restart: with inactive off, appglass off or the
alacritty family not applied it puts every window back and idles. On
SIGTERM, and when niri goes away, every window it changed is reset.

Run by appglass-vibrancy.service (``appglass hook install``).
"""

import glob
import json
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time

from . import inactive

APP_IDS = ("Alacritty",)
FRAME = 1 / 60
IDLE_WAIT = 2.0
CONFIG_EVERY = 0.5
RESET = None            # a send() value: back to the config file opacity


class Fader:
    """The windows and their animation; pure (the caller gives the time and
    sends the (pid, value) pairs it returns, value RESET or an opacity)."""

    def __init__(self, app_ids=APP_IDS):
        self.app_ids = set(app_ids)
        self.win = {}           # id -> {"pid", "focused", "v", "from", "to", "t0"}
        self.touched = set()    # pids sent a value since their last reset
        self.on = False
        self.content = 1.0
        self.ratio = 1.0
        self.duration = 0.0
        self.easing = "ease-out-cubic"

    # --- configuration
    def configure(self, on, content=1.0, ratio=1.0, duration_ms=0, easing="ease-out-cubic"):
        """New settings: every window jumps to its new target (no animation)."""
        self.on = bool(on) and ratio < 1.0
        self.content, self.ratio = float(content), float(ratio)
        self.duration = max(0, int(duration_ms)) / 1000.0
        self.easing = easing
        out = []
        for w in self.win.values():
            to = self._target(w)
            w.update({"v": to, "from": to, "to": to})
            out += self._send(w)
        return out

    def _target(self, w):
        return 1.0 if (w["focused"] or not self.on) else self.ratio

    def _send(self, w):
        if w["v"] >= 1.0:
            if w["pid"] in self.touched:
                self.touched.discard(w["pid"])
                return [(w["pid"], RESET)]
            return []
        self.touched.add(w["pid"])
        return [(w["pid"], round(self.content * w["v"], 3))]

    @property
    def animating(self):
        return any(w["v"] != w["to"] for w in self.win.values())

    # --- niri events
    def _add(self, d, now):
        w = {"pid": d.get("pid"), "focused": bool(d.get("is_focused"))}
        to = self._target(w)
        w.update({"v": to, "from": to, "to": to, "t0": now})
        self.win[d["id"]] = w
        return self._send(w)

    def _retarget(self, now):
        for w in self.win.values():
            to = self._target(w)
            if to != w["to"]:
                w.update({"from": w["v"], "to": to, "t0": now})

    def _drop(self, wid):
        w = self.win.pop(wid, None)
        if w is not None:
            self.touched.discard(w["pid"])   # the socket goes with the window

    def _ours(self, d):
        return d.get("app_id") in self.app_ids and isinstance(d.get("pid"), int)

    def on_event(self, ev, now):
        out = []
        if not isinstance(ev, dict):
            return out
        if "WindowsChanged" in ev:
            seen = set()
            for d in ev["WindowsChanged"].get("windows") or []:
                if not self._ours(d):
                    continue
                seen.add(d["id"])
                if d["id"] in self.win:
                    self.win[d["id"]]["focused"] = bool(d.get("is_focused"))
                else:
                    out += self._add(d, now)
            for wid in set(self.win) - seen:
                self._drop(wid)
        elif "WindowOpenedOrChanged" in ev:
            d = ev["WindowOpenedOrChanged"].get("window") or {}
            if self._ours(d) and d["id"] not in self.win:
                out += self._add(d, now)
            elif self._ours(d):
                self.win[d["id"]]["focused"] = bool(d.get("is_focused"))
            if d.get("is_focused"):
                for wid, w in self.win.items():
                    w["focused"] = wid == d["id"]
        elif "WindowClosed" in ev:
            self._drop(ev["WindowClosed"].get("id"))
        elif "WindowFocusChanged" in ev:
            fid = ev["WindowFocusChanged"].get("id")
            if fid is None:
                return out      # a layer-shell surface took the keyboard
            for wid, w in self.win.items():
                w["focused"] = wid == fid
        else:
            return out
        self._retarget(now)
        return out

    def tick(self, now):
        out = []
        for w in self.win.values():
            if w["v"] == w["to"]:
                continue
            x = (now - w["t0"]) / self.duration if self.duration > 0 else 1.0
            if x >= 1:
                w["v"] = w["to"]
            else:
                w["v"] = w["from"] + (w["to"] - w["from"]) * inactive.ease(self.easing, x)
            out += self._send(w)
        return out

    def release(self):
        """Reset every window this daemon changed."""
        out = [(w["pid"], RESET) for w in self.win.values() if w["pid"] in self.touched]
        self.touched.clear()
        for w in self.win.values():
            w.update({"v": 1.0, "from": 1.0, "to": 1.0})
        return out


# ---------------------------------------------------------------- the desktop side

def runtime_dir(env):
    return env.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()


def message(value):
    if value is RESET:
        cfg = {"window_id": -1, "options": [], "reset": True}
    else:
        cfg = {"window_id": -1, "options": ["window.opacity=%.3f" % value], "reset": False}
    return (json.dumps({"Config": cfg}) + "\n").encode()


class Sender:
    def __init__(self, env):
        self.rt = runtime_dir(env)
        self.wl = env.environ.get("WAYLAND_DISPLAY")

    def socket_path(self, pid):
        if self.wl:
            p = os.path.join(self.rt, "Alacritty-%s-%d.sock" % (self.wl, pid))
            if os.path.exists(p):
                return p
        hits = glob.glob(os.path.join(glob.escape(self.rt), "Alacritty-*-%d.sock" % pid))
        return hits[0] if hits else None

    def __call__(self, pid, value):
        p = self.socket_path(pid)
        if p is None:
            return False
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(0.05)
            s.connect(p)
            s.sendall(message(value))
            return True
        except OSError:
            return False
        finally:
            s.close()


def niri_env(env):
    """The environment for niri msg: NIRI_SOCKET from the newest niri socket
    when the service manager did not pass one."""
    e = dict(env.environ)
    if not e.get("NIRI_SOCKET"):
        socks = glob.glob(os.path.join(glob.escape(runtime_dir(env)), "niri.*.sock"))
        if socks:
            e["NIRI_SOCKET"] = max(socks, key=os.path.getmtime)
    return e


class Config:
    """settings.json + state.json + the DMS level, re-read when they change."""

    def __init__(self, env):
        from . import settings as _settings
        self.env = env
        self.paths = (_settings.path(env), os.path.join(env.state_dir, "state.json"),
                      env.config_path("niri", "dms", "windowrules.kdl"),
                      env.config_path("dms", "settings.json"))
        self.stamp = None

    def _stamp(self):
        out = []
        for p in self.paths:
            try:
                st = os.stat(p)
                out.append((st.st_mtime_ns, st.st_size, st.st_ino))
            except OSError:
                out.append(None)
        return tuple(out)

    def changed(self):
        s = self._stamp()
        if s == self.stamp:
            return False
        self.stamp = s
        return True

    def read(self):
        """configure() keyword arguments."""
        from . import core, settings as _settings
        s, err = _settings.load(self.env)
        st = core._load_json(self.paths[1])
        owners = st.get("owners", {}) if isinstance(st, dict) else {}
        p = inactive.params(s)
        content = core.Levels.from_env(self.env, s).content
        on = bool(s.get("enabled", True) and p["enabled"] and "alacritty" in owners)
        return {"on": on, "content": content, "ratio": inactive.ratio(content, p["factor"]),
                "duration_ms": p["durationMs"], "easing": p["easing"]}


def _reader(proc, q):
    try:
        for line in proc.stdout:
            q.put(line)
    except (OSError, ValueError):
        pass            # closed on the way out
    q.put(None)


def run(env, out=None, err=None, send=None, clock=time.monotonic):
    """The daemon loop. Returns 1 when niri goes away (systemd restarts it)."""
    err = err or sys.stderr
    if env.sandbox is not None:
        rt = os.path.realpath(runtime_dir(env))
        if not rt.startswith(env.sandbox + os.sep):
            print("appglass vibrancy: APPGLASS_SANDBOX set and XDG_RUNTIME_DIR is "
                  "outside it: refusing to talk to real windows", file=err)
            return 2
    niri = env.which("niri")
    if not niri:
        print("appglass vibrancy: niri not found", file=err)
        return 1
    send = send or Sender(env)
    fader, cfg = Fader(), Config(env)

    def flush(pairs):
        for pid, v in pairs:
            send(pid, v)

    def stop(*_a):
        raise SystemExit(0)

    old = None
    if threading.current_thread() is threading.main_thread():
        old = signal.signal(signal.SIGTERM, stop)
    proc = subprocess.Popen([niri, "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, env=niri_env(env))
    q = queue.Queue()
    threading.Thread(target=_reader, args=(proc, q), daemon=True).start()
    last_cfg = 0.0
    try:
        while True:
            now = clock()
            if now - last_cfg >= CONFIG_EVERY:
                last_cfg = now
                if cfg.changed():
                    flush(fader.configure(**cfg.read()))
            try:
                line = q.get(timeout=FRAME if fader.animating else min(IDLE_WAIT, CONFIG_EVERY))
            except queue.Empty:
                line = ""
            if line is None:
                print("appglass vibrancy: niri event stream ended", file=err)
                return 1
            if line.strip():
                try:
                    flush(fader.on_event(json.loads(line), clock()))
                except ValueError:
                    pass
            flush(fader.tick(clock()))
    finally:
        flush(fader.release())
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        proc.stdout.close()
        if old is not None:
            signal.signal(signal.SIGTERM, old)
