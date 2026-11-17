"""Ghostty: background-opacity = content, opaque glyphs, the DMS palette readable on glass.

- $XDG_CONFIG_HOME/ghostty/appglass (owned): background-opacity at the
  content level (background-opacity-cells stays off: cells with an explicit
  background stay opaque), the background, the foreground, cursor, selection
  and the 16 colours (docs/terminal.md).
- the main config (config.ghostty when it exists, else config) (edited,
  backed up): ``config-file = ?<appglass>`` as its last line. Ghostty loads a
  config-file after the file that names it, so its keys win over the user's
  own background-opacity and over the DMS theme; nothing of theirs is
  commented out. A main config the user changed after apply is kept as it
  is; remove takes the line out.

Ghostty is not on flathub (the native install only). niri: the
``^com\\.mitchellh\\.ghostty$`` app-id gets opacity 1.0.
"""

import os

from . import _term
from ..core import Conflict

NAME = "ghostty"
APP_IDS = [r"^com\.mitchellh\.ghostty$"]
CMDS = ("ghostty",)


def installed(env):
    return bool(_term.targets(env, CMDS))


def line(ours):
    return "config-file = ?" + ours


def main_config(d):
    new = os.path.join(d, "config.ghostty")
    old = os.path.join(d, "config")
    return new if os.path.isfile(new) else old


def render(ctx):
    pal = _term.palette(ctx)
    lines = _term.header("#", "Ghostty glass") + [
        "# Loaded after the main config; the glyphs stay opaque, the background is glass.",
        "",
        "background-opacity = %s" % _term.a2(ctx.levels.content),
        "background-opacity-cells = false",
        "background = %s" % pal["background"],
        "foreground = %s" % pal["foreground"],
        "cursor-color = %s" % pal["cursor"],
        "cursor-text = %s" % pal["cursor_text"],
        "selection-background = %s" % pal["selection_bg"],
        "selection-foreground = %s" % pal["selection_fg"],
    ]
    lines += ["palette = %d=%s" % (i, c) for i, c in enumerate(pal["ansi"])]
    lines.append("")
    return "\n".join(lines)


def undo(env, path, text):
    ours = os.path.join(os.path.dirname(path), "appglass")
    return _term.drop_lines(text, lambda ln: ln.strip() == line(ours))


def apply(ctx):
    paths = []
    for t in _term.targets(ctx.env, CMDS):
        d = t.config_path("ghostty")
        ours = os.path.join(d, "appglass")
        main = main_config(d)
        if os.path.islink(main):
            raise Conflict("%s is a symlink (user-managed); left untouched" % main)
        paths.append(ctx.write_owned(ours, render(ctx)))
        changed = ctx.changed_since_apply(main)
        ctx.edit_text(main, lambda text: text if changed else _term.append_line(text, line(ours)),
                      undo=lambda text, m=main: undo(ctx.env, m, text))
        paths.append(main)
    return paths
