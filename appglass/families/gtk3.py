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

from ..core import TARGET, fmt_alpha, readable

NAME = "gtk3"
THEME = "AppGlass"

# app: (executable, desktop file id, autostart file or None)
APPS = {
    "solaar": ("solaar", "solaar.desktop", "solaar.desktop"),
    "nvidia-settings": ("nvidia-settings", "nvidia-settings.desktop", None),
}
APP_IDS = [r"^(solaar|nvidia-settings)$"]
# the engine routes every other host GTK3 app here too (ctx.records())
GENERIC = True
# the route is an environment variable on the launcher: never for an app
# that starts other apps (adapters.resolve)
ENV_ROUTE = True

ENV_PREFIX = "env GTK_THEME=%s " % THEME
MARK = "# appglass: Exec runs with GTK_THEME=%s (GTK3 glass theme)" % THEME
# only a copy of a system launcher gets the header (a launcher of the
# user's own is edited without it): adopt --rescue takes it as proof that
# appglass made the file
CREATED_MARK = MARK


def accepts(rec):
    """None when a GTK3 record can take the AppGlass theme, else why not."""
    if rec.get("flatpak"):
        return "GTK3 flatpak: the AppGlass theme is not visible inside the sandbox"
    if rec.get("user_only"):
        return "a launcher of yours with no system one: left as it is"
    return None


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


_a = fmt_alpha   # 0.6 -> '0.60', 0.125 -> '0.125'


# an unfocused window looks like a focused one: Adwaita greys all window text
# to #919190 when unfocused (:backdrop); text keeps its focused colour
# (Adwaita's own focused names)
BACKDROP_FG = """\
/* unfocused: text keeps its focused colour (Adwaita greys it on :backdrop) */
window.background:backdrop, button:backdrop, button:backdrop.flat,
notebook > header > tabs > arrow:backdrop { color: @theme_fg_color; }
.view:backdrop, iconview:backdrop, .view text:backdrop, iconview text:backdrop,
textview text:backdrop, list:backdrop, entry:backdrop, spinbutton:backdrop:not(.vertical) {
  color: @theme_text_color; }
notebook > header tab:backdrop, notebook > header tab:backdrop:checked { color: @theme_fg_color; }
/* Adwaita's spin button arrows: fg mixed 10.5% / 21% towards the background */
spinbutton:not(.vertical) button:backdrop { color: mix(@theme_fg_color, @theme_bg_color, 0.105); }
spinbutton:not(.vertical) image:backdrop, entry image:backdrop {
  color: mix(@theme_fg_color, @theme_bg_color, 0.21); }
/* the bar's framed buttons keep their focused edges; the window buttons
   (.titlebutton) and flat buttons have none, so they get none (no ring) */
headerbar button:not(.titlebutton):not(.flat):backdrop,
.titlebar button:not(.titlebutton):not(.flat):backdrop {
  border-color: @borders; border-bottom-color: {edge}; }
/* plain buttons keep their focused edges, gradient and shadows; the more
   specific ones (flat, titlebutton, suggested, spin) win in both states */
button:backdrop { border-color: {border}; border-bottom-color: {edge};
  background-image: {button_bg}; text-shadow: {shadow}; -gtk-icon-shadow: {shadow};
  box-shadow: {button_box}; }
frame > border:backdrop, .frame:backdrop { border-color: {border}; }
/* tree views: tree lines, header separators, expanders and insensitive rows
   keep their colours */
treeview.view:backdrop { border-left-color: {tree_lines}; }
treeview.view header button:backdrop { border-color: {header_border}; }
treeview.view.expander, treeview.view.expander:backdrop { color: {expander}; }
treeview.view.expander:selected, treeview.view.expander:selected:backdrop { color: {expander_sel}; }
treeview.view:disabled, treeview.view:disabled:backdrop { color: {insensitive}; }
treeview.view:disabled:selected, treeview.view:disabled:selected:backdrop { color: {insensitive_sel}; }
treeview.view.separator, treeview.view.separator:backdrop { color: {tree_separator}; }
/* paned separators (Adwaita lightens them on :backdrop) */
paned > separator:backdrop { background-image: image({border}); }
paned > separator.wide:backdrop { background-image: image({border}), image({border}); }
"""
# Adwaita's focused literals (no named colour for them), per mode
ADWAITA = {
    "dark": {"edge": "#070707", "border": "#1b1b1b",
             "button_bg": "linear-gradient(to top, #323232 2px, #353535)",
             "shadow": "0 -1px rgba(0, 0, 0, 0.834353)",
             "button_box": "inset 0 1px rgba(255, 255, 255, 0.02), 0 1px 2px rgba(0, 0, 0, 0.07)",
             "tree_lines": "#8e8e8d", "header_border": "#545453", "expander": "silver",
             "expander_sel": "#b9cbe2", "insensitive": "#919190", "insensitive_sel": "#7398c5",
             "tree_separator": "#353535"},
    "light": {"edge": "#bfb8b1", "border": "#cdc7c2",
              "button_bg": "linear-gradient(to top, #edebe9 2px, #f6f5f4)",
              "shadow": "0 1px rgba(255, 255, 255, 0.769231)",
              "button_box": "inset 0 1px white, 0 1px 2px rgba(0, 0, 0, 0.07)",
              "tree_lines": "#979a9b", "header_border": "#d7d2ce", "expander": "#4d4d4d",
              "expander_sel": "#c2daf7", "insensitive": "#929595", "insensitive_sel": "#86b5ef",
              "tree_separator": "#f6f5f4"},
}


