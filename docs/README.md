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
4. **Fallback.** An app that cannot paint its own alpha is opaque by default: `appglass.kdl` starts with a catch-all `opacity 1.0` rule (browserGlass browsers excluded), so its text stays sharp. `fallback.mode` in settings.json switches this to `value` (the detected fallback apps get `opacity fallback.value`, 0.70 by default) or `off` (no rule, the global niri `opacity 0.60` applies, as before). Games (`steam_app_*`, gamescope) are always opaque with the blur off.

The category docs use separate example file names for the rules (`appglass-gtk4.kdl`, `app-glass.kdl`, ...). One file is enough.

## Apps

The full matrix per family, with the measured verify numbers, is in [apps.md](apps.md) (generated from `apps.json`).

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
| Obsidian 1.15.1 (flatpak) | electron | yes | yes | partial | vault CSS snippet `appglass.css` (clear every layer, paint once) + `--text-faint` fix; dark and light themes (same colours under `body.theme-dark` and `body.theme-light`) | [electron.md](electron.md) |
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
| Herdr 0.1.16 (gpui) | gpu | yes | yes | partial | theme `dankglass.json` (`#rrggbbaa`) + cloned layout `glass.json` + `shared.json` `layout: glass`; ANSI 0/5/8 taken from DMS roles (outline / tertiary / on_surface_variant) and lifted | [gpu.md](gpu.md) |
| ArtCraft Launcher 0.19.2 (egui/wgpu) | gpu | yes | yes | yes (forced) | `ck-shim` family `artcraft`: Mesa EGL + wgpu GL + colour keys, no opaque region, 60 fps cap | [gpu.md](gpu.md) |
| Zed (gpui) | gpu | no | no | yes (expected) | user copy of DMS `dank-zed.json` with per-level alpha | [gpu.md](gpu.md) |

"partial" means the glass works and text stays opaque, but some target levels are missed or a readability fix is still open. "(expected)" marks documented-only results.

### Fallback apps

These get the fallback rule (opaque by default, see Method step 4), not the glass rule:

- **Chrome, Discord, Feishin, Steam, VS Code, Element, Signal, Slack, Spotify**: an Electron/Chromium window is see-through only if the app's own code sets a transparent background colour.
- **Lian Li Linux** and other WebKitGTK/Tauri apps: transparency is compiled in (Tauri `transparent: true`, `webkit_web_view_set_background_color`). Lian Li has a light UI, so a higher per-app value (0.80-0.85) is suggested, untested.
- **VLC, Jellyfin, KDE apps, KeePassXC, Krita, OBS, qBittorrent**: Qt Widgets palette alpha lands on an opaque buffer; real glass needs a style plugin (Kvantum, not installed).
- **LocalSend** and other Flutter apps: the `FlView` is opaque unless the app's runner clears it.
- **Timeshift**: runs as root through XWayland, no RGBA visual.
- **GIMP, LibreOffice, Thunderbird**: they paint their own opaque surfaces.

## CLI

```sh
appglass detect [--json]            # every launcher with its toolkit and the evidence (read-only)
appglass learn [--json|--dry-run]   # toolkit of each open window from niri + /proc, cached
appglass status [--json]            # levels, families, the adapter route of every app, hand-made files
appglass apply [--only a,b] [--dry-run]
appglass apply --all [--adopt] [--dry-run]   # every detected app with a working adapter
appglass adopt [PATH...] [--dry-run]         # hand a known hand-made file to appglass (backed up)
appglass adopt --rescue [--dry-run]          # state.json lost: rebuild it from the marked files
appglass remove [--only a,b]
appglass get [key] | set key value [--apply]
appglass sync --settings-file F [--dry-run]  # the DMS plugin's one call
appglass hook install [--dry-run] | remove
appglass plugin install | remove [--dry-run]  # link dms-plugin into the DMS plugins folder
appglass doctor [--fix]                      # drift between the repo render and the disk
appglass restore [ID] [--list]               # put back a backup ring entry
```

