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
"""

import os

from .. import shims
from ..core import Conflict

NAME = "qtstyle"
APP_IDS = [r"^vlc$"]
ADAPTER = "qt-style"
LAUNCHERS = (("vlc.desktop", "vlc"),)
MODULES = ("Qt6Widgets",)
# the engine routes every other host Qt 6 Widgets app here (ctx.records())
GENERIC = True


def installed(env):
    return any(env.which(cmd) for _, cmd in LAUNCHERS)


def accepts(rec):
    """None for a host app that links Qt 6 Widgets (the style plugin is
    built with the host Qt 6), else why not."""
    if rec.get("flatpak"):
        return "Qt flatpak: its runtime Qt is not the host Qt the style is built with (ABI)"
    if rec.get("user_only"):
        return "a launcher of yours with no system one: left as it is"
    ev = " ".join(rec.get("evidence") or ())
    if "libQt6Widgets" not in ev:
        if "libQt5" in ev:
            return "Qt 5 app: the style plugin is built for Qt 6 (ABI)"
        return "no libQt6Widgets in its binary: the Qt 6 style does not load"
    return None


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


def launcher_any(env, text, content):
    """launcher() for an app found by the engine: every Exec= line (its
    first word may be a full path or a wrapper name)."""
    pre = ("env QT_PLUGIN_PATH=%s QT_STYLE_OVERRIDE=appglass APPGLASS_COLORS=%s "
           "APPGLASS_CONTENT=%s " % (plugin_dir(env), env.cache_path("dms", "dms-colors.json"),
                                     shims.jq_raw(content)))
    out = []
    for line in text.splitlines(True):
        if line.startswith("Exec=") and not line.startswith("Exec=env QT_PLUGIN_PATH=") \
                and line[5:].strip():
            line = "Exec=" + pre + line[5:]
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
    if not ids:
        ctx.warn("no system launcher for %s: nothing to start the style with"
                 % ", ".join(d for d, _ in LAUNCHERS))
    listed = {d for d, _ in LAUNCHERS}
    for rec in ctx.records():
        if rec["desktop_id"] in listed:
            continue
        try:
            p = ctx.desktop_override(rec["desktop_id"],
                                     lambda t: launcher_any(env, t, ctx.levels.content))
        except Conflict as ex:
            ctx.warn("%s: %s" % (rec["key"], ex))
            continue
        if p:
            paths.append(p)
            ids += [x for x in rec.get("app_ids") or () if x not in ids]
    ctx.app_ids = ids
    return paths
