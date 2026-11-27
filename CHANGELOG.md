# Changelog

All notable changes to appGlass are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Uninstalling the plugin from DMS now takes every appglass file out.** A registry install is a clone of the
  repository, and DMS deletes it on uninstall, so the CLI that undoes the glass went with it. `appglass hook install`
  now keeps a copy of the CLI in `~/.local/share/appglass/cli` (`appglass sync` refreshes it after an update), and
  when the plugin's folder is gone at unload the plugin runs that copy with `appglass remove --if-gone <plugin.json>`.
  It waits 4 s (`APPGLASS_SWEEP_GRACE`) and does nothing if `plugin.json` is back (an update), else it restores every
  file, takes the hook and the units out, then the copy. Disabling or reloading the plugin still changes nothing.

### Fixed

- A DMS uninstall left the launchers, CSS, niri rules, matugen hook and user units in place, with the units
  pointing at a deleted clone.

## [0.1.1] - 2026-11-27

### Fixed

- `appglass restore` no longer refuses everything when Herdr's folder is set with an absolute `HERDR_APP_HOME` outside the home folder.
- With a moved `XDG_DATA_HOME`, the sync unit now watches the user applications and flatpak folders there, so new apps get their glass without a manual sync.
- A damaged entry in the learned toolkit cache no longer makes `apply`, `detect` and the sync hook crash: the entry is dropped.
- **Herdr lost its glass when a mod switched its layout.** The skillshare mod installs and selects its own
  `herdr-skillshare` layout, and appglass kept that as an opt-out. The glass layout is now made from the layout
  Herdr runs when it has main's shape, and remove puts that layout back. A layout of another shape (win98) is
  still kept as an opt-out.
- **A WebKitGTK page still went bare on hover** (Kiri, WebKitGTK 2.54, NVIDIA). The 0.1.0 fix (damage
  tracking off) was not enough: Kiri asks WebKit to draw without compositing, and that path repaints only the
  hovered rects. The shim now asks for compositing always instead of never.
- **A WebKitGTK window flashed opaque on hover.** A full re-mark of the page read its own colour with the glass
  off for a moment, and the content fade then ran from opaque back to the glass. The fade is off during the read.
- **Two appglass runs could hold the lock at once.** A run that took the state folder out released its lock
  first, so a waiting run could lock the deleted `.lock` while a third run locked the new one. The folder now goes
  out under the lock, and a run that waited takes the live lock again.
- **A theme change with a broken settings.json reset your levels.** The matugen hook ran on the defaults when
  settings.json was invalid or unreadable. It dropped your levels and could bring back an app you switched off. A
  hook run now leaves every file as it is and warns.
- **Every command crashed on a malformed DMS colours file.** A `dms-colors.json` whose `colors` entry was not an
  object made `levels`, `status` and `apply` fail with a traceback. Such a file is now ignored.
- **Copies of your files were readable by other users.** The backups, ring copies and `.appglass-changed` copies
  were written at 0644 even when the original was private. They are now written 0600.
- **appglass restore checks the paths it puts back.** A ring entry that names a file outside the home folder and
  the XDG folders is now refused whole, before any file changes.
- **`appglass status` is faster on a cold cache.** It scanned every desktop file twice. It now scans them once.
- The sync path unit now watches the DMS window rules and colours under `$XDG_CONFIG_HOME` and `$XDG_CACHE_HOME` when you move those, so level and colour changes are followed there too (run `appglass hook install` again).
- A DMS colour change now flips the GTK theme even when the matugen hook already wrote the new GTK3 CSS, so open GTK3 apps pick up the new colours.
- **Jellyfin, LocalSend, Feishin and VSCodium did not start from a beta branch or on a non-x86_64 machine.** The
  wrappers pinned `--branch=stable --arch=x86_64`, the plain fallback too. They now run the installed branch and arch.
- **A `$` in the appglass repo path under HOME broke every wrapper, appglass-sync and appglass-vibrancy.** Only
  the `$HOME` prefix expands now.
