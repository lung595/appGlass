"""Obsidian: a vault CSS snippet that turns the window into glass.

For every vault listed in Obsidian's obsidian.json (flatpak:
~/.var/app/md.obsidian.Obsidian/config/obsidian/obsidian.json, native:
$XDG_CONFIG_HOME/obsidian/obsidian.json, key .vaults[].path) appglass writes
<vault>/.obsidian/snippets/appglass.css (owned) and adds "appglass" to
"enabledCssSnippets" in <vault>/.obsidian/appearance.json (other keys and
snippets kept, file created when missing, restored on remove). A snippet the
user turned off in Obsidian since stays off: the hook does not turn it back
on.

Obsidian clears its window background by itself as soon as the page
background is not opaque, so the snippet is enough (docs/electron.md). It
clears every full-size layout layer and paints each region once: content at
the content level, ribbon/sidebars/tab bar/status bar at the bar level,
menus, modals, popovers, notices and tooltips opaque. Text and icon colours
come from DMS and are moved toward white (dark glass) or black (light glass)
until opaque text reaches 2.25:1 over any backdrop; icons get no opacity.

The same colours go under body.theme-dark and body.theme-light: they follow
the DMS palette mode, whatever Obsidian's own theme setting is. Obsidian
reloads a changed snippet live, so a theme change shows up without a
restart.
"""

import json
import os

from .. import inactive
from ..core import Conflict, hex_to_rgb, mix, norm_hex, readable, rgb_to_hex

NAME = "obsidian"
APP_IDS = [r"^md\.obsidian\.Obsidian$", r"^obsidian$"]

FLATPAK_ID = "md.obsidian.Obsidian"
SNIPPET = "appglass"
CONFIG_DIR = ".obsidian"
TARGET = 2.25          # >= 2:1 with a margin for antialiasing
CODE_TINT = 0.04       # --background-primary-alt (code blocks) over the content
TAB_TINT = 0.06        # --tab-background-active over the tab bar

# Obsidian's named colours. Syntax highlighting (--code-operator/tag red,
# -value purple, -important orange, -keyword pink, -function yellow, -string
# green, -property cyan), callouts, highlights, tags in the graph, canvas and
# mermaid all derive from them, so text in those colours is only readable on
# glass when these are. They come from the DMS terminal palette (hook
# dank16term, else dms-colors.json dank16: 1 red, 2 green, 3 yellow, 4 blue,
# 6 cyan; DMS's colour 5 is not a magenta, so purple, orange and pink are
# mixed), else Obsidian's own defaults; then lifted like the other text.
ACCENTS = ("red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink")
OBSIDIAN_ACCENTS = {
    "dark": {"red": "#fb464c", "orange": "#e9973f", "yellow": "#e0de71",
             "green": "#44cf6e", "cyan": "#53dfdd", "blue": "#027aff",
             "purple": "#a882ff", "pink": "#fa99cd"},
    "light": {"red": "#e93147", "orange": "#ec7500", "yellow": "#e0ac00",
              "green": "#08b94e", "cyan": "#00bfbc", "blue": "#086ddd",
              "purple": "#7852ee", "pink": "#d53984"},
}


def flatpak_config(env):
    return env.home_path(".var", "app", FLATPAK_ID, "config", "obsidian", "obsidian.json")


def native_config(env):
    return env.config_path("obsidian", "obsidian.json")


def flatpak_installed(env):
    # look at the installations instead of running `flatpak info`: that one
    # creates ~/.local/share/flatpak/{.changed,repo} in a HOME without them
    for base in (env.data_path("flatpak"), "/var/lib/flatpak"):
        if os.path.isdir(os.path.join(base, "app", FLATPAK_ID)):
            return True
    return os.path.isfile(flatpak_config(env))


def installed(env):
    return bool(env.which("obsidian") or flatpak_installed(env)
                or os.path.isfile(native_config(env)))


