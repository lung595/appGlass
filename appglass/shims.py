"""Shared pieces of the shim and wrapper adapters (qt-style, webkit-shim,
ck-shim, qtquick-shim, electron-hook, electron-vencord).

Sources live in the repo under shims/<adapter>/. At apply time a family:

* builds its C/C++ shim with the host compiler into
  ~/.local/lib/appglass/<app>/ (``build``): a ctx.artifact whose stamp is the
  sha256 of the sources plus the compiler and Qt versions, so it is rebuilt
  only when one of them changes (or the file was changed by hand);
* copies the runtime files (templates, hooks, the shim source for reference)
  next to it (``copy``), and renders the CSS from the palette and the levels
  (``render``), the same way the launch wrapper does with jq (``jq_raw``,
  ``jq_pct``), so a launch and an apply give the same bytes;
* writes the launch wrapper ~/.local/bin/appglass-<app> (``wrapper``): it
  reads ``appglass levels`` at every launch and falls back to the plain app
  when the shim is missing;
* points the launcher at the wrapper (``exec_to``) through
  ctx.desktop_override.
"""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile

from .core import Conflict, hex_to_rgb

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIMS = os.path.join(REPO, "shims")
APPGLASS = os.path.join(REPO, "bin", "appglass")
PLACEHOLDER = "@APPGLASS@"


def source(adapter, name):
    with open(os.path.join(SHIMS, adapter, name), "rb") as f:
        return f.read()


def lib_dir(env, *p):
    return env.home_path(".local", "lib", "appglass", *p)


def bin_path(env, name):
    return env.home_path(".local", "bin", name)


def appglass_cmd(env, p=None):
    """bin/appglass (or another repo path) as a wrapper writes it inside
    double quotes: $HOME/... when the repo is under HOME, else the absolute
    path (verify.stage turns the $HOME form back into the absolute one for
    the hidden session, whose HOME holds no repo)."""
    p = APPGLASS if p is None else p
    if p.startswith(env.home + os.sep):
        # only the $HOME prefix expands: a $ in the rest stays literal
        return "$HOME" + re.sub(r'(["\\`$])', r"\\\1", p[len(env.home):])
    return re.sub(r'(["\\`$])', r"\\\1", p)


def script(env, adapter, name):
    """A repo script with @APPGLASS@ filled in."""
    return source(adapter, name).decode("utf-8").replace(PLACEHOLDER, appglass_cmd(env))


def wrapper(ctx, adapter, name, meta=None):
    """~/.local/bin/<name> from shims/<adapter>/<name>, executable (meta: kept
    in its state record)."""
    return ctx.write_owned(bin_path(ctx.env, name), script(ctx.env, adapter, name), meta=meta,
                           mode=0o755)


def copy(ctx, adapter, app, names, mode=None):
    out = []
    for n in names:
        out.append(ctx.write_owned(lib_dir(ctx.env, app, n), source(adapter, n), mode=mode))
    return out


# --- numbers and colours the way the wrappers print them with jq

def jq_raw(x):
    """jq -r '.k' of a number appglass levels printed (json floats)."""
    return repr(float(x))


def jq_pct(x):
    """jq -r '(.k * 1000 | round) / 10'."""
    v = math.floor(float(x) * 1000 + 0.5) / 10
    return str(int(v)) if v == int(v) else repr(v)


def rgb(ctx, role, fallback):
    """'r, g, b' of a palette role (fallback hex when the role is missing)."""
    try:
        h = ctx.colors(role)
    except Exception:
        h = "#" + fallback
    return "%d, %d, %d" % hex_to_rgb(h)


def fill(text, pairs):
    """sed -e s/{{k}}/v/g ... in order."""
    for k, v in pairs:
        text = text.replace("{{%s}}" % k, v)
    return text


def levels(ctx):
    """The values `appglass levels` prints (bar_over_content rounded)."""
    from . import inactive
    return dict(ctx.levels.as_dict(), **inactive.fields(ctx.settings, ctx.levels.content))


