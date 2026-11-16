# appGlass

The same glass as browserGlass, for desktop apps on niri + DMS. App backgrounds are translucent over the niri blur, bars are a little more opaque than the content, menus and popups are opaque, and text, icons and logos stay fully opaque and readable.

Today the global niri "Glass blur" rule (`opacity 0.60`, blur on) fades every window as a whole, text included. appGlass moves the alpha into the app's own colour files, background roles only, and sets the niri opacity of each glass app back to 1.0.

## Levels

| Level | Alpha | Surfaces | Where the number comes from |
|---|---|---|---|
| Content | 0.60 (153) | window / view / editor / terminal background | The opacity already in use: the niri "Glass blur" rule (`opacity 0.60`) and DMS `foregroundLayerTransparency` (0.6 in `~/.config/dms/settings.json`) |
| Bars | 0.65 (166) | header bars, tab bars, sidebars, toolbars, status bars | browserGlass `NAV_BAR_OPACITY = 0.65` |
| Popups | 1.0 (255) | menus, popovers, tooltips, dialogs, command palettes | Opaque, as in browserGlass. DMS `popupTransparency` (0.7 here) applies to DMS's own popouts and floating windows, not to app menus |
| Text | 1.0 (255) | text, icons, logos | Never alpha'd |

Bugs by definition: text below 2:1 contrast on the glass, and a dark logo that disappears on dark glass.

Alphas stack. A bar drawn on top of the 0.60 content needs `a = (0.65 - 0.60) / (1 - 0.60) = 0.125` to land at 0.65. Painting it at 0.65 gives 0.86.

## Method

1. **Alpha in the colour files.** Background roles get an alpha by level; text roles never do. DMS already writes colour files with matugen (`dank-colors.css`, `dank-theme.toml`, ...). appGlass adds user matugen templates (or static files that reference the DMS colour names) next to them, so the glass follows the wallpaper. No daemon, no patching, no polling.
2. **Per-app switch**, where the toolkit needs one: Alacritty `window.opacity`, an Obsidian CSS snippet, Dux `ui-settings.json` keys, a Herdr layout, `GTK_THEME` for GTK3 apps.
3. **niri `opacity 1.0` per glass app**, matched on its app-id, in a file included after the global "Glass blur" rule (`dms/windowrules.kdl`). Later rules win, and blur stays on from the global rule:

   ```kdl
   // ~/.config/niri/config.kdl, after: include "dms/windowrules.kdl"
   include optional=true "appglass.kdl"
   ```

   ```kdl
   // ~/.config/niri/appglass.kdl: apps that paint their own glass
   window-rule {
       match app-id=r#"^Alacritty$"#
       match app-id=r#"^org\.gnome\.(Nautilus|Software|Zenity)$"#
       match app-id=r#"^org\.gnome\.Epiphany(\.WebApp_.*)?$"#
       match app-id=r#"^xdg-desktop-portal-gnome$"#
       match app-id=r#"^(solaar|nvidia-settings)$"#
       match app-id=r#"^md\.obsidian\.Obsidian$"#
       match app-id=r#"^(dev\.duxlabs\.files|dev\.duxlabs\.calendar)$"#
       match app-id=r#"^herdr-app$"#
       opacity 1.0
   }
   ```

   GNOME Web is in the rule: the global `gtk-4.0/gtk.css` already makes its chrome glass, so without the rule the chrome would get both alphas. The page stays opaque; see [webkit.md](webkit.md).

   The rule and the app setting go together. App glass without the rule multiplies with the global 0.60 (content 153 becomes 92, text at most 153). The rule without app glass makes the window fully opaque.
4. **Fallback.** An app that cannot paint its own alpha gets no rule and keeps the global niri `opacity 0.60`, as today.

The category docs use separate example file names for the rules (`appglass-gtk4.kdl`, `app-glass.kdl`, ...). One file is enough.

## Apps

Tested: run in a nested niri session, with the window alpha measured from window screenshots. Documented: from docs and sources only, not run. Window screenshots are premultiplied RGBA: the alpha values are reliable, but contrast ratios from the early composites (which treated them as straight alpha) are too pessimistic, light themes most of all. The docs quote a contrast ratio only where a premultiplied-correct composite was used, and say "to re-measure" otherwise.