def backdrop_fg(mode):
    css = BACKDROP_FG
    for k, v in ADWAITA[mode].items():
        css = css.replace("{%s}" % k, v)
    return css

RULES = """\
/* content level {c} */
window.background, window.background:backdrop {{ background-color: alpha(@window_bg_color, {c}); }}
{backdrop_fg}.view, .view:backdrop, .view:disabled, iconview, iconview:backdrop,
.view text, .view text:backdrop, .view text:disabled, iconview text, iconview text:backdrop,
textview text, textview text:backdrop, textview text:disabled, textview border,
treeview.view, treeview.view:backdrop, list, list:backdrop, scrolledwindow viewport {{ background-color: transparent; }}
.view:selected, .view:selected:focus, treeview.view:selected, treeview.view:selected:focus, row:selected, iconview:selected,
.view:selected:backdrop, treeview.view:selected:backdrop, row:selected:backdrop, row.activatable:selected,
row.activatable:selected:backdrop, iconview:selected:backdrop {{ background-color: @accent_bg_color; color: @accent_fg_color; }}

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
    lines.append(RULES.format(c=_a(lv.content), b=_a(lv.bar), i=_a(lv.bar_over_content),
                              backdrop_fg=backdrop_fg("light" if ctx.mode == "light" else "dark")))
    return "\n".join(lines)


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


def _override(ctx, dest, source, plain=False):
    """A themed copy of source, or a minimal edit of an existing user file.

    Both go through edit_text, so the file stays the user's: a change made
    after apply (Hidden=true, a menu editor, GTK_THEME taken out) is kept on
    the next apply, and remove takes our part out of a changed copy (deleted
    when nothing of the user's is left). A symlinked dest
    (dotfiles) is left alone. Returns dest, or None when nothing is overridden.

    plain: the engine holds the app opaque (S7): a launcher written before
    goes back to the plain command (the system text, or the user's own
    with our prefix out), until the next fingerprint brings the glass back.
    An event (hook run) never takes over a launcher the user made: only a
    typed apply edits one in place (backed up), as qtstyle and gtk4 refuse.
    """
    if plain and not ctx.owns(dest):
        return None                    # nothing of ours to take back
    if (ctx.app.from_hook and not ctx.owns(dest) and os.path.lexists(dest)
            and ctx.app.state.owner_of(os.path.abspath(dest)) is None):
        ctx.warn_once("hand-made:" + dest,
                      "%s is a launcher of yours: left as it is (a typed appglass apply "
                      "edits it, backed up)" % ctx.env.tilde(dest))
        return None
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
            src = f.read()
        src = src if plain else themed(src, mark=True)
    elif getattr(ctx, "probe", False) and MARK in (ctx.read_text(dest) or ""):
        # state.json lost, the app uninstalled since: the copy appglass
        # made, with the system text it was made from read back out of it
        src = themed(undo(ctx.env, dest, ctx.read_text(dest)), mark=True)
    elif not os.path.lexists(dest) or MARK in (ctx.read_text(dest) or ""):
        return None                    # nothing to copy, or our old copy: dropped

    changed = ctx.changed_since_apply(dest)
    if plain:
        def fn(text):
            # our prefix out; the rest (the user's own edits) kept
            return src if src is not None and not text.strip() else undo(ctx.env, dest, text)

        ctx.edit_text(dest, fn, undo=lambda t: undo(ctx.env, dest, t))
        return dest
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
    # held opaque by the engine (S7): their launchers run the plain app
    plain = {r["desktop_id"]: r for r in ctx.records(plain=True)}
    for app in installed_apps(env):
        exe, desk, auto = APPS[app]
        off = desk in plain
        source = find_system(ddirs, "applications", desk)
        p = _override(ctx, ctx.data_path("applications", desk), source, plain=off)
        if p:
            paths.append(p)
        elif source is None and not off:
            ctx.warn("%s: no %s in XDG_DATA_DIRS; no launcher override" % (app, desk))
        if auto:
            p = _override(ctx, ctx.config_path("autostart", auto),
                          find_system(cdirs, "autostart", auto), plain=off)
            if p:
                paths.append(p)
        if not off:
            apps.append(app)
    ids = ["^(%s)$" % "|".join(apps)] if apps else []
    # every other GTK3 app the engine routes here (launcher override only)
    listed = {d for _, d, _ in APPS.values()}
    for rec in ctx.records():
        if rec["desktop_id"] in listed or rec["key"] in APPS:
            continue
        p = _override(ctx, ctx.data_path("applications", rec["desktop_id"]), rec["path"])
        if p:
            paths.append(p)
            ids += [x for x in rec.get("app_ids") or () if x not in ids]
    for did, rec in plain.items():
        if did in listed or rec["key"] in APPS:
            continue
        p = _override(ctx, ctx.data_path("applications", did), rec["path"], plain=True)
        if p:
            paths.append(p)
    ctx.app_ids = ids
    return paths
