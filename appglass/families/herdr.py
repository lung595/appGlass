"""Herdr (gpui): an alpha theme, a glass copy of the main layout, selected.

Herdr's home is $HERDR_APP_HOME, else $XDG_CONFIG_HOME/herdr-app. appglass
writes there (docs/gpu.md):

- themes/appglass.json (owned): DMS colours. ``colors`` takes #rrggbbaa:
  canvas (behind the cards) = surface at the content alpha, chrome (sidebar,
  tab bar, status bar) = surface at the bar alpha, background (terminals and
  cards) fully clear so the canvas shows through once. muted, dim and border
  are solid (Herdr derives them as translucent foreground, which fades the
  text on glass). popover/surface/raised are left to Herdr, so popups stay
  opaque. Every text colour (foreground, muted, dim, the 16 ANSI colours) is
  moved toward white/black until it reaches 2.25:1 on the glass over any
  backdrop; ANSI black/magenta/bright black come from outline / tertiary /
  on_surface_variant, as for Alacritty.
- layouts/appglass.json (owned): derived at every apply from Herdr's own
  layouts/main.json (Herdr writes its shipped layouts into its home on every
  start, and never updates clones): root window_blur, theme appglass,
  terminal_opacity 0 and a clear background; the sidebar column loses its
  background (its mods already paint chrome, a second one stacks); work-body
  paints the canvas. No main.json yet (Herdr never started) or a main.json
  without those nodes: the family is skipped with a warning.
- shared.json: "layout": "appglass" merged in (other keys kept; remove puts
  the old value back, unless Herdr switched to another layout since). Once
  Herdr has switched away from the glass layout (another "layout" value
  after an apply), re-apply keeps that choice (warned once) and still
  updates the theme and layout files; remove + apply selects the glass
  again.
"""

import copy
import json
import os

from ..core import Conflict, norm_hex, readable, worst_contrast

NAME = "herdr"
APP_IDS = [r"^herdr-app$"]

LAYOUT = "appglass"
THEME = "appglass"
TARGET = 2.25              # >= 2:1 with a margin for antialiasing
FLOOR = 2.0                # below this a text colour is a bug: warn
# ANSI index -> matugen role (dank16term's 0/5/8 are unreadable on glass)
ANSI_ROLES = {0: "outline", 5: "tertiary", 8: "on_surface_variant"}
SIDEBAR = "sidebar"
WORK_BODY = "work-body"


def app_home(env):
    h = env.environ.get("HERDR_APP_HOME")
    if h and os.path.isabs(h):
        return os.path.abspath(h)
    return env.config_path("herdr-app")


def installed(env):
    return (env.which("herdr-app") is not None
            or os.path.isfile(env.data_path("herdr-app", "herdr-app")))


def _term16(ctx):
    """The 16 DMS terminal colours: hook (dank16term) first, else dank16."""
    t16, _ = ctx.term16
    return t16 or ctx.dank16


def theme(ctx):
    """The theme as a dict (rendered with json.dumps)."""
    lv = ctx.levels
    bg = ctx.colors("surface")
    fg = ctx.colors("on_surface")

    def text(c):
        return readable(c, bg, lv.content, TARGET)

    t16 = _term16(ctx)
    ansi = []
    for i in range(16):
        role = ANSI_ROLES.get(i)
        if role:
            c = ctx.colors(role)
        elif t16:
            c = t16[i]
        else:
            # no DMS terminal palette at all: ANSI from matugen roles
            c = ctx.colors(("outline", "error", "tertiary", "secondary", "primary",
                            "tertiary", "secondary", "on_surface")[i % 8])
        ansi.append(text(norm_hex(c)))
    return {
        "background": bg,
        "foreground": text(fg),
        "selection": ctx.colors("primary_container"),
        "cursor": ctx.colors("primary"),
        "ansi": ansi,
        "colors": {
            "canvas": bg + ctx.alpha_hex(lv.content),
            "chrome": bg + ctx.alpha_hex(lv.bar),
            "background": bg + "00",
            "muted": text(ctx.colors("on_surface_variant")),
            "dim": text(ctx.colors("outline")),
            "border": ctx.colors("outline_variant"),
        },
    }


def _nodes(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _nodes(v)


def layout(main):
    """The glass layout from Herdr's main layout (a parsed dict)."""
    if not isinstance(main, dict) or not isinstance(main.get("children"), list):
        raise ValueError("not a layout tree")
    out = copy.deepcopy(main)
    found = set()
    for n in _nodes(out.get("children")):
        if n.get("id") == SIDEBAR:
            n["background"] = None
            found.add(SIDEBAR)
        elif n.get("id") == WORK_BODY:
            n["background"] = "canvas"
            found.add(WORK_BODY)
    missing = {SIDEBAR, WORK_BODY} - found
    if missing:
        raise ValueError("no %s node" % " / ".join(sorted(missing)))
    out["window_blur"] = True
    out["theme"] = THEME
    out["terminal_opacity"] = 0
    out["background"] = "#00000000"
    return out


def _dump(obj):
    return json.dumps(obj, indent=2) + "\n"


def verify_seed(env):
    """The hidden check's first run: Herdr's onboarding marked finished in
    the throwaway shared.json (merged over the staged glass keys), or its
    Welcome dialog covers about 75 % of the window and the shot measures
    the dialog. The hidden session's Herdr home is the XDG default."""
    return {os.path.join(".config", "herdr-app", "shared.json"): {"frame.welcomed": "finished"}}


def apply(ctx):
    home = app_home(ctx.env)
    main_path = os.path.join(home, "layouts", "main.json")
    text = ctx.read_text(main_path)
    if text is None:
        raise Conflict("%s not found: start Herdr once (it writes its layouts), "
                       "then run appglass apply again" % main_path)
    try:
        lay = layout(json.loads(text))
    except ValueError as ex:
        raise Conflict("%s: cannot derive the glass layout (%s)" % (main_path, ex))
    theme_path = os.path.join(home, "themes", THEME + ".json")
    layout_path = os.path.join(home, "layouts", LAYOUT + ".json")
    shared = os.path.join(home, "shared.json")
    th = theme(ctx)
    _check_contrast(ctx, th)
    ctx.write_owned(theme_path, _dump(th))
    ctx.write_owned(layout_path, _dump(lay))
    values = {"layout": LAYOUT}
    chosen = _current_layout(ctx, shared)
    if ctx._record(shared) is not None and chosen not in (None, LAYOUT):
        # Herdr switched to another layout since the last apply: keep it
        ctx.warn_once("layout", "Herdr's layout is %r, not %r; kept (remove + "
                      "apply selects the glass layout again)" % (chosen, LAYOUT))
        values = {}
    ctx.merge_json(shared, values)
    return [theme_path, layout_path, shared]


def _current_layout(ctx, path):
    text = ctx.read_text(path)
    try:
        obj = json.loads(text) if text and text.strip() else {}
    except ValueError:
        return None          # merge_json reports the bad file
    return obj.get("layout") if isinstance(obj, dict) else None


def _check_contrast(ctx, th):
    """Warn when a text colour cannot reach 2:1 on this glass (very low
    foregroundLayerTransparency): readable() then falls back to white/black."""
    bg, a = th["background"], ctx.levels.content
    texts = [th["foreground"], th["colors"]["muted"], th["colors"]["dim"]] + th["ansi"]
    worst = min(worst_contrast(c, bg, a) for c in texts)
    if worst < FLOOR:
        ctx.warn("content alpha %.2f is too clear for readable text (worst %.2f:1 "
                 "< 2:1); raise foregroundLayerTransparency" % (a, worst))
