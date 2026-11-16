# GTK3

GTK3 apps on native Wayland get real glass from CSS alone: no RGBA visual, no code change, no daemon. Solaar and nvidia-settings were tested in a nested niri session, along with a GTK3 test app (headerbar, menubar, toolbar, sidebars, notebook, textview, treeview, statusbar, popover, menu). Content reaches 0.60, bars 0.65 and menus/popovers 1.0, and the text stays opaque. The base rules need a notebook add-on, and `GtkDialog` bodies are not covered yet.
Timeshift (runs as root through pkexec and XWayland), GIMP, LibreOffice and Thunderbird stay on the global niri opacity fallback. Inkscape is partial at best.

## Apps

| App | Tested / Documented | Works | Method | niri rule needed |
|---|---|---|---|---|
| GTK3 test app (Gtk 3.24.52 stand-in with every common widget) | Tested in a nested niri session | partial (yes with the notebook add-on; dialogs and tooltips not covered) | `appglass-gtk3.css` imported after `dank-colors.css` (mode A or B) | `opacity 1.0` on its app-id |
| Solaar 1.1.20 | Tested in a nested niri session (modes A and B) | yes (main window, Rule Editor, tray menu); About dialog body stays opaque | Same CSS. Mode B through a `~/.config/autostart/solaar.desktop` override | `opacity 1.0`, app-id `solaar` |
| nvidia-settings | Tested in a nested niri session (mode A) | partial (2 of 6 pages opaque without the notebook add-on; with it, column-header text is too faint) | Same CSS plus the notebook add-on. Mode B through a `.desktop` override | `opacity 1.0`, app-id `nvidia-settings` |
| Timeshift 25.12.4 | Documented only (installed, not run: needs root) | no (fallback) | None. `pkexec timeshift-gtk` runs as root, reads `/root/.config/gtk-3.0` and goes through xwayland-satellite | None. Keep the global `opacity 0.60` |
| Thunar | Documented only (not installed) | yes (expected) | Same CSS. The side pane is a `.sidebar` treeview and the views are `.view`/iconview | `opacity 1.0`, app-id `thunar` |
| Inkscape 1.x | Documented only (not installed) | partial (expected: panels only) | Extra CSS in `~/.config/inkscape/ui/style.css`. The canvas is opaque | `opacity 1.0`, app-id `org.inkscape.Inkscape`, only if adopted |
| GIMP (2.10 = GTK2, 3.x = GTK3) | Documented only (not installed) | no (fallback) | 2.10: no CSS alpha path. 3.x: its own `gimp.css` theme overrides colours, and the canvas is opaque | None (fallback, or keep it opaque) |
| LibreOffice (VCL gtk3 plugin) | Documented only (not installed) | no (fallback) | VCL paints its own opaque surfaces, so GTK CSS alpha never reaches the window | None (fallback) |
| Thunderbird | Documented only (not installed) | no (not via GTK3) | Gecko draws its own UI (Gecko/userChrome, not covered by these docs yet) | None (fallback) |

## Levels

| Surface | Target | Reachable? |
|---|---|---|
| Window content (`window.background`, views, treeview rows, textview, notebook page) | 0.60 (alpha 153) | Yes, measured 0.600. Notebook pages need the add-on (stock Adwaita paints them opaque) |
| CSD headerbar | 0.65 (alpha 166) | Yes, measured 0.651 (alpha set directly, because it is not drawn over the window background) |
| menubar, toolbar, statusbar, `.sidebar`, StackSidebar, notebook tabs, treeview column headers | 0.65 (alpha 166) | Yes, measured 0.651, using the stacked alpha 0.125 (see below). StackSidebar, tabs and column headers need the add-on |
| Menus (`GtkMenu` xdg_popup), popovers, combo-box menus | 1.0 | Yes, measured 1.000 / no tint over a #ff00ff background |
| Tooltips | 1.0 | Rule written. **Untested** (no pointer input in the nested session) |
| `GtkDialog` body (About, Pair, message dialogs) | 0.60 | **No** with the current rules. The CSS node is `dialog`, not `window`, so the body stays opaque stock Adwaita `#353535`. Proposed rule below, untested |
| Buttons, entries, combo boxes, switches | — | Stay opaque (alpha 1.0). Small surfaces, which is acceptable |
| Text, icons, bitmaps | never alpha'd | Yes. Glyph cores reach alpha 255, and app-drawn bitmaps (NVIDIA banner) stay 255 |
| XWayland GTK3 windows | 0.60 | No (documented). Non-CSD X11 GTK3 windows get a non-RGBA visual, so the CSS alpha turns black/opaque. Fallback |

