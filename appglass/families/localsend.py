"""ck-shim: LocalSend (flatpak org.localsend.localsend_app, Flutter).

A forced adapter (off until apps.localsend or apps.org.localsend.localsend_app
is enabled). appglass-ck.so (LD_PRELOAD inside the flatpak, built from
shims/ck-shim with gcc) colour-keys LocalSend's own background colours to
the glass levels. The wrapper passes the lib dir read-only for that run only
(no flatpak override) and picks the keys from LocalSend's theme setting.

Files (owned; adopted hand files restored by remove):
  ~/.local/lib/appglass/localsend/appglass-ck.so   (stamp: source + gcc)
  ~/.local/lib/appglass/localsend/appglass-ck.c    its source, for reference
  ~/.local/bin/appglass-localsend                  the launch wrapper (levels at launch)
  ~/.local/share/applications/org.localsend.localsend_app.desktop -> the wrapper

Only LocalSend (ArtCraft is the artcraft family): other apps the catalogue
routes to ck-shim (egui, winit...) need their own keys and are not handled here.
"""

from .. import shims

NAME = "localsend"
ADAPTER = "ck-shim"
OPT_IN = True
FLATPAK = "org.localsend.localsend_app"
KEYS = (FLATPAK,)
APP_IDS = [r"^org\.localsend\.localsend_app$"]
APP = "localsend"
WRAPPER = "appglass-localsend"


def installed(env):
    return shims.installed_flatpak(env, FLATPAK)


def apply(ctx):
    paths = [shims.c_shim(ctx, ADAPTER, APP, "appglass-ck.c", "appglass-ck.so")]
    paths += shims.copy(ctx, ADAPTER, APP, ("appglass-ck.c",))
    w = shims.wrapper(ctx, ADAPTER, WRAPPER)
    paths.append(w)
    p = shims.launcher(ctx, FLATPAK + ".desktop", w, app_id=FLATPAK)
    if p:
        paths.append(p)
    return paths
