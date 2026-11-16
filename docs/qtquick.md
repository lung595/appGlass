# Quickshell / QtQuick apps

Dux Files and Dux Calendar already have glass built in. Two JSON keys plus one niri `opacity 1.0` rule give a 0.60 window with opaque text, and the colours follow DMS with no template.
Both work **partially**. The levels are inverted compared with the target (content is never more transparent than the bars), and dropdown menus take the window alpha. DMS's own windows are already glass. Nothing in this category needs the niri fallback.

## Summary

| App | Tested / Documented | Works | Method | niri rule needed |
|---|---|---|---|---|
| Dux Files (`dfiles`) | Tested (two independent runs in a nested niri session) | partial | `~/.config/dfiles/ui-settings.json` keys (merge) | yes, `opacity 1.0` for `dev.duxlabs.files` |
| Dux Calendar (`dcal`) | Tested (two independent runs in a nested niri session) | partial | `~/.config/dankcal/ui-settings.json` keys (merge), then restart the app | yes, `opacity 1.0` for `dev.duxlabs.calendar` |
| DMS's own windows (Settings, modals) | Documented (DMS source and config read, not launched) | yes (already done) | none: DMS paints translucent surfaces itself | already present: `dms-window-opaque` |

"partial" means the glass itself works and text stays opaque, but some target levels can't be reached (see below).

## Levels

Both apps are built on the same QtQuick base as DMS (`DCommon`). The window background (`surface`) gets alpha `floatingWindowTransparency` (w). Panes are drawn **on top** of that background with alpha `floatingWindowForegroundTransparency` (f), so the alphas stack:

```
pane alpha = 1 - (1 - w) * (1 - f)
```

| Surface | Alpha | Target | Reachable? |
|---|---|---|---|
| Window background, header, sidebar, dcal title strip | w | bars 0.65 | yes, any value (tested at 0.60) |
| dfiles file list, search field; dcal toolbar row and month grid | 1-(1-w)(1-f) | content 0.60 | only if it is **at least** w. 0.60/0.0 gives a uniform 0.60, 0.60/0.65 gives 0.86 |
| dfiles preview/details card | 1.0 (fixed) | content 0.60 | no, always opaque |
| dfiles context menu (`FileMenu`) | 1.0 | 1.0 | yes (tested) |
| Tooltips (`inverseSurface`) | 1.0 | 1.0 | yes (code only) |
| dcal `DankPopupMenu`, `MonthDayPopover` | 1.0 | 1.0 | yes (code only) |
| Dropdown menus (`DDropdown`: dcal Repeat/Reminder/Calendar pickers, Settings dropdowns) | w | 1.0 | **no**: they take the window alpha (code only, not captured) |
| Dialog windows (dcal "New event", dfiles Settings, dfiles portal file chooser) | w, fields f-stacked | — | follow the same keys |
| Text, icons, folder logo | 1.0 | never alpha'd | yes, with three exceptions (see "Measured results") |

So "content 0.60 < bars 0.65" can't be reached. The two configurations that make sense are:

- **A, one level:** w 0.60, f 0.0. Everything is 0.60 (153), which matches the niri/DMS glass.
- **B, two levels:** w 0.60, f 0.65. Bars are 0.60 (153), content is 0.86 (219). The content is more opaque, which gives more contrast.

Calculated, not tested: f ≈ 0.125 gives content ≈ 0.65 with the bars at 0.60. That is the target pair, but inverted.

Recommendation: dfiles **A**, dcal **B**. The dcal choice rests on its dimmed day numbers being weak under A (see caveats), and it is provisional until contrast is re-measured.

## Settings

Neither app needs a matugen file. With no `colorSource` set, they read `~/.cache/dms/dms-colors.json` (a watched file) and follow the DMS palette and dark/light mode live. appGlass only writes alpha keys.

### Keys (same schema in both apps)

| Key | Meaning | Default |
|---|---|---|
| `floatingWindowTransparency` | Alpha of the window background, header, sidebar, title strip, dropdown menus and dialog windows | 1.0 |
| `floatingWindowForegroundLayers` | Draw panes as a layer on top of the window | true |
| `floatingWindowForegroundTransparency` | Alpha of those panes (stacks on top of the window alpha) | 1.0 |
| `blurEnabled` | The app requests blur itself (`ext-background-effect-v1` `set_blur_region` over the whole window) | false |
| `themeMode` | `auto` / `dark` / `light`. Leave it at `auto` so the app follows DMS | auto |