**Alphas stack.** A widget painted on top of the 0.60 window needs `a = (target - 0.60) / (1 - 0.60)`. For 0.65 that is **0.125**. The first naive attempt used 0.65 everywhere and measured 0.859 on menubar/toolbar/sidebar and 0.937 on the textview (three layers). Views therefore get `transparent`, and inner bars get `alpha(..., 0.125)`.

## Settings

### Starting point (current session)

- `~/.config/gtk-3.0/` holds `dank-colors.css` (written by the DMS matugen template `dmsgtk3`: `matugen/configs/gtk.toml`, template `gtk-colors.css`) and `settings.ini` (icon theme only). There is **no `gtk.css`**, so `dank-colors.css` is not loaded, and GTK3 apps render **light stock Adwaita** today. GTK3 ignores `color-scheme=prefer-dark`.
- `dank-colors.css` defines libadwaita colour names (`window_bg_color`, `headerbar_bg_color`, `sidebar_bg_color`, `popover_bg_color`, `accent_bg_color`…). Stock GTK3 Adwaita compiles its colours to literals, so these names do nothing on their own. The glass CSS references them explicitly, and that is how DMS colours reach GTK3.
- **Colour reuse:** `appglass-gtk3.css` contains no hex values, only `@window_bg_color` and the other names. It is a static file. Every time DMS/matugen regenerates `dank-colors.css`, the glass follows on the next app start, so no extra matugen template is needed.

### `~/.config/gtk-3.0/appglass-gtk3.css` (dark DMS scheme)

The base rules (tested in modes A and B), then the add-on (tested in mode A), then two proposed rules (untested):

```css
/* appGlass GTK3 rules (dark DMS scheme). Needs dank-colors.css imported before it.
   Levels: content 0.60, bars 0.65, menus/popovers/tooltips 1.0. Text never gets alpha.
   Alphas stack: a bar painted over the 0.60 window uses a = (0.65 - 0.60) / (1 - 0.60) = 0.125.
   Selectors carry :backdrop/:disabled variants and ".view text" so they also win
   when loaded as a theme (GTK_THEME) instead of the user gtk.css. */

/* content level 0.60 */
window.background, window.background:backdrop { background-color: alpha(@window_bg_color, 0.60); }
/* Adwaita greys all window text to #919190 when unfocused (:backdrop): too faint on glass */
window.background:backdrop { color: mix(@window_fg_color, @window_bg_color, 0.15); }
.view, .view:backdrop, .view:disabled, iconview, iconview:backdrop,
.view text, .view text:backdrop, .view text:disabled, iconview text, iconview text:backdrop,
textview text, textview text:backdrop, textview text:disabled, textview border,
treeview.view, treeview.view:backdrop, list, list:backdrop, scrolledwindow viewport { background-color: transparent; }
.view:selected, .view:selected:focus, treeview.view:selected, treeview.view:selected:focus, row:selected, iconview:selected { background-color: @accent_bg_color; color: @accent_fg_color; }

/* bar level 0.65. CSD headerbar is not painted over the window background -> 0.65 direct */
headerbar, headerbar:backdrop, .titlebar:not(headerbar), .titlebar:not(headerbar):backdrop {
  background-color: alpha(@headerbar_bg_color, 0.65); background-image: none; }
window.csd > .titlebar:not(headerbar) { background-color: transparent; }
/* bars inside the window: stacked over the 0.60 window -> 0.125 */
menubar, menubar:backdrop, .menubar, .menubar:backdrop, toolbar, toolbar:backdrop, .toolbar, .toolbar:backdrop,
.sidebar, .sidebar:backdrop, stacksidebar, stacksidebar:backdrop, placessidebar, placessidebar:backdrop,
actionbar > revealer > box, actionbar > revealer > box:backdrop, searchbar > revealer > box, statusbar {
  background-color: alpha(@sidebar_bg_color, 0.125); background-image: none; }

/* popups level 1.0 */
menu, menu:backdrop, .menu, .menu:backdrop, .context-menu, .context-menu:backdrop,
window.popup, window.popup.background, window.popup.background:backdrop,
popover, popover.background, popover.background:backdrop,
tooltip, tooltip.background, .csd.popup decoration { background-color: @popover_bg_color; }
tooltip label, tooltip * { color: @popover_fg_color; }

/* text: solid colours instead of opacity */
.dim-label, label.dim-label, headerbar .subtitle, .titlebar .subtitle, .titlebar:not(headerbar) .subtitle {
  opacity: 1; color: mix(@window_fg_color, @window_bg_color, 0.15); }
label:disabled, label:disabled:backdrop { opacity: 1; color: mix(@window_fg_color, @window_bg_color, 0.20); }

/* add-on (tested, mode A): notebooks, StackSidebar, treeview column headers.
   Stock Adwaita paints notebook pages #2d2d2d and tabs #282828, fully opaque. */
notebook, notebook:backdrop, notebook > stack, notebook > stack:not(:only-child), notebook > stack:not(:only-child):backdrop { background-color: transparent; }
notebook > header, notebook > header:backdrop { background-color: alpha(@sidebar_bg_color, 0.125); }
/* .sidebar sits on the stacksidebar node, which paints nothing; the inner list does */
stacksidebar list, stacksidebar list:backdrop { background-color: alpha(@sidebar_bg_color, 0.125); }
treeview.view header button, treeview.view header button:backdrop { background-color: alpha(@sidebar_bg_color, 0.125); background-image: none; }

/* proposed, UNTESTED: solid column-header text (it gets too faint once the header is glass) */
treeview.view header button, treeview.view header button:backdrop { color: @window_fg_color; }
/* proposed, UNTESTED: GtkDialog bodies (About, Pair, message dialogs) */
dialog.background, dialog.background:backdrop { background-color: alpha(@window_bg_color, 0.60); }
```

