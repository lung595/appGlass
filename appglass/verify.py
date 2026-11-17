"""appglass verify / launch-check / fail / keys: the engine's checks.

verify <key> | --queue
    The pixel check (spec 1.7) in a hidden headless session, fully apart
    from the real one: a short private XDG_RUNTIME_DIR (made with mktemp in
    $XDG_RUNTIME_DIR, or $APPGLASS_VERIFY_BASE), env -i with an allow-list,
    dbus-run-session, a throwaway HOME holding a copy of the app's glass
    files, gamescope --backend headless --expose-wayland and a nested niri
    with animations off (shims/verify/appglass-verify-run). The app starts
    from its glass launcher; the window shot (niri screenshot-window,
    premultiplied alpha) must show the background within 0.05 of the
    content level and opaque text. PASS lets an injected route go live for
    this app version (fingerprint); FAIL makes it run plain with one
    notification. A window that does not show within 10 s is
    "unverifiable": an injected route stays off, a theme route stays on.
    Not run while a game window is open (exit 75: try later), nor on a
    battery under 20 %. In a sandbox only the stand-in named by
    $APPGLASS_VERIFY_HARNESS runs (it prints the result as JSON).
    A run checks what fits BUDGET seconds ($APPGLASS_VERIFY_BUDGET), runs
    the hook apply after each result and leaves the rest queued for the next
    event (the unit's TimeoutSec is above BUDGET + 2 * APP_MAX). SIGTERM
    (systemd stopping the unit) still kills the hidden session and deletes
    its private dir; a dir left by a killed run is swept at the next start.

launch-check <key> <pid>
    Started by each glass wrapper (setsid -f) before it runs the app: polls
    the niri windows once a second for up to 20 s. A window of that pid, a
    child of it, or the app's app-id is a good launch; the pid gone with no
    window is a failed one. Two failed launches on the same app version:
    the app runs plain until its next update, one notification.

fail <key> [reason]
    Record one failed launch by hand (what launch-check does).

keys <key> <mode>
    The colour keys of a ck-shim app as APPGLASS_KEYS wants them
    (hex:level,...), read from ~/.cache/appglass/keys/<key>/<fp>/<mode>.json
    (seeded from the family's defaults). Nothing printed (exit 1) without
    keys: the wrapper then starts the plain app.
"""

import collections
import json
import os
import re
import shutil
import stat
import signal
import subprocess
import tempfile
import time

from . import engine

EX_TEMPFAIL = 75
BUDGET = 25 * 60       # seconds of checks per run, the rest stays queued
APP_MAX = 90           # one app at most: staging, the 50 s session, the apply
STALE_RUN = 15 * 60    # an agv.* dir older than this is a killed run's
WINDOW_WAIT = 10
LAUNCH_WAIT = 20
TOL = 0.05


class Busy(Exception):
    pass


# ---------------------------------------------------------------- guards

def game_running(app):
    """The app-id of an open game window, or None."""
    from . import learn, niri
    ws = learn.windows(app.env) or []
    games = list(niri.GAME_IDS)
    st = engine.store(app)
    for r in engine.records(app):
        if r["key"] in st.data["games"] or r.get("toolkit") == "game":
            games += r.get("app_ids") or []
    for w in ws:
        if any(re.search(rx, w["app_id"]) for rx in games):
            return w["app_id"]
    return None


def on_low_battery(env):
    base = env.environ.get("APPGLASS_POWER_SUPPLY") or "/sys/class/power_supply"
    try:
        names = os.listdir(base)
    except OSError:
        return False
    for n in names:
        d = os.path.join(base, n)
        try:
            with open(os.path.join(d, "type")) as f:
                if f.read().strip() != "Battery":
                    continue
            with open(os.path.join(d, "status")) as f:
                status = f.read().strip()
            with open(os.path.join(d, "capacity")) as f:
                cap = int(f.read().strip())
        except (OSError, ValueError):
            continue
        if status == "Discharging" and cap < 20:
            return True
    return False


# ---------------------------------------------------------------- the check

