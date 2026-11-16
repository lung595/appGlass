"""Alacritty: window.opacity = content, opaque glyphs, palette readable on glass.

Writes $XDG_CONFIG_HOME/alacritty/appglass.toml (owned) and edits the main
alacritty.toml: appglass.toml goes into general.import right after
dank-theme.toml, and the main file's own ``[window] opacity`` (and
``[colors] transparent_background_colors``) line is commented out, because
the main file wins over every import.

Palette: black = outline, magenta = tertiary, bright black =
on_surface_variant (docs/terminal.md), then every ANSI entry, the dim
entries and the dim foreground are moved toward white (dark glass) or black
(light glass) until opaque text reaches 2.25:1 on the glass over any
backdrop (white, black, wallpaper). Unchanged entries are not written, so
they keep following dank-theme.toml.

A main file the user changed after apply (their own opacity line, the import
taken out, any edit) is kept as it is by re-applies; remove takes appglass's
parts out and keeps the TOML valid (a key the user set again is theirs).
"""

import os
import re
import tomllib

from ..core import Conflict, norm_hex, readable, scale

NAME = "alacritty"
APP_IDS = [r"^Alacritty$"]

NAMES = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
ROLE_OVERRIDES = {("normal", "black"): "outline",
                  ("normal", "magenta"): "tertiary",
                  ("bright", "black"): "on_surface_variant"}
DIM_FACTOR = 0.66          # Alacritty's own dim factor
TARGET = 2.25              # >= 2:1 with a margin for antialiasing
MARK = "# appglass"
OFF = "# appglass-off: "


def installed(env):
    return env.which("alacritty") is not None


def main_config(env):
    """Alacritty's own search order; the first existing file, else the first."""
    cands = [env.config_path("alacritty", "alacritty.toml"),
             env.config_path("alacritty.toml"),
             env.home_path(".config", "alacritty", "alacritty.toml"),
             env.home_path(".alacritty.toml")]
    for c in cands:
        if os.path.isfile(c):
            return c
    return cands[0]


