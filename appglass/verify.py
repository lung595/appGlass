"""appglass verify / launch-check / fail / keys: the engine's checks.

verify <key> | --queue
    The pixel check (spec 1.7) in a hidden headless session, fully apart
    from the real one: a short private XDG_RUNTIME_DIR (made with mktemp in
    $XDG_RUNTIME_DIR, or $APPGLASS_VERIFY_BASE), env -i with an allow-list,
    a bwrap mount namespace without the systemd user manager (a flatpak
    stays in the check's cgroup; none: a flatpak is unverifiable),
    dbus-run-session, a throwaway HOME holding a copy of the app's glass
    files, gamescope --backend headless --expose-wayland and a nested niri
    with animations off (shims/verify/appglass-verify-run). The app starts
    from its glass launcher; its window is the one of the started pid or a
    child (shims/verify/agv-pick.py), else one whose app-id matches a name
    of its launcher, and the app-id seen is kept (engine.seen_ids). The
    shot (niri screenshot-window, premultiplied alpha) must show the
    background within 0.05 of the content level and opaque text, with no
    more than a quarter of it and no hole inside it at alpha 0. PASS
    lets an injected route go live for this app version (fingerprint);
    FAIL makes it run plain with one notification. A window that does not
    show within 10 s is "unverifiable": an injected route stays off, a
    theme route stays on.
    Not run while a game window is open (exit 75: try later), nor on a
    battery under 20 %. In a sandbox only the stand-in named by
    $APPGLASS_VERIFY_HARNESS runs (it prints the result as JSON).
    A run checks what fits BUDGET seconds ($APPGLASS_VERIFY_BUDGET), runs
    the hook apply after each result and leaves the rest queued for the next
    event (the unit's TimeoutSec is above BUDGET + 2 * APP_MAX). SIGTERM
    (systemd stopping the unit, KillMode=mixed: verify alone gets it) still
    SIGKILLs the hidden session and deletes its private dir; a dir left by a killed run is swept at the next start.

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
# a window more than this share bare (alpha 0: the blur with no colour at
# all) has holes, not glass: native chrome around one glassed WebView. The
# rounded corners and CSD margins of a normal window stay under 0.10.
BARE = 0.25
# ... and a window with one bare region inside it, away from those margins,
# has a hole even when the rest is glass: a native sidebar shown after a
# glassed WebView mapped, its labels on the bare blur. A hole is a region of
# alpha 0 at least HOLE_EDGE px in from the window's edge that holds a solid
# square of HOLE_CORE blocks of HOLE_BLOCK px (40 x 40) and covers more than
# HOLE of the window. CSD shadow margins (20 px at scale 1, 40 at scale 2),
# rounded corners and the thin gaps between widgets never hold that square.
# The price: a clear strip along an edge less than HOLE_EDGE + 40 px deep
# (a transparent custom header) is not a hole; only BARE catches it.
HOLE = 0.01
HOLE_EDGE = 16
HOLE_BLOCK = 8
HOLE_CORE = 5
NO_MASK = ("no bwrap mount namespace: a flatpak would leave the check's limits "
           "(systemd scope)")


class Busy(Exception):
    pass


# ---------------------------------------------------------------- guards

# a game with no window yet, or one niri names by no game id (comm is 15
# characters at most: pressure-vessel-wrap reads pressure-vessel-); a
# Windows program under wine names itself after its .exe
GAME_PROCS = re.compile(r"^(wine|wine64|wineserver|wine-preloader|wine64-preload\w*|proton"
                        r"|umu-run|reaper|pressure-vessel\S*|\S+\.exe)$", re.I)


def game_process(env):
    """The name of a running wine, proton, umu or Steam runtime process, or None."""
    from . import learn
    root = learn.proc_root(env)
    try:
        pids = [n for n in os.listdir(root) if n.isdigit()]
    except OSError:
        return None
    for pid in pids:
        try:
            with open(os.path.join(root, pid, "comm")) as f:
                comm = f.read().strip()
        except OSError:
            continue
        if GAME_PROCS.match(comm):
            return comm
    return None


def game_running(app):
    """What says a game runs (a window's app-id, a process name), or None.
    No answer from niri counts as a game: a check never starts blind."""
    from . import learn, niri
    p = game_process(app.env)
    if p:
        return "a game process runs (%s)" % p
    ws = learn.windows(app.env)
    if ws is None:
        return "niri did not answer, so a game may be open"
    games = list(niri.GAME_IDS)
    st = engine.store(app)
    for r in engine.records(app):
        if r["key"] in st.data["games"] or r.get("toolkit") == "game":
            games += r.get("app_ids") or []
    for w in ws:
        if any(re.search(rx, w["app_id"]) for rx in games):
            return "a game window is open (%s)" % w["app_id"]
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
    # the staged launcher (a family waiting for its first check has none on
    # disk), else the one on disk, else the app's own
    p = (staged_path(app.env, home, os.path.join(app.env.data_home, "applications", did))
         if did else None) or ""
    if not os.path.isfile(p):
        p = os.path.join(app.env.data_home, "applications", did)
    if not did or not os.path.isfile(p):
        p = rec.get("path")
    if not p or not os.path.isfile(p):
        return None
    ex = detect.parse_desktop(p).get("Exec") or ""
    ex = re.sub(r"\s%[fFuUdDnNickvm]\b", "", ex).replace("@@u", "").replace("@@", "")
    words = ex.split(" ")
    out = [w.replace(app.env.home, home) for w in words]
    # the program (after env and its VAR=value words): one installed under
    # the real HOME (~/.local/bin/herdr-app) is not copied to the throwaway
    # one, and the mask keeps / as it is: it runs from where it is
    i = 0
    while i < len(words) and (words[i] in ("", "env") or "=" in words[i]):
        i += 1
    if i < len(words) and out[i] != words[i] and not os.path.exists(out[i]) \
            and os.path.isfile(words[i]):
        out[i] = words[i]
    return " ".join(out)


def candidate(app, owner, key=None):
    """{path: (bytes, mode)}: the files the family would write now (its
    plan, never committed), with the app key under check routed as if it
    passed (the others as the engine has them). A family waiting for its
    first check has none on disk yet; a stale one may plan new ones for the
    update."""
    fam = app.families.get(owner)
    if fam is None:
        return {}
    ctx = app.ctx(owner)
    ctx.candidate = key
    try:
        fam.apply(ctx)
    except Exception:
        return {}
    return {p: (op.data, op.mode) for p, op in ctx.ops.items()
            if op.kind != "retire" and isinstance(op.data, bytes)}


class Unstageable(Exception):
    """The glass files cannot be put in the throwaway HOME."""


def staged_path(env, home, p):
    """Where a file of the user's goes in the throwaway home (the hidden
    session's XDG dirs are the defaults under it, wherever the user's are),
    or None for a file outside HOME and the XDG dirs."""
    for real, rel in ((env.config_home, ".config"), (env.data_home, ".local/share"),
                      (env.state_home, ".local/state"), (env.cache_home, ".cache"),
                      (env.home, "")):
        if p.startswith(real + os.sep):
            return os.path.join(home, rel, os.path.relpath(p, real))
    return None


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
    staged.update(candidate(app, owner, rec.get("key")) if owner else {})
    # what the family says the app needs to open on its glass window
    # (Obsidian: its vault list), {real path: bytes}
    hook = getattr(app.families.get(owner or ""), "verify_stage", None)
    if hook:
        staged.update({p: (data, 0o644) for p, data in (hook(env) or {}).items()})
    # the level sources (core.Levels.from_env): the shims and the launchers
    # read the level at run time, so without them the hidden app runs at the
    # 0.60 default while the judge wants the user's level. The window rule
    # goes as it is; of the DMS settings only the one key the level reads
    rules = env.config_path("niri", "dms", "windowrules.kdl")
    if os.path.isfile(rules):
        with open(rules, "rb") as f:
            staged[rules] = (f.read(), 0o644)
    from . import core
    dms = core._load_json(env.config_path("dms", "settings.json"))
    if isinstance(dms, dict) and isinstance(dms.get("foregroundLayerTransparency"), (int, float)):
        staged[env.config_path("dms", "settings.json")] = (json.dumps(
            {"foregroundLayerTransparency": dms["foregroundLayerTransparency"]}).encode(), 0o644)
    # what those files import by file:// URL (the AppGlass themes import
    # ~/.config/gtk-3.0/dank-colors.css): without it their colours are undefined
    rx = re.compile(r"file://(%s/[^\s\"')]+)" % re.escape(env.home))
    for data, _ in list(staged.values()):
        for m in rx.finditer(data.decode("utf-8", "replace")):
            p = m.group(1)
            if p not in staged and os.path.isfile(p):
                with open(p, "rb") as f:
                    staged[p] = (f.read(), 0o644)
    # state.json: without it the staged appglass files look like a lost
    # state and `appglass keys` refuses (the wrapper then starts the plain
    # app); the colour keys of this app version (learned ones included)
    sp = os.path.join(env.state_dir, "state.json")
    if os.path.isfile(sp):
        with open(sp, "rb") as f:
            staged[sp] = (f.read(), 0o644)
    kd = os.path.dirname(keys_file(env, rec.get("key") or "", rec.get("fp"), "dark"))
    if rec.get("key") and "/" not in rec["key"] and os.path.isdir(kd):
        for n in sorted(os.listdir(kd)):
            if n.endswith(".json") and os.path.isfile(os.path.join(kd, n)):
                with open(os.path.join(kd, n), "rb") as f:
                    staged[os.path.join(kd, n)] = (f.read(), 0o644)
    # the throwaway HOME holds what is under $HOME and the XDG dirs (moved
    # under it): a file outside both would leave the check with the plain app
    out = sorted(p for p in staged if staged_path(env, home, p) is None)
    if out:
        raise Unstageable("the glass files are outside HOME and the XDG dirs (%s): "
                          "the check cannot stage them" % os.path.dirname(out[0]))
    for p, (data, mode) in sorted(staged.items()):
        dst = staged_path(env, home, p)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            data = _rehome(env, home, data.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            pass
        with open(dst, "wb") as f:
            f.write(data)
        os.chmod(dst, mode if mode is not None else 0o644)
    return home


def seed_scheme(app, home):
    """The user's colour scheme (the DMS mode the glass keys are made for)
    in the throwaway HOME: a GSettings keyfile (session_env picks the
    keyfile backend), read by the apps and by the settings portal the
    private bus starts. Without it the portal says "no preference" and the
    apps draw light over keys made for dark (an opaque window)."""
    scheme = "prefer-light" if app.palette.mode == "light" else "prefer-dark"
    p = os.path.join(home, ".config", "glib-2.0", "settings", "keyfile")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("[org/gnome/desktop/interface]\ncolor-scheme='%s'\n" % scheme)
    return scheme


def staged_level(home):
    """The content level the hidden session reads in the throwaway HOME."""
    from . import core, settings as _s
    e = core.Env({"HOME": home})
    return core.Levels.from_env(e, _s.load(e)[0]).content


def seed(app, rec, home):
    """The app's own first-run state in the throwaway home (its family's
    verify_seed: {path under HOME: bytes}), so no first-run dialog covers
    the window the check shoots. A dict instead of bytes is merged into
    the JSON object staged there (Herdr's shared.json holds glass keys). A
    generic family's hook takes the record too (verify_seed(env, rec)): it
    seeds the apps it knows, the others start as they are. Returns why it
    cannot be seeded, or None."""
    fam = app.families.get(route_of(app, rec).get("family") or "")
    fn = getattr(fam, "verify_seed", None)
    if fn is None:
        return None
    if getattr(fam, "GENERIC", False):
        files = fn(app.env, rec) or {}
    else:
        files = fn(app.env)
        if not files:
            return "cannot seed the first run of %s (its version is not known)" % fam.NAME
    for rel, data in files.items():
        dst = os.path.join(home, rel)
        os.makedirs(os.path.dirname(dst), mode=0o700, exist_ok=True)
        if isinstance(data, dict):
            try:
                with open(dst, "rb") as f:
                    cur = json.loads(f.read().decode("utf-8"))
            except (OSError, ValueError):
                cur = None
            data = (json.dumps(dict(cur if isinstance(cur, dict) else {}, **data),
                               indent=1) + "\n").encode("utf-8")
        with open(dst, "wb") as f:
            f.write(data)
    return None


def _rehome(env, home, text):
    """A staged text file with the real $HOME (and an XDG dir out of it)
    rewritten to the throwaway one, except the appglass repo: a wrapper calls bin/appglass as
    "$HOME/<repo>" when the repo is under HOME, and the throwaway HOME holds
    no repo (every check would start the plain app and fail)."""
    from . import shims
    hold = "\0appglass-repo\0"
    repo = shims.REPO
    text = text.replace(repo, hold)
    if repo.startswith(env.home + os.sep):
        text = text.replace("$HOME" + repo[len(env.home):], hold)
    for real, rel in ((env.config_home, ".config"), (env.data_home, ".local/share"),
                      (env.state_home, ".local/state"), (env.cache_home, ".cache")):
        if not real.startswith(env.home + os.sep):          # an XDG dir out of HOME
            text = text.replace(real, os.path.join(home, rel))
    return text.replace(env.home, home).replace(hold, repo)


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
xwayland-satellite {
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


def session_env(env, home, run, fp=None):
    """The environment of the hidden session: built from nothing (env -i), a
    throwaway HOME, the private runtime dir run/rt, caches in run. fp: the
    app version checked (the throwaway launcher has another fingerprint;
    `appglass keys` reads the keys of this one)."""
    e = {"HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config"),
         "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
         "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
         "XDG_CACHE_HOME": os.path.join(home, ".cache"),
         "PATH": env.environ.get("PATH", "/usr/bin:/bin"),
         "USER": env.environ.get("USER", ""), "LANG": env.environ.get("LANG", "C.UTF-8"),
         "TERM": "dumb", "XDG_RUNTIME_DIR": os.path.join(run, "rt"),
         # the app's temp files and its path sockets stay in the private dir
         # (abstract sockets and the network are shared, unless the family
         # asks mask_argv for its own network namespace, docs/engine.md)
         "TMPDIR": os.path.join(run, "tmp"),
         "XDG_DATA_DIRS": env.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share"),
         "XDG_CONFIG_DIRS": "/etc/xdg", "GTK_USE_PORTAL": "0",
         # GSettings from a keyfile in the throwaway HOME (seed_scheme), not dconf
         "GSETTINGS_BACKEND": "keyfile",
         # no gvfsd (its wsdd and smb backends reach the LAN)
         "GIO_USE_VFS": "local",
         # the hidden session is a niri Wayland session
         "XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "niri",
         "__GL_SHADER_DISK_CACHE_PATH": os.path.join(run, "glcache"),
         "MESA_SHADER_CACHE_DIR": os.path.join(run, "mesacache"),
         "AGV_REAL_NIRI": env.environ.get("NIRI_SOCKET", "")}
    for k in HINTS:
        if env.environ.get(k):
            e[k] = env.environ[k]
    if fp:
        e["APPGLASS_VERIFY_FP"] = fp
    return e


_MASK = {}


def mask_argv(env, hide=(), nonet=False):
    """The bwrap argv (ending in --) the hidden session runs under: its own
    mount namespace with the systemd user manager's dir empty (flatpak run
    reaches the manager by the hard-coded /run/user/UID/systemd/private and
    would put the app in an app-flatpak-*.scope, out of the check's cgroup
    and its limits; without it flatpak runs the app in its own process
    tree) and an empty /tmp/.X11-unix (the hidden X server's socket is not
    next to the user's). hide: more paths out of reach (a family's
    verify_mask: a dir becomes an empty tmpfs, a file /dev/null); nonet: its
    own network namespace (no network, no abstract socket of the session).
    None when bwrap cannot do it here (not installed, no user namespaces):
    proven once per bwrap and mask with a probe."""
    bw = env.which("bwrap")
    if not bw:
        return None
    hide = tuple(hide)
    k = (bw, hide, bool(nonet))
    if k not in _MASK:
        sd = "/run/user/%d/systemd" % os.getuid()
        argv = [bw, "--dev-bind", "/", "/", "--die-with-parent"]
        if nonet:
            argv.append("--unshare-net")
        if os.path.isdir(sd):
            argv += ["--tmpfs", sd]
        if os.path.isdir("/tmp/.X11-unix"):
            argv += ["--perms", "1777", "--tmpfs", "/tmp/.X11-unix"]
        probe = ['test ! -e "$1/private"']
        args = [sd]
        for p in hide:
            if os.path.isdir(p):
                argv += ["--tmpfs", p]
                probe.append('test -z "$(ls -A "$%d")"' % (len(args) + 1))
            else:
                argv += ["--ro-bind", "/dev/null", p]
                probe.append('test -c "$%d"' % (len(args) + 1))
            args.append(p)
        if nonet:   # no network: no device but lo, and no name resolves (resolved's varlink
            # socket under /run/systemd answers DNS from out of the namespace)
            probe.append('test "$(grep -c : /proc/net/dev)" = 1')
            probe.append('{ ! command -v getent >/dev/null || ! getent hosts example.com; }')
        argv.append("--")
        try:
            r = subprocess.run(argv + ["/bin/sh", "-c", " && ".join(probe), "sh"] + args,
                               env={"PATH": "/usr/bin:/bin"}, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=20)
            ok = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        _MASK[k] = argv if ok else None
    return _MASK[k]


# what the hidden session never masks under /run: the private runtime dir
# is under /run/user, the bus and systemd's sockets serve the session itself
RUN_KEEP = frozenset(("user", "dbus", "systemd"))


def run_paths(rec, keys=(), run="/run"):
    """The entries under /run a host app reaches by a path its binaries
    name (a daemon's socket, a container engine's), and /run/<key> for each
    key: those that exist, as the mask hides them (a link resolved, a
    socket in a dir of its own gives the dir). [] for a flatpak (its
    sandbox has its own /run)."""
    if rec.get("flatpak"):
        return []
    rx = re.compile(re.escape(run.encode()) + rb"/([A-Za-z0-9][A-Za-z0-9._-]*)")
    names = set(keys)
    for b in [rec.get("exec")] + list(rec.get("seen") or ()):
        if not b:
            continue
        try:
            with open(b, "rb") as f:
                names.update(m.decode("ascii") for m in rx.findall(f.read()))
        except OSError:
            continue
    out = set()
    for n in names:
        p = os.path.join(run, n)
        if n in RUN_KEEP or not os.path.lexists(p):
            continue
        real = os.path.realpath(p)
        rel = os.path.relpath(real, os.path.realpath(run)).split(os.sep)
        if rel[0] in (os.pardir, ".") or rel[0] in RUN_KEEP:
            continue
        out.add(os.path.join(run, rel[0]))
    return sorted(out)


# the system manager's doors: the system bus (systemctl as a user, polkit)
# and all of /run/systemd (its private socket, its varlink sockets, and
# resolved's io.systemd.Resolve, which answers DNS from out of a network
# namespace). A WebKitGTK family hides them (Lian Li's GUI starts a root
# unit, lianli-control-recovery, over the system bus).
SYSTEM_SOCKETS = ("dbus/system_bus_socket", "systemd")


def system_paths(run="/run"):
    """The SYSTEM_SOCKETS under run that exist, for a verify_mask hide (the
    systemd dir becomes an empty tmpfs)."""
    return [os.path.join(run, p) for p in SYSTEM_SOCKETS if os.path.lexists(os.path.join(run, p))]


def session_paths(rt=None, prefix=None):
    """The real session's bus socket ($XDG_RUNTIME_DIR/bus: the check runs
    its own bus) and, with prefix, the files in $XDG_RUNTIME_DIR whose name
    starts with it (Lian Li's session locks), for a verify_mask hide."""
    rt = os.environ.get("XDG_RUNTIME_DIR") if rt is None else rt
    if not rt or not os.path.isdir(rt):
        return []
    out = [os.path.join(rt, "bus")] if os.path.lexists(os.path.join(rt, "bus")) else []
    if prefix:
        try:
            names = sorted(os.listdir(rt))
        except OSError:
            names = []
        out += [os.path.join(rt, n) for n in names
                if n.startswith(prefix) and not os.path.isdir(os.path.join(rt, n))]
    return out


# resolved's varlink sockets: they answer DNS from out of a network namespace
RESOLVE = "/run/systemd/resolve"


def verify_mask(app, rec):
    """The app's family's verify_mask(rec) over the base mask: {"hide":
    [paths], "nonet": bool}. Every check hides the system manager (the
    system bus and /run/systemd: an app with a fresh HOME starts root
    services over them, dnf5daemon, geoclue, localed) and the real session
    bus socket (the check runs its own bus); an app that cannot show a
    window without them is unverifiable. Every check runs with no network
    (an app with a fresh HOME would announce itself on the LAN, or sync); a
    family that truly needs it says "nonet": False. With no network,
    resolved's dir is hidden too (unless a dir above it is)."""
    fam = app.families.get(route_of(app, rec).get("family") or "")
    fn = getattr(fam, "verify_mask", None)
    m = (fn(rec) if fn else None) or {}
    hide = []
    for h in system_paths() + session_paths() + list(m.get("hide") or ()):
        if h not in hide:
            hide.append(h)
    nonet = m.get("nonet", True) is not False
    if nonet and os.path.isdir(RESOLVE) and \
            not any(RESOLVE == h or RESOLVE.startswith(h.rstrip(os.sep) + os.sep) for h in hide):
        hide.append(RESOLVE)
    return {"hide": hide, "nonet": nonet}


def verify_alphas(app, rec, level):
    """The family's verify_alphas(env, rec, level): the alphas its own design
    draws over the window fill at that level (Dux Calendar's panes), or ()."""
    fam = app.families.get(route_of(app, rec).get("family") or "")
    fn = getattr(fam, "verify_alphas", None)
    return tuple(fn(app.env, rec, level) or ()) if fn else ()


def is_flatpak(rec, cmd=""):
    words = (cmd or "").split()
    return bool(rec.get("flatpak")) or (bool(words) and os.path.basename(words[0]) == "flatpak")


def window_rx(rec):
    """One regex for the app's window: its app-id regexes and every name of
    its launcher (StartupWMClass, flatpak id, desktop id, binary)."""
    from . import detect
    rxs = list(rec.get("app_ids") or ())
    for n in rec.get("names") or ():
        r = detect._rx(n)
        if r not in rxs:
            rxs.append(r)
    return "|".join(rxs) or "^$"


def parse_window(log):
    """(window id, app-id) from the harness output, or (None, None)."""
    m = re.search(r"(?m)^window=(\d+)(?: app_id=(\S*))?", log)
    if not m:
        return None, None
    return m.group(1), m.group(2) or None


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
    # a family the hidden session cannot run faithfully says why up front
    skip = getattr(app.families.get(route_of(app, rec).get("family") or ""), "verify_skip", None)
    why = skip(env, rec) if skip else None
    if why:
        return {"result": "unverifiable", "reason": why}
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
    want = verify_mask(app, rec)
    mask = mask_argv(env, want["hide"], want["nonet"])
    if mask is None and (want["hide"] or want["nonet"]):
        return {"result": "unverifiable",
                "reason": "no bwrap mount namespace: the app would reach %s"
                          % ", ".join(want["hide"] + (["the network"] if want["nonet"] else []))}
    if mask is None and is_flatpak(rec):
        return {"result": "unverifiable", "reason": NO_MASK}
    base = private_base(env)
    sweep(base)
    run = new_run(base)
    p = None
    try:
        rt = os.path.join(run, "rt")
        try:
            home = stage(app, rec, run)
        except Unstageable as e:
            return {"result": "unverifiable", "reason": str(e)}
        lv = staged_level(home)
        if abs(lv - level) > 0.005:
            return {"result": "unverifiable",
                    "reason": "the hidden session would run at level %.2f, not %.2f"
                              % (lv, level)}
        seed_scheme(app, home)
        why = seed(app, rec, home)
        if why:
            return {"result": "unverifiable", "reason": why}
        cmd = launcher_exec(app, rec, home)
        if not cmd:
            return {"result": "unverifiable", "reason": "no launcher to start"}
        if mask is None and is_flatpak(rec, cmd):
            return {"result": "unverifiable", "reason": NO_MASK}
        with open(os.path.join(run, "cmd.sh"), "w") as f:
            f.write("#!/bin/sh\nexec %s\n" % cmd)
        with open(os.path.join(run, "niri.kdl"), "w") as f:
            f.write(KDL % {"run": run})
        real = env.environ.get("XDG_RUNTIME_DIR") or ""
        if os.path.realpath(rt) == os.path.realpath(real or "/nonexistent"):
            raise Busy("refusing: the private runtime dir is the real one")
        clean = session_env(env, home, run, fp=rec.get("fp"))
        for k in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
                  "TMPDIR"):
            os.makedirs(clean[k], exist_ok=True)
        shot = os.path.join(run, "window.png")
        p = subprocess.Popen((mask or []) + ["dbus-run-session", "--", harness_script(), run,
                                             window_rx(rec), shot, str(WINDOW_WAIT)],
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
        res = judge(env, shot, level, panes=verify_alphas(app, rec, level))
        seen = parse_window(log)[1]
        if seen:
            res["app_id"] = seen
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
    # an app can leave read-only dirs (Dux unpacks its QML 0555 into the
    # runtime dir): rm cannot empty them. Make every dir of the tree ours
    # writable first (no link followed, this file system only)
    try:
        dev = os.lstat(run).st_dev
    except OSError:
        dev = None
    for dp, dns, _ in os.walk(run):
        for n in list(dns):
            q = os.path.join(dp, n)
            try:
                st = os.lstat(q)
                if st.st_dev != dev or not stat.S_ISDIR(st.st_mode):
                    dns.remove(n)
                elif st.st_mode & 0o700 != 0o700:
                    os.chmod(q, 0o700)
            except OSError:
                dns.remove(n)
    subprocess.run(["rm", "-rf", "--one-file-system", run], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def alpha_plane(env, png):
    """(width, height, alpha bytes) of a PNG (ffmpeg decodes it, as PAM)."""
    data = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", png, "-frames:v", "1",
                                    "-f", "image2pipe", "-c:v", "pam", "-pix_fmt", "rgba", "-"],
                                   timeout=30)
    end = data.index(b"ENDHDR\n")
    head = dict(ln.split(" ", 1) for ln in data[:end].decode("ascii").splitlines()[1:]
                if " " in ln)
    return int(head["WIDTH"]), int(head["HEIGHT"]), data[end + 7:][3::4]


