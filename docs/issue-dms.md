# Per-app glass: alpha on app backgrounds by level instead of fading whole windows

## Problem

The usual way to get glass on niri + DMS today is the "Glass blur" window rule in `dms/windowrules.kdl` (`opacity 0.60`, blur on). niri applies that opacity to the whole window, so text, icons and logos are drawn at 0.60 together with the background and are tinted by whatever is behind the window. In Alacritty, for example, glyphs measure alpha 153 of 255 under that rule instead of 255.

DMS already has the numbers: `foregroundLayerTransparency`, `popupTransparency`, `dankBarTransparency` and the floating-window settings in `~/.config/dms/settings.json`. DMS uses them for its own surfaces (bar, popouts, Settings), and `dms-window-opaque` already sets `opacity 1.00` on DMS windows because they paint their own glass. Other apps never get these values: the matugen templates DMS runs (`dank-colors.css`, `dank-theme.toml`, ...) carry colours without background alpha, so a window-wide opacity is the only option left.

## Proposal

Move the alpha into the colour files DMS already generates, on background roles only, and set the niri opacity of those apps back to 1.0.

1. **Alpha by level**, the same levels for every app:

   | Level | Alpha | Surfaces |
   |---|---|---|
   | Content | DMS `foregroundLayerTransparency` (0.60 here) | window / view / editor / terminal background |
   | Bars | `max(content, 0.65)` | header bars, tab bars, sidebars, toolbars, status bars |
   | Popups | 1.0 | menus, popovers, tooltips, dialogs, command palettes |
   | Text | 1.0, never alpha'd | text, icons, logos |

   Alphas stack: a bar painted on top of the 0.60 content needs `(0.65 - 0.60) / (1 - 0.60) = 0.125` to land at 0.65. Painting it at 0.65 gives 0.86.

2. **Generate it from the matugen templates DMS already runs.** Background roles get the alpha of their level; text roles do not. Some text colours that are fine on an opaque window are too faint on glass (dank16term color0/5/8, Adwaita's `--dim-opacity` 0.55, Obsidian's `--text-faint` `#666`), so text roles are made solid and moved toward white (dark scheme) or black (light scheme) until they reach 2.25:1 over any backdrop from black to white. Under 2:1 counts as a bug.

3. **A niri window rule `opacity 1.0` for each app that paints its own alpha**, matched on its app-id, in a file included after `dms/windowrules.kdl`. Later rules win, and blur stays on from the global rule. This is the same pattern as `dms-browser-glass.kdl`:

   ```kdl
   // ~/.config/niri/config.kdl, after: include "dms/windowrules.kdl"
   include optional=true "appglass.kdl"
   ```

   ```kdl
   // ~/.config/niri/appglass.kdl
   window-rule {
       match app-id=r#"^Alacritty$"#
       match app-id=r#"^org\.gnome\.Nautilus$"#
       // ... one match per glass app
       opacity 1.0
   }
   ```

   The rule and the app-side alpha go together. App alpha without the rule multiplies with the global 0.60 (content 0.60 becomes 0.36, text at most 0.60). The rule without app alpha makes the window fully opaque.

4. **Re-run on every theme change.** In the POC this is a user matugen template whose `post_hook` re-applies, so it runs whenever DMS runs the user templates ("Run user templates", on by default).

5. **Opt-out respected.** Anything the user takes out stays out on later theme changes: the niri include line, a deleted `gtk.css` or a removed glass import in it, an Obsidian snippet turned off, `GTK_THEME` removed from a launcher, another Herdr layout selected, a Dux key removed.

6. **Fallback.** An app that cannot paint its own alpha gets no rule and keeps the global `opacity 0.60`, as today.

## How the POC does it

POC: <!-- link to the appGlass repo -->

A small Python CLI with one module per app family (Alacritty, GTK4, GTK3, Obsidian, Dux, Herdr). It reads the colours from its own matugen output (else `~/.cache/dms/dms-colors.json`) and the content level from `foregroundLayerTransparency` (0.60 when unset).

```sh
appglass apply [--only gtk4,alacritty] [--dry-run]   # write the glass files for the installed apps + the niri rule
appglass remove [--only ...]                         # undo every file it touched
appglass status [--json]                             # colours, levels, applied families, app routes
appglass detect --json | apply --all [--dry-run]     # detected toolkits; apply every app with an adapter
appglass hook install | remove                       # matugen user template + post_hook
```

