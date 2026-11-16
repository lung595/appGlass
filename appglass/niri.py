"""niri: one generated rules file + one include line in config.kdl.

$XDG_CONFIG_HOME/niri/appglass.kdl holds up to five window-rules, in order:

  fallback "opaque" a catch-all ``opacity 1.0`` (browsers excluded), before
                    the glass block: windows appglass cannot glass stay sharp
  glass             a match line per applied app, ``opacity 1.0``: the app
                    paints its own translucency over the blur
  fallback "value"  the detected fallback apps at ``opacity <value>``
  inactive          glass apps that are not focused, ``opacity <inactive>``
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

from .core import AppglassError, Conflict

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


def delegated(app_id_re):
    """True when the app-id regex matches one of browserGlass's app-ids."""
    try:
        r = re.compile(app_id_re)
    except re.error:
        return False
    return any(r.search(a) for a in BROWSERGLASS_IDS)


def _ids(ids, skip=()):
    out = []
    for a in ids:
        if a not in out and a not in skip and not delegated(a):
            out.append(a)
    return out


def _num(v):
    return "1.0" if float(v) >= 1 else "%.2f" % float(v)


def render(app_ids, fallback="off", value=0.70, fallback_ids=(), games=None, inactive=None):
    """The rules file. With the defaults only the glass block (the old file);
    games=() writes the games block with the default game app-ids."""
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
    fb = _ids(fallback_ids, skip=glass)
    if fallback == "value" and fb:
        lines += ["", "// fallback: whole-window opacity (text fades too)", "window-rule {"]
        lines += ["    match app-id=%s" % _kdl_string(a) for a in fb]
        lines += ["    opacity %s" % _num(value), "}"]
    if inactive is not None and glass:
        lines += ["", "// glass apps that are not focused", "window-rule {"]
        lines += ["    match app-id=%s is-active=false" % _kdl_string(a) for a in glass]
        lines += ["    opacity %s" % _num(inactive), "}"]
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
    ids = []
    for name in app.state.families():
        for a in app.state.owners[name].get("app_ids", []):
            if a not in ids:
                ids.append(a)
    for a in extra:
        if a not in ids:
            ids.append(a)
    return ids


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
    return {
        "fallback": fb.get("mode", "opaque"),
        "value": fb.get("value", 0.70),
        "inactive": fb.get("inactive"),
        "fallback_ids": list(fallback_ids),
        "games": list(game_ids),
        "_wanted": os.path.isfile(_settings.path(app.env))
        or bool(fallback_ids) or bool(game_ids) or bool(_adopted(app)),
    }


def sync(app, dry_run=False, extra_ids=()):
    ids = app_ids(app, extra_ids)
    kw = rule_inputs(app)
    wanted = kw.pop("_wanted")
    if not ids and not wanted:
        if "niri" in app.state.owners and not dry_run:
            app.remove_owner("niri")
            app.info("niri: no glass apps, rule removed")
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
            for k in ("fallback_ids", "game_ids"):
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
    if changed and os.path.isfile(cfg):
        ok, out = validate(app.env, cfg)
        if ok is False:
            app.remove_owner("niri")
            app.error("niri validate failed, rule removed again:\n%s" % out)
            return []
        if ok is None:
            app.warn("niri: not on PATH, config not validated")
    if changed:
        app.info("niri: wrote %s" % ", ".join(changed))
    return changed


__all__ = ["render", "add_include", "strip_include", "sync", "validate", "config_path",
           "AppglassError"]
