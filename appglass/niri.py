"""niri: one generated rules file + one include line in config.kdl.

$XDG_CONFIG_HOME/niri/appglass.kdl holds up to five window-rules, in order:

  fallback "opaque" a catch-all ``opacity 1.0`` (browsers excluded), before
                    the glass block: windows appglass cannot glass stay sharp
  glass             a match line per applied app, ``opacity 1.0``: the app
                    paints its own translucency over the blur (an app
                    switched off on its own too, while its glass files stay:
                    never in the fallback block as well, see kept_glass)
  blend             the glass apps whose window says it is opaque
                    (BLEND_FAMILIES) at ``opacity 0.999``: at 1.0 niri
                    believes it and skips what is behind (black, or a
                    background that flickers)
  fallback "value"  the detected fallback apps at ``opacity <value>``
  games             ``opacity 1.0``, blur off, popups 1.0

App-ids the browserGlass plugin covers are left out of every block (its
dms-browser-glass.kdl is included later and owns them). config.kdl gets
``include optional=true "appglass.kdl"`` right after the line that includes
"dms/windowrules.kdl" (the global "Glass blur" rule), so the later rule wins
and the blur stays on. Without that line the include goes at the end.

An include the user took out of config.kdl since apply (deleted or
commented) stays out, on the hook and on a manual apply, warned once; a
deleted config.kdl or appglass.kdl stays deleted (appglass.kdl until a
manual apply). remove + apply puts them back.
"""

import os
import re

from .core import Conflict

FILE = "appglass.kdl"
INCLUDE = 'include optional=true "%s"' % FILE
_HAS_INCLUDE = re.compile(r'^\s*include\b[^\n]*"appglass\.kdl"', re.M)
_DMS_RULES = re.compile(r'^\s*include\b[^\n]*"dms/windowrules\.kdl"[^\n]*$', re.M)


def config_path(env):
    p = env.environ.get("NIRI_CONFIG")
    return os.path.abspath(p) if p else env.config_path("niri", "config.kdl")


def _kdl_string(s):
    if '"#' not in s:
        return 'r#"%s"#' % s
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


# browserGlass's APP_IDS (the DMS plugin browserGlass): delegated, never ours
BROWSERGLASS_IDS = (
    "firefox", "firefox-esr", "librewolf", "zen", "zen-browser", "zen-beta", "floorp",
    "waterfox", "org.mozilla.firefox", "io.gitlab.librewolf-community",
    "app.zen_browser.zen", "one.ablaze.floorp", "net.waterfox.waterfox",
)
BROWSERGLASS_RE = "^(%s)$" % "|".join(a.replace(".", "\\.") for a in BROWSERGLASS_IDS)
GAME_IDS = (r"^steam_app_\d+$", r"^gamescope$")
FALLBACK_MODES = ("opaque", "value", "off")
# these windows mark themselves opaque (a whole-window wl_surface.set_opaque_region)
# while the glass paints them with alpha: Chromium without transparent (the
# Electron hook apps, Obsidian) and GTK3 (the WebKit shim apps: GTK sets it
# from the window's CSS background; the shim clears it too, the rule is the
# second guard). Below 1.0 niri blends them (docs/routes.md)
BLEND_FAMILIES = ("feishin", "vscodium", "obsidian", "webkit", "lianli")
BLEND_OPACITY = "0.999"


def delegated(app_id_re):
    """True when the app-id regex matches one of browserGlass's app-ids."""
    try:
        r = re.compile(app_id_re)
    except re.error:
        return False
    return any(r.search(a) for a in BROWSERGLASS_IDS)


_LITERAL = re.compile(r"^\^((?:[^\\^$.|?*+()\[\]{}]|\\.)*)\$$")


def _covered(a, ids):
    """True when a is one of ids, or an anchored literal app-id (^name$)
    that another of ids matches (^solaar$ under ^(solaar|nvidia-settings)$)."""
    if a in ids:
        return True
    m = _LITERAL.match(a)
    if not m:
        return False
    name = re.sub(r"\\(.)", r"\1", m.group(1))
    for b in ids:
        try:
            if b != a and re.search(b, name):
                return True
        except re.error:
            continue
    return False


def _ids(ids, skip=()):
    out = []
    for a in ids:
        if a not in out and not _covered(a, skip) and not delegated(a):
            out.append(a)
    return out


def _num(v):
    return "1.0" if float(v) >= 1 else "%.2f" % float(v)


