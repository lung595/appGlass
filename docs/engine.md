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

Install an app the usual way (dnf, flatpak, an AppImage, a hand-written launcher). Within seconds appglass detects it, picks a route, and either makes it glass or leaves it opaque with a reason. No command is needed. For each launcher:

1. **Detect.** appglass reads the launcher and the binary it starts, without running the app: the ELF libraries it links, Electron fuses, the flatpak runtime. The result is a toolkit (gtk4, gtk3, qt-widgets, electron, webkitgtk, flutter, ...). `appglass detect` prints it, and `appglass learn` adds the toolkit of windows that are open right now, for apps the static read cannot place. Detect results are cached by a stat-only fingerprint of the launcher and every file the probe read (`~/.cache/appglass/detect.json`), so only a new or changed launcher is probed again.
2. **Class.** Some apps are kept away from routes before any route is picked (see [Classes](#classes-what-is-never-touched)): root GUIs, games, password managers, game launchers.
3. **Route.** An app that a family lists (Alacritty, Solaar, Nautilus, Obsidian, Herdr, Dux, Feishin, VSCodium, Lian Li, LocalSend, ArtCraft, Jellyfin, VLC, Discord, the terminals, Zed, Kate, Konsole, mpv, GIMP) takes that family. A route you picked in Settings > Apps comes before it. Any other app takes the route of its toolkit (see [Routes by toolkit](#routes-by-toolkit)), and with no route for its toolkit it gets the fallback look.
4. **Gate.** A theme route goes live at once. A route that loads code into the app waits for its hidden check (see [The gate](#the-gate-glass-waiting-stale-opaque-off-excluded)).
5. **Apply.** appglass plans every write first, then writes. Each file it creates or edits is recorded with a backup, so it can be undone byte for byte.

`appglass status` shows, for each app, the route it got, its state and the reason (for example "family gtk3", "no adapter for toolkit java", "waiting for a check (injected route)", "runs as root (pkexec): never touched").

A Native app that a family lists by hand (Solaar in `gtk3`, Alacritty) and that you switched off in Settings > Apps shows as fallback with the reason "off in settings", even though it keeps its glass until its family is off (see [Safety](#safety)). An app that only its toolkit route reached (a GTK3 or Qt app no family lists) shows "off" with the same reason; its launcher override and niri rule stay through the syncs and go with the next typed `appglass apply --all`.

### Route kinds

| Badge | What it means | On by default |
|---|---|---|
| Native | A colour file, a CSS file, a theme or a config key the app already reads. Nothing is loaded into the app. | yes, at once |
| Forced | A shim or hook loaded into one launch of the app (a preload library, an Electron inspector hook). The app binary is not changed. | yes, after its hidden check passes |
| Mod | A client mod that the user installed (Vencord for Discord). | yes, after its hidden check passes |
| Fallback | No route: the app gets the fallback look (opaque by default). | |
| Opaque | Kept opaque on purpose (games, root GUIs). | |
| Delegated | Another tool owns it (Firefox-family browsers: browserGlass). | |
| Excluded | DMS draws these windows itself. | |

The Qt style plugin is a Native route: Qt loads the style itself, nothing is preloaded.

### Classes: what is never touched

| Class | How it is found | Result |
|---|---|---|
| root | `pkexec`, `sudo`, `run0`, `doas` or `su -c` in the Exec line or in the script it runs (Timeshift) | opaque, "runs as root (...): never touched" |
| game | `steam://rungameid`, `umu-run`, wine or proton, an exe under `steamapps/common/`, `compatdata/`, `Heroic/`, `lutris/` or `Games/`, SDL with no toolkit | excluded, no override written, blur off. Sticky: once a game, always a game |
| sensitive | password and secrets apps (KeePassXC, Bitwarden, Seahorse, ...) | native routes only: never a preload or hook |
| game-launcher | Steam, Lutris, Heroic, Bottles, umu-run | never a preload, no theme by environment (see [steam.md](steam.md)) |
| spawner | terminals, file managers, IDEs and app launchers (they start other apps) | no theme by environment (`GTK_THEME`, `QT_STYLE_OVERRIDE`) from a toolkit route: it would reach every app they start. Konsole has its own route, and its Qt style is taken out of the environment of the shells it starts |
| game-category | `Categories=Game` in the launcher, with no other game sign | no theme by environment |

A launcher whose target is gone (an Exec that is not on `PATH`, an absolute path that does not exist, a failing `TryExec`) is "not installed" and gets nothing. The usual case is a launcher left behind by an app whose client was deleted.

### Routes by toolkit

- **GTK3:** every GTK3 app gets the `GTK_THEME=AppGlass` launcher override.
- **Qt6 Widgets (host):** every app that needs `libQt6Widgets` gets `QT_STYLE_OVERRIDE=appglass`, with the unfocused fade.
- **GTK4:** the global `gtk-4.0/gtk.css`. A GTK4 flatpak gets a launcher override that adds `--filesystem=xdg-config/gtk-4.0:ro` to that launch only. appglass never writes a persistent `flatpak override`.
- **Electron:** only the per-app routes (Obsidian, Vencord for Discord, the Feishin and VSCodium inspector hook).
- **Chrome and Chromium browsers:** no route. Web content has no window alpha, so they stay opaque.
- **Steam client (CEF):** no route, nothing injected. See [steam.md](steam.md) and [Limits](#limits).

TODO(adapters): a generic Electron route through `NODE_OPTIONS`, and a ck-shim route with learned colour keys for apps that have no hand-made keys (see [routes.md](routes.md)).

## States you see

These are the status chips in Settings > Apps:

| Chip | Meaning |
|---|---|
| Glass | The route is applied. |
| Fallback | No route, or the app's family is not installed. The window gets the fallback look. |
| Waiting for check | An injected route waits for its first hidden check. The app runs plain, its window opaque. |
| Stale | An injected route after an app update: the old check no longer counts. The app runs plain until it passes again. |
| Paused | The glass is paused, or you switched this app off. For a Native app the files stay until its family is off (see [guide.md](guide.md#per-app-switch)). |
| Conflict | A hand-made file that appglass does not own is in the way. Settings > Advanced > Adopt hand-made files hands it over, backed up first. |
| Opaque | Kept opaque on purpose, or an injected route that failed its check or two launches. |
| Game: never touched | A game: opaque, blur off, nothing written. |
| Delegated | Owned by browserGlass, or drawn by DMS. |

`appglass status --json` gives each app one of the states glass, waiting, stale, opaque, off, excluded, with its reason. Files that a retired family once wrote (the old Vencord files) are no longer listed.

## When it runs

- `appglass hook install` adds a matugen user template whose post-hook runs `appglass apply --from-hook --quiet`, so every DMS theme change re-renders the colours of the families already applied. It also installs the user units below.
- `appglass-sync.path` watches the DMS colours (`~/.cache/dms/dms-colors.json`) and window rules (`niri/dms/windowrules.kdl`), the launcher folders (`/usr/share/applications`, `~/.local/share/applications`, `~/Applications`), the rpm database and the flatpak `.changed` stamps (system and user). A change of the DMS level or colours re-applies; a new or updated app is routed.
- A dnf transaction touches the rpm database many times. The path unit has no trigger limit (`TriggerLimitBurst=0`) and the service no start limit: a hit limit would put the path unit into a failure mode that stops every watch, the DMS follow included, until the next login. The service coalesces the burst instead: one run at a time, a 1 s settle, then it waits until the rpm database has been quiet for 5 s.
- `appglass-sync.timer` runs the same sync once a day, for apps that update themselves and for a missed event.
- `appglass-verify.service` runs the queued hidden checks (see [The gate](#the-gate-glass-waiting-stale-opaque-off-excluded)). A sync that queued a check starts it.
- `appglass-discord.path` watches Discord's config, so the Vencord route survives a Discord update.
- `appglass-vibrancy.service` is the only resident process: it fades unfocused Alacritty windows, which niri cannot do without fading the text.
- The DMS plugin only writes settings and runs `appglass sync`. The units and the CLI do the work, so the glass stays the same when the plugin is off.

## The gate: glass, waiting, stale, opaque, off, excluded

A theme route (GTK, Qt, a config key, the GTK4 config dir) goes live at once. An injected route (a preload, an inspector hook, a colour key, a client mod) goes live only after `appglass verify` has passed for the app's current version (its fingerprint). Until then the app is "waiting for a check" and runs plain. After an app update the old pass no longer counts, so the app is "stale" and runs plain until the next check. If you turned the app on yourself in Settings > Apps, that counts as consent: it is glass at once ("enabled by you (not checked yet)"), and the check still runs.

`appglass-verify.service` runs the queued checks idle (nice 19, idle IO, at most half a CPU, 2 GB). Each check starts the app in a hidden headless session: gamescope `--backend headless`, a nested niri, a private `XDG_RUNTIME_DIR` and `TMPDIR`, `env -i`, a private D-Bus and a throwaway HOME holding a copy of the app's glass files. Never on your screen. The window shot must show the background at the content level (on at least a quarter of the window) and opaque text. Nothing is run while a game window is open or a wine, wineserver, proton, umu-run, Steam reaper or pressure-vessel process runs, while niri does not answer, nor on a battery under 20 %. `appglass verify <key>` runs one check by hand.

What the hidden session does not isolate: the network, abstract Unix sockets, the system D-Bus and USB devices (there is no `unshare -n` without user namespaces). An app checked there runs for real for up to 50 s: LocalSend announces itself on the LAN and listens on its port (a file sent to it lands in the throwaway HOME, deleted after), and Lian Li's GUI talks to its daemon as it does at every start. An app the kernel kills for memory under the 2 GB shows no window, so it counts as unverifiable: its injected route stays off, unless you switched the app on yourself.

Every glass wrapper reads a plain marker (`~/.local/state/appglass/plain/<key>`) first, and starts the plain app while the gate says so. Every wrapper also starts `appglass launch-check`. If the app dies with no window twice on the same version, it runs plain until its next update. `appglass fail <key>` records a failed launch by hand.

ck-shim colour keys are data (`~/.cache/appglass/keys/<key>/<fp>/<mode>.json`, one file per dark and light mode, written by `appglass keys`), so an update or a theme flip never needs a wrapper edit.

### Feishin and VSCodium: the inspector port is closed after the injection

The wrapper starts the app with `--inspect=127.0.0.1:0` (a random port on loopback only). The session id goes to a 0700 runtime dir. `agl-inject.py` loads `agl-hook.js` in the main process, retrying while Node starts, then arms `inspector.close()` and hangs up, after a failed injection too. Node's `close()` waits for every session to end, so it runs on a timer after the injector has gone. The injector then checks that the port refuses connections and prints `inspector closed`. If the port were still open, it says so on stderr. It stays bound to 127.0.0.1 with a random port, and nothing else is exposed.

Measured on Feishin 1.17.0: the inspector port is gone about 4 s before the screenshot, and the app keeps running with its glass.

Limit: the hidden check starts Feishin in a throwaway HOME, where it opens its first-run dialogs ("server required", "a new version has been installed"). Their dimmed backdrop covers the glass, so the check sees about 205 where it expects 153 and reports a fail.

## Never touched

- **Games.** Steam games (`steam_app_*`) and gamescope windows get a niri rule with `opacity 1.0` and blur off. No file, env variable or preload ever reaches a game. Steam's own `steam://rungameid` launchers are detected as games.
- **Root GUIs and password managers.** See [Classes](#classes-what-is-never-touched).
- **Windows DMS and Quickshell draw themselves.** They are already glass.
- **Firefox-family browsers.** browserGlass owns them.
- **System files.** appglass writes only under your home folder, never needs root, and never modifies an app binary, asar or flatpak deploy. Its changes sit beside the app: launcher overrides in `~/.local/share/applications`, user CSS and themes, a preload for one launch. The preload variables are taken out of the environment of the app's child processes.
- **Your own edits.** A file you changed after appglass keeps your change. Anything you took out stays out on later theme changes.

One exception to "beside the app": the Mod route for Discord re-runs the Vencord installer you installed after a Discord update, and that installer patches Discord's own `app-*/resources` folder. This is why it is a Mod route.

TODO(engine): a hard deny-list that refuses writes under `/usr`, `/etc`, `/var`, `/opt` and `/app`. Today every write path is under the home folder by construction, but nothing refuses a system path.

## Safety

- **Every write is recorded.** state.json lists each file appglass owns or edited, with a backup of the original. `appglass remove` puts every one back byte for byte; files it created are deleted.
- **A backup ring.** Each apply that changes files keeps a snapshot of those files and of state.json. The last 5 are kept. `appglass restore --list` shows them.
- **No blind overwrite.** If state.json is lost but appglass files are still on disk, apply writes nothing and says how to get back: `appglass restore` puts back the newest saved state and files; without a saved one, `appglass adopt --rescue` records the appglass files again (`appglass doctor` lists them).
- **Self-check.** `appglass doctor` compares appglass's own files (units, niri rule, owned files, plugin link) with what the repo would render. `appglass doctor --fix` re-renders what drifted, and the ring keeps what it overwrites.
- **A check before anything loaded into an app.** Forced and Mod routes are on by default, but they go live only after the hidden check passes for the app's current version, and an update sends them back to the check. You can switch any of them off, one app at a time; turning one on from the plugin asks first. The check is coarse: it asks for the background at the level and at least 12 opaque pixels (text), and it cannot tell text from an opaque button.
- **No event removes anything.** Disabling, reloading or re-enabling the plugin changes no file and no unit. A failed check or launch only makes the app run plain: its files stay. Only a pause, a family switched off, a Forced or Mod app switched off, `appglass remove` or the confirmed uninstall takes files out. Switching off a Native app in Settings > Apps takes nothing out yet: only its whole family can be switched off, with `dms ipc call appGlass app <family> off` while the plugin is installed (for example `dms ipc call appGlass app gtk3 off`), or `appglass set apps.<family>.enabled false --apply` without it.

  TODO(engine): a per-app off for Native apps that takes their files out at once, from the plugin.

## When something fails

Failure always ends opaque, never half-faded:

- With the default fallback ("Opaque"), every window appglass does not glass gets `opacity 1.0`. A window with no route is opaque and sharp.
- A shim that cannot be built (no compiler, no Qt headers) makes apply skip that family with a warning that names what is missing. The app keeps the fallback look.
- If `niri validate` rejects the rule file, a typed command takes the rule out again (the ring keeps the files). A hook or sync run leaves it and reports the error; the next typed `appglass apply` validates again and takes it out.
- A hand-made file in the way shows as Conflict. appglass does not write over it.
- An injected route that fails its check, fails it again after an update, or opens no window on two launches, runs plain until the app's next update, with one desktop notification: "<App>: glass paused, its glass check failed", "<App>: glass paused after an update" or "<App>: glass paused after two failed launches".

## Cost

- Idle: no process of appglass runs, except the Alacritty fade reader (`appglass-vibrancy.service`). The path units and the timer are watched by the systemd user manager.
- A sync: a stat-only fingerprint pass over every launcher, and a probe only of new or changed ones. Measured on the design prototype: 86 fingerprint keys (46 launchers) in 3.0 ms, about 25 ms per event, 1.7 s for the cold scan, once.
- A sync with nothing to do: the hook run (`apply --from-hook --quiet`) remembers every path it looked at, with its stat (`~/.cache/appglass/hook/inputs.json`), when it wrote nothing and started no program. The next such run stats those paths and appglass's own sources first; when none changed it exits before the lock, in about 20 ms with Python's start included.
- The compiler and Qt versions in a shim's build stamp are kept in `~/.cache/appglass/toolchain.json` while the tools and the `.pc` files stay the same, so a run that builds nothing starts no compiler.
- A warning that holds from one run to the next (GTK4 with no `dank-colors.css` yet) is printed once, not on every hook run.
- A theme or level change: one `appglass apply --from-hook`, which re-renders only the families already applied.
- `appglass detect` over every installed launcher, cold: 1.74 s and 384 MB peak memory, measured once on the test machine.
- A hidden check: up to 50 s per app, idle priority, at most half a CPU and 2 GB.
- Launch: the wrappers of Forced routes read the current levels at start (`appglass levels`).

## Limits

- **Apps started outside their launcher** (from a shell, or by D-Bus activation) do not get launcher-based routes (GTK3 theme, Qt style, shims). They keep the fallback look: opaque and sharp. GTK4 uses the global CSS, so it is not affected.
- **Restart needed** after a theme change for GTK apps and Dux Calendar. Alacritty, Herdr and Dux Files reload live. Obsidian needs a restart on the first enable (or the snippet toggled off and on), and reloads live after that.
- **Light mode** is measured less than dark mode.
- **Dark logos drawn by an app** can be hard to see on dark glass. CSS cannot reach them.
- **Opaque by design:** Steam, Chrome and other Chromium browsers, games, root GUIs, Java, Tk and X11 apps that are not GTK, Electron apps with no CSS hook. Qt flatpaks on the KDE runtime cannot load the host Qt style: only Kate and Konsole, which have their own routes, get glass. See [routes.md](routes.md#opaque) for each reason.

  TODO(adapters): `appglass status` still lists Steam with the old Forced route `steam-cdp` and a switch; that switch does nothing (the reason stays "Steam client (CEF): no injection, it stays opaque") and Steam stays opaque. The route is to be dropped from the catalogue.