def hole_share(w, h, alpha):
    """The share of the window in its largest hole (HOLE_*), 0 without one."""
    b, m = HOLE_BLOCK, HOLE_EDGE
    bw, bh = (w - 2 * m) // b, (h - 2 * m) // b
    if bw < HOLE_CORE or bh < HOLE_CORE:
        return 0
    zero = bytes(b)
    bare = []                       # blocks all at alpha 0
    for by in range(bh):
        row = [True] * bw
        for dy in range(b):
            o = (m + by * b + dy) * w + m
            line = alpha[o:o + bw * b]
            for bx in range(bw):
                if row[bx] and line[bx * b:bx * b + b] != zero:
                    row[bx] = False
        bare.append(row)
    k, r = HOLE_CORE, HOLE_CORE // 2
    across = [[False] * bw for _ in range(bh)]   # the middle of k bare blocks in a row
    for y in range(bh):
        n = 0
        for x in range(bw):
            n = n + 1 if bare[y][x] else 0
            if n >= k:
                across[y][x - r] = True
    core = [[False] * bw for _ in range(bh)]     # ... and of k such in a column
    for x in range(bw):
        n = 0
        for y in range(bh):
            n = n + 1 if across[y][x] else 0
            if n >= k:
                core[y - r][x] = True
    seen = [[False] * bw for _ in range(bh)]
    best = 0
    for sy in range(bh):
        for sx in range(bw):
            if not core[sy][sx] or seen[sy][sx]:
                continue
            seen[sy][sx] = True
            todo, n = [(sy, sx)], 0
            while todo:
                y, x = todo.pop()
                n += 1
                for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= yy < bh and 0 <= xx < bw and bare[yy][xx] and not seen[yy][xx]:
                        seen[yy][xx] = True
                        todo.append((yy, xx))
            best = max(best, n)
    return best * b * b / float(w * h)


