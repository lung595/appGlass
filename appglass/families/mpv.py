"""mpv: a glass background colour; the video, the OSD and the popups stay opaque.

mpv (vo=gpu-next, B5b) carries alpha to the Wayland surface when the
background colour has an alpha below FF; mpv 0.42 has no --alpha option any
more. For each installed mpv (native: $XDG_CONFIG_HOME/mpv; flatpak
io.mpv.Mpv: ~/.var/app/io.mpv.Mpv/config/mpv):

- mpv/appglass.conf (owned): ``background=color``, ``background-color`` as a
  quoted "#AARRGGBB" (``#`` starts a comment in mpv.conf) with AA the content
  level and RGB the DMS surface_container, ``border-background=color`` (the
  letterbox too), and the console at background alpha 00 (opaque: libass
  alpha is a transparency). The video and the OSD colours are untouched.
- mpv/mpv.conf (edited, backed up): ``include="<appglass.conf>"`` by its
  absolute path, at the top so the user's own lines after it win. A
  mpv.conf changed since apply is kept as it is by re-applies.

niri: ``^mpv$`` and ``^io\\.mpv\\.Mpv$`` get opacity 1.0 (otherwise the
global glass rule fades the video and the text too). A running mpv keeps the
old colour until it restarts (``set background-color`` over IPC is live).
"""

import os

from . import _term
from ..core import Conflict, alpha_hex, norm_hex

NAME = "mpv"
APP_IDS = [r"^mpv$", r"^io\.mpv\.Mpv$"]
FLATPAK = "io.mpv.Mpv"
CMDS = ("mpv",)


def installed(env):
    return bool(_term.targets(env, CMDS, FLATPAK))


def render(ctx):
    bg = norm_hex(ctx.colors("surface_container")).lstrip("#")
    return "\n".join(_term.header("#", "mpv glass") + [
        "# Included by mpv.conf: the window background is glass, the video stays opaque.",
        "background=color",
        'background-color="#%s%s"' % (alpha_hex(ctx.levels.content), bg),
        "border-background=color",
        "script-opts-append=console-background_alpha=00",
        ""])


def include_line(path):
    return 'include="%s"' % path


def edit_main(text, ours):
    inc = include_line(ours)
    if _term.has_line(text, inc):
        return text
    return inc + "\n" + text


def undo(env, path, text):
    return _term.drop_lines(text, lambda ln: ln.strip().startswith('include="')
                            and ln.strip().endswith(os.sep + 'appglass.conf"'))


def apply(ctx):
    paths = []
    for t in _term.targets(ctx.env, CMDS, FLATPAK):
        d = t.config_path("mpv")
        ours = os.path.join(d, "appglass.conf")
        main = os.path.join(d, "mpv.conf")
        if os.path.islink(main):
            raise Conflict("%s is a symlink (user-managed); left untouched" % main)
        paths.append(ctx.write_owned(ours, render(ctx)))
        changed = ctx.changed_since_apply(main)
        ctx.edit_text(main, lambda text, o=ours: text if changed else edit_main(text, o),
                      undo=lambda text, m=main: undo(ctx.env, m, text))
        paths.append(main)
    return paths
