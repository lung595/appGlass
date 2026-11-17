"""GTK3 (mode B): a per-app theme, AppGlass, opted in by launcher overrides.

GTK3 has no per-app user CSS and a global gtk-3.0/gtk.css would reach every
GTK3 client (a double fade for each one without a niri rule), so appglass
does not write one. Instead (docs/gtk3.md, mode B):

* $XDG_DATA_HOME/themes/AppGlass/gtk-3.0/gtk.css (owned): Adwaita
  (gtk-contained-dark.css, or gtk-contained.css for a light DMS scheme),
  then $XDG_CONFIG_HOME/gtk-3.0/dank-colors.css by absolute file:// URL, then
  the glass rules at the appglass levels. The rules use only the DMS colour
  names (@window_bg_color ...), so they follow dank-colors.css.
* launcher overrides in $XDG_DATA_HOME/applications/ for the apps in APPS:
  copied from the system .desktop file (XDG_DATA_DIRS), with
  ``Exec=env GTK_THEME=AppGlass ...``. A user override that already exists
  is edited instead (backed up, restored byte-identical on remove). The
  copies are made as edits, not owned files: a user change to them is kept,
  GTK_THEME taken out (an opt-out) included; remove takes our part out and
  deletes a copy when nothing of the user's is left. A copy the user
  deleted stays deleted (the core keeps the record, so remove still works).
* $XDG_CONFIG_HOME/autostart/solaar.desktop: Solaar is single-instance and
  autostarted from $XDG_CONFIG_DIRS/autostart (/etc/xdg/autostart), so a
  launcher override alone has no effect while it runs. Copied with the same
  Exec change, only when the system autostart file exists; an existing user
  autostart file is edited (backed up).

niri gets ``opacity 1.0`` for the installed apps only. An app started
without GTK_THEME (e.g. from a shell) is then opaque, not faded twice.
Restart the apps (Solaar: log out or ``solaar quit`` then relaunch) to pick
the theme up; GTK3 reads CSS at start.
"""

import os
import re
import urllib.parse

from .. import inactive
from ..core import readable

NAME = "gtk3"
THEME = "AppGlass"

# app: (executable, desktop file id, autostart file or None)
APPS = {
    "solaar": ("solaar", "solaar.desktop", "solaar.desktop"),
    "nvidia-settings": ("nvidia-settings", "nvidia-settings.desktop", None),
}
APP_IDS = [r"^(solaar|nvidia-settings)$"]
TARGET = 2.25

ENV_PREFIX = "env GTK_THEME=%s " % THEME
MARK = "# appglass: Exec runs with GTK_THEME=%s (GTK3 glass theme)" % THEME


def installed_apps(env):
    return [a for a, (exe, _, _) in APPS.items() if env.which(exe)]


def installed(env):
    return bool(installed_apps(env))


def data_dirs(env):
    v = env.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [d for d in v.split(":") if d and os.path.isabs(d)
            and os.path.abspath(d) != env.data_home]


def config_dirs(env):
    v = env.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    return [d for d in v.split(":") if d and os.path.isabs(d)
            and os.path.abspath(d) != env.config_home]


def find_system(dirs, *rel):
    for d in dirs:
        p = os.path.join(d, *rel)
        if os.path.isfile(p):
            return p
    return None


def _a(v):
    """0.6 -> '0.60', 0.125 -> '0.125'."""
    s = ("%.3f" % v).rstrip("0")
    whole, frac = s.split(".")
    return "%s.%s" % (whole, frac.ljust(2, "0"))


# Adwaita greys all window text to #919190 when unfocused, with no transition
BACKDROP_FG = """\
/* Adwaita greys all window text to #919190 when unfocused (:backdrop): too faint on glass */
window.background:backdrop { color: mix(@window_fg_color, @window_bg_color, 0.15); }
"""
# with the inactive fade on, text keeps its focused colour (Adwaita's own
# focused names), so only the background changes and nothing jumps
BACKDROP_FG_FADE = """\
/* unfocused: the background fades, text keeps its focused colour */
window.background:backdrop, button:backdrop, button:backdrop.flat,
notebook > header > tabs > arrow:backdrop { color: @theme_fg_color; }
.view:backdrop, iconview:backdrop, .view text:backdrop, iconview text:backdrop,
textview text:backdrop, list:backdrop, entry:backdrop { color: @theme_text_color; }
"""