def judge(env, png, level, hist=None, plane=None, panes=()):
    """The window shot against the content level (spec 1.7 measure). The
    holes are looked for when the whole plane is known (a shot, or plane:
    (width, height, alpha bytes)), not from a histogram alone. panes: the
    alphas the family's own design draws over the window fill (verify_alphas),
    taken as well as the level."""
    if hist is None:
        plane = alpha_plane(env, png) if plane is None else plane
        hist = collections.Counter(plane[2])
    want = int(round(level * 255))
    tol = int(round(TOL * 255))
    wants = [want] + [int(round(a * 255)) for a in panes]
    visible = sum(v for k, v in hist.items() if k)
    trans = {k: v for k, v in hist.items() if 0 < k < 255}
    mode = max(trans, key=trans.get) if trans else None
    near = sum(v for k, v in trans.items() if any(abs(k - w) <= tol for w in wants))
    opaque = hist.get(255, 0)
    bare = hist.get(0, 0) / max(sum(hist.values()), 1)
    rep = {"alpha_mode": mode, "expected": want, "share": round(near / max(visible, 1), 3),
           "opaque_px": opaque, "bare": round(bare, 3)}
    if plane is not None:
        rep["hole"] = round(hole_share(*plane), 3)
    if mode is None:
        return dict(rep, result="fail", reason="the window is opaque (no glass)")
    if bare > BARE:
        return dict(rep, result="fail", reason="%.0f%% of the window at alpha 0 (holes, not glass)"
                    % (100.0 * bare))
    if rep.get("hole", 0) > HOLE:
        return dict(rep, result="fail", reason="a hole of %.0f%% of the window at alpha 0 "
                    "(native widgets on the bare blur)" % (100.0 * rep["hole"]))
    if all(abs(mode - w) > tol for w in wants):
        return dict(rep, result="fail", reason="background alpha %d, expected %d+-%d"
                    % (mode, want, tol))
    if near / max(visible, 1) < 0.25:
        return dict(rep, result="fail", reason="only %.0f%% of the window at the level"
                    % (100.0 * near / max(visible, 1)))
    if opaque < 12:
        return dict(rep, result="fail", reason="no opaque text on screen")
    return dict(rep, result="pass", reason="background %d (want %s), %d opaque text px"
                % (mode, " or ".join(str(w) for w in wants), opaque))