The same controls are in each app's Settings page: "Opacity", "Foreground layers" and "Layer opacity". The Settings page writes the same file, so **merge the keys into it and never overwrite it**. Right now there is no `~/.config/dfiles/ui-settings.json` (only `bookmarks.json`), so appGlass creates it.

### Dux Files: `~/.config/dfiles/ui-settings.json` (config A)

Keys as tested:

```json
{
  "floatingWindowTransparency": 0.60,
  "floatingWindowForegroundTransparency": 0.0,
  "floatingWindowForegroundLayers": true,
  "blurEnabled": true
}
```

Merge:

```sh
f=${XDG_CONFIG_HOME:-$HOME/.config}/dfiles/ui-settings.json
mkdir -p "${f%/*}"; [ -s "$f" ] || echo '{}' > "$f"
jq '. + {"floatingWindowTransparency":0.60,"floatingWindowForegroundTransparency":0.0,"floatingWindowForegroundLayers":true,"blurEnabled":true}' \
  "$f" > "$f.new" && cat "$f.new" > "$f" && rm "$f.new"
```

Reload: live. The file is watched, and an edit made while the app ran showed up at once, with no restart.

### Dux Calendar: `~/.config/dankcal/ui-settings.json` (config B)

Keys as tested:

```json
{
  "floatingWindowTransparency": 0.60,
  "floatingWindowForegroundTransparency": 0.65,
  "floatingWindowForegroundLayers": true,
  "blurEnabled": true
}
```

Merge it the same way (path `dankcal/ui-settings.json`, f = 0.65).

Reload: **not live**. Quit and relaunch dcal after writing the file, or change the values in its own Settings page.

### niri rule (both apps)

Without this rule the global "Glass blur" rule (opacity 0.60) multiplies on top: 153 becomes about 92 (0.36), and the text fades with it. Put the rule in a file that is included **after** the global rule, for example `~/.config/niri/appglass.kdl`. Blur stays on from the global rule.

```kdl
window-rule {
    match app-id=r#"^(dev\.duxlabs\.files|dev\.duxlabs\.calendar)$"#
    opacity 1.0
}
```

`~/.config/niri/dms/layout.kdl` already gives these app-ids `background-effect { xray false; }`.

Write the keys and the rule together, and remove them together. If the keys are missing (app reset), the window is opaque. If only the rule is missing, the window is 0.36.

### DMS's own windows: nothing to do

`DFloatingWindow` (Settings, process list, keybinds…) paints `Theme.floatingWindowSurface` = `hostSurface` × `floatingWindowTransparency`. While `floatingWindowSyncGlobal` is true (the default), that value follows `popupTransparency` (0.7 here). Panes use `foregroundLayerTransparency` (0.6 here), which gives about 0.88 combined. The windows request blur themselves, and `~/.config/niri/dms/windowrules.kdl` already has `dms-window-opaque` (`opacity 1.00` for `dev.duxlabs.shell|com.danklinux.dms`). The bar and popouts are layer-shell surfaces, governed by `popupTransparency`, `foregroundLayerTransparency` and `dankBarTransparency` in `~/.config/dms/settings.json`.

## Measured results (tested in a nested niri session)

Alpha is 0–255 (153 = 0.60, 219 = 0.86), measured on real-alpha window screenshots in the user's DMS palette. Both apps were run twice, independently, and the second run reproduced the first run's numbers.

| App, mode, w/f | Whole window min / avg / max | Regions |
|---|---|---|
| dfiles dark 0.60/0.0 (A) | 153 / 186.1 / 255 | header 153, list pane 153 (flat), preview card 255 |
| dfiles dark 0.60/0.65 (B) | 153 / 224.8 / 255 | header 153; list pane, search field, gaps 219; preview card 255 |
| dfiles light 0.60/0.65 | 153 / 224.8 / 255 | header 153, list pane 219, column header 242, preview card 255 |
| dfiles Settings window (A) | 153 / 170.9 / 255 | separate window at the window alpha |
| dfiles context menu (A) | — | fully opaque (exactly `surface_container`, no bleed-through; captured from the screen) |
| dcal dark 0.60/0.65 (B) | 153 / 214.1 / 255 | title strip 153; toolbar row and month grid 219 |
| dcal dark 0.60/0.0 (A) | 153 / 154.8 / 255 | everything 153 |
| dcal "New event" dialog (B) | 153 / 192.1 / 255 | body 153, footer/fields 219 |

