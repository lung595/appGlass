# The App Glass plugin for DMS

The plugin is a settings page and a bar pill over the `appglass` command. It saves your choices and runs `appglass sync`; the user units and the CLI do the work. Turning the plugin off, reloading it or restarting DMS changes no file and no unit: the glass stays as it is.

Install it with `appglass plugin install` (see [guide.md](guide.md#install)), then enable "App Glass" in DMS Settings > Plugins.

## The page

At the top:

- the **search** field;
- a line with the state ("Glass on, N apps on glass", "Glass paused", "Uninstalled: every file restored") and the **Pause glass** / **Resume glass** button;
- the last error, if a command failed.

On the left, the rail: Glass, Apps, Fade, Fallback, Advanced, About. On a narrow window the rail shows icons only.

### Search

The search goes over every setting on every page and over the app list.

- **Ctrl+F** goes to the search field from anywhere on the page; **/** does too when no text field has the keys.
- Typing filters the page to the matching settings and apps.
- **Enter** opens the page of the best match.
- **Esc** clears the search; a second **Esc** gives the keys back to the page.

## Glass

- **Glass for desktop apps**: the main switch. Off pauses the glass in every app; turning it on puts it back. Same as the Pause button and a right click on the bar pill.
- **Glass level**: read-only. It follows the DMS window opacity (the "Glass blur" window rule): content at that level, bars at `max(content, 0.65)`, popups opaque. Text and icons stay opaque. To change it, change the DMS rule.
- **Apps on glass**: how many apps have glass, fall back or stay opaque.
- **Re-apply**: writes every glass file again from the current settings. New and updated apps are picked up on their own (see [engine.md](engine.md#when-it-runs)); Re-apply is for when you want it now.

TODO(engine): an "Automatic for new apps" switch, to turn the automatic routing of new apps off.

## Apps

- **App list**: one row per app, with its name, a status chip, the route and its badge, the reason, and a switch.
  - Status chips: Glass, Fallback, Waiting for check, Stale, Paused, Conflict, Opaque, Game: never touched, Delegated. What each one means: [engine.md](engine.md#states-you-see).
  - Badges: Native, Forced, Mod, Fallback, Opaque, Delegated, Excluded. What each route does: [routes.md](routes.md).
  - **Per-app switch.** For a Forced or Mod app, off takes that app's files out and the app gets the fallback look. For a Native app the row shows Paused, but its files and its niri rule stay, and the app still opens with glass. This page has no family switch yet: `dms ipc call appGlass app <family> off` (for example `dms ipc call appGlass app gtk3 off`) takes the whole family out and keeps it out. `appglass set` refuses while the plugin is installed and enabled, and `appglass remove --only <family>` lasts only until the next sync (see [guide.md](guide.md#per-app-switch)). Rows for games, browserGlass browsers and DMS windows have no switch.

    TODO(engine): a per-app off for Native apps that takes their files out.
  - **Route choice.** When an app has more than one route, the row lists them to pick from.
  - **Mod and Forced routes are on by default** and go live once their hidden check passes (the row shows Waiting for check until then). Switched off, they **ask before they turn on again**, both from the switch and from the route choice. Native routes turn on at once.
  - A Conflict row names the hand-made file in the way. Advanced > Adopt hand-made files hands it over.

Each app is also found by the search, by name.

TODO(engine): filter chips (All, Glass, Opaque, Off, Games), the evidence behind each route, and the time of the last check (`appglass status --json` has the check's reason).

## Fade

Unfocused windows get a little more transparent. Only the background fades: text stays opaque.

- **Fade unfocused windows**: on or off (on by default).
- **Fade amount**: how much more transparent an unfocused window gets, 0 to 20 % (10 % by default: the unfocused level is the content level x 0.90), never below 60 %. At the default content level of 0.60 nothing changes until the content level is raised.
- **Fade duration**: how long the fade takes, 0 to 400 ms (180 ms by default); 0 ms means no animation.
- **Fade easing**: the curve of the fade animation: Ease out (default), Ease in and out, Linear.
- **Dim apps that cannot fade** (off by default): a niri rule for the other apps. It is instant, and their text dims too.

The apps that fade their own background: the GTK4 and GTK3 apps, Obsidian, Alacritty, Discord (Vencord), Feishin, Jellyfin, Lian Li and the Qt style apps (VLC, Kate and the Qt apps the engine finds). The fade is recorded for GTK3, VLC, Feishin and Jellyfin; for the others it is unit-tested, not recorded ([routes.md](routes.md) says so per app). The level is written into each app's files and launcher, so most open apps pick up a change when they restart.

TODO(fade): the terminals other than Alacritty (Konsole's terminal area included), Zed, mpv, GIMP, VSCodium and the colour-key apps (LocalSend, ArtCraft) do not fade yet: only "Dim apps that cannot fade" reaches them.

## Fallback

What the apps appglass cannot glass look like.

- **Apps without glass**:
  - **Opaque** (default): `opacity 1.0`, sharp text, no fade.
  - **Translucent (text too)**: the whole window at the Fallback opacity. Text fades with it.
  - **DMS opacity**: appglass leaves these windows alone, at the DMS rule's opacity. Text fades with it.
- **Fallback opacity**: the opacity of the translucent fallback (0.70 by default).

## Advanced

- **Learn open windows**: records the toolkit of each open window, so an app the static read could not place gets the right route. Same as `appglass learn`.
- **Adopt hand-made files**: hands the known hand-made glass files to appglass, each one backed up first. Uninstall puts the originals back. Same as `appglass adopt`.
- **Copy report**: copies every app's status, route and reason as text, for a bug report.
- **Uninstall appGlass**: see [Uninstall](#uninstall).

TODO(engine): "Run check now" (the hidden check: `appglass verify <key>` from a terminal), "Doctor" and "Fix" buttons, and the switch for debug-port routes.

### Uninstall

**Uninstall appGlass** asks first: "Every file appglass wrote or changed is put back byte for byte, its sync hook goes, then this plugin's link. Your other DMS plugins are not touched."

On confirm, the plugin:

1. stops every sync that waits, and waits for one that runs, so nothing writes the glass back;
2. runs `appglass remove`: every file restored, the matugen hook and the user units removed;
3. runs `appglass plugin remove`: the plugin link removed.

If step 2 fails, nothing is half-removed: the page says "Uninstall stopped: <error>. Glass is set up again from the current settings", and the glass comes back from a sync. If step 3 fails, the page says: "Every file is restored, but this plugin's link stays: run 'appglass plugin remove' in a terminal to finish." The bar pill then says "uninstalled". While the plugin is still loaded after an uninstall, **Set up again** brings the glass back with the settings the plugin kept (per-app choices, fade, fallback: an app switched off stays off); `appglass get` fills in only a setting it never stored.

If DMS reloads the plugin or restarts while step 2 runs, the plugin starts without a sync (a sync would write the glass back) and the page says "Uninstall did not finish": **Uninstall** again finishes it, **Set up again** keeps the glass.

The same from a terminal: `appglass remove && appglass plugin remove`.

## About

- **Version**: the appGlass version.
- **Never touched**: games, the windows DMS and Quickshell draw themselves, and the browsers browserGlass owns (shown as Delegated). appglass only writes under your home folder and never needs root.
- **Command line**: `appglass status`, `appglass learn`, `appglass adopt` and `appglass remove` do the same from a terminal.

## Bar pill

The pill shows the glass icon and how many apps are on glass; while paused the icon changes to "blur off" and the pill says "off", after an uninstall "uninstalled". A click opens the settings; a right click pauses or resumes the glass.

## IPC

For key bindings or scripts:

| Call | Does | Answers |
|---|---|---|
| `dms ipc call appGlass status` | the last `appglass status --json` | JSON |
| `dms ipc call appGlass sync` | re-apply from the current settings | `OK`, or `not ready` while the plugin is still starting |
| `dms ipc call appGlass toggle` | pause or resume | `glass on` / `glass off` |
| `dms ipc call appGlass pause` | pause | `glass off` |
| `dms ipc call appGlass resume` | resume | `glass on` |
| `dms ipc call appGlass app <key> on\|off` | one app's switch | `<key> on` / `<key> off` |

While an uninstall runs, or after it, the calls that change something answer `uninstalling` or `uninstalled` and change nothing.

A niri key binding, for example:

```kdl
Mod+Shift+G { spawn "dms" "ipc" "call" "appGlass" "toggle"; }
```

## While the plugin is installed and enabled

The plugin owns the settings. `appglass set` then refuses with a hint to use the settings page: change settings there or through IPC. With the plugin disabled in DMS Settings > Plugins (or not installed), `appglass set` works again; when the plugin is enabled again, its own stored settings replace what was set meanwhile (its start sync saves and applies them). `appglass status`, `appglass learn`, `appglass apply` and `appglass remove` still work from a terminal.