- **detect** reads the `.desktop` launchers (XDG_DATA_DIRS and flatpak exports), resolves the binary (flatpak `/app` paths remapped, wrapper scripts followed), and classifies it from ELF `NEEDED`, Electron fuses, static markers and directory markers. A user override in `~/.local/share/applications` shadows the system file; the record says so.
- **learn** reads `niri msg -j windows` (app-id and pid only, never titles) and `/proc/<pid>/maps`; a process that loads several toolkits gets the toplevel one (a gjs app with WebKitGTK is GTK4, Electron is not GTK3). detect merges the cache.
- **status** resolves every app to an adapter (`appglass/adapters`): its tier (native, forced, mod, fallback, opaque, delegated, excluded), its risk, and what apply does with it today. Forced and mod adapters stay off until `appglass set apps.<key>.enabled true`.
- **hook install** adds the matugen template (re-render on every DMS theme change) and the sync units in `~/.config/systemd/user`: `appglass-sync.path`/`.service` (the DMS window rules and colours) and `appglass-discord.path`/`.service` (`~/.config/discord`), plus `~/.local/bin/appglass-sync`, which runs `bin/appglass-sync`. The sync unit runs `apply --from-hook --list-changed` and nudges Herdr and GTK only when one of their files changed (no GTK flicker on a no-op run). The Discord unit runs it with `--discord`, which exits at once on Discord's own writes and acts only when the newest `app-*` host dir lacks Vencord (while the vencord family is applied). Then it enables both path units. `hook remove` restores all of it and disables the units that were not enabled before. No event takes files out: when an applied app is not detected for a moment (or its family is switched off), the hook run and the plugin's sync leave its files as they are (`left as is`); a typed `appglass apply`, `appglass apply --only <family>` or `appglass remove --only <family>` takes them out.
- **Shim adapters** (VLC qt-style, Lian Li webkit-shim, LocalSend and ArtCraft ck-shim, Jellyfin qtquick-shim, Feishin electron-hook, Discord electron-vencord) build their shim from `shims/<adapter>/` with the host compiler into `~/.local/lib/appglass/<app>/` (rebuilt only when the sources, compiler or Qt version change), write a launch wrapper in `~/.local/bin` that reads `appglass levels` at every start, and point the launcher at it. All but VLC are off until enabled.
- **Hand-made files.** A launcher or rules file appglass did not write is left alone and reported; `adopt` backs it up and records it, the owner regenerates it from then on, and `remove` puts the original back byte-identical. Adopting the hand-made `~/.local/bin/appglass-sync` or its units runs `hook install` in the same run, so the hand script stops calling the hand pieces the families retire; while a hand sync script is still live, vencord keeps `appglass-vencord` and the theme template instead of retiring them. Launcher overrides made by appglass are regenerated from the system file on every apply, so they follow package updates.
- **Backup ring.** Every apply, sync, adopt, remove or restore that writes a file first saves the bytes it overwrites (or that the file was absent) and state.json, in `~/.local/state/appglass/ring/<time>/`. The ring keeps the 5 newest runs. `appglass restore --list` shows them, `appglass restore [ID]` puts one back (the newest by default), and the state before the restore becomes a new entry. A full `remove` that leaves nothing owned deletes the state folder, ring included.
- **Lost state.json.** When state.json is missing but files with an appglass header or marker are on disk (the generated files, the niri rule, the hook units and scripts, a file appglass edited that still holds its lines), or `backup/` still holds originals no record names, `apply`, `sync`, `remove`, `set`, `adopt` and `hook install`/`remove` write nothing and exit 1, naming what they found, and the ring and `backup/` stay (a full `remove` that finds such originals keeps them too, with a warning): `appglass restore` puts the last saved state back; without one, `appglass adopt --rescue` first saves every marked file (and `backup/`) in a new ring entry, then writes a new state.json: the files appglass wrote are recorded as its own, and each file it edited as edited, with the file minus appglass's lines as the original, so `apply` and `remove` work again (by hand instead: delete the files appglass wrote and take its lines out of the files it edited, `appglass doctor` lists them). Restoring an older entry undoes every newer one too (files, links and the folders they made), so a `remove` after it leaves the tree as it was. An unreadable state.json is never overwritten: `restore`, `doctor` and `get` still run (doctor reports it), and the restore keeps the unreadable file in the ring. Restoring the entry from before the first apply moves the later originals in `backup/` into the ring too and leaves an empty state.json, so the next apply starts clean and `remove` and glass off still run. Ring entries are named in UTC and carry a sequence number, which sets their order: it survives a clock or timezone change, even a clock set back.
- **doctor** compares what is installed with what the repository renders today, one line per drift: the hook units and scripts (`hook.py` `UNITS`), the niri rule and include, each owned file against the sha256 in state.json, the plugin link, and a hand-made unit that differs from the repository's (only reported: `appglass adopt` takes it over). A niri config that no longer includes `appglass.kdl` is reported and left to you (`appglass remove`, then `apply`, puts the include back). `--fix` re-renders what appglass owns, first saving a hand-changed version beside it as `<file>.appglass-changed` (then `.appglass-changed.1`, `.2` and so on: a saved version is never overwritten; the ring keeps what it overwrites too). A matugen hook section you took out of the matugen config is reported, not put back (`appglass hook install` does), and relinks a dangling plugin link. Exit 0 with no drift, 1 when drift is left.
- **settings.json.** `~/.config/appglass/settings.json`, when `set`, `sync` or `adopt` creates it, is recorded in state.json (owner `settings`): a full `remove` that leaves nothing else deletes it and its folder. One that was there before stays the user's.