`~/.config/gtk-3.0/settings.ini` (the dark variant; it is honoured on Wayland even with the settings portal running):

```ini
[Settings]
gtk-icon-theme-name=Fluent-dark
gtk-application-prefer-dark-theme=1
```

### Delivery: two modes (both tested; B recommended)

GTK3 has no per-app user CSS, so choose one of the two.

**Mode A: global user CSS.** `~/.config/gtk-3.0/gtk.css`:

```css
@import url("dank-colors.css");
@import url("appglass-gtk3.css");
```

User-priority CSS beats every theme rule regardless of specificity, so this is the most robust mode. But it hits **every** GTK3 client. Any GTK3 app that has no niri `opacity 1.0` rule gets a double fade (0.60 × 0.60 = 0.36 background, and text faded to 0.60). It also reaches GTK3 dialogs opened by Electron apps, and may leak into the GTK colours that Firefox/LibreWolf read for their native look (untested).

**Mode B: per-app theme with `GTK_THEME` (recommended).** Only the opted-in apps change, so it pairs 1:1 with the niri rule. `~/.local/share/themes/AppGlass/gtk-3.0/gtk.css` (CSS `url()` needs absolute paths: replace `USER`):

```css
@import url("resource:///org/gtk/libgtk/theme/Adwaita/gtk-contained-dark.css");
@import url("file:///home/USER/.config/gtk-3.0/dank-colors.css");
@import url("file:///home/USER/.config/gtk-3.0/appglass-gtk3.css");
```

Here the theme provides the dark variant (`gtk-contained-dark.css`). The rules run at theme priority, so specificity matters. The first attempt left the textview opaque because Adwaita's `.view text` beat a plain `textview text`. The base rules above (with `.view text` and the `:backdrop`/`:disabled` variants) measured the same alphas in both modes. The add-on rules were only measured in mode A.

Launch the apps with the variable:

- **Solaar.** It is started by the systemd xdg-autostart generator from `/etc/xdg/autostart/solaar.desktop` and is single-instance. Copy that file to `~/.config/autostart/solaar.desktop` and set `Exec=env GTK_THEME=AppGlass solaar --window=hide`. A `~/.local/share/applications` override alone has no effect while the autostarted instance runs, because new launches hand off to it.
- **nvidia-settings.** Copy `/usr/share/applications/nvidia-settings.desktop` to `~/.local/share/applications/` and set `Exec=env GTK_THEME=AppGlass nvidia-settings`.

Optional: matugen has a `DATA_DIR` output macro, so a user template could write the theme file next to `CONFIG_DIR/gtk-3.0/appglass-gtk3.css` (untested). It is not required, because the files are static.

### niri rule

One rule per glass app, in a file included **after** `dms/windowrules.kdl`, which holds the global "Glass blur" rule (opacity 0.60, blur on), the same way `dms-browser-glass.kdl` is included. Blur stays on from the global rule. Example `~/.config/niri/appglass-gtk3.kdl`:

```kdl
// GTK3 apps paint their own glass: niri must not fade the whole window.
window-rule {
    match app-id=r#"^(solaar|nvidia-settings)$"#
    opacity 1.0
}
```

`~/.config/niri/config.kdl`, right after `include "dms/windowrules.kdl"`:

```kdl
include optional=true "appglass-gtk3.kdl"
```

