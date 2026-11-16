# GPU-native Rust UIs (gpui, egui/wgpu)

Herdr (gpui) reaches all three levels: 0.60 content, 0.65 bars and sidebar, 1.0 popups. It needs a theme file, one custom layout and a niri rule. One ANSI palette entry still needs a fix. Zed (gpui) is expected to work the same way, but this is documented only.
ArtCraft Launcher (egui/wgpu) cannot be made transparent without a rebuild, so it keeps the global niri opacity.

## Apps

| App | Tested / Documented | Works | Method | niri rule needed |
|---|---|---|---|---|
| Herdr 0.1.16 (gpui) | Tested in a nested niri session, then re-checked from scratch | partial: all three levels work; ANSI bright-black is unreadable over light backdrops | Theme `themes/dankglass.json` with `#rrggbbaa` colours, plus a custom layout `layouts/glass.json` (`window_blur`, transparent root, `terminal_opacity: 0`), plus `shared.json` `layout: glass` | `match app-id="^herdr-app$"` + `opacity 1.0` |
| ArtCraft Launcher 0.19.2 (eframe/egui + wgpu) | Tested (baseline only) | no | None. No theme or config file exists, and egui transparency is set at compile time | None: the global `opacity 0.60` rule is the fallback |
| Zed (gpui) | Documented (not installed) | expected yes, unverified | User copy of the DMS matugen template `dank-zed.json`, with `background.appearance` and alpha set per level | `match app-id="^dev\\.zed\\.Zed$"` + `opacity 1.0` (unverified) |

## Levels

| Surface | Herdr (tested) | Zed (documented) | ArtCraft |
|---|---|---|---|
| Content 0.60 (alpha 153) | yes: work area, pane interior, pane header, gaps between panes, Files panel | expected: editor, terminal, gutter | no: whole window 255; fallback dims it all, text included |
| Bars / sidebar 0.65 (alpha 166) | yes: sidebar, brand bar, sidebar footer, tab bar, status bar | expected: panel, title bar, status bar, tab bar, toolbar, tabs | no |
| Menus / popups 1.0 (alpha 255) | yes: command palette, `+` new-menu, Settings window, toast | expected: `elevated_surface.background` kept solid | n/a |
| Text / icons / logos (255) | yes: glyph cores and the sheep logo at 255 | expected: text colours kept solid. The shipped template has alpha on `text.placeholder` and `text.disabled` | faded to 0.60 by the fallback |

Herdr, not tested: tooltips and pointer-anchored right-click menus. Modal dialogs dim the window behind them with a scrim (alpha 189/197) while open. This is expected.

## Herdr: exact settings

Config home: `~/.config/herdr-app/` (`$XDG_CONFIG_HOME/herdr-app`; `HERDR_APP_HOME` can override it).

Herdr hot-reloads themes and layouts, so no restart is needed. No daemon and no patching are needed. The chosen layout persists in `shared.json`: after a relaunch, the window came back with the same look (minimum alpha 153).

### 1. Theme: `~/.config/herdr-app/themes/dankglass.json`

