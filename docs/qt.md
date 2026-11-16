# Qt (Qt Widgets / Qt Quick apps)

Qt Widgets apps (VLC, Jellyfin Desktop, KDE apps, KeePassXC, OBS, ...) cannot become glass on this machine without installing a style: palette alpha is always painted onto an opaque buffer, so they keep the global niri `opacity 0.60` fallback.
The mechanism itself works under niri: a Qt Quick window colour with alpha reaches all three levels (0.60 / 0.65 / 1.0) with opaque text, and a Qt Widgets window with `WA_TranslucentBackground` reaches one level (0.60), which is what Kvantum would do after an install.

Quickshell / Qt Quick apps that ship their own glass settings (Dux Files, Dux Calendar, DMS windows) are covered in [qtquick.md](qtquick.md).

## Apps

| App | Tested / Documented | Works | Method | niri rule needed |
|---|---|---|---|---|
| VLC 3.0.24 (Qt6 build) | Tested | no | palette alpha via gtk3 platform theme (`gtk.css`, `QT_GUI_GTK_JSON`), `--qt-opacity=0.6` | none (fallback 0.60), optional `opacity 1.0` for an opaque video player |
| Jellyfin Desktop 2.0.0 (flatpak, Qt6 QML + WebEngine + mpv) | Documented (not launched) | no | none: QML compiled in, no window colour option | none (fallback 0.60) |
| Qt6 Widgets + `WA_TranslucentBackground` (test program, stand-in for Kvantum) | Tested | partial | Fusion, palette Window/Base alpha 153, `WA_TranslucentBackground` on the toplevel | `opacity 1.0` for the app |
| Qt Quick window colour alpha (`qml` runner, QML you control) | Tested | yes | `ApplicationWindow.color` alpha 0.60, bars painted at 0.125, opaque popups | `opacity 1.0` for the app |
| Kvantum (style engine, not installed) | Documented | partial (expected) | `QT_STYLE_OVERRIDE=kvantum` + `translucent_windows=true` theme | `opacity 1.0` per Kvantum app |
| Dolphin / KDE apps (Breeze + DMS kcolorscheme) | Documented | no | kcolorscheme alpha (gives opaque dark) | none (fallback 0.60) |
| Konsole | Documented | partial (expected: terminal area only, see [terminal.md](terminal.md)) | colour scheme `Opacity=0.6` | `opacity 1.0` for `org.kde.konsole` |
| KeePassXC | Documented | no | none (built-in theme stylesheet paints opaque) | none (fallback 0.60) |
| Krita | Documented | no | none | none (fallback 0.60, or 1.0 for colour work) |
| OBS Studio | Documented | no | none (QSS themes on an opaque toplevel, GL preview) | none (fallback 0.60) |
| qBittorrent (and other QSS-themed Qt apps) | Documented | no | `.qbtheme` QSS alpha (gives opaque) | none (fallback 0.60) |

"Tested" means run in a nested niri session with the window alpha measured from screenshots. "Documented" means taken from docs/sources only, not run.

## Levels

The rule that decides everything for Qt Widgets: **palette alpha is not translucency**. qt5ct/qt6ct colours, kcolorscheme, the gtk3 platform theme and QSS all blend their alpha onto an opaque toplevel buffer. The window turns dark, but alpha stays 255. Only `Qt::WA_TranslucentBackground` on the toplevel makes it see-through, and in a real app only a style plugin (Kvantum, Darkly/Lightly-type Breeze forks) or the app itself sets it. None is installed here: no kvantum, qt5ct, qt6ct or plasma-integration, `/usr/lib64/qt6/plugins/styles` is empty, and the only Qt6 platform themes are `gtk3` and `xdgdesktopportal`.

