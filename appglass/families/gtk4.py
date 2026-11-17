"""GTK4 / libadwaita: alpha on the background colour roles, text stays opaque.

Writes $XDG_CONFIG_HOME/gtk-4.0/dank-glass.css (owned) from the DMS colours
at the appglass levels (docs/gtk4.md), and gtk-4.0/gtk.css:

    @import url("dank-colors.css");
    @import url("dank-glass.css");

gtk.css is read by every GTK4 app, so:

* gtk.css absent: appglass creates it as an edit, not as an owned file, so
  it stays the user's: a change made after apply (a user rule, DMS
  ``gtk.sh remove`` taking out the dank-colors line, the glass import taken
  out to opt out) is kept on the next apply. Remove takes the glass import
  out and deletes the file when nothing of the user's is left.
* gtk.css deleted by the user after apply: an opt-out, left deleted (the
  hook does not bring it back); remove + apply writes it again.
* gtk.css holds only a DMS import line (what DMS ``gtk.sh apply`` writes):
  merged, the original is backed up and restored byte-identical on remove.
* anything else: the family is skipped with a warning (a user stylesheet is
  never rewritten).

DMS does not clobber this gtk.css: its ``gtk.sh`` treats a gtk.css whose
first line is the dank-colors import as already set up ("Dank import already
present") and leaves the other lines alone; ``gtk.sh remove`` deletes only
the dank-colors line.

Levels: window/view = content; headerbar, sidebars and cards are painted on
top of the window background, so they get the inner alpha
1 - (1 - bar) / (1 - content) (0.125 at 0.60) to land at the bar level;
popovers and dialogs are opaque. Text (``*_fg_color``) is left to DMS unless
on_surface would fall under 2.25:1 on the glass, then it is moved toward
white/black.

niri: the GTK4 CSS alpha applies to every native GTK4/libadwaita app, so
every one installed must get ``opacity 1.0`` (otherwise it is faded twice).
APPS lists them; the niri rule gets the installed ones. Epiphany is partial:
its chrome (headerbar, tabs, sidebar) is glass, the web page stays opaque.

Flatpak GTK4 apps do not read the host gtk-4.0: their XDG_CONFIG_HOME is
~/.var/app/<id>/config. For the FLATPAK_APPS installed (user or system),
appglass writes the same three files there: dank-glass.css (owned), a copy
of the host DMS dank-colors.css (owned, refreshed on every apply, so a DMS
theme change reaches the app through the hook) and gtk.css (the same edit
and merge as on the host). No flatpak override is needed. Any other GTK4
flatpak the engine routes here (GENERIC) gets a launcher override instead
that adds FLATPAK_ARG (the host gtk-4.0, read only) to `flatpak run`.

Generic rules for apps B5b measured (docs/apps.md): the GtkSourceView text
area (its style scheme paints the view opaque under the window fill: GNOME
Text Editor, Builder), column and list views nested in the window
background (they stacked to 0.96: Mission Center, Resources), and the
selected sidebar row (DMS paints it opaque secondary_container: half alpha).
"""

import os
import re

from .. import inactive
from ..core import Conflict, readable

NAME = "gtk4"

# (niri app-id regex, executables that mean "installed", note)
APPS = [
    (r"^org\.gnome\.Nautilus$", ("nautilus",), "Files"),
    (r"^nautilus-autorun-software$", ("nautilus-autorun-software",), "Nautilus autorun dialog"),
    (r"^org\.gnome\.Software$", ("gnome-software",), "GNOME Software"),
    (r"^org\.gnome\.Zenity$", ("zenity",), "Zenity dialogs"),
    (r"^xdg-desktop-portal-gnome$", ("xdg-desktop-portal-gnome",),
     "file chooser portal, used by Chrome, Electron and other portal apps"),
    (r"^com\.github\.tchx84\.Flatseal$", ("com.github.tchx84.Flatseal",),
     "Flatseal, native package (the flatpak one does not read the host gtk.css)"),
    (r"^org\.gnome\.Epiphany(\.WebApp_.*)?$", ("epiphany",),
     "Epiphany and its web apps: partial, chrome is glass, the page stays opaque"),
    (r"^org\.gnome\.Adwaita1\.Demo$", ("adwaita-1-demo",), "libadwaita demo"),
]
# (niri app-id regex, flatpak app id, note): flatpaks that get the css in
# ~/.var/app/<id>/config/gtk-4.0
FLATPAK_APPS = [
    (r"^org\.gnome\.TextEditor$", "org.gnome.TextEditor", "GNOME Text Editor (GtkSourceView)"),
    (r"^io\.missioncenter\.MissionCenter$", "io.missioncenter.MissionCenter", "Mission Center"),
    (r"^net\.nokyan\.Resources$", "net.nokyan.Resources", "Resources"),
]
APP_IDS = [a[0] for a in APPS] + [a[0] for a in FLATPAK_APPS]

