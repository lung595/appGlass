"""Konsole: a glass colour scheme and profile (the terminal view), DMS palette readable.

QStyle does not reach Konsole's TerminalDisplay (B5b): the terminal area
takes its alpha from the colour scheme's ``Opacity``. For each installed
Konsole (native: $XDG_DATA_HOME/konsole + $XDG_CONFIG_HOME/konsolerc;
flatpak org.kde.konsole: ~/.var/app/org.kde.konsole/{data,config}):

- konsole/AppGlass.colorscheme (owned): ``[General] Opacity`` at the content
  level, Blur=false (niri blurs), the background, the foreground and the 16
  colours with their intense / faint variants, text readable on glass.
- konsole/AppGlass.profile (owned): the AppGlass scheme on top of Konsole's
  built-in profile.
- konsolerc (edited, backed up): ``[Desktop Entry] DefaultProfile=AppGlass.profile``
  when no default profile is set. A default profile of the user's own is
  kept (warned: pick the AppGlass scheme in it, or the AppGlass profile).
  Konsole rewrites konsolerc itself; remove takes the key out only while it
  still names the AppGlass profile.

The window chrome (tab bar, menus, toolbar) is the qt-style family's: its
launcher for org.kde.konsole starts Konsole with the appglass Qt style, and
the style takes its variables out of the environment, so the shell and what
it starts never inherit them. niri: ``^org\\.kde\\.konsole$`` gets opacity
1.0 (Konsole paints its own alpha; the qt-style family names it too).
"""

import os

from . import _term
from ..core import Conflict, scale

NAME = "konsole"
APP_IDS = [r"^org\.kde\.konsole$"]
FLATPAK = "org.kde.konsole"
CMDS = ("konsole",)
SCHEME = "AppGlass"
PROFILE = "AppGlass.profile"
INTENSE, FAINT = 1.25, 0.66


def installed(env):
    return bool(_term.targets(env, CMDS, FLATPAK))


def _lift(h):
    from ..core import mix
    return mix(h, "#ffffff", 0.2)


def scheme(ctx):
    pal = _term.palette(ctx)
    c = _term.rgb_csv
    lines = ["# appglass: Konsole glass scheme. Generated, do not edit: rewritten by appglass apply."]

    def sec(name, colour):
        return ["", "[%s]" % name, "Color=%s" % c(colour)]

    lines += sec("Background", pal["background"])
    lines += sec("BackgroundIntense", pal["background"])
    lines += sec("BackgroundFaint", pal["background"])
    for i in range(8):
        n, b = pal["ansi"][i], pal["ansi"][i + 8]
        lines += sec("Color%d" % i, n)
        lines += sec("Color%dIntense" % i, b)
        lines += sec("Color%dFaint" % i, ctx.readable(scale(n, FAINT), pal["background"],
                                                        ctx.levels.content, _term.TARGET))
    lines += sec("Foreground", pal["foreground"])
    lines += sec("ForegroundIntense", _lift(pal["foreground"]))
    lines += sec("ForegroundFaint", ctx.readable(scale(pal["foreground"], FAINT),
                                                 pal["background"], ctx.levels.content,
                                                 _term.TARGET))
    lines += ["", "[General]", "Blur=false", "ColorRandomization=false",
              "Description=%s" % SCHEME, "Opacity=%s" % _term.a2(ctx.levels.content),
              "Wallpaper=", ""]
    return "\n".join(lines)


PROFILE_TEXT = """# appglass: Konsole glass profile. Generated, do not edit.
[Appearance]
ColorScheme=%s

[General]
Name=AppGlass
Parent=FALLBACK/
""" % SCHEME


def edit_rc(ctx, text, path):
    cur = _term.ini_get(text, "Desktop Entry", "DefaultProfile")
    if cur and cur != PROFILE:
        ctx.warn_once("profile:" + path, "%s: the default profile is %s (yours, kept); "
                      "pick the %s colour scheme in it, or the AppGlass profile"
                      % (ctx.env.tilde(path), cur, SCHEME))
        return text
    return _term.ini_set(text, "Desktop Entry", "DefaultProfile", PROFILE)


def undo(env, path, text):
    if os.path.basename(path) != "konsolerc":
        return text
    out = _term.ini_unset(text, "Desktop Entry", "DefaultProfile", PROFILE)
    return out + "\n" if out and not out.endswith("\n") else out


def apply(ctx):
    paths = []
    for t in _term.targets(ctx.env, CMDS, FLATPAK):
        d = t.data_path("konsole")
        rc = t.config_path("konsolerc")
        if os.path.islink(rc):
            raise Conflict("%s is a symlink (user-managed); left untouched" % rc)
        paths.append(ctx.write_owned(os.path.join(d, SCHEME + ".colorscheme"), scheme(ctx)))
        paths.append(ctx.write_owned(os.path.join(d, PROFILE), PROFILE_TEXT))
        changed = ctx.changed_since_apply(rc)
        ctx.edit_text(rc, lambda text, p=rc: text if changed else edit_rc(ctx, text, p),
                      undo=lambda text, p=rc: undo(ctx.env, p, text))
        paths.append(rc)
    return paths