| Surface | 0.60 content | 0.65 bars | 1.0 menus/popups/tooltips |
|---|---|---|---|
| Qt Widgets, palette alpha only (qt6ct, kcolorscheme, gtk3, QSS) | no (255) | no (255) | yes (everything is opaque) |
| Qt Widgets + `WA_TranslucentBackground` (tested) | yes (153) | **no**: menubar and toolbar are also 153 | tooltips yes (255); real menus not opened, see below |
| Qt Quick window colour (tested) | yes (153) | yes (166, painted at 0.125 over the window) | yes (255, including a native popup window) |
| Kvantum (documented) | `reduce_window_opacity=40` | only through theme SVG / `[MenuBar]` / `[Toolbar]` sections, no single key | `reduce_menu_opacity=0` |
| Konsole (documented) | terminal area only | no (tabs/menus opaque) | yes |

Alpha stacks. A bar painted at 0.65 over a 0.60 window ends up at `1 - 0.4 * 0.35 = 0.86`. To reach 0.65 the bar must be painted at about 0.125 over the window: `1 - 0.4 * 0.875 = 0.65` (measured 166).

## Settings per working app

### Qt Quick window colour (tested, works)

Only for QML whose source you write or control (the `qml` runner, Quickshell configs and similar). Existing Qt Quick apps do not pick this up from a theme file. No flag or env var is needed on Qt6 Wayland.

Working QML (tested in a nested niri session, Qt 6.11.2):

```qml
import QtQuick
import QtQuick.Window
import QtQuick.Controls
ApplicationWindow {
    visible: true; width: 800; height: 600
    // content level 0.60
    color: Qt.rgba(0.08, 0.086, 0.137, 0.60)
    // header: 0.125 over the 0.60 window -> 0.65 effective
    header: Rectangle { height: 56; color: Qt.rgba(0.08, 0.086, 0.137, 0.125)
        Text { anchors.verticalCenter: parent.verticalCenter; x: 16
               text: "Header 0.65"; color: "#e6e6f0"; font.pixelSize: 22 } }
    // sidebar: same 0.125 trick
    Rectangle { width: 160; height: parent.height; color: Qt.rgba(0.08, 0.086, 0.137, 0.125) }
    Text { x: 200; y: 40; text: "Content text on 0.60 glass"; color: "#e6e6f0"; font.pixelSize: 28 }
    // popups, menus, tooltips: opaque backgrounds
    Popup { x: 480; y: 340; width: 260; height: 100; visible: true
        background: Rectangle { color: "#1d1f2e"; radius: 8 } }
    Menu {
        background: Rectangle { implicitWidth: 200; color: "#1d1f2e"; radius: 6 }
        MenuItem { text: "Open"; contentItem: Text { text: "Open"; color: "#e6e6f0"; leftPadding: 8 } } }
    ToolTip { visible: true; timeout: -1; text: "Tooltip"
        background: Rectangle { color: "#2a2c3e"; radius: 4 }
        contentItem: Text { text: "Tooltip 1.0"; color: "#e6e6f0" } }
}
```

- DMS colours: take them from DMS rather than hard-coding. The window colour is the DMS `surface` colour with alpha 0.60, text uses `on_surface`. Quickshell code can read `~/.cache/dms/dms-colors.json` (a watched file, see [qtquick.md](qtquick.md)).
- Reload: the colour is in the QML source, so the app must reload or restart that QML.
- Default Controls styles (for example the light `Button` background) are not themed and stay opaque. Glass only appears on surfaces whose colour you set.

### Qt Widgets with `WA_TranslucentBackground` (tested, partial)

This is a test program, not a user fix. It shows what a translucency-capable style does. Key lines:

```cpp
app.setStyle("Fusion");
QColor win(20, 22, 35, 153), bar(20, 22, 35, 166), pop(29, 31, 46, 255), fg("#e6e6f0");
p.setColor(QPalette::Window, win); p.setColor(QPalette::Base, win);
p.setColor(QPalette::AlternateBase, bar); p.setColor(QPalette::Button, bar);
// WindowText, Text, ButtonText, ToolTipText = fg (opaque); ToolTipBase = pop
mainWindow.setAttribute(Qt::WA_TranslucentBackground);   // without this: alpha 255
```

