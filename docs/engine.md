# How appGlass decides

This page explains what appGlass does on its own, what it never does, and what you see when it cannot glass an app. The per-route details are in [routes.md](routes.md).

## The levels

By default the levels follow DMS (`levels.content` and `levels.bar` in `~/.config/appglass/settings.json` override them):

1. **Content** is the opacity of the DMS "Glass blur" window rule in `~/.config/niri/dms/windowrules.kdl`. If there is no such rule, it is the DMS `foregroundLayerTransparency` setting, and if that is unset too, 0.60.
2. **Bars** are `max(content, 0.65)`.
3. **Popups**, menus and dialogs are 1.0.
4. **Text**, icons and logos are never given alpha.

`appglass levels` prints them. At a content level of 0.60:

```json
{"content": 0.6, "bar": 0.65, "popup": 1.0, "bar_over_content": 0.125, "content8": 153, "bar8": 166, "popup8": 255}
```

`bar_over_content` is there because alphas stack. A bar drawn on top of the 0.60 content must itself be painted at `(0.65 - 0.60) / (1 - 0.60) = 0.125` to end at 0.65. Painting it at 0.65 gives 0.86.

## The idea in one line

Each app paints its own background with alpha, and its niri rule goes back to `opacity 1.0`. Blur stays on from the DMS rule. Both halves always go together:

- app alpha without the `opacity 1.0` rule multiplies with the DMS 0.60: the background ends at 0.36 and text at 0.60;
- the `opacity 1.0` rule without app alpha makes the window fully opaque.

So appglass writes the rule only for the apps it really glasses, in one file, `~/.config/niri/appglass.kdl`, included right after `dms/windowrules.kdl` (the same pattern as `dms-browser-glass.kdl`). After every change it runs `niri validate`. If niri rejects the file, a command you typed takes the rule out again; a hook or sync run leaves it and reports the error, and the next typed `appglass apply` validates again and takes it out.

## How an app gets its route

1. **Detect.** `appglass detect` reads each launcher and the binary it starts, without running the app: the ELF libraries it links, Electron fuses, the flatpak runtime. The result is a toolkit (gtk4, gtk3, qt-widgets, electron, webkitgtk, flutter, ...). `appglass learn` adds the toolkit of windows that are open right now, for apps the static read cannot place.
2. **Route.** An app that a family lists (Alacritty, GTK3, GTK4, Obsidian, Herdr, Dux, Feishin, Lian Li, LocalSend, ArtCraft, Jellyfin, VLC, Discord) takes that family, and that is final: glass when the family is on, the fallback look when it is off. A route you picked in Settings > Apps comes before it. Otherwise the app gets one route from the catalogue, by app id (Steam, Jellyfin, OBS) or by toolkit, but that route has no files in this version, so the app keeps the fallback look. With no route for its toolkit, the app gets the fallback.

   TODO(engine): a ranked list of routes per toolkit, where the first route that is implemented and switched on wins.
3. **Apply.** appglass plans every write first, then writes. Each file it creates or edits is recorded with a backup, so it can be undone byte for byte.

`appglass status` shows, for each app, the route it got and the reason (for example "family gtk3", "no adapter for toolkit java", "forced adapter, off until enabled (risk medium)").

