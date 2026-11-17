"""qt-style: Qt Widgets apps (VLC) through the appglass Qt style plugin.

shims/qt-style/glassstyle.cpp is built with the host Qt 6 into
~/.local/lib/appglass/qt6/styles/libappglass.so (stamp: the sources, g++ and
the Qt6Widgets version: a Qt update rebuilds it). The style paints the
window and view backgrounds with the DMS surface colours at the glass
levels, bars at the bar level, menus and popups opaque, text untouched.

The launcher override ~/.local/share/applications/vlc.desktop (generated
from the system one on every apply) starts VLC with

    env QT_PLUGIN_PATH=~/.local/lib/appglass/qt6 QT_STYLE_OVERRIDE=appglass
        APPGLASS_COLORS=<cache>/dms/dms-colors.json APPGLASS_CONTENT=<level> vlc

The style reads the colours from APPGLASS_COLORS at start; the level is
written into the launcher, and the sync unit / matugen hook re-apply when it
changes. remove deletes the style and the launcher (an adopted hand-made
launcher comes back byte-identical).

Flatpak KDE apps (Kate, Konsole; B5b: the host-built plugin loads in the KDE
runtime when its Qt minor matches): the launcher override of the exported
desktop file adds to ``flatpak run`` read-only access to the plugin dir and
the DMS colours dir, and the same variables, the plugin dir in front of the
runtime's QT_PLUGIN_PATH (/app/lib/plugins:/usr/share/runtime/lib/plugins),
and APPGLASS_BAR at the bar-over-content level (bars equal to the content
when the bar level is lower). No flatpak override is written: an app started
another way is plain.

The style reads its variables once and takes them out of the environment
(every APPGLASS_*, QT_STYLE_OVERRIDE=appglass, its plugin dir in
QT_PLUGIN_PATH): Konsole's shell, Kate's tools and what they start never
inherit them.
"""

import os

from .. import shims

NAME = "qtstyle"
APP_IDS = [r"^vlc$"]
ADAPTER = "qt-style"
LAUNCHERS = (("vlc.desktop", "vlc"),)
FLATPAKS = (("org.kde.kate.desktop", "org.kde.kate"), ("org.kde.konsole.desktop", "org.kde.konsole"))
RUNTIME_PLUGINS = "/app/lib/plugins:/usr/share/runtime/lib/plugins"
MODULES = ("Qt6Widgets",)
MARK = "--env=QT_STYLE_OVERRIDE=appglass"


def installed(env):
    return (any(env.which(cmd) for _, cmd in LAUNCHERS)
            or any(shims.installed_flatpak(env, app) for _, app in FLATPAKS))


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


def launcher(env, text, cmd, content):
    pre = ("env QT_PLUGIN_PATH=%s QT_STYLE_OVERRIDE=appglass APPGLASS_COLORS=%s "
           "APPGLASS_CONTENT=%s " % (plugin_dir(env), env.cache_path("dms", "dms-colors.json"),
                                     shims.jq_raw(content)))
    out = []
    for line in text.splitlines(True):
        if line.startswith("Exec=") and not line.startswith("Exec=env QT_PLUGIN_PATH="):
            word = line[5:].split(None, 1)[0] if line[5:].strip() else ""
            if os.path.basename(word) == cmd:
                line = "Exec=" + pre + line[5:]
        out.append(line)
    return "".join(out)


def flatpak_launcher(env, text, levels):
    pd = plugin_dir(env)
    colors = env.cache_path("dms", "dms-colors.json")
    flags = " ".join([
        "--filesystem=%s:ro" % pd, "--filesystem=%s:ro" % os.path.dirname(colors),
        "--env=QT_PLUGIN_PATH=%s:%s" % (pd, RUNTIME_PLUGINS), MARK,
        "--env=APPGLASS_COLORS=%s" % colors,
        "--env=APPGLASS_CONTENT=%s" % shims.jq_raw(levels.content),
        "--env=APPGLASS_BAR=%s" % shims.jq_raw(round(levels.bar_over_content, 4))])
    out = []
    for line in text.splitlines(True):
        if line.startswith("Exec=") and MARK not in line:
            words = line[5:].split(" ")
            if len(words) > 1 and os.path.basename(words[0]) == "flatpak" and words[1] == "run":
                line = "Exec=%s run %s %s" % (words[0], flags, " ".join(words[2:]))
        out.append(line)
    return "".join(out)


def apply(ctx):
    env = ctx.env
    src = {n: shims.source(ADAPTER, n) for n in ("glassstyle.cpp", "appglass.json")}
    paths = [shims.build(ctx, ADAPTER, style_path(env), src, _steps,
                         ("cxx", "moc", "pkgconfig"), qt=MODULES)]
    ids = []
    for desktop_id, cmd in LAUNCHERS:
        p = ctx.desktop_override(desktop_id,
                                 lambda t, c=cmd: launcher(env, t, c, ctx.levels.content))
        if p:
            paths.append(p)
            ids.append(r"^%s$" % desktop_id[:-len(".desktop")])
    for desktop_id, app in FLATPAKS:
        if not shims.installed_flatpak(env, app):
            continue
        p = ctx.desktop_override(desktop_id, lambda t: flatpak_launcher(env, t, ctx.levels))
        if p:
            paths.append(p)
            ids.append(r"^%s$" % app.replace(".", r"\."))
    if not ids:
        ctx.warn("no system launcher for %s: nothing to start the style with"
                 % ", ".join(d for d, _ in LAUNCHERS + FLATPAKS))
    ctx.app_ids = ids
    return paths