def route_of(app, rec):
    from . import adapters
    return adapters.resolve(rec, app.families, app.settings,
                            gate=lambda r, injected, explicit: ("glass", None))


def launcher_exec(app, rec, home):
    """The command the glass launcher runs (field codes out), with the real
    $HOME rewritten to the throwaway one; None without a launcher."""
    from . import detect
    did = rec.get("desktop_id") or ""
    rel = os.path.relpath(os.path.join(app.env.data_home, "applications", did), app.env.home)
    # the staged launcher (a family waiting for its first check has none on
    # disk), else the one on disk, else the app's own
    p = os.path.join(home, rel) if did and not rel.startswith("..") else ""
    if not os.path.isfile(p):
        p = os.path.join(app.env.data_home, "applications", did)
    if not did or not os.path.isfile(p):
        p = rec.get("path")
    if not p or not os.path.isfile(p):
        return None
    ex = detect.parse_desktop(p).get("Exec") or ""
    ex = re.sub(r"\s%[fFuUdDnNickvm]\b", "", ex).replace("@@u", "").replace("@@", "")
    return ex.replace(app.env.home, home)


def candidate(app, owner):
    """{path: (bytes, mode)}: the files the family would write now (its
    plan, never committed). A family waiting for its first check has none
    on disk yet; a stale one may plan new ones for the update."""
    fam = app.families.get(owner)
    if fam is None:
        return {}
    ctx = app.ctx(owner)
    try:
        fam.apply(ctx)
    except Exception:
        return {}
    return {p: (op.data, op.mode) for p, op in ctx.ops.items()
            if op.kind != "retire" and isinstance(op.data, bytes)}


def stage(app, rec, run):
    """The throwaway HOME: the glass files of this app's family (the ones
    it owns, then its candidate plan on top; text files get the real $HOME
    rewritten), the DMS colours, the appglass settings. Returns the home dir."""
    env = app.env
    home = os.path.join(run, "h")
    owner = route_of(app, rec).get("family")
    files = set()
    for name in ("niri", owner):
        files.update((app.state.owners.get(name) or {}).get("files", {}))
    files.add(env.cache_path("dms", "dms-colors.json"))
    files.add(os.path.join(env.state_dir, "colors.json"))
    files.add(env.config_path("appglass", "settings.json"))
    staged = {}
    for p in sorted(files):
        if os.path.isfile(p):
            with open(p, "rb") as f:
                staged[p] = (f.read(), stat.S_IMODE(os.stat(p).st_mode))
    staged.update(candidate(app, owner) if owner else {})
    # what those files import by file:// URL (the AppGlass themes import
    # ~/.config/gtk-3.0/dank-colors.css): without it their colours are undefined
    rx = re.compile(r"file://(%s/[^\s\"')]+)" % re.escape(env.home))
    for data, _ in list(staged.values()):
        for m in rx.finditer(data.decode("utf-8", "replace")):
            p = m.group(1)
            if p not in staged and os.path.isfile(p):
                with open(p, "rb") as f:
                    staged[p] = (f.read(), 0o644)
    for p, (data, mode) in sorted(staged.items()):
        if not p.startswith(env.home + os.sep):
            continue
        dst = os.path.join(home, os.path.relpath(p, env.home))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            data = data.decode("utf-8").replace(env.home, home).encode("utf-8")
        except UnicodeDecodeError:
            pass
        with open(dst, "wb") as f:
            f.write(data)
        os.chmod(dst, mode if mode is not None else 0o644)
    return home


KDL = """screenshot-path "%(run)s/shot-%%s.png"
hotkey-overlay {
    skip-at-startup
}
prefer-no-csd
gestures {
    hot-corners {
        off
    }
}
animations {
    off
}
layout {
    gaps 0
    background-color "#000000"
    focus-ring {
        off
    }
    border {
        off
    }
}
"""


def harness_script():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "shims", "verify", "appglass-verify-run")


def private_base(env):
    """Where the private runtime dir goes: short (sun_path is 108 bytes)."""
    b = env.environ.get("APPGLASS_VERIFY_BASE") or env.environ.get("XDG_RUNTIME_DIR")
    if not b or not os.path.isdir(b):
        raise Busy("no runtime dir for the private session")
    return b


