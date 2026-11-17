"""qt-style: Qt Widgets apps (VLC) through the appglass Qt style plugin.

shims/qt-style/glassstyle.cpp is built with the host Qt 6 into
~/.local/lib/appglass/qt6/styles/libappglass.so (stamp: the sources, g++ and
the Qt6Widgets version: a Qt update rebuilds it). The style paints the
window and view backgrounds with the DMS surface colours at the glass
levels, bars at the bar level, menus and popups opaque, text untouched.
An unfocused top-level window eases its background to the inactive level
(QVariantAnimation on WindowActivate/WindowDeactivate, idle in between).

The launcher override ~/.local/share/applications/vlc.desktop (generated
from the system one on every apply) starts VLC with

    env QT_PLUGIN_PATH=~/.local/lib/appglass/qt6 QT_STYLE_OVERRIDE=appglass
        APPGLASS_COLORS=<cache>/dms/dms-colors.json APPGLASS_CONTENT=<level>
        APPGLASS_INACTIVE=<unfocused level> APPGLASS_FADE_MS=<ms> APPGLASS_FADE_EASING=<name> vlc

The style reads the colours from APPGLASS_COLORS at start; the level is
written into the launcher, and the sync unit / matugen hook re-apply when it
changes. remove deletes the style and the launcher (an adopted hand-made
launcher comes back byte-identical).
"""

import os

from .. import inactive, shims

NAME = "qtstyle"
APP_IDS = [r"^vlc$"]
ADAPTER = "qt-style"
LAUNCHERS = (("vlc.desktop", "vlc"),)
MODULES = ("Qt6Widgets",)


def installed(env):
    return any(env.which(cmd) for _, cmd in LAUNCHERS)


def plugin_dir(env):
    return shims.lib_dir(env, "qt6")


def style_path(env):
    return os.path.join(plugin_dir(env), "styles", "libappglass.so")


def _steps(tc, d):
    moc = [tc.moc] + shims.pkg_flags(tc, *MODULES, only_i=True) + \
        ["glassstyle.cpp", "-o", "glassstyle.moc"]
    cxx = [tc.cxx, "-O2", "-shared", "-fPIC", "-std=c++17", "-I.", "glassstyle.cpp",
           "-o", "libappglass.so"] + shims.pkg_flags(tc, *MODULES)
    return [moc, cxx]


def launcher(env, text, cmd, content, fade=None):
    """``fade``: inactive.fields() (the unfocused level and the fade); none: no fade."""
    fade = fade or {"inactive": content, "fade_ms": 0, "fade_easing": "linear"}
    pre = ("env QT_PLUGIN_PATH=%s QT_STYLE_OVERRIDE=appglass APPGLASS_COLORS=%s "
           "APPGLASS_CONTENT=%s APPGLASS_INACTIVE=%s APPGLASS_FADE_MS=%d APPGLASS_FADE_EASING=%s "
           % (plugin_dir(env), env.cache_path("dms", "dms-colors.json"), shims.jq_raw(content),
              shims.jq_raw(fade["inactive"]), int(fade["fade_ms"]), fade["fade_easing"]))
    out = []
    for line in text.splitlines(True):
        if line.startswith("Exec=") and not line.startswith("Exec=env QT_PLUGIN_PATH="):
            word = line[5:].split(None, 1)[0] if line[5:].strip() else ""
            if os.path.basename(word) == cmd:
                line = "Exec=" + pre + line[5:]
        out.append(line)
    return "".join(out)


def apply(ctx):
    env = ctx.env
    src = {n: shims.source(ADAPTER, n) for n in ("glassstyle.cpp", "appglass.json")}
    paths = [shims.build(ctx, ADAPTER, style_path(env), src, _steps,
                         ("cxx", "moc", "pkgconfig"), qt=MODULES)]
    ids = []
    fade = inactive.fields(ctx.settings, ctx.levels.content)
    for desktop_id, cmd in LAUNCHERS:
        p = ctx.desktop_override(desktop_id,
                                 lambda t, c=cmd: launcher(env, t, c, ctx.levels.content, fade))
        if p:
            paths.append(p)
            ids.append(r"^%s$" % desktop_id[:-len(".desktop")])
    if not ids:
        ctx.warn("no system launcher for %s: nothing to start the style with"
                 % ", ".join(d for d, _ in LAUNCHERS))
    ctx.app_ids = ids
    return paths