This is the tested file. Its colours are DMS dark `surface` (#101418) and `on_surface` (#e0e2e8). The `colors` map accepts `#rrggbbaa`, although Herdr's bundled docs only show `#rrggbb`.

```json
{
  "background": "#101418",
  "foreground": "#e0e2e8",
  "selection": "#2b4a66",
  "cursor": "#9acbfa",
  "ansi": [
    "#3a3f45", "#ff8a80", "#a5d6a7", "#ffe082", "#9acbfa", "#ce93d8", "#80deea", "#e0e2e8",
    "#6c727a", "#ff8a80", "#a5d6a7", "#ffe082", "#9acbfa", "#ce93d8", "#80deea", "#ffffff"
  ],
  "colors": {
    "canvas":     "#10141899",
    "chrome":     "#101418a6",
    "background": "#10141800",
    "muted":      "#c2c7cf",
    "dim":        "#a3a9b1",
    "border":     "#3a4048"
  }
}
```

The theme tokens:
- `canvas` is the area behind the cards: content level, `99` = 0.60.
- `chrome` covers the sidebars and bars: bar level, `a6` = 0.65.
- `background` is the terminal and card fill. It is fully clear, so the canvas shows through without stacking.
- `muted`, `dim` and `border` are solid on purpose. Herdr's defaults are translucent foreground, which fades the text (see "What breaks").
- `popover`, `surface` and `raised` (popups) are left alone, so popups stay opaque.

The ANSI entry 8 (`#6c727a`) still needs a lighter value, for example `#8f959d` or lighter. That value is not tested yet. See "What breaks".

### 2. Layout: `~/.config/herdr-app/layouts/glass.json`

This is a copy of the shipped `layouts/main.json` with four changes:
- Root: `"window_blur": true`, `"theme": "dankglass"`, `"terminal_opacity": 0`, `"background": "#00000000"`.
- The `sidebar` column: `"background": null`. Its mods already paint `chrome`, so a second background stacks them.
- `work-body`: `"background": "canvas"`.

This command makes the copy (it reproduces the tested file):

```sh
cd ~/.config/herdr-app/layouts
jq '.window_blur=true | .theme="dankglass" | .terminal_opacity=0 | .background="#00000000"
    | walk(if type=="object" and .id=="sidebar" then .background=null
           elif type=="object" and .id=="work-body" then .background="canvas"
           else . end)' main.json > glass.json
```

`terminal_opacity` below 1 stops the terminal from painting its own solid background.

`window_blur` makes gpui request `org_kde_kwin_blur`, which niri supports. It is redundant with the niri `background-effect` blur, and its effect on niri was not measured.

### 3. Select the layout: `~/.config/herdr-app/shared.json`

```json
{ "layout": "glass" }
```

Keep the other keys already in the file. Choosing the layout in Herdr's settings works too, and so does `herdr-app do layout.switch --name glass`. Only the layout named in `shared.json` gets the look; other layouts, such as a `win98` one, stay as they are.

### 4. niri rule

Place this after the global "Glass blur" rule (opacity 0.60, blur on):

```kdl
window-rule {
    match app-id="^herdr-app$"
    opacity 1.0
}
```

This snippet, after a global `opacity 0.60` rule, passes `niri validate`. Its effect was not measured in a running compositor, because window screenshots capture only the app's own alpha.

### 5. DMS colours (matugen)

DMS ships no Herdr template. For the POC, add a user template, for example `herdr.toml` with an `output_path` of `CONFIG_DIR/herdr-app/themes/dankglass.json`. Write the alpha as a hex suffix after the role:

```json
"background": "{{colors.surface.dark.hex}}",
"foreground": "{{colors.on_surface.dark.hex}}",
"colors": {
  "canvas":     "{{colors.surface.dark.hex}}99",
  "chrome":     "{{colors.surface.dark.hex}}a6",
  "background": "{{colors.surface.dark.hex}}00"
}
```

Not tested: the template itself, and which DMS roles should feed `muted`, `dim`, `border` and `ansi`. The tested file used the fixed hex values above. Whatever roles are chosen, they must stay solid (no alpha suffix).

## Measured results (Herdr)

Alpha comes from window screenshots (0-255).

| Variant | Content | Sidebar | Tab / status bar | Popups | Text |
|---|---|---|---|---|---|
| Baseline, no glass | 255 | 255 | 255 | 255 | 255 |
| Final (theme + `glass.json` layout) | 153 | 166 | 166 | 255 (palette, new-menu, Settings, toast) | 255 |
| Alpha theme only, on shipped `main.json` | 153 | 242 | 219 | – | 255 |
| Shipped layout with only `window_blur`/`theme`/`terminal_opacity` changed | – | 242 | – | – | – |
| Theme + `settings.json` `terminal_opacity` (no custom layout) | terminal stays 255 | 220 | – | – | – |

Final window: alpha min 153, average 162, max 255.

Readability (checked in composites over the blurred wallpaper, white and black backdrops):
- The UI text is crisp: "Spaces", "Settings", "Add machine", title, status bar and `ls` output.
- The black and white sheep logo is clearly visible on the dark glass.
- Terminal ANSI colours are crisp, apart from the two exceptions under "What breaks".
- There are no seams, and no black areas where there should be transparency.

Contrast ratios: to re-measure. The composites made so far treated the premultiplied PNG as straight alpha, so their ratios are not quoted here. That error makes light backdrops come out too dark.

## What breaks / caveats

- **Translucent muted text (fixed).** Herdr derives `muted`, `dim` and `border` as translucent foreground. On 0.60 glass over a light backdrop, "Spaces", the hint text in the second sidebar list and "Add machine" nearly vanished. Solid `muted`/`dim`/`border` values fix this.
- **ANSI bright-black (`ansi[8]` `#6c727a`): a bug, still open.** It is used for shell autosuggestions, comments and "grey" output. It is invisible over a white backdrop and weak over the wallpaper. Give it a lighter value; contrast to re-measure.
- **ANSI black (`ansi[0]` `#3a3f45`).** It is effectively invisible on the dark glass. Black on dark is weak in any dark terminal, but the glass makes it worse.
- **Faint hints.** The status-bar hint "Ctrl+Shift+P commands" and the hint text in the second sidebar list are the faintest UI text over light backdrops. Re-measure them with a correct composite.
- **Frozen layout.** `glass.json` is a clone, and Herdr never updates clones. Upstream changes to `main.json` will not reach it, so re-run the `jq` step after Herdr updates. The custom layout is required: the theme-only variants stack `chrome` to 219-242 (see table).
- **Herdr writes its own files.** `shared.json` (selected layout), `view.json` and `layouts/.state/` are written by the running app, so switching the layout from inside Herdr is the safer way to set it.
- **Light mode.** Untested. The tested theme is dark only (`"appearance": "dark"`). A light theme needs its own `surface` values with the same alpha suffixes, plus solid muted text colours checked on light glass.
- **Window width.** In a narrow window, opening the Files panel pushes the terminal out of view. This is a layout matter, not a glass one; the panel itself measured 0.60.

## ArtCraft Launcher (fallback)

- Binary `/usr/bin/artcraft-launcher` (rpm `artcraft-launcher-0.19.2`), built with eframe/egui, winit and wgpu.
- Tested in a nested niri session: the window is fully opaque (alpha 255 everywhere). It has a dark UI with light text and greyscale app icons.
- No config or theme file exists: only `.instance-token` and logs under `~/.local/share/artcraft-launcher`. The light/dark toggle has no opacity option. Its env vars (`ARTCRAFT_LAUNCHER_LOCALE`, `ARTCRAFT_LAUNCHER_PRETEND_VERSION`, `CRAFT_UPDATE_DEV`, `WINIT_*`) do not control transparency.
- egui transparency (`ViewportBuilder::with_transparent(true)` plus a clear colour with alpha) is set at compile time, so it is out of scope.
- Result: keep the global niri `opacity 0.60` rule, and add no app rule. Text, logos and icons fade with the window. The light-on-dark UI should stay readable, but this was not measured.
- Note: the launcher ignores `--help` and starts normally, including its update check.

## Zed (documented only, unverified)

Zed is not installed. This section comes from the DMS template and Zed's theme schema.

- DMS ships `/usr/share/quickshell/dms/matugen/templates/dank-zed.json`. `configs/zed.toml` writes it to `~/.config/zed/themes/dank-zed-theme.json`.
- The template already holds four themes:
  - "DankShell Dark" and "DankShell Light": `background.appearance: opaque`, solid colours.
  - "DankShell Dark Transparent" and "DankShell Light Transparent": `background.appearance: blurred`, `background: null`, and almost every surface at a single alpha `B6` (0.71). That includes `elevated_surface.background`, so menus and popovers are translucent too.
- The "Transparent" variants are therefore one level, not three. appGlass needs a user copy of the template with per-level alpha:
  - `"background.appearance": "blurred"` (`"transparent"` also works, since niri blurs anyway).
  - `"background"`: clear (`...00` or `null`), so the layers above do not stack.
  - `editor.background`, `terminal.background`, `editor.gutter.background`: `...99` (0.60).
  - `panel.background`, `title_bar.background`, `title_bar.inactive_background`, `status_bar.background`, `tab_bar.background`, `toolbar.background`, `tab.inactive_background`, `tab.active_background`: `...a6` (0.65).
  - `elevated_surface.background`: solid (1.0).
  - `text`, `text.muted` and the other text roles: solid. The shipped `text.placeholder` (`99`) and `text.disabled` (`60`) carry alpha; check them on glass.
  - `element.*` and `surface.background` sit on top of the editor and panels, so check them for stacking.
- Edit the template copy, not `dank-zed-theme.json`: DMS rewrites that file whenever the colours change.
- Alternative: `theme_overrides` in Zed's `settings.json`. Its colours are static, not matugen-driven.
- niri rule, after the global rule:

```kdl
window-rule {
    match app-id="^dev\\.zed\\.Zed$"
    opacity 1.0
}
```

- Expected risks, the same as found in Herdr: built-in alpha on muted text and borders, and backgrounds stacking.