RULES = """\
/* content level {c} */
window.background, window.background:backdrop {{ background-color: alpha(@window_bg_color, {c}); }}
{backdrop_fg}.view, .view:backdrop, .view:disabled, iconview, iconview:backdrop,
.view text, .view text:backdrop, .view text:disabled, iconview text, iconview text:backdrop,
textview text, textview text:backdrop, textview text:disabled, textview border,
treeview.view, treeview.view:backdrop, list, list:backdrop, scrolledwindow viewport {{ background-color: transparent; }}
.view:selected, .view:selected:focus, treeview.view:selected, treeview.view:selected:focus, row:selected, iconview:selected {{ background-color: @accent_bg_color; color: @accent_fg_color; }}

/* bar level {b}. CSD headerbar is not painted over the window background -> {b} direct */
headerbar, headerbar:backdrop, .titlebar:not(headerbar), .titlebar:not(headerbar):backdrop {{
  background-color: alpha(@headerbar_bg_color, {b}); background-image: none; }}
window.csd > .titlebar:not(headerbar) {{ background-color: transparent; }}
/* bars inside the window: stacked over the {c} window -> {i} */
menubar, menubar:backdrop, .menubar, .menubar:backdrop, toolbar, toolbar:backdrop, .toolbar, .toolbar:backdrop,
.sidebar, .sidebar:backdrop, stacksidebar, stacksidebar:backdrop, placessidebar, placessidebar:backdrop,
actionbar > revealer > box, actionbar > revealer > box:backdrop, searchbar > revealer > box, statusbar {{
  background-color: alpha(@sidebar_bg_color, {i}); background-image: none; }}

/* popups level 1.0 */
menu, menu:backdrop, .menu, .menu:backdrop, .context-menu, .context-menu:backdrop,
window.popup, window.popup.background, window.popup.background:backdrop,
popover, popover.background, popover.background:backdrop,
tooltip, tooltip.background, .csd.popup decoration {{ background-color: @popover_bg_color; }}
tooltip label, tooltip * {{ color: @popover_fg_color; }}

/* text: solid colours instead of opacity */
.dim-label, label.dim-label, headerbar .subtitle, .titlebar .subtitle, .titlebar:not(headerbar) .subtitle {{
  opacity: 1; color: mix(@window_fg_color, @window_bg_color, 0.15); }}
label:disabled, label:disabled:backdrop {{ opacity: 1; color: mix(@window_fg_color, @window_bg_color, 0.20); }}

/* notebooks, StackSidebar, treeview column headers (stock Adwaita paints them opaque) */
notebook, notebook:backdrop, notebook > stack, notebook > stack:not(:only-child), notebook > stack:not(:only-child):backdrop {{ background-color: transparent; }}
notebook > header, notebook > header:backdrop {{ background-color: alpha(@sidebar_bg_color, {i}); }}
stacksidebar list, stacksidebar list:backdrop {{ background-color: alpha(@sidebar_bg_color, {i}); }}
treeview.view header button, treeview.view header button:backdrop {{ background-color: alpha(@sidebar_bg_color, {i}); background-image: none; }}
/* solid column-header text (too faint once the header is glass) */
treeview.view header button, treeview.view header button:backdrop {{ color: @window_fg_color; }}
/* GtkDialog bodies (About, message dialogs): the CSS node is dialog, not window */
dialog.background, dialog.background:backdrop {{ background-color: alpha(@window_bg_color, {c}); }}
"""


def render(ctx):
    lv = ctx.levels
    base = "gtk-contained.css" if ctx.mode == "light" else "gtk-contained-dark.css"
    colours = ctx.config_path("gtk-3.0", "dank-colors.css")
    lines = [
        "/* appglass: GTK3 glass theme (%s). Generated, do not edit: rewritten by" % THEME,
        "   appglass apply. Used by apps started with GTK_THEME=%s." % THEME,
        "   Levels: content %s, bars %s (inner %s over the content), popups 1.0."
        % (_a(lv.content), _a(lv.bar), _a(lv.bar_over_content)),
        "   Text never gets alpha. */",
        '@import url("resource:///org/gtk/libgtk/theme/Adwaita/%s");' % base,
        '@import url("file://%s");' % urllib.parse.quote(colours),
    ]
    sc = ctx.colors("surface_container")
    fg = ctx.colors("on_surface")
    rf = readable(fg, sc, lv.content, TARGET)
    if rf != fg:
        lines.append("/* on_surface %s is under %.2f:1 on the glass: moved */" % (fg, TARGET))
        lines.append("@define-color window_fg_color %s;" % rf)
        lines.append("@define-color view_fg_color %s;" % rf)
    lines.append("")
    fade = inactive.active(ctx.settings, lv.content)
    lines.append(RULES.format(c=_a(lv.content), b=_a(lv.bar), i=_a(lv.bar_over_content),
                              backdrop_fg=BACKDROP_FG_FADE if fade else BACKDROP_FG))
    lines += inactive_rule(ctx)
    return "\n".join(lines)


def inactive_rule(ctx):
    """Unfocused windows: the window background a little more transparent,
    faded by a transition (settings inactive). [] when off. After RULES, so
    it wins over the content rule for :backdrop."""
    c = ctx.levels.content
    if not inactive.active(ctx.settings, c):
        return []
    p = inactive.params(ctx.settings)
    lv = inactive.level(c, p["factor"])
    return [
        "/* inactive windows: background %s -> %s, faded (text stays opaque) */"
        % (_a(c), _a(lv)),
        "window.background { transition: %s; }" % inactive.transition("background-color",
                                                                       ctx.settings),
        "window.background:backdrop { background-color: alpha(@window_bg_color, %s); }"
        % _a(lv),
        "",
    ]


