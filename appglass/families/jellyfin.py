"""qtquick-shim: Jellyfin Desktop 2.x (flatpak org.jellyfin.JellyfinDesktop,
Qt Quick + QtWebEngine + mpv).

A forced adapter (on by default, live once its hidden check passes;
apps.jellyfin.enabled=false switches it off). libjfglass.so (LD_PRELOAD in the main process only, built from
shims/qtquick-shim with the host Qt 6) gives the Qt Quick window an alpha
channel, clears the window and web view backgrounds, shows the mpv layer only
while a video plays (videos and text stay 1.0) and injects the CSS named by
JFGLASS_CSS. The stamp has the host Qt versions and the flatpak runtime the
shim is loaded into: a runtime update rebuilds it.

Files (owned; adopted hand files restored by remove):
  ~/.local/lib/appglass/jellyfin/libjfglass.so
  ~/.local/lib/appglass/jellyfin/jfglass.cpp            source, for reference
  ~/.local/lib/appglass/jellyfin/jellyfin-glass.css.tmpl
  ~/.local/lib/appglass/jellyfin/gen-css.sh             renders the CSS at launch
  ~/.local/lib/appglass/jellyfin/jellyfin-glass.css     rendered on apply too
  ~/.local/bin/appglass-jellyfin                        the launch wrapper
  ~/.local/share/applications/org.jellyfin.JellyfinDesktop.desktop -> the wrapper
"""

from .. import detect, shims

NAME = "jellyfin"
ADAPTER = "qtquick-shim"
OPT_IN = True
FLATPAK = "org.jellyfin.JellyfinDesktop"
KEYS = (FLATPAK,)
APP_IDS = [r"^org\.jellyfin\.JellyfinDesktop$"]
APP = "jellyfin"
WRAPPER = "appglass-jellyfin"
TMPL = "jellyfin-glass.css.tmpl"
MODULES = ("Qt6Quick", "Qt6Qml", "Qt6Gui", "Qt6Core")
# gen-css.sh: (template key, palette role, fallback) in its sed order
ROLES = (("surface", "surface", "13140d"),
         ("surface_container", "surface_container", "21221a"),
         ("surface_container_high", "surface_container_high", "2b2c24"),
         ("on_surface", "on_surface", "e4e3d6"),
         ("on_surface_rgb", "on_surface", "e4e3d6"),
         ("on_surface_variant", "on_surface_variant", "c7c7b7"))


def installed(env):
    return detect.flatpak_app(env, FLATPAK) is not None


def css(ctx):
    lv = shims.levels(ctx)
    pairs = [("content", shims.jq_raw(lv["content"])),
             ("bar_over", shims.jq_raw(lv["bar_over_content"]))]
    pairs += [(k, shims.rgb(ctx, role, fb)) for k, role, fb in ROLES]
    return shims.fill(shims.source(ADAPTER, TMPL).decode("utf-8"), pairs)


def _steps(tc, d):
    return [[tc.moc, "jfglass.cpp", "-o", "jfglass.moc"],
            [tc.cxx, "-std=c++17", "-O2", "-fPIC", "-shared", "-o", "libjfglass.so",
             "jfglass.cpp"] + shims.pkg_flags(tc, *MODULES) + ["-ldl"]]


def apply(ctx):
    env = ctx.env
    info = detect.flatpak_app(env, FLATPAK) or {}
    paths = [shims.build(ctx, ADAPTER, shims.lib_dir(env, APP, "libjfglass.so"),
                         {"jfglass.cpp": shims.source(ADAPTER, "jfglass.cpp")}, _steps,
                         ("cxx", "moc", "pkgconfig"), qt=MODULES,
                         extra=["runtime " + info.get("runtime", "?")], mode=0o644)]
    paths += shims.copy(ctx, ADAPTER, APP, ("jfglass.cpp", TMPL))
    paths.append(ctx.write_owned(shims.lib_dir(env, APP, "gen-css.sh"),
                                 shims.script(env, ADAPTER, "gen-css.sh"), mode=0o755))
    paths.append(ctx.write_owned(shims.lib_dir(env, APP, "jellyfin-glass.css"), css(ctx)))
    w = shims.wrapper(ctx, ADAPTER, WRAPPER)
    paths.append(w)
    p = shims.launcher(ctx, FLATPAK + ".desktop", w, app_id=FLATPAK)
    if p:
        paths.append(p)
    return paths
