"""inputs: a no-change hook run that costs a few milliseconds.

The sync script runs ``appglass apply --from-hook --quiet --list-changed``
on every theme change and every launcher or settings event. Most of those
runs change nothing. A hook run records every path it looks at (open, stat,
lstat, access, readlink, listdir, scandir; absent paths too) with its stat,
and, when it wrote nothing, ran no program it cannot vouch for, saw nothing
change under it and left no check queued, saves them in
$XDG_CACHE_HOME/appglass/hook/inputs.json together with the stat of
appglass's own sources. The next hook run with the same command line and
environment stats those paths first: all the same, the run would do what the
last one did (nothing), so it exits before the lock.

The stat of a file is its inode, size, mtime and ctime; a listed directory
the same (an entry added or removed changes its mtime); a directory only
stat'ed (an exists() or a realpath() on the way) is its inode and type, so
an unrelated file in ~/.config does not cost a full run. Code that reads a
directory's mtime on purpose says so with full().

A program the run starts is opaque to the recorder: its output can change
with no file the run looked at changing. The callers that can name what the
output depends on run it inside covered() and full() those paths (flatpak
info: the app's deploy dirs; the toolchain: its cached versions). Any other
program makes the run not cacheable.
"""

import contextlib
import hashlib
import json
import os
import re
import stat
import sys

VERSION = 1
SKIP = ("/proc/", "/sys/", "/dev/")
ENV_RX = re.compile(r"^(HOME|USER|LANG|PATH|DISPLAY|WAYLAND_DISPLAY|NIRI_\w+|XDG_\w+"
                    r"|APPGLASS_\w+|FLATPAK_\w+|HERDR_\w+|PKG_CONFIG\w*)$")
PKG = os.path.dirname(os.path.abspath(__file__))
_stat, _lstat = os.stat, os.lstat
WRITE_EVENTS = ("os.rename", "os.remove", "os.rmdir", "os.mkdir", "os.symlink", "os.link",
                "os.chmod", "os.chown", "os.utime", "os.truncate", "os.chflags",
                "os.setxattr", "os.removexattr", "shutil.rmtree", "shutil.copyfile",
                "shutil.copymode", "shutil.copystat", "shutil.copytree", "shutil.move")
RUN_EVENTS = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
              "os.fork", "os.forkpty", "pty.spawn")
_W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def path(env):
    return os.path.join(env.cache_home, "appglass", "hook", "inputs.json")