- `apply` plans every write first, then writes, and records each file in a state file. On `remove`, files it created are deleted, files it edited are restored byte-identical from a backup, and merged JSON keys are put back. If the user changed an edited file since, only appglass's part is taken out.
- The niri rule goes into `~/.config/niri/appglass.kdl`, and the include line goes right after the `dms/windowrules.kdl` include. After a change, `niri validate` runs; if it fails, the rule is taken out again.
- `hook install` adds a `[templates.appglass]` section to `~/.config/matugen/config.toml`. matugen renders a colours JSON and runs `appglass apply --from-hook --quiet`, which refreshes only the families already applied, and does nothing before the first manual `apply`.
- An existing user file is merged into or edited, never replaced. A GTK4 `gtk.css` that holds more than the DMS import line is left alone, and the family is skipped with a warning.
- 286 unit tests cover the generated files, the state handling and remove. Each family also has an end-to-end script that runs the app in a nested niri session, checks the window alpha per region, opaque glyphs and at least 2:1 text contrast from window screenshots, then checks that `remove` leaves the files byte-identical.

## Apps

"Tested" means run in a nested niri session with the alpha measured from window screenshots; "(expected)" means from docs and sources only. The full table (52 rows) and per-toolkit details are in the POC's `docs/`.

| App | Toolkit | Method | Levels (content / bars / popups) | Result | Notes |
|---|---|---|---|---|---|
| Alacritty 0.17.0 | terminal | `[window] opacity` = content, `transparent_background_colors = false`, imported after `dank-theme.toml`; palette overrides | 0.60 / explicit-bg cells (statuslines) 1.0, no 0.65 / no popups | yes | Live reload. The main `alacritty.toml` wins over imports, so its own `opacity` line is commented out |
| Nautilus 51.1 | GTK4 / libadwaita | `gtk-4.0/gtk.css` imports `dank-colors.css` + a generated `dank-glass.css` (alpha on bg roles, `dialog sheet` rule, `--dim-opacity: 0.80`, `:backdrop` filter fix) | 0.60 / 0.65 (sidebar) / 1.0 | yes | The content headerbar is flat by libadwaita design, so it stays at 0.60. No live reload |
| GNOME Software, file-chooser portal, Zenity | GTK4 / libadwaita | same `gtk.css` | 0.60 / 0.65 / 1.0 (expected) | yes (expected) | Installed, not launched. Need the rule because `gtk.css` is global |
| GNOME Web 51 | GTK4 + WebKitGTK | same `gtk.css` | page 1.0 (no content level) / 0.65 / dialogs 1.0 | partial | Chrome only, the page stays opaque |
| Solaar 1.1.20 | GTK3 | per-app theme `AppGlass` (Adwaita + `dank-colors.css` + glass rules) via `GTK_THEME` in launcher/autostart overrides | 0.60 / 0.65 / 1.0 | yes | About dialog body stayed opaque in the test (the POC adds a `dialog` rule, not re-measured). Restart to pick up colours |
| nvidia-settings | GTK3 | same theme + notebook add-on | 0.60 / 0.65 / 1.0 | partial | Column-header text was too faint with the add-on (the POC sets a solid colour, not re-measured) |
| Obsidian 1.15.1 (flatpak) | Electron | vault CSS snippet: clear every layout layer, paint each region once; text and accent colours lifted | 0.60 / 0.65 (status bar 0.87, stacked) / 1.0 | partial | Stock `--text-faint` is under 2:1 and is replaced. Measured in dark mode only |
| Dux Files | QtQuick | merge `floatingWindowTransparency` 0.60, `floatingWindowForegroundTransparency` 0.0 into `ui-settings.json` | 0.60 (preview card 1.0) / 0.60 / context menu 1.0 | partial | Live. Levels inverted (see below); dropdowns take the window alpha |
| Dux Calendar | QtQuick | same keys, foreground 0.65 | 0.86 / 0.60 / popup menus 1.0 | partial | Restart needed. Levels inverted; dropdowns take the window alpha |
| Herdr 0.1.16 | gpui | theme with `#rrggbbaa` colours + a glass copy of the main layout, selected in `shared.json` | 0.60 / 0.65 / 1.0 | partial | Live reload. ANSI 0/8 were unreadable in the tested hand-made theme; the POC derives them from DMS roles and lifts them, not re-measured in the docs |
| DMS windows | QtQuick | none, DMS paints them | already glass (window 0.70, panes about 0.88) | yes (expected) | `dms-window-opaque` already present |
| kitty, foot, Ghostty, WezTerm, Zed | terminal / gpui | per-app opacity key, or an alpha copy of `dank-zed.json` | 0.60 (Zed: all three levels) (expected) | yes (expected) | Not in the POC |
| VSCodium (flatpak) | Electron | electron hook (opt-in wrapper `appglass-vscodium`): window background cleared from the main process, workbench CSS injected | 0.60 / 0.60 / 1.0 | yes (opt-in) | The Node inspector stays open on 127.0.0.1 while it runs |
| Chrome, Discord, Feishin, Steam, VS Code (Microsoft build), Element, Signal, Slack, Spotify | Electron / CEF | none | global 0.60 | no (fallback) | The app's code has to clear its window background; no flag or theme does it |
| VLC, Jellyfin, KDE apps, KeePassXC, Krita, OBS, qBittorrent | Qt Widgets (Jellyfin: QML) | none | global 0.60 | no (fallback) | Palette alpha lands on an opaque buffer; would need a style plugin (Kvantum). Jellyfin's QML is compiled in |
| Lian Li Linux, LocalSend, ArtCraft Launcher | Tauri / Flutter / egui | none | global 0.60 | no (fallback) | Transparency is compiled in or must be set by the app |
| Timeshift, GIMP, LibreOffice, Thunderbird | GTK3 / own UI | none | global 0.60 | no (fallback) | Root via XWayland (Timeshift) or opaque own surfaces |

