"""appglass core: environment, safety guard, colours, levels, state and commands.

Every write goes through a plan: families describe what they want written
(``Ctx.write_owned``, ``Ctx.edit_text``, ``Ctx.merge_json``), the core checks
every target against the sandbox guard and the ownership rules, and only then
writes. ``state.json`` records each file created and each pre-existing file
modified (original bytes saved under ``backup/``), so ``remove`` can put the
tree back byte-identical.
"""

import argparse
import errno
import fcntl
import hashlib
import importlib
import json
import os
import pkgutil
import re
import shutil
import subprocess
import sys

STATE_VERSION = 1
DEFAULT_CONTENT = 0.60
BAR_MIN = 0.65
CORE_OWNERS = ("niri", "hook")
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$")


# ---------------------------------------------------------------- errors

class AppglassError(Exception):
    exit_code = 1


class SandboxViolation(AppglassError):
    exit_code = 2


class Conflict(AppglassError):
    """A target exists, is not ours and cannot be merged safely: skip the owner."""


# ---------------------------------------------------------------- colour helpers

def norm_hex(value):
    """'#AABBCC' / 'aabbcc' / '#aabbccdd' -> '#aabbcc' (alpha dropped)."""
    m = _HEX.match(str(value).strip())
    if not m:
        raise ValueError("not a hex colour: %r" % (value,))
    return "#" + m.group(1).lower()


def hex_to_rgb(value):
    h = norm_hex(value)[1:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#" + "".join("%02x" % max(0, min(255, int(round(c)))) for c in rgb)


def alpha8(a):
    """0.60 -> 153."""
    return int(round(255 * max(0.0, min(1.0, float(a)))))


def alpha_hex(a):
    """0.60 -> '99' (two hex digits, for #rrggbbaa)."""
    return "%02x" % alpha8(a)


def rgba(hex_colour, a):
    """CSS rgba(): rgba('#101418', 0.6) -> 'rgba(16, 20, 24, 0.60)'."""
    r, g, b = hex_to_rgb(hex_colour)
    return "rgba(%d, %d, %d, %s)" % (r, g, b, _fmt_alpha(a))


def _fmt_alpha(a):
    s = "%.3f" % float(a)
    s = s.rstrip("0")
    if s.endswith("."):
        s += "0"
    if len(s.split(".")[1]) < 2:
        s += "0"
    return s


def mix(a, b, t):
    """Blend hex a toward hex b by t (0..1), in sRGB."""
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(ra[i] + (rb[i] - ra[i]) * t for i in range(3)))


def scale(hex_colour, f):
    return rgb_to_hex(tuple(c * f for c in hex_to_rgb(hex_colour)))