## Unfocused windows

With `inactive.enabled` (on by default) an unfocused window's background goes a little more transparent, with a short fade; text, icons and logos stay opaque. niri switches an opacity rule at once, so each app fades its own background:

- **GTK4, GTK3**: `window.background:backdrop` at the lower alpha, with a CSS transition.
- **Obsidian**: `body:not(.is-focused)` lowers the snippet colours, with a transition.
- **Alacritty**: `appglass vibrancy`, run by `appglass-vibrancy.service` (installed by `hook install`), follows the niri focus and eases `window.opacity` over Alacritty's IPC socket.
- **Others**: nothing, unless `inactive.instantFallback` adds a niri `is-active=false` rule (instant, and the text dims too).

The unfocused level is content x `factor` (0.90 by default), never below 0.60: at the default content level 0.60 nothing changes until the content level is raised.

## DMS plugin

`dms-plugin/` is the DMS plugin "App Glass". Install it as a link (the plugin runs the `bin/appglass` of the repository it points into):

```sh
appglass plugin install        # ~/.config/dms/plugins/appGlass -> <repo>/dms-plugin
appglass hook install          # the sync units and the vibrancy daemon, if not done yet
```

Then enable App Glass in DMS Settings > Plugins, and add the App Glass pill to a bar if you want it. On its first start the plugin copies the current `appglass get` settings into its own data, and from then on owns them (`appglass set` is refused while it is enabled). Each change on its settings page is written to `$XDG_RUNTIME_DIR/appglass-plugin-settings.json` and passed to `appglass sync`, debounced, one run at a time.

The plugin has three parts (`plugin.json`, type `composite`):

