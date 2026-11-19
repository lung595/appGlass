# Changelog

All notable changes to appGlass are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

The first release.

### Added

- **Glass level from DMS.** appGlass reads the opacity of the first DMS window rule with no match
  and blur on (Settings → Applications → Window rules), then DMS `foregroundLayerTransparency`, then 0.60.
  Content follows it. Bars stay at `max(content, 0.65)`. Menus, popovers and dialogs stay opaque.
  Text, icons and logos are never faded.
- **One niri rule file.** `~/.config/niri/appglass.kdl` sets `opacity 1.0` for each glass app.
  It also has the fallback, unfocused and games blocks.
  The glass apps whose window marks itself opaque while it paints with alpha (Feishin, VSCodium,
  Obsidian, the WebKitGTK apps) get `opacity 0.999`, so niri keeps drawing what is behind them
  (at 1.0 their background could go black or flicker). The WebKit shim also clears that region itself.
- **Native routes** (the app's own colour files):
  - terminals: Alacritty, kitty, foot, Ghostty, WezTerm, Konsole;
  - GTK4 and libadwaita apps through user CSS, with the GtkSourceView background cleared;
  - GTK3 apps through an appGlass GTK3 theme in their launcher;
  - Qt 6 Widgets apps (VLC, and the flatpak Kate and Konsole) through the appGlass Qt style plugin;
  - app configs for Kate, mpv, GIMP 3 and Zed;
  - Obsidian (CSS snippet), Herdr (theme), Dux Files and Dux Calendar (keys).
- **Forced and Mod routes:**
  - Discord through a Vencord theme;
  - Feishin and VSCodium through an Electron main-process hook;
  - Lian Li Linux through a WebKitGTK shim;
  - any other host GTK3 WebKitGTK 4.x app whose window is the web view (Kiri), found by its toolkit,
    through the same shim with page CSS and a script that reads the page's own colours;
  - Jellyfin Desktop through a Qt Quick shim;
  - LocalSend through a colour-key shim;
  - ArtCraft Launcher through an explicit Vulkan layer that keys opaque frames on the GPU.
- **Hidden check.** Forced and Mod routes go live only after a headless check passes
  for the app's current version (`appglass verify`). An update sends them back to the check.
  The check runs at your level (it copies the DMS glass rule and `foregroundLayerTransparency`)
  and in your colour scheme, and measures the app's own main window, never a helper dialog
  such as zenity. A check that cannot judge is "unverifiable" and changes nothing. A Native
  route is never paused by a failed check: it is shown in `appglass status`, the glass stays.
  An app with a window open on the desktop is not checked until it is closed.
- **Detection.** `appglass detect` finds the toolkit of each installed app.
  `appglass learn` records the toolkit of each open window.
  GTK3, GTK4 and Qt 6 apps that no family lists are routed by their toolkit.
- **Automatic routing.** Every app is on by default after install.
  New and updated apps are routed within seconds, and routes heal after app updates.
- **Hook.** A matugen template and user units re-apply on every DMS theme or level change.
  A no-change run exits in about 20 ms.
- **Unfocused fade.** Unfocused windows fade a little more (10 % by default, 180 ms, ease out).
  Only the background fades. It is built into the GTK4, GTK3 and Qt Widgets routes, Alacritty,
  Obsidian, Discord (Vencord), Feishin, Jellyfin and the WebKitGTK apps (Kiri; Lian Li has it
  built in but stays opaque while its check fails);
  recorded in a session for GTK3, VLC, Feishin, Jellyfin and Kiri, unit-tested for the others.
  The other routes do not fade yet;
  **Dim apps that cannot fade** (off by default) gives them an instant niri rule that dims
  the whole window, text too.
- **DMS plugin "App Glass".** A settings page (Glass, Apps, Fade, Fallback, Advanced, About),
  a bar pill with the glass count, a global pause, and IPC calls.
  It survives DMS reloads.
- **Safety.** Every write is recorded in state.json with a backup.
  A ring keeps the last 5 applies. `appglass restore`, `appglass adopt --rescue` and
  `appglass doctor --fix` bring things back. No event removes files.
- **Commands.** `apply`, `remove`, `status`, `levels`, `detect`, `learn`, `get`, `set`, `hook`,
  `plugin`, `adopt`, `doctor`, `restore`, `verify` and `fail`.
- **Docs.** A user guide, the engine, the routes, the plugin pages, and an app table
  generated from `docs/apps.json`.

### Fixed

- **False fails of the hidden check** on a desktop at level 0.80: the check ran at 0.60
  (the DMS level sources were not copied) and judged at 0.80, so every app failed and went plain.
  Also fixed: Nautilus' empty folder stacked a second fill (a status page in the window
  background is now clear), Dux Calendar's panes are judged at their own level (237 at 0.80),
  Obsidian opened its vault chooser (the check now copies the vault list), LocalSend, Nautilus
  and Dux Calendar opened in light mode (the hidden session now has your colour scheme), and
  Discord's check measured the bootstrap's zenity updater (Discord cannot be checked: unverifiable).
- **Lian Li's check is unverifiable, never a fail:** with its daemon hidden (as the check must)
  its "Waiting for daemon" dialog covers the page, so a shot measures the dialog's scrim. No plain
  marker is written; Lian Li stays opaque unless you switch it on, then it stays glass.
- **The hidden check leaves no private dir behind** when the app left read-only dirs in it
  (Dux unpacks its QML read-only into the runtime dir).

[0.1.0]: https://github.com/lung595/appGlass/commits/master
