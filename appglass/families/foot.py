"""foot: [colors] alpha = content, opaque glyphs, the DMS palette readable on glass.

For each installed foot (native: $XDG_CONFIG_HOME/foot; flatpak
page.codeberg.dnkl.foot: ~/.var/app/page.codeberg.dnkl.foot/config/foot):

- foot/appglass.ini (owned): ``alpha`` at the content level, the background,
  the foreground and the 16 colours (docs/terminal.md). The section is
  ``[colors-dark]`` for foot 1.26 and later (``[colors]`` is its deprecated
  alias there), ``[colors]`` before (foot 1.25, the flathub build in B5b,
  rejects ``[colors-dark]``, the section the DMS template writes).
- foot/foot.ini (edited, backed up): ``include=<appglass.ini>`` in the main
  section, after the user's own includes (the DMS dank-colors.ini), by its
  absolute path: an include of ~/.config does not resolve inside the flatpak,
  ~/.var/app/<id> is the same path inside and out. A foot.ini ``alpha=`` line
  in a colours section comes after the include and would win, so it is
  commented out (``# appglass-off: ``); the user's other colours stay theirs.

A foot.ini the user changed after apply is kept as it is by re-applies;
remove takes the include out and puts the commented lines back.
niri: ``^foot$``, footclient and the flatpak's ``page.codeberg.dnkl.foot`` get opacity 1.0: foot paints its own alpha.
"""

import os
import re

from . import _term
from ..core import Conflict

NAME = "foot"
APP_IDS = [r"^foot$", r"^footclient$", r"^page\.codeberg\.dnkl\.foot$"]
FLATPAK = "page.codeberg.dnkl.foot"
CMDS = ("foot",)
OFF = "# appglass-off: "
_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")
COLOR_SECTIONS = ("colors", "colors-dark", "colors-light", "colors2")


def installed(env):
    return bool(_term.targets(env, CMDS, FLATPAK))


def _ver(s):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", s or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None


def version(env, target):
    """foot's version (major, minor, patch) for a target, or None."""
    if target.kind == "native":
        exe = env.which("foot")
        try:
            r = env.run([exe, "--version"], timeout=10)
        except (OSError, Exception):
            return None
        return _ver(r.stdout + r.stderr)
    from .. import detect
    info = detect.flatpak_app(env, FLATPAK)
    if not info:
        return None
    meta = os.path.join(info["files"], "share", "metainfo", FLATPAK + ".metainfo.xml")
    try:
        with open(meta, encoding="utf-8", errors="replace") as f:
            m = re.search(r'<release[^>]*\bversion="([^"]+)"', f.read())
    except OSError:
        return None
    return _ver(m.group(1)) if m else None


def section(ver):
    return "colors-dark" if ver and ver >= (1, 26) else "colors"


def render(ctx, sec):
    pal = _term.palette(ctx)
    h = lambda c: c.lstrip("#")  # noqa: E731
    lines = _term.header("#", "foot glass") + [
        "# Included by foot.ini; the glyphs stay opaque, the background is glass.",
        "",
        "[%s]" % sec,
        "alpha=%s" % _term.a2(ctx.levels.content),
        "background=%s" % h(pal["background"]),
        "foreground=%s" % h(pal["foreground"]),
        "selection-foreground=%s" % h(pal["selection_fg"]),
        "selection-background=%s" % h(pal["selection_bg"]),
        "cursor=%s %s" % (h(pal["cursor_text"]), h(pal["cursor"])),
    ]
    for i in range(8):
        lines.append("regular%d=%s" % (i, h(pal["ansi"][i])))
    for i in range(8):
        lines.append("bright%d=%s" % (i, h(pal["ansi"][i + 8])))
    lines.append("")
    return "\n".join(lines)


def include_line(path):
    return "include=" + path


def edit_main(text, ours):
    inc = include_line(ours)
    lines = text.splitlines(keepends=True)
    sec, first_sec, last_inc = None, None, None
    for i, ln in enumerate(lines):
        m = _SECTION.match(ln)
        if m:
            sec = m.group(1).strip()
            if first_sec is None:
                first_sec = i
            continue
        s = ln.strip()
        if sec is None and re.match(r"^include\s*=", s):
            last_inc = i
        if sec in COLOR_SECTIONS and re.match(r"^alpha\s*=", s):
            lines[i] = OFF + ln
    if not any(ln.rstrip("\n").strip() == inc for ln in lines):
        at = last_inc + 1 if last_inc is not None else 0
        if at > 0 and not lines[at - 1].endswith("\n"):
            lines[at - 1] += "\n"
        lines.insert(at, inc + "\n")
    return "".join(lines)


def undo(env, path, text):
    out = []
    for ln in text.splitlines(keepends=True):
        s = ln.strip()
        if s.startswith("include=") and s.endswith(os.sep + "appglass.ini"):
            continue
        if ln.startswith(OFF):
            ln = ln[len(OFF):]
        out.append(ln)
    return "".join(out)


def apply(ctx):
    paths = []
    for t in _term.targets(ctx.env, CMDS, FLATPAK):
        d = t.config_path("foot")
        ours = os.path.join(d, "appglass.ini")
        main = os.path.join(d, "foot.ini")
        if os.path.islink(main):
            raise Conflict("%s is a symlink (user-managed); left untouched" % main)
        paths.append(ctx.write_owned(ours, render(ctx, section(version(ctx.env, t)))))
        changed = ctx.changed_since_apply(main)
        ctx.edit_text(main, lambda text, o=ours: text if changed else edit_main(text, o),
                      undo=lambda text, m=main: undo(ctx.env, m, text))
        paths.append(main)
    return paths
