# Steam

The Steam client stays opaque. `appglass status` shows it as `opaque` with the reason
"Steam client (CEF): no injection, it stays opaque".

## Why

- The client UI is CEF (`steamwebhelper`). Like Chrome, its web content paints an opaque page, and Valve's
  CEF flags give no window alpha on Linux.
- Injecting CSS or code into the client (a preload, the CEF remote debugging port) was dropped. Steam is a game
  launcher: its children are games, some with anti-cheat, so nothing is loaded into Steam or anything it starts.
- Steam's own GL composer option is still being checked in a throwaway Steam (result pending). Unless it gives
  the window real alpha, there is no route.

## What appglass does with Steam

- Detect marks the client `cef` and the class `game-launcher`. A game launcher may get a native route one
  day, but never an injected one (preload, inspector, colour key).
- Steam games (`steam://rungameid`, `steam_app_<id>` windows, anything under `steamapps/common/` or
  `compatdata/`) are the class `game`: excluded, no override written, blur off. Once seen as a game, an app
  stays a game.
- Self-heal follows the client's version through the mtime of `package/steam_client_*.manifest`, so a Steam
  update is noticed, but there is nothing to re-apply.
- `appglass verify` waits while a game runs: it never starts a hidden session during a game.
