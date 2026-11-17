# Changelog

All notable changes to appGlass are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

The first release.

### Added

- **Glass level from DMS.** appGlass reads the opacity of the DMS "Glass blur" window rule.
  Content follows it. Bars stay at `max(content, 0.65)`. Menus, popovers and dialogs stay opaque.
  Text, icons and logos are never faded.
- **One niri rule file.** `~/.config/niri/appglass.kdl` sets `opacity 1.0` for each glass app.
  It also has the fallback, unfocused and games blocks.
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
  - Jellyfin Desktop through a Qt Quick shim;
  - LocalSend through a colour-key shim;
  - ArtCraft Launcher through an explicit Vulkan layer that keys opaque frames on the GPU.
- **Hidden check.** Forced and Mod routes go live only after a headless check passes
  for the app's current version (`appglass verify`). An update sends them back to the check.
- **Detection.** `appglass detect` finds the toolkit of each installed app.
  `appglass learn` records the toolkit of each open window.
  GTK3, GTK4 and Qt 6 apps that no family lists are routed by their toolkit.
- **Automatic routing.** Every app is on by default after install.
  New and updated apps are routed within seconds, and routes heal after app updates.
- **Hook.** A matugen template and user units re-apply on every DMS theme or level change.
  A no-change run exits in about 20 ms.
- **Unfocused fade.** Unfocused windows fade a little more (10 % by default, 180 ms, ease out).
  Only the background fades. The fade works on every glass route.
- **DMS plugin "App Glass".** A settings page (Glass, Apps, Fade, Fallback, Advanced, About),
  a bar pill with the glass count, a global pause, and IPC calls.
  It survives DMS reloads.
- **Safety.** Every write is recorded in state.json with a backup.
  A ring keeps the last 5 applies. `appglass restore`, `appglass adopt --rescue` and
  `appglass doctor --fix` bring things back. No event removes files.
- **Commands.** `apply`, `remove`, `status`, `levels`, `get`, `set`, `sync`, `hook`, `plugin`,
  `adopt`, `doctor`, `restore` and `verify`.
- **Docs.** A user guide, the engine, the routes, the plugin pages, and an app table
  generated from `docs/apps.json`.

[0.1.0]: https://github.com/lung595/appGlass/commits/main