def with_lock(app, fn):
    """fn(a) under the appglass lock, a being an App that read the state
    under it: verify runs its hidden sessions without the lock (a queue run
    can last BUDGET) and takes it only to record a result and apply it, on
    the state as it is then (an apply or set made meanwhile is kept)."""
    from . import core
    lockf, created = core._lock(app.env)
    a = None
    try:
        a = core.App(app.env.environ, out=app.out, err=app.err, quiet=app.quiet)
        a.event = True
        core.refuse_orphans(a)
        r = fn(a)
    except BaseException:
        core._unlock(app.env, lockf, created, a, failed=True)
        if a is not None:
            app.errors += a.errors
        raise
    core._unlock(app.env, lockf, created, a)
    app.errors += a.errors
    return r


def verify_lock(env):
    """One verify at a time (the hidden sessions are heavy): an open file
    holding the lock, or None when another verify runs."""
    import fcntl
    d = env.state_dir
    if not os.path.isdir(d):
        return open(os.devnull)         # nothing applied: nothing to race on
    p = os.path.join(d, "verify.lock")
    env.guard(p)
    f = open(p, "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def record(a, key, rec, route, res):
    """Record one result (under the lock, a: the App that read the state
    under it); a PASS or FAIL runs the hook apply."""
    if res.get("result") in ("pass", "fail"):
        seen = res.get("app_id")
        engine.verified(a, key, rec.get("fp"), res["result"], res.get("reason", ""),
                        app_id=seen if isinstance(seen, str) and seen else None,
                        injected=bool(route.get("injected")))
    else:
        st = engine.store(a)
        prev = st.get(key).get("verify") or {}
        if prev.get("fp") == rec.get("fp") and prev.get("result") in ("pass", "fail"):
            # unverifiable is never a fail (engine.md): a check that could
            # not judge (a timeout, no window) keeps the verdict stored for
            # this fingerprint and changes nothing else
            st.dequeue(key)
            st.save()
            res["kept"] = prev["result"]
            return res
        seen = prev.get("app_id")
        st.app(key)["verify"] = {"fp": rec.get("fp"), "result": "unverifiable",
                                 "reason": res.get("reason", ""), "route": engine.ROUTE_VERSION,
                                 "at": time.strftime("%Y-%m-%d %H:%M")}
        if seen:
            st.app(key)["verify"]["app_id"] = seen
        st.dequeue(key)
        if route.get("injected") and engine.explicit_on(a, route.get("family"), key):
            # the user's own on stays on (S4): say the check could not run
            name = engine.app_name(a, key)
            engine.notify_once(a, key, rec.get("fp"), "%s: glass could not be checked" % name,
                               "%s keeps the glass you switched on, unchecked: %s"
                               % (name, res.get("reason", "?")), tag="unverifiable:")
        st.save()
    if res.get("result") in ("pass", "fail") and a.state.owners:
        # a PASS lets a route go live, a FAIL takes it out (S7): the
        # hook run brings either in now, not at the end of the queue
        from .core import cmd_apply
        a.from_hook = True
        a._engine_records = None
        cmd_apply(a, None, False, from_hook=True)
    return res


def verify_one(app, key):
    """Check one app. Returns the result dict (also recorded)."""
    rec = engine.record_for(app, key)
    if rec is None:
        return {"result": "unverifiable",
                "reason": "no launcher for %s (verify takes an app key or a family name,"
                          " as appglass status lists them)" % key}
    route = route_of(app, rec)
    if route.get("state") == "excluded" or not route.get("family"):
        def skip(a):
            engine.store(a).dequeue(key)
            engine.store(a).save()
        with_lock(app, skip)
        return {"result": "skipped", "reason": route.get("reason")}
    seen = open_on_desktop(app, rec)
    if seen:
        # not judged, not recorded: it stays queued and keeps its state
        return {"result": "unverifiable",
                "reason": "a window of it is open on the desktop (%s): a single-instance app "
                          "would hand the hidden launch to it; checked once it is closed" % seen}
    res = run_harness(app, rec, app.levels.content)
    return with_lock(app, lambda a: record(a, key, rec, route, res))


def open_on_desktop(app, rec):
    """The app-id of a window of this app open on the real desktop, or None.
    A single-instance app (Electron's lock, a D-Bus name, a socket) can pass
    a second launch to the running instance, so the hidden session would
    measure nothing of its own, or the wrong window."""
    from . import learn
    rx = window_rx(rec)
    for w in learn.windows(app.env) or ():
        if re.search(rx, w["app_id"]):
            return w["app_id"]
    return None


def cmd_verify(app, key=None, queue=False):
    if app.dry_run:
        raise ValueError("verify has no dry run")
    g = game_running(app)
    if g:
        app.info("verify: %s: waiting, nothing checked" % g)
        return EX_TEMPFAIL
    if on_low_battery(app.env):
        app.info("verify: on battery under 20 %: waiting, nothing checked")
        return EX_TEMPFAIL
    install_term_handler()
    vl = verify_lock(app.env)
    if vl is None:
        app.info("verify: another check is running: nothing checked")
        return EX_TEMPFAIL
    try:
        return _verify_keys(app, key, queue)
    finally:
        vl.close()


def _verify_keys(app, key, queue):
    if queue:
        # the queue as a hook run sees it now (an app may have changed since)
        def queued(a):
            a.from_hook = True
            engine.refresh(a)
            return list(engine.store(a).data["queue"])
        keys = with_lock(app, queued)
        app.from_hook = True
    elif engine.record_for(app, key) is None and key in app.families:
        # a family name: check the apps of that family that are installed
        keys = [r["key"] for r in engine.records(app)
                if route_of(app, r).get("family") == key]
        if not keys:
            app.info("verify: %s: no app of this family found" % key)
            return 0
    else:
        keys = [key]
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
        kept = "; the %s stored for this version is kept" % res["kept"] if res.get("kept") else ""
        app.info("verify: %s: %s (%s)%s" % (k, res.get("result"), res.get("reason", ""), kept))
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
    if engine.record_for(app, key) is None:
        from .core import AppglassError
        raise AppglassError("fail: no app %s (use a key that appglass status shows)" % key)
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
    # the hidden session (verify) names the app version it checks
    fp = env.environ.get("APPGLASS_VERIFY_FP") or (rec or {}).get("fp")
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
