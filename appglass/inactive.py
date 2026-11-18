"""Inactive windows: a little more transparent, faded in and out.

niri cannot animate an opacity rule (a window-rule opacity switches at once),
so the fade is done by each app on its background only (text, icons and logos
stay opaque):

  gtk4      dank-glass.css: ``window.background:backdrop`` at a lower alpha
            of libadwaita's --window-bg-color, with a CSS transition on
            background-color; the bar contents keep ``filter: none`` on
            :backdrop (no faded titles, no jump). Plain GTK4 apps (Default
            theme, no libadwaita) have no --window-bg-color: the rule falls
            back to their own opaque background, so they neither fade nor
            turn to glass when unfocused
  gtk3      the AppGlass theme: the same on ``window.background:backdrop``
            and on the CSD headerbar (from the bar level); backdrop text,
            tabs, spin buttons and headerbar button edges keep their
            focused colours instead of Adwaita's instant grey
  obsidian  the snippet: ``body:not(.is-focused)`` lowers the --ag-* colours,
            with a transition on the painted regions
  alacritty a small daemon (``appglass vibrancy``) that follows the niri focus
            and eases ``window.opacity`` over Alacritty's IPC socket
  vencord   the Discord theme: ``html:not(.app-focused)`` (Discord's own
            window-focus class) lowers --ag-content, #app-mount eases it
  feishin   agl-hook.js sets ``html.agl-inactive`` on BrowserWindow blur
  jellyfin  jfglass sets ``html.agl-inactive`` on QQuickWindow activeChanged
  lianli    appglass-wk.so sets ``html.agl-inactive`` when the page loses focus
  webkit    the same class from the same shim, for any GTK3 WebKitGTK app
  qtstyle   the Qt style animates the window fill on WindowDeactivate

The wrappers get the values from ``appglass levels`` (``fields``): inactive,
fade ("180ms cubic-bezier(...)"), fade_ms, fade_easing.

Apps with no lever can get an instant niri ``is-active=false`` rule
(instantFallback, off by default: it fades the text too, without animation).

Not covered: the ck-shim apps (LocalSend, ArtCraft: colour keys, no CSS) are
deferred, and plain GTK4 apps without libadwaita stay opaque (they are not
glass either).

Two departures from the engine plan: the focus is read in each app (GTK
:backdrop, Electron blur, QWindow active, page focus) rather than from niri's
focus state, so a fade starts with the app's own focus event; and the levels
are written into the app's CSS or wrapper at apply time, so most apps that
are already open pick up a settings change only when they restart.

settings.json ``inactive``:

    {"enabled": true, "factor": 0.90, "durationMs": 180,
     "easing": "ease-out-cubic", "instantFallback": false}

The inactive level is content x factor, never below FLOOR (0.60, the default
content level): with content already at or under the floor nothing changes.
"""

FLOOR = 0.60
EASINGS = {
    "ease-out-cubic": "cubic-bezier(0.33, 1, 0.68, 1)",
    "ease-in-out": "cubic-bezier(0.65, 0, 0.35, 1)",
    "linear": "linear",
}
DEFAULTS = {"enabled": True, "factor": 0.90, "durationMs": 180,
            "easing": "ease-out-cubic", "instantFallback": False}
FACTOR_RANGE = (0.80, 1.00)
DURATION_RANGE = (0, 400)
# families that fade their own background (the rest can only get the
# instant niri rule)
LEVER_FAMILIES = ("gtk4", "gtk3", "obsidian", "alacritty", "vencord", "feishin",
                  "jellyfin", "lianli", "webkit", "qtstyle")


def params(settings):
    """The inactive block of a validated settings dict (defaults filled in)."""
    p = dict(DEFAULTS)
    p.update((settings or {}).get("inactive") or {})
    return p


def level(content, factor):
    """The inactive level for a content level."""
    content, factor = float(content), float(factor)
    if content <= FLOOR:
        return round(content, 4)
    return round(max(FLOOR, content * factor), 4)


def ratio(content, factor):
    """level / content: the alpha factor applied to the content colours."""
    content = float(content)
    if content <= 0:
        return 1.0
    return round(level(content, factor) / content, 4)


def active(settings, content):
    """True when the effect is on and changes something at this level."""
    p = params(settings)
    return bool(p["enabled"]) and ratio(content, p["factor"]) < 1.0


def fields(settings, content):
    """What ``appglass levels`` adds for the wrappers and the rendered CSS:
    the inactive content level and the fade, both a no-op (the content
    level, 0 ms) when the effect is off or at the floor."""
    p = params(settings)
    on = active(settings, content)
    ms = int(p["durationMs"]) if on else 0
    name = p["easing"] if p["easing"] in EASINGS else "ease-out-cubic"
    return {"inactive": level(content, p["factor"]) if on else round(float(content), 4),
            "fade_ms": ms, "fade_easing": name,
            "fade": "%dms %s" % (ms, css_easing(name))}


def css_easing(name):
    return EASINGS.get(name, EASINGS["ease-out-cubic"])


def transition(prop, settings):
    """``background-color 180ms cubic-bezier(...)`` (or ``none`` at 0 ms)."""
    p = params(settings)
    ms = int(p["durationMs"])
    if ms <= 0:
        return "none"
    return "%s %dms %s" % (prop, ms, css_easing(p["easing"]))


def ease(name, x):
    """The easing curve at x in 0..1 (the daemon's animation)."""
    x = min(1.0, max(0.0, float(x)))
    if name == "linear":
        return x
    if name == "ease-in-out":
        return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2
    return 1 - (1 - x) ** 3