Text, icons and logos:

- Glyph cores reach alpha 255 in file names, sizes, item counts, the folder logo, the toolbar glyphs, dcal's title, month name, weekday labels and day digits, and the gear and close icons. Zoomed crops show crisp text with no halo, no black fill and no opaque block.
- Exceptions (text with its own alpha by design):
  - dfiles search placeholder "Search in Files": text alpha about 0.6 (pixel max 214 over 153 glass).
  - dcal dimmed out-of-month day digits: max 237.
  - dcal title-bar fullscreen icon: max 238.
- Contrast: **to re-measure**. The composites used for the first contrast numbers treated the premultiplied screenshots as straight alpha, so their ratios aren't reliable (light themes come out much too dark), and none are quoted here. Over the user's blurred wallpaper in dark mode, every primary text was clearly readable in both apps. The weakest elements are the three exceptions above, plus the dfiles secondary text and the column header in light mode.

## Caveats and known issues

- **Inverted levels.** The bars can't be more opaque than the content (see "Levels"). The dfiles preview card is always opaque.
- **Dropdown menus are translucent.** `DDropdown` uses `menuBackgroundColor = floatingSurface`, which is `surfaceContainer` at the window alpha, so it shows at 0.60 instead of 1.0. This comes from reading the source; an open dropdown couldn't be captured. Context menus and tooltips are opaque.
- **dcal dimmed digits at config A.** The out-of-month day numbers (own alpha up to 237) sit directly on the 0.60 glass, and the early composites flagged them as under 2:1 on bright backdrops, while the grid lines almost vanish. Config B puts the 0.86 pane under them. Re-measure before relying on this.
- **Light mode.** The early composites flagged these as under 2:1 in light mode:
  - dfiles: the column header "Name" (primary colour), the search placeholder and the secondary "0 items" text.
  - dcal: the dimmed digits, the fullscreen icon and the window title.

  These composites are known to make light themes too dark, so this may be an artifact. It is latent anyway: DMS is in dark mode today. Re-measure in light mode before shipping.
- **Placeholder text has alpha.** This breaks the "text never alpha'd" rule, but it only affects hint text.
- **The apps rewrite their config.** The Settings page writes `ui-settings.json`, so always merge keys and never replace the file. A change in the Settings page can overwrite appGlass's values. That is the user's choice.
- **`blurEnabled` and xray.** With `blurEnabled` true, the app asks for blur itself. In the nested niri session (xray on), the blurred floating Settings window hid the main window behind it. On the real session, `dms/layout.kdl` sets `xray false` for these app-ids, which should avoid this, but that wasn't tested there.
- **Rule order (untested).** The `opacity 1.0` rule must come after the global `opacity 0.60` rule. Its placement against the real config wasn't tested in the nested session.
- **Single instance.** Both are Go launchers that unpack their QML into `$XDG_RUNTIME_DIR/<app>-shell/` and run one instance per session. A running instance must be quit, not just reloaded, for dcal to apply new keys. These are native binaries, not flatpaks, so there are no sandbox access issues.
- **Not captured:** the dfiles properties dialog, dropdown menus and tooltips.

## Documented only (not run)

- **DMS windows:** already glass as described above (window 0.70, panes about 0.88, opaque niri rule present). Not launched, because a second DMS instance would register polkit, notification and tray services next to the live shell. Text readability is expected to be fine because these windows use the same `DCommon` surface code as dfiles and dcal, which were tested. **Unverified.**
- **Optional, unverified:** to bring DMS windows to the 0.60 content level, set `floatingWindowSyncGlobal` to false and `floatingWindowTransparency` to 0.60 in `~/.config/dms/settings.json` (the unsynced path in `Theme.qml`).
