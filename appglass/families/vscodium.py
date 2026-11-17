"""electron-hook: VSCodium (flatpak com.vscodium.codium, Electron, VS Code OSS).

A forced adapter (off until apps.vscodium or apps.com.vscodium.codium is
enabled), the Feishin route with a VS Code stylesheet: the wrapper starts
VSCodium through its normal flatpak command with --verbose (the codium CLI
otherwise detaches the main process and its stderr) and a Node inspector on
127.0.0.1 (random port, --inspect-publish-uid=stderr, the session UUID read
only by the wrapper from a 0700 dir); agl-inject.py then requires agl-hook.js
in the main process, which clears the window background and injects
vscode-glass.css (the workbench painted once at the content level, every
full-size part transparent, menus, the quick input, widgets and
notifications left opaque). The inspector port stays open while VSCodium
runs: the reason this adapter is opt-in.

A few surfaces are painted on canvases from the theme colours, out of CSS
reach (B5b): the minimap, the overview ruler and the current line. A marked
block in the user's settings.json (edited, backed up; the user's settings
kept) sets workbench.colorCustomizations for those four keys only. A
settings.json with a workbench.colorCustomizations of its own is left
untouched (a warning names the keys to add by hand).

Files (owned; adopted hand files restored by remove):
  ~/.local/lib/appglass/vscodium/agl-hook.js, agl-inject.py
  ~/.local/lib/appglass/vscodium/vscode-glass.css.tmpl
  ~/.local/lib/appglass/vscodium/vscode-glass.css     rendered on apply and at launch
  ~/.local/bin/appglass-vscodium                      the launch wrapper
  ~/.local/share/applications/com.vscodium.codium.desktop -> the wrapper
  ~/.var/app/com.vscodium.codium/config/VSCodium/User/settings.json (edited)
niri: ^com\\.vscodium\\.codium$ (and code, code-oss: the same CSS fits them)
get opacity 1.0.
"""

import json
import os

from .. import shims
from ..core import Conflict
from . import zed

NAME = "vscodium"
ADAPTER = "electron-hook"
OPT_IN = True
FLATPAK = "com.vscodium.codium"
KEYS = (FLATPAK,)
APP_IDS = [r"^com\.vscodium\.codium$", r"^VSCodium$", r"^code$", r"^code-oss$"]
APP = "vscodium"
WRAPPER = "appglass-vscodium"
TMPL = "vscode-glass.css.tmpl"
CSS = "vscode-glass.css"
ROLES = (("surface", "101418"), ("surface_container", "1e2226"),
         ("surface_container_high", "282c30"))
COLORS = "workbench.colorCustomizations"
# canvas / JS painted from the theme: CSS cannot clear them
CANVAS = {"minimap.background": "#00000000", "editorOverviewRuler.background": "#00000000",
          "editor.lineHighlightBorder": "#00000000", "editor.lineHighlightBackground": "#ffffff0d"}


def installed(env):
    return shims.installed_flatpak(env, FLATPAK)


def css(ctx):
    lv = shims.levels(ctx)
    pairs = [("content", shims.jq_raw(lv["content"])),
             ("bar_over", shims.jq_raw(lv["bar_over_content"]))]
    pairs += [(r, shims.rgb(ctx, r, fb)) for r, fb in ROLES]
    return shims.fill(shims.source(ADAPTER, TMPL).decode("utf-8"), pairs)


def settings_path(env):
    return os.path.join(env.home, ".var", "app", FLATPAK, "config", "VSCodium", "User",
                        "settings.json")


def canvas(mode):
    out = dict(CANVAS)
    if mode == "light":
        out["editor.lineHighlightBackground"] = "#0000000d"
    return out


def block(values, comma):
    body = json.dumps({COLORS: values}, indent=2)
    inner = body.strip()[1:-1].strip("\n")        # '  "workbench.colorCustomizations": {...}'
    return "  %s\n%s%s\n  %s\n" % (zed.BEGIN, inner, "," if comma else "", zed.END)


def edit(ctx, text, path):
    base = zed.drop_block(text)
    settings = zed.parse(base, path)
    if COLORS in settings:
        raise Conflict("%s already has a %s of its own; left untouched (add %s there by hand)"
                       % (path, COLORS, ", ".join("%s %s" % kv for kv in sorted(canvas(ctx.mode).items()))))
    values = canvas(ctx.mode)
    if not base.strip():
        return "{\n%s}\n" % block(values, False)
    at = zed._code_start(base)
    if at < 0:
        raise Conflict("%s: no top-level object; left untouched" % path)
    comma = not zed.strip_jsonc(base[at + 1:]).lstrip().startswith("}")
    tail = base[at + 1:]
    if tail.startswith("\n"):
        tail = tail[1:]
    return base[:at + 1] + "\n" + block(values, comma) + tail


def undo(env, path, text):
    return zed.undo(env, path, text)


def settings(ctx):
    p = settings_path(ctx.env)
    if os.path.islink(p):
        ctx.warn("%s is a symlink (user-managed): the minimap, the overview ruler and the "
                 "current line stay opaque" % ctx.env.tilde(p))
        return None
    try:
        edit(ctx, ctx.read_text(p) or "", p)
    except Conflict as e:
        ctx.warn("%s: the minimap, the overview ruler and the current line stay opaque" % e)
        return None
    ctx.edit_text(p, lambda text: edit(ctx, text, p), undo=lambda text: undo(ctx.env, p, text))
    return p


def apply(ctx):
    env = ctx.env
    paths = shims.copy(ctx, ADAPTER, APP, ("agl-hook.js", "agl-inject.py", TMPL))
    paths.append(ctx.write_owned(shims.lib_dir(env, APP, CSS), css(ctx)))
    w = shims.wrapper(ctx, ADAPTER, WRAPPER)
    paths.append(w)
    p = shims.launcher(ctx, FLATPAK + ".desktop", w, app_id=FLATPAK)
    if p:
        paths.append(p)
    s = settings(ctx)
    if s:
        paths.append(s)
    return paths