def vaults(env, warn=None, unreadable=None):
    """Vault directories from every obsidian.json, in order, without duplicates.

    An obsidian.json that cannot be read is warned about and appended to
    `unreadable` (a list) when given.
    """
    warn = warn or (lambda m: None)
    out, seen = [], set()
    for cfg in (flatpak_config(env), native_config(env)):
        if not os.path.isfile(cfg):
            continue
        try:
            with open(cfg, "rb") as f:
                data = json.loads(f.read().decode("utf-8"))
        except (OSError, ValueError) as ex:
            warn("cannot read %s: %s" % (cfg, ex))
            if unreadable is not None:
                unreadable.append(cfg)
            continue
        vs = data.get("vaults") if isinstance(data, dict) else None
        if not isinstance(vs, dict):
            continue
        for v in vs.values():
            p = v.get("path") if isinstance(v, dict) else None
            if not isinstance(p, str) or not os.path.isabs(p):
                continue
            if not os.path.isdir(p):
                warn("vault %s (in %s) does not exist, skipped" % (p, cfg))
                continue
            key = os.path.realpath(p)
            if key in seen:
                continue
            seen.add(key)
            out.append(os.path.abspath(p))
    return out


def skip_reason(env, rec):
    """Why a glass Obsidian is plain: no vault to put the snippet in (apply
    skips the family), else None. An obsidian.json that does not read says
    nothing (apply keeps the files of an earlier run)."""
    unreadable = []
    if vaults(env, unreadable=unreadable) or unreadable:
        return None
    return "no Obsidian vaults found in %s or %s" % (env.tilde(flatpak_config(env)),
                                                     env.tilde(native_config(env)))


# ---------------------------------------------------------------- appearance.json

def _dump(obj, like):
    """JSON the way Obsidian writes it (2-space indent), keeping a final newline."""
    out = json.dumps(obj, indent=2, ensure_ascii=False)
    return out + "\n" if like.endswith("\n") else out


def _load_appearance(text):
    if not text.strip():
        return {}
    try:
        obj = json.loads(text)
    except ValueError:
        raise Conflict("appearance.json is not valid JSON (left untouched)")
    if not isinstance(obj, dict):
        raise Conflict("appearance.json is not a JSON object (left untouched)")
    lst = obj.get("enabledCssSnippets", [])
    if not isinstance(lst, list):
        raise Conflict("appearance.json: enabledCssSnippets is not a list (left untouched)")
    return obj


def snippet_enabled(text):
    return SNIPPET in _load_appearance(text).get("enabledCssSnippets", [])


def enable_snippet(text, changed=False):
    """appearance.json text with "appglass" in enabledCssSnippets (idempotent).

    changed: appglass enabled it before and the file was changed since. If
    "appglass" is no longer in the list, the user turned the snippet off in
    Settings > Appearance > CSS snippets: keep that.
    """
    obj = _load_appearance(text)
    lst = obj.get("enabledCssSnippets", [])
    if SNIPPET in lst or changed:
        return text
    obj["enabledCssSnippets"] = list(lst) + [SNIPPET]
    return _dump(obj, text)


def undo(env, path, text):
    """remove after Obsidian rewrote appearance.json: drop only our entry."""
    obj = json.loads(text)
    lst = obj.get("enabledCssSnippets")
    if not isinstance(lst, list) or SNIPPET not in lst:
        return text
    rest = [s for s in lst if s != SNIPPET]
    if rest:
        obj["enabledCssSnippets"] = rest
    else:
        del obj["enabledCssSnippets"]     # an empty list and no list mean the same
    return _dump(obj, text)


# ---------------------------------------------------------------- the snippet

def _rgb(hex_colour):
    h = hex_colour.lstrip("#")
    return "%d, %d, %d" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _over(top, top_a, bottom, bottom_a):
    """(hex, alpha) of a tint `top` at top_a painted over glass `bottom` at bottom_a."""
    a = top_a + bottom_a * (1 - top_a)
    if a <= 0:
        return bottom, 0.0
    t, b = hex_to_rgb(top), hex_to_rgb(bottom)
    return rgb_to_hex(tuple((t[i] * top_a + b[i] * bottom_a * (1 - top_a)) / a
                            for i in range(3))), a


