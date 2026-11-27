"""learn: the toolkit of each open window, from niri and /proc (read-only).

``niri msg -j windows`` gives app-id + pid per window; /proc/<pid>/maps
gives the loaded libraries, /proc/<pid>/exe the binary (Electron fuses) and
/proc/<pid>/cgroup the flatpak id. Window titles are never read or stored.

A process can load several toolkits (gjs apps load WebKitGTK next to GTK4;
Electron loads GTK3 for its dialogs), so the toplevel toolkit is the first
one present in TOPLEVEL order. WebKitGTK only wins without GTK4 (Tauri).

The result is cached in $XDG_CACHE_HOME/appglass/learned.json (merged with
earlier runs, newest wins); detect reads it to fill in launchers it could
not classify statically (Go launchers, D-Bus activated portals, ...).
``appglass remove`` deletes it.

Test hooks: APPGLASS_NIRI_WINDOWS (a JSON file in place of the niri call)
and APPGLASS_PROC (a /proc stand-in).
"""

import json
import os
import re
import time

from . import detect

VERSION = 1

TOPLEVEL = ("game", "electron", "cef", "gecko", "flutter", "qt-webengine", "qt-quick",
            "qt-widgets", "gtk4-adw", "gtk4", "webkitgtk", "gtk3", "sdl")

MAP_LIBS = (
    (r"^libcef\.so", "cef"),
    (r"^libxul\.so", "gecko"),
    (r"^libflutter_linux_gtk\.so", "flutter"),
    (r"^libQt[56]WebEngineCore\.so", "qt-webengine"),
    (r"^libQt[56]Quick\.so", "qt-quick"),
    (r"^libQt[56]Widgets\.so", "qt-widgets"),
    (r"^libadwaita-1\.so", "gtk4-adw"),
    (r"^libgtk-4\.so", "gtk4"),
    (r"^libwebkit(2gtk-4\.[01]|gtk-6\.0)\.so", "webkitgtk"),
    (r"^libgtk-3\.so", "gtk3"),
    (r"^libSDL[23]", "sdl"),
    # Wine / Proton: a game, whatever else it maps (spec 1.3, sticky)
    (r"^wine64-preloader$", "game"),
    (r"^wine-preloader$", "game"),
    (r"^ntdll\.so$", "game"),
    (r"^winex11\.drv\.so$", "game"),
    (r"^winewayland\.drv\.so$", "game"),
)
# a niri window whose pid is the X11 bridge: the client is behind it
X11_BRIDGES = ("xwayland-satellite", "Xwayland")
_MAP_LIBS = tuple((re.compile(r), t) for r, t in MAP_LIBS)
_FLATPAK_SCOPE = re.compile(r"app-flatpak-([A-Za-z0-9_.-]+?)-\d+\.scope")


def path(env):
    return os.path.join(env.cache_home, "appglass", "learned.json")


def proc_root(env):
    return env.environ.get("APPGLASS_PROC") or "/proc"


def windows(env):
    """[{"app_id", "pid"}] of the open windows, or None when niri is not there."""
    f = env.environ.get("APPGLASS_NIRI_WINDOWS")
    try:
        if f:
            with open(f, "rb") as fh:
                doc = json.loads(fh.read().decode("utf-8"))
        else:
            if not env.environ.get("NIRI_SOCKET") or not env.which("niri"):
                return None
            r = env.run(["niri", "msg", "-j", "windows"], timeout=10)
            if r.returncode != 0:
                return None
            doc = json.loads(r.stdout)
    except (OSError, ValueError):
        return None
    out = []
    for w in doc if isinstance(doc, list) else []:
        if isinstance(w, dict) and w.get("app_id") and isinstance(w.get("pid"), int):
            out.append({"app_id": w["app_id"], "pid": w["pid"]})
    return out


def _read(p, n=4 << 20):
    try:
        with open(p, "rb") as f:
            return f.read(n).decode("utf-8", "replace")
    except OSError:
        return ""


def probe_pid(env, pid):
    """{"toolkit", "evidence", "exe", "flatpak"} for one process."""
    base = os.path.join(proc_root(env), str(pid))
    found = {}
    for line in _read(os.path.join(base, "maps")).splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        name = os.path.basename(parts[5].strip())
        for rx, tk in _MAP_LIBS:
            if tk not in found and rx.search(name):
                found[tk] = "maps %s" % name
                break
    exe_link = os.path.join(base, "exe")
    try:
        exe = os.readlink(exe_link)
    except OSError:
        exe = None
    fz = detect.electron_fuses(exe_link) if os.path.exists(exe_link) else None
    if fz:
        found["electron"] = "exe has the Electron %s fuse wire" % fz["electron"]
    m = _FLATPAK_SCOPE.search(_read(os.path.join(base, "cgroup"), 65536))
    toolkit = next((t for t in TOPLEVEL if t in found), None)
    if toolkit is None and exe and os.path.basename(exe) in detect.TERMINALS:
        toolkit, found["terminal"] = "terminal", "exe %s" % os.path.basename(exe)
    ev = [found[t] + " -> " + t for t in TOPLEVEL + ("terminal",) if t in found]
    return {"toolkit": toolkit or "unknown", "evidence": ev, "exe": exe,
            "flatpak": m.group(1) if m else None}


