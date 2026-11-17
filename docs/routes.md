# Routes: how each kind of app gets its glass

A route is the way one kind of app is made to paint its own background with alpha. Every route has the same target, from the DMS level ([engine.md](engine.md#the-levels)):

- content at the level (alpha 153 at 0.60);
- bars at `max(content, 0.65)` (alpha 166 at 0.60);
- popups at 1.0;
- text at 255.

Every route also adds the app's app-id to the `opacity 1.0` rule in `~/.config/niri/appglass.kdl`. Every route is undone by switching its family off, with the family name from the table below: `dms ipc call appGlass app <family> off` while the plugin is installed (for example `dms ipc call appGlass app gtk3 off`), or `appglass set apps.<family>.enabled false --apply` without it. `appglass remove --only <family>` takes the files out too, but only until the next sync or `appglass apply --all` while the family is still on in settings. The switch in Settings > Apps takes the files out only for a Forced or Mod app; for a Native app it shows Paused and the files stay (see [guide.md](guide.md#per-app-switch)).

The "Measured" lines come from window screenshots taken in a nested niri session (or, where noted, on the real desktop), with the alpha read per pixel. "0.80" means the measurement was taken at a DMS level of 0.80, where the content target is alpha 204. The per-toolkit pages have the full results.

TODO(adapters): the app list of each route below is the list in this version. Routes are being made generic (any GTK3 app, any Qt Widgets app, any terminal, Electron apps through `NODE_OPTIONS`); this page and the README app table will follow.

| Route | Badge | Family | Apps | Default |
|---|---|---|---|---|
| [Terminal opacity key](#terminal-alacritty) | Native | `alacritty` | Alacritty | on |
| [GTK4 CSS](#gtk4--libadwaita) | Native | `gtk4` | Nautilus, GNOME Software, Zenity, the file chooser portal, Flatseal (native package), GNOME Web (chrome only) | on |
| [GTK3 theme](#gtk3) | Native | `gtk3` | Solaar, nvidia-settings | on |
| [Qt style plugin](#qt-widgets-vlc) | Native | `qtstyle` | VLC | on |
| [Obsidian snippet](#obsidian) | Native | `obsidian` | Obsidian | on |
| [Herdr theme](#herdr) | Native | `herdr` | Herdr | on |
| [Dux keys](#dux-files-and-dux-calendar) | Native | `dux` | Dux Files, Dux Calendar | on |
| [Vencord theme](#discord-vencord) | Mod | `vencord` | Discord with Vencord | off |
| [Electron inspector hook](#feishin-electron-inspector-hook) | Forced | `feishin` | Feishin | off |
| [WebKit shim](#lian-li-webkitgtk-shim) | Forced | `lianli` | Lian Li Linux | off |
| [Qt Quick shim](#jellyfin-qt-quick-shim) | Forced | `jellyfin` | Jellyfin Desktop | off |
| [Colour-key shim](#localsend-and-artcraft-colour-key-shim) | Forced | `localsend`, `artcraft` | LocalSend, ArtCraft Launcher | off |
| [Opaque](#opaque) | | | Steam, Chrome, games, everything else | |

## Terminal (Alacritty)

- **Writes:** `~/.config/alacritty/appglass.toml` (`[window] opacity` = content, plus palette fixes), imported right after `dank-theme.toml` in your `alacritty.toml`. The main file's own `opacity` line is commented out, because the main file wins over every import.
- **Text:** the palette entries that are too faint on glass (DMS black, magenta, bright black, dim colours) are moved toward white on a dark scheme, toward black on a light one, until text reaches 2.25:1 over any backdrop.
- **Measured:** before, under the DMS rule alone, every pixel of the window, text included, is alpha 153. After, the background is 153 and the text 255. Source: [terminal.md](terminal.md).
- **Reload:** live.
- **Undo:** `appglass remove --only alacritty` restores `alacritty.toml` byte for byte.

TODO(adapters): kitty, foot, Ghostty and WezTerm through their own opacity keys.

## GTK4 / libadwaita

- **Writes:** `~/.config/gtk-4.0/dank-glass.css` (alpha on the background colour roles, from the DMS colours), and adds `@import url("dank-glass.css");` after the DMS import in `~/.config/gtk-4.0/gtk.css`.
- **Apps:** `gtk.css` is read by every GTK4 app, so the niri rule lists every GTK4 app appglass knows: Nautilus, GNOME Software, Zenity, the GNOME file chooser portal (used by Chrome and Electron apps), Flatseal (native package), GNOME Web, the libadwaita demo. GNOME Web is partial: its chrome is glass, the web page stays opaque.
- **Measured:** Nautilus content 153, sidebar 166, popovers and dialogs 255, text 255. Source: [gtk4.md](gtk4.md).
- **Reload:** GTK4 reads the CSS at start: restart the app.
- **Undo:** `appglass remove --only gtk4` takes the import out and deletes `gtk.css` when nothing of yours is left in it. Taking the import out by hand, or deleting `gtk.css`, is an opt-out that appglass keeps.
- **Limit:** flatpak GTK4 apps do not read the host `gtk-4.0` folder, so they are not listed.

## GTK3

- **Writes:** a per-app theme, `~/.local/share/themes/AppGlass/gtk-3.0/gtk.css` (Adwaita, then `dank-colors.css`, then the glass rules), launcher overrides in `~/.local/share/applications/` that start the app with `GTK_THEME=AppGlass`, and `~/.config/autostart/solaar.desktop` with the same change, because Solaar is started at login from the system autostart file (an autostart file you already had is edited, backed up). There is no global `gtk-3.0/gtk.css`, so other GTK3 apps are not affected.
- **Apps:** Solaar, nvidia-settings.
- **Measured:** Solaar content 153 (0.600), header bar and bars 166 (0.651), menus 255, glyph cores 255. Source: [gtk3.md](gtk3.md).
- **Reload:** restart the app (Solaar is a tray process: quit it first).
- **Undo:** `appglass remove --only gtk3`. A launcher override you already had is edited, backed up and restored byte for byte.
- **Limit:** started from a shell, the app does not get `GTK_THEME` and keeps the fallback look.

## Qt Widgets (VLC)

- **Writes:** a Qt 6 style plugin built from source with the host Qt, `~/.local/lib/appglass/qt6/styles/libappglass.so`, and a launcher override `~/.local/share/applications/vlc.desktop` that starts VLC with `QT_STYLE_OVERRIDE=appglass`. Nothing is preloaded: Qt loads the style itself.
- **Measured:** content 153, bars 166, text 255. Source: [qt.md](qt.md).
- **Needs:** `g++` and the Qt 6 headers. A Qt update rebuilds the plugin.
- **Undo:** `appglass remove --only qtstyle`.
- **Limit:** Qt 5 apps and flatpak apps on the KDE runtime cannot load a host Qt 6 plugin: they keep the fallback look.

## Obsidian

- **Writes:** `<vault>/.obsidian/snippets/appglass.css` in every vault listed in Obsidian's `obsidian.json`, and turns the snippet on in that vault's `appearance.json` (your other snippets and keys are kept).
- **Measured:** content 153, ribbon, sidebars and tab bar 166, menus and modals 255, text 255; the stock `--text-faint` (under 2:1) is replaced. Source: [electron.md](electron.md).
- **Reload:** later theme changes reload live. The first enable needs an Obsidian restart, or the snippet toggled off and on.
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
- **Turn on:** Settings > Apps (asks first), or `appglass set apps.vencord.enabled true --apply`.
- **Undo:** `appglass remove --only vencord` puts Vencord's settings back. It does not uninstall Vencord.

## Feishin (Electron inspector hook)

Feishin has no CSS hook of its own. This version uses the Node inspector, which Feishin's Electron fuses allow. The wrapper starts Feishin through its normal flatpak command with the inspector on, injects a small hook into the main process, and the hook clears the window background and adds the glass CSS.

- **Writes:** `~/.local/lib/appglass/feishin/` (the hook, the injector, the CSS), the wrapper `~/.local/bin/appglass-feishin`, and a launcher override `org.jeffvli.feishin.desktop` that starts the wrapper.
- **The port:** the inspector listens on 127.0.0.1 only, on a random port. The port is not listed over HTTP: the session id is read only by the wrapper, from a private (0700) folder, and deleted after the injection. In this version the port stays open while Feishin runs. This is why the route is Forced and off by default.
- **Measured:** on the real desktop at 0.80, background 204, text 255 (see the [issue draft](issue-dms.md#screenshots)).
- **Turn on:** Settings > Apps (asks first), or `appglass set apps.feishin.enabled true --apply`.
- **Undo:** `appglass remove --only feishin`. The next launch is the plain Feishin.

TODO(adapters): close the inspector right after the injection when Electron allows it, and keep 127.0.0.1 with a random port only when it does not. Not measured yet.
TODO(engine): a `NODE_OPTIONS=--require` route needs no port and ranks first where the fuse allows it (Feishin's does); port routes get a "port" badge, and one setting in Settings > Advanced turns them all off.

## Lian Li (WebKitGTK shim)

- **Writes:** `appglass-wk.so` built with `gcc` in `~/.local/lib/appglass/lianli/`, the page CSS, the wrapper `~/.local/bin/appglass-lianli` and a launcher override. The shim is preloaded for that one launch: it clears the WebView background, gives the window an alpha visual and adds the CSS.
- **Measured:** on the real desktop at 0.80, background 204, text 255 (see the [issue draft](issue-dms.md#screenshots)).
- **Limit:** the NVIDIA WebKit workarounds (`WEBKIT_DISABLE_DMABUF_RENDERER=1`, `WEBKIT_DISABLE_COMPOSITING_MODE=1`) make a transparent WebView nearly invisible (alpha about 0). See [webkit.md](webkit.md).
- **Turn on:** `appglass set apps.lianli.enabled true --apply` or Settings > Apps.
- **Undo:** `appglass remove --only lianli`.

## Jellyfin (Qt Quick shim)

- **Writes:** `libjfglass.so` built with the host Qt 6 in `~/.local/lib/appglass/jellyfin/`, the CSS, the wrapper and a launcher override. The shim is preloaded into the main process only. It gives the window an alpha channel, clears the web view background and shows the video layer only while a video plays.
- **Measured:** in an isolated session at 0.80, the home page background 204 and text 255; a playing, paused or OSD video stays 255, popups 255.
- **Needs:** `g++` and host Qt 6.11 or newer (the shim is built with the host Qt and loaded into the flatpak). A runtime update rebuilds the shim.
- **Turn on:** `appglass set apps.jellyfin.enabled true --apply` or Settings > Apps.
- **Undo:** `appglass remove --only jellyfin`.

## LocalSend and ArtCraft (colour-key shim)

Flutter and egui apps draw everything themselves into one surface. The shim replaces the app's own background colours (known keys) with the same colour at the glass level, and leaves every other pixel, text included, untouched.

- **Writes:** `appglass-ck.so` built with `gcc`, the wrapper (`appglass-localsend`, `appglass-artcraft`) and a launcher override. For LocalSend (flatpak) the lib folder is passed read-only for that run only, with no `flatpak override`. ArtCraft is moved to Mesa EGL with wgpu's GL backend, which renders on the CPU (software rendering, llvmpipe), and its swaps are capped at 60 fps.
- **Measured:** LocalSend on the real desktop at 0.80: background 204, text 255. ArtCraft at 0.80: background 204, text 255. See [flutter.md](flutter.md), [gpu.md](gpu.md) and the [issue draft](issue-dms.md#screenshots).
- **Limit:** the colour keys are per app and per light/dark theme. A colour that is not a key stays opaque: a miss fails safe, it never fades text.
- **Turn on:** `appglass set apps.localsend.enabled true --apply` or `appglass set apps.artcraft.enabled true --apply`, or Settings > Apps.
- **Undo:** `appglass remove --only localsend,artcraft`.

TODO(engine): colour keys learned from a hidden capture, for apps with no hand-made keys.

## Opaque

With the default fallback ("Opaque", Settings > Fallback), these windows get `opacity 1.0`: opaque and sharp.

- **Steam (the client window).** Steam stays opaque because no official way gives its window an alpha channel, and appglass does not inject code into Steam (its children are games). Two official routes were measured on the real client:
  - the CEF flags for underlays, with the page background made transparent through the CEF debugger: the page was transparent, the window still alpha 255 everywhere, also with GPU compositing off;
  - Steam's GL composer option: the main window and menus always use Steam's system composer, which prints "transparent background not supported"; the GL composer is only used for toasts. With `-cef-disable-xcomposite-workaround` the window was still alpha 255 everywhere.

  Steam games are never touched either way.

  TODO(adapters): `appglass status` still lists Steam with an old Forced route, `steam-cdp` ("forced adapter, off until enabled"), and Settings > Apps gives it a switch. That switch does nothing: turned on, the reason reads "adapter steam-cdp not implemented yet" and Steam stays opaque. The route is to be dropped from the catalogue.
- **Chrome and Chromium browsers.** Web content has no window alpha: measured alpha 255 everywhere. See [electron.md](electron.md).
- **Games, Wine/Proton, SDL.** Opaque with blur off, on purpose. Nothing runs inside a game process.
- **Electron apps without a CSS hook**, Java, Tk, X11 apps that are not GTK, Qt from a flatpak KDE runtime: no route in this version.

Settings > Fallback can make these windows translucent instead ("Translucent (text too)", at the Fallback opacity, 0.70 by default) or leave them at the DMS opacity ("DMS opacity"). Both fade the text with the background.

TODO(engine): root GUIs (Timeshift through pkexec) shown opaque with the reason "runs as root".