def accent_sources(ctx):
    """The eight named colours before they are made readable."""
    t16, _ = ctx.term16
    t16 = t16 or ctx.dank16
    if not t16:
        return dict(OBSIDIAN_ACCENTS["light" if ctx.mode == "light" else "dark"])
    red, green, yellow, blue, cyan = (norm_hex(t16[i]) for i in (1, 2, 3, 4, 6))
    purple = mix(blue, red, 0.5)
    return {"red": red, "orange": mix(red, yellow, 0.5), "yellow": yellow,
            "green": green, "cyan": cyan, "blue": blue, "purple": purple,
            "pink": mix(red, purple, 0.5)}


def colours(ctx):
    """Every colour the snippet uses, from the DMS palette and levels."""
    lv = ctx.levels
    surface = ctx.colors("surface")
    bar = ctx.colors("surface_container")
    menu = ctx.colors("surface_container_high")
    dark = ctx.mode != "light"

    tint = ctx.colors("on_surface")
    # every glass text sits on: content, bars, code blocks (tinted content),
    # the active tab (tinted bar); the opaque menus have far more contrast
    glasses = [(surface, lv.content), (bar, lv.bar),
               _over(tint, CODE_TINT, surface, lv.content),
               _over(tint, TAB_TINT, bar, lv.bar)]

    def text(role):
        return lift(ctx.colors(role))

    def lift(c):
        for _ in range(4):          # moving toward white/black never undoes a pass
            for bg, a in glasses:
                c = readable(c, bg, a, TARGET)
        return c

    return {
        "dark": dark,
        "content": ctx.rgba(surface, lv.content),
        "bar": ctx.rgba(bar, lv.bar),
        # the status bar floats over the content: paint it so the sum is the bar level
        "bar_over_content": ctx.rgba(bar, lv.bar_over_content),
        "menu": menu,
        # notices and tooltips: opaque, on the menu colour
        "on_menu": readable(ctx.colors("on_surface"), menu, 1.0, TARGET),
        "error_on_menu": readable(text("error"), menu, 1.0, TARGET),
        "field": ctx.colors("surface_container_highest"),
        "hover": ctx.colors("surface_variant"),
        "border": ctx.colors("outline_variant"),
        "on_surface": ctx.colors("on_surface"),
        "normal": text("on_surface"),
        "muted": text("on_surface_variant"),
        # Obsidian's faint text (#666 / #ababab) is under 2:1 on glass: lift outline
        "faint": text("outline"),
        "accent": text("primary"),
        "error": text("error"),
        "on_accent": ctx.colors("on_primary"),
        "primary": ctx.colors("primary"),
        "accents": {k: lift(v) for k, v in accent_sources(ctx).items()},
    }


