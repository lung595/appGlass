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
3. **niri `opacity 1.0` per glass app** (0.999 for the few whose window says it is opaque, below), matched on its app-id, in a file included after the global "Glass blur" rule (`dms/windowrules.kdl`). Later rules win, and blur stays on from the global rule:

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

   // glass apps whose window says it is opaque: niri blends them
   window-rule {
       match app-id=r#"^md\.obsidian\.Obsidian$"#
       opacity 0.999
   }
   ```

   The families whose window declares a whole opaque region while the app paints it with alpha (Feishin and VSCodium through the Electron hook, Obsidian, the WebKit shim apps such as Kiri, Lian Li) get a second block at `opacity 0.999`, after the glass block. At 1.0 niri believes the opaque region and skips what is behind the window (black, or a background that flickers); below 1.0 it blends it ([routes.md](routes.md)). Only the installed apps of those families are listed.

   GNOME Web is in the rule: the global `gtk-4.0/gtk.css` already makes its chrome glass, so without the rule the chrome would get both alphas. The page stays opaque; see [webkit.md](webkit.md).

   The rule and the app setting go together. App glass without the rule multiplies with the global 0.60 (content 153 becomes 92, text at most 153). The rule without app glass makes the window fully opaque.
4. **Fallback.** An app that cannot paint its own alpha is opaque by default: `appglass.kdl` starts with a catch-all `opacity 1.0` rule (browserGlass browsers excluded), so its text stays sharp. `fallback.mode` in settings.json switches this to `value` (the detected fallback apps get `opacity fallback.value`, 0.70 by default) or `off` (no rule, the global niri `opacity 0.60` applies, as before). Games (`steam_app_*`, gamescope) are always opaque with the blur off.

The category docs use separate example file names for the rules (`appglass-gtk4.kdl`, `app-glass.kdl`, ...). One file is enough.

## Apps

The full matrix per family, with the measured verify numbers, is in [apps.md](apps.md) (generated from `apps.json`).

Tested: run in a nested niri session, with the window alpha measured from window screenshots. Documented: from docs and sources only, not run. Window screenshots are premultiplied RGBA: the alpha values are reliable, but contrast ratios from the early composites (which treated them as straight alpha) are too pessimistic, light themes most of all. The docs quote a contrast ratio only where a premultiplied-correct composite was used, and say "to re-measure" otherwise.

Which route each app takes today, and why an app stays opaque, is in [routes.md](routes.md) (the opaque ones: [routes.md#opaque](routes.md#opaque)). The research notes per toolkit (below, under Docs) keep the first per-app tests as a record.

## CLI

```sh
appglass detect [--json]            # every launcher with its toolkit and the evidence (read-only)
appglass learn [--json|--dry-run]   # toolkit of each open window from niri + /proc, cached
appglass status [--json]            # levels, families, the adapter route of every app, hand-made files
appglass apply [--only a,b] [--dry-run]
appglass apply --all [--adopt] [--dry-run]   # every detected app with a working adapter
appglass adopt [PATH...] [--dry-run]         # hand a known hand-made file to appglass (backed up)
appglass adopt --rescue [--dry-run]          # state.json lost: rebuild it from the marked files
appglass remove [--only a,b] [--forget-away]
appglass get [key] | set key value [--apply]
appglass sync --settings-file F [--dry-run] [--no-switch]  # the DMS plugin's one call
appglass hook install [--dry-run] | remove
appglass plugin install | remove [--dry-run]  # link dms-plugin into the DMS plugins folder
appglass doctor [--fix]                      # drift between the repo render and the disk
appglass restore [ID] [--list]               # put back a backup ring entry
appglass levels                              # the current levels as JSON (what the wrappers read)
appglass verify <key> | --queue              # the hidden check: one app, or every queued app
appglass fail <key> [reason]                 # record a failed glass launch
appglass vibrancy                            # the Alacritty fade daemon (run by its unit)
appglass launch-check <key> <pid>            # (wrappers) watch one launch for a window
appglass keys <key> dark|light               # (wrappers) the colour keys of an app
```

- **detect** reads the `.desktop` launchers (XDG_DATA_DIRS and flatpak exports), resolves the binary (flatpak `/app` paths remapped, wrapper scripts followed), and classifies it from ELF `NEEDED`, Electron fuses, static markers and directory markers. A user override in `~/.local/share/applications` shadows the system file; the record says so.
- **learn** reads `niri msg -j windows` (app-id and pid only, never titles) and `/proc/<pid>/maps`; a process that loads several toolkits gets the toplevel one (a gjs app with WebKitGTK is GTK4, Electron is not GTK3). detect merges the cache.
- **status** resolves every app to an adapter (`appglass/adapters`): its tier (native, forced, mod, fallback, opaque, delegated, excluded), its risk, and what apply does with it today. Forced and mod adapters are on, and go live only once their hidden check passes (`appglass verify`, see [engine.md](engine.md)); `appglass set apps.<key>.enabled false` keeps one off.
- **hook install** adds the matugen template (re-render on every DMS theme change) and the sync units in `~/.config/systemd/user`: `appglass-sync.path`/`.service` (the DMS window rules and colours) and `appglass-discord.path`/`.service` (`~/.config/discord`), plus `~/.local/bin/appglass-sync`, which runs `bin/appglass-sync`. The sync unit runs `apply --from-hook --list-changed` and nudges Herdr and GTK only when one of their files changed (no GTK flicker on a no-op run). The Discord unit runs it with `--discord`, which exits at once on Discord's own writes and acts only when the newest `app-*` host dir lacks Vencord (while the vencord family is applied). The engine adds watches on the application folders (user, system, flatpak exports) and the rpm database to `appglass-sync.path`, a daily `appglass-sync.timer` for apps that update themselves, and `appglass-verify.service` (`appglass verify --queue`, idle priority), started by a sync run that queued an app to check ([engine.md](engine.md#when-it-runs)). Then it enables the path units and the timer. `hook remove` restores all of it and disables the units that were not enabled before. No event takes files out: when an applied app is not detected for a moment, the hook run and the plugin's sync leave its files as they are (`left as is`); a typed `appglass apply`, `appglass apply --only <family>` or `appglass remove --only <family>` takes them out. A family switched off in settings (`apps.<family>.enabled false`, or the app key of a Forced or Mod app) is the exception: the plugin's sync takes its files out, as a typed command does.
- **Shim adapters** (VLC qt-style, Lian Li and any GTK3 WebKitGTK app webkit-shim, LocalSend and ArtCraft ck-shim, Jellyfin qtquick-shim, Feishin and VSCodium electron-hook, Discord electron-vencord) build their shim from `shims/<adapter>/` with the host compiler into `~/.local/lib/appglass/<app>/` (rebuilt only when the sources, compiler or Qt version change), write a launch wrapper in `~/.local/bin` that reads `appglass levels` at every start, and point the launcher at it. All but VLC wait for their hidden check: until it passes, the wrapper runs the app plain. ArtCraft also gets the Vulkan layer in `~/.local/lib/appglass/artcraft/vk/` (`libappglass-vk.so` + `appglass-vk.json` + the device probe `appglass-vkprobe`, nothing in the system or user Vulkan layer folders); its wrapper takes the GPU route when the layer is there and the probe finds a Vulkan device that is not the CPU, else the CPU route (`APPGLASS_ARTCRAFT=cpu` forces it, `=off` starts it plain). `status`, `doctor` and the plugin's app row say which route it takes; a layer that does not build leaves the CPU route installed and status says why. Undo: `appglass remove --only artcraft` takes out the shim, the layer, the wrapper and the launcher override.
- **Hand-made files.** A launcher or rules file appglass did not write is left alone and reported; `adopt` backs it up and records it, the owner regenerates it from then on, and `remove` puts the original back byte-identical. Adopting the hand-made `~/.local/bin/appglass-sync` or its units runs `hook install` in the same run, so the hand script stops calling the hand pieces the families retire; while a hand sync script is still live, vencord keeps `appglass-vencord` and the theme template instead of retiring them. Launcher overrides made by appglass are regenerated from the system file on every apply, so they follow package updates.
- **Backup ring.** Every apply, sync, adopt, remove or restore that writes a file first saves the bytes it overwrites (or that the file was absent) and state.json, in `~/.local/state/appglass/ring/<time>/`. A config file that is a symlink (a dotfiles folder) keeps its link: the ring saves the link and the bytes behind it, and `restore` writes them back through the link. The ring keeps the 5 newest runs, and also the newest entry that holds a state.json: once state.json is lost, the runs after it (an `adopt --rescue`) cannot push out the last state `restore` can give back. `appglass restore --list` shows them, `appglass restore [ID]` puts one back (the newest by default), and the state before the restore becomes a new entry. A full `remove` that leaves nothing owned deletes the state folder, ring included. When `~/.local/state/appglass` is a link to a folder of yours, `remove` keeps the link and the folder and takes out only appglass's own names there (state.json, `.lock`, `verify.lock`, `colors.json`, `engine.json`, `engine.json.bad`, `backup/`, `ring/`, `plain/`; inside the three folders only what has appglass's shape: a ring entry with its time name, a backup `<hash>.orig`, a plain marker file); anything else in it stays, and `remove` names it. A link to nothing, or to HOME, an XDG base folder, a parent of one or `/`, is refused by every command that writes (and `doctor` reports it), and so is a first use of a folder that already holds one of those names: with no `.lock` and no state.json of appglass's in it, appglass has not used it, so the names are yours (point the link at an empty folder).
- **Lost state.json.** When state.json is missing but files with an appglass header or marker are on disk (the generated files, the niri rule, the hook units and scripts, a file appglass edited that still holds its lines; the files of an app uninstalled since apply count too: every family's paths are looked at, installed or not), or `backup/` still holds originals no record names, `apply`, `sync`, `remove`, `set`, `adopt` and `hook install`/`remove` write nothing and exit 1, naming what they found, and the ring and `backup/` stay (a full `remove` that finds such originals keeps them too, with a warning): `appglass restore` puts the last saved state back; without one, `appglass adopt --rescue` first saves every marked file (and `backup/`) in a new ring entry, then writes a new state.json: the files appglass wrote are recorded as its own, and each file it edited as edited, with the file minus appglass's lines as the original (also when you edited it around those lines, as long as each line appglass would take out names appglass or one of the files of the same app it also finds; a lone line that only looks like appglass's is left as it is, with a warning), and a JSON file appglass merged keys into that also holds yours, with no original in `backup/`, keeps your keys: only a key whose value names appglass (Herdr's `"layout": "appglass"`) is recorded, and `remove` takes it out; a key that may be yours too (Vencord's `transparent` and theme list, Dux's numbers) stays as it is, so `apply` and `remove` work again (by hand instead: delete the files appglass wrote and take its lines out of the files it edited, `appglass doctor` lists them). The rescue records only what it can prove, and lists the rest without touching it: a file appglass edits is recorded as its own (deleted by `remove`) only when nothing is left of it once appglass's lines are out, when it carries a line appglass puts only on a file it makes (the header of a GTK3 launcher copy), or when the ring shows appglass made it and nothing else wrote it since; otherwise it is recorded as edited, so after the whole state folder is lost a file appglass made from nothing keeps what is not appglass's in it (the DMS import in `gtk.css` or `alacritty.toml`, the `[config]` line of matugen's `config.toml`), named in the rescue's warnings for you to delete. An original in `backup/` that no new record uses (its file was left as it is, a path reached through a symlink) stays there, named in the warnings with the `cp` that puts it back (it replaces the current file with the copy from before appglass changed it, so changes made to the file since are lost), and the state folder stays with it, a full `remove` too, until that file holds it again. An original that does not match the record of the ring's last saved state.json, or of the ring entry of the run that made it, is never put back: the ring's copy of it takes its place; with none, a file appglass edited gets the file minus appglass's lines as its original, and any other file is left as it is. A copy in `backup/` that the ring cannot vouch for (damaged, or with no ring record to check it against) is recorded in state.json as untrusted and never named in a `cp` hint: the rescue, `doctor`, `adopt` and `apply` say it cannot be trusted and give the way out, `mv <copy> <copy>.damaged` to set it aside (then apply backs up the current file again); a copy set aside keeps the state folder, and `doctor` names it, until you delete it. A path reached through a symlink and a file that is also another path appglass writes or a file it reads are never recorded, ring or not. One that holds appglass's lines (and is not, at its real path, a file appglass writes or reads) is still named by the refusal, `doctor` and the rescue; when nothing else is left to record (every config folder linked to a dotfiles folder, the whole state folder lost), the rescue writes no state.json and exits 1, and you take appglass's lines out of those files by hand. A plain copy of a file appglass reads (DMS's `dank-colors.css` in a flatpak's `gtk-4.0`) is never recorded without the ring's word, and a file that only matches what an app's part renders is recorded only when that app is installed or another of its files is proven appglass's. `apply`, `doctor` and the rescue name the same files. With the whole state folder lost (the ring too), which folders appglass made is a best guess: a folder that holds nothing but appglass's files goes with them on `remove` (an empty folder of the app's own that appglass wrote into, Obsidian's `.obsidian/snippets`, goes too), `~/.local/bin` always stays, and a JSON file appglass merged keys into keeps the 2-space layout appglass wrote (its own layout was in the lost `backup/`). Restoring an older entry undoes every newer one too (files, links and the folders they made), so a `remove` after it leaves the tree as it was. An unreadable state.json is never overwritten: `restore`, `doctor` and `get` still run (doctor reports it), and the restore keeps the unreadable file in the ring. Restoring the entry from before the first apply moves the later originals in `backup/` into the ring too and leaves an empty state.json, so the next apply starts clean and `remove` and glass off still run. A restore takes an original out of `backup/` only once its file holds those bytes again: one the entry did not put back (an entry from before the ring saved the bytes behind a link) stays there, named with the `cp` that puts it back, and the state folder with it. Ring entries are named in UTC and carry a sequence number, which sets their order: it survives a clock or timezone change, even a clock set back.
- **doctor** compares what is installed with what the repository renders today, one line per drift: the hook units and scripts (`hook.py` `UNITS`), the niri rule and include, each owned file against the sha256 in state.json, a file a stopped run cut half way (state.json records each write before it; a file that then holds neither its old bytes nor its new ones is cut, not your edit: `appglass remove` gives its original back whole and saves what the cut left as `<file>.appglass-changed` (a file appGlass created is then deleted; an edit you made after the stop is in the saved copy), and `apply` writes it again from its original), a record whose original in `backup/` is gone (a remove that stopped half way: `appglass remove` finishes it), the plugin link, a hand-made unit that differs from the repository's (only reported: `appglass adopt` takes it over), and what a rescue or restore left for you (only reported): an original kept in `backup/` until its file holds it again (with the `cp` that puts it back), a copy it could not trust (no `cp`: the `mv` that sets it aside) and a copy set aside, until you delete it, and a file reached through a symlink that still holds appglass's lines as the rescue found it. A niri config that no longer includes `appglass.kdl` is reported and left to you (`appglass remove`, then `apply`, puts the include back). `--fix` re-renders what appglass owns, first saving a hand-changed version beside it as `<file>.appglass-changed` (then `.appglass-changed.1`, `.2` and so on: a saved version is never overwritten; the ring keeps what it overwrites too). A matugen hook section you took out of the matugen config is reported, not put back (`appglass hook install` does), and relinks a dangling plugin link. Exit 0 with no drift, 1 when drift is left.
- **settings.json.** `~/.config/appglass/settings.json`, when `set`, `sync` or `adopt` creates it, is recorded in state.json (owner `settings`): a full `remove` that leaves nothing else deletes it and its folder. One that was there before stays the user's.

## Unfocused windows

With `inactive.enabled` (on by default) an unfocused window's background goes a little more transparent, with a short fade; text, icons and logos stay opaque. niri switches an opacity rule at once, so each app fades its own background. Recorded in a session: the fade of GTK3, VLC, Feishin and Jellyfin; for Kiri (the generic WebKit route), the focused and unfocused levels (204 and 184 at 0.80, `tests/e2e/webkit.sh`), not the steps of the fade (LocalSend: no fade); the other routes below are unit-tested only, [routes.md](routes.md) says so per app, with the reason.

- **GTK4, GTK3**: `window.background:backdrop` at the lower alpha, with a CSS transition (GTK3 also fades the CSD headerbar from the bar level). While the fade is on, unfocused text keeps its focused look: GTK4 bar contents get `filter: none` on `:backdrop` (instead of the `opacity(0.8)` cue), GTK3 text, notebook tabs, spin buttons and headerbar button edges keep their focused colours (instead of Adwaita's grey, which switches at once). With the fade off, the old cues come back. The GTK4 rule uses libadwaita's `--window-bg-color`, so plain GTK4 apps (Default theme, no libadwaita) keep their own opaque background when unfocused instead of turning to glass.
- **Obsidian**: `body:not(.is-focused)` lowers the snippet colours, with a transition.
- **Alacritty**: `appglass vibrancy`, run by `appglass-vibrancy.service` (installed by `hook install`), follows the niri focus and eases `window.opacity` over Alacritty's IPC socket. Without the hook nothing fades Alacritty, so `instantFallback` dims it like the apps below.
- **Discord (Vencord), Feishin, Jellyfin, Lian Li, the WebKitGTK apps**: a class on the page root (`html:not(.app-focused)`, set by Discord itself; `html.agl-inactive`, set by agl-hook.js, jfglass or appglass-wk.so) lowers the content background, with a CSS transition.
- **Qt style apps** (VLC, Kate, the Kate and Konsole flatpaks, and the Qt apps the engine finds): the style animates the window fill on deactivation.
- **Others**: nothing, unless `inactive.instantFallback` adds a niri `is-active=false` rule (instant, and the text dims too). Deferred: the ck-shim apps (LocalSend, ArtCraft), VSCodium, the terminal area of the other terminals (Konsole's tabs and menus fade through the Qt style, and `instantFallback` leaves Konsole out while its runtime's Qt minor is the host's, so its terminal area gets no dim either), mpv, GIMP and Zed. Plain GTK4 apps without libadwaita stay opaque, focused or not.

The unfocused level is content x `factor` (0.90 by default), never below 0.60: at the default content level 0.60 nothing changes until the content level is raised.

Each app reads its own focus (GTK `:backdrop`, Electron blur, Qt window activation, page focus), not niri's, and the levels are written at apply time: most open apps pick up a change of these settings only when they restart.

## DMS plugin

`dms-plugin/` is the DMS plugin "App Glass". Install it as a link (the plugin runs the `bin/appglass` of the repository it points into):

```sh
appglass plugin install        # ~/.config/dms/plugins/appGlass -> <repo>/dms-plugin
appglass hook install          # the sync units and the vibrancy daemon, if not done yet
```

Then enable App Glass in DMS Settings > Plugins, and add the App Glass pill to a bar if you want it. On its first start the plugin copies the current `appglass get` settings into its own data, and from then on owns them (`appglass set` is refused while it is enabled). Each change on its settings page is written to `$XDG_RUNTIME_DIR/appglass-plugin-settings.json` and passed to `appglass sync`, debounced, one run at a time. The sync at the plugin's start passes `--no-switch`: its stored data may differ from `settings.json` (after `appglass restore`, or a hand edit), so what differs is saved and applied but takes nothing out; only a switch on the page (or a switch whose sync did not finish) removes files.

The plugin has three parts (`plugin.json`, type `composite`):

- **The daemon** (`AppGlassDaemon.qml`) runs every `appglass` call: the debounced `sync`, `status --json` (shared with the page and the pill), and the Advanced actions. Disabling, re-enabling or reloading the plugin in DMS changes no file and no unit.
- **Reload-safe**: the three files DMS loads (`AppGlassDaemon.qml`, `AppGlassWidget.qml`, `AppGlassSettings.qml`) are thin shells that build their body (`components/DaemonBody.qml`, `components/PillText.qml`, `components/SettingsBody.qml`) from a new URL on each `dms ipc call plugins reload appGlass`, so an update of `components/logic.js` or the settings parts is live after a plain plugin reload (the QML engine caches a file by its URL). The new URL follows DMS's reload counter, read from PluginService (no entry there is the first load), as the shell's own URL can come back from the QML disk cache with an older revision. What proves it: a quickshell started on its own (a nested niri, temporary XDG dirs, `DMS_SOCKET` unset; quickshell's IPC is per instance) loaded the current shells through DMS 2.1.2's real PluginService and reloaded them three times, each reload after an edit of the body, `logic.js` and the settings body: the daemon, the pill and the settings page showed the new marker every time (A, then B, C, D), and the uninstall state carried over. The stubbed `tests/qml/reload.test.qml` checks the same in the suite. Which command an update needs:
  - **code only** (`components/`, or the body of one of the three root `.qml` files): `dms ipc call plugins reload appGlass` is enough.
  - **`plugin.json` or the set of root files** (its capabilities, or a new root file such as `AppGlassWidget.qml` when an older install had none): run `dms restart`. DMS reads the manifest only when it scans the plugin, and disabling and enabling the plugin again does not read it. `dms ipc call plugin-scan rescan appGlass` is not a way out here: on such an update it fails with "File name case mismatch" and leaves the plugin disabled, and only `dms restart` brings it back.
- **The bar pill** (`AppGlassWidget.qml`): the glass icon (crossed out while paused) and how many apps are on glass. A click opens the settings, a right click pauses or resumes the glass.
- **The settings page** (`AppGlassSettings.qml`, with its parts in `components/settings/`): a search field on top (Ctrl+F or `/`; Enter opens the best match, Esc clears, a second Esc leaves the field), the glass state with a global Pause, and a category rail (Glass, Apps, Fade, Fallback, Advanced, About; icons only on a narrow page, the name on hover or focus; the arrow keys move from the focused category to the next one).
  - **Glass**: the glass switch (off runs `remove` for every glass file but the hook), the glass level as information (it follows the DMS window rule opacity), Re-apply.
  - **Apps**: the app list from `appglass status --json`, with each app's tier, a switch, and a route choice when more than one adapter can take the app. Mod and Forced routes ask before they turn on.
  - **Fade**: the unfocused-window controls (on/off, how much more transparent, animation length and curve, instant fallback).
  - **Fallback**: the opacity for apps appglass cannot glass.
  - **Advanced**: Learn open windows, Adopt hand-made files, Copy report, and Uninstall. Adopt and Uninstall ask first (the question is dropped when the page changes); one action runs at a time. Uninstall stops pending syncs, waits for a running one, runs `appglass remove`, then `appglass plugin remove`; the plugin then stays inert (its data keeps `uninstallState`) until **Set up again** on the same page syncs the settings the plugin kept (`appglass get` fills only a setting it never stored), then runs `appglass hook install` (the hook and units `remove` took out). Once its link is gone, DMS loads it again only from a new link (`appglass plugin install`), and that load sets up again the same way; an uninstall whose link stayed keeps it inert across reloads and shell restarts too. While uninstalled the header says so, and Pause, Re-apply, Learn, Adopt and the switches are off; when the plugin link stays (`appglass plugin remove` failed), the bar pill reads "uninstalled" ("unfinished" after an uninstall a reload cut short) and its right click does nothing; the Fade and Fallback settings are locked too. A failed `appglass remove` keeps its error under Uninstall until the next try.
  - **About**: the version, what appglass never touches, and the same actions from a terminal.

Glass off then on adopts again, file by file, the hand files that glass off gave back: one whose bytes did not change meanwhile is adopted again, one that changed stays the user's and is a conflict (a sibling of the same owner is still adopted). While glass is off the unchanged ones show as `parked`, the changed ones as conflicts.

Runs that come from events (`sync` from the plugin, the matugen hook and the sync units) never revert, delete or forget a file: a target that is gone for a while (a vault on a drive not mounted) keeps its record, and only a command you run (`remove`, `apply`, glass or an app switched off) takes files out. Such a record is kept even by a command you run, as long as its folder is gone (`remove` gives the file back once the folder is back); for a folder gone for good (a deleted vault), `appglass remove --forget-away` forgets those records and writes nothing there. The original of a file appglass changed there stays in the state folder's `backup/` (and the state folder with its ring, a full remove too): the warning gives the `cp` that puts it back if the folder comes back, and deleting that copy lets the next `remove` take the state folder out. A file appglass made there is left as it is (the warning names it).

IPC: `dms ipc call appGlass sync | status | toggle | pause | resume | app <key> on|off`. `pause` and `resume` turn the glass off and on, like the pill; `sync`, `toggle`, `pause`, `resume` and `app` answer `uninstalling` or `uninstalled` once Uninstall has started, and change nothing. When `appglass remove` fails, the glass and the syncs go on at once (with any change made meanwhile); when only the plugin link could not be taken out, Uninstall stays off and the page says to run `appglass plugin remove` in a terminal.

`appglass plugin remove` takes the link out again (only a link to this repository's plugin, never the plugins folder: DMS watches it from its start only); the glass files stay until `appglass remove`. Tests: `sh dms-plugin/tests/qml/run.sh [filter]` (Qt 6 `qml`, run by the unittest suite too). The unittest suite: `python3 -m unittest discover -s tests` from the repository root (about 15 minutes; run it in a throwaway HOME, with a short `TMPDIR` path: the GTK tests' broadwayd puts its socket in a folder there, and a Unix socket path is at most 107 bytes).

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

- A launcher whose client is gone (its `Exec` is not on `PATH`, or names a path that no longer exists) counts as not installed: appglass leaves it alone ([engine.md](engine.md)).

## Docs

- [guide.md](guide.md): install, first run, pause, per-app switch, undo and uninstall
- [engine.md](engine.md): how appGlass picks a route, what it never touches, what you see when it cannot glass an app
- [routes.md](routes.md): what each route does to each app, with the measured result
- [plugin.md](plugin.md): the DMS settings page, search, bar pill and IPC calls

Research notes per toolkit, from before the shipped routes (what was tried and why; [routes.md](routes.md) is what appglass does today):

- [terminal.md](terminal.md): Alacritty, kitty, foot, Ghostty, WezTerm, Konsole, Ptyxis
- [gtk4.md](gtk4.md): GTK4 / libadwaita (Nautilus, GNOME Software, portal, Zenity, Flatseal)
- [gtk3.md](gtk3.md): GTK3 (Solaar, nvidia-settings, Timeshift, Thunar, Inkscape, GIMP, LibreOffice)
- [electron.md](electron.md): Electron / Chromium / CEF (Obsidian, Discord, Chrome, Feishin, Steam, Vesktop)
- [webkit.md](webkit.md): Tauri / WebKitGTK (the generic WebKit shim route, Kiri, Lian Li Linux, GNOME Web)
- [qtquick.md](qtquick.md): Quickshell / QtQuick (Dux Files, Dux Calendar, DMS windows)
- [qt.md](qt.md): Qt Widgets / Qt Quick (VLC, Jellyfin, Kvantum, KDE apps)
- [flutter.md](flutter.md): Flutter (LocalSend)
- [gpu.md](gpu.md): gpui / egui (Herdr, ArtCraft Launcher, Zed)
- POC: `bin/appglass` + `appglass/` (see the [DMS issue draft](issue-dms.md) and the tests in `tests/`)
- [issue-dms.md](issue-dms.md): draft issue for DankMaterialShell (not posted)