def render(app_ids, fallback="off", value=0.70, fallback_ids=(), games=None, blend_ids=()):
    """The rules file. With the defaults only the glass block (the old file);
    games=() writes the games block with the default game app-ids; blend_ids
    (glass app-ids) get opacity 0.999."""
    if fallback not in FALLBACK_MODES:
        raise ValueError("fallback mode %r" % fallback)
    glass = _ids(app_ids)
    lines = [
        "// appglass: generated, do not edit: rewritten by appglass apply,",
        "// removed by appglass remove. Included after dms/windowrules.kdl, so",
        "// these rules win over the global Glass blur rule and the blur stays on.",
    ]
    if fallback == "opaque":
        lines += [
            "",
            "// fallback: windows appglass cannot glass stay opaque (sharp text)",
            "window-rule {",
            "    exclude app-id=%s" % _kdl_string(BROWSERGLASS_RE),
            "    opacity 1.0",
            "}",
        ]
    if glass:
        lines += ["", "// glass: apps that paint their own glass", "window-rule {"]
        lines += ["    match app-id=%s" % _kdl_string(a) for a in glass]
        lines += ["    opacity 1.0", "}"]
    blend = [a for a in _ids(blend_ids) if a in glass]
    if blend:
        lines += ["", "// glass apps whose window says it is opaque: niri blends them",
                  "window-rule {"]
        lines += ["    match app-id=%s" % _kdl_string(a) for a in blend]
        lines += ["    opacity %s" % BLEND_OPACITY, "}"]
    fb = _ids(fallback_ids, skip=glass)
    if fallback == "value" and fb:
        lines += ["", "// fallback: whole-window opacity (text fades too)", "window-rule {"]
        lines += ["    match app-id=%s" % _kdl_string(a) for a in fb]
        lines += ["    opacity %s" % _num(value), "}"]
    gm = [] if games is None else _ids(list(GAME_IDS) + list(games), skip=glass)
    if gm:
        lines += ["", "// games: opaque, no blur behind", "window-rule {"]
        lines += ["    match app-id=%s" % _kdl_string(a) for a in gm]
        lines += ["    opacity 1.0", "    background-effect {", "        blur false",
                  "    }", "    popups {", "        opacity 1.0", "    }", "}"]
    lines.append("")
    return "\n".join(lines)


def add_include(text):
    if _HAS_INCLUDE.search(text):
        return text
    m = _DMS_RULES.search(text)
    if m:
        end = m.end()
        nl = "\n" if end < len(text) and text[end] == "\n" else ""
        if nl:
            return text[:end + 1] + INCLUDE + "\n" + text[end + 1:]
        return text[:end] + "\n" + INCLUDE + "\n"
    if text and not text.endswith("\n"):
        text += "\n"
    return text + INCLUDE + "\n"


def _same(text):
    return text


def strip_include(text):
    return re.sub(r'(?m)^[ \t]*include\b[^\n]*"appglass\.kdl"[^\n]*\n?', "", text)


def undo_for(app, path):
    if os.path.abspath(path) == config_path(app.env):
        return strip_include
    return None


def app_ids(app, extra=()):
    """The glass app-ids of the applied families. A family whose every app
    runs plain (the engine's plain/ markers: waiting, stale, paused after
    failed launches) is left out, so the catch-all keeps them opaque."""
    from . import engine
    plain = set(engine.store(app).plain)
    ids = []
    for name in app.state.families():
        keys = list(getattr(app.families.get(name), "KEYS", ()) or ())
        if keys and all(k in plain for k in keys):
            continue
        for a in app.state.owners[name].get("app_ids", []):
            if a not in ids:
                ids.append(a)
    for a in extra:
        if a not in ids:
            ids.append(a)
    # one app of a generic family (gtk3, qtstyle, gtk4) that runs plain
    drop = set()
    for k in plain:
        r = engine.record_for(app, k)
        drop.update((r or {}).get("app_ids") or ())
    return [a for a in ids if a not in drop]


def validate(env, cfg):
    """(ok, output). ok is None when niri is not on PATH."""
    if not env.which("niri"):
        return None, "niri not found"
    r = env.run(["niri", "validate", "-c", cfg], timeout=30)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


ADOPTED_STUB = """\
// appglass: this file was hand-made; appglass adopted it and keeps it empty.
// Its rules live in appglass.kdl now (fallback.mode in appglass settings).
// appglass remove puts the original back.
"""


def is_game_id(rx):
    return rx in GAME_IDS or bool(re.match(r"^\^steam_app_\d+\$$", rx))


def _adopted(app):
    o = app.state.owners.get("niri", {})
    return sorted(p for p, r in o.get("files", {}).items() if r.get("adopted"))


def kept_glass(app, kept):
    """The app-ids of the apps switched off on their own whose glass is
    still there (core._niri_ids): their family applied, and their launcher
    still its file. They stay in the glass block; in the fallback block
    their glass would get the fallback opacity on top (faded twice)."""
    ids = []
    for k in kept:
        if not isinstance(k, dict):
            continue
        o = app.state.owners.get(k.get("family"))
        if o is None:
            continue
        f = k.get("file")
        if f and (f not in (o.get("files") or {}) or not os.path.lexists(f)):
            continue
        ids += [a for a in k.get("ids") or () if a not in ids]
    return ids


