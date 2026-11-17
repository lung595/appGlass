"""The adapter catalogue: how each kind of app can get glass, and at what cost.

families/ holds the adapters that are implemented (they write files); this
registry also lists the planned ones, so detect/status can say what an app
would need. Each adapter has:

  TIER   native    the app's own theme/config files (on when detected)
         forced    an env var, a preload shim or a launcher flag the app does
                   not offer (off until switched on in settings.json)
         mod       a third-party client mod (off until switched on)
         fallback  niri whole-window opacity only (fallback.mode)
         opaque    games: niri opacity 1.0, blur off
         delegated another plugin owns it (browserGlass)
         excluded  DMS draws it itself; never touched
  RISK   none | low | medium | medium-high | high, plus a reason

resolve() maps one detect record to its adapter and to what apply does with
it today ("effective": glass, fallback, opaque, delegated, excluded).
"""

import re

from .. import niri

NATIVE, FORCED, MOD = "native", "forced", "mod"
FALLBACK, OPAQUE, DELEGATED, EXCLUDED = "fallback", "opaque", "delegated", "excluded"
TIERS = (NATIVE, FORCED, MOD, FALLBACK, OPAQUE, DELEGATED, EXCLUDED)


class Adapter:
    __slots__ = ("NAME", "TIER", "RISK", "WHY", "TOOLKITS", "FAMILY", "FAMILIES", "SUMMARY")

    def __init__(self, name, tier, risk, toolkits=(), family=None, summary="", why=""):
        # family: one family name, or a tuple when several apps share the
        # adapter (FAMILY is the first, the toolkit default's family)
        fams = (family,) if isinstance(family, str) else tuple(family or ())
        self.NAME, self.TIER, self.RISK, self.WHY = name, tier, risk, why
        self.TOOLKITS, self.SUMMARY = tuple(toolkits), summary
        self.FAMILIES, self.FAMILY = fams, (fams[0] if fams else None)

    @property
    def implemented(self):
        return self.FAMILY is not None or self.TIER in (FALLBACK, OPAQUE, DELEGATED, EXCLUDED)

    def as_dict(self):
        return {"name": self.NAME, "tier": self.TIER, "risk": self.RISK, "why": self.WHY,
                "toolkits": list(self.TOOLKITS), "family": self.FAMILY,
                "families": list(self.FAMILIES),
                "implemented": self.implemented, "summary": self.SUMMARY}


