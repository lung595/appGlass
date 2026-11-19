# Routes: how each kind of app gets its glass

A route is the way one kind of app is made to paint its own background with alpha. Every route has the same target, from the DMS level ([engine.md](engine.md#the-levels)):

- content at the level (alpha 153 at 0.60);
- bars at `max(content, 0.65)` (alpha 166 at 0.60);
- popups at 1.0;
- text at 255.

Every route also adds the app's app-id to the `opacity 1.0` rule in `~/.config/niri/appglass.kdl`. Every route is undone by switching its family off, with the family name from the table below: `dms ipc call appGlass app <family> off` while the plugin is installed and enabled (for example `dms ipc call appGlass app gtk3 off`), or `appglass set apps.<family>.enabled false --apply` without it. `appglass remove --only <family>` takes the files out too, but only until the next sync or `appglass apply --all` while the family is still on in settings. The switch in Settings > Apps takes the files out only for a Forced or Mod app; for a Native app it shows Paused and the files stay (see [guide.md](guide.md#per-app-switch)). A Forced or Mod route is on by default, but goes live only once its hidden check passes ([engine.md](engine.md#the-gate-glass-waiting-stale-opaque-off-excluded)). A Native route is on at once and stays on: its check is recorded and shown, a failed one never pauses it, and a check that cannot judge (unverifiable) changes nothing ([engine.md](engine.md#what-a-check-judges-and-what-it-never-does)).

The "Measured" lines come from window screenshots taken in a nested niri session (or, where noted, on the real desktop), with the alpha read per pixel. "0.80" means the measurement was taken at a DMS level of 0.80, where the content target is alpha 204. The per-toolkit pages have the full results.

The app lists below name the apps each family lists by hand. The GTK3, GTK4 and Qt routes also take any app of their toolkit that the engine finds ([engine.md](engine.md#routes-by-toolkit)). The full matrix, with the measured result per app, is in [apps.md](apps.md).

TODO(adapters): a generic Electron route through `NODE_OPTIONS`, for Electron apps no family lists.

| Route | Kind | Family | Apps | Default |
|---|---|---|---|---|
| [Terminal opacity key](#terminals) | Native | `alacritty`, `kitty`, `foot`, `ghostty`, `wezterm`, `konsole` | Alacritty, kitty, foot, Ghostty, WezTerm, Konsole | on |
| [GTK4 CSS](#gtk4--libadwaita) | Native | `gtk4` | Nautilus, GNOME Software, Zenity, the file chooser portal, Flatseal (native package), GNOME Web (chrome only); flatpaks: GNOME Text Editor, Mission Center, Resources; any other GTK4 app that uses libadwaita (a plain GTK4 app, with no libadwaita, gets the fallback) | on |
| [GTK3 theme](#gtk3) | Native | `gtk3` | Solaar, nvidia-settings, any other host GTK3 app | on |
| [Qt style plugin](#qt-widgets-vlc-kate-konsole) | Native | `qtstyle` | VLC, Kate and Konsole (flatpak), any other host Qt 6 Widgets app (not one that also links Qt Quick/QML: that one keeps the fallback) | on |
| [App config](#kate-mpv-gimp-zed) | Native | `kate`, `mpv`, `gimp`, `zed` | Kate (editor theme), mpv, GIMP 3, Zed | on |
| [Obsidian snippet](#obsidian) | Native | `obsidian` | Obsidian | on |
| [Herdr theme](#herdr) | Native | `herdr` | Herdr | on |
| [Dux keys](#dux-files-and-dux-calendar) | Native | `dux` | Dux Files, Dux Calendar | on |
| [Vencord theme](#discord-vencord) | Mod | `vencord` | Discord with Vencord | on, after its check |
| [Electron inspector hook](#feishin-and-vscodium-electron-inspector-hook) | Forced | `feishin`, `vscodium` | Feishin, VSCodium | on, after its check |
| [WebKit shim](#lian-li-webkitgtk-shim) | Forced | `lianli` | Lian Li Linux | on, after its check |
| [WebKit shim, generic](#any-webkitgtk-app-generic-webkit-shim) | Forced | `webkit` | Kiri, any other host GTK3 WebKitGTK 4.x app | on, after its check |
| [Qt Quick shim](#jellyfin-qt-quick-shim) | Forced | `jellyfin` | Jellyfin Desktop | on, after its check |
| [Colour-key shim](#localsend-and-artcraft-colour-key-shim) | Forced | `localsend`, `artcraft` | LocalSend, ArtCraft Launcher (GPU route through a Vulkan layer, else CPU route) | on, after its check |
| [Opaque](#opaque) | | | Steam, Chrome, games, everything else | |

## Terminals

### Alacritty

- **Writes:** `~/.config/alacritty/appglass.toml` (`[window] opacity` = content, plus palette fixes), imported right after `dank-theme.toml` in your `alacritty.toml`. The main file's own `opacity` line is commented out, because the main file wins over every import.
- **Text:** the palette entries that are too faint on glass (DMS black, magenta, bright black, dim colours) are moved toward white on a dark scheme, toward black on a light one, until text reaches 2.25:1 over any backdrop.
- **Measured:** before, under the DMS rule alone, every pixel of the window, text included, is alpha 153. After, the background is 153 and the text 255. Source: [terminal.md](terminal.md).
- **Reload:** live.
- **Fade, not recorded:** `appglass vibrancy` eases `window.opacity` over Alacritty's IPC socket when the niri focus changes; not recorded in a session for this version; the easing and the focus tracking are unit-tested (`tests/test_vibrancy.py`). The service comes with `appglass hook install`; without it Alacritty does not fade, and "Dim apps that cannot fade" reaches it instead.
- **Undo:** `appglass remove --only alacritty` restores `alacritty.toml` byte for byte.

### kitty, foot, Ghostty, WezTerm, Konsole

- **Writes:** an owned file at the content level with the DMS palette made readable on glass, included by the main config (edited, backed up): kitty `appglass.conf` (`background_opacity`), foot `appglass.ini` (`alpha`), Ghostty `appglass` (`background-opacity`), WezTerm `appglass.lua` (`window_background_opacity`, the tab bar at the bar level), Konsole an `AppGlass` colour scheme and profile (`Opacity`). The flatpak builds of foot, WezTerm and Konsole get the same in their `~/.var/app/<id>` folder. Konsole's tabs and menus take the Qt style (below).
- **Measured:** foot (flatpak) background 153, text 255; Konsole (flatpak) background 153, text 255, popups 255. kitty, Ghostty and WezTerm are not measured here: the writers are unit-tested only. Source: [apps.md](apps.md).
- **Fade:** none. These terminals have no lever appglass drives; only "Dim apps that cannot fade" reaches kitty, foot, Ghostty and WezTerm. Konsole's tabs and menus fade with the Qt style and its terminal area does not, and the dim leaves Konsole out (the Qt style fades it already, so a niri dim would dim the tabs twice): its terminal area gets neither a fade nor the dim. The exception is a Konsole flatpak whose KDE runtime's Qt minor is not the host's: the style does not load, so with `instantFallback` on Konsole gets the niri dim (one dim, its colour scheme keeps the terminal area glass) until the Qt minors match again.
- **Undo:** `appglass remove --only kitty` (or `foot`, `ghostty`, `wezterm`, `konsole`) takes the include out.

## GTK4 / libadwaita

- **Writes:** `~/.config/gtk-4.0/dank-glass.css` (alpha on the background colour roles, from the DMS colours), and adds `@import url("dank-glass.css");` after the DMS import in `~/.config/gtk-4.0/gtk.css`.
- **Apps:** `gtk.css` is read by every GTK4 app, so the niri rule lists every GTK4 app appglass knows: Nautilus, GNOME Software, Zenity, the GNOME file chooser portal (used by Chrome and Electron apps), Flatseal (native package), GNOME Web, the libadwaita demo. GNOME Web is partial: its chrome is glass, the web page stays opaque.
- **Measured:** Nautilus content 153, sidebar 166, popovers and dialogs 255, text 255. Source: [gtk4.md](gtk4.md). A status page in the window background (Nautilus' empty folder) is clear, so it does not stack a second fill on the content (the hidden check at 0.80 read 204 with it, 237 before).
- **Reload:** GTK4 reads the CSS at start: restart the app.
- **Fade, not recorded for this version:** `window.background:backdrop` at the unfocused level with a CSS transition; the rendered CSS is unit-tested (`tests/test_gtk4.py`). It uses the same mechanism as GTK3, recorded below. An earlier build was recorded at 0.80 (nested niri, three runs, kept in the probe notes, `shots/fade/gtk4.fade.txt`): 0.80 to 0.72 in 117 to 133 ms, back in 117 to 134 ms.
- **Undo:** `appglass remove --only gtk4` takes the import out and deletes `gtk.css` when nothing of yours is left in it. Taking the import out by hand, or deleting `gtk.css`, is an opt-out that appglass keeps.
- **A `gtk.css` of your own** (anything more than the DMS import line) is never rewritten: the family is skipped and its apps show Fallback. To opt in, add `@import url("dank-glass.css");` after the dank-colors import line yourself.
- **Flatpaks:** flatpak GTK4 apps do not read the host `gtk-4.0` folder. GNOME Text Editor, Mission Center and Resources get the same files in their own `~/.var/app/<id>/config/gtk-4.0`. A `dank-colors.css` you put there yourself as a link to the host one is kept and used; any other file of yours there skips that flatpak only (warned), not the family. Any other GTK4 flatpak the engine finds gets a launcher override that gives that launch read-only access to the host `gtk-4.0` folder; no `flatpak override` is written. Measured: GNOME Text Editor 153, Mission Center 153, Resources 153, text and popups 255 ([apps.md](apps.md)).

## GTK3

- **Writes:** a per-app theme, `~/.local/share/themes/AppGlass/gtk-3.0/gtk.css` (Adwaita, then `dank-colors.css`, then the glass rules), launcher overrides in `~/.local/share/applications/` that start the app with `GTK_THEME=AppGlass`, and `~/.config/autostart/solaar.desktop` with the same change, because Solaar is started at login from the system autostart file (an autostart file you already had is edited, backed up). There is no global `gtk-3.0/gtk.css`, so other GTK3 apps are not affected.
- **Apps:** Solaar, nvidia-settings, and every other host GTK3 app the engine finds (an app that starts other apps and a root GUI excepted; a password manager such as Seahorse gets it too, as password managers get native routes only, never a preload or hook: see [engine.md](engine.md#classes-what-is-never-touched)).
- **Measured:** Solaar content 153 (0.600), header bar and bars 166 (0.651), menus 255, glyph cores 255. Source: [gtk3.md](gtk3.md).
- **Reload:** restart the app (Solaar is a tray process: quit it first).
- **Fade, recorded:** the GTK3 end-to-end check at 0.80 (`APPGLASS_E2E_LEVEL=0.80 tests/e2e/gtk3.sh`, nested niri, the role window behind a second one): focused 204, unfocused 184 (0.72), text opaque at its focused colour (2 runs, from scratch). The fade is the theme's 180 ms CSS transition on `window.background:backdrop`; the steps of the transition were not recorded. On a header bar window the title buttons go 148 to 120 and get no ring when unfocused (one probe in the nested niri; on every run, `tests/test_gtk3.py` `test_unfocused_widgets_keep_their_text` renders the title buttons and a flat header bar button focused and unfocused with real GTK on broadway and checks their pixels: no ring).
- **Undo:** `appglass remove --only gtk3`. A launcher override you already had is edited, backed up and restored byte for byte.
- **Limit:** started from a shell, the app does not get `GTK_THEME` and keeps the fallback look.

## Qt Widgets (VLC, Kate, Konsole)

- **Writes:** a Qt 6 style plugin built from source with the host Qt, `~/.local/lib/appglass/qt6/styles/libappglass.so`, and a launcher override `~/.local/share/applications/vlc.desktop` that starts VLC with `QT_STYLE_OVERRIDE=appglass`, the same for every other host Qt 6 Widgets app the engine finds. Nothing is preloaded: Qt loads the style itself, and takes its variables out of the environment of the processes the app starts.
- **Kate and Konsole (flatpak):** their launcher override gives that `flatpak run` read-only access to the style and the DMS colours. The host-built style loads in the KDE runtime only when its Qt minor version matches the host Qt: apply reads the runtime branch from the flatpak's metadata (`org.kde.Platform/x86_64/6.11` is Qt 6.11) and, when it is not the host's Qt minor, writes no launcher override and no Kate glass `katerc` for that app, warns, and `appglass status` gives the reason. Kate keeps the fallback look until they match. Konsole keeps its colour scheme glass (status still reads glass, family konsole) with plain tabs and menus, and `instantFallback` gives it the niri dim instead of the style's fade.
- **Fade:** an unfocused window eases its background to the unfocused level, in the flatpaks and in the apps the engine finds too (not recorded for the apps the engine finds: the same style, unit-tested in `tests/test_fade.py`).
- **Fade, recorded:** VLC 3.0.24 (under XWayland) at 0.80, 180 ms ease-out, three runs: unfocused, the background went 0.80 to 0.72 in about 110 ms, one step per frame (7 steps; the end of the ease-out is under one 8-bit step); focused again, back to 0.80 in 120 to 180 ms (2 or 3 steps).
- **Measured:** VLC 3.0.24 (host Qt 6) with the appglass style, in a nested niri session at 0.60: controls 153, menu bar and tool bar 166, text 255; the video area stays 255 (black) and the menus are opaque. The same style on a Qt 6 Widgets stand-in (menu bar, tool bar, dock, tabs, status bar): content 153, bars 166, text 255, dialogs 255. Screenshot: VLC in the [issue draft](issue-dms.md#screenshots). [qt.md](qt.md) holds the rows from before the style.
- **Fade, not recorded for Kate and Konsole:** they use the same style as VLC, in the KDE runtime; not recorded in a session for this version; the launcher passing the fade to the style is unit-tested (`tests/test_fade.py`).
- **Needs:** `g++` and the Qt 6 headers. A Qt update rebuilds the plugin.
- **Undo:** `appglass remove --only qtstyle`.
- **Limit:** Qt 5 apps cannot load a Qt 6 plugin, other flatpak apps on the KDE runtime are not routed, and Kate and Konsole get no style while their runtime's Qt minor version is not the host's (status says so): Kate keeps the fallback look, Konsole its colour scheme glass with the niri dim.

## Kate, mpv, GIMP, Zed

Native routes through each app's own config files, for the native and the flatpak build.

- **Kate:** a KSyntaxHighlighting theme "AppGlass" with a clear editor background, under the Qt style glass. Measured (flatpak): 153, text 255, popups 255; the minimap stays a tint.
- **mpv:** `background-color` with the content alpha in `appglass.conf`; the video, the OSD and the console stay opaque. Measured (flatpak): 153, text 255, popups 255.
- **GIMP 3:** a marked block at the end of the user `gimp.css`. The canvas stays opaque by design. Measured (flatpak): 153, text 255, popups 255.
- **Zed:** `theme_overrides` for the active theme in `settings.json`. Partial: Zed 1.28.1 lays a black floor of alpha 0.40 under the window, so the background measures 194, not 153.
- **Undo:** `appglass remove --only kate` (or `mpv`, `gimp`, `zed`). Source: [apps.md](apps.md).

## Obsidian

- **Writes:** `<vault>/.obsidian/snippets/appglass.css` in every vault listed in Obsidian's `obsidian.json`, and turns the snippet on in that vault's `appearance.json` (your other snippets and keys are kept).
- **Measured:** content 153, ribbon, sidebars and tab bar 166, menus and modals 255, text 255; the stock `--text-faint` (under 2:1) is replaced. Source: [electron.md](electron.md).
- **Fade, not recorded:** `body:not(.is-focused)` lowers the snippet colours, with a transition; not recorded in a session for this version; the snippet is unit-tested (`tests/test_obsidian.py`).
- **niri rule `opacity 0.999`:** Obsidian's window is created without `transparent: true`, so Chromium sets a whole-window opaque region (`wl_surface.set_opaque_region`, kept) while the snippet paints it with alpha. At `opacity 1.0` niri believes the opaque region and skips what is behind; at 0.999 it blends the window (a census in a nested niri; no black frame was recorded on Obsidian, see Feishin below for the one that was).
- **Reload:** later theme changes reload live. Quit Obsidian before the first `appglass apply`: the first enable needs an Obsidian restart, or the snippet toggled off and on.
- **Check:** the hidden check stages the vault list (`obsidian.json`, only the vaults under your HOME, with their path, time and open flag), so Obsidian opens the vault and its glass, not the vault chooser. A vault outside your HOME is left out of the list.
- **No vault:** with no vault in `obsidian.json` there is nowhere to put the snippet: the family is skipped and Obsidian shows Fallback until you open a vault and apply again.
- **Undo:** `appglass remove --only obsidian`. A snippet you turn off in Obsidian stays off.

## Herdr

- **Writes:** `themes/appglass.json` (DMS colours as `#rrggbbaa`) and a glass copy of the main layout in Herdr's config folder, selected in `shared.json` (merged, never replaced).
- **Measured:** content 153, sidebar, tab bar and status bar 166, command palette and menus 255. Source: [gpu.md](gpu.md).
- **Reload:** live.
- **Needs:** Herdr started once, so its layouts exist.
- **Undo:** `appglass remove --only herdr`. Selecting another layout in Herdr is an opt-out that appglass keeps.

## Dux Files and Dux Calendar

- **Writes:** four keys merged into each app's `ui-settings.json` (the window transparency keys of the DMS `DCommon` base). No colour file: the apps follow DMS live.
- **Measured:** see [qtquick.md](qtquick.md). Panes are drawn on top of the window, so content cannot be more transparent than the bars: Dux Files uses one level everywhere, Dux Calendar 0.86 panes for its dimmed day numbers. The hidden check takes the calendar's panes as a second level: its floating level stacked on the window, 237 at 0.80 (1 - (1 - 0.80)(1 - 0.65)).
- **Reload:** Dux Files live, Dux Calendar after a restart.
- **Undo:** `appglass remove --only dux` puts the keys back.

## Discord (Vencord)

A Mod route: client mods are against Discord's terms. appglass never installs Vencord and never owns it; you install it with the official installer.

- **Writes:** `~/.config/Vencord/themes/appglass-discord.css` (rendered from the DMS colours and levels), and merges `transparent` and the enabled themes into Vencord's `settings.json`.
- **After a Discord update:** the `appglass-discord.path` unit re-runs the Vencord installer CLI, so the glass comes back. It runs it only from `~/.local/share/appglass/VencordInstallerCli-linux`, and only when that file is executable; nothing else is looked for. The one-line install command from vencord.dev does not keep the installer, so put it there yourself:

  ```sh
  curl -fL -o ~/.local/share/appglass/VencordInstallerCli-linux \
      https://github.com/Vencord/Installer/releases/latest/download/VencordInstallerCli-linux
  chmod +x ~/.local/share/appglass/VencordInstallerCli-linux
  ```

  `.gitignore` keeps it out of the clone's changes. Without it, run the Vencord installer again yourself after each Discord update. That installer patches Discord's own `app-*/resources` folder. The niri rule is written only while Vencord is in the newest Discord folder; otherwise Discord keeps the fallback look.
- **Measured:** not measured in a nested session for this version.
- **Fade, not recorded:** Discord's window shows Discord's web app, which needs a signed-in account. A test session must not reuse your signed-in profile (it holds the account's session), and a fresh profile stops at the login page. What is checked: the rendered theme puts `html:not(.app-focused)` (Discord drops that class when its window loses focus) at the unfocused level and eases `#app-mount` (unit test).
- **Default:** on, live once its hidden check passes. Switch it off in Settings > Apps, or `appglass set apps.vencord.enabled false --apply` without the plugin.
- **Check:** none can run. The Discord client, its Vencord patch and the login live in `~/.config/discord`, which the hidden check does not copy (left alone, the bootstrap would show its zenity updater and download a plain client). So Discord's check is always unverifiable: it goes live only when you switch it on yourself in Settings > Apps (that on is kept, with one "glass could not be checked" notification).
- **Undo:** `appglass remove --only vencord` puts Vencord's settings back. It does not uninstall Vencord.

## Feishin and VSCodium (Electron inspector hook)

Feishin and VSCodium have no CSS hook of their own. This version uses the Node inspector, which their Electron fuses allow. The wrapper starts the app through its normal flatpak command with the inspector on, injects a small hook into the main process, and the hook clears the window background and adds the glass CSS (for VSCodium a workbench stylesheet, plus a marked block in its `settings.json` for the canvas colours).

- **Writes:** `~/.local/lib/appglass/feishin/` (the hook, the injector, the CSS), the wrapper `~/.local/bin/appglass-feishin`, and a launcher override `org.jeffvli.feishin.desktop` that starts the wrapper. VSCodium: the same under `vscodium/`, `appglass-vscodium` and `com.vscodium.codium.desktop`.
- **The port:** the inspector listens on 127.0.0.1 only, on a random port. The port is not listed over HTTP: the session id is read only by the wrapper, from a private (0700) folder, and deleted after the injection. Right after the injection the injector closes the inspector, and checks that the port refuses connections ([engine.md](engine.md#feishin-and-vscodium-the-inspector-port-is-closed-after-the-injection)).
- **Measured:** Feishin on the real desktop at 0.80, background 204, text 255 (see the [issue draft](issue-dms.md#screenshots)); the port gone about 4 s before the screenshot on Feishin 1.17.0. VSCodium (flatpak): 153, text 255 ([apps.md](apps.md)).
- **Fade, recorded:** Feishin 1.17.0 at 0.80 over a coloured background, three runs, under the `opacity 0.999` rule appglass writes for it (below): unfocused, 0.80 to 0.72 in 115 to 135 ms (3 or 4 steps); focused again, back in 65 to 185 ms. How it was started: not through the installed wrapper but from a hand-written command doing what the wrapper does (the app's Electron run bare, outside flatpak, with `--no-sandbox`; the CSS generated and the hook injected through the inspector as the wrapper does).
- **The niri rule is `opacity 0.999`, not 1.0:** Chromium creates the window without `transparent: true`, so it marks the whole window opaque (`wl_surface.set_opaque_region`) while its buffer has alpha, and the hook's clear background comes too late to change that. At `opacity 1.0` niri believes the opaque region and does not draw what is behind the window. Recorded with the DMS blur rule and a 1.0 rule: the fade is right, then about 0.2 s after the window gets focus back (when a neighbour repaints) the whole window shows over black, until Feishin repaints. With `opacity 0.999` niri blends the window and it stays glass, so `appglass.kdl` has a block at `opacity 0.999` for Feishin and VSCodium (Obsidian and the WebKit shim apps join it, for the same reason), after the glass block and before the unfocused one. VSCodium uses the same hook and gets the same rule, but it has no fade: its stylesheet has no unfocused rule, so only "Dim apps that cannot fade" (Settings > Fade) reaches it. The black-window issue was not recorded on it.
- **Default:** on, live once its hidden check passes. Switch it off in Settings > Apps.
- **Undo:** `appglass remove --only feishin` (or `vscodium`). The next launch is the plain app.
TODO(engine): a `NODE_OPTIONS=--require` route needs no port and ranks first where the fuse allows it (Feishin's does); port routes get a "port" badge, and one setting in Settings > Advanced turns them all off.

## Lian Li (WebKitGTK shim)

- **Writes:** `appglass-wk.so` built with `gcc` in `~/.local/lib/appglass/lianli/`, the page CSS, the wrapper `~/.local/bin/appglass-lianli` and a launcher override. The shim is preloaded for that one launch: it clears the WebView background, gives the window an alpha visual and adds the CSS.
- **Measured:** on the real desktop at 0.80, background 204, text 255 (see the [issue draft](issue-dms.md#screenshots)); in a nested niri with its daemon hidden (`tests/e2e/lianli.sh`, Lian Li Linux 1.3.0), content 153 and bars 166. 1.3 paints its main area (`div.main`) over the page background: the CSS clears it, and its empty device list (`div.empty-state`) takes the card level.
- **Fade, not recorded for this version:** the shim sets `html.agl-inactive` on the page when the window loses focus, and the CSS lowers the background with a transition; the rule and the shim's focus hook are unit-tested (`tests/test_fade.py`). An earlier build was recorded at 0.80 (nested niri, three runs, `shots/fade/lianli.fade.txt` in the probe notes): 0.80 to 0.72 in about 115 ms, back in 67 to 151 ms.
- **niri rule `opacity 0.999`:** the same as the generic route below: GTK3 sets the window's opaque region whole (`add(20, 20, 1000, 600)` in a nested niri) whatever the shim paints; the shim clears it and the rule is the second guard.
- **Limit:** the NVIDIA WebKit workarounds (`WEBKIT_DISABLE_DMABUF_RENDERER=1`, `WEBKIT_DISABLE_COMPOSITING_MODE=1`) make a transparent WebView nearly invisible (alpha about 0). See [webkit.md](webkit.md).
- **Default:** on, live once its hidden check passes, but the check cannot judge Lian Li: it hides the daemon (as it must), so Lian Li lays its "Check your installation / Waiting for daemon" dialog and a scrim over the page (background about 202 for 153 on 1.3.0, `tests/e2e/lianli.sh`; 224 for 204 at 0.80). So the check is unverifiable up front (`verify_skip`): no hidden session starts, `appglass status` says "could not be checked", Lian Li stays opaque and its switch in Settings > Apps shows off (a plain marker is written only when its wrapper is already on disk, and it is not a verdict). Switching it on yourself in Settings > Apps (`apps.lianli.enabled` in `settings.json`) makes it glass, and an unverifiable check keeps it so.
- **Undo:** `appglass remove --only lianli`.

## Any WebKitGTK app (generic WebKit shim)

- **Who:** found by its toolkit: a host app whose binary links `libwebkit2gtk-4.x` and `libgtk-3` (Kiri, the Tauri / wry apps). The shim glasses the window only while the WebView is all it draws, looked at again whenever a widget maps or unmaps: with native widgets beside the view (a mail client's folder list, even one shown after the window maps) the window is opaque and the check fails it. A launcher whose command is a script is refused (the preload would not reach the app). Lian Li keeps its own family. Not a flatpak (the host-built preload does not load in its runtime), not WebKitGTK 6 / GTK4 (the shim's window code is GTK3): those keep the fallback, and `appglass status` says why.
- **Writes:** `appglass-wk.so` built with `gcc` in `~/.local/lib/appglass/webkit/`, `webkit-glass.css` (the levels, rendered at every start) and `webkit-glass.js`, the wrapper `~/.local/bin/appglass-webkit` and one launcher override per app (`Exec=appglass-webkit <key> <its Exec>`).
- **How:** the same shim as Lian Li; the page script reads the page's own colours: the page colour at the content level, large boxes of another colour (sidebars, headers, status bars, cards) at the bar level, popups (dialogs, menus, listboxes, tooltips, floating boxes) left opaque, text never touched. See [webkit.md](webkit.md#the-generic-route-family-webkit).
- **Measured:** Kiri 0.2.1 in a nested niri, measured on its setup screen (no engine in the harness): content 153, bars 166, text 255, its language dialog 255; at 0.80, 204 focused and 184 unfocused.
- **niri rule `opacity 0.999`, opaque region cleared:** GTK3 sets the window's opaque region to the whole window from its opaque CSS background (at its realize, each resize and each style change, app-paintable or not), so with the glass painted in it the window said it was opaque. At `opacity 1.0` niri believed it and skipped what is behind: the background flickered as the windows below repainted. Recorded on Kiri in a nested niri, over a window that repaints: at 1.0, 0 of 79 frames changed behind it; at 0.999, 72 of 79. The shim now clears the region of a glass window after GTK each time (`gdk_window_set_opaque_region(window, NULL)`; at 1.0, 71 of 79 frames changed behind it, and resizes and focus changes sent no region again), and `appglass.kdl` blends the family at 0.999 as well. Until the page first paints, the window is not glass yet (it keeps its own opaque background, see [webkit.md](webkit.md)), so it keeps GTK's whole region, which is true then: in a nested niri census Kiri sent the whole region at map and cleared it about 4.5 s later, Lian Li about 4.8 s after map. The 0.999 rule covers that switch too.
- **Check:** with no network and the `/run` entries its binaries name hidden. Kiri's passes in `tests/e2e/webkit.sh` (it waits at default settings, `appglass verify kiri` passes, the next apply gives it the glass); no other WebKitGTK app was checked.
- **Default:** on, live per app once its hidden check passes. Switching an app on yourself makes it glass at once, until its queued check runs: a failed check makes it opaque again, whatever the switch says. Switch an app off in Settings > Apps.
- **Undo:** `appglass remove --only webkit`. The next launch is the plain app.

## Jellyfin (Qt Quick shim)

- **Writes:** `libjfglass.so` built with the host Qt 6 in `~/.local/lib/appglass/jellyfin/`, the CSS, the wrapper and a launcher override. The shim is preloaded into the main process only. It gives the window an alpha channel, clears the web view background and shows the video layer only while a video plays.
- **Measured:** in an isolated session at 0.80, the home page background 204 and text 255; a playing, paused or OSD video stays 255, popups 255.
- **Fade, recorded:** Jellyfin Desktop 2.0.0 at 0.80 on its server address page (no server, no network), three runs: unfocused, the change starts 160 to 240 ms after the focus change and takes 50 to 117 ms (2 steps); focused again, back to 0.80 in about 270 ms (4 to 6 steps). How it was started: a hand-written `flatpak run` command doing what the wrapper's `Exec` does (the shim preloaded, the lib folder passed read-only), plus no network, no document portal and the QtWebEngine sandbox off for the harness, not the installed wrapper.
- **Needs:** `g++` and host Qt 6.11 or newer (the shim is built with the host Qt and loaded into the flatpak). A runtime update rebuilds the shim.
- **Default:** on, live once its hidden check passes. Switch it off in Settings > Apps.
- **Undo:** `appglass remove --only jellyfin`.

## LocalSend and ArtCraft (colour-key shim)

Flutter and egui apps draw everything themselves into one surface. The shim replaces the app's own background colours (known keys) with the same colour at the glass level, and leaves every other pixel, text included, untouched.

- **Writes:** `appglass-ck.so` built with `gcc`, the wrapper (`appglass-localsend`, `appglass-artcraft`) and a launcher override. For LocalSend (flatpak) the lib folder is passed read-only for that run only, with no `flatpak override`. ArtCraft also gets the Vulkan layer `VK_LAYER_APPGLASS_glass` and its device probe in `~/.local/lib/appglass/artcraft/vk/` (nothing in the system or user Vulkan layer folders).
- **ArtCraft's routes:** the wrapper picks one at every start ([artcraft-gpu.md](artcraft-gpu.md#install-and-routes)):

  | Route | When | What it does |
  |---|---|---|
  | GPU | the layer is installed and the probe finds a Vulkan device that is not the CPU | wgpu stays on Vulkan; the layer asks for a premultiplied swapchain and runs the colour keys on the GPU; no frame cap |
  | CPU | `APPGLASS_ARTCRAFT=cpu`, no layer (it did not build), or only llvmpipe, no device or a probe that fails; Mesa EGL installed | Mesa EGL with wgpu's GL backend on llvmpipe (software rendering), the colour keys, swaps capped at 60 fps |
  | plain | `APPGLASS_ARTCRAFT=off`, the check not passed yet (waiting, stale, paused), a light system theme, no keys, or neither route possible | the launcher as it ships, opaque |

  `appglass status`, `doctor` and the plugin's app row say which route it takes and why.
- **Measured:** LocalSend on the real desktop at 0.80: background 204, text 255. ArtCraft at 0.80 on the CPU route: background 204, text 255. ArtCraft 0.19.2 in the headless harness at 0.60, both routes: content 153, bar 166, text 255; scrolling costs about 25 times less CPU on the GPU route at 60 Hz ([artcraft-gpu.md](artcraft-gpu.md#the-installed-family-headless-harness)). See [flutter.md](flutter.md), [gpu.md](gpu.md) and the [issue draft](issue-dms.md#screenshots).
- **Fade, recorded:** LocalSend 1.18.2 at 0.80 (light theme), three runs: no fade, the background stays 0.80 focused and unfocused. The shim has no focus lever; only "Dim apps that cannot fade" reaches it. Started from a hand-written `flatpak run` command doing what the wrapper's `Exec` does, not the installed wrapper.
- **Fade, ArtCraft:** none, on both routes. Neither the Vulkan layer nor the CPU shim has a focus lever; only "Dim apps that cannot fade" reaches it. Not recorded in a session.
- **Limit:** the colour keys are per app and per light/dark theme. A colour that is not a key stays opaque: a miss fails safe, it never fades text.
- **Keys:** the keys are data, one file per app version and dark or light mode (`~/.cache/appglass/keys/`), read by the wrapper through `appglass keys`, so an update or a theme flip needs no wrapper edit.
- **Default:** on, live once its hidden check passes. Switch it off in Settings > Apps.
- **Undo:** `appglass remove --only localsend,artcraft`.

TODO(adapters): colour keys learned from a hidden capture, for apps with no hand-made keys. The learner exists (`python3 -m appglass.keylearn`, measured by hand on Saber and Sublime Text in [apps.md](apps.md)), but no family uses learned keys yet.

## Opaque

With the default fallback ("Opaque", Settings > Fallback), these windows get `opacity 1.0`: opaque and sharp.

- **Steam (the client window).** Steam stays opaque because no official way gives its window an alpha channel, and appglass does not inject code into Steam (its children are games). Two official routes were measured on the real client:
  - the CEF flags for underlays, with the page background made transparent through the CEF debugger: the page was transparent, the window still alpha 255 everywhere, also with GPU compositing off;
  - Steam's GL composer option: the main window and menus always use Steam's system composer, which prints "transparent background not supported"; the GL composer is only used for toasts. With `-cef-disable-xcomposite-workaround` the window was still alpha 255 everywhere.

  Steam games are never touched either way.

  `appglass status` lists Steam with no route, and Settings > Apps gives it no switch: the reason reads "Steam client (CEF): no injection, it stays opaque". Only the niri fallback reaches it.
- **Chrome and Chromium browsers.** Web content has no window alpha: measured alpha 255 everywhere. See [electron.md](electron.md).
- **Games, Wine/Proton, SDL.** Opaque with blur off, on purpose. Nothing runs inside a game process. A host GTK4 game is the exception: every host GTK4 app reads the global `gtk.css`, so it gets the glass background like the other GTK4 apps. `apply --all` puts its app-id in the niri glass block (opacity 1.0, blur on), not the games block (blur off would leave that translucent background over nothing), whatever `fallback.mode` is: under the DMS opacity it would fade twice.
- **Root GUIs** (Timeshift through pkexec): opaque, with the reason "runs as root". No file, launcher or environment variable is written for them; `apply --all` puts their app-id in the niri games block (opacity 1.0, blur off), so they stay opaque whatever `fallback.mode` is.
- **Electron apps without a CSS hook**, Java, Tk, X11 apps of other toolkits (a Qt app under XWayland gets the Qt route: VLC was measured that way), Qt from a flatpak KDE runtime (Kate and Konsole excepted): no route in this version.

Settings > Fallback can make Steam, Chrome, Electron apps without a CSS hook, Java, Tk and X11 apps of other toolkits translucent instead ("Translucent (text too)", at the Fallback opacity, 0.70 by default) or leave them at the DMS opacity ("DMS opacity"). Both fade the text with the background. Games, root GUIs and Qt flatpaks on the KDE runtime stay opaque in every mode.