| App | Category | Installed | Tested | Works | Method | Doc |
|---|---|---|---|---|---|---|
| Alacritty 0.17.0 | terminal | yes | yes | yes | `[window] opacity = 0.60`, `transparent_background_colors = false`, DMS `dank-theme.toml` via `general.import`; palette overrides | [terminal.md](terminal.md) |
| kitty | terminal | no | no | yes (expected) | `background_opacity 0.60` + `include dank-theme.conf` | [terminal.md](terminal.md) |
| foot | terminal | no | no | yes (expected) | `alpha=0.60` in `[colors-dark]` (`dank-colors.ini`) | [terminal.md](terminal.md) |
| Ghostty | terminal | no | no | yes (expected) | `background-opacity = 0.60` (+ `background-opacity-cells`), `theme = dankcolors` | [terminal.md](terminal.md) |
| WezTerm | terminal | no | no | yes (expected) | `window_background_opacity = 0.60` + `text_background_opacity` | [terminal.md](terminal.md) |
| Konsole | terminal / qt | no | no | partial (expected) | colour scheme `[General] Opacity=0.6`; terminal area only, tabs and menus opaque | [terminal.md](terminal.md), [qt.md](qt.md) |
| Ptyxis | terminal | no | no | partial (expected) | GSettings `org.gnome.Ptyxis.Profile` `opacity 0.6`; terminal area only | [terminal.md](terminal.md) |
| Nautilus (Files) 51.1 | gtk4 | yes | yes | yes | `gtk-4.0/gtk.css`: alpha on libadwaita bg roles, `dialog sheet` rule, `--dim-opacity: 0.80`, `:backdrop` filter fix | [gtk4.md](gtk4.md) |
| libadwaita role test app | gtk4 | yes | yes | yes | same `gtk.css` | [gtk4.md](gtk4.md) |
| GNOME Software 51.1 | gtk4 | yes | no | yes (expected) | same `gtk.css` | [gtk4.md](gtk4.md) |
| xdg-desktop-portal-gnome (file chooser) | gtk4 | yes | no | yes (expected) | inherits `gtk.css` | [gtk4.md](gtk4.md) |
| Zenity | gtk4 | yes | no | yes (expected) | inherits `gtk.css` | [gtk4.md](gtk4.md) |
| Flatseal (flatpak) | gtk4 | no | no | partial (expected) | `gtk.css` + `flatpak override --user --filesystem=xdg-config/gtk-4.0:ro` | [gtk4.md](gtk4.md) |
| GTK3 test app (Gtk 3.24.52) | gtk3 | yes | yes | partial | `appglass-gtk3.css` after `dank-colors.css` + notebook add-on; `GtkDialog` bodies not covered | [gtk3.md](gtk3.md) |
| Solaar 1.1.20 | gtk3 | yes | yes | yes | same CSS; mode B via `~/.config/autostart/solaar.desktop` with `GTK_THEME=AppGlass` | [gtk3.md](gtk3.md) |
| nvidia-settings | gtk3 | yes | yes | partial | same CSS + notebook add-on; column-header text too faint with the add-on | [gtk3.md](gtk3.md) |
| Timeshift 25.12.4 | gtk3 | yes | no | no | fallback (runs as root through XWayland, no RGBA visual) | [gtk3.md](gtk3.md) |
| Thunar | gtk3 | no | no | yes (expected) | same CSS (mode A or B) | [gtk3.md](gtk3.md) |
| Inkscape 1.x | gtk3 | no | no | partial (expected) | glass rules in `~/.config/inkscape/ui/style.css`; panels only, canvas opaque | [gtk3.md](gtk3.md) |
| GIMP 2.10 / 3.x | gtk3 | no | no | no | fallback (or keep opaque) | [gtk3.md](gtk3.md) |
| LibreOffice (VCL gtk3) | gtk3 | no | no | no | fallback | [gtk3.md](gtk3.md) |
| Thunderbird | gtk3 (Gecko) | no | no | no | fallback; Gecko/userChrome not covered yet | [gtk3.md](gtk3.md) |
| Obsidian 1.15.1 (flatpak) | electron | yes | yes | partial | vault CSS snippet `appglass.css` (clear every layer, paint once) + `--text-faint` fix; dark theme only | [electron.md](electron.md) |
| Any Electron app (decision rule) | electron | yes | yes | partial | only if the app's code sets `backgroundColor` `#00000000`; no flag or env var works | [electron.md](electron.md) |
| Google Chrome (flatpak) | electron | yes | yes | no | fallback (255 everywhere) | [electron.md](electron.md) |
| Discord (rpm) | electron | yes | no | no | fallback (`transparent:false` hard-coded, no user CSS) | [electron.md](electron.md) |
| Feishin (flatpak) | electron | yes | no | no | fallback (`custom.css` recolours only) | [electron.md](electron.md) |
| Steam (flatpak, CEF) | electron | yes | no | no | fallback | [electron.md](electron.md) |
| Vesktop / Vencord / Equibop | electron | no | no | partial (unverified) | "Transparent window" + alpha variant of DMS `dank-discord.css` | [electron.md](electron.md) |
| VS Code / VSCodium | electron | no | no | no | fallback | [electron.md](electron.md) |
| Element / Signal / Slack / Spotify | electron | no | no | no | fallback | [electron.md](electron.md) |
| Lian Li Linux (`lianli-gui`, Tauri 2) | webkit | yes | yes | no | fallback (transparency compiled in, `gtk.css` has no effect) | [webkit.md](webkit.md) |
| Tauri/wry app built with `transparent: true` (demo) | webkit | no | yes | partial | the app paints alpha: RGBA visual, WebView bg rgba 0, rgba CSS per level; needs a rebuild | [webkit.md](webkit.md) |
| GNOME Web / Epiphany 51 | webkit | yes | yes | partial | chrome only via libadwaita roles in `gtk-4.0/gtk.css` (gtk4 family, `opacity 1.0` rule); page always opaque | [webkit.md](webkit.md) |
| Geary / Evolution / Yelp / GOA web views | webkit | no | no | no | fallback unless the app clears the WebView background | [webkit.md](webkit.md) |
| Dux Files (`dfiles`) | qtquick | yes | yes | partial | merge keys into `~/.config/dfiles/ui-settings.json` (w 0.60, f 0.0); levels inverted | [qtquick.md](qtquick.md) |
| Dux Calendar (`dcal`) | qtquick | yes | yes | partial | merge keys into `~/.config/dankcal/ui-settings.json` (w 0.60, f 0.65), restart; levels inverted | [qtquick.md](qtquick.md) |
| DMS windows (Settings, modals) | qtquick | yes | no | yes (already done) | DMS paints them itself; `dms-window-opaque` rule already present | [qtquick.md](qtquick.md) |
| VLC 3.0.24 (Qt6) | qt | yes | yes | no | fallback (255 in every palette variant) | [qt.md](qt.md) |
| Jellyfin Desktop 2.0.0 (flatpak) | qt | yes | no | no | fallback (QML compiled in) | [qt.md](qt.md) |
| Qt6 Widgets + `WA_TranslucentBackground` (test program) | qt | yes | yes | partial | Fusion, palette alpha 153; one level only, alpha-0 holes | [qt.md](qt.md) |
| Qt Quick window colour (`qml` runner) | qt | yes | yes | yes | `ApplicationWindow.color` alpha 0.60, bars 0.125, opaque popups; only for QML you control | [qt.md](qt.md) |
| Kvantum (style engine) | qt | no | no | partial (expected) | `QT_STYLE_OVERRIDE=kvantum`, `translucent_windows=true`, `reduce_window_opacity=40`, `reduce_menu_opacity=0` | [qt.md](qt.md) |
| Dolphin / KDE apps (Breeze) | qt | no | no | no | fallback (kcolorscheme alpha gives opaque dark) | [qt.md](qt.md) |
| KeePassXC | qt | no | no | no | fallback | [qt.md](qt.md) |
| Krita | qt | no | no | no | fallback (or opaque for colour work) | [qt.md](qt.md) |
| OBS Studio | qt | no | no | no | fallback | [qt.md](qt.md) |
| qBittorrent (QSS-themed apps) | qt | no | no | no | fallback | [qt.md](qt.md) |
| LocalSend 1.18.2 (flatpak) | flutter | yes | yes | no | fallback; optional accent tint + in-app dark theme | [flutter.md](flutter.md) |
| Other Flutter apps (AppFlowy, Spotube, ...) | flutter | no | no | no | fallback unless the app ships its own transparency | [flutter.md](flutter.md) |
| Herdr 0.1.16 (gpui) | gpu | yes | yes | partial | theme `dankglass.json` (`#rrggbbaa`) + cloned layout `glass.json` + `shared.json` `layout: glass`; ANSI 0/8 still unreadable | [gpu.md](gpu.md) |
| ArtCraft Launcher 0.19.2 (egui/wgpu) | gpu | yes | yes | no | fallback (transparency is compile-time) | [gpu.md](gpu.md) |
| Zed (gpui) | gpu | no | no | yes (expected) | user copy of DMS `dank-zed.json` with per-level alpha | [gpu.md](gpu.md) |

