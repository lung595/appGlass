"""Shared pieces of the native terminal and app-config families (foot, kitty,
ghostty, wezterm, konsole, mpv, zed, kate): where the app reads its config
(native and flatpak) and the DMS terminal palette made readable on glass.

Not a family (the leading underscore keeps it out of discovery).

Targets: a native install reads $XDG_CONFIG_HOME / $XDG_DATA_HOME; a flatpak
reads ~/.var/app/<id>/config and ~/.var/app/<id>/data (flatpak sets the XDG
dirs there), and that is a path the sandbox sees at the same place, so a file
there may include another one by its absolute path. A family writes the same
files into every target that is installed.

Palette: the 16 DMS terminal colours (the hook's dank16term, else dank16) with
black / magenta / bright black from outline / tertiary / on_surface_variant
(dank16term's are unreadable on glass, docs/terminal.md), then every text
colour moved toward white (dark glass) or black (light glass) until it reaches
2.25:1 on the glass over any backdrop, as for Alacritty and Herdr.
"""

import os

from ..core import hex_to_rgb, norm_hex, readable

TARGET = 2.25
ANSI_ROLES = {0: "outline", 5: "tertiary", 8: "on_surface_variant"}
_FALLBACK = ("outline", "error", "tertiary", "secondary", "primary", "tertiary",
             "secondary", "on_surface")


class Target:
    """One place an app reads its config from."""

    def __init__(self, kind, config, data, app_id=None):
        self.kind, self.config, self.data, self.app_id = kind, config, data, app_id

    def config_path(self, *p):
        return os.path.join(self.config, *p)

    def data_path(self, *p):
        return os.path.join(self.data, *p)

    def __repr__(self):
        return "Target(%s, %s)" % (self.kind, self.config)


def var_app(env, app_id, *p):
    return env.home_path(".var", "app", app_id, *p)


def flatpak_installed(env, app_id):
    from .. import detect
    return app_id is not None and detect.flatpak_app(env, app_id) is not None


def targets(env, cmds=(), flatpak=None):
    """The installed targets: native when one of cmds is on PATH, flatpak when
    the app id is installed (user or system)."""
    out = []
    if any(env.which(c) for c in cmds):
        out.append(Target("native", env.config_home, env.data_home))
    if flatpak and flatpak_installed(env, flatpak):
        out.append(Target("flatpak", var_app(env, flatpak, "config"),
                          var_app(env, flatpak, "data"), flatpak))
    return out


def term16(ctx):
    t16, _ = ctx.term16
    return t16 or ctx.dank16


def palette(ctx, bg_role="surface"):
    """{"background", "foreground", "cursor", "cursor_text", "selection_bg",
    "selection_fg", "ansi": [16]} as #rrggbb, text readable on the glass."""
    lv = ctx.levels
    bg = norm_hex(ctx.colors(bg_role))

    def text(c):
        return readable(norm_hex(c), bg, lv.content, TARGET)

    t16 = term16(ctx)
    ansi = []
    for i in range(16):
        role = ANSI_ROLES.get(i)
        if role:
            c = ctx.colors(role)
        elif t16:
            c = t16[i]
        else:
            c = ctx.colors(_FALLBACK[i % 8])
        ansi.append(text(c))
    return {
        "background": bg,
        "foreground": text(ctx.colors("on_surface")),
        "cursor": norm_hex(ctx.colors("primary")),
        "cursor_text": bg,
        "selection_bg": norm_hex(ctx.colors("primary_container")),
        "selection_fg": norm_hex(ctx.colors("on_primary_container")),
        "ansi": ansi,
    }


def rgb_csv(h):
    return "%d,%d,%d" % hex_to_rgb(h)


def a2(v):
    """0.8 -> '0.80'; 0.125 -> '0.125'."""
    s = ("%.3f" % v).rstrip("0")
    whole, frac = s.split(".")
    return "%s.%s" % (whole, frac.ljust(2, "0"))


def header(comment, what):
    return [comment + " appglass: %s. Generated, do not edit: rewritten by" % what,
            comment + " appglass apply (and by the matugen hook on every DMS theme change)."]


# ---------------------------------------------------------------- line edits

def has_line(text, line):
    return any(ln.rstrip("\n") == line for ln in text.splitlines())


def drop_lines(text, pred):
    return "".join(ln for ln in text.splitlines(keepends=True) if not pred(ln.rstrip("\n")))


def append_line(text, line):
    """text with line at the end (once)."""
    if has_line(text, line):
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + line + "\n"


# ---------------------------------------------------------------- KConfig / INI

def _ini_sec(line):
    s = line.strip()
    if s.startswith("[") and s.endswith("]"):
        return s[1:-1]
    return None


def ini_get(text, section, key):
    sec = None
    val = None
    for ln in text.splitlines():
        h = _ini_sec(ln)
        if h is not None:
            sec = h
        elif sec == section and "=" in ln:
            k, v = ln.split("=", 1)
            if k.strip() == key:
                val = v.strip()
    return val


def ini_set(text, section, key, value):
    """text with key=value in [section] (a key already there is replaced in
    place; the section is added at the end when missing)."""
    lines = text.splitlines(keepends=True)
    sec, last, found = None, None, False
    for i, ln in enumerate(lines):
        h = _ini_sec(ln)
        if h is not None:
            sec = h
            if sec == section:
                last = i
            continue
        if sec == section:
            if ln.strip():
                last = i
            if "=" in ln and ln.split("=", 1)[0].strip() == key:
                lines[i] = "%s=%s\n" % (key, value)
                found = True
    if found:
        return "".join(lines)
    if last is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines and lines[-1].strip():
            lines.append("\n")
        lines += ["[%s]\n" % section, "%s=%s\n" % (key, value)]
        return "".join(lines)
    if not lines[last].endswith("\n"):
        lines[last] += "\n"
    lines.insert(last + 1, "%s=%s\n" % (key, value))
    return "".join(lines)


def ini_unset(text, section, key, value=None):
    """text without key in [section] (only when it holds value, if given);
    a section left empty is dropped."""
    lines = text.splitlines(keepends=True)
    out, sec = [], None
    for ln in lines:
        h = _ini_sec(ln)
        if h is not None:
            sec = h
        elif sec == section and "=" in ln:
            k, v = ln.split("=", 1)
            if k.strip() == key and (value is None or v.strip() == value):
                continue
        out.append(ln)
    # drop an empty [section]
    res, i = [], 0
    while i < len(out):
        if _ini_sec(out[i]) == section:
            j = i + 1
            while j < len(out) and _ini_sec(out[j]) is None and not out[j].strip():
                j += 1
            if j >= len(out) or _ini_sec(out[j]) is not None:
                i = j
                continue
        res.append(out[i])
        i += 1
    while res and not res[-1].strip():
        res.pop()
    return "".join(res)