# helpers that are not on PATH (xdg-desktop-portal-gnome)
LIBEXEC_DIRS = ("/usr/libexec", "/usr/lib/xdg-desktop-portal-gnome", "/usr/lib")

DANK_IMPORT = '@import url("dank-colors.css");'
GLASS_IMPORT = '@import url("dank-glass.css");'
GTK_CSS = DANK_IMPORT + "\n" + GLASS_IMPORT + "\n"
# DMS gtk.sh DANK_IMPORT_RE
_DANK_RE = re.compile(r"^@import url.*dank-colors\.css.*\);$")
TARGET = 2.25
# the engine routes every other GTK4 app here (ctx.records()): a host one
# reads the global gtk.css already (niri rule only); a flatpak one gets
# the gtk-4.0 config dir read-only for each launch, in its launcher
# override (never a persistent flatpak override)
GENERIC = True
FLATPAK_ARG = "--filesystem=xdg-config/gtk-4.0:ro"

BACKDROP_SELECTORS = """\
headerbar:backdrop > windowhandle,
toolbarview > .top-bar:backdrop > windowhandle, toolbarview > .bottom-bar:backdrop > windowhandle,
searchbar > revealer > box:backdrop > *, actionbar > revealer > box:backdrop > *,
tabbar .box:backdrop > scrolledwindow, tabbar .box:backdrop > .start-action, tabbar .box:backdrop > .end-action"""
BACKDROP_RULE = (
    "/* Unfocused windows: Adwaita fades bar contents with filter: opacity(0.5) */\n"
    + BACKDROP_SELECTORS + " { filter: opacity(0.8); }\n")
# with the inactive fade on, the bar contents (titles, icons) keep their
# focused look: the filter has no transition, so it would jump and fade text
BACKDROP_RULE_FADE = (
    "/* Unfocused windows: the background fades, bar contents stay as focused */\n"
    + BACKDROP_SELECTORS + " { filter: none; }\n")

SOURCEVIEW_RULE = """\
/* GtkSourceView: the style scheme paints the text area opaque under the window fill */
textview.view, textview.view > text, textview.view > border,
textview.view:backdrop, textview.view:backdrop > text, textview.view:backdrop > border { background-color: transparent; }
"""

NESTED_VIEW_RULE = """\
/* column/list views inside the window background would stack a second view fill */
window.background columnview.view, window.background columnview > listview.view { background-color: transparent; }
"""

FG_ROLES = ("window_fg_color", "view_fg_color", "headerbar_fg_color",
            "headerbar_backdrop_fg_color", "sidebar_fg_color", "sidebar_backdrop_fg_color",
            "secondary_sidebar_fg_color", "secondary_sidebar_backdrop_fg_color",
            "card_fg_color")


def _found(env, cmd):
    if env.which(cmd):
        return True
    for d in LIBEXEC_DIRS:
        p = os.path.join(d, cmd)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return True
    return False


def accepts(rec):
    if rec.get("flatpak") and rec.get("user_only"):
        return "a launcher of yours with no system one: left as it is"
    return None


def flatpak_launcher(text):
    """Every `flatpak run` Exec= line gets the read-only gtk-4.0 dir."""
    out = []
    for line in text.splitlines(True):
        if line.startswith("Exec=") and FLATPAK_ARG not in line:
            line = re.sub(r"(^Exec=\S*flatpak run)(\s)", r"\1 %s\2" % FLATPAK_ARG, line, count=1)
        out.append(line)
    return "".join(out)


def installed_apps(env):
    """The APPS entries whose executable is present."""
    return [a for a in APPS if any(_found(env, c) for c in a[1])]


def installed_flatpaks(env):
    """The FLATPAK_APPS entries installed (user or system)."""
    from .. import detect
    return [a for a in FLATPAK_APPS if detect.flatpak_app(env, a[1]) is not None]


def installed(env):
    return bool(installed_apps(env)) or bool(installed_flatpaks(env))


def _a(v):
    """0.6 -> '0.60', 0.125 -> '0.125'."""
    s = ("%.3f" % v).rstrip("0")
    whole, frac = s.split(".")
    return "%s.%s" % (whole, frac.ljust(2, "0"))


