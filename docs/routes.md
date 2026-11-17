# Routes: how each kind of app gets its glass

A route is the way one kind of app is made to paint its own background with alpha. Every route has the same target, from the DMS level ([engine.md](engine.md#the-levels)):

- content at the level (alpha 153 at 0.60);
- bars at `max(content, 0.65)` (alpha 166 at 0.60);
- popups at 1.0;
- text at 255.

Every route also adds the app's app-id to the `opacity 1.0` rule in `~/.config/niri/appglass.kdl`. Every route is undone by switching its family off, with the family name from the table below: `dms ipc call appGlass app <family> off` while the plugin is installed and enabled (for example `dms ipc call appGlass app gtk3 off`), or `appglass set apps.<family>.enabled false --apply` without it. `appglass remove --only <family>` takes the files out too, but only until the next sync or `appglass apply --all` while the family is still on in settings. The switch in Settings > Apps takes the files out only for a Forced or Mod app; for a Native app it shows Paused and the files stay (see [guide.md](guide.md#per-app-switch)). A Forced or Mod route is on by default, but goes live only once its hidden check passes ([engine.md](engine.md#the-gate-glass-waiting-stale-opaque-off-excluded)).

The "Measured" lines come from window screenshots taken in a nested niri session (or, where noted, on the real desktop), with the alpha read per pixel. "0.80" means the measurement was taken at a DMS level of 0.80, where the content target is alpha 204. The per-toolkit pages have the full results.

The app lists below name the apps each family lists by hand. The GTK3, GTK4 and Qt routes also take any app of their toolkit that the engine finds ([engine.md](engine.md#routes-by-toolkit)). The full matrix, with the measured result per app, is in [apps.md](apps.md).

TODO(adapters): a generic Electron route through `NODE_OPTIONS`, for Electron apps no family lists.

| Route | Badge | Family | Apps | Default |
|---|---|---|---|---|
| [Terminal opacity key](#terminals) | Native | `alacritty`, `kitty`, `foot`, `ghostty`, `wezterm`, `konsole` | Alacritty, kitty, foot, Ghostty, WezTerm, Konsole | on |
| [GTK4 CSS](#gtk4--libadwaita) | Native | `gtk4` | Nautilus, GNOME Software, Zenity, the file chooser portal, Flatseal (native package), GNOME Web (chrome only); flatpaks: GNOME Text Editor, Mission Center, Resources; any other GTK4 app | on |
| [GTK3 theme](#gtk3) | Native | `gtk3` | Solaar, nvidia-settings, any other host GTK3 app | on |
| [Qt style plugin](#qt-widgets-vlc-kate-konsole) | Native | `qtstyle` | VLC, Kate and Konsole (flatpak), any other host Qt 6 Widgets app | on |
| [App config](#kate-mpv-gimp-zed) | Native | `kate`, `mpv`, `gimp`, `zed` | Kate (editor theme), mpv, GIMP 3, Zed | on |
| [Obsidian snippet](#obsidian) | Native | `obsidian` | Obsidian | on |
| [Herdr theme](#herdr) | Native | `herdr` | Herdr | on |
| [Dux keys](#dux-files-and-dux-calendar) | Native | `dux` | Dux Files, Dux Calendar | on |
| [Vencord theme](#discord-vencord) | Mod | `vencord` | Discord with Vencord | on, after its check |
| [Electron inspector hook](#feishin-and-vscodium-electron-inspector-hook) | Forced | `feishin`, `vscodium` | Feishin, VSCodium | on, after its check |
| [WebKit shim](#lian-li-webkitgtk-shim) | Forced | `lianli` | Lian Li Linux | on, after its check |
| [Qt Quick shim](#jellyfin-qt-quick-shim) | Forced | `jellyfin` | Jellyfin Desktop | on, after its check |
| [Colour-key shim](#localsend-and-artcraft-colour-key-shim) | Forced | `localsend`, `artcraft` | LocalSend, ArtCraft Launcher | on, after its check |
| [Opaque](#opaque) | | | Steam, Chrome, games, everything else | |

## Terminals

### Alacritty

- **Writes:** `~/.config/alacritty/appglass.toml` (`[window] opacity` = content, plus palette fixes), imported right after `dank-theme.toml` in your `alacritty.toml`. The main file's own `opacity` line is commented out, because the main file wins over every import.
- **Text:** the palette entries that are too faint on glass (DMS black, magenta, bright black, dim colours) are moved toward white on a dark scheme, toward black on a light one, until text reaches 2.25:1 over any backdrop.
- **Measured:** before, under the DMS rule alone, every pixel of the window, text included, is alpha 153. After, the background is 153 and the text 255. Source: [terminal.md](terminal.md).
- **Reload:** live.
- **Undo:** `appglass remove --only alacritty` restores `alacritty.toml` byte for byte.

### kitty, foot, Ghostty, WezTerm, Konsole

- **Writes:** an owned file at the content level with the DMS palette made readable on glass, included by the main config (edited, backed up): kitty `appglass.conf` (`background_opacity`), foot `appglass.ini` (`alpha`), Ghostty `appglass` (`background-opacity`), WezTerm `appglass.lua` (`window_background_opacity`, the tab bar at the bar level), Konsole an `AppGlass` colour scheme and profile (`Opacity`). The flatpak builds of foot, WezTerm and Konsole get the same in their `~/.var/app/<id>` folder. Konsole's tabs and menus take the Qt style (below).
- **Measured:** foot (flatpak) background 153, text 255; Konsole (flatpak) background 153, text 255, popups 255. kitty, Ghostty and WezTerm are not measured here: the writers are unit-tested only. Source: [apps.md](apps.md).
- **Undo:** `appglass remove --only kitty` (or `foot`, `ghostty`, `wezterm`, `konsole`) takes the include out.

## GTK4 / libadwaita

- **Writes:** `~/.config/gtk-4.0/dank-glass.css` (alpha on the background colour roles, from the DMS colours), and adds `@import url("dank-glass.css");` after the DMS import in `~/.config/gtk-4.0/gtk.css`.
- **Apps:** `gtk.css` is read by every GTK4 app, so the niri rule lists every GTK4 app appglass knows: Nautilus, GNOME Software, Zenity, the GNOME file chooser portal (used by Chrome and Electron apps), Flatseal (native package), GNOME Web, the libadwaita demo. GNOME Web is partial: its chrome is glass, the web page stays opaque.
- **Measured:** Nautilus content 153, sidebar 166, popovers and dialogs 255, text 255. Source: [gtk4.md](gtk4.md).
- **Reload:** GTK4 reads the CSS at start: restart the app.
- **Undo:** `appglass remove --only gtk4` takes the import out and deletes `gtk.css` when nothing of yours is left in it. Taking the import out by hand, or deleting `gtk.css`, is an opt-out that appglass keeps.
- **Flatpaks:** flatpak GTK4 apps do not read the host `gtk-4.0` folder. GNOME Text Editor, Mission Center and Resources get the same files in their own `~/.var/app/<id>/config/gtk-4.0`. Any other GTK4 flatpak the engine finds gets a launcher override that gives that launch read-only access to the host `gtk-4.0` folder; no `flatpak override` is written. Measured: GNOME Text Editor 153, Mission Center 153, Resources 153, text and popups 255 ([apps.md](apps.md)).

## GTK3

- **Writes:** a per-app theme, `~/.local/share/themes/AppGlass/gtk-3.0/gtk.css` (Adwaita, then `dank-colors.css`, then the glass rules), launcher overrides in `~/.local/share/applications/` that start the app with `GTK_THEME=AppGlass`, and `~/.config/autostart/solaar.desktop` with the same change, because Solaar is started at login from the system autostart file (an autostart file you already had is edited, backed up). There is no global `gtk-3.0/gtk.css`, so other GTK3 apps are not affected.
- **Apps:** Solaar, nvidia-settings, and every other host GTK3 app the engine finds (an app that starts other apps, a root GUI or a password manager excepted, see [engine.md](engine.md#classes-what-is-never-touched)).
- **Measured:** Solaar content 153 (0.600), header bar and bars 166 (0.651), menus 255, glyph cores 255. Source: [gtk3.md](gtk3.md).
- **Reload:** restart the app (Solaar is a tray process: quit it first).
- **Undo:** `appglass remove --only gtk3`. A launcher override you already had is edited, backed up and restored byte for byte.
- **Limit:** started from a shell, the app does not get `GTK_THEME` and keeps the fallback look.

## Qt Widgets (VLC, Kate, Konsole)

- **Writes:** a Qt 6 style plugin built from source with the host Qt, `~/.local/lib/appglass/qt6/styles/libappglass.so`, and a launcher override `~/.local/share/applications/vlc.desktop` that starts VLC with `QT_STYLE_OVERRIDE=appglass`, the same for every other host Qt 6 Widgets app the engine finds. Nothing is preloaded: Qt loads the style itself, and takes its variables out of the environment of the processes the app starts.
- **Kate and Konsole (flatpak):** their launcher override gives that `flatpak run` read-only access to the style and the DMS colours. The host-built style loads in the KDE runtime when its Qt minor version matches.
- **Fade:** an unfocused window eases its background to the unfocused level, in the flatpaks and in the apps the engine finds too.
- **Fade, recorded:** VLC 3.0.24 (under XWayland) at 0.80, 180 ms ease-out, three runs: unfocused, the background went 0.80 to 0.72 in about 110 ms, one step per frame (7 steps; the end of the ease-out is under one 8-bit step); focused again, back to 0.80 in 120 to 180 ms (2 or 3 steps).
- **Measured:** content 153, bars 166, text 255. Source: [qt.md](qt.md).
- **Needs:** `g++` and the Qt 6 headers. A Qt update rebuilds the plugin.
- **Undo:** `appglass remove --only qtstyle`.
- **Limit:** Qt 5 apps cannot load a Qt 6 plugin, and other flatpak apps on the KDE runtime are not routed (the Qt minor version must match): they keep the fallback look.

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
- **Reload:** later theme changes reload live. Quit Obsidian before the first `appglass apply`: the first enable needs an Obsidian restart, or the snippet toggled off and on.
- **Undo:** `appglass remove --only obsidian`. A snippet you turn off in Obsidian stays off.

## Herdr

- **Writes:** `themes/appglass.json` (DMS colours as `#rrggbbaa`) and a glass copy of the main layout in Herdr's config folder, selected in `shared.json` (merged, never replaced).
- **Measured:** content 153, sidebar, tab bar and status bar 166, command palette and menus 255. Source: [gpu.md](gpu.md).
- **Reload:** live.
- **Needs:** Herdr started once, so its layouts exist.
- **Undo:** `appglass remove --only herdr`. Selecting another layout in Herdr is an opt-out that appglass keeps.

## Dux Files and Dux Calendar

- **Writes:** four keys merged into each app's `ui-settings.json` (the window transparency keys of the DMS `DCommon` base). No colour file: the apps follow DMS live.
- **Measured:** see [qtquick.md](qtquick.md). Panes are drawn on top of the window, so content cannot be more transparent than the bars: Dux Files uses one level everywhere, Dux Calendar 0.86 panes for its dimmed day numbers.
- **Reload:** Dux Files live, Dux Calendar after a restart.
- **Undo:** `appglass remove --only dux` puts the keys back.

## Discord (Vencord)

A Mod route: client mods are against Discord's terms. appglass never installs Vencord and never owns it; you install it with the official installer.

- **Writes:** `~/.config/Vencord/themes/appglass-discord.css` (rendered from the DMS colours and levels), and merges `transparent` and the enabled themes into Vencord's `settings.json`.
- **After a Discord update:** the `appglass-discord.path` unit re-runs the Vencord installer, so the glass comes back. That installer patches Discord's own `app-*/resources` folder. The niri rule is written only while Vencord is in the newest Discord folder; otherwise Discord keeps the fallback look.
- **Measured:** not measured in a nested session for this version.
- **Fade, not recorded:** Discord's window shows Discord's web app, which needs a signed-in account. A test session must not reuse your signed-in profile (it holds the account's session), and a fresh profile stops at the login page. What is checked: the rendered theme puts `html:not(.app-focused)` (Discord drops that class when its window loses focus) at the unfocused level and eases `#app-mount` (unit test).
- **Default:** on, live once its hidden check passes. Switch it off in Settings > Apps, or `appglass set apps.vencord.enabled false --apply` without the plugin.
- **Undo:** `appglass remove --only vencord` puts Vencord's settings back. It does not uninstall Vencord.

## Feishin and VSCodium (Electron inspector hook)

Feishin and VSCodium have no CSS hook of their own. This version uses the Node inspector, which their Electron fuses allow. The wrapper starts the app through its normal flatpak command with the inspector on, injects a small hook into the main process, and the hook clears the window background and adds the glass CSS (for VSCodium a workbench stylesheet, plus a marked block in its `settings.json` for the canvas colours).

- **Writes:** `~/.local/lib/appglass/feishin/` (the hook, the injector, the CSS), the wrapper `~/.local/bin/appglass-feishin`, and a launcher override `org.jeffvli.feishin.desktop` that starts the wrapper. VSCodium: the same under `vscodium/`, `appglass-vscodium` and `com.vscodium.codium.desktop`.
- **The port:** the inspector listens on 127.0.0.1 only, on a random port. The port is not listed over HTTP: the session id is read only by the wrapper, from a private (0700) folder, and deleted after the injection. Right after the injection the injector closes the inspector, and checks that the port refuses connections ([engine.md](engine.md#feishin-and-vscodium-the-inspector-port-is-closed-after-the-injection)).
- **Measured:** Feishin on the real desktop at 0.80, background 204, text 255 (see the [issue draft](issue-dms.md#screenshots)); the port gone about 4 s before the screenshot on Feishin 1.17.0. VSCodium (flatpak): 153, text 255 ([apps.md](apps.md)).
- **Fade, recorded:** Feishin 1.17.0 at 0.80 over a coloured background, three runs (with the `opacity 0.999` below): unfocused, 0.80 to 0.72 in 115 to 135 ms (3 or 4 steps); focused again, back in 70 to 185 ms.
- **Known issue, the window can go dark:** Chromium creates the window without `transparent: true`, so it marks the whole window opaque (`wl_surface.set_opaque_region`) while its buffer has alpha, and the hook's clear background comes too late to change that. At the glass rule's `opacity 1.0` niri believes the opaque region and does not draw what is behind the window. Recorded with the DMS blur rule and the glass rule: the fade is right, then about 0.2 s after the window gets focus back (when a neighbour repaints) the whole window shows over black, until Feishin repaints. With `opacity 0.999` for Feishin niri blends the window and it stays glass.
- **Default:** on, live once its hidden check passes. Switch it off in Settings > Apps.
- **Undo:** `appglass remove --only feishin` (or `vscodium`). The next launch is the plain app.
TODO(engine): opaque region: write `opacity 0.999` for the Electron hook apps in the niri glass rule, or make the hook create the window transparent.
TODO(engine): a `NODE_OPTIONS=--require` route needs no port and ranks first where the fuse allows it (Feishin's does); port routes get a "port" badge, and one setting in Settings > Advanced turns them all off.

## Lian Li (WebKitGTK shim)

- **Writes:** `appglass-wk.so` built with `gcc` in `~/.local/lib/appglass/lianli/`, the page CSS, the wrapper `~/.local/bin/appglass-lianli` and a launcher override. The shim is preloaded for that one launch: it clears the WebView background, gives the window an alpha visual and adds the CSS.
- **Measured:** on the real desktop at 0.80, background 204, text 255 (see the [issue draft](issue-dms.md#screenshots)).
- **Limit:** the NVIDIA WebKit workarounds (`WEBKIT_DISABLE_DMABUF_RENDERER=1`, `WEBKIT_DISABLE_COMPOSITING_MODE=1`) make a transparent WebView nearly invisible (alpha about 0). See [webkit.md](webkit.md).
- **Default:** on, live once its hidden check passes. Switch it off in Settings > Apps.
- **Undo:** `appglass remove --only lianli`.

## Jellyfin (Qt Quick shim)

- **Writes:** `libjfglass.so` built with the host Qt 6 in `~/.local/lib/appglass/jellyfin/`, the CSS, the wrapper and a launcher override. The shim is preloaded into the main process only. It gives the window an alpha channel, clears the web view background and shows the video layer only while a video plays.
- **Measured:** in an isolated session at 0.80, the home page background 204 and text 255; a playing, paused or OSD video stays 255, popups 255.
- **Fade, recorded:** Jellyfin Desktop 2.0.0 at 0.80 on its server address page (no server, no network), three runs: unfocused, the change starts 160 to 240 ms after the focus change and takes 50 to 115 ms (2 steps); focused again, back to 0.80 in about 270 ms (4 to 6 steps).
- **Needs:** `g++` and host Qt 6.11 or newer (the shim is built with the host Qt and loaded into the flatpak). A runtime update rebuilds the shim.
- **Default:** on, live once its hidden check passes. Switch it off in Settings > Apps.
- **Undo:** `appglass remove --only jellyfin`.

## LocalSend and ArtCraft (colour-key shim)

Flutter and egui apps draw everything themselves into one surface. The shim replaces the app's own background colours (known keys) with the same colour at the glass level, and leaves every other pixel, text included, untouched.

- **Writes:** `appglass-ck.so` built with `gcc`, the wrapper (`appglass-localsend`, `appglass-artcraft`) and a launcher override. For LocalSend (flatpak) the lib folder is passed read-only for that run only, with no `flatpak override`. ArtCraft is moved to Mesa EGL with wgpu's GL backend, which renders on the CPU (software rendering, llvmpipe), and its swaps are capped at 60 fps.
- **Measured:** LocalSend on the real desktop at 0.80: background 204, text 255. ArtCraft at 0.80: background 204, text 255. See [flutter.md](flutter.md), [gpu.md](gpu.md) and the [issue draft](issue-dms.md#screenshots).
- **Fade, recorded:** LocalSend 1.18.2 at 0.80 (light theme), three runs: no fade, the background stays 0.80 focused and unfocused. The shim has no focus lever; only "Dim apps that cannot fade" reaches it.
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

  TODO(adapters): `appglass status` still lists Steam with an old Forced route, `steam-cdp`, and Settings > Apps gives it a switch. That switch does nothing: on or off, the reason reads "Steam client (CEF): no injection, it stays opaque" and Steam stays opaque. The route is to be dropped from the catalogue.
- **Chrome and Chromium browsers.** Web content has no window alpha: measured alpha 255 everywhere. See [electron.md](electron.md).
- **Games, Wine/Proton, SDL.** Opaque with blur off, on purpose. Nothing runs inside a game process.
- **Root GUIs** (Timeshift through pkexec): opaque, with the reason "runs as root". Nothing is written for them.
- **Electron apps without a CSS hook**, Java, Tk, X11 apps that are not GTK, Qt from a flatpak KDE runtime (Kate and Konsole excepted): no route in this version.

Settings > Fallback can make these windows translucent instead ("Translucent (text too)", at the Fallback opacity, 0.70 by default) or leave them at the DMS opacity ("DMS opacity"). Both fade the text with the background.