# what the hidden session keeps from the user's environment: the backend
# hints, so an app picks the same toolkit backend as in the real session
HINTS = ("ELECTRON_OZONE_PLATFORM_HINT", "FLATPAK_USER_DIR")


def session_env(env, home, run):
    """The environment of the hidden session: built from nothing (env -i), a
    throwaway HOME, the private runtime dir run/rt, caches in run."""
    e = {"HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config"),
         "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
         "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
         "XDG_CACHE_HOME": os.path.join(home, ".cache"),
         "PATH": env.environ.get("PATH", "/usr/bin:/bin"),
         "USER": env.environ.get("USER", ""), "LANG": env.environ.get("LANG", "C.UTF-8"),
         "TERM": "dumb", "XDG_RUNTIME_DIR": os.path.join(run, "rt"),
         "XDG_DATA_DIRS": env.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share"),
         "XDG_CONFIG_DIRS": "/etc/xdg", "GTK_USE_PORTAL": "0",
         # the hidden session is a niri Wayland session
         "XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "niri",
         "__GL_SHADER_DISK_CACHE_PATH": os.path.join(run, "glcache"),
         "MESA_SHADER_CACHE_DIR": os.path.join(run, "mesacache"),
         "AGV_REAL_NIRI": env.environ.get("NIRI_SOCKET", "")}
    for k in HINTS:
        if env.environ.get(k):
            e[k] = env.environ[k]
    return e


def new_run(base):
    """A private dir agv.* under base, with its runtime dir rt (0700)."""
    run = tempfile.mkdtemp(prefix="agv.", dir=base)
    os.chmod(run, 0o700)
    os.mkdir(os.path.join(run, "rt"), 0o700)
    return run


def kill_session(run, proc="/proc"):
    """SIGKILL every process of the hidden session: the ones whose
    XDG_RUNTIME_DIR is run/rt (the app's own setsid session and the
    dbus-run-session services escape a process-group kill). Returns how
    many were killed."""
    want = b"XDG_RUNTIME_DIR=" + os.path.join(run, "rt").encode()
    me, n = os.getpid(), 0
    for _ in range(3):
        hit = 0
        try:
            pids = [int(x) for x in os.listdir(proc) if x.isdigit()]
        except OSError:
            return n
        for pid in pids:
            if pid == me:
                continue
            try:
                with open(os.path.join(proc, str(pid), "environ"), "rb") as f:
                    if want not in f.read().split(b"\0"):
                        continue
                os.kill(pid, signal.SIGKILL)
                hit += 1
            except (OSError, ValueError):
                continue
        n += hit
        if not hit:
            break
        time.sleep(0.1)
    return n


def sweep(base, age=STALE_RUN):
    """Delete the agv.* dirs a killed run left under base (FUSE mounts out
    first, this file system only); a live run's dir is younger than age."""
    try:
        names = os.listdir(base)
    except OSError:
        return
    now = time.time()
    for n in names:
        d = os.path.join(base, n)
        try:
            st = os.lstat(d)
        except OSError:
            continue
        if (not n.startswith("agv.") or not stat.S_ISDIR(st.st_mode)
                or st.st_uid != os.getuid() or now - st.st_mtime < age):
            continue
        kill_session(d)
        _scrub(d)


def _term(signum, frame):
    raise SystemExit(128 + signum)


def install_term_handler():
    """SIGTERM unwinds (the finally blocks kill the session and scrub)."""
    signal.signal(signal.SIGTERM, _term)


