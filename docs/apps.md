# App table

Generated from `docs/apps.json` by `python3 -m appglass.appstable --write`; do not edit by hand.

Tested: **here** = headless verify of the family on an isolated install (content level 0.60 = 153:
bg alpha at the level, light text at 255, an opened popup at 255); **earlier** = verified in an
earlier step (README, the family's doc or commit); **probe** = the B5b research probe at level 0.80
(204), not this family; **no** = documented only.

Result follows the evidence: **needs adapter** = no family covers the app; **untested** = a family
exists but was not verified on this app (the probe's or the expected result is in the notes);
glass, partial or opaque only for rows tested here (a glass row needs a PASS) or earlier;
**glass (popups unverified)** = a PASS that opened no popup on a toolkit that has popups.

52 rows (a row can name several apps): 14 tested here, 14 earlier, 22 probe, 2 documented. 18 glass (2 with popups unverified), 6 partial, 0 opaque, 3 untested, 25 needs adapter.

| App | Toolkit | Family | Route | Tested | Result | Measured / reason | Evidence |
|---|---|---|---|---|---|---|---|
| foot 1.20.2 (flatpak) | own (pixman) | foot | `[colors-dark] alpha` + DMS palette, flatpak config dir | here | glass | PASS: bg 153 (100%), text 255, no popup | shots/adapters/foot.json |
| Konsole 26.08.3 (flatpak) | Qt6 / KDE | konsole | glass colour scheme + profile; qt-style launcher for tabs and menus | here | glass | PASS: bg 153 (94%), text 255, popup 255 (72%) | shots/adapters/konsole.json |
| Kate 26.08.3 (flatpak) | Qt6 / KTextEditor | kate | KSyntaxHighlighting theme with a clear editor background + qt-style (WA_OpaquePaintEvent cleared) | here | glass | PASS: bg 153 (73%), text 255, popup 255 (100%). the glass theme only in the glass start (plain flatpak run stays Breeze: kfix-plain.json). Minimap a tint (about 197), its lines and the icon border icons not clear (no theme key) | shots/adapters/kfix-glass.json |
| mpv 0.42.0 (flatpak) | own (libmpv gpu-next) | mpv | `background=color`, `background-color=#99rrggbb`, `border-background=color`, `script-opts-append=console-background_alpha=00`; video, OSD and console opaque | here | glass | PASS: bg 153 (97%), text 255, popup 255 (74%) | shots/adapters/mpv.json |
| GNOME Text Editor 51.0 (flatpak) | GTK4 / libadwaita + GtkSourceView 5 | gtk4 | gtk.css with the GtkSourceView rule, delivered to the flatpak | here | glass | PASS: bg 153 (88%), text 255, popup 255 (97%) | shots/adapters/texteditor.json |
| Mission Center 1.2.0 (flatpak) | GTK4 / libadwaita | gtk4 | gtk.css (columnview/listview rule), delivered to the flatpak | here | glass | PASS: bg 153 (69%), text 255, popup 255 (54%). popup share counts the live graphs that changed under the menu too | shots/adapters/missioncenter.json |
| VSCodium 1.143 (flatpak) | Electron | vscodium | electron-hook (the Feishin hook) with workbench CSS; opt-in | here | glass (popups unverified) | PASS: bg 153 (76%), text 255, no popup, 3 glass regions clear. breadcrumb strip and terminal panel checked as regions (opaque share 4% and 0%); the terminal uses the DOM renderer (gpuAcceleration off). Fresh-HOME starts vsf1-13: 2 of 5 without glass before the injector retried while Node starts, 8 of 8 glass after | shots/adapters/vsf6.json |
| Zed 1.28.1 (flatpak) | GPUI (wgpu) | zed | `window_background_appearance` + theme_overrides alpha in settings.json | here | partial | FAIL: bg 194, not 153. Zed 1.28.1 lays a black floor of alpha 0.40 under the window: bg 194 at content 0.60 (224 at 0.80), also with every theme background cleared (zed-clear*.json); the older Zed in B5b measured 204 exactly. Text and the command palette 255 | shots/adapters/zed.json |
| Saber 1.37.1 (flatpak) | Flutter | - | no family; measured with the ck-shim and keys from appglass.keylearn passed by hand: 232323:0.60, SNAP 0.2 | here | needs adapter | expected: partial. PASS: bg 153 (96%), text 255, no popup. keys learned from one opaque capture match the hand keys (232323); no Saber family and no niri rule for com.adilhanney.saber yet; B5b: hovered rows inside its popups are keyed (5-11% of the popup) | shots/adapters/saber-ck.json |
| Sublime Text 4215 (flatpak) | custom GL on GTK3 | - | no family; measured with the ck-shim and keys from appglass.keylearn passed by hand: 303841,72787e at 0.60, SNAP 0.3, APPGLASS_KEEP for the real binary, hardware_acceleration opengl | here | needs adapter | expected: partial. PASS: bg 153 (86%), text 255, popup 255 (98%). no Sublime family and no niri rule for subl yet; the GTK menubar stays opaque (gtk3 theme not combined); keys follow the colour scheme, so they are relearned when it changes | shots/adapters/sublime-ck.json |
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
| Lian Li Linux (lianli-gui) | Tauri / WebKitGTK | lianli | webkit-shim appglass-wk.so; opt-in. e2e in a nested niri with its daemon hidden: content 153, bars 166 | earlier | glass |  | tests/e2e/lianli.sh, commit 84ce964 |
| Kiri 0.2.1 (kiri-window) | Tauri / WebKitGTK | webkit | webkit-shim appglass-wk.so + page CSS/JS from the page's own colours, found by toolkit (any host GTK3 WebKitGTK 4.x app whose window is the WebView); opt-in. e2e in a nested niri, measured on its setup screen (no engine in the harness): content 153 (94% within 6), bars 166, language dialog 255; its hidden check passes (background 153, opaque text) and then applies the glass | earlier | glass |  | tests/e2e/webkit.sh, commit 7e67ea2 |
| Discord + Vencord | Electron (client mod) | vencord | Vencord transparent window + DMS theme with alpha; opt-in | earlier | partial | needs the Vencord client mod; the official client alone has no route | commit fc31872 |
| kitty | own (OpenGL) | kitty | `background_opacity` + DMS theme include | no | untested | expected: glass. expected; not on flathub, not installed: the writer is unit-tested only | - |
| Ghostty | own (OpenGL/GTK4) | ghostty | `background-opacity` (+ cells) + DMS theme | no | untested | expected: glass. expected; not on flathub, not installed: the writer is unit-tested only | - |
| WezTerm | own (OpenGL/WebGPU) | wezterm | lua config: window_background_opacity, text_background_opacity 1.0, tab bar at the bar level | probe | untested | probe: partial. flathub build is on the end-of-life fdo 23.08 runtime and was not installed here; B5b: 204 with tab bar fills at their own level; writer unit-tested | b5b/results.json |
| GIMP 3.2.8 (flatpak) | GTK3 | gimp | user gimp.css block over GIMP's own theme | here | glass | PASS: bg 153 (80%), text 255, popup 255 (99%). the canvas stays opaque by design; the File menu opaque; the first-start welcome dialog is glass too (gimp2.json measured that dialog: 153 on 47%, its banner image opaque) | shots/adapters/gimp3.json |
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
| Celluloid 0.30 (flatpak) | GTK4 / libadwaita + libmpv | - | probe: the gtk4 css delivered to ~/.var/app/<id>/config/gtk-4.0 (Celluloid not in FLATPAK_APPS) | here | needs adapter | expected: partial. FAIL: bg 214, not 153. the generic gtk4 css stacks a second fill under the welcome view: bg 214 (two 0.60 layers), header menu 255; needs a Celluloid rule before it joins FLATPAK_APPS; B5b: the video area stays 255 | shots/adapters/celluloid.json |
| Resources 1.10.2 (flatpak) | GTK4 / libadwaita | gtk4 | gtk.css delivered to the flatpak (FLATPAK_APPS) | here | glass (popups unverified) | PASS: bg 153 (76%), text 255, no popup. no popup opened (its menu button has no key binding); sidebar graphs at their own alpha | shots/adapters/resources2.json |
| Bottles | GTK4 / libadwaita | - | gtk4 css | probe | needs adapter | probe: partial. a modal AdwWindow is 204 with the generic css (B5b). Headless verify here blocked: without a Wine runner (a download) Bottles opens its onboarding dialog over the window (gtk4 css: dialog 255, the window under its dim 204; shots/adapters/bottles2.json) | b5b/results.json |
| Rhythmbox 3.5.1 (flatpak) | GTK3 | - | probe: the gtk3 family's AppGlass theme copied by hand into the flatpak (~/.var/app/<id>/data/themes, dank-colors.css beside it) and GTK_THEME=AppGlass | here | needs adapter | expected: glass. PASS: bg 153 (84%), text 255, no popup. glass with the gtk3 theme, but the gtk3 family does not deliver to flatpaks yet (adapter work: theme copy plus GTK_THEME for the flatpak); toolbar and sidebar 166; no popup opened (no key opens its menu) | shots/adapters/rhythmbox3.json |
| LibreOffice | VCL gtk3 | - | gtk3 theme | probe | needs adapter | probe: partial. VCL-painted surfaces (Start Center, toolbars, document) stay 255 | b5b/results.json |
| Inkscape | GTK3 | - | gtk3 theme + ui/style.css | probe | needs adapter | probe: partial. canvas and rulers opaque by design | b5b/results.json |
| Thunderbird | Gecko | - | userChrome.css | probe | needs adapter | probe: glass. needs a Gecko family | b5b/results.json |
| Joplin | Electron | - | user CSS | probe | needs adapter | probe: glass. needs an app CSS writer | b5b/results.json |
| Logseq | Electron | - | custom.css | probe | needs adapter | probe: glass. needs an app CSS writer | b5b/results.json |
| Blender 5.3 | own (GHOST, Vulkan/GL) | - | theme alpha | probe | needs adapter | probe: partial. widgets inside popups 204-223 | b5b/results.json |
| JDownloader 2 | Java Swing | - | javaagent | probe | needs adapter | probe: partial. needs a java-swing adapter (no EGL, ck-shim cannot apply) | b5b/results.json |
| DBeaver CE | Java SWT on GTK3 | - | gtk3 css | probe | needs adapter | probe: partial. SWT paints its own backgrounds; needs an swt family | b5b/results.json |
