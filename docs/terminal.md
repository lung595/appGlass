# Terminals

> **Research notes.** This page records what was tried before appglass shipped its routes, and the findings behind them. What appglass does today for each app is in [routes.md](routes.md); where the two disagree, routes.md is current.

Terminals are the easiest category. Each one draws its own translucent background and keeps glyphs opaque, so the niri rule can be set to `opacity 1.0` and the text stops fading. Alacritty was tested in a nested niri session and works. The rows below marked documented were written before appglass shipped its terminal writers; foot and Konsole (flatpak) are measured since ([routes.md](routes.md#kitty-foot-ghostty-wezterm-konsole)). No terminal needs the global niri opacity fallback, but Konsole and Ptyxis only make the terminal area glass, while their toolkit chrome stays opaque.

## Overview

| App | Tested / Documented | Works | Method | niri rule needed |
|---|---|---|---|---|
| Alacritty 0.17.0 | Tested | yes | `[window] opacity = 0.60`, `transparent_background_colors = false` | `app-id="^Alacritty$"` → `opacity 1.0` |
| kitty | Documented | yes (unverified) | `background_opacity 0.60` | `app-id="^kitty$"` → `opacity 1.0` |
| foot | Documented | yes (unverified) | `alpha=0.60` in the colours section | `app-id="^foot$"` → `opacity 1.0` |
| Ghostty | Documented | yes (unverified) | `background-opacity = 0.60` (+ `background-opacity-cells`) | `app-id=r#"^com\.mitchellh\.ghostty$"#` → `opacity 1.0` |
| WezTerm | Documented | yes (unverified) | `window_background_opacity = 0.60` + `text_background_opacity` | `app-id=r#"^org\.wezfurlong\.wezterm$"#` → `opacity 1.0` |
| Konsole | Documented | partial (unverified) | colour scheme `[General] Opacity=0.6` | `app-id=r#"^org\.kde\.konsole$"#` → `opacity 1.0` |
| Ptyxis | Documented | partial (unverified) | profile `opacity` (GSettings) | `app-id=r#"^org\.gnome\.Ptyxis$"#` → `opacity 1.0` |

Only Alacritty is installed on this machine.

## Levels

Target: content 0.60 (alpha 153), bars 0.65 (alpha 166), menus/popups 1.0, text never alpha'd.

| Surface | Alacritty (tested) | Others (documented) |
|---|---|---|
| Content background | 0.60, measured alpha 153 | 0.60 in all of them |
| Bars (TUI statuslines, segmented prompts, selection, search hits) | **1.0** with `transparent_background_colors = false`, or **0.60** with `true`. 0.65 cannot be set | WezTerm alone has a second value (`text_background_opacity`, e.g. 0.65). kitty's `transparent_background_colors` with per-colour `@alpha` might allow it too. Unverified |
| Tab bar / header | none | kitty tab bar and Ghostty/WezTerm tab chrome: unverified. Konsole and Ptyxis chrome stays opaque |
| Menus / popups | none | Konsole and Ptyxis menus are opaque toolkit widgets |
| Text, cursor | 1.0 (measured alpha 255) | 1.0 (documented) |

In practice a terminal has a single glass level: content at 0.60. TUI bars come out more opaque (1.0) than the content, which is close enough to the "bars more opaque" rule.

## Alacritty (tested)

### Files

| File | Owner | Content |
|---|---|---|
| `~/.config/alacritty/dank-theme.toml` | DMS (matugen template `dmsalacritty`, `/usr/share/quickshell/dms/matugen/templates/alacritty.toml`) | colours only, no opacity. Rewritten on every theme change: do not edit |
| `~/.config/alacritty/alacritty.toml` | user | imports the DMS file. Opacity and palette overrides go here |
| niri config (e.g. `~/.config/niri/dms-browser-glass.kdl`) | user | per-app `opacity 1.0` rule |

DMS colours are reused as-is through `general.import`. Alacritty's main file overrides everything it imports. This matters on this machine: the current `~/.config/alacritty/alacritty.toml` hard-codes `opacity = 1.0` in `[window]`, and that line must be changed or removed. An `opacity` key in an imported file is ignored while the main file sets one.

### alacritty.toml

This is the tested config. Paths are adapted from the test.

```toml
[general]
import = ["~/.config/alacritty/dank-theme.toml"]

[window]
opacity = 0.60

[colors]
transparent_background_colors = false

# Readability overrides for glass. Must come after the import (the main file wins).
# Values are the matugen roles of the current DMS theme (dark):
[colors.normal]
black   = '#8c9198'   # colors.outline
magenta = '#d2bfe6'   # colors.tertiary

[colors.bright]
black   = '#c2c7cf'   # colors.on_surface_variant
```

`window.blur` is not needed. niri's global rule already blurs the background, and the Alacritty key only works on macOS and KDE.

The hex overrides above are fixed values, so they go stale when the wallpaper changes. To follow DMS, generate them with a user matugen template (proposal, not tested):

```toml
# template, output e.g. ~/.config/alacritty/appglass.toml
[colors.normal]
black   = '{{colors.outline.default.hex}}'
magenta = '{{colors.tertiary.default.hex}}'

[colors.bright]
black   = '{{colors.on_surface_variant.default.hex}}'
```

Import it after `dank-theme.toml` (`import = [".../dank-theme.toml", ".../appglass.toml"]`), and keep the palette keys out of the main file. The list should also cover the entries the re-check found below 2:1 on a white backdrop (color1 and dim text, see below). No colour has been chosen for those yet.

### Reload

Live reload: Alacritty applied changes to `opacity`, `transparent_background_colors` and the palette in a running window, with no restart. Nothing runs in the background and there is no runtime cost.

### niri rule

Place this after the user's global "Glass blur" rule (`opacity 0.60` + `background-effect { blur true }`), for example in a file included after `dms/windowrules.kdl`:

```kdl
window-rule {
    match app-id="^Alacritty$"
    opacity 1.0
}
```

Blur stays on from the global rule. Tested: with the rule in place, the result is identical to Alacritty alone.

The rule and the Alacritty key are needed together:

- Without the Alacritty key you get the global 0.60 on everything, text included (today's look).
- With the Alacritty key but without the niri rule, the two opacities multiply: the background measured alpha 92 (0.36) and text at most 153.

## Measured results (Alacritty, tested in a nested niri session)

Window screenshots are premultiplied RGBA. A background pixel reads (10,12,14,153), which is #101418 at 0.60. The contrast figures below come from a premultiplied-correct composite of the window over the blurred wallpaper, a white backdrop and a black backdrop.

### Alpha per region (0-255)

| Case | Config | min / avg / max | Empty bg | Glyphs | Explicit-bg cells, reverse bar |
|---|---|---|---|---|---|
| Today | Alacritty 1.0 + niri 0.60 | 153 / 153 / 153 | 153 | **153 (faded)** | 153 |
| Recommended | Alacritty 0.60, tbc=false, niri rule 1.0 | 153 / 157.4-159.2 / 255 | 153 | up to 255 | 255 |
| All glass | Alacritty 0.60, tbc=true, niri rule 1.0 | 153 / 154.2 / 255 | 153 | up to 255 | 153 |
| No niri rule | Alacritty 0.60, niri 0.60 | 92 / - / 153 | 92 | at most 153 | - |

The background really is see-through on the output. A full-output screenshot shows the nested backdrop colour through the window, and the text stays untinted. With today's setup the text itself is tinted by the backdrop.

### Text and readability

- Glyph cores reach alpha 255 with their exact colour, e.g. red at (207,128,251,255). Antialiased edges blend between 153 and 255: in a normal text line about 2% of pixels reach 255 and about 18% sit between 153 and 254. Thin regular-weight text looks slightly lighter than on an opaque window, but it is far better than today's maximum of 153.
- The cursor is opaque (255).
- The default foreground #e0e2e8 measures 4.24-10.5 on the wallpaper composite and 3.73 on white, so it passes.
- In the recommended config, explicit-background cells are solid blocks on the glass, which looks like an intentional statusline. With tbc=true the reverse-video bar becomes a 60% grey band with dark text: readable but muddy.
- Logos and icons: terminals have none of their own. Nerd Font icons and emoji were not tested (no Nerd font in the test home, and emoji did not render).

### Contrast of the DMS dank16term palette on glass (dark theme)

| Entry | Colour | On glass (wallpaper) | On white backdrop | Verdict |
|---|---|---|---|---|
| color0 black | #101418 (= background) | invisible (equals bg) | - | bug |
| color5 magenta | #1e567e (primary_container) | **1.16-1.73** | - | bug |
| color8 bright black (comments, autosuggestions) | #3e4347 | **1.11-1.82** | - | bug |
| color1 red | #cf80fb | 2.13 on the lightest patch | **1.87** | bug on light backdrops |
| dim text (SGR 2) | about #9a9ca1 | 2.00 on the lightest patch | **1.76** | bug on light backdrops |
| color4 blue | #7fb7ed | - | 2.28 | borderline |
| default fg | #e0e2e8 | 4.24-10.5 | 3.73 | ok |

With the three overrides in place (normal black = outline, magenta = tertiary, bright black = on_surface_variant), every ANSI colour was readable on the wallpaper composite. The first test run measured black 2.2-3.3, magenta 4.2-6.1 and bright black 4.2-6.2 on glass. A second, independent run did not re-measure these overrides. color1 and dim text are not covered by the fix.

## What breaks / caveats

1. **Palette entries unreadable on glass.** color0, color5 and color8 from DMS dank16term fall below 2:1 on glass (table above). color1 and dim text fall below 2:1 over light parts of the wallpaper. The palette needs overrides; the ones above cover only part of it. One side effect: programs that paint a `black` background get a light grey block instead of a black one. `color7` (#eff8ff) with white text was already unreadable before glass.
2. **Explicit default-colour backgrounds turn opaque.** With tbc=false, a cell painted with a truecolor background equal to the default (#101418) is drawn at alpha 255 as a dark block. A Neovim or Helix colourscheme that sets `Normal` bg makes the whole editor opaque. DMS also ships a neovim template. Fixes: a transparent background in that app (Neovim `Normal guibg=NONE`), or tbc=true, which also makes the bars 0.60.
3. **No 0.65 level.** Alacritty has only two background values: 0.60 for the default background, and 1.0 (or 0.60) for explicit backgrounds.
4. **The main config overrides imports.** The hard-coded `opacity = 1.0` in `~/.config/alacritty/alacritty.toml` wins over any imported file. A generated appGlass file cannot set the opacity on its own.
5. **Light mode not tested.** All measurements use the dark DMS theme. On light glass, dark text over a dark wallpaper is likely to need its own palette check.
6. **Not tested:** real mouse/keyboard selection (emulated with an escape-coded background; expected to follow the explicit-bg rule), the search/hint footer bar, and Nerd Font icons and emoji.
7. **App-id:** the rule matches the default app-id `Alacritty`. A window started with `--class` needs its own match.

## Documented only (not tested, unverified)

These apps are not installed. Everything below comes from upstream documentation, not from a test run. The palette contrast issue above applies to every terminal that uses the DMS dank16term colours.

### kitty

- `kitty.conf`: `include dank-theme.conf` and `background_opacity 0.60`. This sets the alpha of the default background only; text stays opaque.
- `dynamic_background_opacity yes` allows runtime changes (`kitten @ set-background-opacity`).
- Newer versions have `transparent_background_colors` with a per-colour `@alpha`, which might give statuslines their own level (e.g. 0.65).
- Tab bar: `tab_bar_background` / `tab_bar_margin_color`. Whether it follows `background_opacity` is unverified.
- DMS writes `kitty/dank-theme.conf` and `kitty/dank-tabs.conf`, both colours only. The opacity key goes in `kitty.conf`.
- `background_blur` works on macOS and KDE only and is not needed with niri.
- niri: `match app-id="^kitty$"`, `opacity 1.0`.

### foot

- `alpha=0.60` in the colours section. DMS writes `[colors-dark]` in `foot/dank-colors.ini`, so the key goes in that section (`[colors]` on older foot). `foot.ini` includes it with `include=dank-colors.ini`.
- Newer foot has an option that decides whether explicit-bg cells are translucent too (`alpha-mode`; exact name and version unverified).
- No tab bar, no menus.
- niri: `match app-id="^foot$"`, `opacity 1.0`. footclient windows use the same app-id.

### Ghostty

- `background-opacity = 0.60`, plus `background-opacity-cells = true` (newer versions) to make explicit-colour cells translucent as well.
- DMS writes `ghostty/themes/dankcolors`, colours only. In the main config, set `theme = dankcolors` plus the opacity key.
- The GTK/libadwaita header and tabs may not follow `background-opacity`. With `gtk-titlebar = false` and niri `prefer-no-csd` there is no chrome.
- Single-instance by default on Linux (`gtk-single-instance`).
- `background-blur` works on macOS and KDE only.
- niri: `match app-id=r#"^com\.mitchellh\.ghostty$"#`, `opacity 1.0`.

### WezTerm

- `wezterm.lua`: `window_background_opacity = 0.60` for the content, and `text_background_opacity` (default 1.0) for explicit-bg cells. These are two independent levels (e.g. 0.60 and 0.65), which no other terminal here offers.
- DMS writes `wezterm/colors/dank-theme.toml`, used through `color_scheme = "dank-theme"` and `color_scheme_dirs`.
- Whether tab bar colours (`colors.tab_bar`, `window_frame`) accept alpha is unverified. `hide_tab_bar_if_only_one_tab = true` avoids the question.
- Hot reload. `kde_window_background_blur` works on KDE only.
- niri: `match app-id=r#"^org\.wezfurlong\.wezterm$"#`, `opacity 1.0`.

### Konsole (partial)

- Profile colour scheme `~/.local/share/konsole/<name>.colorscheme`, `[General] Opacity=0.6`. `Blur=true` works with KWin only.
- Only the terminal area becomes glass. Menus, tab bar and toolbar are opaque Qt widgets.
- DMS has no Konsole template (its `kcolorscheme` covers Qt widget colours, not the terminal scheme). Supporting it would need an appGlass template that writes a `.colorscheme`.
- niri: `match app-id=r#"^org\.kde\.konsole$"#`, `opacity 1.0`.

### Ptyxis (partial)

- Profile opacity: GSettings `org.gnome.Ptyxis.Profile` key `opacity` (0..1), also under Preferences > Profile.
- Only the terminal area becomes glass. The libadwaita header bar and tabs stay opaque (no documented key).
- DMS has no template; Ptyxis uses its own `.palette` files.
- niri: `match app-id=r#"^org\.gnome\.Ptyxis$"#`, `opacity 1.0`.
