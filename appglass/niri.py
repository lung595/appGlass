"""niri: one generated rules file + one include line in config.kdl.

$XDG_CONFIG_HOME/niri/appglass.kdl holds a single window-rule with a match
line per applied family and ``opacity 1.0``. config.kdl gets
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


def render(app_ids):
    lines = [
        "// appglass: apps that paint their own glass. Generated, do not edit:",
        "// rewritten by appglass apply, removed by appglass remove.",
        "// Included after dms/windowrules.kdl, so opacity 1.0 wins over the",
        "// global Glass blur rule and the blur stays on.",
        "window-rule {",
    ]
    for a in app_ids:
        lines.append("    match app-id=%s" % _kdl_string(a))
    lines += ["    opacity 1.0", "}", ""]
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


def sync(app, dry_run=False, extra_ids=()):
    ids = app_ids(app, extra_ids)
    if not ids:
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
            ctx.write_owned(rules, render(ids))
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
        changed = app.commit(ctx, dry_run=dry_run)
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