_EXEC = re.compile(r"^(Exec\s*=\s*)(.*)$")


def themed(text, mark=False):
    """Every Exec= line runs with GTK_THEME=AppGlass; idempotent."""
    out = []
    for ln in text.splitlines(keepends=True):
        body = ln.rstrip("\r\n")
        nl = ln[len(body):]
        m = _EXEC.match(body)
        if m:
            cmd = m.group(2)
            if re.search(r"(^|\s)GTK_THEME=\S*", cmd):
                cmd = re.sub(r"(^|\s)GTK_THEME=\S*", r"\1GTK_THEME=" + THEME, cmd, count=1)
            elif not cmd.startswith(ENV_PREFIX):
                cmd = ENV_PREFIX + cmd
            body = m.group(1) + cmd
        elif re.match(r"^DBusActivatable\s*=\s*true\s*$", body, re.I):
            body = "DBusActivatable=false"   # D-Bus activation would skip Exec
        out.append(body + nl)
    text = "".join(out)
    if mark and MARK not in text:
        text = MARK + "\n" + text
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def has_theme(text):
    """Some Exec= line runs with GTK_THEME=AppGlass."""
    return any(_EXEC.match(ln) and re.search(r"(^|\s)GTK_THEME=%s(\s|$)" % THEME, ln)
               for ln in text.splitlines())


def undo(env, path, text):
    """Take the GTK_THEME prefix out of a user .desktop file changed since."""
    out = []
    for ln in text.splitlines(keepends=True):
        if ln.strip() == MARK:
            continue
        if _EXEC.match(ln.rstrip("\r\n")):
            ln = ln.replace(ENV_PREFIX, "", 1)
        out.append(ln)
    return "".join(out)


def _override(ctx, dest, source):
    """A themed copy of source, or a minimal edit of an existing user file.

    Both go through edit_text, so the file stays the user's: a change made
    after apply (Hidden=true, a menu editor, GTK_THEME taken out) is kept on
    the next apply, and remove takes our part out of a changed copy (deleted
    when nothing of the user's is left). A symlinked dest
    (dotfiles) is left alone. Returns dest, or None when nothing is overridden.
    """
    if os.path.islink(dest):
        ctx.warn("%s is a symlink (user-managed); left untouched, no override"
                 % ctx.env.tilde(dest))
        return None
    if os.path.lexists(dest) and not os.path.isfile(dest):
        ctx.warn("%s is not a regular file; left untouched" % ctx.env.tilde(dest))
        return None
    src = None
    if source is not None:
        with open(source, "r", encoding="utf-8") as f:
            src = themed(f.read(), mark=True)
    elif not os.path.lexists(dest) or MARK in (ctx.read_text(dest) or ""):
        return None                    # nothing to copy, or our old copy: dropped

    changed = ctx.changed_since_apply(dest)
    if changed and not ctx.deleted_since_apply(dest) and not has_theme(ctx.read_text(dest) or ""):
        ctx.warn_once("opt-out:" + dest,
                      "%s no longer runs with GTK_THEME=%s; kept (remove + apply "
                      "puts it back)" % (ctx.env.tilde(dest), THEME))

    def fn(text):
        if changed:
            # changed since apply: the user's file now. Keep their opt-out
            # (GTK_THEME taken out, file emptied); themed() is a no-op otherwise
            return themed(text) if has_theme(text) else text
        return src if src is not None and not text.strip() else themed(text)

    ctx.edit_text(dest, fn, undo=lambda t: undo(ctx.env, dest, t))
    return dest


def apply(ctx):
    env = ctx.env
    paths = []
    if not os.path.isfile(ctx.config_path("gtk-3.0", "dank-colors.css")):
        # imported by URL at run time, so the theme is the same either way.
        # The matugen hook can run before DMS has rendered it (in parallel):
        # say it once, not on every theme change.
        ctx.warn_once("dank-colors", "%s not found: the AppGlass theme imports it; "
                      "GTK3 apps keep the stock Adwaita colours until DMS writes it"
                      % env.tilde(ctx.config_path("gtk-3.0", "dank-colors.css")))
    theme = ctx.data_path("themes", THEME, "gtk-3.0", "gtk.css")
    ctx.write_owned(theme, render(ctx))
    paths.append(theme)
    apps = []
    ddirs, cdirs = data_dirs(env), config_dirs(env)
    for app in installed_apps(env):
        exe, desk, auto = APPS[app]
        source = find_system(ddirs, "applications", desk)
        p = _override(ctx, ctx.data_path("applications", desk), source)
        if p:
            paths.append(p)
        elif source is None:
            ctx.warn("%s: no %s in XDG_DATA_DIRS; no launcher override" % (app, desk))
        if auto:
            p = _override(ctx, ctx.config_path("autostart", auto),
                          find_system(cdirs, "autostart", auto))
            if p:
                paths.append(p)
        apps.append(app)
    ctx.app_ids = ["^(%s)$" % "|".join(apps)] if apps else []
    return paths
