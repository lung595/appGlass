# appGlass user guide

appGlass gives desktop apps a glass background on niri + DMS while text, icons and logos stay fully opaque.
You set the glass level the usual DMS way, with the opacity of the "Glass blur" window rule. appGlass follows that level.

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
- Python 3;
- for the apps that need a shim (see [routes.md](routes.md)): `gcc`, plus `g++` and the Qt 6 headers for the Qt shims.

```sh
git clone <repo> ~/.local/share/appglass
cd ~/.local/share/appglass
bin/appglass plugin install         # links the DMS plugin into the DMS plugins folder
bin/appglass hook install           # matugen hook + user units: re-apply on every DMS theme or level change
bin/appglass apply --all --dry-run  # preview: which files it would write, changes nothing
bin/appglass apply --all            # write the glass files for every app it supports
```

Then enable "App Glass" in DMS Settings > Plugins.

The commands below write `appglass` for `~/.local/share/appglass/bin/appglass`. To type it that way, link it into your PATH: `ln -s ~/.local/share/appglass/bin/appglass ~/.local/bin/`.

TODO(engine): `appglass setup` will do the four steps above in one command, and the first enable of the plugin will run it.

## First run

- `apply` writes the glass files for the apps it finds, and one niri rule file, `~/.config/niri/appglass.kdl`, included right after `dms/windowrules.kdl`. That rule sets `opacity 1.0` for every app that paints its own glass, and blur stays on.
- Every other window also gets `opacity 1.0` by default: opaque and sharp, never faded. You can change this in Settings > Fallback.
- Apps on a native route are glass the next time they start. Alacritty, Herdr, Dux Files and the Obsidian snippet reload live. GTK apps and Dux Calendar need a restart.
- Apps on a Forced or Mod route (a shim, a hook or a client mod) stay off until you turn them on. See [Per-app switch](#per-app-switch).
- Games are never touched. They get opaque windows with no blur behind them.

TODO(engine): apps found on install will be routed automatically, and a route that loads code into an app will go live only after a hidden headless check passes. Today the Forced and Mod routes are opt-in, one app at a time.

## Everyday

- **The level.** Change the opacity of the DMS "Glass blur" window rule. The sync unit sees the change and re-applies: content follows the rule, bars stay at `max(content, 0.65)`, popups stay opaque.
- **The theme.** A DMS wallpaper or scheme change re-renders the colours through the matugen hook. GTK apps pick the new colours up on their next start.
- **A new app.** Today, run `appglass apply --all`, or press Re-apply in Settings > Glass.

  TODO(engine): systemd path units on the application folders, the rpm database and the flatpak `.changed` files will pick new and updated apps up within seconds, with no command.
- **Unfocused windows** fade a little more (Settings > Fade). Only the background fades; text stays opaque.

  TODO(fade): the fade settings (amount, duration, easing, which apps can fade) are being reworked; this section will follow them.

## Pause

A pause takes the glass files out of every app and keeps the hook and the units, so resuming puts the same glass back. Windows go back to plain DMS behaviour while paused.

- the "Pause glass" / "Resume glass" button at the top of the settings page;
- a right click on the bar pill;
- from a key binding: `dms ipc call appGlass pause`, `dms ipc call appGlass resume` or `dms ipc call appGlass toggle`.

Turning the plugin off, reloading it or restarting DMS does not pause and removes nothing.

Without the plugin, there is no pause command yet: `appglass remove` takes everything out (the hook too), and `appglass hook install` + `appglass apply --all` put it back.

TODO(engine): `appglass pause` and `appglass resume` as CLI commands.

## Per-app switch

In Settings > Apps, each app has its own switch, and a route choice when it has more than one. A Forced or Mod route asks before it turns on.

From a key binding: `dms ipc call appGlass app <key> on` or `dms ipc call appGlass app <key> off`.

Without the plugin:

```sh
appglass status                                # every app: status, route, reason
appglass set apps.<key>.enabled false --apply  # off: that app's files are restored
appglass set apps.<key>.enabled true --apply   # on again (also how a Forced route is turned on)
appglass set apps.<key>.route <name>           # pick a route, when the app lists several
```

`<key>` is the family name (`alacritty`, `feishin`, ...) or the app id shown by `appglass status`. While the plugin is installed it owns the settings, and `appglass set` refuses with a hint: use the settings page or IPC then.

TODO(engine): `appglass app <key> auto|off` as a short form.

## Undo

Every file appglass writes or edits is recorded. Files it created are deleted, files it edited are restored byte for byte from a backup, and the JSON keys it merged are put back. If you edited one of those files after appglass, only appglass's part is taken out and your edit stays.

```sh
appglass remove --only gtk3,feishin   # undo some families
appglass remove                       # undo everything, the hook and units too
appglass restore --list               # the backup ring: one entry per apply that changed files, last 5 kept
appglass restore                      # put the newest ring entry back (files and state)
```

If you take something out by hand (the niri include line, a deleted `gtk.css`, the Obsidian snippet turned off, `GTK_THEME` removed from a launcher), appglass leaves it out on later theme changes.

## Uninstall

From the plugin: Settings > Advanced > Uninstall appGlass, then confirm. It restores every file, removes the hook and units, then the plugin link. If the link cannot be removed, the page says so: run `appglass plugin remove` to finish.

From a terminal:

```sh
appglass remove && appglass plugin remove
```

`appglass remove` restores every file and removes the matugen hook and the user units too, so `appglass hook remove` is not needed afterwards (it only prints "hook: not installed"). Then delete the clone if you like. Your other DMS plugins are not touched.

## Command line

```sh
appglass status [--json]                # colours, levels, applied families, every app's route and reason
appglass levels                         # the current levels as JSON
appglass detect [--json]                # which toolkit draws each installed app (read-only)
appglass learn [--json] [--dry-run]     # record the toolkit of each open window
appglass apply [--only f1,f2] [--dry-run]
appglass apply --all [--adopt] [--dry-run]
appglass adopt [paths] [--dry-run]      # hand known hand-made glass files to appglass, backed up first
appglass remove [--only f1,f2]
appglass restore [id] [--list]
appglass get [key]                      # settings.json, or one dotted key
appglass set <key> <value> [--apply]
appglass hook install|remove [--dry-run]
appglass plugin install|remove [--dry-run]
appglass doctor [--fix]                 # check appglass's own files (units, niri rule, owned files, plugin link)
```

TODO(engine): `appglass verify <key>` (run the hidden check now) and `appglass report <key>` (a scrubbed record for bug reports).

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
