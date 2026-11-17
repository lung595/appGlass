"""WezTerm: window_background_opacity = content, opaque glyphs, bars at the bar level.

For each installed WezTerm (native: $XDG_CONFIG_HOME/wezterm; flatpak
org.wezfurlong.wezterm: ~/.var/app/org.wezfurlong.wezterm/config/wezterm):

- wezterm/appglass.lua (owned): a Lua module whose apply_to_config(config)
  sets window_background_opacity at the content level,
  text_background_opacity 1.0 (cells with an explicit background stay
  opaque), the DMS colours made readable on glass, and the fancy tab bar
  (window_frame titlebar colours, colors.tab_bar.background) at the bar
  level: the tab bar is painted over the cleared window, not stacked on the
  content, so it takes the bar alpha itself.
- wezterm.lua (edited, backed up): WezTerm puts its config dir on the Lua
  package.path, so one line before the final ``return <config>`` does it:
  ``require('appglass').apply_to_config(<config>)  -- appglass``. Without a
  wezterm.lua appglass writes a minimal one. A wezterm.lua that does not end
  in ``return <name>`` is not rewritten (skipped with the line to add).
  A wezterm.lua the user changed after apply is kept as it is; remove takes
  the line out.

On NVIDIA the Wayland frontend of WezTerm 20240203 never maps its window
(B5b): ``enable_wayland = false`` is the user's choice, not written here.
niri: ``^org\\.wezfurlong\\.wezterm$`` gets opacity 1.0.
"""

import os
import re

from . import _term
from ..core import Conflict, hex_to_rgb

NAME = "wezterm"
APP_IDS = [r"^org\.wezfurlong\.wezterm$"]
FLATPAK = "org.wezfurlong.wezterm"
CMDS = ("wezterm", "wezterm-gui")
MARK = "  -- appglass"
_REQ = re.compile(r"""require\s*\(?\s*['"]appglass['"]""")
_RET = re.compile(r"^\s*return\s+([A-Za-z_][A-Za-z0-9_]*)\s*;?\s*$")

NEW = """local wezterm = require 'wezterm'
local config = wezterm.config_builder()
%s
return config
"""


def installed(env):
    return bool(_term.targets(env, CMDS, FLATPAK))


def _rgba(h, a):
    return "rgba(%d,%d,%d,%s)" % (hex_to_rgb(h) + (_term.a2(a),))


def render(ctx):
    lv = ctx.levels
    pal = _term.palette(ctx)
    bar = _rgba(ctx.colors("surface"), lv.bar)
    q = lambda c: "'%s'" % c  # noqa: E731
    lines = _term.header("--", "WezTerm glass") + [
        "-- wezterm.lua calls apply_to_config(config) before it returns the config.",
        "local M = {}",
        "",
        "function M.apply_to_config(config)",
        "  config.window_background_opacity = %s" % _term.a2(lv.content),
        "  config.text_background_opacity = 1.0",
        "  config.colors = config.colors or {}",
        "  local c = config.colors",
        "  c.background = %s" % q(pal["background"]),
        "  c.foreground = %s" % q(pal["foreground"]),
        "  c.cursor_bg = %s" % q(pal["cursor"]),
        "  c.cursor_border = %s" % q(pal["cursor"]),
        "  c.cursor_fg = %s" % q(pal["cursor_text"]),
        "  c.selection_bg = %s" % q(pal["selection_bg"]),
        "  c.selection_fg = %s" % q(pal["selection_fg"]),
        "  c.ansi = {%s}" % ", ".join(q(x) for x in pal["ansi"][:8]),
        "  c.brights = {%s}" % ", ".join(q(x) for x in pal["ansi"][8:]),
        "  -- the tab bar sits on the cleared window: the bar level itself",
        "  c.tab_bar = c.tab_bar or {}",
        "  c.tab_bar.background = %s" % q(bar),
        "  c.tab_bar.inactive_tab_edge = %s" % q(bar),
        "  config.window_frame = config.window_frame or {}",
        "  config.window_frame.active_titlebar_bg = %s" % q(bar),
        "  config.window_frame.inactive_titlebar_bg = %s" % q(bar),
        "end",
        "",
        "return M",
        "",
    ]
    return "\n".join(lines)


def call(name):
    return "require('appglass').apply_to_config(%s)%s" % (name, MARK)


def edit_main(text, path):
    if not text.strip():
        return NEW % call("config")
    if _REQ.search(text):
        return text
    lines = text.splitlines(keepends=True)
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if not s or s.startswith("--"):
            continue
        m = _RET.match(lines[i])
        if not m:
            break
        lines.insert(i, call(m.group(1)) + "\n")
        return "".join(lines)
    raise Conflict("%s does not end with 'return <config>'; left untouched. Add "
                   "%s before it to opt in" % (path, call("config").replace(MARK, "")))


def undo(env, path, text):
    return _term.drop_lines(text, lambda ln: ln.endswith(MARK) and _REQ.search(ln))


def apply(ctx):
    paths = []
    for t in _term.targets(ctx.env, CMDS, FLATPAK):
        d = t.config_path("wezterm")
        ours = os.path.join(d, "appglass.lua")
        main = os.path.join(d, "wezterm.lua")
        if os.path.islink(main):
            raise Conflict("%s is a symlink (user-managed); left untouched" % main)
        changed = ctx.changed_since_apply(main)
        cur = ctx.read_text(main) or ""
        if not changed:
            edit_main(cur, main)       # a Conflict before anything is written
        paths.append(ctx.write_owned(ours, render(ctx)))
        ctx.edit_text(main, lambda text, m=main: text if changed else edit_main(text, m),
                      undo=lambda text, m=main: undo(ctx.env, m, text))
        paths.append(main)
    return paths
