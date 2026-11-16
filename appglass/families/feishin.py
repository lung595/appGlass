"""electron-hook: Feishin (flatpak org.jeffvli.feishin, Electron).

A forced adapter (off until apps.feishin or apps.org.jeffvli.feishin is
enabled). The wrapper starts Feishin through its normal flatpak command with
a Node inspector on 127.0.0.1 (random port, --inspect-publish-uid=stderr:
the target is not listed over HTTP, the session UUID is read only by the
wrapper from a 0700 dir and deleted after injection); agl-inject.py then
requires agl-hook.js in the main process, which clears the window background
and injects feishin-glass.css. The inspector port stays open while Feishin
runs (Electron cannot close it): the reason this adapter is opt-in.

Files (owned; adopted hand files restored by remove):
  ~/.local/lib/appglass/feishin/agl-hook.js, agl-inject.py
  ~/.local/lib/appglass/feishin/feishin-glass.css.tmpl
  ~/.local/lib/appglass/feishin/feishin-glass.css     rendered on apply and at launch
  ~/.local/bin/appglass-feishin                       the launch wrapper
  ~/.local/share/applications/org.jeffvli.feishin.desktop -> the wrapper
"""

from .. import shims

NAME = "feishin"
ADAPTER = "electron-hook"
OPT_IN = True
FLATPAK = "org.jeffvli.feishin"
KEYS = (FLATPAK,)
APP_IDS = [r"^feishin$"]
APP = "feishin"
WRAPPER = "appglass-feishin"
TMPL = "feishin-glass.css.tmpl"
ROLES = (("surface", "101418"), ("surface_container", "1e2226"),
         ("surface_container_high", "282c30"))


def installed(env):
    return shims.installed_flatpak(env, FLATPAK)


def css(ctx):
    lv = shims.levels(ctx)
    pairs = [("content", shims.jq_raw(lv["content"])),
             ("bar_over", shims.jq_raw(lv["bar_over_content"]))]
    pairs += [(r, shims.rgb(ctx, r, fb)) for r, fb in ROLES]
    return shims.fill(shims.source(ADAPTER, TMPL).decode("utf-8"), pairs)


def apply(ctx):
    env = ctx.env
    paths = shims.copy(ctx, ADAPTER, APP, ("agl-hook.js", "agl-inject.py", TMPL))
    paths.append(ctx.write_owned(shims.lib_dir(env, APP, "feishin-glass.css"), css(ctx)))
    w = shims.wrapper(ctx, ADAPTER, WRAPPER)
    paths.append(w)
    p = shims.launcher(ctx, FLATPAK + ".desktop", w, app_id=FLATPAK)
    if p:
        paths.append(p)
    return paths