Add `thunar` (and any other GTK3 app you opt in) to the regex. Do **not** add XWayland or root GTK3 apps (Timeshift).

### Reload

GTK3 reads the CSS when the app starts. After a DMS colour or wallpaper change, restart the app. Solaar is a long-running tray process, so it keeps stale colours until it is restarted (live reload untested). niri reloads its rules automatically.

## Measured results (tested in a nested niri session)

Alpha comes from the niri window screenshot (0–255 / 0–1). Contrast ratios are quoted only where they were measured on a premultiplied-correct composite. The others are marked "to re-measure".

### GTK3 test app (mode A; mode B gave the same alphas)

| Region | Base rules | With add-on |
|---|---|---|
| CSD headerbar | 0.651 | 0.651 |
| menubar / toolbar / statusbar | 0.651 | 0.651 |
| ListBox `.sidebar` | 0.651 | 0.651 |
| GtkStackSidebar | **0.600** (content level, miss) | 0.651 |
| content, treeview rows, textview outside a notebook | 0.600 | 0.600 |
| notebook page (with textview) | **1.000** (opaque stock `#2d2d2d`) | 0.600 |
| notebook tabs | **1.000** | 0.651 |
| treeview column header | 1.000 | not measured in this app (0.651 in nvidia-settings) |
| popover | 1.000 | — |
| GtkMenu (xdg_popup) | opaque: pixel (40,44,48) = `@popover_bg_color` over a #ff00ff background, no tint (glass pixels there are (120,20,124)) | — |
| tooltip | not opened | — |
| CSD shadow margin | 0 | 0 |

- Text: glyph cores reach alpha 1.0. 3× zoom crops show crisp text with no fade or fringing.
- Contrast for body, dim-label, insensitive and unfocused text: **to re-measure** (only uncorrected composites exist). On the white background the unfocused window was the weakest case, so re-check it first.
- A dark logo hard-coded by the app (`#111`) is near invisible on the dark glass. That is a **bug CSS cannot fix**, because the content is drawn by the app. An `image { -gtk-icon-shadow: 0 0 3px alpha(@window_fg_color, 0.5); }` halo is possible, but untested.

### Solaar 1.1.20 (SSD, no headerbar; modes A and B identical)

| Region | Alpha |
|---|---|
| Main window | YMIN 153, YAVG 155.0 (0.600). Pixel (18,20,22,153) = 0.60 premultiplied `#1e2226` |
| Device treeview, right pane | 0.600 |
| Buttons | 1.000 |
| Without the CSS (control) | 255 everywhere |
| Tray `Gtk.Menu` | `#282c30` (`@popover_bg_color`) at 255, no tint over a #ff00ff background |
| Rule Editor window | 0.600 |
| About dialog | headerbar 0.65 (alpha 166); body **opaque** stock `#353535` (255) |

Contrast (WCAG, premultiplied-correct composite over blurred wallpaper / white / black):

| Text | Ratio |
|---|---|
| Insensitive "Select a device" label | 3.28 / 2.26 / 9.69 (passes 2:1, thin margin on white) |
| Button labels (on opaque fills) | 10.7 focused, 3.89 unfocused |
| Rule Editor tree text | 12.1 / 4.31 / 18.5 |
| Disabled tray-menu item | 7.38 |

- The glyph pixels of "Select a device" are (185,188,193,255): fully opaque. The Solaar logo in the About dialog and the symbolic icons in the Rule Editor are clearly visible.
- No black background, no artifacts, and the backdrop state is fine.
- Not seen: device rows, device/battery icons, the settings panel (switches, combo popups, sliders) and tooltips. Devices were hidden on purpose. The icons come from the colour icon theme (Fluent-dark), so a dark-logo problem is unlikely but unverified.

### nvidia-settings (native Wayland, mode A)

| Region | Base rules | With add-on |
|---|---|---|
| System Information page | YMIN 153, YAVG 160.7, YMAX 255 | — |
| Tree pane, page body | 153 (0.600) | 153 |
| Bottom status bar | 166 (0.651) | 166 |
| Graphics Information / Application Profiles notebook (tabs, toolbar, list) | **255**, stock `#2d2d2d`/`#282828` | list 153, tabs and column headers 166 |
| Section-header separator strips | 163 (0.64, cosmetic) | — |
| NVIDIA banner bitmaps, Help/Quit buttons, entries | 255 | 255 |
| Combo menu (GtkComboBoxText in the test app, same CSS) | `#282c30` at 255, no tint | — |

