"""webkit-shim: Lian Li Linux (lianli-gui, Tauri / WebKitGTK).

A forced adapter (on by default, live once its hidden check passes;
apps.lianli.enabled=false switches it off). appglass-wk.so (LD_PRELOAD, built from shims/webkit-shim with gcc)
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
# glass reaches the app only through its launcher override: a hand-made
# launcher in its place keeps it opaque (core.app_routes)
LAUNCHER = True
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


def verify_skip(env, rec):
    """The hidden check cannot judge Lian Li: it must hide the daemon (the
    fans and lights of the real machine, see verify_mask), and without it
    the app lays its "Check your installation / Waiting for daemon" dialog
    and a scrim over the page, so the shot measures the scrim (about 224
    at 0.80, 202 at 0.60), not the glass. Unverifiable, never a fail: it
    stays opaque unless you switch it on yourself."""
    return ("Lian Li covers its window with its \"Waiting for daemon\" dialog "
            "when the daemon is hidden, as the hidden check must: Lian Li is not checked")


def verify_mask(rec):
    """The hidden check keeps the app away from its daemon (/run/lianli:
    the fans and lights of the real machine), from the system manager (the
    GUI runs systemctl start lianli-control-recovery.service, a root unit
    its polkit rule allows: the system bus and all of /run/systemd
    hidden, resolved's DNS socket with it), from the real session bus and its session locks
    ($XDG_RUNTIME_DIR/bus, lianli-session-*.lock) and off the network."""
    from .. import verify
    return {"hide": verify.run_paths(rec, keys=("lianli",)) + verify.system_paths()
            + verify.session_paths(prefix="lianli"), "nonet": True}


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