# order matters: the first adapter for a toolkit is its default route
CATALOGUE = (
    Adapter("terminal", NATIVE, "none", ["terminal"],
            ("alacritty", "foot", "kitty", "ghostty", "wezterm", "konsole"),
            "the terminal's own background opacity key"),
    Adapter("gtk4", NATIVE, "low", ["gtk4-adw", "gtk4"], "gtk4",
            "gtk-4.0/gtk.css alpha on the background colours",
            "every GTK4 app reads the file; unlisted ones get double translucency"),
    Adapter("gtk3", NATIVE, "low", ["gtk3"], "gtk3",
            "GTK_THEME=AppGlass through a launcher override"),
    Adapter("electron-builtin", NATIVE, "low", [], "obsidian",
            "the app's own CSS snippets plus its translucency switch"),
    Adapter("gpui-json", NATIVE, "none", ["gpui"], ("herdr", "zed"),
            "theme file with alpha colours (Zed: theme_overrides in settings.json)"),
    Adapter("dux-json", NATIVE, "none", [], "dux", "the app's ui-settings window colour"),
    Adapter("qt-style", NATIVE, "low", ["qt-widgets"], "qtstyle",
            "QT_STYLE_OVERRIDE=appglass (a Qt style plugin) through a launcher override"),
    Adapter("app-config", NATIVE, "none", [], ("mpv", "gimp", "kate"),
            "the app's own config: a glass background colour (mpv), a user CSS over its theme "
            "(GIMP), a clear editor colour theme (Kate, under the qt-style glass)"),
    Adapter("kvantum", NATIVE, "low", [], None, "a Kvantum theme with translucency"),
    Adapter("gecko", NATIVE, "low", ["gecko"], None,
            "userChrome/userContent for non-browser Gecko apps (Thunderbird)"),
    Adapter("electron-vencord", MOD, "medium", [], "vencord",
            "a Vencord theme with transparency (Discord)",
            "client mods break Discord's terms of service"),
    Adapter("electron-hook", FORCED, "medium", ["electron"], ("feishin", "vscodium"),
            "a main-process hook (NODE_OPTIONS when the fuse allows it) plus CSS",
            "may break on app updates"),
    Adapter("webkit-shim", FORCED, "medium", ["webkitgtk"], "lianli",
            "a preload that makes the WebKit view transparent, plus page CSS"),
    Adapter("qtquick-shim", FORCED, "medium-high", ["qt-webengine", "qt-quick"], "jellyfin",
            "a preload that sets the QML window alpha (Jellyfin)",
            "video playback breaks until the shim re-shows mpv"),
    Adapter("ck-shim", FORCED, "high", ["flutter", "egui", "winit", "iced", "slint"],
            ("localsend", "artcraft"),
            "a colour-key EGL shim",
            "may force software rendering"),
    Adapter("steam-cdp", FORCED, "medium", ["cef"], None,
            "Steam launch flags plus CSS injected over the local debug port",
            "any local process can drive the logged-in client while it runs"),
    Adapter("obs-plugin", FORCED, "medium", [], None, "an OBS plugin plus theme"),
    Adapter("niri-fallback", FALLBACK, "none", [], None,
            "niri opacity only (fallback.mode)", "text fades too in value mode"),
    Adapter("games", OPAQUE, "none", ["game", "sdl"], None,
            "niri opacity 1.0, blur off, popups 1.0"),
    Adapter("browserglass", DELEGATED, "none", ["gecko"], None,
            "the browserGlass DMS plugin owns Firefox-family browsers"),
    Adapter("excluded", EXCLUDED, "none", [], None, "DMS paints these windows itself"),
)
BY_NAME = {a.NAME: a for a in CATALOGUE}

# per-app routes the catalogue knows by app-id (before the toolkit default)
APP_ROUTES = (
    (r"^discord$", "electron-vencord"),
    (r"^steam$", "steam-cdp"),
    (r"^org\.jellyfin\.JellyfinDesktop$", "qtquick-shim"),
    (r"^com\.obsproject\.Studio$", "obs-plugin"),
)

EXCLUDED_IDS = (
    r"^org\.quickshell$", r"^dms-open$", r"^dev\.duxlabs\.shell(\..+)?$",
    r"^com\.danklinux\.dms$", r"^org\.freedesktop\.Xwayland$",
)

