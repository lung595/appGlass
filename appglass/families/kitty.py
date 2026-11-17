"""kitty: background_opacity = content, opaque glyphs, the DMS palette readable on glass.

- $XDG_CONFIG_HOME/kitty/appglass.conf (owned): background_opacity at the
  content level, the background, the foreground, cursor, selection and the
  16 colours (docs/terminal.md). Cells with an explicit background stay
  opaque (kitty applies background_opacity to the default background only).
- kitty.conf (edited, backed up): ``include appglass.conf`` as its last line.
  kitty takes the last value of a key, so the include wins over the user's
  own ``background_opacity`` and over the DMS dank-theme.conf include above
  it; nothing of theirs is commented out. A kitty.conf the user changed after
  apply is kept as it is; remove takes the line out.

kitty is not on flathub (the native install only). niri: ``^kitty$`` gets
opacity 1.0: kitty paints its own alpha.
"""

import os

from . import _term
from ..core import Conflict

NAME = "kitty"
APP_IDS = [r"^kitty$"]
CMDS = ("kitty",)
LINE = "include appglass.conf"


def installed(env):
    return bool(_term.targets(env, CMDS))


def render(ctx):
    pal = _term.palette(ctx)
    lines = _term.header("#", "kitty glass") + [
        "# Included last by kitty.conf; the glyphs stay opaque, the background is glass.",
        "",
        "background_opacity %s" % _term.a2(ctx.levels.content),
        "background %s" % pal["background"],
        "foreground %s" % pal["foreground"],
        "cursor %s" % pal["cursor"],
        "cursor_text_color %s" % pal["cursor_text"],
        "selection_background %s" % pal["selection_bg"],
        "selection_foreground %s" % pal["selection_fg"],
    ]
    lines += ["color%d %s" % (i, c) for i, c in enumerate(pal["ansi"])]
    lines.append("")
    return "\n".join(lines)


def undo(env, path, text):
    return _term.drop_lines(text, lambda ln: ln.strip() == LINE)


def apply(ctx):
    paths = []
    for t in _term.targets(ctx.env, CMDS):
        d = t.config_path("kitty")
        ours = os.path.join(d, "appglass.conf")
        main = os.path.join(d, "kitty.conf")
        if os.path.islink(main):
            raise Conflict("%s is a symlink (user-managed); left untouched" % main)
        paths.append(ctx.write_owned(ours, render(ctx)))
        changed = ctx.changed_since_apply(main)
        ctx.edit_text(main, lambda text: text if changed else _term.append_line(text, LINE),
                      undo=lambda text, m=main: undo(ctx.env, m, text))
        paths.append(main)
    return paths