def x11_clients(env):
    """[{"class", "instance", "pid"}] of the X11 client windows (their
    _NET_WM_PID), or [] (no DISPLAY, no xprop). APPGLASS_X11_CLIENTS names a
    JSON file of the same list (tests)."""
    f = env.environ.get("APPGLASS_X11_CLIENTS")
    if f:
        try:
            with open(f, "rb") as fh:
                doc = json.loads(fh.read().decode("utf-8"))
            return [c for c in doc if isinstance(c, dict) and isinstance(c.get("pid"), int)]
        except (OSError, ValueError):
            return []
    if env.sandbox is not None or not env.environ.get("DISPLAY") or not env.which("xprop"):
        return []
    try:
        r = env.run(["xprop", "-root", "_NET_CLIENT_LIST"], timeout=5)
        ids = re.findall(r"0x[0-9a-fA-F]+", r.stdout.split("#", 1)[-1])
    except Exception:
        return []
    out = []
    for wid in ids[:200]:
        try:
            r = env.run(["xprop", "-id", wid, "_NET_WM_PID", "WM_CLASS"], timeout=5)
        except Exception:
            continue
        pid = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", r.stdout)
        m = re.search(r"WM_CLASS\(STRING\) = (.*)", r.stdout)
        cls = re.findall(r'"([^"]*)"', m.group(1)) if m else []
        if pid:
            out.append({"pid": int(pid.group(1)), "instance": cls[0] if cls else "",
                        "class": cls[1] if len(cls) > 1 else (cls[0] if cls else "")})
    return out


def client_pid(env, w, clients=None):
    """The pid to probe for a niri window: the X11 client's own
    (_NET_WM_PID) when niri names the bridge (xwayland-satellite)."""
    try:
        exe = os.path.basename(os.readlink(os.path.join(proc_root(env), str(w["pid"]), "exe")))
    except OSError:
        return w["pid"]
    if exe not in X11_BRIDGES:
        return w["pid"]
    clients = x11_clients(env) if clients is None else clients
    for c in clients:
        if w["app_id"] in (c.get("class"), c.get("instance")) or \
                w["app_id"].lower() in (c.get("class", "").lower(), c.get("instance", "").lower()):
            return c["pid"]
    return None          # an X11 window we cannot map: not the bridge's toolkit


def learn(env):
    """{app_id: record} for the open windows, or None without niri."""
    ws = windows(env)
    if ws is None:
        return None
    out = {}
    clients = None
    for w in ws:
        if w["app_id"] in out:
            continue
        pid = w["pid"]
        try:
            bridged = os.path.basename(os.readlink(os.path.join(proc_root(env), str(pid), "exe")))
        except OSError:
            bridged = None
        if bridged in X11_BRIDGES:
            if clients is None:
                clients = x11_clients(env)
            pid = client_pid(env, w, clients)
            if pid is None:
                continue
        rec = probe_pid(env, pid)
        rec["pid"] = pid
        if pid != w["pid"]:
            rec["evidence"] = rec["evidence"] + ["X11 client of %s (_NET_WM_PID %d)"
                                                 % (bridged, pid)]
        out[w["app_id"]] = rec
    return out


def load(env):
    try:
        with open(path(env), "rb") as f:
            doc = json.loads(f.read().decode("utf-8"))
        apps = doc.get("apps", {}) if isinstance(doc, dict) else {}
        # an entry that is not an object (a hand edit) would crash merge()
        return ({k: v for k, v in apps.items() if isinstance(v, dict)}
                if isinstance(apps, dict) else {})
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


def save(env, found):
    from .core import _atomic_write, _missing_dirs
    apps = load(env)
    stamp = time.strftime("%Y-%m-%d")
    for app_id, rec in found.items():
        r = {k: rec[k] for k in ("toolkit", "evidence", "exe", "flatpak")}
        r["seen"] = stamp
        apps[app_id] = r
    p = path(env)
    env.guard(p)
    for d in _missing_dirs(os.path.dirname(p)):
        env.guard(d)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = json.dumps({"version": VERSION, "apps": apps}, indent=2, sort_keys=True) + "\n"
    _atomic_write(p, data.encode("utf-8"))
    return p


def forget(env):
    p = path(env)
    if not os.path.exists(p):
        return False
    env.guard(p)
    os.remove(p)
    try:
        os.rmdir(os.path.dirname(p))
    except OSError:
        pass
    return True


def merge(records, learned):
    """detect records + learned windows. A launcher whose app-id regex or name
    matches a learned app-id takes the runtime toolkit (static kept in
    toolkit_static); learned windows no launcher claims become records with
    source "learned"."""
    claimed = set()
    for r in records:
        for app_id, l in learned.items():
            if app_id in r.get("names", ()) or any(re.search(rx, app_id)
                                                   for rx in r.get("app_ids", ())):
                claimed.add(app_id)
                if l.get("toolkit") == "game":
                    r.setdefault("classes", {})["game"] = "runtime: %s" % "; ".join(
                        l.get("evidence", []))[:200]
                if l.get("toolkit", "unknown") != "unknown":
                    r["toolkit_static"] = r["toolkit"]
                    r["toolkit"] = l["toolkit"]
                    r["strong"] = True
                    r["evidence"] = ["runtime: " + e for e in l.get("evidence", [])] + \
                        r.get("evidence", [])
                    if app_id not in r["names"]:
                        r["names"].append(app_id)
                r["learned"] = app_id
    for app_id in sorted(learned):
        if app_id in claimed:
            continue
        l = learned[app_id]
        records.append({
            "key": app_id, "desktop_id": None, "path": None, "name": app_id,
            "overridden_by": None, "nodisplay": False, "flatpak": None, "installed": True,
            "names": [app_id], "app_ids": [detect._rx(app_id)], "exec": l.get("exe"),
            "toolkit": l.get("toolkit", "unknown"),
            "evidence": ["runtime: " + e for e in l.get("evidence", [])],
            "fuses": None, "learned": app_id, "source": "learned", "strong": True,
        })
    records.sort(key=lambda r: r["key"].lower())
    return records