- Text glyph cores reach 255 and are crisp in 3× crops. The banners are opaque images, so they stay readable.
- Contrast (focused, unfocused, PowerMizer insensitive rows): **to re-measure**.
- **Bug with the add-on:** once the column header is glass, the header text ("Priority", "Pattern"…) fell below 2:1 on the white composite (measured on the uncorrected composite; to re-measure). The proposed `color: @window_fg_color` rule above addresses it, but it is untested. The disabled toolbar "minus" icon is just as faint, which is acceptable for a disabled icon.
- Not opened: nvidia-settings' own PowerMizer combo, the App Profiles editor dialogs (these are `GtkDialog` and so are affected by the dialog gap) and tooltips.

## What breaks / caveats

- **Notebooks opaque without the add-on.** This is common in preferences and settings windows (2 of 6 nvidia-settings pages). Ship the add-on.
- **Dialogs.** `GtkDialog` bodies stay opaque `#353535`, not even the DMS colour. Only their headerbar becomes glass. The proposed `dialog.background` rule is untested.
- **Column-header text** gets too faint once the header is glass. The proposed solid colour is untested.
- **Unfocused windows on light backgrounds.** Adwaita greys backdrop text to `#919190`. The base rules swap it for a solid mix, but on white the margin was the thinnest of all cases. Re-measure it.
- **App-drawn dark content** (hard-coded dark logos or markup) is invisible on dark glass, and CSS cannot reach it.
- **Light DMS scheme: untested.** The rules assume dark: `settings.ini` forces prefer-dark, and mode B imports `gtk-contained-dark.css`. For light, mode B would import `gtk-contained.css` and `prefer-dark` must follow the scheme. The `mix()` text colours and the contrast on light glass are unmeasured.
- **Mode A double fade.** Every GTK3 app without a niri `opacity 1.0` rule ends up at 0.36. Prefer mode B, or keep the niri regex complete.
- **DMS GTK apply step.** DMS's `gtk.sh apply` writes an `@import url("dank-colors.css")` into `gtk.css`. In mode A, check afterwards that `appglass-gtk3.css` is still imported *after* `dank-colors.css`.
- **Root / XWayland GTK3** (Timeshift, any X11-only GTK3 app): fallback only.
- **Flatpak GTK3 apps** (none installed here; documented, untested): flatpak forces `XDG_CONFIG_HOME` to `~/.var/app/<app-id>/config`. The CSS files would have to go into `~/.var/app/<app-id>/config/gtk-3.0/`. In mode B the sandbox also needs `GTK_THEME` (`flatpak override --user --env=GTK_THEME=AppGlass <app-id>`) and access to the theme dir and colour file.
- **Not covered by the tests:** tooltips (no pointer input), modal popovers (they need an input grab, so only non-modal popovers were opened), and real user clicks (menus were opened programmatically).

## Documented-only apps (unverified)

- **Timeshift 25.12.4** (installed, not run). `timeshift-launcher` runs `pkexec timeshift-gtk`. As root it reads `/root/.config/gtk-3.0`, and pkexec keeps only `DISPLAY`/`XAUTHORITY`, so it runs through xwayland-satellite. It would need root-owned config, and a non-CSD X11 GTK3 window has no RGBA visual anyway. Keep the global niri opacity, with no rule added.
- **Thunar.** Expected to work with the same CSS in mode A or B: the side pane is a `.sidebar` treeview, which gives 0.65, and the views are `.view`/iconview, which give 0.60. Add `thunar` to the niri regex, and in mode B override `thunar.desktop`. Unverified.
- **Inkscape 1.x** (GTK3; GTK4 port in progress). It loads its own UI theme plus `~/.config/inkscape/ui/style.css` on top of the GTK theme. Docks and panels could take the glass rules there, but the canvas is opaque. Partial: adopt it (with `app-id=r#"^org\.inkscape\.Inkscape$"#`, `opacity 1.0`) only if the panels-only look is wanted. Unverified.
- **GIMP.** 2.10 is GTK2, with no CSS alpha path. 3.x is GTK3, but its own theme CSS (`gimp.css`) overrides the colours, and the canvas is opaque by design. Keep the fallback, or keep it fully opaque as an image editor. Unverified.
- **LibreOffice** (VCL gtk3 plugin). VCL paints most surfaces itself with opaque colours derived from the theme, and the document canvas is opaque. A GTK3 CSS alpha does not reach the window background. Fallback. Unverified.
- **Thunderbird.** Gecko draws its own UI, and GTK only supplies native colours and dialogs. Not a GTK3 CSS target: Gecko/userChrome is not covered by these docs yet, so it keeps the global niri opacity.
