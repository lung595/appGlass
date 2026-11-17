# App table

Generated from `docs/apps.json` by `python3 -m appglass.appstable --write`; do not edit by hand.

Tested: **here** = headless verify of the family on an isolated install (content level 0.60 = 153:
bg alpha at the level, light text at 255, an opened popup at 255); **earlier** = verified in an
earlier step (README, the family's doc or commit); **probe** = the B5b research probe at level 0.80
(204), not this family; **no** = documented only.

Result follows the evidence: **needs adapter** = no family covers the app; **untested** = a family
exists but was not verified on this app (the probe's or the expected result is in the notes);
glass, partial or opaque only for rows tested here (a glass row needs a PASS) or earlier.

51 rows (a row can name several apps): 10 tested here, 13 earlier, 26 probe, 2 documented. 15 glass, 8 partial, 0 opaque, 5 untested, 23 needs adapter.

| App | Toolkit | Family | Route | Tested | Result | Measured / reason | Evidence |
|---|---|---|---|---|---|---|---|
| foot 1.20.2 (flatpak) | own (pixman) | foot | `[colors-dark] alpha` + DMS palette, flatpak config dir | here | glass | PASS: bg 153 (100%), text 255, no popup | shots/adapters/foot.json |
| Konsole 26.08.3 (flatpak) | Qt6 / KDE | konsole | glass colour scheme + profile; qt-style launcher for tabs and menus | here | glass | PASS: bg 153 (94%), text 255, popup 255 (72%) | shots/adapters/konsole.json |
| Kate 26.08.3 (flatpak) | Qt6 / KTextEditor | kate | KSyntaxHighlighting theme with a clear editor background + qt-style (WA_OpaquePaintEvent cleared) | here | glass | PASS: bg 153 (73%), text 255, popup 255 (100%). the glass theme only in the glass start (plain flatpak run stays Breeze: kfix-plain.json). Minimap a tint (about 197), its lines and the icon border icons not clear (no theme key) | shots/adapters/kfix-glass.json |
| mpv 0.42.0 (flatpak) | own (libmpv gpu-next) | mpv | `background-color` with alpha, `alpha=yes`; video, OSD and console opaque | here | glass | PASS: bg 153 (97%), text 255, popup 255 (74%) | shots/adapters/mpv.json |
| GNOME Text Editor 51.0 (flatpak) | GTK4 / libadwaita + GtkSourceView 5 | gtk4 | gtk.css with the GtkSourceView rule, delivered to the flatpak | here | glass | PASS: bg 153 (88%), text 255, popup 255 (97%) | shots/adapters/texteditor.json |
| Mission Center 1.2.0 (flatpak) | GTK4 / libadwaita | gtk4 | gtk.css (columnview/listview rule), delivered to the flatpak | here | glass | PASS: bg 153 (69%), text 255, popup 255 (54%). popup share counts the live graphs that changed under the menu too | shots/adapters/missioncenter.json |
| VSCodium 1.143 (flatpak) | Electron | vscodium | electron-hook (the Feishin hook) with workbench CSS; opt-in | here | glass | PASS: bg 153 (76%), text 255, no popup, 3 glass regions clear. breadcrumb strip and terminal panel checked as regions (opaque share 4% and 0%); the terminal uses the DOM renderer (gpuAcceleration off). Fresh-HOME starts vsf1-13: 2 of 5 without glass before the injector retried while Node starts, 8 of 8 glass after | shots/adapters/vsf6.json |
| Zed 1.28.1 (flatpak) | GPUI (wgpu) | zed | `window_background_appearance` + theme_overrides alpha in settings.json | here | partial | FAIL: bg 194, not 153. Zed 1.28.1 lays a black floor of alpha 0.40 under the window: bg 194 at content 0.60 (224 at 0.80), also with every theme background cleared (zed-clear*.json); the older Zed in B5b measured 204 exactly. Text and the command palette 255 | shots/adapters/zed.json |
| Saber 1.37.1 (flatpak) | Flutter | ck-shim (learned keys) | ck-shim with keys from appglass.keylearn: 232323:0.60, SNAP 0.2 | here | partial | PASS: bg 153 (96%), text 255, no popup. keys learned from one opaque capture match the hand keys (232323); no Saber family yet, so the keys are passed by hand; B5b: hovered rows inside its popups are keyed (5-11% of the popup) | shots/adapters/saber-ck.json |
| Sublime Text 4215 (flatpak) | custom GL on GTK3 | ck-shim (learned keys) | ck-shim with keys from appglass.keylearn: 303841,72787e at 0.60, SNAP 0.3, APPGLASS_KEEP for the real binary, hardware_acceleration opengl | here | partial | PASS: bg 153 (86%), text 255, popup 255 (98%). the GTK menubar stays opaque (gtk3 theme not combined); no Sublime family yet; keys follow the colour scheme, so they are relearned when it changes | shots/adapters/sublime-ck.json |
| Alacritty 0.17.0 | own (OpenGL) | alacritty | `window.opacity`, opaque glyphs, DMS palette | earlier | glass |  | docs/terminal.md |
| Nautilus 51.1 and libadwaita apps | GTK4 / libadwaita | gtk4 | gtk.css alpha on the libadwaita background roles | earlier | glass |  | docs/gtk4.md |
| Solaar, nvidia-settings | GTK3 | gtk3 | AppGlass theme by launcher override (mode B) | earlier | partial | GtkDialog bodies not covered; nvidia-settings column headers faint | docs/gtk3.md |
| VLC 3.0.24 | Qt6 Widgets | qtstyle | appglass Qt style plugin | earlier | glass |  | commit 31c3d64 |
| Obsidian 1.15.1 (flatpak) | Electron | obsidian | vault CSS snippet appglass.css | earlier | partial | depends on the vault theme; every layer cleared, painted once | docs/electron.md |
| Dux Files / Dux Calendar | Qt Quick | dux | the apps' own ui-settings.json glass keys | earlier | partial | the apps' levels are inverted (bars clearer than content) | docs/qtquick.md |
| Herdr 0.1.16 | GPUI | herdr | alpha theme + glass copy of the main layout | earlier | partial | ANSI colours taken from DMS roles; some panes keep their own fills | docs/gpu.md |
| ArtCraft Launcher 0.19.2 | egui / wgpu | artcraft | ck-shim: Mesa EGL + wgpu GL + colour keys, 60 fps cap; opt-in | earlier | glass |  | docs/gpu.md |
| Feishin (flatpak) | Electron | feishin | electron-hook main-process hook; opt-in | earlier | glass |  | commit 1571a2a |
| Jellyfin Desktop 2.0.0 (flatpak) | Qt Quick + WebEngine | jellyfin | qtquick-shim libjfglass.so; opt-in | earlier | glass |  | commit de7eee8 |
| LocalSend 1.18.2 (flatpak) | Flutter | localsend | ck-shim colour keys; opt-in | earlier | glass |  | commit ec1db1a |
| Lian Li Linux (lianli-gui) | Tauri / WebKitGTK | lianli | webkit-shim appglass-wk.so; opt-in | earlier | glass |  | commit 7b90b43 |
| Discord + Vencord | Electron (client mod) | vencord | Vencord transparent window + DMS theme with alpha; opt-in | earlier | partial | needs the Vencord client mod; the official client alone has no route | commit fc31872 |
| kitty | own (OpenGL) | kitty | `background_opacity` + DMS theme include | no | untested | expected: glass. expected; not on flathub, not installed: the writer is unit-tested only | - |
| Ghostty | own (OpenGL/GTK4) | ghostty | `background-opacity` (+ cells) + DMS theme | no | untested | expected: glass. expected; not on flathub, not installed: the writer is unit-tested only | - |
| WezTerm | own (OpenGL/WebGPU) | wezterm | lua config: window_background_opacity, text_background_opacity 1.0, tab bar at the bar level | probe | untested | probe: partial. flathub build is on the end-of-life fdo 23.08 runtime and was not installed here; B5b: 204 with tab bar fills at their own level; writer unit-tested | b5b/results.json |
| GIMP 3.2.8 (flatpak) | GTK3 | gimp | user gimp.css block over GIMP's own theme | probe | untested | probe: glass. not installed here (size); B5b measured 204 on menubar and docks, canvas opaque; writer unit-tested | b5b/results.json |
| Ptyxis | GTK4 / libadwaita + VTE | - | gsettings profile opacity + gtk4 css | probe | needs adapter | probe: partial. popups follow the titlebar and profile alpha (not opaque); needs a Ptyxis profile writer | b5b/results.json |
| Element | Electron | - | electron-hook (Feishin hook) | probe | needs adapter | probe: opaque. fuses deny the inspector and NODE_OPTIONS, so the hook cannot load; needs an electron-fuse adapter (user copy of the binary with the fuse flipped) | b5b/results.json |
| Signal | Electron | - | electron-hook (Feishin hook) | probe | needs adapter | probe: opaque. fuses deny the inspector and NODE_OPTIONS; B5b reached 204 only with an app.asar loader shim (electron-loader route, not built) | b5b/results.json |
| Slack | Electron | - | electron-hook | probe | needs adapter | probe: opaque. same fuses as Signal; needs the electron-loader route | b5b/results.json |
| Spotify | CEF | - | CSS route | probe | needs adapter | probe: opaque. CEF ignores page alpha; needs a CEF interposer | b5b/results.json |
| Telegram Desktop | Qt6 (static, custom widgets) | - | ck-shim + forced Mesa EGL | probe | needs adapter | probe: partial. modals share the window colour and get keyed; per-theme key tables | b5b/results.json |
| Cinny | Tauri / WebKitGTK | - | webkit-shim in a flatpak | probe | needs adapter | probe: partial. needs a flatpak variant of the Tauri family | b5b/results.json |
| Dolphin | Qt6 / KDE | - | qt-style + kdeglobals View colours | probe | needs adapter | probe: glass. needs a kde family (flatpak plumbing, QT_QPA_PLATFORMTHEME=kde) | b5b/results.json |
| Strawberry | Qt6 Widgets | - | qt-style | probe | needs adapter | probe: partial. only the frame: playlist and collection views paint opaque | b5b/results.json |
| KeePassXC | Qt6 Widgets | - | qt-style + classic theme | probe | needs adapter | probe: partial. the dark theme paints opaque; glass with the classic theme only | b5b/results.json |
| Krita | Qt5 Widgets | - | qt-style (Qt5 build) | probe | needs adapter | probe: glass. needs a Qt5 build of the style | b5b/results.json |
| OBS Studio | Qt6 Widgets | - | qt-style | probe | needs adapter | probe: glass. previews stay opaque | b5b/results.json |
| Celluloid | GTK4 / libadwaita + libmpv | - | gtk4 css | probe | needs adapter | probe: glass. video area stays 255 | b5b/results.json |
| Resources | GTK4 / libadwaita | gtk4 | gtk.css delivered to the flatpak (FLATPAK_APPS) | probe | untested | probe: glass. not re-verified here | b5b/results.json |
| Bottles | GTK4 / libadwaita | - | gtk4 css | probe | needs adapter | probe: partial. a modal AdwWindow is 204 with the generic css | b5b/results.json |
| Rhythmbox | GTK3 | - | gtk3 theme | probe | needs adapter | probe: glass | b5b/results.json |
| LibreOffice | VCL gtk3 | - | gtk3 theme | probe | needs adapter | probe: partial. VCL-painted surfaces (Start Center, toolbars, document) stay 255 | b5b/results.json |
| Inkscape | GTK3 | - | gtk3 theme + ui/style.css | probe | needs adapter | probe: partial. canvas and rulers opaque by design | b5b/results.json |
| Thunderbird | Gecko | - | userChrome.css | probe | needs adapter | probe: glass. needs a Gecko family | b5b/results.json |
| Joplin | Electron | - | user CSS | probe | needs adapter | probe: glass. needs an app CSS writer | b5b/results.json |
| Logseq | Electron | - | custom.css | probe | needs adapter | probe: glass. needs an app CSS writer | b5b/results.json |
| Blender 5.3 | own (GHOST, Vulkan/GL) | - | theme alpha | probe | needs adapter | probe: partial. widgets inside popups 204-223 | b5b/results.json |
| JDownloader 2 | Java Swing | - | javaagent | probe | needs adapter | probe: partial. needs a java-swing adapter (no EGL, ck-shim cannot apply) | b5b/results.json |
| DBeaver CE | Java SWT on GTK3 | - | gtk3 css | probe | needs adapter | probe: partial. SWT paints its own backgrounds; needs an swt family | b5b/results.json |
