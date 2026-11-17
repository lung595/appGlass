"""webkit-shim: Lian Li Linux (lianli-gui, Tauri / WebKitGTK).

A forced adapter (off until apps.lianli or apps.com.sgtaziz.lianlilinux is
enabled). appglass-wk.so (LD_PRELOAD, built from shims/webkit-shim with gcc)
clears the WebView background, gives the window an RGBA visual and injects
lianli-glass.css as a user stylesheet.

Files (all owned, removed by remove; adopted hand files restored):
  ~/.local/lib/appglass/lianli/appglass-wk.so      the shim (stamp: source + gcc)
  ~/.local/lib/appglass/lianli/appglass-wk.c       its source, for reference
  ~/.local/lib/appglass/lianli/lianli-glass.css.tmpl
  ~/.local/lib/appglass/lianli/lianli-glass.css    rendered on apply (the hook
                                                   re-renders it) and at launch
  ~/.local/bin/appglass-lianli                     the launch wrapper
  ~/.local/share/applications/com.sgtaziz.lianlilinux.desktop -> the wrapper
"""

from .. import shims

NAME = "lianli"
ADAPTER = "webkit-shim"
OPT_IN = True
KEYS = ("com.sgtaziz.lianlilinux",)
APP_IDS = [r"^com\.sgtaziz\.lianlilinux$"]
APP = "lianli"
COMMAND = "lianli-gui"
DESKTOP = "com.sgtaziz.lianlilinux.desktop"
WRAPPER = "appglass-lianli"
TMPL = "lianli-glass.css.tmpl"


def installed(env):
    return bool(env.which(COMMAND))


def css(ctx):
    lv = shims.levels(ctx)
    return shims.fill(shims.source(ADAPTER, TMPL).decode("utf-8"),
                      [("content", shims.jq_pct(lv["content"])),
                       ("bar_over", shims.jq_pct(lv["bar_over_content"])),
                       ("inactive", shims.jq_pct(lv["inactive"])), ("fade", lv["fade"])])


def apply(ctx):
    env = ctx.env
    paths = [shims.c_shim(ctx, ADAPTER, APP, "appglass-wk.c", "appglass-wk.so")]
    paths += shims.copy(ctx, ADAPTER, APP, ("appglass-wk.c", TMPL))
    paths.append(ctx.write_owned(shims.lib_dir(env, APP, "lianli-glass.css"), css(ctx)))
    w = shims.wrapper(ctx, ADAPTER, WRAPPER)
    paths.append(w)
    p = shims.launcher(ctx, DESKTOP, w, command=COMMAND)
    if p:
        paths.append(p)
    return paths