def render(ctx):
    lv = ctx.levels
    c, inner = lv.content, lv.bar_over_content
    sc = ctx.colors("surface_container")
    scl = ctx.colors("surface_container_low")
    sch = ctx.colors("surface_container_high")
    lines = [
        "/* appglass: GTK4/libadwaita glass. Generated, do not edit: rewritten by",
        "   appglass apply. Imported after dank-colors.css by gtk.css.",
        "   Levels: content %s, bars %s (inner %s over the content), popups 1.0."
        % (_a(c), _a(lv.bar), _a(inner)),
        "   Background roles only: text, icons and logos stay opaque. */",
        "@define-color window_bg_color alpha(%s, %s);" % (sc, _a(c)),
        "@define-color view_bg_color alpha(%s, %s);" % (scl, _a(c)),
        "/* inner layers stack on the content base: %s -> %s net */" % (_a(inner), _a(lv.bar)),
        "@define-color headerbar_bg_color alpha(%s, %s);" % (sc, _a(inner)),
        "@define-color headerbar_backdrop_color alpha(%s, %s);" % (sc, _a(inner)),
        "@define-color sidebar_bg_color alpha(%s, %s);" % (sch, _a(inner)),
        "@define-color sidebar_backdrop_color alpha(%s, %s);" % (sch, _a(inner)),
        "@define-color secondary_sidebar_bg_color alpha(%s, %s);" % (sc, _a(inner)),
        "@define-color secondary_sidebar_backdrop_color alpha(%s, %s);" % (sc, _a(inner)),
        "@define-color card_bg_color alpha(%s, %s);" % (sch, _a(inner)),
        "@define-color overview_bg_color alpha(%s, %s);" % (sch, _a(c)),
        "/* popups opaque */",
        "@define-color popover_bg_color %s;" % sch,
        "@define-color dialog_bg_color %s;" % sc,
    ]
    fg = ctx.colors("on_surface")
    rf = fg
    for bg in (sc, scl, sch):
        rf = readable(rf, bg, c, TARGET)
    if rf != fg:
        lines.append("/* on_surface %s is under %.2f:1 on the glass: moved */" % (fg, TARGET))
        lines += ["@define-color %s %s;" % (r, rf) for r in FG_ROLES]
    lines += [
        "",
        "/* AdwDialog sheets paint window_bg_color: force the opaque dialog colour */",
        "dialog sheet { background-color: @dialog_bg_color; }",
        "",
        "/* Dimmed text (.dim-label/.dimmed, pathbar, subtitles) defaults to 0.55 */",
        ":root { --dim-opacity: 0.80; }",
        "",
        BACKDROP_RULE_FADE if inactive.active(ctx.settings, c) else BACKDROP_RULE,
        SOURCEVIEW_RULE,
        NESTED_VIEW_RULE,
        "/* the selected sidebar row: DMS paints it opaque */",
        ".navigation-sidebar row:selected, .navigation-sidebar child:selected,",
        ".navigation-sidebar flowboxchild:selected { background-color: alpha(%s, 0.50); }"
        % ctx.colors("secondary_container"),
        "",
    ]
    lines += inactive_rule(ctx)
    return "\n".join(lines)


def inactive_rule(ctx):
    """Unfocused windows: the window background a little more transparent,
    faded by a transition (settings inactive). [] when off."""
    c = ctx.levels.content
    if not inactive.active(ctx.settings, c):
        return []
    p = inactive.params(ctx.settings)
    r = inactive.ratio(c, p["factor"])
    return [
        "/* inactive windows: background %s -> %s, faded (text stays opaque) */"
        % (_a(c), _a(inactive.level(c, p["factor"]))),
        "window.background { transition: %s; }" % inactive.transition("background-color",
                                                                       ctx.settings),
        # libadwaita only: the Default theme paints an opaque literal, never
        # @window_bg_color, so alpha(@window_bg_color) would turn plain GTK4
        # windows into glass when unfocused. --window-bg-color exists only
        # under libadwaita; elsewhere the var() falls back to the Default
        # theme's own opaque background.
        "window.background:backdrop { --agl-backdrop-bg: alpha(var(--window-bg-color), %s); "
        "background-color: var(--agl-backdrop-bg, @theme_bg_color); }" % _a(r),
        "",
    ]


def _lines(text):
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def is_dms_import(text):
    """A gtk.css that is only what DMS gtk.sh writes (or empty)."""
    ls = _lines(text)
    return not ls or (len(ls) == 1 and bool(_DANK_RE.match(ls[0])))


