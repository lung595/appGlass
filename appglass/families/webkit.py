"""webkit-shim, generic: every host WebKitGTK app (GTK3 + WebKitGTK 4.x, as
Tauri / wry builds them) the engine routes here (Kiri, ...). Lian Li keeps
its own family (lianli: its own CSS from its theme variables).

The engine finds the apps by toolkit (detect: the binary links
libwebkit2gtk-4.x and libgtk-3), not by a list. The route loads code into
the app (an LD_PRELOAD), so it is injected (OPT_IN): each app goes live
once the hidden-session check passed for its version (engine gate per
fingerprint), or when you switch it on yourself (apps.<key>.enabled or
apps.webkit.enabled); an app held opaque gets its plain launcher back.

appglass-wk.so clears the WebView background, gives the window an RGBA
visual and injects two files: webkit-glass.css (a USER stylesheet with the
levels, rendered at every launch) and webkit-glass.js, which reads the
page's own colours and marks it: the page colour at the content level,
large boxes of another colour (sidebars, toolbars, cards) at the bar level,
popups (dialogs, menus, listboxes, tooltips, floating boxes) untouched and
opaque, text never touched. The unfocused fade: html.agl-inactive (the
shim's focus script) eases the content to the inactive level.

Files (all owned, removed by remove):
  ~/.local/lib/appglass/webkit/appglass-wk.so        the shim (stamp: source + gcc)
  ~/.local/lib/appglass/webkit/appglass-wk.c         its source, for reference
  ~/.local/lib/appglass/webkit/webkit-glass.js
  ~/.local/lib/appglass/webkit/webkit-glass.css.tmpl
  ~/.local/lib/appglass/webkit/webkit-glass.css      rendered on apply and at launch
  ~/.local/bin/appglass-webkit                       the launch wrapper (<key> <command> ...)
  ~/.local/share/applications/<app>.desktop          Exec= appglass-webkit <key> <the app's Exec>
"""

from .. import shims
from ..core import Conflict

NAME = "webkit"
ADAPTER = "webkit-shim"
# the engine routes every host GTK3 WebKitGTK app here (ctx.records())
GENERIC = True
# a preload: each app is checked in the hidden session first (engine gate)
OPT_IN = True
KEYS = ()
APP_IDS = []
LIB = "webkit"
WRAPPER = "appglass-webkit"
TMPL = "webkit-glass.css.tmpl"
JS = "webkit-glass.js"


def installed(env):
    return False      # installed when the engine routes an app here (core.installed)


def accepts(rec):
    """None for a host app that links WebKitGTK 4.x with GTK3 (the shim's
    window code is GTK3), else why not."""
    if rec.get("flatpak"):
        return "WebKitGTK flatpak: a host-built preload does not load in its runtime (ABI)"
    if rec.get("user_only"):
        return "a launcher of yours with no system one: left as it is"
    ev = " ".join(rec.get("evidence") or ())
    if "libwebkitgtk-6.0" in ev or "libgtk-4" in ev:
        return "WebKitGTK 6 (GTK4): the shim's window code is GTK3 only"
    if "libwebkit2gtk-4." not in ev:
        return "no libwebkit2gtk-4.x in its binary: the shim has nothing to hook"
    if "libgtk-3" not in ev:
        return "no libgtk-3 in its binary: the shim's window code is GTK3 only"
    return None


def verify_mask(rec):
    """The hidden check runs the app off the network and away from what it
    reaches under /run (a daemon or container engine socket its binary
    names, /run/<its name>): a throwaway HOME does not make a throwaway
    daemon (Kiri drives the real container engine by /run/kiri/docker.sock)."""
    from .. import verify
    keys = [rec["key"]] + [n for n in rec.get("names") or () if "/" not in n]
    return {"hide": verify.run_paths(rec, keys=keys), "nonet": True}


def css(ctx):
    lv = shims.levels(ctx)
    return shims.fill(shims.source(ADAPTER, TMPL).decode("utf-8"),
                      [("content", shims.jq_pct(lv["content"])),
                       ("bar_over", shims.jq_pct(lv["bar_over_content"])),
                       ("inactive", shims.jq_pct(lv["inactive"])), ("fade", lv["fade"])])


def launcher(text, wrapper_path, key):
    """Every Exec= line starts the app through the wrapper (its key first)."""
    pre = "%s %s " % (shims.desktop_quote(wrapper_path), shims.desktop_quote(key))
    out = []
    for line in text.splitlines(True):
        if line.startswith("Exec=") and line[5:].strip() and not line.startswith("Exec=" + pre):
            line = "Exec=" + pre + line[5:]
        out.append(line)
    return "".join(out)


def apply(ctx):
    env = ctx.env
    paths = [shims.c_shim(ctx, ADAPTER, LIB, "appglass-wk.c", "appglass-wk.so")]
    paths += shims.copy(ctx, ADAPTER, LIB, ("appglass-wk.c", TMPL, JS))
    paths.append(ctx.write_owned(shims.lib_dir(env, LIB, "webkit-glass.css"), css(ctx)))
    w = shims.wrapper(ctx, ADAPTER, WRAPPER)
    paths.append(w)
    # held opaque by the engine (S7): a launcher written before goes back to
    # the system text until the next fingerprint; one you switched off too
    for rec in ctx.records(plain=True) + ctx.switched_off():
        did = rec["desktop_id"]
        if ctx.owns(ctx.data_path("applications", did)):
            p = ctx.desktop_override(did, lambda t: t)
            if p:
                paths.append(p)
    ids = []
    for rec in ctx.records():
        try:
            p = ctx.desktop_override(rec["desktop_id"],
                                     lambda t, k=rec["key"]: launcher(t, w, k))
        except Conflict as ex:
            ctx.warn("%s: %s" % (rec["key"], ex))
            continue
        if p:
            paths.append(p)
            ids += [x for x in rec.get("app_ids") or () if x not in ids]
    ctx.app_ids = ids
    return paths
