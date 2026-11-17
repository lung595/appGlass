# The engine: every app automatic, and self-heal after updates

Install an app the usual way (dnf, flatpak, an AppImage, a hand-written launcher). Within seconds appglass
detects it, picks a route by toolkit, and either makes it glass or leaves it opaque with a reason. No command
is needed. After an app update the glass is checked again before an injected route goes live.

## What triggers a sync

- `appglass-sync.path` watches the launcher dirs (`/usr/share/applications`, `~/.local/share/applications`,
  `~/Applications`), the rpm database, and the flatpak `.changed` stamps (system and user). It also watches the
  DMS colours and the DMS window rules, as before.
- A dnf transaction touches the rpm database many times. The path unit has no trigger limit
  (`TriggerLimitBurst=0`) and the service no start limit: a hit limit would put the path unit into a failure
  mode that stops every watch, the DMS follow included, until the next login. The service coalesces the burst
  instead: one run at a time, a 1 s settle, then it waits until the rpm database has been quiet for 5 s.
- `appglass-sync.timer` runs once a day, for apps that update themselves and for a missed event.
- `appglass hook install` installs all three units (path, service, timer) and the verify service.

Each run starts with a stat-only fingerprint pass over every launcher (`~/.cache/appglass/detect.json`).
Only new or changed launchers are probed again, so a run with no change costs a few milliseconds.

## Classes: what is never touched

| Class | How it is found | Result |
|---|---|---|
| root | `pkexec`, `sudo`, `run0`, `doas` or `su -c` in the Exec line or in the script it runs (Timeshift) | opaque, "runs as root" |
| game | `steam://rungameid`, `umu-run`, wine or proton, an exe under `steamapps/common/`, `compatdata/`, `Heroic/`, `lutris/` or `Games/`, SDL with no toolkit | excluded, no override written, blur off. Sticky: once a game, always a game |
| sensitive | password and secrets apps (KeePassXC, Bitwarden, Seahorse, ...) | never an injected route |
| game-launcher | Steam, Lutris, Heroic, Bottles | never an injected route (see [steam.md](steam.md)) |

A launcher whose target is gone (an Exec that is not on `PATH`, an absolute path that does not exist, a
failing `TryExec`) is "not installed" and gets nothing. Gone is the example: both of its launchers point to
a client that is no longer there.

## Routes by toolkit

- **GTK3:** every GTK3 record gets the `GTK_THEME=AppGlass` launcher override.
- **Qt6 Widgets (host):** every record that needs `libQt6Widgets` gets `QT_STYLE_OVERRIDE=appglass`.
- **GTK4 flatpak:** the launcher override adds `--filesystem=xdg-config/gtk-4.0:ro` to that launch only.
  appglass never writes a persistent `flatpak override`.
- **Electron:** the per-app hooks (Obsidian, Vencord for Discord, the Feishin inspector). See below.
- **Chrome and Chromium browsers:** no route. Web content has no window alpha, so they stay opaque.
- **Steam client (CEF):** no route, nothing injected. See [steam.md](steam.md).

## The gate: glass, waiting, stale, opaque, off, excluded

A theme route (GTK, Qt, the GTK4 config dir) goes live at once. An injected route (a preload, an inspector, a
colour key) goes live only after `appglass verify` has passed for the app's current version (its fingerprint).
Until then the app is "waiting for a check" and runs plain. After an app update the old pass no longer counts,
so the app is "stale" and runs plain until the next check.

`appglass-verify.service` runs the queued checks idle (nice 19, idle IO, at most half a CPU, 512 MB). Each
check starts the app in a hidden headless session: gamescope `--backend headless`, a nested niri, a private
`XDG_RUNTIME_DIR`, `env -i`, a private D-Bus and a throwaway HOME holding a copy of the app's glass files. The
window shot must show the background at the content level and opaque text. Nothing is run while a game window
is open, nor on a battery under 20 %. `appglass verify <key>` runs one check by hand.

Every glass wrapper also starts `appglass launch-check`. If the app dies with no window twice on the same
version, it runs plain until its next update, with one desktop notification. `appglass fail <key>` records a
failed launch by hand.

ck-shim colour keys are data now (`~/.cache/appglass/keys/<key>/<fp>/<mode>.json`, one file per dark and
light mode), so an update or a theme flip never needs a wrapper edit.

## Feishin: the inspector port is closed after the injection

Feishin is "Auto, port closed after". The wrapper starts Feishin with `--inspect=127.0.0.1:0` (a random port on
loopback only). The session id goes to a 0700 runtime dir. `agl-inject.py` loads `agl-hook.js` in the main
process, then arms `inspector.close()` and hangs up. Node's `close()` waits for every session to end, so it runs
on a timer after the injector has gone. The injector then checks that the port refuses connections and
prints `inspector closed`. If the port were still open, it says so on stderr. It stays bound to 127.0.0.1 with a
random port, and nothing else is exposed.

Measured on Feishin 1.17.0: the inspector port is gone about 4 s before the screenshot, and the app keeps
running with its glass.

Limit: the hidden check starts Feishin in a throwaway HOME, where it opens its first-run dialogs ("server
required", "a new version has been installed"). Their dimmed backdrop covers the glass, so the check sees
about 205 where it expects 153 and reports a fail.

## Status

`appglass status` and the plugin show the state and its reason for every app. Files that a retired family once
wrote (the old Vencord files) are no longer listed.