def snippet(ctx):
    c = colours(ctx)
    lv = ctx.levels
    mono0, mono100 = ("0, 0, 0", "255, 255, 255") if c["dark"] else ("255, 255, 255", "0, 0, 0")
    tint = _rgb(c["on_surface"])
    head = """\
/* appglass for Obsidian. Generated from the DMS colours, do not edit:
   rewritten by appglass apply, removed by appglass remove.
   Levels: content %(content).2f, bars/sidebars %(bar).2f, menus/popups/modals opaque.
   Alpha on background roles only; text and icons stay opaque.
   DMS mode: %(mode)s (used for Obsidian's dark and light theme alike). */
""" % {"content": lv.content, "bar": lv.bar, "mode": ctx.mode}
    vars_ = """\
body.theme-dark, body.theme-light {
  color-scheme: %(scheme)s;
  --ag-content: %(content)s;
  --ag-bar: %(bar)s;
  --ag-bar-over-content: %(bar_over_content)s;
  --ag-menu: %(menu)s;
  --mono-rgb-0: %(mono0)s;
  --mono-rgb-100: %(mono100)s;
  --background-primary: var(--ag-content);
  --background-primary-alt: rgba(%(tint)s, %(code_tint)s);
  --background-secondary: var(--ag-bar);
  --background-secondary-alt: var(--ag-bar);
  --titlebar-background: var(--ag-bar);
  --titlebar-background-focused: var(--ag-bar);
  --tab-container-background: var(--ag-bar);
  --tab-background-active: rgba(%(tint)s, %(tab_tint)s);
  --ribbon-background: var(--ag-bar);
  --ribbon-background-collapsed: var(--ag-bar);
  --background-modifier-form-field: %(field)s;
  --background-modifier-border: %(border)s;
  --interactive-normal: %(field)s;
  --interactive-hover: %(hover)s;
  --interactive-accent: %(primary)s;
  --interactive-accent-hover: %(primary)s;
  --text-on-accent: %(on_accent)s;
  --text-normal: %(normal)s;
  --text-muted: %(muted)s;
  --text-faint: %(faint)s;
  --code-comment: %(faint)s;
  --text-accent: %(accent)s;
  --text-accent-hover: %(accent)s;
  --text-error: %(error)s;
  --link-color: %(accent)s;
  --link-color-hover: %(accent)s;
  --link-external-color: %(accent)s;
  --link-external-color-hover: %(accent)s;
  --list-marker-color: %(muted)s;
  --icon-color: %(muted)s;
  --icon-color-hover: %(normal)s;
  --icon-color-active: %(accent)s;
  --icon-color-focused: %(normal)s;
  --icon-opacity: 1;
  --icon-opacity-hover: 1;
  --icon-opacity-active: 1;
  --callout-quote: %(muted)s;
  --notice-color: %(on_menu)s;
  --tooltip-color: %(on_menu)s;
  --ag-menu-error: %(error_on_menu)s;
%(accent_vars)s}
""" % dict(c, accent_vars="".join(
               "  --color-%s: %s;\n  --color-%s-rgb: %s;\n" % (k, c["accents"][k], k, _rgb(c["accents"][k]))
               for k in ACCENTS), scheme="dark" if c["dark"] else "light", mono0=mono0, mono100=mono100,
           tint=tint, code_tint=CODE_TINT, tab_tint=TAB_TINT)
    rules = """\
/* 1. every full-size layout layer is clear, so alphas never stack */
html, body, .app-container, .horizontal-main-container, .workspace, .titlebar,
.titlebar-inner, .titlebar-button-container, .workspace-split, .workspace-tabs,
.workspace-tabs .workspace-leaf, .workspace-tab-container,
.workspace-tab-header-container, .workspace-sidedock-vault-profile, .sidebar-toggle-button,
.workspace-ribbon, .workspace-leaf-content, .view-header, .view-content,
.markdown-source-view, .markdown-preview-view, .markdown-reading-view, .cm-editor, .cm-scroller,
.nav-files-container, .status-bar {
  background-color: transparent !important;
}
/* 2. paint each region exactly once */
.workspace-ribbon.mod-left, .workspace-ribbon.side-dock-ribbon,
.workspace-split.mod-left-split, .workspace-split.mod-right-split,
.workspace-split.mod-root .workspace-tab-header-container {
  background-color: var(--ag-bar) !important;
}
.workspace-split.mod-root .workspace-tab-container { background-color: var(--ag-content) !important; }
.status-bar { background-color: var(--ag-bar-over-content) !important; }
/* 3. disabled icons (the view header's back/forward arrows) are dimmed by
   colour, not by opacity: an opacity would make the glyph translucent */
.clickable-icon[aria-disabled=true], .clickable-icon.is-disabled,
.metadata-property-icon[aria-disabled=true] {
  opacity: 1 !important;
  color: var(--text-faint) !important;
}
/* 4. floating surfaces opaque */
.menu, .modal, .popover, .hover-popover, .suggestion-container, .tooltip, .prompt, .notice {
  background-color: var(--ag-menu) !important;
}
/* Obsidian draws notices and tooltips dark in both themes (#fafafa text):
   on the DMS menu colour they take its text colour, an error tooltip too */
.tooltip.mod-error { color: var(--ag-menu-error) !important; }
"""
    return head + vars_ + rules + inactive_rules(ctx)


