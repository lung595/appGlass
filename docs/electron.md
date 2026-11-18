# Electron / Chromium

> **Research notes.** This page records what was tried before appglass shipped its routes, and the findings behind them. What appglass does today for each app is in [routes.md](routes.md); where the two disagree, routes.md is current.

Obsidian gets real glass with three levels (content 0.60, bars 0.65, menus 1.0) from a vault CSS snippet and one niri rule. Text stays opaque, and the snippet needs the `--text-faint` fix below.
appglass now also glasses Discord (through Vencord) and Feishin and VSCodium (through the Electron inspector hook), both on by default once their hidden check passes ([routes.md](routes.md#discord-vencord), [routes.md](routes.md#feishin-and-vscodium-electron-inspector-hook)). The Discord and Feishin rows below are from before those routes. Every other Electron/Chromium/CEF app here (Chrome, Steam, VS Code, Element, Signal, Slack, Spotify) keeps the global niri `opacity 0.60` fallback, because the app's own code never clears its window background.

## Apps

| App | Tested / Documented | Works | Method | niri rule needed |
|---|---|---|---|---|
| Obsidian (flatpak `md.obsidian.Obsidian` 1.15.1, Electron 43.8.9) | Tested in a nested niri session (isolated vault, no network) | partial: yes after a one-line fix (stock snippet leaves faint text under 2:1) | CSS snippet `appglass.css` in each vault, enabled in Settings > Appearance > CSS snippets | `opacity 1.0` for `^md\.obsidian\.Obsidian$`, with the 0.999 blend block (its window says it is opaque; [routes.md](routes.md#obsidian)) |
| Any Electron app (decision rule, Electron 43.8.9) | Tested in a nested niri session (bare Electron binary, own test page) | partial: only if the app's code sets a transparent `backgroundColor` | Nothing you can configure from outside. See [the Electron rule](#the-electron-rule) | Only for apps that pass the rule |
| Google Chrome (flatpak `com.google.Chrome`) | Tested in a nested niri session (temp profile, `--app=` window) | no (alpha 255 everywhere) | None. Fallback | None. Keep the global `opacity 0.60` |
| Discord (stock rpm) | Documented (source read, not run) | no | None. `transparent:false` and an opaque background are hard-coded, and there is no user CSS | None (fallback) |
| Feishin (flatpak `org.jeffvli.feishin`) | Documented (source read, not run) | no | None for glass. `custom.css` can recolour, but the window is opaque | None (fallback) |
| Steam (flatpak, CEF) | Documented (not launched) | no | None. Skins restyle web content only | None (fallback) |
| Vesktop / Vencord desktop / Equibop | Documented (source read, not installed) | partial, unverified | "Transparent window" setting plus alpha in a theme CSS | `opacity 1.0` for `^vesktop$` (unverified app-id) |
| VSCodium 1.143 (flatpak `com.vscodium.codium`) | Tested headless on an isolated install ([apps.md](apps.md)) | yes (on by default, live after its check) | electron hook: the wrapper `appglass-vscodium` starts it with a local Node inspector, `agl-inject.py` loads `agl-hook.js`, which clears the window background and injects `vscode-glass.css`; a marked block in settings.json for the canvas colours | `opacity 1.0` for `^com\.vscodium\.codium$` |
| VS Code (Microsoft build) | Documented (not installed) | no | None out of the box; the same CSS fits, but the hook is only wired for VSCodium | None (fallback) |
| Element / Signal / Slack / Spotify | Documented (not installed) | no | None. No transparency option and no supported user CSS | None (fallback) |

Do **not** add `opacity 1.0` for a fallback app. It would make the window fully opaque, because the app paints alpha 255 itself.

## Levels

| Surface | Target | Obsidian (tested) | Other Electron apps |
|---|---|---|---|
| Content background | 0.60 (alpha 153) | yes, 153 | only as the uniform niri fallback (text fades too) |
| Ribbon / sidebars / tab bar | 0.65 (alpha 166) | yes, 166 | no |
| Status bar, window-control strip | 0.65 | no: 222 / 224 (0.65 stacked over 0.60, cosmetic) | no |
| Menus, command palette, notices, popovers, tooltips | 1.0 | yes, 255 | no separate control |
| Settings window (separate window in Obsidian 1.15) | 1.0 | 255, opaque (not glass) | n/a |
| Text / icons | never alpha'd | text 255; ribbon icons peak at 242 (Obsidian's `--icon-opacity` 0.85) | not achievable (fallback fades them) |

## The Electron rule

Measured with Electron 43.8.9 on niri/Wayland. The test page paints `body { background: rgba(16,20,24,.6) }`:

| BrowserWindow setting | Window alpha |
|---|---|
| no `backgroundColor` (default) | 255, opaque (page blended over white) |
| `backgroundColor: "#ffffff"` | 255 |
| `backgroundColor: "#00000000"` (no `transparent:true`) | 153 (0.60) |
| opaque at creation, then `setBackgroundColor("#00000000")` | 153 |
| `transparent: true` + `#00000000` | 153 (`transparent:true` adds nothing on Wayland) |
| `backgroundColor: "#80000000"` | 204 (window colour and CSS alpha stack) |
| default + `--default-background-color=00000000` | 255 (no effect) |
| default + `--enable-transparent-visuals` | 255 (no effect, X11 only) |
| `#00000000` + `--disable-gpu` | 153 (software compositing still works, no black) |

- An Electron window turns see-through only when the **app's own code** sets a fully transparent background colour, either at creation or later. No flag, env var or theme file can do this from outside.
- Once the window is clear, CSS alpha reaches the compositor unchanged. A full-screen nested shot showed the nested background through the window (content pixel `(112,12,116)` = 0.6·`(16,20,24)` + 0.4·magenta). Glyph cores stay at 255.
- Paint each region exactly once. Nested translucent layers stack (two 0.60 layers come out at about 0.84, then 0.94).
- Native `Menu.popup()` menus and Electron's default menubar are opaque, but they use Chromium's own grey `(47,47,47)` / `(53,53,53)` and CSS can't theme them.
- `getBackgroundColor()` reports `#000000` for a clear window because it drops the alpha. Don't use it to detect transparency.
- Resize, column-width changes and fullscreen left no black areas or stale frames.

## Settings

### Obsidian (tested)

Obsidian's built-in "Translucent window" setting (`appearance.json` key `translucency`) is **macOS only**. On Linux it shows "Not supported on Linux" and does nothing, so leave it off. On its own, Obsidian sets the window background to `#00000000` whenever the page background is not fully opaque. That makes a CSS snippet enough.

**Files (per vault):**

- `<vault>/.obsidian/snippets/appglass.css`, with the content below.
- `<vault>/.obsidian/appearance.json`: `"enabledCssSnippets"` must include `"appglass"`. Turning it on in Settings > Appearance > CSS snippets is safer than editing the JSON by hand:

```json
{ "enabledCssSnippets": ["appglass"] }
```

The vault list is in `~/.var/app/md.obsidian.Obsidian/config/obsidian/obsidian.json` → `.vaults[].path`. For a native install it is `~/.config/obsidian/obsidian.json`.

**Snippet (final, tested):**

```css
/* appGlass for Obsidian (CSS snippet). Alpha on background roles only, text untouched.
   Levels: content 0.60, bars/sidebars 0.65, menus/popups/modals opaque. */
body.theme-dark {
  --ag-content: rgba(16, 20, 24, 0.60);   /* DMS surface */
  --ag-bar: rgba(30, 34, 38, 0.65);       /* DMS surface_container */
  --ag-menu: rgb(40, 44, 48);             /* DMS surface_container_high, opaque */
  --background-primary: var(--ag-content);
  --background-primary-alt: rgba(255, 255, 255, 0.04);
  --background-secondary: var(--ag-bar);
  --background-secondary-alt: var(--ag-bar);
  --titlebar-background: var(--ag-bar);
  --titlebar-background-focused: var(--ag-bar);
  --tab-container-background: var(--ag-bar);
  --ribbon-background: var(--ag-bar);
  --ribbon-background-collapsed: var(--ag-bar);
  --text-normal: #e0e2e8;
  --text-muted: #c2c7cf;
  /* accent text uses DMS primary so it stays readable on bright wallpapers */
  --text-accent: #9acbfa;
  --link-color: #9acbfa;
  --link-external-color: #9acbfa;
  --list-marker-color: #c2c7cf;
  --text-faint: #b4bac3;  /* code comments, chevrons, markdown markers: stock #666 is under 2:1 on glass */
}
/* 1. every full-size layout layer is clear, so alphas never stack */
html, body, .app-container, .horizontal-main-container, .workspace, .titlebar,
.workspace-split, .workspace-tabs, .workspace-tabs .workspace-leaf, .workspace-tab-container,
.workspace-tab-header-container, .workspace-sidedock-vault-profile, .sidebar-toggle-button,
.workspace-ribbon, .workspace-leaf-content, .view-header, .view-content,
.markdown-source-view, .markdown-preview-view, .markdown-reading-view, .cm-editor, .cm-scroller,
.nav-files-container, .status-bar {
  background-color: transparent !important;
}
/* 2. paint each region exactly once */
.workspace-ribbon.mod-left, .workspace-ribbon.side-dock-ribbon, .workspace-split.mod-left-split, .workspace-split.mod-right-split,
.workspace-split.mod-root .workspace-tab-header-container, .status-bar {
  background-color: var(--ag-bar) !important;
}
.workspace-split.mod-root .workspace-tab-container { background-color: var(--ag-content) !important; }
/* 3. floating surfaces opaque */
.menu, .modal, .popover, .hover-popover, .suggestion-container, .tooltip, .prompt, .notice {
  background-color: var(--ag-menu) !important;
}
```

Why it is built this way: setting only the `--background-*` variables stacks the layers, which measured sidebar 224 and content 239. Step 1 clears every full-size layer, and step 2 paints each region once.

**niri rule.** Put it after the global "Glass blur" rule (opacity 0.60, blur on), for example in `~/.config/niri/config.kdl` or a file included from it. Blur stays on from the global rule.

```kdl
window-rule {
    match app-id=r#"^md\.obsidian\.Obsidian$"#
    opacity 1.0
}
```

**DMS colours.** The values above are DMS dark-scheme colours written in by hand: `surface` `#101418`, `surface_container` `#1e2226`, `surface_container_high` `#282c30`, `on_surface` `#e0e2e8`, `on_surface_variant` `#c2c7cf`, `primary` `#9acbfa`. DMS ships **no** Obsidian matugen template (its `matugen/configs/` has none). To follow the wallpaper you would need a user template that writes into each vault's `.obsidian/snippets/`. A proposal (untested) uses 8-digit hex for the alpha (`99` = 153 = 0.60, `a6` = 166 = 0.65):

```css
/* <user templates dir>/obsidian-appglass.css (proposal, untested) */
body.theme-dark {
  --ag-content: {{colors.surface.default.hex}}99;
  --ag-bar: {{colors.surface_container.default.hex}}a6;
  --ag-menu: {{colors.surface_container_high.default.hex}};
  --text-normal: {{colors.on_surface.default.hex}};
  --text-muted: {{colors.on_surface_variant.default.hex}};
  --text-accent: {{colors.primary.default.hex}};
  --link-color: {{colors.primary.default.hex}};
  --link-external-color: {{colors.primary.default.hex}};
  --list-marker-color: {{colors.on_surface_variant.default.hex}};
  --text-faint: #b4bac3;
  /* ...plus the --background-* mappings and rules 1-3 from the snippet above, unchanged */
}
```

```toml
[templates.obsidian_appglass]
input_path = '<user templates dir>/obsidian-appglass.css'
output_path = '<vault>/.obsidian/snippets/appglass.css'
```

`--text-faint` has no tested DMS role. `#b4bac3` passed, and a dimmer `#9aa1ab` failed on white (1.70:1).

**Reload.**

- Obsidian reloads a changed snippet file by itself: an edit showed up within about 4 s, with no restart. A DMS theme change would therefore show up live.
- Turning the snippet off and on in Settings applies live too (255, then 153/166 again).
- A first apply while Obsidian is already running does not turn the glass on until Obsidian restarts (or the snippet is toggled off and on in Settings > Appearance > CSS snippets): Obsidian does not pick up an `enabledCssSnippets` entry added to appearance.json behind its back, and it may later save its settings without it (appglass then keeps it off). Quit Obsidian before the first `appglass apply`; later theme changes only rewrite the snippet file and show up live.
- Cold start: for about 1.2 s the window sits at 214/219 (stacked) before settling at 153/166. No black flash.
- The per-vault window file `<config>/obsidian/<vault-id>.json` stores a `"background"` value. Forcing it to an opaque `#1c1c1c` still gave a translucent window on the next launch. This was not tried on the real profile.
- Launching with the flatpak's own flags gives the same result. No extra flag is needed.

### Fallback apps

Discord, Feishin, Chrome, Steam, VS Code (Microsoft build), Element, Signal, Slack and Spotify: add nothing. They stay under the global "Glass blur" rule (`opacity 0.60`), so their text fades with the window.

## Measured results (tested in a nested niri session)

Alpha values are 0-255, read from niri window screenshots. Contrast ratios below come from the re-check's composites, which unpremultiply the screenshot before blending it over white, the blurred user wallpaper and black (premultiplied-correct). They compare the strongest glyph pixel against the dominant background.

### Obsidian, region alpha

| Region | Alpha |
|---|---|
| Content (editor / reading view) | 153 (0.60) |
| Ribbon, file-explorer sidebar, sidebar header, vault bar, tab bar | 166 (0.65) |
| Status bar | 222 (stacked) |
| Window-control buttons (min/max/close) | 224 (stacked) |
| Code block | 157 (theme tint over content) |
| Active file highlight | 172 |
| Command palette (`.prompt`), file menu (`.menu`), notice, page-preview popover | 255 |
| Tooltip (`.tooltip` element added to the page, not a real hover) | 255 |
| Modal backdrop behind the palette | 189-199 (the theme's dimming layer) |
| Settings window | 255 everywhere, black title bar |
| Snippet disabled | 255 everywhere |
| Frameless shadow margin (~16 px, present with the snippet on or off) | 0-12 |

### Obsidian, readability

| Element | on white | on wallpaper | on black |
|---|---|---|---|
| Paragraph text `#e0e2e8` | 3.73 | 10.2 | 15.1 |
| Internal link `#9acbfa` | 2.83 | 7.63 | 11.5 |
| Code-block language label | 2.61 | 3.68 | 10.7 |
| Ribbon icons | 2.59 | 5.87 | 8.0 |
| Status bar text | 6.36 | 8.27 | 10.3 |
| Code comment, stock `--text-faint` `#666` | **1.31** | **1.28** | 3.16 |
| Folder chevron, stock `--text-faint` | **1.13** | **1.96** | 2.61 |
| Disabled back/forward arrows, stock (opacity on the glyph) | 1.49 | 2.20 | 2.27 |
| Disabled back/forward arrows, opaque in `--text-faint` `#b4b7bc` | 2.40 | 2.72 | 9.74 |
| Code operator, stock `--color-red` `#fb464c` | **1.40** | n/a | 5.67 |
| Code number, stock `--color-purple` `#a882ff` | **1.68** | n/a | 6.81 |
| Code operator, DMS red lifted `#ff98b7` | 2.40 | 2.72 | 9.73 |
| Code number, DMS-derived purple lifted `#ceacd2` | 2.41 | 2.73 | 9.76 |
| Code comment with `--text-faint: #b4bac3` | 2.27 | 3.75 | n/a |
| Folder chevron with `--text-faint: #b4bac3` | 2.27 | 5.14 | n/a |

- Normal, muted and link text has glyph cores at 255 and looks sharp on all three backdrops.
- Ribbon icons peak at 242 but stay readable.
- Obsidian itself has no logos.
- Disabled back/forward arrows: Obsidian dims them with an opacity, which made the glyph itself translucent (under 2:1 on white). The snippet sets `opacity: 1` on disabled icons and dims them by colour (`--text-faint`) instead. The e2e test checks that their brightest pixels are at alpha 255.
- Accent colours: Obsidian's named colours (`--color-red`, `-orange`, `-yellow`, `-green`, `-cyan`, `-blue`, `-purple`, `-pink` and their `-rgb` triplets) drive syntax highlighting (`--code-operator`/`--code-tag` red, `--code-value` purple, `--code-important` orange, `--code-keyword` pink, `--code-function` yellow, `--code-string` green, `--code-property` cyan), callouts, highlights, canvas and mermaid colours. The stock values are under 2:1 on glass over white. The snippet sets all eight, from the DMS terminal palette (red, green, yellow, blue and cyan; purple, orange and pink are mixed from those), and lifts them like the other text over the content, bar, code-block and tab glass. The e2e test checks that code operators and numbers are drawn in those colours, with opaque glyphs at 2:1 or more.

### Electron rule test page

| Region | Alpha |
|---|---|
| Header bar, sidebar | 166 |
| Content | 153 (an empty crop is exactly 153) |
| CSS menu, native `Menu.popup()`, default menubar | 255 |

| Element (white composite) | Contrast |
|---|---|
| Body text `#e0e2e8` | 3.7 |
| Muted `#c2c7cf`, link `#9acbfa` | about 2.8 |
| Faint `#8c9199` | **1.5** (bug) |
| Dark logo `#24292f` on dark glass | **1.3** (bug, almost invisible) |
| Dark text `#202428` on dark glass | **1.25** (bug) |

On black, all light text is at least 6:1. Coloured and light icons stay fully opaque and clear.

### Google Chrome

A `--app=` window on a page with `html { background: transparent }` and an `rgba(...,.6)` body measured alpha 255 everywhere. Fallback.

## What breaks / caveats

- **Faint text.** The stock dark theme's `--text-faint` `#666` is under 2:1 on glass: code comments, folder chevrons and `[[` markers almost disappear on the real wallpaper. Keep the `--text-faint: #b4bac3` line. Any theme with "faint" or "disabled" text and icon roles needs the same remapping.
- **Dark logos and icons on dark glass** come out at about 1.3:1. This is a content issue in any Electron app, and Obsidian is not affected.
- **Stacked spots.** The status bar (222) and the window-control strip (224) sit on top of the content. If you want them at 0.65 too, drop `.status-bar` from rule 2 (it stays cleared in rule 1) and clear the titlebar button container. Untested and cosmetic.
- **Both Obsidian themes, DMS mode.** appglass writes the snippet under `body.theme-dark, body.theme-light` with the colours of the current DMS mode, so Obsidian's own theme setting does not matter (the snippets above are the first dark-only probe). Obsidian hard-codes a few colours that do not follow `--color-*`: the quote/cite callout (`--callout-quote: #9e9e9e`, 1.68:1 over white on dark glass, 1.10:1 over black on light glass) and the notice and tooltip text (`--notice-color` / `--tooltip-color` `#FAFAFA`, drawn for a dark surface in both themes: 1.2:1 on the light DMS menu colour). The snippet sets `--callout-quote` to the lifted muted text, notice and tooltip text to `on_surface` made readable on the menu colour, and an error tooltip's text (`.tooltip.mod-error`) to the error colour made readable on it.
- **Per vault.** Each vault needs its own snippet and has to have it enabled. Community themes that paint their own backgrounds need the same clearing rules.
- **Class renames.** Obsidian updates can rename classes. `.workspace-ribbon.mod-left` had already stopped matching, and `.side-dock-ribbon` is the current class (both are in the snippet).
- **Hard-coded colours** until a user matugen template exists (see above).
- **Not exercised.** A real hover tooltip, the editor link-autocomplete and `<select>` dropdowns were not opened: there was no input-injection tool in the nested session. Autocomplete uses `.suggestion-container`, which the snippet covers, and the palette's suggestion list measured 255.
- **Native menus** in other Electron apps are opaque Chromium grey and can't be themed with CSS.
- **Testing a second Obsidian instance.** Obsidian's CLI socket `$XDG_RUNTIME_DIR/.obsidian-cli.sock` is in the flatpak's shared `xdg-run`, so a second *flatpak* instance takes over the running one's socket. For an isolated test, run the binary from the flatpak's `files/` dir with its own HOME/XDG dirs (`flatpak info --show-location md.obsidian.Obsidian`).
- **Discord rewrites its background colour.** The web app pushes `BACKGROUND_COLOR` into `~/.config/discord/settings.json` over IPC, so editing it by hand does nothing useful, and the window is `transparent:false` anyway.
- **Flatpak paths.** Feishin's `custom.css` lives inside its sandbox config (`~/.var/app/org.jeffvli.feishin/config/feishin/`). Obsidian reads snippets from the vault itself, so no flatpak override is needed for the snippet.

## Documented only (unverified)

None of these were run. The Electron rule above is what decides each one.

- **Vesktop / Vencord desktop / Equibop** (not installed). Vesktop's `src/main/mainWindow.ts` sets `transparent: true` and `backgroundColor: "#00000000"` when the Vencord setting "Transparent window" is on. Per the Electron rule, that background should let CSS alpha through. `transparencyOption` (mica/acrylic) is Windows only and `macosVibrancyStyle` is macOS only. One source read concluded the transparency setting is Windows only, so check it on a real install. Expected method:
  - Settings > Vencord > "Transparent window", then restart.
  - A theme or QuickCSS with alpha: content 0.60, sidebars/header 0.65, popouts/menus/tooltips opaque, with the same "clear every layer, paint each once" rule.
  - DMS already writes `~/.config/vesktop/themes/dank-discord.css`, `~/.config/equibop/themes/dank-discord.css` and `~/.config/Vencord/themes/dank-discord.css` from its `vesktop.css` template (configs `vesktop.toml` / `equibop.toml` / `vencord.toml`). It uses opaque hex values, so it needs alpha variants.
  - Rule: `opacity 1.0` for `^vesktop$`. Check the real app-id with `niri msg windows`.
  - Discord renames classes often, which can break the theme.
- **Discord (stock rpm).** `core.asar` creates the main window with `transparent:false` and `backgroundColor:getBackgroundColor()` (default `#2f3136`). It has no user-CSS mechanism. BetterDiscord, or Vencord on stock Discord, means patching or injecting, which is out of scope. Fallback.
- **Feishin.** Settings > "Enable custom CSS" loads `custom.css`. The file is watched live and sanitised (no `content:`, no `url()`). Its `BrowserWindow` sets neither `backgroundColor` nor `transparent`, so the window stays opaque. It can be recoloured but not made glass. Fallback.
- **Steam (CEF).** Not launched. Skins only change web content, and the window stays opaque. Fallback.
- **VS Code / VSCodium.** The settings alone (`window.titleBarStyle`, `workbench.colorCustomizations`) cannot do it: any alpha there sits on an opaque window. VSCodium is glassed by injection instead: the `vscodium` family (electron hook, wrapper `appglass-vscodium`; on by default, live once its hidden check passes) clears the window background from the main process and injects a workbench stylesheet. The inspector closes right after the injection ([routes.md](routes.md#feishin-and-vscodium-electron-inspector-hook)). VS Code (Microsoft build) is not wired. Fallback.
- **Element / Signal / Slack / Spotify.** No transparency option and no supported user CSS. Element custom themes are colour JSON only, and Spicetify for Spotify is injection. Fallback.
- **Other Chromium browsers.** Same as Chrome: no transparent toplevel. Web content is handled separately by browserGlass.