def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    if isinstance(rgb, str):
        rgb = hex_to_rgb(rgb)
    r, g, b = (_lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def glass_range(bg_hex, alpha):
    """Luminance range of a glass pixel (bg at alpha) over any backdrop."""
    bg = hex_to_rgb(bg_hex)
    a = float(alpha)
    over_black = tuple(c * a for c in bg)
    over_white = tuple(c * a + 255 * (1 - a) for c in bg)
    return luminance(over_black), luminance(over_white)


def worst_contrast(fg_hex, bg_hex, alpha):
    """Worst contrast of opaque text fg on the glass, over any backdrop.

    The glass composite lies between "glass over black" and "glass over
    white" (per channel, so in luminance too). Text inside that range can
    meet a backdrop that matches it exactly (contrast 1).
    """
    lo, hi = glass_range(bg_hex, alpha)
    lt = luminance(fg_hex)
    if lt > hi:
        return (lt + 0.05) / (hi + 0.05)
    if lt < lo:
        return (lo + 0.05) / (lt + 0.05)
    return 1.0


def readable(fg_hex, bg_hex, alpha, target=2.25):
    """Return fg (or fg moved toward white/black) with worst_contrast >= target.

    The hue is kept by blending in sRGB; the direction is the one that needs
    the smaller change. Already readable colours come back unchanged.
    """
    fg = norm_hex(fg_hex)
    if worst_contrast(fg, bg_hex, alpha) >= target:
        return fg
    best = None
    for end in ("#ffffff", "#000000"):
        for i in range(1, 101):
            c = mix(fg, end, i / 100.0)
            if worst_contrast(c, bg_hex, alpha) >= target:
                if best is None or i < best[0]:
                    best = (i, c)
                break
    if best is None:
        lo, hi = glass_range(bg_hex, alpha)
        return "#ffffff" if (1.05 / (hi + 0.05)) >= ((lo + 0.05) / 0.05) else "#000000"
    return best[1]


# ---------------------------------------------------------------- environment

def _split(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


class Env:
    """Paths and switches, all from the environment (XDG defaults per spec)."""

    def __init__(self, environ=None):
        e = dict(os.environ if environ is None else environ)
        self.environ = e
        home = e.get("HOME")
        if not home:
            raise AppglassError("HOME is not set")
        self.home = os.path.abspath(home)

        def xdg(var, default):
            v = e.get(var)
            if v and os.path.isabs(v):
                return os.path.abspath(v)
            return os.path.join(self.home, default)

        self.config_home = xdg("XDG_CONFIG_HOME", ".config")
        self.data_home = xdg("XDG_DATA_HOME", os.path.join(".local", "share"))
        self.state_home = xdg("XDG_STATE_HOME", os.path.join(".local", "state"))
        self.cache_home = xdg("XDG_CACHE_HOME", ".cache")
        if "APPGLASS_SANDBOX" in e and not e["APPGLASS_SANDBOX"].strip():
            # set but empty: a script bug, never "no sandbox"
            raise SandboxViolation("APPGLASS_SANDBOX is set but empty: refusing")
        sb = e.get("APPGLASS_SANDBOX")
        self.sandbox = os.path.realpath(sb) if sb else None
        self.assume_installed = set(_split(e.get("APPGLASS_ASSUME_INSTALLED")))
        self.assume_not_installed = set(_split(e.get("APPGLASS_ASSUME_NOT_INSTALLED")))

    # paths
    def config_path(self, *p):
        return os.path.join(self.config_home, *p)

    def data_path(self, *p):
        return os.path.join(self.data_home, *p)

    def state_path(self, *p):
        return os.path.join(self.state_home, *p)

    def cache_path(self, *p):
        return os.path.join(self.cache_home, *p)

    def home_path(self, *p):
        return os.path.join(self.home, *p)

    @property
    def state_dir(self):
        return self.state_path("appglass")

    def tilde(self, path):
        """'~/x' when path is under HOME, else the absolute path."""
        path = os.path.abspath(path)
        if path.startswith(self.home + os.sep):
            return "~/" + os.path.relpath(path, self.home)
        return path

    # safety guard
    def guard(self, path):
        if self.sandbox is None:
            return
        real = os.path.realpath(path)
        sb = self.sandbox
        if real != sb and not real.startswith(sb + os.sep):
            raise SandboxViolation(
                "APPGLASS_SANDBOX=%s: refusing to write %s" % (sb, path))

    # install detection
    def which(self, cmd):
        return shutil.which(cmd, path=self.environ.get("PATH", os.defpath))

    def flatpak_installed(self, app_id):
        if not self.which("flatpak"):
            return False
        try:
            r = subprocess.run(["flatpak", "info", app_id], env=self.environ,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               stdin=subprocess.DEVNULL, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0

    def run(self, argv, **kw):
        kw.setdefault("env", self.environ)
        kw.setdefault("stdin", subprocess.DEVNULL)
        kw.setdefault("capture_output", True)
        kw.setdefault("text", True)
        return subprocess.run(argv, **kw)


# ---------------------------------------------------------------- colours / levels

class Palette:
    """Matugen roles for the current mode.

    Source order: $XDG_STATE_HOME/appglass/colors.json (rendered by the hook
    template), then $XDG_CACHE_HOME/dms/dms-colors.json (.colors.<mode>).
    """

    def __init__(self, env, warn=None):
        self.env = env
        self.mode = "dark"
        self.colors = {}
        self.source = None
        self.dank16 = None
        self.term16 = None
        self.term16_mtime = None
        warn = warn or (lambda m: None)
        dms = env.cache_path("dms", "dms-colors.json")
        ours = os.path.join(env.state_dir, "colors.json")
        dms_data = _load_json(dms)
        if os.path.exists(ours):
            d = _load_json(ours)
            if isinstance(d, dict) and isinstance(d.get("colors"), dict) and d["colors"]:
                try:
                    self.colors = {k: norm_hex(v) for k, v in d["colors"].items()}
                    self.mode = d.get("mode") if d.get("mode") in ("dark", "light") else "dark"
                    self.source = ours
                    t16 = d.get("dank16term")
                    if isinstance(t16, dict):
                        try:
                            self.term16 = [norm_hex(t16["color%d" % i]) for i in range(16)]
                            self.term16_mtime = os.stat(ours).st_mtime
                        except (KeyError, TypeError, ValueError):
                            self.term16 = None
                except ValueError as ex:
                    warn("ignoring %s: %s" % (ours, ex))
                    self.colors = {}
            else:
                warn("ignoring malformed %s" % ours)
        if not self.colors and isinstance(dms_data, dict):
            mode = dms_data.get("mode") if dms_data.get("mode") in ("dark", "light") else "dark"
            cols = (dms_data.get("colors") or {}).get(mode) or {}
            try:
                self.colors = {k: norm_hex(v) for k, v in cols.items() if isinstance(v, str)}
            except ValueError as ex:
                warn("ignoring %s: %s" % (dms, ex))
                self.colors = {}
            if self.colors:
                self.mode, self.source = mode, dms
        if isinstance(dms_data, dict) and isinstance(dms_data.get("dank16"), dict):
            d16 = dms_data["dank16"]
            try:
                self.dank16 = [norm_hex(d16["color%d" % i][self.mode]) for i in range(16)]
            except (KeyError, TypeError, ValueError):
                self.dank16 = None

    def get(self, role):
        try:
            return self.colors[role]
        except KeyError:
            raise AppglassError("colour role %r not found (source: %s)"
                                % (role, self.source or "none: no DMS colours found"))


class Levels:
    """Alphas per level. content = DMS foregroundLayerTransparency."""

    def __init__(self, content, bar=None):
        c = max(0.0, min(1.0, float(content)))
        self.content = c
        self.bar = max(c, BAR_MIN) if bar is None else max(c, min(1.0, float(bar)))
        self.popup = 1.0
        # alpha a bar must be painted with, on top of the content, to land at `bar`
        self.bar_over_content = 0.0 if c >= 1.0 else (self.bar - c) / (1.0 - c)
        self.content8 = alpha8(self.content)
        self.bar8 = alpha8(self.bar)
        self.popup8 = 255

    @classmethod
    def from_env(cls, env, settings=None):
        """settings.json levels.content wins when set; else the DMS window rule
        opacity (Settings > Window Rules, the global rule with blur), then DMS
        foregroundLayerTransparency, then 0.60. levels.bar overrides the bars."""
        if settings is None:
            from . import settings as _s
            settings = _s.load(env)[0]
        lv = settings.get("levels", {})
        if lv.get("content") is not None:
            return cls(lv["content"], lv.get("bar"))
        v = dms_rule_opacity(env.config_path("niri", "dms", "windowrules.kdl"))
        if v is None:
            s = _load_json(env.config_path("dms", "settings.json"))
            v = DEFAULT_CONTENT
            if isinstance(s, dict) and isinstance(s.get("foregroundLayerTransparency"), (int, float)):
                v = float(s["foregroundLayerTransparency"])
        return cls(v, lv.get("bar"))

    def as_dict(self):
        return {"content": self.content, "bar": self.bar, "popup": self.popup,
                "bar_over_content": round(self.bar_over_content, 4),
                "content8": self.content8, "bar8": self.bar8, "popup8": self.popup8}


def dms_rule_opacity(path):
    """Opacity of the first DMS window rule that has no match and turns the blur on
    (the "Glass blur" rule DMS writes to niri/dms/windowrules.kdl), or None."""
    raw = _read(path)
    if raw is None:
        return None
    text = re.sub(r"//[^\n]*", "", raw.decode("utf-8", "replace"))
    for block in re.split(r"\bwindow-rule\s*\{", text)[1:]:
        if re.search(r"^\s*match\b", block, re.M):
            continue
        if not re.search(r"\bblur\s+true\b", block):
            continue
        m = re.search(r"^\s*opacity\s+([0-9]*\.?[0-9]+)", block, re.M)
        if m:
            return max(0.0, min(1.0, float(m.group(1))))
    return None


def _load_json(path):
    try:
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _read_planned(path):
    """_read for a family's plan: a path that exists but cannot be read as a
    file (a directory, mode 000, ...) is a Conflict, not a crash."""
    try:
        return _read(path)
    except OSError as ex:
        if os.path.isdir(path):
            raise Conflict("%s is not a regular file (left untouched)" % path)
        raise Conflict("%s cannot be read (%s); left untouched"
                       % (path, ex.strerror or type(ex).__name__))


def sha(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- state

class State:
    def __init__(self, env):
        self.env = env
        self.path = os.path.join(env.state_dir, "state.json")
        d = _load_json(self.path)
        if not isinstance(d, dict) or d.get("version") != STATE_VERSION:
            if d is not None:
                raise AppglassError("unreadable state %s; refusing to guess" % self.path)
            d = {"version": STATE_VERSION, "owners": {}, "state_parents": []}
        d.setdefault("owners", {})
        d.setdefault("state_parents", [])
        self.data = d

    @property
    def owners(self):
        return self.data["owners"]

    def owner_of(self, path):
        for name, o in self.owners.items():
            if path in o.get("files", {}):
                return name
        return None

    def families(self):
        return sorted(n for n in self.owners if n not in CORE_OWNERS)

    def save(self):
        env = self.env
        d = env.state_dir
        env.guard(self.path)
        if not os.path.isdir(d):
            created = _missing_dirs(d)
            for p in created:
                env.guard(p)
            os.makedirs(d, exist_ok=True)
            if not self.data["state_parents"]:
                self.data["state_parents"] = created
        data = (json.dumps(self.data, indent=2, sort_keys=True) + "\n").encode()
        _atomic_write(self.path, data)

    def destroy(self):
        """Remove the state dir and any parent dirs it created (when empty)."""
        d = self.env.state_dir
        if os.path.isdir(d):
            self.env.guard(d)
            shutil.rmtree(d)
        for p in sorted(self.data.get("state_parents", []), key=len, reverse=True):
            if p == d:
                continue
            try:
                os.rmdir(p)
            except OSError:
                pass


def _missing_dirs(d):
    out = []
    d = os.path.abspath(d)
    while not os.path.isdir(d):
        out.append(d)
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return list(reversed(out))


def _atomic_write(path, data):
    tmp = os.path.join(os.path.dirname(path), ".%s.appglass-tmp" % os.path.basename(path))
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        st = os.stat(path)
        os.chmod(tmp, st.st_mode & 0o7777)
    except FileNotFoundError:
        pass
    os.replace(tmp, path)


def _inplace_write(path, data):
    """Rewrite an existing file without changing its inode (watchers keep it)."""
    if os.path.exists(path):
        with open(path, "r+b") as f:
            f.write(data)
            f.truncate()
    else:
        with open(path, "wb") as f:
            f.write(data)


# ---------------------------------------------------------------- plan / ctx

def _unmerge_json(cur, keys):
    """The JSON object in cur with merge_json's keys put back. A key whose
    value is no longer the one appglass set (the app or user changed it or
    took it out) is left as it is."""
    obj = json.loads(cur.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("not a JSON object")
    for k, info in keys.items():
        if "set" in info and (k not in obj or obj[k] != info["set"]):
            continue      # changed or taken out since: theirs now
        if info.get("present"):
            obj[k] = info.get("value")
        else:
            obj.pop(k, None)
    return obj


class Op:
    __slots__ = ("kind", "data", "undo", "keys", "meta")

    def __init__(self, kind, data, undo=None, keys=None, meta=None):
        self.kind = kind      # owned | edit | json
        self.data = data      # bytes to write
        self.undo = undo      # edit: fn(text)->text for a diverged remove
        self.keys = keys      # json: {key: {"present": bool, "value": ...}}
        self.meta = meta      # owned: extra record fields (desktop source, artifact stamp)


class Ctx:
    """What a family's apply(ctx) gets. See appglass/families/__init__.py."""

    def __init__(self, app, owner):
        self.app = app
        self.owner = owner
        self.env = app.env
        self.ops = {}
        self.order = []
        self.messages = []
        self.once = set()       # warn_once keys still true this run
        self.kept_absent = set()  # recorded files the user deleted: left deleted
        # a family with several apps may set this to the niri app-id regexes
        # of the apps it actually configured (default: the module's APP_IDS)
        self.app_ids = None

    # read-only info
    @property
    def mode(self):
        return self.app.palette.mode

    @property
    def levels(self):
        return self.app.levels

    @property
    def dank16(self):
        return self.app.palette.dank16

    @property
    def term16(self):
        """(list of 16 hex, mtime) of DMS's terminal palette (dank16term) from
        the hook's colors.json, or (None, None) without the hook."""
        return self.app.palette.term16, self.app.palette.term16_mtime

    def colors(self, role):
        return self.app.palette.get(role)

    alpha_hex = staticmethod(alpha_hex)
    rgba = staticmethod(rgba)
    readable = staticmethod(readable)

    def config_path(self, *p):
        return self.env.config_path(*p)

    def data_path(self, *p):
        return self.env.data_path(*p)

    def state_path(self, *p):
        return self.env.state_path(*p)

    def cache_path(self, *p):
        return self.env.cache_path(*p)

    def home_path(self, *p):
        return self.env.home_path(*p)

    def warn(self, msg):
        self.messages.append(msg)

    def warn_once(self, key, msg):
        """warn() only the first apply in a row that hits ``key``: an apply
        that does not call warn_once(key) forgets it again."""
        if key in self.once:
            return            # already said this run (a family's own wording wins)
        self.once.add(key)
        if key not in self.app.state.owners.get(self.owner, {}).get("warned", []):
            self.warn(msg)

    def read_text(self, path):
        """Current text of path as this plan would leave it (None if absent)."""
        path = os.path.abspath(path)
        if path in self.ops:
            return self.ops[path].data.decode("utf-8")
        if path in self.kept_absent:
            return None
        b = _read_planned(path)
        return None if b is None else b.decode("utf-8", "replace")

    # ownership checks
    def _record(self, path):
        return self.app.state.owners.get(self.owner, {}).get("files", {}).get(path)

    def _check_other_owner(self, path):
        o = self.app.state.owner_of(path)
        if o is not None and o != self.owner:
            raise Conflict("%s is managed by appglass '%s'" % (path, o))

    def changed_since_apply(self, path):
        """True when this owner wrote path before and the user or the app
        changed it since (now or at an earlier apply: sticky), deleting it
        included. edit_text then hands fn the current text (or, deleted,
        leaves it deleted); a family can use this to keep a user's opt-out
        (its part taken out) instead of putting its part back."""
        path = os.path.abspath(path)
        rec = self._record(path)
        if rec is None or rec.get("how") not in ("edit", "json"):
            return False
        if rec.get("app_rewrote") or self.deleted_since_apply(path):
            return True
        cur = _read_planned(path)
        return cur is not None and sha(cur) != rec.get("sha256")

    def deleted_since_apply(self, path):
        """True when this owner wrote path before and it is gone now (the
        user deleted it). edit_text and merge_json then leave it deleted, on
        every apply until remove; write_owned does on hook runs (a manual
        apply writes an owned file again)."""
        path = os.path.abspath(path)
        return (self._record(path) is not None and path not in self.ops
                and not os.path.lexists(path))

    def _keep_deleted(self, path, what):
        """Plan nothing for a recorded file the user deleted: the record
        stays (remove still knows it), the file stays deleted."""
        self.kept_absent.add(path)
        self.warn_once("deleted:" + path,
                       "%s was deleted since apply; left deleted (%s)"
                       % (self.env.tilde(path), what))
        return path

    def _add(self, path, op):
        if path not in self.ops:
            self.order.append(path)
        self.ops[path] = op
        return path

    # writes (planned; the core commits them)
    def write_owned(self, path, text, meta=None):
        """A file appglass creates and owns: deleted on remove. An adopted
        file (``appglass adopt``) is owned too, and restored from its backup
        on remove.

        Raises Conflict when the path exists and is not appglass's.
        """
        path = os.path.abspath(path)
        self._check_other_owner(path)
        rec = self._record(path)
        if rec is None and os.path.lexists(path):
            raise Conflict("%s exists and is not appglass's (left untouched)" % path)
        if rec is not None and rec["kind"] != "created" and not rec.get("adopted"):
            raise Conflict("%s is a user file, not an appglass file" % path)
        if self.app.from_hook and self.deleted_since_apply(path):
            # the user deleted a file appglass owns: the theme hook must not
            # bring it back; a manual apply does
            return self._keep_deleted(path, "appglass apply writes it again")
        data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
        return self._add(path, Op("owned", data, meta=meta))

    # launcher overrides and artifacts
    def system_desktop(self, desktop_id):
        """Path of the system launcher desktop_id (XDG_DATA_DIRS and flatpak
        exports, $XDG_DATA_HOME left out), or None."""
        from . import detect
        for d in detect.data_dirs(self.env):
            if d == os.path.abspath(self.env.data_home):
                continue
            p = os.path.join(d, "applications", desktop_id)
            if os.path.isfile(p):
                return p
        return None

    def desktop_override(self, desktop_id, fn):
        """$XDG_DATA_HOME/applications/<desktop_id>, owned, generated as
        fn(system text) on every apply (so it follows package updates; the
        record keeps the source path and its sha256). Removed on remove.

        Returns the path, or None without a system launcher. Raises Conflict
        for a launcher the user made (``appglass adopt`` hands it over) and
        for a symlink.
        """
        dest = os.path.abspath(os.path.join(self.env.data_home, "applications", desktop_id))
        src = self.system_desktop(desktop_id)
        if src is None:
            return None
        if os.path.islink(dest):
            raise Conflict("%s is a symlink; left untouched" % self.env.tilde(dest))
        rec = self._record(dest)
        if rec is None and os.path.lexists(dest) and self.app.state.owner_of(dest) is None:
            raise Conflict("%s is a hand-made launcher (appglass adopt %s hands it to "
                           "appglass, backed up)" % (self.env.tilde(dest),
                                                     self.env.tilde(dest)))
        raw = _read(src)
        text = fn(raw.decode("utf-8", "replace"))
        return self.write_owned(dest, text, meta={"source": src, "source_sha256": sha(raw)})

    @property
    def cache_dir(self):
        """$XDG_CACHE_HOME/appglass/<owner>: where artifacts go."""
        return self.env.cache_path("appglass", self.owner)

    def artifact(self, name, build, stamp):
        """An owned file in cache_dir built by build() -> bytes. build runs
        only when the recorded stamp differs from stamp or the file changed
        (a built shim survives applies without a rebuild). Removed on remove."""
        path = os.path.abspath(os.path.join(self.cache_dir, name))
        rec = self._record(path)
        cur = _read(path)
        if (rec is not None and rec.get("meta", {}).get("stamp") == stamp
                and cur is not None and sha(cur) == rec.get("sha256")):
            data = cur
        else:
            data = build()
        return self.write_owned(path, data, meta={"artifact": True, "stamp": stamp})

    def edit_text(self, path, fn, undo=None):
        """Edit a user text file: fn(text) -> new text ('' when absent).

        The original bytes are backed up and restored byte-identical on
        remove. fn must be idempotent. On re-apply fn gets the original
        text again (so the result is identical), unless the user changed the
        file since, then fn gets the current text. undo(text) -> text is used
        on remove only when the file changed since apply.
        """
        path = os.path.abspath(path)
        self._check_other_owner(path)
        rec = self._record(path)
        if rec is not None and rec["kind"] == "created" and rec.get("how") != "edit":
            raise Conflict("%s is an appglass-owned file, not a user file" % path)
        if self.deleted_since_apply(path):
            # appglass wrote it and the user deleted it: an opt-out
            return self._keep_deleted(path, "remove + apply writes it again")
        cur = _read_planned(path) if path not in self.ops else self.ops[path].data
        base = cur
        if rec is not None and path not in self.ops:
            if (cur is not None and sha(cur) == rec["sha256"]
                    and not rec.get("app_rewrote")):
                # unchanged since our last write: rebuild from the original
                # (after a user change, the current text is the base for good)
                if rec["kind"] == "modified":
                    base = self.app.backup_bytes(rec)
                else:
                    base = None   # we created it: rebuild from empty
        if base is not None and os.path.lexists(path) and not os.path.isfile(path):
            raise Conflict("%s is not a regular file" % path)
        try:
            text = "" if base is None else base.decode("utf-8")
        except UnicodeDecodeError:
            raise Conflict("%s is not UTF-8 text" % path)
        new = fn(text)
        if not isinstance(new, str):
            raise AppglassError("edit fn for %s did not return text" % path)
        return self._add(path, Op("edit", new.encode("utf-8"), undo=undo))

    def merge_json(self, path, values):
        """Merge top-level keys into a JSON object file (other keys kept).

        Written in place (same inode). On remove the original bytes come
        back, or, if the app rewrote the file since, only our keys are put
        back to their original values.
        """
        path = os.path.abspath(path)
        self._check_other_owner(path)
        rec = self._record(path)
        if path not in self.ops and os.path.lexists(path) and not os.path.isfile(path):
            raise Conflict("%s is not a regular file (left untouched)" % path)
        if self.deleted_since_apply(path):
            return self._keep_deleted(path, "remove + apply writes it again")
        cur = _read_planned(path) if path not in self.ops else self.ops[path].data
        if cur is None or not cur.strip():
            obj = {}
        else:
            try:
                obj = json.loads(cur.decode("utf-8"))
            except ValueError:
                raise Conflict("%s is not valid JSON (left untouched)" % path)
            if not isinstance(obj, dict):
                raise Conflict("%s is not a JSON object (left untouched)" % path)
        keys = dict(rec.get("keys", {})) if rec else {}
        if path in self.ops and self.ops[path].keys:
            keys = dict(self.ops[path].keys)
        if path not in self.ops and self.changed_since_apply(path):
            # keys appglass set that the user (or the app) took out since:
            # an opt-out, so they stay out (the record keeps them for remove)
            out = sorted(k for k in values if "set" in keys.get(k, {}) and k not in obj)
            if out:
                self.warn_once("keys-out:" + path,
                               "%s no longer has %s since apply; kept without (remove + "
                               "apply puts them back)" % (self.env.tilde(path), ", ".join(out)))
                values = {k: v for k, v in values.items() if k not in out}
        for k, v in values.items():
            if k not in keys:
                keys[k] = {"present": k in obj, "value": obj.get(k)}
            # "set": the value we wrote; remove leaves a key the app changed
            keys[k] = dict(keys[k], set=v)
            obj[k] = v
        data = (json.dumps(obj, indent=2) + "\n").encode("utf-8")
        if cur is not None and cur.strip():
            try:
                if json.loads(cur.decode("utf-8")) == obj:
                    data = cur      # nothing to change: keep the bytes
            except ValueError:
                pass
        return self._add(path, Op("json", data, keys=keys))


# ---------------------------------------------------------------- families

def discover(warn=None):
    """Import every appglass/families/<name>.py; a broken module is skipped."""
    from . import families as pkg
    warn = warn or (lambda m: None)
    out = {}
    for m in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        if m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module("%s.%s" % (pkg.__name__, m.name))
        except Exception as ex:
            warn("family module %s failed to load: %s: %s" % (m.name, type(ex).__name__, ex))
            continue
        missing = [a for a in ("NAME", "APP_IDS", "installed", "apply") if not hasattr(mod, a)]
        if missing:
            warn("family module %s skipped: lacks %s" % (m.name, ", ".join(missing)))
            continue
        if mod.NAME in out or mod.NAME in CORE_OWNERS:
            warn("family module %s skipped: duplicate name %s" % (m.name, mod.NAME))
            continue
        out[mod.NAME] = mod
    return out


# ---------------------------------------------------------------- app

class App:
    def __init__(self, environ=None, out=None, err=None, quiet=False):
        self.env = Env(environ)
        self.out = out or sys.stdout
        self.err = err or sys.stderr
        self.quiet = quiet
        self.from_hook = False      # apply --from-hook (the matugen post_hook)
        self.dry_run = False
        from . import settings as _settings
        self.settings, self.settings_error = _settings.load(self.env)
        if self.settings_error:
            self.warn("settings ignored (defaults used): %s" % self.settings_error)
        self.palette = Palette(self.env, warn=self.warn)
        self.levels = Levels.from_env(self.env, self.settings)
        self.state = State(self.env)
        self.errors = 0
        self.families = discover(warn=self.warn)

    # output
    def info(self, msg):
        if not self.quiet:
            print(msg, file=self.out)

    def warn(self, msg):
        print("appglass: warning: %s" % msg, file=self.err)

    def error(self, msg):
        self.errors += 1
        print("appglass: error: %s" % msg, file=self.err)

    def installed(self, fam):
        if fam.NAME in self.env.assume_not_installed:
            return False
        if fam.NAME in self.env.assume_installed:
            return True
        try:
            return bool(fam.installed(self.env))
        except Exception as ex:  # detection must never break apply
            self.warn("%s: install check failed: %s" % (fam.NAME, ex))
            return False

    def ctx(self, owner):
        return Ctx(self, owner)

    def backup_dir(self):
        return os.path.join(self.env.state_dir, "backup")

    def backup_bytes(self, rec):
        p = os.path.join(self.env.state_dir, rec["backup"])
        b = _read(p)
        if b is None:
            raise AppglassError("backup %s is missing" % p)
        return b

    def backup(self, p, cur):
        """Save cur (p's bytes) in the state backup dir: {"backup", "orig_sha256"}."""
        env, st = self.env, self.state
        bname = hashlib.sha1(p.encode()).hexdigest()[:16] + ".orig"
        bpath = os.path.join(self.backup_dir(), bname)
        env.guard(bpath)
        if not os.path.isdir(self.backup_dir()):
            st.save()  # creates the state dir (records created parents)
            os.makedirs(self.backup_dir(), exist_ok=True)
        with open(bpath, "wb") as f:
            f.write(cur)
        return {"backup": os.path.join("backup", bname), "orig_sha256": sha(cur)}

    # ---- commit
    def commit(self, ctx, app_ids=None, dry_run=False):
        """Write a ctx's plan; revert files this owner had but no longer plans."""
        env, st = self.env, self.state
        owner = st.owners.get(ctx.owner, {"files": {}, "dirs": []})
        stale = [p for p in owner.get("files", {})
                 if p not in ctx.ops and p not in ctx.kept_absent]
        # guard everything before the first byte is written
        for p in list(ctx.ops) + stale:
            env.guard(p)
            for d in _missing_dirs(os.path.dirname(p)):
                env.guard(d)
        env.guard(st.path)
        changed = []
        if dry_run:
            for p in ctx.order:
                cur = _read(p)
                if cur != ctx.ops[p].data:
                    changed.append(p)
            return changed
        for p in stale:
            self._revert(ctx.owner, p, owner["files"][p])
            self._drop_backup(owner["files"].pop(p))
        for p in ctx.kept_absent:
            rec = owner["files"].get(p)
            if rec is not None and rec.get("how") in ("edit", "json"):
                # sticky: if the file comes back, it is the user's
                rec["app_rewrote"] = True
        st.owners[ctx.owner] = owner
        if ctx.once:
            owner["warned"] = sorted(ctx.once)
        else:
            owner.pop("warned", None)
        if app_ids is not None:
            owner["app_ids"] = list(app_ids)
        for p in ctx.order:
            op = ctx.ops[p]
            rec = owner["files"].get(p)
            cur = _read(p)
            for d in _missing_dirs(os.path.dirname(p)):
                os.mkdir(d)
                owner.setdefault("dirs", []).append(d)
            if rec is None:
                if cur is None:
                    rec = {"kind": "created", "how": "owned" if op.kind == "owned" else op.kind}
                else:
                    if op.kind == "owned":
                        raise Conflict("%s appeared during apply" % p)
                    rec = dict(self.backup(p, cur), kind="modified", how=op.kind)
            elif (rec.get("how") in ("json", "edit") and cur is not None
                  and sha(cur) != rec.get("sha256")):
                # the app or the user rewrote the file since the last apply:
                # the backup no longer holds their changes, so remove must
                # strip only ours (json keys / the owner's undo; sticky)
                rec["app_rewrote"] = True
            if op.keys is not None:
                rec["keys"] = op.keys
            if op.meta:
                rec["meta"] = op.meta
            else:
                rec.pop("meta", None)
            if (rec["kind"] == "created" and rec.get("how") == "edit"
                    and not rec.get("app_rewrote")):
                # built from empty: what the owner's undo leaves of it is not
                # the user's, so a remove that ends there deletes the file
                pristine = self._pristine(ctx.owner, p, op)
                if pristine is None:
                    rec.pop("pristine_sha256", None)
                else:
                    rec["pristine_sha256"] = pristine
            if cur != op.data:
                if op.kind == "owned":
                    _atomic_write(p, op.data)
                else:
                    _inplace_write(p, op.data)
                changed.append(p)
            rec["sha256"] = sha(op.data)
            owner["files"][p] = rec
            st.save()
        st.save()
        return changed

    def _revert(self, owner_name, p, rec):
        env = self.env
        env.guard(p)
        if os.path.lexists(p) and not os.path.isfile(p):
            self.warn("%s is no longer a regular file; left as is" % p)
            return
        try:
            cur = _read(p)
        except OSError as ex:
            self.warn("%s cannot be read (%s); left as is"
                      % (p, ex.strerror or type(ex).__name__))
            return
        if cur is None and rec["kind"] == "modified":
            # the user deleted a file appglass had edited: an opt-out, so the
            # backup is not put back (it is dropped with the record)
            self.warn("%s was deleted since apply; left deleted" % p)
            return
        diverged = cur is not None and (sha(cur) != rec.get("sha256")
                                        or bool(rec.get("app_rewrote")))
        if rec["kind"] == "created":
            if cur is None:
                return
            if rec.get("how") == "owned" or not diverged:
                os.remove(p)
                return
            if rec.get("how") == "json":
                try:
                    obj = _unmerge_json(cur, rec.get("keys", {}))
                    if not obj:
                        os.remove(p)
                    elif obj != json.loads(cur.decode("utf-8")):
                        _inplace_write(p, (json.dumps(obj, indent=2) + "\n").encode())
                    return    # (none of ours left in it: their bytes kept)
                except (ValueError, AttributeError):
                    pass
            # a file we created by editing, changed since by the user: take
            # our part out with the owner's undo; delete the file when nothing
            # of the user's is left
            undo = self._undo_for(owner_name, p)
            if undo is not None:
                try:
                    rest = undo(cur.decode("utf-8")).encode("utf-8")
                except Exception as ex:
                    self.warn("%s: undo failed (%s); kept as is" % (p, ex))
                    return
                if not rest.strip() or sha(rest.strip()) == rec.get("pristine_sha256"):
                    os.remove(p)
                    return
                _inplace_write(p, rest)
                self.warn("%s changed since appglass created it; appglass parts "
                          "removed, your changes kept" % p)
                return
            self.warn("%s changed since appglass created it; kept as is" % p)
            return
        orig = self.backup_bytes(rec)
        if not diverged:
            _inplace_write(p, orig)
            return
        if rec.get("how") == "json":
            try:
                obj = _unmerge_json(cur, rec.get("keys", {}))
                try:
                    same = json.loads(orig.decode("utf-8")) == obj
                except ValueError:
                    same = False
                # nothing of the app's left: the original bytes, else the
                # merge (none of ours left in it: their bytes kept)
                if same:
                    _inplace_write(p, orig)
                elif obj != json.loads(cur.decode("utf-8")):
                    _inplace_write(p, (json.dumps(obj, indent=2) + "\n").encode())
                return
            except (ValueError, AttributeError):
                pass
        # an adopted file is ours whole: no undo, the user's version is saved aside
        undo = None if rec.get("how") == "owned" else self._undo_for(owner_name, p)
        if undo is not None:
            try:
                _inplace_write(p, undo(cur.decode("utf-8")).encode("utf-8"))
                self.warn("%s changed since apply; appglass parts removed, your changes kept" % p)
                return
            except Exception as ex:
                self.warn("%s: undo failed (%s); restoring the original" % (p, ex))
        keep = p + ".appglass-changed"
        env.guard(keep)
        with open(keep, "wb") as f:
            f.write(cur)
        _inplace_write(p, orig)
        self.warn("%s changed since apply; original restored, your version saved as %s" % (p, keep))

    def _pristine(self, owner_name, path, op):
        """sha256 of what the undo leaves of op.data, outer whitespace
        stripped (None without an undo)."""
        undo = op.undo or self._undo_for(owner_name, path)
        if undo is None:
            return None
        try:
            return sha(undo(op.data.decode("utf-8")).encode("utf-8").strip())
        except Exception:
            return None

    def _undo_for(self, owner_name, path):
        """Ask the owner for an undo fn (families/core expose undo(path) optionally)."""
        if owner_name == "niri":
            from . import niri
            return niri.undo_for(self, path)
        if owner_name == "hook":
            from . import hook
            return hook.undo_for(self, path)
        fam = self.families.get(owner_name)
        fn = getattr(fam, "undo", None) if fam else None
        if fn is None:
            return None
        return lambda text: fn(self.env, path, text)

    def _drop_backup(self, rec):
        """Delete rec's backup/*.orig once no record refers to it."""
        b = rec.get("backup")
        if not b:
            return
        for o in self.state.owners.values():
            for r in o.get("files", {}).values():
                if r is not rec and r.get("backup") == b:
                    return
        p = os.path.join(self.env.state_dir, b)
        self.env.guard(p)
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        try:
            os.rmdir(self.backup_dir())
        except OSError:
            pass

    def remove_owner(self, name):
        owner = self.state.owners.get(name)
        if not owner:
            return False
        for p in list(owner.get("files", {})):
            self.env.guard(p)
        for p, rec in list(owner.get("files", {}).items()):
            self._revert(name, p, rec)
            self._drop_backup(owner["files"].pop(p))
            self.state.save()
        for d in sorted(owner.get("dirs", []), key=len, reverse=True):
            try:
                os.rmdir(d)
            except OSError:
                pass
        del self.state.owners[name]
        self.state.save()
        return True

    def finish(self):
        """Drop the state dir once nothing is owned any more."""
        if not self.state.owners:
            self.state.destroy()

    # ---- niri sync
    def sync_niri(self, dry_run=False, extra_ids=()):
        from . import niri
        return niri.sync(self, dry_run=dry_run, extra_ids=extra_ids)


# ---------------------------------------------------------------- commands

def _lock(env):
    d = env.state_dir
    for p in _missing_dirs(d):
        env.guard(p)
    env.guard(os.path.join(d, ".lock"))
    created = _missing_dirs(d)
    os.makedirs(d, exist_ok=True)
    f = open(os.path.join(d, ".lock"), "a")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f, created


def _unlock(env, lockf, created, app):
    try:
        lockf.close()
    except OSError:
        pass
    if app is None:
        # startup failed (e.g. unreadable state): touch nothing but our own lock
        if created:
            try:
                os.remove(os.path.join(env.state_dir, ".lock"))
            except OSError:
                pass
            for p in sorted(created, key=len, reverse=True):
                try:
                    os.rmdir(p)
                except OSError:
                    pass
        return
    st = app.state
    if st is not None and st.owners:
        if created and not st.data.get("state_parents"):
            st.data["state_parents"] = created
            st.save()
        return
    d = env.state_dir
    if os.path.isdir(d):
        # nothing owned: the dir only holds the lock (or a stale colors.json)
        shutil.rmtree(d)
    for p in sorted(set(created) | set(st.data.get("state_parents", [])),
                    key=len, reverse=True):
        if p == d:
            continue
        try:
            os.rmdir(p)
        except OSError:
            pass


def _selected(app, only):
    if not only:
        return sorted(app.families)
    names = _split(only)
    bad = [n for n in names if n not in app.families]
    if bad:
        raise AppglassError("unknown family: %s (known: %s)"
                            % (", ".join(bad), ", ".join(sorted(app.families))))
    return names


def _family_enabled(app, name):
    from . import settings as _settings
    return _settings.app_enabled(app.settings, name, True)


def cmd_apply(app, only=None, dry_run=False, from_hook=False):
    app.from_hook = from_hook
    app.dry_run = dry_run
    if app.settings_error and not from_hook:
        raise AppglassError("settings.json is invalid (%s); fix it with appglass set, "
                            "or delete it for the defaults" % app.settings_error)
    if not app.settings.get("enabled", True):
        app.info("glass is off in settings.json (enabled false): nothing applied "
                 "(appglass remove takes the files out)")
        return
    if from_hook:
        # the matugen post_hook: refresh only what the user applied (state.json),
        # never bring back a family that was never applied or was removed
        names = [n for n in app.state.families() if n in app.families]
        for n in app.state.families():
            if n not in app.families:
                app.warn("%s: recorded in state.json but its module is missing; "
                         "left as is" % n)
        if not names:
            app.info("nothing applied yet: nothing to refresh")
            return
    else:
        names = _selected(app, only)
    planned = []
    for name in names:
        fam = app.families[name]
        why = None
        if not app.installed(fam):
            why = "not installed"
        elif not _family_enabled(app, name):
            why = "off in settings"
        if why:
            if name in app.state.owners:
                if dry_run:
                    app.info("%s: %s, would remove its files" % (name, why))
                else:
                    app.remove_owner(name)
                    app.info("%s: %s, files removed" % (name, why))
            else:
                app.info("%s: %s, skipped" % (name, why))
            continue
        ctx = app.ctx(name)
        try:
            try:
                fam.apply(ctx)
            finally:
                # the reasons a family gives before it skips are worth showing
                for m in ctx.messages:
                    app.warn("%s: %s" % (name, m))
            ids = list(fam.APP_IDS if ctx.app_ids is None else ctx.app_ids)
            changed = app.commit(ctx, app_ids=ids, dry_run=dry_run)
        except SandboxViolation:
            raise
        except Conflict as ex:
            app.warn("%s: skipped: %s" % (name, ex))
            continue
        except Exception as ex:
            app.error("%s: %s: %s" % (name, type(ex).__name__, ex))
            continue
        if dry_run:
            planned.extend(ids)
        verb = "would write" if dry_run else "wrote"
        if changed:
            app.info("%s: %s %s" % (name, verb, ", ".join(changed)))
        else:
            app.info("%s: up to date" % name)
    app.sync_niri(dry_run=dry_run, extra_ids=planned)
    if not from_hook:
        warn_hand_files(app)


def cmd_remove(app, only=None):
    if only:
        for name in _selected(app, only):
            if app.remove_owner(name):
                app.info("%s: removed" % name)
        app.sync_niri()
        return
    if "niri" in app.state.owners:
        app.remove_owner("niri")
        app.info("niri: removed")
    for name in app.state.families():
        app.remove_owner(name)
        app.info("%s: removed" % name)
    if "hook" in app.state.owners:
        app.remove_owner("hook")
        app.info("hook: removed")
    from . import learn
    if learn.forget(app.env):
        app.info("learned: cache removed")


def cmd_status(app):
    env, st = app.env, app.state
    p = app.info
    p("sandbox:  %s" % (env.sandbox or "-"))
    p("colours:  %s (%s)" % (app.palette.source or "none", app.palette.mode))
    lv = app.levels
    p("levels:   content %.2f (%d)  bars %.2f (%d)  popups 1.0 (255)"
      % (lv.content, lv.content8, lv.bar, lv.bar8))
    for name in sorted(app.families):
        fam = app.families[name]
        inst = "installed" if app.installed(fam) else "not installed"
        o = st.owners.get(name)
        if o:
            files = ", ".join(sorted(o.get("files", {})))
            p("%-10s %s, applied: %s" % (name, inst, files))
        else:
            p("%-10s %s, not applied" % (name, inst))
    for name in CORE_OWNERS:
        o = st.owners.get(name)
        p("%-10s %s" % (name, ("applied: " + ", ".join(sorted(o["files"]))) if o else "not applied"))
    try:
        routes = app_routes(app)
    except Exception as ex:  # status must not die on a detection bug
        app.warn("detect failed: %s" % ex)
        routes = []
    if routes:
        p("apps:")
        for r, route in routes:
            p("  %-34s %-12s %-16s %-9s %s" % (r["key"][:34], r["toolkit"], route["adapter"],
                                             route["effective"], route["reason"]))
    for h in hand_files(app):
        if h["status"] != "absent":
            p("hand file %s: %s (%s)" % (h["path"], h["status"], h["adapter"] or "no adapter"))


def app_routes(app, records=None):
    """[(record, route)] for every installed, shown app: route = adapters.resolve()."""
    from . import adapters
    records = detected(app) if records is None else records
    out = []
    for r in records:
        if not r.get("installed") or r.get("nodisplay"):
            continue
        route = adapters.resolve(r, app.families, app.settings)
        fam = route.get("family")
        if fam and route["effective"] == "glass" and not app.installed(app.families[fam]):
            route.update(effective="fallback", reason="family %s: not installed" % fam)
        out.append((r, route))
    return out


def hand_files(app):
    """The hand-made files appglass knows: [{path, adapter, what, exists,
    status}] with status adopted | owned | conflict | absent."""
    from . import adapters
    env, st = app.env, app.state
    out = []
    for rel, adapter, what in adapters.HAND_FILES:
        p = os.path.join(env.home, rel)
        owner = st.owner_of(p)
        rec = st.owners.get(owner, {}).get("files", {}).get(p) if owner else None
        if rec and rec.get("adopted"):
            status = "adopted"
        elif owner:
            status = "owned"
        elif os.path.lexists(p):
            status = "conflict"
        else:
            status = "absent"
        impl = bool(adapter) and adapters.BY_NAME[adapter].implemented
        out.append({"path": env.tilde(p), "adapter": adapter, "what": what,
                    "implemented": impl, "owner": owner, "status": status})
    return out


def status_doc(app):
    from . import adapters
    st, lv = app.state, app.levels
    fams = {}
    for name in sorted(app.families):
        o = st.owners.get(name)
        fams[name] = {"installed": app.installed(app.families[name]),
                      "enabled": _family_enabled(app, name),
                      "applied": sorted(app.env.tilde(f) for f in o.get("files", {})) if o else []}
    core_owners = {n: sorted(app.env.tilde(f) for f in st.owners[n]["files"])
                   if n in st.owners else [] for n in CORE_OWNERS}
    apps = []
    counts = {}
    for r, route in app_routes(app):
        counts[route["effective"]] = counts.get(route["effective"], 0) + 1
        apps.append(dict({"key": r["key"], "name": r["name"], "toolkit": r["toolkit"],
                          "app_ids": r["app_ids"], "source": r.get("source", "desktop")},
                         **route))
    return {
        "version": 1,
        "enabled": app.settings["enabled"],
        "settings_error": app.settings_error,
        "levels": {"content": lv.content, "bar": lv.bar},
        "fallback": app.settings["fallback"],
        "families": fams,
        "core": core_owners,
        "apps": apps,
        "summary": dict(sorted(counts.items())),
        "hand_files": hand_files(app),
        "adapters": [a.as_dict() for a in adapters.CATALOGUE],
    }


def cmd_get(app, key=None):
    from . import settings as _settings
    try:
        v = _settings.get_key(app.settings, key or "")
    except _settings.SettingsError as ex:
        raise AppglassError("get: %s" % ex)
    print(json.dumps(v, indent=2, sort_keys=True), file=app.out)


def _refuse_if_plugin(app):
    from . import settings as _settings
    if _settings.plugin_active(app.env):
        raise AppglassError("settings are managed by the DMS plugin appGlass (%s): "
                            "change them in DMS Settings > Plugins > appGlass"
                            % app.env.tilde(_settings.plugin_dir(app.env)))


def cmd_set(app, key, value, apply_after=False):
    from . import settings as _settings
    _refuse_if_plugin(app)
    if app.settings_error:
        raise AppglassError("settings.json is invalid (%s); delete it to start "
                            "from the defaults" % app.settings_error)
    try:
        new = _settings.set_key(app.settings, key, _settings.parse_value(value))
    except _settings.SettingsError as ex:
        raise AppglassError("set %s: %s" % (key, ex))
    changed = _settings.save(app.env, new)
    _reload_settings(app, new)
    app.info("%s = %s%s" % (key, json.dumps(_settings.get_key(new, key)),
                            "" if changed else " (unchanged)"))
    if apply_after:
        cmd_apply_all(app)


def _reload_settings(app, s):
    app.settings, app.settings_error = s, None
    app.levels = Levels.from_env(app.env, s)


def cmd_sync(app, settings_file, dry_run=False):
    """The DMS plugin's call: validate the full settings, save, apply."""
    from . import settings as _settings
    try:
        with open(settings_file, "rb") as f:
            obj = json.loads(f.read().decode("utf-8"))
        new = _settings.validate(obj)
    except FileNotFoundError:
        raise AppglassError("sync: %s not found" % settings_file)
    except (ValueError, UnicodeDecodeError) as ex:
        raise AppglassError("sync: %s rejected, nothing saved: %s" % (settings_file, ex))
    if dry_run:
        app.info("settings: would save %s" % app.env.tilde(_settings.path(app.env)))
    else:
        if _settings.save(app.env, new):
            app.info("settings: saved %s" % app.env.tilde(_settings.path(app.env)))
    _reload_settings(app, new)
    if not new["enabled"]:
        if dry_run:
            app.info("glass off: would remove every appglass file")
        else:
            cmd_remove(app)
        return
    cmd_apply_all(app, dry_run=dry_run)


def adopt_owner(app, adapter):
    """The owner name that takes a hand file of adapter, or None."""
    from . import adapters
    a = adapters.BY_NAME.get(adapter) if adapter else None
    if a is None:
        return None
    if a.NAME == "niri-fallback":
        return "niri"
    if a.FAMILY and a.FAMILY in app.families:
        return a.FAMILY
    return None


def adopt_path(app, p, owner):
    """Record p (a regular file) as owner's, backed up: an owned file that
    remove restores byte-identical."""
    env, st = app.env, app.state
    p = os.path.abspath(p)
    other = st.owner_of(p)
    if other is not None:
        raise Conflict("%s is managed by appglass '%s'" % (env.tilde(p), other))
    if os.path.islink(p) or not os.path.isfile(p):
        raise Conflict("%s is not a regular file" % env.tilde(p))
    env.guard(p)
    env.guard(st.path)
    cur = _read(p)
    o = st.owners.setdefault(owner, {"files": {}, "dirs": []})
    o.setdefault("files", {})[p] = dict(app.backup(p, cur), kind="modified", how="owned",
                                       sha256=sha(cur), adopted=True)
    st.save()
    return p


def cmd_adopt(app, paths=None, dry_run=False):
    """Hand the known hand-made files to appglass: each is backed up and
    recorded as its owner's (restored byte-identical on remove); the owner
    regenerates it on the next apply. Returns the adopted paths."""
    env, st = app.env, app.state
    from . import adapters
    known = {os.path.join(env.home, rel): h
             for (rel, _, _), h in zip(adapters.HAND_FILES, hand_files(app))}
    if paths:
        todo = []
        for p in paths:
            ap = os.path.join(env.home, p[2:]) if p.startswith("~/") else os.path.abspath(p)
            if ap not in known:
                raise AppglassError("adopt: %s is not a hand-made file appglass knows "
                                    "(appglass status lists them)" % env.tilde(ap))
            todo.append(ap)
    else:
        todo = [p for p, h in sorted(known.items()) if h["status"] == "conflict"]
    done = []
    verb = "would adopt" if dry_run else "adopted"
    for p in todo:
        h = known[p]
        t = env.tilde(p)
        if h["status"] in ("adopted", "owned"):
            app.info("adopt: %s is already appglass's (%s)" % (t, h["owner"]))
            continue
        if h["status"] == "absent":
            app.info("adopt: %s does not exist" % t)
            continue
        owner = adopt_owner(app, h["adapter"])
        if owner is None:
            app.warn("adopt: %s: its owner (%s) is not implemented yet; left as is"
                     % (t, h["adapter"] or "no adapter"))
            continue
        if os.path.islink(p) or not os.path.isfile(p):
            app.warn("adopt: %s is not a regular file; left as is" % t)
            continue
        if dry_run:
            app.info("adopt: %s %s (owner %s, original backed up)" % (verb, t, owner))
            done.append(p)
            continue
        adopt_path(app, p, owner)
        app.info("adopt: %s %s (owner %s, original backed up)" % (verb, t, owner))
        done.append(p)
    return done


def warn_hand_files(app):
    if getattr(app, "hand_files_reported", False):
        return          # apply --all --adopt said it per file already
    for h in hand_files(app):
        if h["status"] != "conflict":
            continue
        if adopt_owner(app, h["adapter"]):
            app.warn("%s is a hand-made file (%s); appglass leaves it alone until "
                     "appglass adopt %s" % (h["path"], h["what"], h["path"]))
        else:
            app.warn("%s is a hand-made file (%s); its owner (%s) is not implemented "
                     "yet, left alone" % (h["path"], h["what"], h["adapter"] or "none"))


def cmd_apply_all(app, dry_run=False, adopt=False):
    """apply for every detected app with a working adapter: the families,
    the niri fallback (detected fallback apps get the value-mode block) and
    games (opaque); hand files adopted first with --adopt."""
    from . import niri
    if app.settings_error:
        raise AppglassError("settings.json is invalid (%s)" % app.settings_error)
    routes = app_routes(app)
    fb, games = [], []
    for r, route in routes:
        if route["effective"] == "fallback":
            fb.extend(x for x in r["app_ids"] if x not in fb)
        elif route["effective"] == "opaque":
            games.extend(x for x in r["app_ids"]
                         if x not in games and not niri.is_game_id(x))
    app.fallback_ids, app.game_ids = fb, games
    counts = {}
    for r, route in routes:
        counts[route["effective"]] = counts.get(route["effective"], 0) + 1
    app.info("apps: %s" % ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items())))
    for r, route in routes:
        app.info("  %-34s %-12s %-16s %-9s %s" % (r["key"][:34], r["toolkit"], route["adapter"],
                                                route["effective"], route["reason"]))
    would = []
    if adopt:
        would = cmd_adopt(app, None, dry_run=dry_run)
        app.hand_files_reported = True
    cmd_apply(app, dry_run=dry_run)
    if dry_run:
        for p in would:
            app.info("niri: would write %s (a comment stub; its rules are in appglass.kdl)"
                     % app.env.tilde(p))


def detected(app):
    """detect records with the learned cache and the open windows merged in."""
    from . import detect, learn
    recs = detect.scan(app.env)
    learned = learn.load(app.env)
    live = learn.learn(app.env)
    if live:
        learned.update(live)
    return learn.merge(recs, learned)


def cmd_learn(app, as_json=False, dry_run=False):
    from . import learn
    found = learn.learn(app.env)
    if found is None:
        raise AppglassError("learn: no niri session (niri msg -j windows failed)")
    if as_json:
        print(json.dumps(found, indent=2, sort_keys=True), file=app.out)
    else:
        for app_id in sorted(found):
            r = found[app_id]
            app.info("%-36s %-13s %s" % (app_id[:36], r["toolkit"],
                                         (r["evidence"] or ["no toolkit library mapped"])[0]))
    if dry_run or as_json:
        return
    p = learn.save(app.env, found)
    app.info("learned %d window%s: %s" % (len(found), "" if len(found) == 1 else "s",
                                         app.env.tilde(p)))


def cmd_detect(app, as_json=False):
    recs = detected(app)
    if as_json:
        print(json.dumps(recs, indent=2, sort_keys=True), file=app.out)
        return
    for r in recs:
        if r["nodisplay"] or not r["installed"]:
            continue
        print("%-36s %-13s %s" % (r["key"][:36], r["toolkit"],
                                  (r["evidence"] or ["no evidence"])[0]), file=app.out)


def main(argv=None, environ=None, out=None, err=None):
    ap = argparse.ArgumentParser(prog="appglass",
                                 description="Glass for desktop apps on niri + DMS.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("apply", help="write the glass files for installed apps")
    scope = a.add_mutually_exclusive_group()
    scope.add_argument("--only", help="comma-separated family names")
    scope.add_argument("--from-hook", action="store_true",
                       help="re-apply only the families already applied (the "
                            "matugen post_hook runs this on every theme change)")
    scope.add_argument("--all", action="store_true",
                       help="every detected app with a working adapter (families, "
                            "niri fallback, games)")
    a.add_argument("--adopt", action="store_true",
                   help="with --all: adopt the known hand-made files first")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--quiet", action="store_true")
    ad = sub.add_parser("adopt", help="hand known hand-made files to appglass (backed up)")
    ad.add_argument("paths", nargs="*", help="files to adopt (default: every one appglass "
                                             "has an owner for)")
    ad.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("remove", help="restore every file appglass touched")
    r.add_argument("--only", help="comma-separated family names")
    sp = sub.add_parser("status", help="show colours, levels, applied families and app routes")
    sp.add_argument("--json", action="store_true", help="machine-readable status")
    sub.add_parser("levels", help="print the current levels as JSON")
    h = sub.add_parser("hook", help="matugen hook: re-apply on every DMS theme change")
    h.add_argument("action", choices=("install", "remove"))
    d = sub.add_parser("detect", help="which toolkit draws each installed app (read-only)")
    d.add_argument("--json", action="store_true")
    lr = sub.add_parser("learn", help="record the toolkit of each open window (niri + /proc)")
    lr.add_argument("--json", action="store_true", help="print, do not save")
    lr.add_argument("--dry-run", action="store_true")
    g = sub.add_parser("get", help="print settings.json (or one dotted key) as JSON")
    g.add_argument("key", nargs="?")
    s_ = sub.add_parser("set", help="change one setting (refused while the DMS plugin "
                                    "manages them)")
    s_.add_argument("key", help="dotted key, e.g. fallback.mode or apps.steam.enabled")
    s_.add_argument("value", help="JSON value (true, 0.7, null) or a bare string")
    s_.add_argument("--apply", action="store_true", help="apply --all afterwards")
    y = sub.add_parser("sync", help="validate, save and apply full settings (the DMS "
                                    "plugin's call)")
    y.add_argument("--settings-file", required=True)
    y.add_argument("--dry-run", action="store_true")
    y.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    err = err or sys.stderr
    quiet = getattr(args, "quiet", False)
    app = None
    lockf = None
    created = []
    try:
        env = Env(environ)
        if (args.cmd in ("apply", "remove", "hook", "set", "sync", "learn", "adopt")
                and not getattr(args, "dry_run", False) and not getattr(args, "json", False)):
            lockf, created = _lock(env)
        app = App(environ, out=out, err=err, quiet=quiet)
        if args.cmd == "apply" and args.all:
            cmd_apply_all(app, dry_run=args.dry_run, adopt=args.adopt)
        elif args.cmd == "apply":
            if args.adopt:
                raise AppglassError("apply: --adopt goes with --all")
            cmd_apply(app, args.only, args.dry_run, from_hook=args.from_hook)
        elif args.cmd == "adopt":
            cmd_adopt(app, args.paths, dry_run=args.dry_run)
        elif args.cmd == "remove":
            cmd_remove(app, args.only)
        elif args.cmd == "status":
            if args.json:
                print(json.dumps(status_doc(app), indent=2, sort_keys=True), file=app.out)
            else:
                cmd_status(app)
        elif args.cmd == "levels":
            print(json.dumps(app.levels.as_dict()), file=app.out if hasattr(app, "out") and app.out else sys.stdout)
        elif args.cmd == "detect":
            cmd_detect(app, as_json=args.json)
        elif args.cmd == "learn":
            cmd_learn(app, as_json=args.json, dry_run=args.dry_run)
        elif args.cmd == "get":
            cmd_get(app, args.key)
        elif args.cmd == "set":
            cmd_set(app, args.key, args.value, apply_after=args.apply)
        elif args.cmd == "sync":
            cmd_sync(app, args.settings_file, dry_run=args.dry_run)
        elif args.cmd == "hook":
            from . import hook
            if args.action == "install":
                hook.install(app)
            else:
                hook.remove(app)
        if lockf is not None:
            _unlock(env, lockf, created, app)
            lockf = None
        return 1 if app.errors else 0
    except AppglassError as ex:
        print("appglass: %s" % ex, file=err)
        return ex.exit_code
    except OSError as ex:
        if ex.errno in (errno.EACCES, errno.EROFS, errno.EPERM):
            print("appglass: %s" % ex, file=err)
            return 1
        raise
    finally:
        if lockf is not None:
            try:
                _unlock(Env(environ), lockf, created, app)
            except AppglassError:
                pass
