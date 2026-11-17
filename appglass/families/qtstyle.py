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

Flatpak KDE apps (Kate, Konsole; B5b: the host-built plugin loads in the KDE
runtime when its Qt minor matches): the launcher override of the exported
desktop file adds to ``flatpak run`` read-only access to the plugin dir and
the DMS colours dir, and the same variables, the plugin dir in front of the
runtime's QT_PLUGIN_PATH (/app/lib/plugins:/usr/share/runtime/lib/plugins),
and APPGLASS_BAR at the bar-over-content level (bars equal to the content
when the bar level is lower). Kate's launcher also puts the kate family's
glass katerc dir in front of XDG_CONFIG_DIRS (the AppGlass editor theme for
this start only). No flatpak override is written: an app started another way
is plain.

The style reads its variables once and takes them out of the environment
(every APPGLASS_*, QT_STYLE_OVERRIDE=appglass, its plugin dir in
QT_PLUGIN_PATH; an appglass dir in XDG_CONFIG_DIRS once the event loop runs): Konsole's shell, Kate's tools and what they start never
inherit them.
"""

import os

from .. import inactive, shims
from ..core import Conflict
from . import kate

NAME = "qtstyle"
APP_IDS = [r"^vlc$"]
ADAPTER = "qt-style"
LAUNCHERS = (("vlc.desktop", "vlc"),)
FLATPAKS = (("org.kde.kate.desktop", "org.kde.kate"), ("org.kde.konsole.desktop", "org.kde.konsole"))
RUNTIME_PLUGINS = "/app/lib/plugins:/usr/share/runtime/lib/plugins"
RUNTIME_XDG = "/app/etc/xdg:/etc/xdg"   # flatpak's XDG_CONFIG_DIRS
MODULES = ("Qt6Widgets",)
MARK = "--env=QT_STYLE_OVERRIDE=appglass"
# the engine routes every other host Qt 6 Widgets app here (ctx.records())
GENERIC = True
# the route is an environment variable on the launcher: never for an app
# that starts other apps (adapters.resolve)
ENV_ROUTE = True


def installed(env):
    return (any(env.which(cmd) for _, cmd in LAUNCHERS)
            or any(shims.installed_flatpak(env, app) for _, app in FLATPAKS))


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


def flatpak_launcher(env, text, levels, app=None, fade=None):
    """``fade``: inactive.fields(), as for ``launcher``; none: no fade."""
    fade = fade or {"inactive": levels.content, "fade_ms": 0, "fade_easing": "linear"}
    pd = plugin_dir(env)
    colors = env.cache_path("dms", "dms-colors.json")
    flags = [
        "--filesystem=%s:ro" % pd, "--filesystem=%s:ro" % os.path.dirname(colors),
        "--env=QT_PLUGIN_PATH=%s:%s" % (pd, RUNTIME_PLUGINS), MARK,
        "--env=APPGLASS_COLORS=%s" % colors,
        "--env=APPGLASS_CONTENT=%s" % shims.jq_raw(levels.content),
        "--env=APPGLASS_BAR=%s" % shims.jq_raw(round(levels.bar_over_content, 4)),
        "--env=APPGLASS_INACTIVE=%s" % shims.jq_raw(fade["inactive"]),
        "--env=APPGLASS_FADE_MS=%d" % int(fade["fade_ms"]),
        "--env=APPGLASS_FADE_EASING=%s" % fade["fade_easing"]]
    if app == kate.FLATPAK:  # the glass start's katerc (kate family), never the user's
        flags.append("--env=XDG_CONFIG_DIRS=%s:%s" % (kate.xdg_dir(env), RUNTIME_XDG))
    flags = " ".join(flags)
    out = []
    for line in text.splitlines(True):
        if line.startswith("Exec=") and MARK not in line:
            words = line[5:].split(" ")
            if len(words) > 1 and os.path.basename(words[0]) == "flatpak" and words[1] == "run":
                line = "Exec=%s run %s %s" % (words[0], flags, " ".join(words[2:]))
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
    fade = inactive.fields(ctx.settings, ctx.levels.content)
    # held opaque by the engine (S7): a launcher written before goes back to
    # the system text (no style variables) until the next fingerprint
    plain = {r["desktop_id"]: r for r in ctx.records(plain=True)}
    for did in plain:
        if ctx.owns(ctx.data_path("applications", did)):
            p = ctx.desktop_override(did, lambda t: t)
            if p:
                paths.append(p)
    for desktop_id, cmd in LAUNCHERS:
        if desktop_id in plain:
            continue
        p = ctx.desktop_override(desktop_id,
                                 lambda t, c=cmd: launcher(env, t, c, ctx.levels.content, fade))
        if p:
            paths.append(p)
            ids.append(r"^%s$" % desktop_id[:-len(".desktop")])
    for desktop_id, app in FLATPAKS:
        if desktop_id in plain or not shims.installed_flatpak(env, app):
            continue
        p = ctx.desktop_override(desktop_id, lambda t, a=app: flatpak_launcher(env, t, ctx.levels, a, fade))
        if p:
            paths.append(p)
            ids.append(r"^%s$" % app.replace(".", r"\."))
    if not ids:
        ctx.warn("no system launcher for %s: nothing to start the style with"
                 % ", ".join(d for d, _ in LAUNCHERS + FLATPAKS))
    listed = {d for d, _ in LAUNCHERS + FLATPAKS}
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