- **The daemon** (`AppGlassDaemon.qml`) runs every `appglass` call: the debounced `sync`, `status --json` (shared with the page and the pill), and the Advanced actions. Disabling, re-enabling or reloading the plugin in DMS changes no file and no unit.
- **Reload-safe**: the three files DMS loads (`AppGlassDaemon.qml`, `AppGlassWidget.qml`, `AppGlassSettings.qml`) are thin shells that build their body (`components/DaemonBody.qml`, `components/PillText.qml`, `components/SettingsBody.qml`) from a new URL on each `dms ipc call plugins reload appGlass`, so an update of `components/logic.js` or the settings parts is live after a plain plugin reload (the QML engine caches a file by its URL). Which command an update needs:
  - **code only** (`components/`, or the body of one of the three root `.qml` files): `dms ipc call plugins reload appGlass` is enough.
  - **`plugin.json` or the set of root files** (its capabilities, or a new root file such as `AppGlassWidget.qml` when an older install had none): run `dms restart`. DMS reads the manifest only when it scans the plugin, and disabling and enabling the plugin again does not read it. `dms ipc call plugin-scan rescan appGlass` is not a way out here: on such an update it fails with "File name case mismatch" and leaves the plugin disabled, and only `dms restart` brings it back. The new URL follows DMS's reload counter, read from PluginService (no entry there is the first load), as the shell's own URL can come back from the QML disk cache with an older revision.
- **The bar pill** (`AppGlassWidget.qml`): the glass icon (crossed out while paused) and how many apps are on glass. A click opens the settings, a right click pauses or resumes the glass.
- **The settings page** (`AppGlassSettings.qml`, with its parts in `components/settings/`): a search field on top (Ctrl+F or `/`; Enter opens the best match, Esc clears, a second Esc leaves the field), the glass state with a global Pause, and a category rail (Glass, Apps, Fade, Fallback, Advanced, About; icons only on a narrow page, the name on hover or focus; the arrow keys move from the focused category to the next one).
  - **Glass**: the glass switch (off runs `remove` for every glass file but the hook), the glass level as information (it follows the DMS window rule opacity), Re-apply.
  - **Apps**: the app list from `appglass status --json`, with each app's tier, a switch, and a route choice when more than one adapter can take the app. Mod and Forced routes ask before they turn on.
  - **Fade**: the unfocused-window controls (on/off, how much more transparent, animation length and curve, instant fallback).
  - **Fallback**: the opacity for apps appglass cannot glass.
  - **Advanced**: Learn open windows, Adopt hand-made files, Copy report, and Uninstall. Adopt and Uninstall ask first (the question is dropped when the page changes); one action runs at a time. Uninstall stops pending syncs, waits for a running one, runs `appglass remove`, then `appglass plugin remove`; the plugin then stays inert, across reloads and shell restarts too (its data keeps `uninstallState`), until **Set up again** on the same page seeds it from `appglass get` and syncs. While uninstalled the header says so, and Pause, Re-apply, Learn, Adopt and the switches are off; when the plugin link stays (`appglass plugin remove` failed), the bar pill reads "uninstalled" and its right click does nothing. A failed `appglass remove` keeps its error under Uninstall until the next try.
  - **About**: the version, what appglass never touches, and the same actions from a terminal.

Glass off then on adopts again, file by file, the hand files that glass off gave back: one whose bytes did not change meanwhile is adopted again, one that changed stays the user's and is a conflict (a sibling of the same owner is still adopted). While glass is off the unchanged ones show as `parked`, the changed ones as conflicts.

Runs that come from events (`sync` from the plugin, the matugen hook and the sync units) never revert, delete or forget a file: a target that is gone for a while (a vault on a drive not mounted) keeps its record, and only a command you run (`remove`, `apply`, glass or an app switched off) takes files out.

IPC: `dms ipc call appGlass sync | status | toggle | pause | resume | app <key> on|off`. `pause` and `resume` turn the glass off and on, like the pill; `sync`, `toggle`, `pause`, `resume` and `app` answer `uninstalling` or `uninstalled` once Uninstall has started, and change nothing. When `appglass remove` fails, the glass and the syncs go on at once (with any change made meanwhile); when only the plugin link could not be taken out, Uninstall stays off and the page says to run `appglass plugin remove` in a terminal.

`appglass plugin remove` takes the link out again (only a link to this repository's plugin); the glass files stay until `appglass remove`. Tests: `sh dms-plugin/tests/qml/run.sh [filter]` (Qt 6 `qml`, run by the unittest suite too).

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