def _one(s, full):
    if stat.S_ISDIR(s.st_mode) and not full:
        return [s.st_mode, s.st_ino, s.st_dev]
    return [s.st_mode, s.st_ino, s.st_dev, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def sig(p, full=True):
    """The stat of p (lstat, plus stat through a symlink), None if absent."""
    try:
        s = _lstat(p)
    except (OSError, ValueError):
        return None
    out = [_one(s, full)]
    if stat.S_ISLNK(s.st_mode):
        try:
            out.append(_one(_stat(p), full))
        except (OSError, ValueError):
            out.append(None)
    return out


def key(env, argv):
    e = sorted((k, v) for k, v in env.environ.items() if ENV_RX.match(k))
    doc = [VERSION, list(argv), e, sys.executable]
    return hashlib.sha256(json.dumps(doc).encode()).hexdigest()


def fresh(env, argv):
    """The last cacheable hook run had these inputs and nothing changed."""
    try:
        with open(path(env), "rb") as f:
            doc = json.loads(f.read().decode("utf-8"))
        if doc.get("v") != VERSION or doc.get("key") != key(env, argv):
            return False
        for p, full, s in doc["paths"]:
            if sig(p, full) != s:
                return False
        return bool(doc["paths"])
    except Exception:
        return False


def drop(env):
    """Forget the last digest (any write the run could not vouch for): an
    empty one in its place (an event run deletes no file, test_invariants)."""
    p = path(env)
    if not os.path.exists(p):
        return
    try:
        with open(p + ".tmp", "w") as f:
            f.write("{}\n")
        os.replace(p + ".tmp", p)
    except OSError:
        pass


class Recorder:
    def __init__(self, env):
        self.env = env
        self.mine = os.path.dirname(path(env))
        self.seen = {}          # path: [full, sig at first look]
        self.wrote = set()
        self.ran = []
        self.covered = 0
        self.on = False

    def note(self, p, full=False):
        if not self.on:
            return
        if isinstance(p, bytes):
            p = os.fsdecode(p)
        if not isinstance(p, str) or not p:
            return
        p = os.path.abspath(p)
        if p.startswith(SKIP) or "/__pycache__/" in p or p == self.mine \
                or p.startswith(self.mine + "/"):
            return
        old = self.seen.get(p)
        if old is None or (full and not old[0]):
            self.on = False
            try:
                self.seen[p] = [full or bool(old and old[0]), sig(p, full)]
            finally:
                self.on = True

    def wrote_to(self, *ps):
        for p in ps:
            if isinstance(p, bytes):
                p = os.fsdecode(p)
            if isinstance(p, str) and p:
                p = os.path.abspath(p)
                self.wrote.add(p)
                self.wrote.add(os.path.dirname(p))

    def audit(self, ev, args):
        if not self.on:
            return
        if ev == "open":
            p, mode, flags = args
            self.note(p)
            if (mode is not None and any(c in mode for c in "wax+")) or \
                    (mode is None and isinstance(flags, int) and flags & _W):
                self.wrote_to(p)
        elif ev in ("os.listdir", "os.scandir"):
            self.note(args[0] if args and args[0] is not None else ".", full=True)
        elif ev in WRITE_EVENTS:
            self.wrote_to(*[a for a in args if isinstance(a, (str, bytes))])
        elif ev.startswith(RUN_EVENTS) and not self.covered:
            self.ran.append(str(args[:2]) if isinstance(args, tuple) else ev)

    def result(self):
        """The paths to save, or None when this run is not cacheable."""
        self.on = False
        if self.ran:
            return None
        out = []
        for p, (full, pre) in self.seen.items():
            post = sig(p, full)
            if post != pre and p not in self.wrote:
                return None             # changed under this run
            out.append([p, full, post])
        # appglass itself: a new version (or a module added) is a full run
        for top, dirs, files in os.walk(PKG):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            out.append([top, True, sig(top, True)])
            out += [[os.path.join(top, n), True, sig(os.path.join(top, n), True)]
                    for n in files if n.endswith(".py")]
        return out


_rec = None
_hooked = False


def _audit(ev, args):
    if _rec is not None:
        _rec.audit(ev, args)


def start(env):
    """Record what this process looks at from now on (the audit hook and
    the os wrappers go in once per process: an audit hook cannot be
    removed)."""
    global _rec, _hooked
    _rec = Recorder(env)
    if not _hooked:
        _hooked = True
        sys.addaudithook(_audit)

        def wrap(f):
            def w(p, *a, **kw):
                if _rec is not None and _rec.on and kw.get("dir_fd") is None:
                    _rec.note(p)
                return f(p, *a, **kw)
            return w
        os.stat = wrap(_stat)
        os.lstat = wrap(_lstat)
        os.access = wrap(os.access)
        os.readlink = wrap(os.readlink)
    _rec.on = True
    return _rec


def full(p):
    """Code that reads p's mtime (a directory too) says so."""
    if _rec is not None:
        _rec.note(p, full=True)


@contextlib.contextmanager
def covered():
    """A program whose output depends only on paths the caller full()s."""
    if _rec is None:
        yield
        return
    _rec.covered += 1
    try:
        yield
    finally:
        _rec.covered -= 1


def save(env, argv, ok):
    """End of a hook run: save the digest when ok and cacheable, else drop
    the old one."""
    global _rec
    rec, _rec = _rec, None
    if rec is None:
        return
    rec.on = False
    p = path(env)
    try:
        env.guard(p)
    except Exception:
        return
    try:
        if not ok:
            drop(env)
            return
        if not os.path.isdir(os.path.dirname(p)):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            rec.wrote_to(os.path.dirname(p))
        paths = rec.result()
        if paths is None:
            drop(env)
            return
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"v": VERSION, "key": key(env, argv), "paths": paths}, f)
        os.replace(tmp, p)
    except Exception:
        drop(env)
