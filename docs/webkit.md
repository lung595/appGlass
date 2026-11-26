# Tauri / WebKitGTK

> **Research notes.** This page records what was tried before appglass shipped its routes, and the findings behind them. What appglass does today for each app is in [routes.md](routes.md); where the two disagree, routes.md is current.

Every host WebKitGTK app built on GTK3 and WebKitGTK 4.x whose window is one WebView (the Tauri / wry apps such as Lian Li Linux, and Kiri, which builds its GTK3 window and view itself) takes one route, the WebKit shim (measured on Kiri and Lian Li only; any other app is documented, not run): a preload that clears the WebView background, gives the window an alpha visual and adds page CSS and a small page script. An app with native widgets beside its WebView (a mail client) stays opaque. Lian Li Linux keeps its own CSS (family `lianli`); any other such app takes the generic family `webkit`, found by its toolkit, not by a list. GNOME Web (GTK4, WebKitGTK 6) gets glass chrome from the GTK4 `gtk.css` and an `opacity 1.0` rule, and its page stays opaque.
A Tauri/wry app that is *built* with `"transparent": true` and rgba page CSS reaches all three levels (0.60 / 0.65 / 1.0, tested with a demo that makes the same calls as wry). It needs a niri `opacity 1.0` rule, and it breaks under the usual NVIDIA WebKit env workarounds.

## Overview