- **Feishin's output filled the runtime dir (RAM) for the whole session.** It now goes through a fifo that keeps
  only the inspector url, like VSCodium.
- WebKitGTK apps: an element restyled on every frame (a spinner, a progress bar) is re-marked once per batch instead of once per change, which cuts layout work while it animates.
- **Lian Li could flicker or go black behind its glass.** Its window opens as `lianli-gui`, but the niri rules
  matched only the desktop file's id, so niri treated the window as opaque. The rules now match both ids.
- **`appglass remove` could wipe a Zed or VSCodium settings.json.** If the appglass end comment was deleted by
  hand, remove dropped every line after the begin comment. appglass now leaves such a file untouched and keeps
  the user's version aside when it restores the original.
- The sync unit now reloads Herdr's theme when its config is in a moved `XDG_CONFIG_HOME` or an absolute `HERDR_APP_HOME`. Before, it only checked `~/.config/herdr-app`.
- **A paused app could come back as waiting after engine.json was reset.** The plain/ marker kept the old
  "waiting" reason when the app was later paused, and a reset rebuilt the app from that stale text. Markers
  are now rewritten when the reason changes.
- **A hand-edited engine.json with the wrong shape crashed every command.** It is now reset like a corrupt
  file, and its bytes are kept in engine.json.bad.
- **An injected family switched on with its app key switched off showed glass in status but ran plain.** The
  launch gate now follows the same rule as status: the family's own switch wins.
- **One truncated Electron binary stopped the whole app scan.** A file that ended right after the Electron fuse marker made the scan crash. Its fuses are now reported as unknown, and the scan goes on.
- Fix a crash with a traceback when another appglass run (uninstall, remove) took the state dir out just before a run or a background launch-check opened its lock.
- GIMP: if a `gimp.css` file has an appglass begin line but no end line (for example, the end line was removed by hand), apply and remove now leave the file untouched and report a conflict. Before, they silently dropped every user rule after the begin line.

## [0.1.0] - 2026-11-19

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
  such as zenity, with no network (its own network namespace). A check that cannot judge is
  "unverifiable" and changes nothing: a pass or fail stored for that version is kept. A Native
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
  built in but stays opaque unless you switch it on, then it stays glass);
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

- **A WebKitGTK page went bare on hover** (Kiri, WebKitGTK 2.54, NVIDIA): WebKit's damage tracking
  repainted only the hovered rects of a frame into a buffer that does not keep the last one, and on
  the clear view the rest of the page vanished down to the blur. The shim turns WebKit's two damage
  features (`PropagateDamagingInformation`, `UseDamagingInformationForCompositing`) off on a glass
  view, so every frame is drawn whole.
- **False fails of the hidden check** on a desktop at level 0.80: the check ran at 0.60
  (the DMS level sources were not copied) and judged at 0.80, so every app failed and went plain.
  Also fixed: Nautilus' empty folder stacked a second fill (a status page in the window
  background is now clear), Dux Calendar's panes are judged at their own level (237 at 0.80),
  Obsidian opened its vault chooser (the check now copies the vault list), LocalSend, Nautilus
  and Dux Calendar opened in light mode (the hidden session now has your colour scheme), and
  Discord's check measured the bootstrap's zenity updater (Discord cannot be checked: unverifiable).
- **Lian Li's check is unverifiable, never a fail:** with its daemon hidden (as the check must)
  its "Waiting for daemon" dialog covers the page, so a shot measures the dialog's scrim. No plain
  marker is written; Lian Li stays opaque unless you switch it on, then it stays glass. A marker
  an older check left on Lian Li or Discord goes at the next apply or hook run.
- **The hidden check leaves no private dir behind** when the app left read-only dirs in it
  (Dux unpacks its QML read-only into the runtime dir).

[Unreleased]: https://github.com/lung595/appGlass/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/lung595/appGlass/releases/tag/v0.1.1
[0.1.0]: https://github.com/lung595/appGlass/releases/tag/v0.1.0