def run_harness(app, rec, level):
    """{"result": pass|fail|unverifiable, "reason", "shot"}."""
    env = app.env
    stub = env.environ.get("APPGLASS_VERIFY_HARNESS")
    # builtin: the real hidden session, the sandbox HOME standing in for the
    # real one (an end-to-end proof); else a stub, or nothing in a sandbox
    if env.sandbox is not None and stub != "builtin":
        if not stub:
            return {"result": "unverifiable", "reason": "no harness in a sandbox"}
        r = env.run([stub, rec["key"], rec.get("fp") or "", "%.3f" % level], timeout=60)
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"result": "fail", "reason": "harness: %s" % (r.stderr or r.stdout).strip()}
        return out if isinstance(out, dict) else {"result": "fail", "reason": "harness"}
    for tool in ("gamescope", "niri", "dbus-run-session", "ffmpeg"):
        if not env.which(tool):
            return {"result": "unverifiable", "reason": "%s not installed" % tool}
    base = private_base(env)
    sweep(base)
    run = new_run(base)
    p = None
    try:
        rt = os.path.join(run, "rt")
        home = stage(app, rec, run)
        cmd = launcher_exec(app, rec, home)
        if not cmd:
            return {"result": "unverifiable", "reason": "no launcher to start"}
        with open(os.path.join(run, "cmd.sh"), "w") as f:
            f.write("#!/bin/sh\nexec %s\n" % cmd)
        with open(os.path.join(run, "niri.kdl"), "w") as f:
            f.write(KDL % {"run": run})
        real = env.environ.get("XDG_RUNTIME_DIR") or ""
        if os.path.realpath(rt) == os.path.realpath(real or "/nonexistent"):
            raise Busy("refusing: the private runtime dir is the real one")
        clean = session_env(env, home, run)
        for k in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
            os.makedirs(clean[k], exist_ok=True)
        shot = os.path.join(run, "window.png")
        p = subprocess.Popen(["dbus-run-session", "--", harness_script(), run, rec["app_ids"][0]
                              if rec.get("app_ids") else "^$", shot, str(WINDOW_WAIT)],
                             env=clean, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            log, _ = p.communicate(timeout=50)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
            return {"result": "unverifiable", "reason": "the session timed out"}
        log = log.decode("utf-8", "replace")
        if "window=none" in log or not os.path.isfile(shot):
            return {"result": "unverifiable",
                    "reason": "no window within %d s" % WINDOW_WAIT, "log": log[-400:]}
        res = judge(env, shot, level)
        keep = env.environ.get("APPGLASS_VERIFY_KEEP")
        if keep and os.path.isdir(keep):
            dst = os.path.join(keep, "%s-%s.png" % (rec["key"], rec.get("fp") or "x"))
            shutil.copyfile(shot, dst)
            res["shot"] = dst
        return res
    finally:
        if p is not None and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
        kill_session(run)
        _scrub(run)


def _scrub(run):
    """Unmount any FUSE left under the private dir, then delete it (on
    this file system only)."""
    try:
        with open("/proc/self/mounts") as f:
            mounts = [ln.split()[1] for ln in f if ln.split()[1].startswith(run + "/")]
    except OSError:
        mounts = []
    fm = shutil.which("fusermount3") or shutil.which("fusermount") or "fusermount3"
    for m in sorted(mounts, key=len, reverse=True):
        subprocess.run([fm, "-u", "-z", m], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    subprocess.run(["rm", "-rf", "--one-file-system", run], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def alpha_hist(env, png):
    """Counter of the alpha values of a PNG (ffmpeg decodes it)."""
    data = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", png, "-f", "rawvideo",
                                    "-pix_fmt", "rgba", "-"], timeout=30)
    return collections.Counter(data[3::4])


def judge(env, png, level, hist=None):
    """The window shot against the content level (spec 1.7 measure)."""
    hist = alpha_hist(env, png) if hist is None else hist
    want = int(round(level * 255))
    tol = int(round(TOL * 255))
    visible = sum(v for k, v in hist.items() if k)
    trans = {k: v for k, v in hist.items() if 0 < k < 255}
    mode = max(trans, key=trans.get) if trans else None
    near = sum(v for k, v in trans.items() if abs(k - want) <= tol)
    opaque = hist.get(255, 0)
    rep = {"alpha_mode": mode, "expected": want, "share": round(near / max(visible, 1), 3),
           "opaque_px": opaque}
    if mode is None:
        return dict(rep, result="fail", reason="the window is opaque (no glass)")
    if abs(mode - want) > tol:
        return dict(rep, result="fail", reason="background alpha %d, expected %d+-%d"
                    % (mode, want, tol))
    if near / max(visible, 1) < 0.25:
        return dict(rep, result="fail", reason="only %.0f%% of the window at the level"
                    % (100.0 * near / max(visible, 1)))
    if opaque < 12:
        return dict(rep, result="fail", reason="no opaque text on screen")
    return dict(rep, result="pass", reason="background %d (want %d), %d opaque text px"
                % (mode, want, opaque))


def verify_one(app, key):
    """Check one app. Returns the result dict (also recorded)."""
    rec = engine.record_for(app, key)
    if rec is None:
        return {"result": "unverifiable", "reason": "no launcher for %s" % key}
    route = route_of(app, rec)
    if route.get("state") == "excluded" or not route.get("family"):
        engine.store(app).dequeue(key)
        engine.store(app).save()
        return {"result": "skipped", "reason": route.get("reason")}
    res = run_harness(app, rec, app.levels.content)
    if res.get("result") in ("pass", "fail"):
        engine.verified(app, key, rec.get("fp"), res["result"], res.get("reason", ""))
    else:
        st = engine.store(app)
        st.app(key)["verify"] = {"fp": rec.get("fp"), "result": "unverifiable",
                                 "reason": res.get("reason", ""), "route": engine.ROUTE_VERSION,
                                 "at": time.strftime("%Y-%m-%d %H:%M")}
        st.dequeue(key)
        if route.get("injected") and engine.explicit_on(app, route.get("family"), key):
            # the user's own on stays on (S4): say the check could not run
            name = engine.app_name(app, key)
            engine.notify_once(app, key, rec.get("fp"), "%s: glass could not be checked" % name,
                               "%s keeps the glass you switched on, unchecked: %s"
                               % (name, res.get("reason", "?")), tag="unverifiable:")
        st.save()
    return res


def cmd_verify(app, key=None, queue=False):
    if app.dry_run:
        raise ValueError("verify has no dry run")
    g = game_running(app)
    if g:
        app.info("verify: a game window is open (%s): waiting, nothing checked" % g)
        return EX_TEMPFAIL
    if on_low_battery(app.env):
        app.info("verify: on battery under 20 %: waiting, nothing checked")
        return EX_TEMPFAIL
    install_term_handler()
    if queue:
        # the queue as a hook run sees it now (an app may have changed since)
        app.from_hook = True
        engine.refresh(app)
    keys = list(engine.store(app).data["queue"]) if queue else [key]
    if not keys:
        app.info("verify: nothing queued")
        return 0
    try:
        budget = float(app.env.environ.get("APPGLASS_VERIFY_BUDGET") or BUDGET)
    except ValueError:
        budget = BUDGET
    t0 = time.monotonic()
    for i, k in enumerate(keys):
        if i and time.monotonic() - t0 + min(APP_MAX, budget) > budget:
            app.info("verify: time budget used: %d left queued for the next run"
                     % (len(keys) - i))
            break
        res = verify_one(app, k)
        app.info("verify: %s: %s (%s)" % (k, res.get("result"), res.get("reason", "")))
        if res.get("result") in ("pass", "fail") and app.state.owners:
            # a PASS lets a route go live, a FAIL takes it out (S7): the
            # hook run brings either in now, not at the end of the queue
            from .core import cmd_apply
            app.from_hook = True
            app._engine_records = None
            cmd_apply(app, None, False, from_hook=True)
    return 0


# ---------------------------------------------------------------- launches

def _children(env, pid):
    from . import learn
    out = set()
    base = learn.proc_root(env)
    try:
        names = os.listdir(base)
    except OSError:
        return out
    parent = {}
    for n in names:
        if not n.isdigit():
            continue
        try:
            with open(os.path.join(base, n, "stat")) as f:
                parent[int(n)] = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
    todo = [pid]
    while todo:
        p = todo.pop()
        for c, pp in parent.items():
            if pp == p and c not in out:
                out.add(c)
                todo.append(c)
    return out


def _alive(env, pid):
    from . import learn
    return os.path.exists(os.path.join(learn.proc_root(env), str(pid)))


def _locked(app, fn):
    """Run one store write under the appglass lock (the poll ran without
    it). No state dir: nothing glass to record."""
    import fcntl
    d = app.env.state_dir
    if not os.path.isdir(d):
        return None
    app.env.guard(os.path.join(d, ".lock"))
    with open(os.path.join(d, ".lock"), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        app._engine_store = None        # re-read under the lock
        return fn()


def cmd_launch_check(app, key, pid):
    from . import learn
    env = app.env
    if env.sandbox is not None and not env.environ.get("APPGLASS_NIRI_WINDOWS"):
        return 0                    # nothing to watch in a sandbox
    wait = float(env.environ.get("APPGLASS_LAUNCH_WAIT") or LAUNCH_WAIT)
    step = float(env.environ.get("APPGLASS_LAUNCH_STEP") or 1)
    rec = engine.record_for(app, key)
    ids = (rec or {}).get("app_ids") or []
    t0 = time.monotonic()
    seen_alive = True
    while time.monotonic() - t0 <= wait:
        ws = learn.windows(env)
        if ws is None:
            return 0                # no niri: nothing to say
        kids = None
        for w in ws:
            if w["pid"] == pid or any(re.search(rx, w["app_id"]) for rx in ids):
                _locked(app, lambda: engine.ok(app, key))
                return 0
            if kids is None:
                kids = _children(env, pid)
            if w["pid"] in kids:
                _locked(app, lambda: engine.ok(app, key))
                return 0
        seen_alive = _alive(env, pid)
        if not seen_alive:
            break
        time.sleep(step)
    if seen_alive:
        return 0                    # still running, no window yet: not a failure
    res = _locked(app, lambda: engine.fail(app, key, "the app exited with no window"))
    if res is None:
        return 0
    n, paused = res
    app.info("launch-check: %s: failed launch %d%s" % (key, n, ", glass paused" if paused else ""))
    return 0


def cmd_fail(app, key, reason=None):
    n, paused = engine.fail(app, key, reason or "failed launch (appglass fail)")
    app.info("%s: failed launch %d on this version%s" % (
        key, n, ": glass paused until the next update" if paused else ""))
    if paused and app.state.owners:
        # a theme route has no wrapper to read the marker: the hook run
        # takes it out of the launcher (S7)
        from .core import cmd_apply
        app._engine_records = None
        cmd_apply(app, None, False, from_hook=True)
    return 0


# ---------------------------------------------------------------- colour keys

def keys_dir(env):
    return os.path.join(env.cache_home, "appglass", "keys")


def keys_file(env, key, fp, mode):
    return os.path.join(keys_dir(env), key, fp or "none", "%s.json" % mode)


def family_defaults(app, key):
    for fam in app.families.values():
        if key in (getattr(fam, "KEYS", ()) or ()) and getattr(fam, "KEY_DEFAULTS", None):
            return fam.KEY_DEFAULTS
    return None


def cmd_keys(app, key, mode, out):
    env = app.env
    if mode not in ("dark", "light") or "/" in key or key.startswith("."):
        return 1
    rec = engine.record_for(app, key)
    fp = (rec or {}).get("fp")
    p = keys_file(env, key, fp, mode)
    data = None
    try:
        with open(p, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        data = None
    if data is None:
        d = family_defaults(app, key)
        if not d or mode not in d:
            return 1
        data = {"keys": [list(k) for k in d[mode]], "source": "family defaults"}
        try:
            engine._write(env, p, data)
        except Exception:
            pass                    # a launch never fails on the cache
    lv = app.levels.as_dict()
    parts = []
    for k in data.get("keys") or ():
        try:
            hx, role = k[0], k[1]
        except (TypeError, IndexError):
            return 1
        if not re.match(r"^[0-9a-fA-F]{6}$", str(hx)) or role not in lv:
            return 1
        parts.append("%s:%s" % (hx.lower(), lv[role]))
    if not parts:
        return 1
    print(",".join(parts), file=out)
    return 0
