# appGlass user guide

appGlass gives desktop apps a glass background on niri + DMS while text, icons and logos stay fully opaque.
You set the glass level the usual DMS way, with the opacity of your global DMS window rule (Settings → Applications → Window rules: the first rule with no match and blur on, whatever its name). appGlass follows that level.

What you get, at a DMS level of 0.60:

| Surface | Opacity | Alpha (0-255) |
|---|---|---|
| Window content (views, editors, terminals) | 0.60, the DMS level | 153 |
| Bars (header bars, sidebars, tab bars, toolbars, status bars) | `max(content, 0.65)` | 166 |
| Menus, popovers, dialogs, tooltips | 1.0 | 255 |
| Text, icons, logos | 1.0, never faded | 255 |

Without appGlass, the DMS rule fades the whole window. In Alacritty the text then measures alpha 153 instead of 255, the same as the background.

How it works for each kind of app: [routes.md](routes.md). How it decides: [engine.md](engine.md). The settings page: [plugin.md](plugin.md).

## Install

Requirements:

- niri and DMS;
- Python 3.11 or newer;
- for the hidden check of the Forced and Mod routes: `gamescope`, `niri`, `dbus-run-session` and `ffmpeg`, plus `bwrap` for a flatpak app and for the WebKitGTK apps (Lian Li, Kiri, ...) (without them those routes stay plain); `jq` and the Vencord installer CLI at `~/.local/share/appglass/VencordInstallerCli-linux` to put Vencord back after a Discord update (the full list: the README Requirements);
- `gcc` for the C shims, and `g++` with the Qt 6 headers for VLC (its style plugin is built from source and is on by default) and the Qt shims; Jellyfin needs host Qt 6.11 or newer (see [routes.md](routes.md)).

```sh
git clone <repo> ~/.local/share/appglass
cd ~/.local/share/appglass
bin/appglass plugin install         # links the DMS plugin into the DMS plugins folder
bin/appglass hook install           # matugen hook + user units: re-apply on every DMS theme or level change, route new apps
bin/appglass apply --all --dry-run  # preview: which files it would write, changes nothing
bin/appglass apply --all            # write the glass files for every app it supports
```

Then enable "App Glass" in DMS Settings > Plugins.

Installed again after an Uninstall from the plugin page: the same steps. On its first load from the new link the plugin sets the glass up again with the settings it kept (an app you switched off stays off). If the page still says "Uninstalled" (an uninstall whose plugin link stayed), press **Set up again** on its Advanced page.

The commands below write `appglass` for `~/.local/share/appglass/bin/appglass`. To type it that way, link it into your PATH: `ln -s ~/.local/share/appglass/bin/appglass ~/.local/bin/`.

TODO(engine): `appglass setup` will do the four steps above in one command, and the first enable of the plugin will run it.

## First run