"partial" means the glass works and text stays opaque, but some target levels are missed or a readability fix is still open. "(expected)" marks documented-only results.

### Fallback apps

These keep the global niri `opacity 0.60` and get no `opacity 1.0` rule (it would make them fully opaque):

- **Chrome, Discord, Feishin, Steam, VS Code, Element, Signal, Slack, Spotify**: an Electron/Chromium window is see-through only if the app's own code sets a transparent background colour.
- **Lian Li Linux** and other WebKitGTK/Tauri apps: transparency is compiled in (Tauri `transparent: true`, `webkit_web_view_set_background_color`). Lian Li has a light UI, so a higher per-app value (0.80-0.85) is suggested, untested.
- **VLC, Jellyfin, KDE apps, KeePassXC, Krita, OBS, qBittorrent**: Qt Widgets palette alpha lands on an opaque buffer; real glass needs a style plugin (Kvantum, not installed).
- **LocalSend** and other Flutter apps: the `FlView` is opaque unless the app's runner clears it.
- **ArtCraft Launcher**: egui transparency is a compile-time option.
- **Timeshift**: runs as root through XWayland, no RGBA visual.
- **GIMP, LibreOffice, Thunderbird**: they paint their own opaque surfaces.

## Findings

- **GTK CSS is global.** `~/.config/gtk-3.0/gtk.css` and `~/.config/gtk-4.0/gtk.css` reach every GTK app, so every GTK app you run needs the niri `opacity 1.0` rule, or it ends up at 0.36 background with text at 0.60. This includes the GNOME file-chooser portal used by Chrome and Electron apps. For GTK3, a per-app `GTK_THEME=AppGlass` theme (mode B) limits the CSS to the apps that have a rule.
- **Alphas stack.** Bars drawn over the 0.60 content must use 0.125 to reach 0.65 (GTK3, GTK4, Qt Quick, Tauri). In Obsidian, setting only the theme variables stacked to 224/239; every full-size layer has to be cleared and each region painted once.
- **The main config can override the colour file.** Alacritty's main `alacritty.toml` wins over imported files, and the current one hard-codes `opacity = 1.0`, so a generated file cannot set the opacity alone.
- **Apps that rewrite their own settings need a merge.** Dux Files/Calendar (`ui-settings.json`), Herdr (`shared.json`) and Discord (`settings.json`) write their own files: merge keys, never replace the file.
- **DMS palette entries that are fine on opaque windows are unreadable on glass.** dank16term color0/color5/color8 fall below 2:1 on dark glass, color1 and dim text below 2:1 over a white backdrop; Herdr ANSI 0/8 and Obsidian's stock `--text-faint` `#666` have the same problem. Faint and dim roles need solid, lighter values.
- **Built-in translucent text.** Adwaita dims text with `--dim-opacity` 0.55 and fades unfocused bar contents with `filter: opacity(0.5)`; Herdr derives muted text as translucent foreground. On glass these need solid colours or higher values.
- **Dark logos drawn by the app** (`#111`, `#24292f`) disappear on dark glass, and CSS cannot reach them. They need a light outline or plate in the app itself.
- **The app decides, not the theme.** Electron (`backgroundColor` `#00000000`), WebKitGTK (`webkit_web_view_set_background_color`), Flutter (`fl_view_set_background_color`) and egui transparency are code paths; no flag, env var or theme file turns them on. Qt Widgets palette alpha is not translucency.
- **NVIDIA WebKit workarounds break the glass.** `WEBKIT_DISABLE_DMABUF_RENDERER=1` or `WEBKIT_DISABLE_COMPOSITING_MODE=1` make a transparent WebView window nearly invisible (alpha ~0).
- **Light mode is a gap.** Every measurement used the dark DMS scheme. The static files hard-code dark values, the Obsidian snippet now follows the DMS mode in both Obsidian themes (`body.theme-dark, body.theme-light`; Obsidian's hard-coded `#9e9e9e` quote callout and `#FAFAFA` notice/tooltip text needed their own colours), GTK3 mode B imports the dark Adwaita variant, and light-mode contrast is still to re-measure with a correct composite.

## Not installed / not found

- A launcher whose client is gone counts as not installed.
- **"craftmail"**: not found on this machine.

## Docs

- [terminal.md](terminal.md): Alacritty, kitty, foot, Ghostty, WezTerm, Konsole, Ptyxis
- [gtk4.md](gtk4.md): GTK4 / libadwaita (Nautilus, GNOME Software, portal, Zenity, Flatseal)
- [gtk3.md](gtk3.md): GTK3 (Solaar, nvidia-settings, Timeshift, Thunar, Inkscape, GIMP, LibreOffice)
- [electron.md](electron.md): Electron / Chromium / CEF (Obsidian, Discord, Chrome, Feishin, Steam, Vesktop)
- [webkit.md](webkit.md): Tauri / WebKitGTK (Lian Li Linux, GNOME Web)
- [qtquick.md](qtquick.md): Quickshell / QtQuick (Dux Files, Dux Calendar, DMS windows)
- [qt.md](qt.md): Qt Widgets / Qt Quick (VLC, Jellyfin, Kvantum, KDE apps)
- [flutter.md](flutter.md): Flutter (LocalSend)
- [gpu.md](gpu.md): gpui / egui (Herdr, ArtCraft Launcher, Zed)
- POC: `bin/appglass` + `appglass/` (see the [DMS issue draft](issue-dms.md) and the tests in `tests/`)
- [issue-dms.md](issue-dms.md): draft issue for DankMaterialShell (problem, proposal, per-app results)
