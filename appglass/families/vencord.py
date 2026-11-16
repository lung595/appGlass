"""electron-vencord: the official Discord with Vencord (a client mod).

A mod adapter: off until apps.vencord or apps.discord is enabled. Client
mods are against Discord's terms; appglass never installs Vencord itself
(the user does, with the official installer) and never owns it.

On apply:
  ~/.config/Vencord/themes/appglass-discord.css   owned: rendered from
      shims/electron-vencord/appglass-discord.css.tmpl with the DMS colours
      and the levels (the hook re-renders it)
  ~/.config/Vencord/settings/settings.json        merged: transparent = true,
      enabledThemes += dank-discord.css, appglass-discord.css (only when one
      is missing; remove puts the keys back)
The window gets its niri glass rule only while Vencord is in the newest
Discord host dir (app-*/resources/_app.asar): after a Discord update the
sync unit (bin/appglass-sync) re-injects it with the installer kept in
~/.local/share/appglass/VencordInstallerCli-linux.

Hand pieces this replaces, once adopted, are retired (deleted on apply,
restored by remove): ~/.local/bin/appglass-vencord and
~/.local/share/appglass/appglass-discord.css.tmpl. Not while a hand-made
~/.local/bin/appglass-sync, which calls them, still runs: they are kept as
they are until hook install (adopt does it) replaces that script.
"""

import json
import os
import re

from .. import shims
from ..core import Conflict

NAME = "vencord"
ADAPTER = "electron-vencord"
OPT_IN = True
KEYS = ("discord",)
APP_IDS = [r"^discord$"]
TMPL = "appglass-discord.css.tmpl"
THEMES = ["dank-discord.css", "appglass-discord.css"]
ROLES = ("on_surface_variant", "primary", "surface_container_highest",
         "surface_container_high", "surface_container", "surface")
RETIRED = (".local/bin/appglass-vencord", ".local/share/appglass/appglass-discord.css.tmpl")


def discord_dir(env):
    return env.config_path("discord")


def vencord_dir(env):
    return env.config_path("Vencord")


def installed(env):
    return os.path.isdir(discord_dir(env)) or bool(env.which("discord"))


def _version(name):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", name)]


def host_dir(env):
    """The newest app-* Discord host dir (sort -V), or None."""
    try:
        apps = [n for n in os.listdir(discord_dir(env)) if n.startswith("app-")]
    except OSError:
        return None
    return os.path.join(discord_dir(env), max(apps, key=_version)) if apps else None


def injected(env):
    h = host_dir(env)
    return h is not None and os.path.isfile(os.path.join(h, "resources", "_app.asar"))


def css(ctx):
    text = shims.source(ADAPTER, TMPL).decode("utf-8")
    for k in ROLES:
        try:
            v = ctx.colors(k)
        except Exception:
            continue
        text = text.replace("{{colors.%s.default.hex}}" % k, v)
    lv = shims.levels(ctx)
    text = text.replace("{{appglass.content_pct}}", shims.jq_pct(lv["content"]))
    text = text.replace("{{appglass.bar_over_pct}}", shims.jq_pct(lv["bar_over_content"]))
    if "{{" in text:
        raise Conflict("unresolved colours in the Discord theme (%s)"
                       % ", ".join(sorted(set(re.findall(r"\{\{([^}]*)\}\}", text)))))
    return text


def apply(ctx):
    env = ctx.env
    vd = vencord_dir(env)
    if not os.path.isdir(vd):
        raise Conflict("Vencord is not installed (%s missing): install it with the official "
                       "installer first" % env.tilde(vd))
    paths = [ctx.write_owned(os.path.join(vd, "themes", "appglass-discord.css"), css(ctx))]
    sp = os.path.join(vd, "settings", "settings.json")
    try:
        with open(sp) as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = None
    cur = cur if isinstance(cur, dict) else {}
    have = cur.get("enabledThemes") if isinstance(cur.get("enabledThemes"), list) else []
    if cur.get("transparent") is not True or any(t not in have for t in THEMES):
        paths.append(ctx.merge_json(sp, {"transparent": True,
                                         "enabledThemes": have + [t for t in THEMES
                                                                  if t not in have]}))
    from .. import hook
    live, kept = hook.hand_sync_live(ctx.app), []
    for rel in RETIRED:
        p = os.path.join(env.home, rel)
        if live and ctx.keep_adopted(p):
            kept.append(env.tilde(p))   # the hand sync script still uses it
            continue
        p = ctx.retire(p)
        if p:
            paths.append(p)
    if kept:
        ctx.warn_once("hand-sync", "kept %s: the hand-made %s still uses them; appglass "
                      "hook install replaces that script, then apply retires them"
                      % (", ".join(kept), env.tilde(hook.sync_path(env))))
    if injected(env):
        ctx.app_ids = list(APP_IDS)
    else:
        ctx.app_ids = []
        ctx.warn_once("not-injected", "Vencord is not in %s (a Discord update?): no glass "
                      "rule until the sync unit re-injects it"
                      % env.tilde(host_dir(env) or discord_dir(env)))
    return paths
