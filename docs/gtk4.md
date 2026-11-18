# GTK4 / libadwaita

> **Research notes.** This page records what was tried before appglass shipped its routes, and the findings behind them. What appglass does today for each app is in [routes.md](routes.md); where the two disagree, routes.md is current.

libadwaita 1.10 (GTK 4.24) apps get real glass from `~/.config/gtk-4.0/gtk.css` alone: alpha on the background colour roles, text and icons stay opaque, popovers and dialogs stay solid. Nautilus is tested. The other libadwaita apps use the same file and are documented only. Flatpak GTK4 apps do not read the host `gtk-4.0` folder: appglass gives them their own copy or a launcher override for that launch only, never a persistent `flatpak override` ([routes.md](routes.md#gtk4--libadwaita)); the `flatpak override` lines below are the manual way. Any GTK4 app without a niri `opacity 1.0` rule gets double translucency (see caveats).

## Apps

| App | Tested / Documented | Works | Method | niri rule needed |
|---|---|---|---|---|
| Nautilus (Files) 51.1 | Tested | yes | `gtk-4.0/gtk.css` alpha on bg roles + dialog-sheet rule + `--dim-opacity` | `org.gnome.Nautilus` → `opacity 1.0` |
| libadwaita role test (small test app: raised headerbar, split-view sidebar, boxed-list cards, TextView, PopoverMenu, AdwAlertDialog) | Tested | yes | same `gtk.css` | n/a (test app) |
| GNOME Software 51.1 | Documented (installed, not launched) | expected yes | same `gtk.css` | `org.gnome.Software` → `opacity 1.0` |
| xdg-desktop-portal-gnome (file chooser) | Documented (installed, not launched) | expected yes | inherits `gtk.css` | `xdg-desktop-portal-gnome` → `opacity 1.0` |
| Zenity | Documented (installed, not launched) | expected yes | inherits `gtk.css` | `org.gnome.Zenity` → `opacity 1.0` |
| Flatseal (flatpak) | Documented (not installed, no GNOME runtime) | partial | `gtk.css` + `flatpak override --filesystem=xdg-config/gtk-4.0:ro` | `com.github.tchx84.Flatseal` → `opacity 1.0` |

GNOME Software was not launched because it talks to the system packagekitd and fwupd and refreshes metadata over the network.

## Levels

| Level | Target | Surfaces | Reached? |
|---|---|---|---|
| Content | 0.60 (153) | `window_bg_color`, `view_bg_color` | yes, measured 153 |
| Bars | 0.65 (166) | sidebar, secondary sidebar, raised headerbar, cards / boxed lists | yes, measured 166 (inner alpha 0.125 over the 0.60 base) |
| Popups | 1.0 (255) | popovers, popover menus, AdwAlertDialog, AdwPreferencesDialog | yes, measured 255 (dialogs need the `dialog sheet` rule) |
| Tooltips | 1.0 | `popover_bg_color` surfaces | not measured (no hover input in the test session) |

Cannot reach the target:
- Nautilus's main content headerbar is flat by libadwaita design (AdwToolbarView), so it shows 0.60, not 0.65. Only the sidebar shows the bar level in Nautilus.
- A GtkTextView or other `.view` widget on a window-bg page stacks to 214 (0.84). More opaque than the target, harmless.

Why 0.125 for bars: libadwaita paints sidebars, headerbars and cards on top of the window/view background, so layers stack. An inner alpha `a` over the 0.60 base gives `1 - 0.40 * (1 - a)`. `a = 0.125` gives exactly 0.65. A diagnostic run with an inner alpha of 0.65 gave 219 (0.86).

## Settings

### Starting point

`~/.config/gtk-4.0/` currently holds only `dank-colors.css` and `settings.ini` (icon theme Fluent-dark). There is no `gtk.css`, so nothing imports `dank-colors.css` and GTK4 apps run stock Adwaita dark today. Creating `gtk.css` therefore also switches every GTK4 app to the DMS palette, not only to glass.

DMS `gtk.sh` (`/usr/share/quickshell/dms/scripts/gtk.sh`) treats a `gtk.css` that already contains `@import url("dank-colors.css");` as user-managed and leaves the extra lines alone. If GTK theming is switched off in DMS, it removes only the import line. The glass overrides stay.

### Tested gtk.css (static)

`~/.config/gtk-4.0/gtk.css`, hex values taken from the current `dank-colors.css`. This is the exact file tested in the nested niri session, plus the unfocused-window fix from the second run (see caveats):

```css
@import url("dank-colors.css");
/* Background roles get alpha by level. Text (*_fg_color) roles are untouched. */
@define-color window_bg_color alpha(#1e2226, 0.60);
@define-color view_bg_color alpha(#191c20, 0.60);
/* Inner layers stack on the 0.60 base: 0.125 -> 0.65 net */
@define-color headerbar_bg_color alpha(#1e2226, 0.125);
@define-color headerbar_backdrop_color alpha(#1e2226, 0.125);
@define-color sidebar_bg_color alpha(#282c30, 0.125);
@define-color sidebar_backdrop_color alpha(#282c30, 0.125);
@define-color secondary_sidebar_bg_color alpha(#1e2226, 0.125);
@define-color secondary_sidebar_backdrop_color alpha(#1e2226, 0.125);
@define-color card_bg_color alpha(#282c30, 0.125);
@define-color overview_bg_color alpha(#282c30, 0.60);
/* Popups opaque */
@define-color popover_bg_color #282c30;
@define-color dialog_bg_color #1e2226;

/* AdwDialog sheets paint window_bg_color: force the opaque dialog colour */
dialog sheet { background-color: @dialog_bg_color; }

/* Dimmed text (.dim-label/.dimmed, pathbar, subtitles) defaults to 0.55 */
:root { --dim-opacity: 0.80; }

/* Unfocused windows: Adwaita fades bar contents with filter: opacity(0.5) */
headerbar:backdrop > windowhandle,
toolbarview > .top-bar:backdrop > windowhandle, toolbarview > .bottom-bar:backdrop > windowhandle,
searchbar > revealer > box:backdrop > *, actionbar > revealer > box:backdrop > *,
tabbar .box:backdrop > scrolledwindow, tabbar .box:backdrop > .start-action, tabbar .box:backdrop > .end-action { filter: opacity(0.8); }
```

Notes:
- The `@define-color` overrides reach libadwaita 1.10's CSS variables. No `--window-bg-color` override, no `window { background: transparent }`, no `.background` hack is needed.
- No `*_fg_color` role is touched.

### Following DMS colours (matugen, untested)

The hex values above go stale when the wallpaper or scheme changes. To follow DMS, render a second file next to `dank-colors.css` with matugen and import it after the DMS one. The stock DMS `gtk.toml` only has `dmsgtk3` / `dmsgtk4` (both writing `dank-colors.css`), so the extra entry goes into the user's own matugen config (DMS can run user templates).

`~/.config/gtk-4.0/gtk.css`:
```css
@import url("dank-colors.css");
@import url("dank-glass.css");
```

Template (`dank-glass.css` template, output `$XDG_CONFIG_HOME/gtk-4.0/dank-glass.css`):
```css
@define-color window_bg_color alpha({{colors.surface_container.default.hex}}, 0.60);
@define-color view_bg_color alpha({{colors.surface_container_low.default.hex}}, 0.60);
@define-color headerbar_bg_color alpha({{colors.surface_container.default.hex}}, 0.125);
@define-color headerbar_backdrop_color alpha({{colors.surface_container.default.hex}}, 0.125);
@define-color sidebar_bg_color alpha({{colors.surface_container_high.default.hex}}, 0.125);
@define-color sidebar_backdrop_color alpha({{colors.surface_container_high.default.hex}}, 0.125);
@define-color secondary_sidebar_bg_color alpha({{colors.surface_container.default.hex}}, 0.125);
@define-color secondary_sidebar_backdrop_color alpha({{colors.surface_container.default.hex}}, 0.125);
@define-color card_bg_color alpha({{colors.surface_container_high.default.hex}}, 0.125);
@define-color overview_bg_color alpha({{colors.surface_container_high.default.hex}}, 0.60);
@define-color popover_bg_color {{colors.surface_container_high.default.hex}};
@define-color dialog_bg_color {{colors.surface_container.default.hex}};
dialog sheet { background-color: @dialog_bg_color; }
:root { --dim-opacity: 0.80; }
/* append the :backdrop filter block from the static file */
```

Matugen entry, same shape as the DMS one:
```toml
[templates.appglassgtk4]
input_path = '<path to the dank-glass.css template>'
output_path = '~/.config/gtk-4.0/dank-glass.css'
```

This template and entry were not run. Only the static file was tested.

### Reload

GTK does not live-reload `gtk.css`. Editing it while Nautilus ran changed nothing. Restart the app after DMS rewrites colours, same as today for `dank-colors.css`.

### niri rule

`gtk.css` is read by every GTK4 app, so every GTK4 app you run must be listed. Put the rule after the global "Glass blur" rule (`opacity 0.60`, blur on) in `~/.config/niri/dms/windowrules.kdl`: later rules win. For example a file `~/.config/niri/appglass-gtk4.kdl`, included after `include "dms/windowrules.kdl"` in `~/.config/niri/config.kdl`, the same way `dms-browser-glass.kdl` is:

```kdl
// GTK4/libadwaita apps paint their own translucent background via
// ~/.config/gtk-4.0/gtk.css, so niri must not fade them again.
window-rule {
    match app-id=r#"^org\.gnome\.(Nautilus|Software|Zenity|Epiphany.*)$"#
    match app-id=r#"^xdg-desktop-portal-gnome$"#
    match app-id=r#"^com\.github\.tchx84\.Flatseal$"#
    opacity 1.0
}
```

Checked with `niri validate`. In the nested niri session, a global `opacity 0.60` rule followed by this `opacity 1.0` rule gave screen pixels identical to a run with no rule. Blur from the global rule stays on.

## Measured results (tested in a nested niri session)

Alpha out of 255, region crops of the RGBA window screenshot. Two independent runs (Nautilus; role-test app) matched the first run on every number.

| Region | Nautilus | Role-test app |
|---|---|---|
| Content (window / view) | 153 (0.60) | 153 (0.60) |
| Sidebar, sidebar header | 166 (0.65) | 166 (0.65) |
| Raised headerbar | n/a (flat, 153) | 166 (0.65) |
| Cards / boxed list | n/a | 166 (0.65) |
| Pathbar entry | 163 | n/a |
| GtkTextView | n/a | 214 (0.84) |
| Popover / popover menu | 255 | 255 |
| AdwPreferencesDialog, with `dialog sheet` rule | 255 | n/a |
| AdwPreferencesDialog, without it | 235-247 (bug) | n/a |
| AdwAlertDialog | n/a | 255 |
| Dimmed content behind a modal dialog | 204 | 204-210 |
| Selected sidebar row, suggested-action button | n/a | 255 |
| No `gtk.css` (control) | 255 everywhere | n/a |

The 20 px border at alpha 0 in every shot, the control included, is the CSD shadow margin. The glass CSS does not cause it.

Text and logos:
- Normal text glyph cores reach alpha 255. Zoomed crops of labels, sidebar and pathbar are sharp, no fading.
- Dimmed and subtitle text is translucent by Adwaita design: glyph alpha about 209 at the default 0.55, about 235 with `--dim-opacity: 0.80`.
- Unfocused-window bar titles: glyph alpha 210 at the stock `filter: opacity(0.5)`.
- Full-colour icons (Fluent folders, thumbnails, PNG logo) stay opaque. Symbolic icons, `github-symbolic` included, are recoloured to the light foreground. The dark GitHub logo shows on a light circle. No icon became invisible, nothing turned black where it should be transparent.

Contrast: to re-measure. The composites used for the ratios in the first test run treated the premultiplied screenshots as straight alpha, which makes them too pessimistic (the white-backdrop numbers most of all). The early numbers ranked dimmed text and unfocused bar text as the weakest; `--dim-opacity: 0.80` and the `:backdrop` filter rule are kept because they raise glyph alpha.

## What breaks / caveats

- **Global file, double translucency.** Any GTK4 app not in the niri rule gets the CSS alpha and the global niri 0.60: about 0.36 background and text at 0.60. Add every GTK4 app you run to the rule. The GNOME file chooser portal is used by Chrome, Electron and other portal apps, so its rule matters most.
- **AdwDialog sheets** paint `window_bg_color`, so without `dialog sheet { background-color: @dialog_bg_color; }` the content shows through the dialog (235-247).
- **Dimmed text** (`.dim-label`, `.dimmed`, pathbar, row subtitles, headerbar subtitle) uses `--dim-opacity` 0.55 by default. Use 0.80.
- **Unfocused windows** fade bar contents with `filter: opacity(0.5)`, which `--dim-opacity` does not cover. Found in the second run, not in the first. Fixed by the `:backdrop` rule above (raised to 0.8, tested).
- **Light mode** not tested. The static file hardcodes the current dark hex values, so a DMS light/dark switch needs the matugen version, then an app restart.
- **No live reload**, see Reload.
- **Turning DMS GTK theming off** removes only the import line. The hardcoded glass overrides stay in `gtk.css`.
- **Flatpak apps** see `~/.var/app/<id>/config`, not the host `~/.config/gtk-4.0`, unless given a filesystem override.
- **Plain GTK4 apps without libadwaita** use the GTK default theme, which reads `gtk.css` but uses other colour names (`theme_bg_color` etc.). None installed, not tested.
- Not tested: tooltips, right-click menus, dialogs other than Nautilus Preferences.
- Low contrast that is not a glass regression: insensitive back/forward arrows (disabled controls) and an all-black image thumbnail on dark glass are just as low on the stock opaque background. The Nautilus thumbnail frame keeps the thumbnail visible.

## Documented only (unverified)

- **GNOME Software** (`org.gnome.Software`): same libadwaita 1.10, same `gtk.css`. Expected 0.60 / 0.65 / 1.0 like Nautilus. App icons are full colour and opaque. Needs the niri rule.
- **xdg-desktop-portal-gnome** (file chooser, default portal per niri-portals.conf) and **Zenity** (`org.gnome.Zenity`): libadwaita, inherit `gtk.css` automatically. Need the niri rule.
- **Epiphany web apps** (epiphany-runtime is installed): libadwaita, covered by `Epiphany.*` in the rule. Not looked at further.
- **Flatseal** (`com.github.tchx84.Flatseal`): not installed, and no `org.gnome.Platform` runtime is present. Commonly documented route, expose the host GTK4 config read-only (per app, or drop the id for all flatpaks):
  ```sh
  flatpak override --user --filesystem=xdg-config/gtk-4.0:ro com.github.tchx84.Flatseal
  ```
  `dank-colors.css` and the glass file must sit in that same directory for the imports to resolve. Plus the niri rule. Marked partial until tested.