# hand-made files from before appglass owned them: (path relative to $HOME,
# the adapter that will own it, what it is)
HAND_FILES = (
    (".config/niri/appglass-test.kdl", "niri-fallback",
     "the opaque catch-all and discord/vlc rules, now fallback.mode = opaque"),
    (".local/share/applications/vlc.desktop", "qt-style", "VLC Qt style launcher"),
    (".local/lib/appglass/qt6/styles/libappglass.so", "qt-style", "the Qt style plugin"),
    (".local/share/applications/com.sgtaziz.lianlilinux.desktop", "webkit-shim",
     "Lian Li shim launcher"),
    (".local/bin/appglass-lianli", "webkit-shim", "Lian Li launch wrapper"),
    (".local/lib/appglass/lianli/appglass-wk.so", "webkit-shim", "the WebKit shim"),
    (".local/lib/appglass/lianli/appglass-wk.c", "webkit-shim", "the WebKit shim source"),
    (".local/lib/appglass/lianli/lianli-glass.css.tmpl", "webkit-shim", "Lian Li CSS template"),
    (".local/lib/appglass/lianli/lianli-glass.css", "webkit-shim", "Lian Li CSS (rendered)"),
    (".local/share/applications/org.localsend.localsend_app.desktop", "ck-shim",
     "LocalSend shim launcher"),
    (".local/bin/appglass-localsend", "ck-shim", "LocalSend launch wrapper"),
    (".local/lib/appglass/localsend/appglass-ck.so", "ck-shim", "the colour-key shim"),
    (".local/lib/appglass/localsend/appglass-ck.c", "ck-shim", "the colour-key shim source"),
    (".local/share/applications/ai.storyteller.artcraft-launcher.desktop", "ck-shim",
     "ArtCraft shim launcher"),
    (".local/bin/appglass-artcraft", "ck-shim", "ArtCraft launch wrapper"),
    (".local/lib/appglass/artcraft/appglass-ck.so", "ck-shim", "the colour-key shim (ArtCraft)"),
    (".local/lib/appglass/artcraft/appglass-ck.c", "ck-shim",
     "the colour-key shim source (ArtCraft)"),
    (".local/share/applications/org.jeffvli.feishin.desktop", "electron-hook",
     "Feishin shim launcher"),
    (".local/bin/appglass-feishin", "electron-hook", "Feishin launch wrapper"),
    (".local/lib/appglass/feishin/agl-hook.js", "electron-hook", "the main-process hook"),
    (".local/lib/appglass/feishin/agl-inject.py", "electron-hook", "the inspector injector"),
    (".local/lib/appglass/feishin/feishin-glass.css.tmpl", "electron-hook",
     "Feishin CSS template"),
    (".local/lib/appglass/feishin/feishin-glass.css", "electron-hook", "Feishin CSS (rendered)"),
    (".local/share/applications/org.jellyfin.JellyfinDesktop.desktop", "qtquick-shim",
     "Jellyfin shim launcher"),
    (".local/bin/appglass-jellyfin", "qtquick-shim", "Jellyfin launch wrapper"),
    (".local/lib/appglass/jellyfin/libjfglass.so", "qtquick-shim", "the Qt Quick shim"),
    (".local/lib/appglass/jellyfin/jfglass.cpp", "qtquick-shim", "the Qt Quick shim source"),
    (".local/lib/appglass/jellyfin/jellyfin-glass.css.tmpl", "qtquick-shim",
     "Jellyfin CSS template"),
    (".local/lib/appglass/jellyfin/gen-css.sh", "qtquick-shim", "Jellyfin CSS renderer"),
    (".local/lib/appglass/jellyfin/jellyfin-glass.css", "qtquick-shim",
     "Jellyfin CSS (rendered)"),
    (".local/bin/appglass-sync", "hook", "the regeneration script (sync path unit)"),
    (".local/bin/appglass-vencord", "electron-vencord",
     "Vencord re-inject + theme (retired: the family and the sync unit do it)"),
    (".local/share/appglass/appglass-discord.css.tmpl", "electron-vencord",
     "Discord theme template (retired: in the repo now)"),
    (".config/Vencord/themes/appglass-discord.css", "electron-vencord", "the Discord glass theme"),
    (".config/systemd/user/appglass-sync.path", "hook", "watches the theme files"),
    (".config/systemd/user/appglass-sync.service", "hook", "runs appglass-sync"),
    (".config/systemd/user/appglass-vibrancy.service", "hook",
     "runs appglass-vibrancy (the Alacritty inactive fade)"),
    (".config/systemd/user/appglass-discord.path", "hook", "watches ~/.config/discord"),
    (".config/systemd/user/appglass-discord.service", "hook", "runs appglass-sync --discord"),
    (".local/bin/appglass-vibrancy", "hook", "the vibrancy daemon wrapper"),
)


def _any(rxs, names):
    for rx in rxs:
        try:
            r = re.compile(rx)
        except re.error:
            continue
        if any(r.search(n) for n in names):
            return True
    return False


def hand_family(adapter, rel, families):
    """The family of adapter that owns the hand file rel: the only one, or
    (an adapter several apps share) the one whose name is a word of the
    path (.local/lib/appglass/artcraft/..., appglass-artcraft)."""
    fams = [f for f in adapter.FAMILIES if f in families]
    if len(adapter.FAMILIES) <= 1:
        return fams[0] if fams else None
    return next((f for f in fams if re.search(r"(^|[/._-])%s([/._-]|$)" % re.escape(f), rel)),
                None)


def family_for(rec, families):
    names = rec.get("names") or []
    for name in sorted(families):
        if _any(getattr(families[name], "APP_IDS", ()), names):
            return name
    return None


