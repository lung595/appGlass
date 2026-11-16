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
Flatpak GTK4 apps do not read the host gtk-4.0 and are not listed.
"""

import os
import re

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
APP_IDS = [a[0] for a in APPS]

# helpers that are not on PATH (xdg-desktop-portal-gnome)
LIBEXEC_DIRS = ("/usr/libexec", "/usr/lib/xdg-desktop-portal-gnome", "/usr/lib")

DANK_IMPORT = '@import url("dank-colors.css");'
GLASS_IMPORT = '@import url("dank-glass.css");'
GTK_CSS = DANK_IMPORT + "\n" + GLASS_IMPORT + "\n"
# DMS gtk.sh DANK_IMPORT_RE
_DANK_RE = re.compile(r"^@import url.*dank-colors\.css.*\);$")
TARGET = 2.25

BACKDROP_RULE = """\
/* Unfocused windows: Adwaita fades bar contents with filter: opacity(0.5) */
headerbar:backdrop > windowhandle,
toolbarview > .top-bar:backdrop > windowhandle, toolbarview > .bottom-bar:backdrop > windowhandle,
searchbar > revealer > box:backdrop > *, actionbar > revealer > box:backdrop > *,
tabbar .box:backdrop > scrolledwindow, tabbar .box:backdrop > .start-action, tabbar .box:backdrop > .end-action { filter: opacity(0.8); }
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


def installed_apps(env):
    """The APPS entries whose executable is present."""
    return [a for a in APPS if any(_found(env, c) for c in a[1])]


def installed(env):
    return bool(installed_apps(env))


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
        BACKDROP_RULE,
    ]
    return "\n".join(lines)


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
    d = ctx.config_path("gtk-4.0")
    glass = os.path.join(d, "dank-glass.css")
    gtk = os.path.join(d, "gtk.css")
    if not os.path.isfile(os.path.join(d, "dank-colors.css")):
        ctx.warn("%s/dank-colors.css not found: GTK4 keeps the stock Adwaita colours "
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
        ctx.warn_once("opt-out", "%s no longer imports dank-glass.css; kept (GTK4 apps stay "
                      "opaque; remove + apply puts the import back)" % ctx.env.tilde(gtk))
    ctx.edit_text(gtk, lambda t: merge(t, gtk, changed), undo=lambda t: undo(ctx.env, gtk, t))
    apps = installed_apps(ctx.env)
    ctx.app_ids = [a[0] for a in apps]
    return [glass, gtk]