def _load_toml(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def theme_from_hook(ctx):
    """dank-theme.toml as DMS renders it, from the hook's colors.json.

    matugen renders the user templates in parallel with DMS's own, so when
    the post_hook runs, dank-theme.toml can still hold the previous theme.
    The hook template carries the same inputs (dank16term, background,
    on_surface), so this is always current.
    """
    t16, _ = ctx.term16
    if not t16:
        return None
    return {"colors": {
        "primary": {"background": ctx.colors("background"),
                    "foreground": ctx.colors("on_surface")},
        "normal": dict(zip(NAMES, t16[:8])),
        "bright": dict(zip(NAMES, t16[8:])),
    }}


def pick_theme(ctx, path):
    """The newer of dank-theme.toml and the hook's colours."""
    file_theme = _load_toml(path)
    hook_theme = theme_from_hook(ctx)
    if hook_theme is None:
        return file_theme
    if file_theme is None:
        return hook_theme
    try:
        file_mtime = os.stat(path).st_mtime
    except OSError:
        return hook_theme
    return file_theme if file_mtime > ctx.term16[1] else hook_theme


def palette(ctx, theme):
    """{section: {name: hex}} for every entry appglass sets."""
    lv = ctx.levels
    prim = (theme or {}).get("colors", {}).get("primary", {})
    bg = norm_hex(prim.get("background") or ctx.colors("surface"))
    fg = norm_hex(prim.get("foreground") or ctx.colors("on_surface"))
    base = {}
    d16 = ctx.dank16
    for si, sec in enumerate(("normal", "bright")):
        tcol = (theme or {}).get("colors", {}).get(sec, {})
        for i, n in enumerate(NAMES):
            v = tcol.get(n) or (d16[si * 8 + i] if d16 else None)
            role = ROLE_OVERRIDES.get((sec, n))
            if role:
                v = ctx.colors(role)
            base[(sec, n)] = norm_hex(v) if v else None
    out = {"primary": {}, "normal": {}, "bright": {}, "dim": {}}
    for (sec, n), v in base.items():
        if v is None:
            continue
        r = readable(v, bg, lv.content, TARGET)
        role = ROLE_OVERRIDES.get((sec, n))
        theme_v = (theme or {}).get("colors", {}).get(sec, {}).get(n)
        if role or r != v or not theme_v:
            out[sec][n] = (r, role)
    for n in NAMES:
        v = base.get(("normal", n))
        if v:
            out["dim"][n] = (readable(scale(v, DIM_FACTOR), bg, lv.content, TARGET), None)
    rf = readable(fg, bg, lv.content, TARGET)
    if rf != fg:
        out["primary"]["foreground"] = (rf, None)
    out["primary"]["dim_foreground"] = (readable(scale(fg, DIM_FACTOR), bg, lv.content, TARGET),
                                        None)
    return out, bg


def render(ctx, theme):
    lv = ctx.levels
    pal, bg = palette(ctx, theme)
    lines = [
        "# appglass: Alacritty glass. Generated, do not edit: rewritten by",
        "# appglass apply (and by the matugen hook on every DMS theme change).",
        "# Imported after dank-theme.toml by alacritty.toml.",
        "",
        "[window]",
        "# DMS foregroundLayerTransparency: background only, glyphs stay opaque",
        "opacity = %.2f" % lv.content,
        "",
        "[colors]",
        "# explicit-background cells (statuslines, selection) stay opaque",
        "transparent_background_colors = false",
    ]
    comment = "# text colours below reach %.2f:1 on the %s glass at %.2f over any backdrop" % (
        TARGET, bg, lv.content)
    lines += ["", comment]
    for sec in ("primary", "normal", "bright", "dim"):
        entries = pal[sec]
        if not entries:
            continue
        lines += ["", "[colors.%s]" % sec]
        order = NAMES if sec != "primary" else ("foreground", "dim_foreground")
        for n in order:
            if n in entries:
                v, role = entries[n]
                note = "  # %s" % role if role else ""
                lines.append("%s = '%s'%s" % (n, v, note))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- main file edit

_TABLE = re.compile(r"^\s*\[\s*([A-Za-z0-9_.\-\" ]+?)\s*\]\s*(#.*)?$")
_ATABLE = re.compile(r"^\s*\[\[")


def _tables(lines):
    """Yield (index, table-name-or-None) for each line."""
    cur = None
    for i, ln in enumerate(lines):
        if _ATABLE.match(ln):
            cur = "[[array]]"
        else:
            m = _TABLE.match(ln)
            if m:
                cur = m.group(1).replace(" ", "").replace('"', "")
        yield i, cur


def _scan_array(text, start):
    """text[start] == '['. Return (end_index_of_]', [(s, e, value)])."""
    i = start + 1
    elems = []
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n,":
            i += 1
        elif c == "#":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c == "]":
            return i, elems
        elif c in "\"'":
            if text.startswith(c * 3, i):
                raise ValueError("multi-line strings in import are not supported")
            j = i + 1
            while j < n and text[j] != c:
                if c == '"' and text[j] == "\\":
                    j += 1
                j += 1
            if j >= n:
                raise ValueError("unterminated string")
            raw = text[i:j + 1]
            elems.append((i, j + 1, tomllib.loads("v = " + raw)["v"]))
            i = j + 1
        else:
            raise ValueError("unexpected %r in import array" % c)
    raise ValueError("unterminated import array")


def _find_import(text):
    """(array_start_index, key_line_index) of general.import, or None."""
    lines = text.splitlines(keepends=True)
    offs = []
    o = 0
    for ln in lines:
        offs.append(o)
        o += len(ln)
    for i, table in _tables(lines):
        ln = lines[i]
        m = None
        if table == "general":
            m = re.match(r"^\s*import\s*=\s*", ln)
        elif table is None:
            m = re.match(r"^\s*(?:general\.)?import\s*=\s*", ln)
        if m:
            if ln[m.end():m.end() + 1] != "[":
                raise ValueError("general.import is not an array")
            return offs[i] + m.end(), i
    return None


def _entry(env, ours):
    return '"%s"' % env.tilde(ours).replace("\\", "\\\\").replace('"', '\\"')


def _is_ours(value, env, ours):
    v = os.path.join(env.home, value[2:]) if value.startswith("~/") else value
    return os.path.abspath(v) == os.path.abspath(ours)


def edit_main(text, env, ours):
    """Idempotent edit of the main alacritty.toml text."""
    ent = _entry(env, ours)
    # 1. import
    found = _find_import(text)
    if found is None:
        lines = text.splitlines(keepends=True)
        gen = [i for i, t in _tables(lines) if t == "general" and _TABLE.match(lines[i])]
        line = "import = [%s]  %s\n" % (ent, MARK)
        if gen:
            i = gen[0]
            if not lines[i].endswith("\n"):
                lines[i] += "\n"
            lines.insert(i + 1, line)
            text = "".join(lines)
        else:
            text = "general." + line + ("\n" if text.strip() else "") + text
    else:
        start, _ = found
        end, elems = _scan_array(text, start)
        if not any(_is_ours(v, env, ours) for _, _, v in elems):
            dank = [e for e in elems if os.path.basename(e[2]) == "dank-theme.toml"]
            if dank:
                pos = dank[-1][1]
                text = text[:pos] + ", " + ent + text[pos:]
            elif elems:
                pos = elems[-1][1]
                text = text[:pos] + ", " + ent + text[pos:]
            else:
                text = text[:start + 1] + ent + text[start + 1:]
    # 2. comment out the main file's own opacity / transparent_background_colors
    lines = text.splitlines(keepends=True)
    for i, table in list(_tables(lines)):
        ln = lines[i]
        if ln.lstrip().startswith("#"):
            continue
        hit = ((table == "window" and re.match(r"^\s*opacity\s*=", ln)) or
               (table == "colors" and re.match(r"^\s*transparent_background_colors\s*=", ln)) or
               (table is None and re.match(
                   r"^\s*(window\.opacity|colors\.transparent_background_colors)\s*=", ln)))
        if hit:
            lines[i] = OFF + ln
    return "".join(lines)


def _parses(text):
    try:
        tomllib.loads(text)
        return True
    except tomllib.TOMLDecodeError:
        return False


def undo(env, path, text):
    """Strip appglass's parts from a main config the user changed since.

    A line appglass commented out comes back only if the file still parses
    with it: when the user set the key again since (their own ``opacity``
    under [window]), theirs is kept and the old one stays a plain comment.
    """
    ours = env.config_path("alacritty", "appglass.toml")
    ent = _entry(env, ours)
    text = text.replace(", " + ent, "")
    text = re.sub(r"(?m)^(general\.)?import = \[" + re.escape(ent) + r"\]  " +
                  re.escape(MARK) + r"\n\n?", "", text)
    text = text.replace(ent, "")
    if not _parses(text):
        # broken already (not by us): only take the markers out
        return re.sub(r"(?m)^" + re.escape(OFF), "", text)
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.startswith(OFF):
            trial = lines[:i] + [ln[len(OFF):]] + lines[i + 1:]
            if _parses("".join(trial)):
                lines = trial
            else:
                lines[i] = "# " + ln[len(OFF):]
    return "".join(lines)


def apply(ctx):
    env = ctx.env
    cfg_dir = ctx.config_path("alacritty")
    ours = os.path.join(cfg_dir, "appglass.toml")
    main = main_config(env)
    theme = pick_theme(ctx, os.path.join(cfg_dir, "dank-theme.toml"))
    if theme is None:
        ctx.warn("dank-theme.toml not found; palette from DMS dms-colors.json")
    ctx.write_owned(ours, render(ctx, theme))
    # changed since apply (a user edit, their own opacity, the import taken
    # out): the file is the user's now, a re-apply keeps it as it is
    changed = ctx.changed_since_apply(main)

    def fn(text):
        if changed:
            return text
        if not text.strip():
            dank = os.path.join(cfg_dir, "dank-theme.toml")
            items = ([_entry(env, dank)] if os.path.exists(dank) else []) + [_entry(env, ours)]
            return "[general]\nimport = [%s]\n" % ", ".join(items)
        try:
            new = edit_main(text, env, ours)
        except ValueError as ex:
            raise Conflict("%s: cannot edit general.import safely: %s" % (main, ex))
        try:
            parsed = tomllib.loads(new)
        except tomllib.TOMLDecodeError as ex:
            raise Conflict("%s: edit would break the TOML (%s); left untouched" % (main, ex))
        if "opacity" in parsed.get("window", {}):
            raise Conflict("%s sets window.opacity in a form appglass cannot comment out"
                           % main)
        return new

    ctx.edit_text(main, fn, undo=lambda t: undo(env, main, t))
    return [ours, main]