A Native app switched off in Settings > Apps shows as fallback with the reason "off in settings", even though it keeps its glass until its family is off (see [Safety](#safety)).

### Route kinds

| Badge | What it means | On by default |
|---|---|---|
| Native | A colour file, a CSS file, a theme or a config key the app already reads. Nothing is loaded into the app. | yes |
| Forced | A shim or hook loaded into one launch of the app (a preload library, a Qt style plugin, an Electron inspector hook). The app binary is not changed. | no: ask first |
| Mod | A client mod that the user installed (Vencord for Discord). | no: ask first |
| Fallback | No route: the app gets the fallback look (opaque by default). | |
| Opaque | Kept opaque on purpose (games). | |
| Delegated | Another tool owns it (Firefox-family browsers: browserGlass). | |
| Excluded | DMS draws these windows itself. | |

TODO(engine): new classes decided before any route: `root` (the launcher goes through pkexec, sudo, su or run0: opaque, reason "runs as root"), `sensitive` (password managers: native routes only, never a preload or hook) and `game-launcher` (Steam, Lutris, Heroic, umu-run, Bottles: never a preload).

## States you see

These are the status chips in Settings > Apps:

| Chip | Meaning |
|---|---|
| Glass | The route is applied. |
| Fallback | No route, the app's family is not installed, or a Forced or Mod route is off (its default). The window gets the fallback look. |
| Paused | The glass is paused, or you switched this app off. For a Native app the files stay until its family is off (see [guide.md](guide.md#per-app-switch)). |
| Conflict | A hand-made file that appglass does not own is in the way. Settings > Advanced > Adopt hand-made files hands it over, backed up first. |
| Opaque | Kept opaque on purpose. |
| Delegated | Owned by browserGlass, or drawn by DMS. |

TODO(engine): the states `waiting` (an injected route waits for its hidden check, shown opaque) and `stale` (an injected route after an app update, shown opaque until it passes again).

## When it runs

- `appglass hook install` adds a matugen user template whose post-hook runs `appglass apply --from-hook --quiet`, so every DMS theme change re-renders the colours of the families already applied.
- The `appglass-sync.path` user unit watches `niri/dms/windowrules.kdl` and `~/.cache/dms/dms-colors.json`. A change of the DMS level or colours re-applies.
- `appglass-discord.path` watches Discord's config, so the Vencord route survives a Discord update.
- `appglass-vibrancy.service` is the only resident process: it fades unfocused Alacritty windows, which niri cannot do without fading the text.
- The DMS plugin only writes settings and runs `appglass sync`. The units and the CLI do the work, so the glass stays the same when the plugin is off.

TODO(engine): the sync unit will also watch `/usr/share/applications`, the rpm database, the flatpak `.changed` files, `~/.local/share/applications` and `~/Applications`, plus a daily timer. One short job then fingerprints the launchers with `stat` only and re-routes just the apps that changed. Measured on the design prototype: 86 fingerprint keys (46 launchers) in 3.0 ms, about 25 ms per event, 1.7 s for the cold scan, once.

## Never touched

- **Games.** Steam games (`steam_app_*`) and gamescope windows get a niri rule with `opacity 1.0` and blur off. No file, env variable or preload ever reaches a game. Steam's own `steam://rungameid` launchers are detected as games.
- **Windows DMS and Quickshell draw themselves.** They are already glass.
- **Firefox-family browsers.** browserGlass owns them.
- **System files.** appglass writes only under your home folder, never needs root, and never modifies an app binary, asar or flatpak deploy. Its changes sit beside the app: launcher overrides in `~/.local/share/applications`, user CSS and themes, a preload for one launch.
- **Your own edits.** A file you changed after appglass keeps your change. Anything you took out stays out on later theme changes.

One exception to "beside the app": the Mod route for Discord re-runs the Vencord installer you installed after a Discord update, and that installer patches Discord's own `app-*/resources` folder. This is why it is a Mod route, off until you turn it on.

TODO(engine): `root` GUIs (Timeshift through pkexec) and password managers will be classed and kept away from injected routes, and a hard deny-list will refuse writes under `/usr`, `/etc`, `/var`, `/opt` and `/app`. Today they fall to whatever the toolkit route says, and the Forced routes only exist for the apps listed in [routes.md](routes.md).

## Safety

- **Every write is recorded.** state.json lists each file appglass owns or edited, with a backup of the original. `appglass remove` puts every one back byte for byte; files it created are deleted.
- **A backup ring.** Each apply that changes files keeps a snapshot of those files and of state.json. The last 5 are kept. `appglass restore --list` shows them.
- **No blind overwrite.** If state.json is lost but appglass files are still on disk, apply writes nothing and says how to get back: `appglass restore` puts back the newest saved state and files; without a saved one, `appglass adopt --rescue` records the appglass files again (`appglass doctor` lists them).
- **Self-check.** `appglass doctor` compares appglass's own files (units, niri rule, owned files, plugin link) with what the repo would render. `appglass doctor --fix` re-renders what drifted, and the ring keeps what it overwrites.
- **Opt-in for anything loaded into an app.** Forced and Mod routes stay off until you turn them on, one app at a time, and the plugin asks first.
- **No event removes anything.** Disabling, reloading or re-enabling the plugin changes no file and no unit. Only a pause, a family switched off, a Forced or Mod app switched off, `appglass remove` or the confirmed uninstall takes files out. Switching off a Native app in Settings > Apps takes nothing out yet: only its whole family can be switched off, with `dms ipc call appGlass app <family> off` while the plugin is installed (for example `dms ipc call appGlass app gtk3 off`), or `appglass set apps.<family>.enabled false --apply` without it.

  TODO(engine): a per-app off for Native apps that takes their files out.

TODO(engine): a route that loads code into an app will go live only after a hidden check passes: the app is started in a headless compositor (gamescope headless, nested niri, a private D-Bus, a throwaway home), never on your screen, and the window must show its background at the level and its text at 255. The prototype measured only the background: Alacritty at alpha 153 in 2.22 s. The text check has not been shown yet.

## When something fails

Failure always ends opaque, never half-faded:

- With the default fallback ("Opaque"), every window appglass does not glass gets `opacity 1.0`. A window with no route is opaque and sharp.
- A shim that cannot be built (no compiler, no Qt headers) makes apply skip that family with a warning that names what is missing. The app keeps the fallback look.
- If `niri validate` rejects the rule file, a typed command takes the rule out again (the ring keeps the files). A hook or sync run leaves it and reports the error; the next typed `appglass apply` validates again and takes it out.
- A hand-made file in the way shows as Conflict. appglass does not write over it.

TODO(engine): after an app update an injected route is shown opaque until it passes the hidden check again; an app that fails to open a window twice under its route goes back to the plain app, with one notification: "<App>: glass paused after an update".

## Cost

- Idle: no process of appglass runs, except the Alacritty fade reader (`appglass-vibrancy.service`). The path units are watched by the systemd user manager.
- A theme or level change: one `appglass apply --from-hook`, which re-renders only the families already applied.
- `appglass detect` over every installed launcher: 1.74 s and 384 MB peak memory, measured once on the test machine. It runs only when you ask for it or apply with `--all`.
- Launch: the wrappers of Forced routes read the current levels at start (`appglass levels`).

## Limits

- **Apps started outside their launcher** (from a shell, or by D-Bus activation) do not get launcher-based routes (GTK3 theme, Qt style, shims). They keep the fallback look: opaque and sharp. GTK4 uses the global CSS, so it is not affected.
- **Restart needed** after a theme change for GTK apps and Dux Calendar. Alacritty, Herdr and Dux Files reload live. Obsidian needs a restart on the first enable (or the snippet toggled off and on), and reloads live after that.
- **Light mode** is measured less than dark mode.
- **Dark logos drawn by an app** can be hard to see on dark glass. CSS cannot reach them.
- **Opaque by design:** Steam, Chrome and other Chromium browsers, games, Java, Tk and X11 apps that are not GTK, Qt from a flatpak KDE runtime, Electron apps with no CSS hook. See [routes.md](routes.md#opaque) for each reason.

  TODO(adapters): `appglass status` still lists Steam with the old Forced route `steam-cdp` and a switch; that switch does nothing ("adapter steam-cdp not implemented yet") and Steam stays opaque.