- `apply` writes the glass files for the apps it finds, and one niri rule file, `~/.config/niri/appglass.kdl`, included right after `dms/windowrules.kdl`. That rule sets `opacity 1.0` for every app that paints its own glass, and blur stays on.
- Every other window also gets `opacity 1.0` by default: opaque and sharp, never faded. You can change this in Settings > Fallback.
- Apps on a native route are glass the next time they start. Alacritty, Herdr and Dux Files reload live. GTK apps and Dux Calendar need a restart. Quit Obsidian before the first `appglass apply`: Obsidian needs a restart on the first enable (or the snippet toggled off and on in Obsidian), and reloads live after that.
- Apps on a Forced or Mod route (a shim, a hook or a client mod) are on, but they wait for a hidden check first: Settings > Apps shows "Waiting for check", and the app runs plain until the check passes in a headless session, off your screen ([engine.md](engine.md#the-gate-glass-waiting-stale-opaque-off-excluded)). To keep one off, switch it off (see [Per-app switch](#per-app-switch)).
- Games and root GUIs are never touched, and password managers never get an injected route. Games get opaque windows with no blur behind them.

## Everyday

- **The level.** Change the opacity of the global DMS window rule. The sync unit sees the change and re-applies: content follows the rule, bars stay at `max(content, 0.65)`, popups stay opaque.
- **The theme.** A DMS wallpaper or scheme change re-renders the colours through the matugen hook. GTK apps pick the new colours up on their next start.
- **A new app.** No command is needed: the sync unit watches the application folders, the rpm database and the flatpak `.changed` files, and a daily timer catches apps that update themselves. A new or updated app is routed within seconds. Re-apply in Settings > Glass, or `appglass apply --all`, does it at once.
- **An app update.** A theme route stays. An injected route goes back to "Stale" and runs plain until its check passes again for the new version. An app that fails its check, or opens no window twice, runs plain until its next update, with one notification.
- **Unfocused windows** fade a little more (Settings > Fade: the amount, 10 % by default; the duration, 180 ms; the easing). Only the background fades; text stays opaque. Apps with no fade of their own (see [plugin.md](plugin.md#fade)) stay as they are, unless "Dim apps that cannot fade" is on.

## Pause

A pause takes the glass files out of every app and keeps the hook and the units, so resuming puts the same glass back. Windows go back to plain DMS behaviour while paused.

- the "Pause glass" / "Resume glass" button at the top of the settings page;
- a right click on the bar pill;
- from a key binding: `dms ipc call appGlass pause`, `dms ipc call appGlass resume` or `dms ipc call appGlass toggle`.

Turning the plugin off, reloading it or restarting DMS does not pause and removes nothing.

Without the plugin, there is no pause command yet: `appglass remove` takes everything out (the hook too), and `appglass hook install` + `appglass apply --all` put it back.

TODO(engine): `appglass pause` and `appglass resume` as CLI commands.

## Per-app switch

In Settings > Apps, each app has its own switch, and a route choice when it has more than one. Forced and Mod routes are on by default; switched off, one asks before it turns on again.

Off takes the app's files out only for a Forced or Mod app (Feishin, VSCodium, Lian Li, the other WebKitGTK apps such as Kiri, LocalSend, ArtCraft, Jellyfin, Discord). For a Native app (Alacritty, the GTK3 and GTK4 apps, VLC, Obsidian, Herdr, Dux) the row shows Paused, but its glass files and its niri rule stay, so the app still opens with glass. To take them out, switch its whole family off with its family name (in [routes.md](routes.md)): `gtk3` covers both Solaar and nvidia-settings.

- With the plugin: `dms ipc call appGlass app gtk3 off` (the settings page has no family switch yet). `dms ipc call appGlass app gtk3 on` brings it back.
- Without the plugin: `appglass set apps.gtk3.enabled false --apply`. `appglass set` works only without the plugin, or with the plugin disabled in DMS Settings > Plugins: while the plugin is installed and enabled it refuses ("settings are managed by the DMS plugin"). A change made with `appglass set` while the plugin is disabled is replaced by the plugin's own settings when it is enabled again.
- `appglass remove --only gtk3` takes the files out too, but it lasts only until the next sync (plugin load, Re-apply, any switch) or `appglass apply --all`, because the family is still on in settings.

`appglass status` and Copy report show such a Native app as fallback with the reason "off in settings", even though it keeps its glass until its family is off.

An app that no family lists, which the engine routed by its toolkit (a GTK3 or Qt app), shows "off" when you switch it off. Its launcher override and niri rule stay through the syncs, and go with the next typed `appglass apply --all`.

TODO(engine): a per-app off for Native apps that takes that app's files, launcher override and niri rule out at once, from the plugin.

From a key binding: `dms ipc call appGlass app <key> on` or `dms ipc call appGlass app <key> off`.

Without the plugin:

```sh
appglass status                                # every app: status, route, reason
appglass set apps.<key>.enabled false --apply  # off (files out for a family name or a Forced/Mod app)
appglass set apps.<key>.enabled true --apply   # on again (a Forced route you turn on is glass before its check)
appglass set apps.<key>.route <name>           # pick a route, when the app lists several
```

`<key>` is the family name (`alacritty`, `gtk3`, `feishin`, ...), or the key `appglass status` shows for a Forced or Mod app, when it has no dots (`discord`). An app id with dots in it (`org.gnome.Nautilus`, every flatpak id) does not work here: `appglass set` reads each dot as a level of the key and refuses ("unknown key in apps.org: gnome"). Switch such an app from the settings page or with IPC (`dms ipc call appGlass app org.jeffvli.feishin off`). While the plugin is installed and enabled it owns the settings, and `appglass set` refuses with a hint: use the settings page or IPC then.

TODO(engine): `appglass set` taking an app id with dots.

TODO(engine): `appglass app <key> auto|off` as a short form.

## Undo

Every file appglass writes or edits is recorded. Files it created are deleted, files it edited are restored byte for byte from a backup, and the JSON keys it merged are put back. If you edited a file after appglass:

- in a file appglass edited or merged into (your `alacritty.toml`, `gtk.css`, a GTK3 launcher override, a JSON settings file), only appglass's part is taken out and your edit stays;
- a file appglass created whole (`appglass.toml`, `dank-glass.css`, the AppGlass GTK3 theme, `appglass.kdl`, the VLC launcher, the shims and wrappers) is deleted, with any edit you made inside it;
- a file you handed over with Adopt is restored as it was before, and your edited version is saved next to it as `<file>.appglass-changed`.

`appglass remove --only <family>` lasts only until the next sync or `appglass apply --all` while the family is still on in settings. To keep a family out, switch it off (see [Per-app switch](#per-app-switch)).

```sh
appglass remove --only gtk3,feishin   # undo some families, until the next sync or apply --all
appglass remove                       # undo everything, the hook and units too (see below with the plugin)
appglass restore --list               # the backup ring: one entry per apply that changed files, last 5 kept
appglass restore                      # put the newest ring entry back (files and state)
```

With the DMS plugin enabled, a full `appglass remove` lasts only until the plugin's next sync (its next start, or a change on its page), which sets the glass up again: use [Uninstall](#uninstall) instead, or `appglass remove && appglass plugin remove`.

If you take something out by hand (the niri include line, a deleted `gtk.css`, the Obsidian snippet turned off, `GTK_THEME` removed from a launcher), appglass leaves it out on later theme changes.

## Uninstall

From the plugin: Settings > Advanced > Uninstall appGlass, then confirm. It restores every file, removes the hook and units, then the plugin link. If the link cannot be removed, the page says so: run `appglass plugin remove` to finish.

From a terminal:

```sh
appglass remove && appglass plugin remove
```

`appglass remove` restores every file and removes the matugen hook and the user units too, so `appglass hook remove` is not needed afterwards (it only prints "hook: not installed"). Then delete the clone if you like, and the PATH link if you made one: `rm ~/.local/bin/appglass`. Your other DMS plugins are not touched.

## Command line

```sh
appglass status [--json]                # colours, levels, applied families, every app's route and reason
appglass levels                         # the current levels as JSON
appglass detect [--json]                # which toolkit draws each installed app (read-only)
appglass learn [--json] [--dry-run]     # record the toolkit of each open window
appglass apply [--only f1,f2] [--dry-run]
appglass apply --all [--adopt] [--dry-run]
appglass adopt [paths] [--dry-run]      # hand known hand-made glass files to appglass, backed up first
appglass adopt --rescue [--dry-run]     # state.json lost, none to restore: record its files again
appglass remove [--only f1,f2] [--forget-away]
appglass restore [id] [--list]
appglass get [key]                      # settings.json, or one dotted key
appglass set <key> <value> [--apply]
appglass hook install [--dry-run]
appglass hook remove
appglass plugin install|remove [--dry-run]
appglass doctor [--fix]                 # check appglass's own files (units, niri rule, owned files, plugin link)
appglass verify <key> | --queue         # run the hidden check now (one app, or the queue)
appglass fail <key> [reason]            # record a failed launch by hand
```

The wrappers also run `appglass launch-check` and `appglass keys` on their own; you do not need them.

TODO(engine): `appglass report <key>` (a scrubbed record for bug reports).

## IPC

```sh
dms ipc call appGlass status            # the last status as JSON
dms ipc call appGlass sync              # re-apply from the current settings
dms ipc call appGlass toggle            # pause or resume
dms ipc call appGlass pause
dms ipc call appGlass resume
dms ipc call appGlass app <key> on|off
```

During and after an uninstall, the calls that change something (`sync`, `toggle`, `pause`, `resume`, `app`) answer "uninstalling" or "uninstalled" and change nothing.