def routes(rec, families):
    """The adapters an app may take (apps.<key>.route), the default first:
    its family's adapter, the app-id route, then the toolkit's glass
    adapters. None for a delegated, excluded or game app."""
    names = rec.get("names") or []
    if any(niri.delegated("^%s$" % re.escape(n)) for n in names) or _any(EXCLUDED_IDS, names) \
            or rec.get("toolkit") == "game":
        return []
    out = []
    fam = family_for(rec, families)
    a = next((x for x in CATALOGUE if fam in x.FAMILIES), None) if fam else None
    if a:
        out.append(a.NAME)
    out += [ad for rx, ad in APP_ROUTES if _any([rx], names)]
    # a toolkit adapter that serves families only works for an app its
    # families list (resolve gives the others the fallback)
    out += [x.NAME for x in CATALOGUE if rec.get("toolkit") in x.TOOLKITS
            and x.TIER in (NATIVE, FORCED, MOD) and (not x.FAMILIES or fam in x.FAMILIES)]
    seen = set()
    return [n for n in out if not (n in seen or seen.add(n))]


def resolve(rec, families, settings=None):
    """{"adapter", "tier", "risk", "implemented", "family", "enabled",
    "effective", "reason"} for one detect record."""
    from .. import settings as _settings
    settings = settings or _settings.DEFAULTS
    names = rec.get("names") or []
    key = rec.get("key")

    def out(adapter, effective, reason, family=None, enabled=None):
        a = BY_NAME[adapter]
        return {"adapter": a.NAME, "tier": a.TIER, "risk": a.RISK,
                "implemented": a.implemented if family is None else True,
                "family": family, "enabled": enabled, "effective": effective,
                "reason": reason}

    if any(niri.delegated("^%s$" % re.escape(n)) for n in names):
        return out("browserglass", DELEGATED, "browserGlass owns this browser")
    if _any(EXCLUDED_IDS, names):
        return out("excluded", EXCLUDED, "DMS draws this window")
    if rec.get("toolkit") == "game":
        return out("games", OPAQUE, "game: always opaque")
    route = (settings.get("apps", {}).get(key) or {}).get("route")
    fam = family_for(rec, families)
    if fam and route in BY_NAME and fam not in BY_NAME[route].FAMILIES:
        fam = None            # the user picked another adapter for this app
    if fam:
        a = next((x for x in CATALOGUE if fam in x.FAMILIES), None)
        if getattr(families[fam], "OPT_IN", False):
            # forced / mod: off until apps.<family> or apps.<key> switches it on
            own = settings.get("apps", {}).get(fam) or {}
            on = bool(own["enabled"]) if "enabled" in own else \
                _settings.app_enabled(settings, key, False)
            why = "family %s" % fam if on else "%s adapter, off until enabled (risk %s)" % (
                a.TIER if a else FORCED, a.RISK if a else "medium")
        else:
            on = _settings.app_enabled(settings, fam, True) and \
                _settings.app_enabled(settings, key, True)
            why = "family %s" % fam if on else "off in settings"
        return out(a.NAME if a else "niri-fallback", "glass" if on else FALLBACK,
                   why, family=fam, enabled=on)
    a = BY_NAME.get(route) if route else None
    if a is None:
        hit = next((ad for rx, ad in APP_ROUTES if _any([rx], names)), None)
        a = BY_NAME.get(hit) if hit else None
    if a is None:
        a = next((x for x in CATALOGUE if rec.get("toolkit") in x.TOOLKITS
                  and x.TIER in (NATIVE, FORCED, MOD)), None)
    if a is None:
        return out("niri-fallback", FALLBACK,
                   "no adapter for toolkit %s" % rec.get("toolkit", "unknown"))
    default_on = a.TIER == NATIVE
    on = _settings.app_enabled(settings, key, default_on)
    if a.FAMILY:
        # the toolkit has a family, but the family does not list this app
        return out(a.NAME, FALLBACK, "family %s does not list this app" % a.FAMILY,
                   enabled=on) | {"implemented": False}
    if not on:
        return out(a.NAME, FALLBACK, "%s adapter, off until enabled (risk %s)"
                   % (a.TIER, a.RISK), enabled=False)
    return out(a.NAME, FALLBACK, "adapter %s not implemented yet" % a.NAME, enabled=True)