PAINTED = """.workspace-ribbon.mod-left, .workspace-ribbon.side-dock-ribbon,
.workspace-split.mod-left-split, .workspace-split.mod-right-split,
.workspace-split.mod-root .workspace-tab-header-container,
.workspace-split.mod-root .workspace-tab-container, .status-bar"""


def inactive_rules(ctx):
    """Unfocused window (Obsidian drops body.is-focused): the glass colours a
    little more transparent, faded by a transition. '' when off."""
    lv = ctx.levels
    if not inactive.active(ctx.settings, lv.content):
        return ""
    p = inactive.params(ctx.settings)
    r = inactive.ratio(lv.content, p["factor"])
    c2, b2 = lv.content * r, min(1.0, lv.bar * r)
    inner = 0.0 if c2 >= 1 else max(0.0, 1 - (1 - b2) / (1 - c2))
    surface, bar = ctx.colors("surface"), ctx.colors("surface_container")
    return """\
/* 5. inactive window: background %.2f -> %.2f, faded (text stays opaque) */
body.theme-dark:not(.is-focused), body.theme-light:not(.is-focused) {
  --ag-content: %s;
  --ag-bar: %s;
  --ag-bar-over-content: %s;
}
%s {
  transition: %s;
}
""" % (lv.content, c2, ctx.rgba(surface, c2), ctx.rgba(bar, b2), ctx.rgba(bar, inner),
       PAINTED, inactive.transition("background-color", ctx.settings))


def _owned(ctx, path):
    return ctx.app.state.owner_of(os.path.abspath(path)) == NAME


def apply(ctx):
    unreadable = []
    vs = vaults(ctx.env, warn=ctx.warn, unreadable=unreadable)
    had_state = NAME in ctx.app.state.owners
    if unreadable and had_state:
        # Obsidian may be rewriting it right now: keep every vault as it is
        raise Conflict("cannot read %s, nothing changed" % ", ".join(unreadable))
    css = snippet(ctx)
    out, skipped = [], []
    for v in vs:
        snip = os.path.join(v, CONFIG_DIR, "snippets", SNIPPET + ".css")
        appearance = os.path.join(v, CONFIG_DIR, "appearance.json")
        ops, order = dict(ctx.ops), list(ctx.order)
        changed = ctx.changed_since_apply(appearance)
        try:
            paths = [ctx.write_owned(snip, css),
                     ctx.edit_text(appearance,
                                   lambda t, changed=changed: enable_snippet(t, changed),
                                   undo=lambda t: undo(ctx.env, None, t))]
            if (changed and not ctx.deleted_since_apply(appearance)
                    and not snippet_enabled(ctx.read_text(appearance) or "")):
                ctx.warn_once("off:" + v, "vault %s: the appglass snippet is turned off in "
                              "appearance.json since apply (in Obsidian, or Obsidian saved "
                              "its settings without it); kept off. Turn it on in Settings > "
                              "Appearance > CSS snippets" % ctx.env.tilde(v))
        except Conflict as ex:
            if _owned(ctx, snip) or _owned(ctx, appearance):
                # glass is already on there: leave the whole family as it is
                # rather than revert a vault over a passing problem
                raise Conflict("vault %s: %s" % (v, ex))
            # a vault appglass never touched: skip just that one
            ctx.ops.clear()
            ctx.ops.update(ops)
            ctx.order[:] = order
            ctx.warn("vault %s skipped: %s" % (v, ex))
            skipped.append(v)
            continue
        out.extend(paths)
    if out:
        return out
    where = (ctx.env.tilde(flatpak_config(ctx.env)), ctx.env.tilde(native_config(ctx.env)))
    reason = ("no vault could be configured" if skipped
              else "no Obsidian vaults found in %s or %s" % where)
    if not had_state:
        raise Conflict(reason)
    # every vault went away since the last apply: revert them all and drop
    # the niri match (an empty plan makes the core revert what it had)
    ctx.warn("%s; appglass files of earlier vaults reverted" % reason)
    ctx.app_ids = []
    return []