def rule_inputs(app):
    """render() keyword arguments from settings.json and the detected apps
    (apply --all sets app.fallback_ids/game_ids; other runs reuse the ones
    recorded at the last apply --all)."""
    from . import settings as _settings
    fb = app.settings.get("fallback", {})
    rec = app.state.owners.get("niri", {})
    fallback_ids = getattr(app, "fallback_ids", None)
    game_ids = getattr(app, "game_ids", None)
    if fallback_ids is None:
        fallback_ids = rec.get("fallback_ids", [])
    if game_ids is None:
        game_ids = rec.get("game_ids", [])
    glass_ids = getattr(app, "glass_ids", None)
    if glass_ids is None:
        glass_ids = rec.get("glass_ids", [])
    kept = getattr(app, "kept_ids", None)
    if kept is None:
        kept = rec.get("kept_ids", [])
    blend = []
    for name in BLEND_FAMILIES:
        blend += [a for a in app.state.owners.get(name, {}).get("app_ids", []) if a not in blend]
    return {
        "fallback": fb.get("mode", "opaque"),
        "value": fb.get("value", 0.70),
        "blend_ids": blend,
        "fallback_ids": list(fallback_ids),
        "games": list(game_ids),
        "_glass": list(glass_ids),
        "_kept": list(kept),
        "_wanted": os.path.isfile(_settings.path(app.env))
        or bool(fallback_ids) or bool(game_ids) or bool(glass_ids) or bool(_adopted(app)),
    }


def sync(app, dry_run=False, extra_ids=()):
    kw = rule_inputs(app)
    wanted = kw.pop("_wanted")
    # host GTK4 apps held opaque (a GTK4 game): they read the glass CSS all
    # the same, so they get the glass block (blur on, opacity 1.0)
    ids = app_ids(app, list(extra_ids) + kw.pop("_glass") + kept_glass(app, kw.pop("_kept")))
    if not ids and not wanted:
        if "niri" in app.state.owners and not dry_run and not app.event:
            app.remove_owner("niri")
            app.info("niri: no glass apps, rule removed")
        elif "niri" in app.state.owners and not dry_run:
            app.info("niri: no glass apps, rule left as is (appglass apply or remove "
                     "takes it out)")
        return []
    cfg = config_path(app.env)
    ctx = app.ctx("niri")
    if not os.path.isfile(cfg) and not ctx.deleted_since_apply(cfg):
        app.warn("niri: %s not found; no opacity rule written (the apps stay under "
                 "the global niri opacity)" % cfg)
        return []
    try:
        rules = os.path.join(os.path.dirname(cfg), FILE)
        if ctx.deleted_since_apply(cfg) and not os.path.lexists(rules):
            ctx.kept_absent.add(rules)  # no config.kdl: do not bring the rule back
        else:
            ctx.write_owned(rules, render(ids, **kw))
        fn = add_include
        if ctx.changed_since_apply(cfg) and not ctx.deleted_since_apply(cfg):
            if not _HAS_INCLUDE.search(ctx.read_text(cfg) or ""):
                # the user took the include out (deleted or commented): an
                # opt-out the theme hook must not undo
                ctx.warn_once("opt-out", "%s no longer includes %s; kept (the glass apps "
                              "stay under the global niri opacity; remove + apply puts "
                              "the include back)" % (app.env.tilde(cfg), FILE))
                fn = _same
        # a deleted config.kdl stays deleted (the core warns once)
        ctx.edit_text(cfg, fn, undo=strip_include)
        for p in _adopted(app):
            ctx.write_owned(p, ADOPTED_STUB)
        changed = app.commit(ctx, dry_run=dry_run)
        if not dry_run and "niri" in app.state.owners:
            o = app.state.owners["niri"]
            for k in ("fallback_ids", "game_ids", "glass_ids", "kept_ids"):
                v = getattr(app, k, None)
                if v is not None:
                    if v:
                        o[k] = list(v)
                    else:
                        o.pop(k, None)
            app.state.save()
    except Conflict as ex:
        app.warn("niri: skipped: %s" % ex)
        return []
    finally:
        for m in ctx.messages:
            app.warn("niri: %s" % m)
    if dry_run:
        if changed:
            app.info("niri: would write %s" % ", ".join(changed))
        return changed
    o = app.state.owners.get("niri") or {}
    if (changed or o.get("validate_failed")) and os.path.isfile(cfg):
        ok, out = validate(app.env, cfg)
        if ok is False and app.event:
            # an event (the hook, the plugin's sync) takes nothing out: the
            # user's own config may be what fails. The next command the user
            # types validates again and takes the rule out
            o["validate_failed"] = True
            app.state.save()
            app.error("niri validate failed; an event run leaves the rule as is (appglass "
                      "apply validates again and takes it out, appglass remove does):\n%s"
                      % out)
            return changed
        if ok is False and not app.event:
            # the rule breaks the niri config: taken out again (the ring
            # holds the files as they were)
            app.remove_owner("niri")
            app.error("niri validate failed, rule removed again:\n%s" % out)
            return []
        if ok is None:
            app.warn("niri: not on PATH, config not validated")
        elif o.pop("validate_failed", None):
            app.state.save()
    if changed:
        app.info("niri: wrote %s" % ", ".join(changed))
    return changed


__all__ = ["render", "add_include", "strip_include", "sync", "validate", "config_path"]