# --- launcher

_FIELD = {"@@", "@@u", "@@f"}


_RESERVED = set(" \t\n\"'\\><~|&;$*?#()`")


def desktop_quote(arg):
    """One Exec= argument, quoted as the Desktop Entry spec says: in double
    quotes when it holds a reserved character, with " ` $ \\ escaped by a
    backslash; then the string-value escape doubles every backslash; a
    literal % is %%."""
    if "\n" in arg or "\r" in arg:
        raise ValueError("no Exec= argument can hold a line break: %r" % arg)
    if any(c in _RESERVED for c in arg) or not arg:
        arg = '"%s"' % re.sub(r'(["`$\\])', r"\\\1", arg)
        arg = arg.replace("\\", "\\\\")
    return arg.replace("%", "%%")


def exec_to(text, wrapper_path, app_id=None, command=None):
    """Point every Exec= at wrapper_path, keeping the arguments after the
    app (flatpak: after app_id, with the @@ file-forwarding marks dropped;
    host: after the command word)."""
    def one(m):
        words = m.group(1).split()
        if app_id is not None:
            if app_id not in words:
                return m.group(0)
            rest = words[words.index(app_id) + 1:]
        else:
            if not words or os.path.basename(words[0]) != command:
                return m.group(0)
            rest = words[1:]
        rest = [w for w in rest if w not in _FIELD]
        return "Exec=" + " ".join([desktop_quote(wrapper_path)] + rest)
    return re.sub(r"(?m)^Exec=(.*)$", one, text)


# --- builds

def _tool(env, name, fallbacks=()):
    p = env.which(name)
    if p:
        return p
    for f in fallbacks:
        if os.path.isfile(f) and os.access(f, os.X_OK):
            return f
    return None