"partial" means the glass works and text stays opaque, but some target levels are missed or a readability fix is still open.

## Limits / open questions

- **Light mode is tested less.** Every screenshot measurement used the dark DMS scheme. The generators handle light mode (unit tests use a light palette), but light-mode contrast in real windows is still to be measured.
- **GTK4 `gtk.css` is global.** `~/.config/gtk-4.0/gtk.css` reaches every GTK4 app, so every one the user runs needs the `opacity 1.0` rule, or it ends up at 0.36 background with text at 0.60. That includes the file-chooser portal used by Chrome and Electron apps. Flatpak GTK4 apps do not read it at all without a filesystem override. GTK3 avoids the problem with a per-app `GTK_THEME`.
- **Obsidian needs a restart on first enable.** Obsidian does not pick up a snippet added to `appearance.json` while it runs (toggling the snippet off and on in its settings also works), and it may later save its settings without it. Later theme changes only rewrite the snippet file, which Obsidian reloads live.
- **Apps that need a restart after a theme change:** GTK3 and GTK4 apps (GTK reads the CSS at start; Solaar is a long-running tray process), Dux Calendar. Alacritty, Dux Files, Herdr and the Obsidian snippet reload live.
- **Dux levels are inverted.** Panes are drawn on top of the window background, so content can never be more transparent than the bars. Dux Files uses one level (0.60 everywhere); Dux Calendar uses 0.60 bars and 0.86 content for its dimmed day numbers. A foreground value of about 0.125 would give 0.60 / 0.65 inverted (calculated, not tested). Dropdown menus take the window alpha instead of 1.0 (from the source, not captured).
- **Measured minimum contrasts** (premultiplied-correct composites, dark mode). The generated text colours target 2.25:1 over any backdrop, and the end-to-end checks fail under 2:1. Lowest measured values:
  - GTK3 (Solaar) insensitive label: 2.26 on white.
  - Obsidian after the fixes: code comment and folder chevron 2.27 on white; disabled arrows and code operators 2.40 on white. Stock `--text-faint` was 1.13-1.31 on white.
  - Alacritty default foreground: 3.73 on white. Stock dank16term color0/5/8 fall below 2:1 on glass; color1 (1.87) and dim text (1.76) fall below it on white. The POC lifts those too; not re-measured in the docs.
  - GTK4 and Dux: to re-measure (only early, uncorrected composites exist).
- **Dark logos** drawn by an app (`#111`, `#24292f`) disappear on dark glass, about 1.3:1. CSS cannot reach them.
- **NVIDIA WebKit workarounds** (`WEBKIT_DISABLE_DMABUF_RENDERER=1`, `WEBKIT_DISABLE_COMPOSITING_MODE=1`) make a transparent WebView window nearly invisible (alpha about 0).

## What would be needed in DMS

- **A setting**, for example "App glass" in the theme settings, with a per-app opt-in. Content follows `foregroundLayerTransparency`, bars `max(content, 0.65)`, popups opaque.
- **Alpha variants of the existing matugen templates** (or extra templates next to them): background roles with the level alpha, text roles solid and readable on glass (solid dim/faint colours, dank16term 0/5/8 replaced). For GTK4 this is a separate glass file imported after `dank-colors.css`; for terminals an opacity key next to the theme import.
- **A generated niri rules file** with `opacity 1.0` for the opted-in apps, included after `dms/windowrules.kdl`, like `dms-browser-glass.kdl`.
- **Templates for apps DMS does not theme today** where it pays off (Obsidian snippet, Herdr theme), or a documented way for user templates to get the level values.

I am happy to turn the POC into a PR in whatever shape fits DMS, or to keep it as a plugin if that is preferred.