def merge(text, path, changed=False):
    """gtk.css edit: text is '' when appglass creates the file.

    changed: appglass wrote gtk.css before and it was changed since (the text
    is then the current one). Whatever it holds is kept: with the glass
    import it is a user rule on top, without it the user opted out (the
    import line taken out, the file emptied), which a re-apply must not undo.
    """
    if changed:
        return text
    if is_dms_import(text):
        return GTK_CSS
    if GLASS_IMPORT in _lines(text):
        return text           # merged before and changed by the user since: keep
    raise Conflict("%s is a user stylesheet, not a DMS import; left untouched. Add %s "
                   "after the dank-colors import to opt in" % (path, GLASS_IMPORT))


def undo(env, path, text):
    if os.path.basename(path) != "gtk.css":
        return text
    return "".join(ln for ln in text.splitlines(keepends=True)
                   if ln.strip() != GLASS_IMPORT)


def apply(ctx):
    paths = []
    host = ctx.config_path("gtk-4.0")
    apps = installed_apps(ctx.env)
    flatpaks = installed_flatpaks(ctx.env)
    ids = [a[0] for a in apps] + [a[0] for a in flatpaks]
    # the apps the engine routes here that are not listed by hand
    generic = [rec for rec in ctx.records()
               if not any(re.search(rx, n) for rx in ids for n in rec.get("names") or ())]
    plain = ctx.records(plain=True)
    # the host gtk-4.0 serves the host apps and the engine's flatpaks (read
    # only through their launchers); a hand-listed flatpak has its own dir
    if apps or generic or plain:
        paths += apply_dir(ctx, host)
    if flatpaks:
        dank = ctx.read_text(os.path.join(host, "dank-colors.css"))
        for _, app_id, _ in flatpaks:
            d = ctx.home_path(".var", "app", app_id, "config", "gtk-4.0")
            if dank is not None:
                paths.append(ctx.write_owned(os.path.join(d, "dank-colors.css"), dank))
            paths += apply_dir(ctx, d, warn=False)
    # a flatpak held opaque by the engine (S7): its launcher goes back to the
    # system text (no gtk-4.0 access) until the next fingerprint. A host
    # GTK4 app reads the global gtk.css: it cannot be made plain on its own.
    for rec in plain:
        dest = ctx.data_path("applications", rec["desktop_id"])
        if rec.get("flatpak") and ctx.owns(dest):
            p = ctx.desktop_override(rec["desktop_id"], lambda t: t)
            if p:
                paths.append(p)
    for rec in generic:
        rid = [x for x in rec.get("app_ids") or () if x not in ids]
        if rec.get("flatpak"):
            try:
                p = ctx.desktop_override(rec["desktop_id"], flatpak_launcher)
            except Conflict as ex:
                ctx.warn("%s: %s" % (rec["key"], ex))
                continue
            if not p:
                continue
            paths.append(p)
        ids += rid
    ctx.app_ids = ids
    return paths


def apply_dir(ctx, d, warn=True):
    glass = os.path.join(d, "dank-glass.css")
    gtk = os.path.join(d, "gtk.css")
    if warn and not os.path.isfile(os.path.join(d, "dank-colors.css")):
        ctx.warn_once("dank-colors", "%s/dank-colors.css not found: GTK4 keeps the stock Adwaita colours "
                 "under the glass until DMS writes it" % ctx.env.tilde(d))
    if os.path.islink(gtk):
        raise Conflict("%s is a symlink (user-managed); left untouched" % gtk)
    if os.path.lexists(gtk) and not os.path.isfile(gtk):
        raise Conflict("%s is not a regular file; left untouched" % gtk)
    ctx.write_owned(glass, render(ctx))
    changed = ctx.changed_since_apply(gtk)
    if ctx.deleted_since_apply(gtk):
        # the core leaves it deleted; say what that means for GTK4
        ctx.warn_once("deleted:" + gtk, "%s was deleted since apply; left deleted (GTK4 "
                      "apps no longer import dank-glass.css and stay opaque; remove + "
                      "apply writes it again)" % ctx.env.tilde(gtk))
    elif changed and GLASS_IMPORT not in _lines(ctx.read_text(gtk) or ""):
        ctx.warn_once("opt-out" if warn else "opt-out:" + gtk, "%s no longer imports dank-glass.css; kept (GTK4 apps stay "
                      "opaque; remove + apply puts the import back)" % ctx.env.tilde(gtk))
    ctx.edit_text(gtk, lambda t: merge(t, gtk, changed), undo=lambda t: undo(ctx.env, gtk, t))
    return [glass, gtk]