def _out(env, argv):
    try:
        r = env.run(argv, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


PC_DIRS = ("/usr/lib64/pkgconfig", "/usr/lib/pkgconfig", "/usr/share/pkgconfig",
           "/usr/local/lib64/pkgconfig", "/usr/local/lib/pkgconfig",
           "/usr/local/share/pkgconfig", "/usr/lib/x86_64-linux-gnu/pkgconfig")


def _versions_path(env):
    return os.path.join(env.cache_home, "appglass", "toolchain.json")


def _cached(env, argv, deps=(), keep=True):
    """_out(env, argv), kept in $XDG_CACHE_HOME/appglass/toolchain.json while
    the stat of the tool and of deps stays the same: the versions in a
    build stamp, so a run that builds nothing starts no compiler (and the
    hook run stays cacheable: inputs.py). keep: False in a dry run (it
    writes nothing)."""
    from . import inputs
    from .core import _atomic_write, _load_json
    deps = [os.path.realpath(argv[0])] + list(deps)
    for d in deps:
        inputs.full(d)
    sig = [inputs.sig(d) for d in deps]
    k = json.dumps([list(argv), sorted((n, v) for n, v in env.environ.items()
                                       if n.startswith("PKG_CONFIG"))])
    p = _versions_path(env)
    doc = _load_json(p)
    doc = doc if isinstance(doc, dict) and doc.get("v") == 1 else {"v": 1, "runs": {}}
    hit = doc["runs"].get(k) if isinstance(doc.get("runs"), dict) else None
    if isinstance(hit, dict) and hit.get("sig") == sig and isinstance(hit.get("out"), str):
        return hit["out"]
    with inputs.covered():
        out = _out(env, argv)
    if out and keep:
        doc.setdefault("runs", {})[k] = {"sig": sig, "out": out}
        try:
            env.guard(p)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            _atomic_write(p, json.dumps(doc, indent=1, sort_keys=True).encode())
        except OSError:
            pass
    return out


class Toolchain:
    """The host compilers: cc, cxx, pkg-config, moc (any may be None)."""

    def __init__(self, env, keep=True):
        self.env = env
        self.keep = keep          # False: a dry run, the version cache untouched
        self.cc = _tool(env, "gcc") or _tool(env, "cc")
        self.cxx = _tool(env, "g++") or _tool(env, "c++")
        self.pkgconfig = _tool(env, "pkg-config") or _tool(env, "pkgconf")
        self._moc = False

    def pkg(self, *args):
        return _out(self.env, [self.pkgconfig] + list(args)) if self.pkgconfig else ""

    def pc_dirs(self):
        e = self.env.environ
        extra = [d for d in (e.get("PKG_CONFIG_PATH") or "").split(os.pathsep) if d]
        lib = [d for d in (e.get("PKG_CONFIG_LIBDIR") or "").split(os.pathsep) if d]
        return extra + (lib or list(PC_DIRS))

    def pkg_info(self, *args):
        """pkg(*args) for a version or a variable: cached while pkg-config
        and the .pc files of the modules named stay the same."""
        if not self.pkgconfig:
            return ""
        deps = []
        for d in self.pc_dirs():
            deps.append(d)
            deps += [os.path.join(d, m + ".pc") for m in args if not m.startswith("-")]
        return _cached(self.env, [self.pkgconfig] + list(args), deps, self.keep)

    @property
    def moc(self):
        if self._moc is False:
            d = self.pkg_info("--variable=libexecdir", "Qt6Core")
            cands = [os.path.join(d, "moc")] if d else []
            cands += ["/usr/lib64/qt6/libexec/moc", "/usr/lib/qt6/libexec/moc"]
            self._moc = (next((c for c in cands if os.path.isfile(c) and os.access(c, os.X_OK)),
                              None) or _tool(self.env, "moc-qt6"))
        return self._moc

    def version(self, tool):
        return _cached(self.env, [tool, "--version"], keep=self.keep).splitlines()[0:1] \
            if tool else []


def stamp(sources, parts):
    h = hashlib.sha256()
    for n in sorted(sources):
        h.update(n.encode() + b"\0" + hashlib.sha256(sources[n]).digest())
    for p in parts:
        h.update(b"\0" + str(p).encode())
    return h.hexdigest()


def build(ctx, adapter, dest, sources, steps, tools, qt=(), extra=(), mode=0o755):
    """ctx.artifact at dest (absolute, mode 0755 by default) built from sources
    ({name: bytes}, written to a temp dir) by steps(tc, dir) -> [argv...],
    run in that dir; the output is the file named basename(dest) there.

    tools: the Toolchain attributes the build needs ("cc", "cxx", "moc",
    "pkgconfig"); qt: pkg-config modules whose versions go into the stamp;
    extra: more stamp parts (a flatpak runtime the shim is loaded into).
    Raises Conflict (the family is skipped) when a tool is missing.
    """
    tc = Toolchain(ctx.env, keep=not getattr(ctx.app, "dry_run", False))
    missing = [t for t in tools if not getattr(tc, t)]
    if missing:
        raise Conflict("cannot build %s: %s not found (gcc-c++ and qt6-qtbase-devel)"
                       % (os.path.basename(dest), ", ".join(missing)))
    parts = []
    for t in tools:
        if t in ("cc", "cxx"):
            parts += tc.version(getattr(tc, t))
    for m in qt:
        v = tc.pkg_info("--modversion", m)
        if not v:
            raise Conflict("cannot build %s: pkg-config does not know %s"
                           % (os.path.basename(dest), m))
        parts.append("%s %s" % (m, v))
    st = stamp(sources, parts + list(extra))
    name = os.path.basename(dest)

    def run():
        d = tempfile.mkdtemp(prefix="appglass-build-")
        try:
            for n, data in sources.items():
                with open(os.path.join(d, n), "wb") as f:
                    f.write(data)
            for argv in steps(tc, d):
                r = ctx.env.run(argv, cwd=d, timeout=600)
                if r.returncode != 0:
                    raise Conflict("building %s failed: %s\n%s"
                                   % (name, " ".join(argv[:2]), (r.stderr or r.stdout)[-2000:]))
            with open(os.path.join(d, name), "rb") as f:
                return f.read()
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return ctx.artifact(name, run, st, dest=dest, mode=mode)


def pkg_flags(tc, *mods, only_i=False):
    args = ["--cflags-only-I"] if only_i else ["--cflags", "--libs"]
    return tc.pkg(*(args + list(mods))).split()


def installed_flatpak(env, app_id):
    return flatpak_info(env, app_id) is not None


def flatpak_info(env, app_id):
    from . import detect
    return detect.flatpak_app(env, app_id)


def asar_version(path):
    """The version in the package.json of an Electron app.asar, or None."""
    import struct
    try:
        with open(path, "rb") as f:
            head = f.read(16)
            if len(head) < 16:
                return None
            hdr = json.loads(f.read(struct.unpack("<I", head[12:16])[0]))
            ent = hdr["files"]["package.json"]
            f.seek(8 + struct.unpack("<I", head[4:8])[0] + int(ent["offset"]))
            v = json.loads(f.read(int(ent["size"])))["version"]
    except (OSError, ValueError, KeyError, TypeError, struct.error):
        return None
    return v if isinstance(v, str) and re.match(r"^[\w.+-]{1,64}$", v) else None


def _crc32c(data, _t=[]):
    if not _t:
        for n in range(256):
            for _ in range(8):
                n = (n >> 1) ^ (0x82f63b78 if n & 1 else 0)
            _t.append(n)
    crc = 0xffffffff
    for b in data:
        crc = _t[(crc ^ b) & 0xff] ^ (crc >> 8)
    return crc ^ 0xffffffff


def _varint(n):
    out = b""
    while n >= 0x80:
        out += bytes([(n & 0x7f) | 0x80])
        n >>= 7
    return out + bytes([n])


def local_storage_log(origin, items):
    """A Chromium Local Storage leveldb with items {key: value} (str, Latin-1)
    for origin ("file://"), as one write-ahead log (000003.log) in an
    otherwise empty leveldb dir: leveldb creates its manifest and replays
    the log on open. Keys and values carry Chromium's Latin-1 prefix (1);
    the origin gets its META record (last modified, size)."""
    import struct
    import time
    puts = [(b"VERSION", b"1")]
    size = 0
    for k, v in items.items():
        key, val = k.encode("latin-1"), v.encode("latin-1")
        puts.append((b"_" + origin.encode() + b"\x00\x01" + key, b"\x01" + val))
        size += len(key) + len(val)
    # base::Time: microseconds since 1601-01-01
    now = int(time.time() * 1e6) + 11644473600 * 1000000
    puts.append((b"META:" + origin.encode(), b"\x08" + _varint(now) + b"\x10" + _varint(size)))
    body = struct.pack("<QI", 1, len(puts))
    for k, v in puts:
        body += b"\x01" + _varint(len(k)) + k + _varint(len(v)) + v
    assert len(body) < 32768 - 7, "one block"
    c = _crc32c(b"\x01" + body)
    masked = (((c >> 15) | (c << 17)) + 0xa282ead8) & 0xffffffff
    return struct.pack("<IHB", masked, len(body), 1) + body


def launcher(ctx, desktop_id, wrapper_path, app_id=None, command=None):
    """The launcher override that starts wrapper_path; a warning (and
    None) without a system launcher."""
    p = ctx.desktop_override(desktop_id, lambda t: exec_to(t, wrapper_path, app_id, command))
    if p is None:
        ctx.warn("no system launcher %s: start %s by hand" % (desktop_id,
                                                              ctx.env.tilde(wrapper_path)))
    return p


def c_shim(ctx, adapter, app, src, out):
    """gcc -shared -fPIC -O2 -Wall -o <out> <src> -ldl into lib/<app>/<out>."""
    return build(ctx, adapter, lib_dir(ctx.env, app, out),
                 {src: source(adapter, src)},
                 lambda tc, d: [[tc.cc, "-shared", "-fPIC", "-O2", "-Wall", "-o", out, src,
                                 "-ldl"]],
                 ("cc",))