| App | Tested / Documented | Works | Method | niri rule needed |
|---|---|---|---|---|
| Kiri 0.2.1 (`kiri-window`, Rust, its own GTK3 window around one webkit2gtk-4.1 view; no wry, tao or Tauri) | Tested (nested niri, e2e `tests/e2e/webkit.sh`) | yes | family `webkit`: `appglass-wk.so` + `webkit-glass.css` + `webkit-glass.js`, found by its toolkit | `opacity 1.0` on `^kiri$`, with the 0.999 blend block (written by appglass: its GTK3 window says it is opaque) |
| Any other host GTK3 WebKitGTK 4.x app whose window is the WebView | Documented (same route, not run on another app) | expected, after its check | family `webkit`, as for Kiri | `opacity 1.0` on its app-id (written by appglass) |
| Lian Li Linux (`lianli-gui`, Tauri 2 / wry / webkit2gtk-4.1) | Tested (nested niri, its daemon hidden, e2e `tests/e2e/lianli.sh`) | no, opaque unless you switch it on: the shim paints the glass, but its hidden check cannot judge it (with the daemon hidden it shows its "Waiting for daemon" dialog and a scrim, background about 202 on 1.3.0), so the check is unverifiable, and an unverifiable check keeps your switch | family `lianli`: the same shim, with its own CSS from its theme variables | `opacity 1.0`, with the 0.999 blend block (written by appglass) |
| Tauri/wry app built with `"transparent": true` (demo that replicates wry) | Tested (demo only, no shipped binary) | partial | The app paints alpha itself: RGBA visual, app-paintable window, WebView background rgba 0, and rgba CSS per level | `opacity 1.0` on its app-id |
| GNOME Web / Epiphany 51 (GTK4 + webkitgtk-6.0 2.54.2) | Tested | partial (chrome only) | libadwaita colour roles in `gtk-4.0/gtk.css` (the GTK4 glass file). The page always stays opaque. | `opacity 1.0` on `^org\.gnome\.Epiphany(\.WebApp_.*)?$` (the gtk4 family's rule) |
| WebKitGTK 6 (GTK4) apps, WebKitGTK flatpaks (Cinny, ...) | Documented | no | the shim's window code is GTK3, and a host-built preload does not load in a flatpak runtime: fallback, with the reason in `appglass status` | Fallback per app-id |
| Geary, Evolution mail view, Yelp, GOA web views | Documented (the shape tested with a test app) | no | GTK4 ones have no route. GTK3 ones take the generic route, but the shim leaves a WebView with native widgets beside it opaque, so the check fails and the app stays opaque: a test app (header bar, two native label columns, one WebView) in the harness looked as plain and its `appglass verify` failed | Fallback per app-id |

## The generic route (family `webkit`)

- **Who:** an app whose launcher's binary links `libwebkit2gtk-4.0` or `-4.1` and `libgtk-3` (`appglass detect` prints `webkitgtk` with both libraries as evidence), not a flatpak, not a launcher of yours alone, not a launcher whose command is a script or `env` with an option (the preload would not reach the app, see Launchers; `appglass status` names it), not a game launcher, not a password app. Lian Li takes its own family first.
- **Gate:** it loads code into the app, so each app waits for its hidden check (per app and version; a WebKitGTK update, the `libwebkit2gtk-4.x` file the binary links, counts as a new version too; the first apply of this version adds the library to the fingerprint of every WebKitGTK app, so a Lian Li that is live because it passed its check is checked once more, and runs plain until that check passes), or goes live at once when you switch it on yourself (Settings > Apps, or `apps.<key>.enabled` in `settings.json`), until its check runs: a failed check makes it opaque again (an unverifiable one keeps your switch; Lian Li's always is). An app held opaque gets its plain launcher back, and an app you switch off loses its preload at the next launch. An app updated since its check is "stale": its launcher and its check record stay, and the wrapper starts it plain until the new check passes.
- **The check:** the app runs in the hidden session with no network and the `/run` entries its binaries name hidden (Kiri does not reach `/run/kiri/docker.sock`; see [engine.md](engine.md)). Kiri is seeded past its language prompt (`~/.kiri/ui.json` in the throwaway HOME), so the check sees the page after it, its setup screen (no container engine in the harness): in `tests/e2e/webkit.sh` Kiri waits at default settings, `appglass verify kiri` passes (background 153, about 8900 opaque text px) and the next apply gives it the glass launcher. Another app gets no seed: its first-run screen is what is judged.
- **Launchers:** `Exec=app ...` and `Exec=env VAR=val ... app ...` (the wrapper makes the plain assignments and starts the app itself) get the glass. `Exec=env -u VAR app` (any option to `env`) is refused with its reason: `env` would stay the first process, the shim would load in it and scrub itself, and the app would run plain. A launcher that starts a shell script which then starts the app does not: the shim stays in the first process it loads in (here the shell) and takes itself and every `APPGLASS_*` variable (its paths, the hidden check's, the e2e's) out of that process's environment array before `main`, so the script's app and every other child start plain. It edits the array itself, not through `unsetenv`: bash exports its own `getenv`/`setenv`/`unsetenv`, which at that point do not reach the environment it builds its children from (`tests/test_scrub.py` runs a bash parent that spawns a child). Point a launcher of your own at the binary instead. A launcher of yours at the override's place (`~/.local/share/applications/<desktop id>`, with a system one beside it) is left as it is: the app runs plain through it, so `appglass status` shows it opaque (fallback), names the file and lists it as the app's conflict; move it away and apply (Lian Li's: `appglass adopt` it).
- **Writes:** `appglass-wk.so` built with `gcc` in `~/.local/lib/appglass/webkit/` (with its source, `webkit-glass.css.tmpl`, `webkit-glass.js` and the rendered `webkit-glass.css`), the wrapper `~/.local/bin/appglass-webkit` and one launcher override per app: `Exec=appglass-webkit <key> <the app's own Exec>`. The wrapper renders the CSS from `appglass levels` at every start and preloads the shim for that one launch (its children, a shell's included, do not inherit it).
- **The shim:** on the first `webkit_web_view_load_uri/html/request/bytes` it clears the WebView background and, once the view is in a window (wry builds the view first), gives the GTK3 toplevel an RGBA visual. It adds `webkit-glass.css` as a user stylesheet, `webkit-glass.js` at document end (top frame), the paint script (below), and the focus script that sets `html.agl-inactive` while the page has no focus. It turns a hardware acceleration policy of NEVER into ALWAYS and WebKit's damage features off on the view (a partial frame without compositing would leave the clear page bare but for the damaged rects, [routes.md](routes.md#any-webkitgtk-app-generic-webkit-shim)). When the window maps, again whenever a widget in it maps or unmaps (once per main-loop turn), and at a view's first document, it looks at what else is drawn, for every WebView of the window (in a stack of views, the page shown can fill it): the window is glassed (app-paintable, once the page has painted: a script at document end posts to a message handler two animation frames later; a finished load is not painted yet, the clear view would show the bare blur until its first frame, so the window keeps its own background until then; a page that never posts leaves it opaque, and without the handler the end of the first load stands in) only while no other widget is mapped beside the view or any of its parents (a `GtkHeaderBar` set as the titlebar with `gtk_window_set_titlebar` is fine: it paints itself; any other custom titlebar counts as a widget beside the view, since a plain box is clear in a client-decorated window) and no margin of those widgets or `border-width` of their containers leaves a frame of bare window round the view (GTK CSS padding is not looked at). Otherwise the native widgets would be holes on the bare blur, so the view gets its own background back, the stylesheet comes out, and the window stays as the app drew it; a sidebar shown after the map turns it opaque then, and the glass comes back when the widget goes (an app that shows everything and then hides a side widget ends glassed). A view taken out of a glassed window (destroyed, or moved to another window, which then decides it) leaves the window with no view, so it is opaque again: native widgets packed in the view's place would otherwise be holes on the bare blur. A view hidden with nothing else in the window does not fill it either (the window would be empty and bare): opaque until it is shown again. A related view (`webkit_web_view_new_with_related_view`, a second window of the same page group) shares the first view's user content manager, so one stylesheet styles both pages: the views on one manager are glass together, and while one of them is shown beside native widgets every window of theirs is opaque and the stylesheet is out (it is on the manager once, out when the last view lets go of it); the scripts are added once per manager. The scripts stay in all along: they only mark the page, which does nothing without the stylesheet, and WebKit runs a user script only on a document that loads after it is added, so a page loaded while the window was opaque is marked too when the glass comes back (`tests/test_webkit.py ShimDecision`). A glass window also clears its opaque region (`gdk_window_set_opaque_region(window, NULL)`, connected after GTK's own handlers on the window's `realize`, `size-allocate` and `style-updated`): GTK3 sets it to the whole window from the window's opaque CSS background whatever app-paintable says, and at niri `opacity 1.0` niri would believe it and skip what is behind the clear view (the background flickers). An opaque window keeps GTK's region, which is true then. `appglass.kdl` also blends these windows at `opacity 0.999` ([routes.md](routes.md#any-webkitgtk-app-generic-webkit-shim)). The hidden check fails an opaque window, and also any window more than a quarter at alpha 0 or with a bare hole: a region of fully clear pixels more than 16 px in from the edge, holding a 40 px square and covering more than 1 % of the window (native widgets drawn on the bare blur; [engine.md](engine.md)). A popup open at the shot that pokes out past the window widens the shot, and the strip beside the window then counts as such a hole: the check fails safe (the app stays opaque) rather than guess where the window sits in the shot.
- **The page script** reads the page's own colours (light and dark both work, nothing per app):
  - the page colour (`html`, else `body`, else what covers the window) is the content level, on `html` only;
  - elements of that colour elsewhere become clear, so the content shows through;
  - large boxes of another colour (a sidebar, a header, a status bar, a card) take their own colour at the bar level (0.125 over the content: 0.65);
  - popups stay opaque and untouched: `dialog`, `role=dialog|alertdialog|menu|listbox|tooltip`, `popover`, `aria-modal`, and floating boxes with a shadow or a z-index. A box that covers the whole window is a page, not a popup (Kiri's setup step); what such an overlay covered is hidden while it stays, since it is glass now;
  - text, images, buttons, fields and translucent backgrounds are never touched.
  A MutationObserver marks what the page adds or restyles; a theme switch (`prefers-color-scheme`, a class or `data-*` on `html`/`body`) marks everything again.
- **Unfocused:** the content eases to the inactive level (`html.agl-inactive`), text stays opaque.
- **Measured (Kiri 0.2.1, nested niri, `tests/e2e/webkit.sh`), on its setup screen (no engine in the harness: its container views were not seen):** content 153 (94% of the background within 6), bars and cards 166, text 255 (`#f2f0eb`, muted `#98a1ac`), the language dialog (`role=dialog`) 255 over a glass window; at 0.80, 204 focused and 184 unfocused. Kiri's muted grey on 0.60 glass over white is 1.85:1, the page's own grey. Lian Li 1.3.0 (`tests/e2e/lianli.sh`, its daemon hidden): content 153 (83% within 6), bars 166.
- **Limits:** the NVIDIA WebKit workarounds below make a transparent WebView nearly invisible. A page that paints its background with an image or a gradient keeps it. A popup drawn as a plain box with no role, no shadow and no z-index is taken for a card (bar level).
- **Undo:** `appglass remove --only webkit`, or switch the app off in Settings > Apps.

## Why the app alone cannot (without the shim)

A WebKitGTK window is see-through only when all three of these hold:

1. The GTK toplevel has an RGBA visual and is app-paintable (GTK3), or has a transparent window background (GTK4).
2. The WebView base background is transparent, set with `webkit_web_view_set_background_color(view, rgba(0,0,0,0))`. The default base is opaque **white** (dark grey when the page uses `color-scheme: dark`), and WebKit paints it under every page.
3. The page CSS (`html`, panels) uses rgba backgrounds.

- **Tauri.** Layers 1 and 2 are done by tao/wry only when the window config has `"transparent": true` (`tauri.conf.json` > `app` > `windows[]`). `tauri::generate_context!()` compiles that config into the binary. `TAURI_CONFIG` / `--config` merging only applies at `tauri build` time. Layer 3 is the frontend bundle, which is embedded in the binary. On an installed Tauri app, all three layers therefore need a rebuild.
- **No env var.** None of the `WEBKIT_*` variables in `libwebkit2gtk-4.1` sets the background colour; they cover rendering, compositing, DMABUF, GStreamer and debug only:

  ```sh
  strings -n 8 /lib64/libwebkit2gtk-4.1.so.0 | grep -E '^WEBKIT_[A-Z_]+$' | sort -u
  ```
- **No GTK theme route.** A translucent `gtk.css` cannot help, because the WebView covers the whole window and paints its opaque base over it.
- **Page CSS alone does nothing.** The same rgba page without WebView transparency measured alpha 255 everywhere: the rgba is blended onto WebKit's white base.

## Levels

| Surface | Target | Tauri app with `transparent: true` | GNOME Web | Lian Li Linux (fallback) |
|---|---|---|---|---|
| Content | 0.60 (153) | **153**, from `html` rgba 0.60 | **cannot**: page is always 255 | 153 uniform (niri) |
| Header / sidebar / tab bar | 0.65 (166) | **166**, from 0.125 overlays on top of 0.60 | **166**, from libadwaita roles | 153 uniform |
| In-page popups / modals | 1.0 (255) | **255** (opaque CSS) | n/a | **153: fades too** |
| Native menus (GtkMenu: context and select menus) | 1.0 | **255** | not opened | n/a |
| Dialogs | 1.0 | n/a | **255** (AdwAlertDialog for a JS alert) | 153 (in-page HTML) |
| Text / icons / logos | never alpha'd | **255** | **255** | **153: text fades** |

Under the niri fallback alone (no shim), Lian Li Linux has a single uniform level, and its in-page modals fade along with everything else. GNOME Web cannot reach the 0.60 content level at all. With the shim (families `lianli` and `webkit`) an installed app reaches the three levels like a Tauri app built transparent; see [The generic route](#the-generic-route-family-webkit).

## Settings

### Lian Li Linux without the shim: niri fallback (no app files)

The window app-id is **`lianli-gui`**, not the desktop file's `com.sgtaziz.lianlilinux`. The app has no custom-CSS or opacity setting. Its binary contains the Tauri schema names (`transparent`, `windowEffects`, `backgroundColor`) and the wry/tao symbols, but these are compiled code paths, not a runtime switch. The real fix is upstream: an opt-in "translucent window" (`"transparent": true` plus rgba CSS).

Place this after the global "Glass blur" rule in `~/.config/niri/config.kdl` (or in an included file):

```kdl
window-rule {
    match app-id="^lianli-gui$"
    opacity 0.60
}
```

This equals the global rule, so the rule only matters if you want to tune it. The UI is light (white content, light-grey sidebar), so a higher value such as `opacity 0.82` is a suggested compromise (0.80-0.85, untested). The in-app dark toggle (the moon icon in the header) may fit dark glass better; this was not tested.

### Tauri/wry app built with `"transparent": true`

This needs the app's source and a rebuild. These are the requirements a Tauri app has to meet; it is also the text for an upstream request.

`tauri.conf.json`:

```json
{
  "app": {
    "windows": [
      { "transparent": true }
    ]
  }
}
```

The calls wry/tao then make on Linux, as replicated in the test:

```python
vis = window.get_screen().get_rgba_visual()
if vis: window.set_visual(vis)
window.set_app_paintable(True)
c = Gdk.RGBA(); c.parse("rgba(0,0,0,0)"); webview.set_background_color(c)
```

Page CSS by level. This is the tested dark palette; the light palette used `245,245,250` with text `#111111` and dim `#555566`:

```css
html  { background: rgba(16,16,24,0.60); height: 100%; }   /* content 0.60, the ONLY root with alpha */
body  { margin: 0; height: 100%; color: #ffffff; }          /* text opaque */
.bar, .side { background: rgba(16,16,24,0.125); }           /* on top of 0.60 -> 0.65 */
.pop  { background: rgb(36,36,48); }                        /* popups/menus 1.0 */
.dim  { color: #b0b0bc; }                                   /* floor for dim text on dark 0.60 glass */
```

- Put the 0.60 alpha on **one** root element only. Setting rgba 0.60 on both `html` and `body` stacks to 0.84 (alpha 214). This comes from the first test and was not re-run.
- **DMS colours.** No DMS/matugen template exists for Tauri apps. The app would need to expose a theme file (for example a CSS file under `~/.config/<app>/`) that a user matugen template could write, with `{{colors.<role>.default.hex}}` turned into rgba by level, as in the GTK4 doc. This does not exist today.
- **Reload.** The page CSS is part of the bundle. A theme file exposed by the app would reload however the app decides; nothing here was tested.
- **Env.** Do **not** launch the app with `WEBKIT_DISABLE_DMABUF_RENDERER=1` or `WEBKIT_DISABLE_COMPOSITING_MODE=1` (see the caveats).

niri rule, placed after the global "Glass blur" rule. Add it only after `niri msg action screenshot-window` shows alpha below 255 for that window:

```kdl
window-rule {
    match app-id="^<tauri-app-id>$"
    opacity 1.0
}
```

### GNOME Web / Epiphany: glass chrome, opaque page

```kdl
window-rule {
    match app-id=r#"^org\.gnome\.Epiphany(\.WebApp_.*)?$"#
    opacity 1.0
}
```

The GTK4 glass `gtk.css` reaches Epiphany's chrome anyway, so the gtk4 family puts it in its `opacity 1.0` rule: without it the chrome would get both alphas. Only with no GTK4 glass file deployed can Epiphany stay on the global rule (fallback).

**Chrome-only CSS** (tested; the page stays opaque). Selector-based CSS (`window`, `headerbar { background-color: rgba(...) }`) left the header at 255. The libadwaita `@define-color` roles are what works. `~/.config/gtk-4.0/gtk.css`, as tested:

```css
@define-color window_bg_color alpha(#1e2226, 0.60);
@define-color view_bg_color alpha(#191c20, 0.60);
@define-color headerbar_bg_color alpha(#1e2226, 0.125);
@define-color headerbar_backdrop_color alpha(#1e2226, 0.125);
@define-color popover_bg_color #282c30;
@define-color dialog_bg_color #1e2226;
dialog sheet { background-color: @dialog_bg_color; }
```

- The hex values are fixed in the tested file. To reuse DMS colours, use the GTK4 method instead (`@import url("dank-colors.css");` plus the `dank-glass.css` matugen template that writes `alpha({{colors.<role>.default.hex}}, a)`). That combination was not tested with Epiphany.
- This file is read by **every** GTK4/libadwaita app, so it is the same file the GTK4 glass uses (see the open points).
- GTK does not live-reload `gtk.css`, so restart Epiphany after a change.

User stylesheet, only to try for a transparent page. It has no effect on the base, but it proves that user CSS is active. `<profile>/user-stylesheet.css` (default profile `~/.local/share/epiphany/`):

```css
html, body { background: transparent !important; background-color: transparent !important; }
```

gsettings. The `web` schema is **relocatable**: the short form `gsettings set org.gnome.Epiphany.web enable-user-css true` fails silently.

```sh
gsettings set org.gnome.Epiphany.web:/org/gnome/epiphany/web/ enable-user-css true
gsettings set org.gnome.Epiphany ask-for-default false   # else a modal "Set as Default Browser?" covers the window
```

With the chrome variant, the window would need `opacity 1.0` instead of the fallback, which leaves glass chrome and a fully opaque page. The chrome variant combined with a niri rule was not measured.

## Measured results (tested in a nested niri session)

Alpha comes from `screenshot-window` (0-255). Every launch ran in a bubblewrap sandbox: real HOME read-only, no network, private bus and runtime dir, and the Lian Li daemon socket hidden.

**Lian Li Linux**

| Case | Alpha min / avg / max |
|---|---|
| Default | 255 / 255 / 255 |
| Translucent GTK3 `gtk.css` (`window, .background, decoration { background-color: rgba(30,30,40,0.60); }`) | 255 / 255 / 255: no effect |
| niri `match app-id="^lianli-gui$"` `opacity 0.60` | 153 / 153 / 153: uniform, text included |

- Readability under the fallback: main text stays readable. Grey secondary text and outlined buttons lose contrast, and the in-page modal is also 0.60.
- This was judged from composites that treated the PNG as straight alpha, so a light UI looks too dark in them. Contrast: **to re-measure**.

**Tauri app with `transparent: true` (demo)**

| Case | Alpha min / avg / max | Regions |
|---|---|---|
| Dark, transparent | 153 / 160.1 / 255 | content 153, header 166, sidebar 166, in-page popup 255, text stem 255 |
| Light, transparent | 153 / 160.1 / 255 | content 153, header/sidebar 166, popup 255 |
| Dark + native GtkMenu | 153 / 162.5 / 255 | menu 255 |
| Dark, `/dev/nvidia*` bound | 153 / 160.1 / 255 | same as dark |
| Opaque control (no WebView transparency) | 255 / 255 / 255 | page rgba blended onto the white base |
| Global niri `opacity 0.60` + app rule `opacity 1.0` | 153 / 160.1 / 255 | on-screen text pure white (255,255,255) |
| Global niri `opacity 0.60`, no app rule | 92 / 96.3 / 153 | backdrop bleeds through the text |

Contrast, from premultiplied-correct composites. Text is opaque, so the text colour equals the CSS colour.

| Element | Over blurred wallpaper | Over white | Over black |
|---|---|---|---|
| Dark: white text on content | 8.3 | 4.9 | 19.8 |
| Dark: dim `#9a9aa8` on content | 3.0 | **1.78 (bug)** | 7.1 |
| Dark: `#111` logo on header | **1.29 (bug)** | 3.2 | **1.05 (bug)** |
| Light: `#111` text on content | 13.1 | 18.0 | 6.2 |
| Light: dim `#555566` on content | 5.1 | 6.9 | 2.4 |

Body text and 10 px text are crisp, and glyph cores are alpha 255. A dark logo on a white plate stays visible.

**GNOME Web / Epiphany 51**

| Case | Header / tab bar | Page | Dialog |
|---|---|---|---|
| Selector `gtk.css`, light | 255 | 255 (white) | - |
| libadwaita roles + user CSS `html,body{background:transparent!important}` | 166 | **255 (white)** | - |
| libadwaita roles + user CSS `:root{color-scheme:dark}` `html{background:rgba(30,34,38,.60)}` | 166 | **255 (dark grey)** | - |
| JS alert (AdwAlertDialog) | 166 | 255 | 255 |

- Text and icons are alpha 255. The CSD shadow margin is 20 px at alpha 0, the same as any GTK4 CSD window.
- Header contrast (tab label, icons, dimmed URL text): **to re-measure**. The dimmed URL text was flagged as borderline against a white backdrop.
- With the transparent user CSS the page is solid white, so white page text is invisible.

## What breaks / caveats

- **NVIDIA env workarounds kill the glass.** With `WEBKIT_DISABLE_DMABUF_RENDERER=1` or `WEBKIT_DISABLE_COMPOSITING_MODE=1`, a transparent WebView window becomes almost fully invisible: alpha 0 except a ~20 px band at the bottom, avg 2.4.
  - This was reproduced with and without `/dev/nvidia*`, and with a tao-style draw handler that clears the window.
  - In opaque mode the same vars render normally.
  - These vars are the usual fix for blank or flickering Tauri windows on NVIDIA (the tested machine has an NVIDIA GPU), and some packages set them in their launcher. Check the alpha before adding `opacity 1.0`.
- **GPU path not confirmed.** The web process loaded both `libgallium` and `libnvidia-eglcore`, so it is unproven whether hardware rendering or llvmpipe was active. The default (DMABUF) path worked in both sandboxes.
- **Dim text on dark glass** fails 2:1 over a bright backdrop: `#9a9aa8` gives 1.78, and `#888` is worse. Give dim text a floor (about `#b0b0bc` on 0.60 dark glass).
- **Dark logos** (`#111`) are invisible on dark glass. Give them a light plate or a light variant.
- **Native menus follow the GTK theme.** Without a user GTK theme, a GtkMenu is light Adwaita on a dark app. Select dropdowns and tooltips could not be opened (no input tool, and `showPicker()` is missing in WebKitGTK 2.54). They are expected to be opaque but were not seen.
- **Tauri dialogs are usually in-page HTML**, so under the fallback they fade together with the window. There is no per-level control.
- **Epiphany:**
  - The page base is opaque in every variant, because Epiphany never calls `webkit_web_view_set_background_color`.
  - Forcing `color-scheme: dark` through user CSS gives a dark opaque page that looks more coherent, but pages that set dark text without a background become unreadable (1.16:1).
  - For about 1 s after a resize, the area not yet repainted shows the 0.60 window background. This is harmless.
  - Popovers and menus were not opened.
- **Shared GTK4 file.** A glass `~/.config/gtk-4.0/gtk.css` deployed for the other GTK4 apps also turns Epiphany's chrome translucent. Under the global 0.60 rule, those surfaces would get both alphas, so the gtk4 family gives Epiphany (and its web apps) `opacity 1.0`: glass chrome, opaque page.
- **Light mode.** Light glass in the Tauri demo reaches the same alpha levels. Early composites made light glass look grey (~190) instead of near-white (~249) over white, because the PNG is premultiplied. Judge light themes only from corrected composites.
- **Flatpak:** none of the tested apps is a flatpak. Lian Li and Epiphany are system packages.
- **Lian Li daemon:** the GUI talks to `/run/lianli/lianli-daemon.sock` and can run `systemctl [--user] start/restart`. Launch any test copy isolated from the real daemon.

## Documented only (not run)

- **Geary, Evolution mail view, Yelp, GNOME Online Accounts web views, and other wry/Tauri apps.**
  - The rule is the same: the web area is transparent only if the app's code calls `webkit_web_view_set_background_color()` with alpha 0, and Tauri apps additionally need `"transparent": true` at build time.
  - GTK chrome can be themed with `gtk.css`, but the web area stays opaque. Use the niri opacity fallback per app-id.
  - Unverified.