For real apps this needs a style plugin, so Kvantum (below) is the user-side route.

### Kvantum (documented, unverified: needs `dnf install kvantum`)

1. Install `kvantum` (Fedora package with the Qt6 style plugin and `kvantummanager`).
2. Make Qt apps use it. Fedora's Qt6 has no qt6ct, so set the session env:

   ```sh
   QT_STYLE_OVERRIDE=kvantum
   ```

3. Select the theme, `~/.config/Kvantum/kvantum.kvconfig`:

   ```ini
   [General]
   theme=DankGlass
   ```

4. Theme file `~/.config/Kvantum/DankGlass/DankGlass.kvconfig`, written by a new user matugen template (start from an existing Kvantum theme's SVG + kvconfig):

   ```ini
   [%General]
   translucent_windows=true
   ; 0..90 percent; 40 gives content ~0.60
   reduce_window_opacity=40
   ; menus, popups, tooltips opaque (level 1.0)
   reduce_menu_opacity=0
   ; Kvantum blur is KWin-only; niri does the blur
   blurring=false
   popup_blurring=false
   ; keep the default opaque= list (media apps); it already contains
   ; vlc, kdenlive, digikam, VirtualBox

   [GeneralColors]
   ; window.color, base.color, text.color, ... from matugen (DMS surface / on_surface)
   ```

   Text roles stay opaque; Kvantum applies alpha only to the window background. A ~0.65 bar level is possible only by tinting the theme SVG or the `[MenuBar]` / `[Toolbar]` sections.
5. Add the niri `opacity 1.0` rule for every app that runs on Kvantum (below).

Reload: Qt styles load at app start, so restart each Qt app after changing the theme (expected, not tested).

### Konsole (documented, unverified: not installed)

Colour scheme `~/.local/share/konsole/<scheme>.colorscheme`, written from a matugen template, selected in the profile:

```ini
[General]
Opacity=0.6
Blur=true
```

One level (terminal area); tabs and menus stay opaque; text stays opaque.

### DMS colour files for Qt (do not add alpha)

DMS already writes Qt colours with matugen:

| matugen config | output |
|---|---|
| `qt6ct.toml` (template `qtct-colors.conf`) | `~/.config/qt6ct/colors/matugen.conf` |
| `qt5ct.toml` (template `qtct-colors.conf`) | `~/.config/qt5ct/colors/matugen.conf` |
| `kcolorscheme.toml` | `~/.local/share/color-schemes/DankMatugen.colors` (+ `DankMatugenLight.colors`, `DankMatugenDark.colors`) |

Putting alpha into these files gives an opaque dark window (tested equivalent: palette-only case, alpha 255). They are the colour source for a Kvantum template, not the place for glass.

### niri rules

Put appGlass rules in a file included **after** `dms/windowrules.kdl` (the DMS-managed file that holds the global "Glass blur" rule, `opacity 0.60` + blur), for example `~/.config/niri/app-glass.kdl`, included next to `dms-browser-glass.kdl`:

```kdl
// ~/.config/niri/config.kdl, after: include "dms/windowrules.kdl"
include optional=true "app-glass.kdl"
```

```kdl
// ~/.config/niri/app-glass.kdl
// Qt apps that paint their own glass (Kvantum apps, own QML windows)
window-rule {
    match app-id=r#"^(org\.kde\.konsole|<kvantum-app-id>)$"#
    opacity 1.0
}

// optional: VLC opaque (video area should not be see-through)
window-rule {
    match app-id="^vlc$"
    opacity 1.0
}
```

Blur stays on, because the global rule's `background-effect { blur true }` still applies. niri reloads its config on save. Write an `opacity 1.0` rule only together with a working glass setup; otherwise the app becomes fully opaque instead of keeping the 0.60 fallback.

## Measured results (tested in a nested niri session)

Alpha is 0-255 from window screenshots and is reliable. The screenshots store premultiplied RGB, and the early composites treated them as straight alpha, so they look darker than on screen. Contrast ratios from those composites are not quoted here: **to re-measure** with a premultiplied-correct composite.

### VLC 3.0.24 (Qt6 build), app-id `vlc`

| Variant | Window alpha min / avg / max | Result |
|---|---|---|
| no theme | 255 / 255 / 255 | Fusion light bars, black video area |
| `QT_QPA_PLATFORMTHEME=gtk3` + `gtk.css` with `rgba(..., 0.60)` backgrounds | 255 / 255 / 255 | text colour changes, background ignored (a red test background stayed 250,249,248) |
| gtk3 theme + `QT_GUI_GTK_JSON` with Fixed `#99141623` Window/Base | 255 / 255 / 255 | palette applies (dark bars), alpha blended onto black: opaque dark |
| `--qt-opacity=0.6` | 255 / 255 / 255 | no effect on Wayland |

Text and the cone logo stay opaque. With the gtk3 JSON palette the menubar text became hard to read, because `MenuPalette` was not overridden.

### Qt6 Widgets + `WA_TranslucentBackground`

The first run and an independent re-run (own build, with an extra label, button, combo box and a black 32 px toolbar icon) agree on the alpha:

| Region | Alpha |
|---|---|
| whole window | min 0, avg 143-150, max 255 |
| menubar, toolbar, tree, text edit | 153 (sampled RGBA 12,13,21,153) |
| QStatusBar, QSplitter handle, central widget behind a QLabel, margins between widgets | **0** (holes) |
| tooltip (QToolTip) | 255 |
| QMenu shown as a tooltip-type surface | 255 |
| same program with palette only (`GLASS=0`) | 255 everywhere |

- Text: glyph cores 255, background 153. Readable on wallpaper, white and black where it sits on the 153 glass.
- Bug: text in the alpha-0 holes (QLabel on the window background, status bar) sits directly on whatever is behind the window. Over a white backdrop it is light on white, below 2:1.
- Bug: the black icon on the dark bar glass is nearly invisible over the wallpaper (dark logo on dark glass).
- No 0.65 bar level: bars and content are both 153.
- A full-output screenshot shows the nested background through the window, so niri really blends it.

### Qt Quick window colour (`qml` runner, Qt 6.11.2)

Confirmed by an independent re-run with a new QML file:

| Region | Alpha |
|---|---|
| whole window | min 153, avg 162.3, max 255 |
| content | 153 (0.60) |
| header | 166 (0.651) |
| sidebar | 166 |
| Popup | 255 |
| Menu | 255 |
| ToolTip | 255 |
| Menu with `popupType: Popup.Window` (native popup) | opaque on a full-screen screenshot |

- Text: bright glyph pixels alpha 241-255, cores 255, only antialiased edges in between (28 px, header, 12 px and icon-glyph text). Crisp on wallpaper, white and black composites. Contrast: to re-measure.
- A dark logo (`#101018` circle) became readable only with a light outline (`border.color: "#e6e6f0"`).
- Dark text (`#303040`) is nearly invisible on the dark glass: a colour choice, not an alpha problem.
- No black fill and no premultiplied fringes on screen. Same alpha with or without `QT_QPA_PLATFORM=wayland`.

## What breaks / caveats

- **Palette alpha alone never works for Qt Widgets.** qt5ct/qt6ct, kcolorscheme, gtk3 and QSS alpha give an opaque dark window. Do not add alpha to the DMS Qt colour files.
- **gtk3 platform theme:** `gtk.css` backgrounds never reach Qt (only the foreground colour does). `QT_GUI_GTK_JSON` does apply a palette, but palettes not overridden (`MenuPalette`) keep GTK colours, and menubar text became hard to read.
- **Holes with `WA_TranslucentBackground`:** every container widget that does not fill its own background is alpha 0, not just the status bar and splitter. Whether Kvantum avoids these holes is not tested.
- **Dark logos/icons on dark glass** need a light outline or backing.
- **Light mode:** the QML colours are fixed in the source; a light DMS theme needs the window colour and text colour switched too (from `dms-colors.json`). Light-theme readability is to re-measure; the early composites make light themes look much too dark.
- **Menus not captured for Qt Widgets:** `QMenu::popup` and `QComboBox::showPopup` without an input serial never appear on Wayland, and no input tool (wtype/ydotool) is installed. Real xdg_popup menus of a Widgets app are unmeasured. Qt Widgets menus are separate popup surfaces and are opaque unless the style makes them translucent.
- **Window screenshots miss native popups:** with `popupType: Popup.Window` the menu region read 153 (the window under it). Use a full-screen screenshot to check popups.
- **VLC 3** refuses to load its Qt interface without an X display (`XOpenDisplay` check), even with `QT_QPA_PLATFORM=wayland`; it still draws over Wayland with app-id `vlc`. Its main window is mostly the black video widget, and Kvantum's default `opaque=` list includes `vlc`.
- **`--qt-opacity`** has no effect on Wayland and would fade text anyway.
- **Apps that paint their own backgrounds** stay opaque in those areas even with Kvantum: video areas, canvases (Krita), QSS themes (OBS `.ovt/.obt`, qBittorrent `.qbtheme`), KeePassXC's built-in theme.
- **Kvantum on Wayland** has had per-version translucency quirks; check each app after install.
- **Flatpak (Jellyfin):** not launched; host Kvantum/style access from a flatpak is not tested.
- **Fallback stacking:** an `opacity 1.0` rule without a working glass setup makes the app opaque; a glass setup without the rule gets multiplied by the global 0.60 (text fades).

## Documented-only apps (unverified)

- **Jellyfin Desktop 2.0.0** (flatpak `org.jellyfin.JellyfinDesktop`, Qt6 QML + WebEngine + mpv): the QML is compiled into the binary with no window colour or transparency option, and the web UI is layered over an mpv item in an opaque Qt Quick window. A Qt Quick window could be translucent (see the tested QML case), but Jellyfin exposes no way to set it. Fallback: niri 0.60.
- **Kvantum:** see the settings above. Expected 2 to 3 levels (window via `reduce_window_opacity`, opaque menus via `reduce_menu_opacity=0`, bar tint via the theme). Cost: one package, one env var, one matugen template (kvconfig + reused SVG), one niri rule per app. Static files, no daemon.
- **Dolphin / KDE apps** (Breeze + `DankMatugen.colors`): Breeze does not make main windows translucent; kcolorscheme alpha gives opaque dark. plasma-integration (the platform theme that reads kdeglobals) is not installed either. Needs Kvantum or a Darkly/Lightly-type style. Fallback: niri 0.60.
- **Konsole:** colour scheme `Opacity=0.6` (+ `Blur=true`) in `~/.local/share/konsole/<scheme>.colorscheme`, from a matugen template; one level, text opaque, menus/tabs opaque. niri rule `opacity 1.0` for `^org\.kde\.konsole$`.
- **KeePassXC:** its built-in light/dark theme stylesheet paints opaque backgrounds. Maybe partial with Kvantum when its theme is set to classic. Fallback: niri 0.60.
- **Krita:** canvas and dockers paint themselves; Kvantum not recommended. Fallback 0.60, or `opacity 1.0` for colour-accurate work.
- **OBS Studio:** QSS themes (`.ovt/.obt`) paint on an opaque toplevel, the preview is GL. Fallback: niri 0.60.
- **qBittorrent** and other QSS-themed apps: QSS alpha lands on an opaque toplevel. Kvantum might work for the window shell. Fallback: niri 0.60.
