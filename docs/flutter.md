# Flutter (Linux GTK embedder)

No Flutter app gets real glass without changing the app itself. LocalSend (the only one installed) stays on the global niri `opacity 0.60` fallback, where text fades along with the background.
You can still tint it with the DMS/matugen accent and force its dark theme, so the faded window keeps readable text and logos.

## Apps

| App | Tested / Documented | Works | Method | niri rule needed |
|---|---|---|---|---|
| LocalSend (flatpak `org.localsend.localsend_app` 1.18.2) | Tested in a nested niri session | no (fallback) | Keep the global niri opacity. Optional colour-only tint: a sandbox `gtk-3.0/gtk.css` with `theme_selected_bg_color` plus in-app Color mode = System, Theme = Dark | None. Keep the global `opacity 0.60`. Do **not** add `opacity 1.0` |
| Other Flutter Linux apps (AppFlowy, Spotube, Hiddify, Ente Auth, Yaru/Ubuntu Flutter apps) | Documented only (not installed, not run) | no (unless the author opted in) | Fallback. Transparency only exists if the app ships `flutter_acrylic` / `window_manager` transparency **and** transparent Dart surfaces | None (fallback) |

## Levels

| Surface | Target | Reachable? |
|---|---|---|
| Content background | 0.60 (alpha 153) | No per-role alpha. Only as the uniform niri fallback, which fades text too |
| Bars / headers / sidebars | 0.65 (alpha 166) | No. They are painted by Dart inside the same Flutter view |
| Menus / popups / tooltips | 1.0 | No separate control. Popups render inside the same single Flutter surface, so they get the same uniform niri opacity as everything else |
| Text / icons / logos | never alpha'd | Not achievable. The niri fallback fades them with the window |

Why it can't work: there are two opaque layers, and neither is reachable from a theme file.

1. **Runner (C, GTK).** The stock Flutter template runner only calls `gtk_application_window_new`, `fl_view_new` and `gtk_container_add`. There is no `fl_view_set_background_color`, no `gdk_screen_get_rgba_visual` and no `gtk_widget_set_app_paintable`. The `FlView` default background is opaque black. `libflutter_linux_gtk.so` exports `fl_view_set_background_color(FlView*, const GdkRGBA*)`, but only the app's runner code can call it.
2. **Dart UI.** Material `Scaffold` / `NavigationBar` paint opaque `ColorScheme` surfaces. A transparent runner would also need `scaffoldBackgroundColor: transparent` (or similar) and per-role alpha in Dart.

GTK CSS reaches only the `GtkWindow` around or behind the `FlView`, never the Flutter surface (see test 3 below).

## Settings

### LocalSend: fallback + optional tint (colour only, not glass)

**niri:** nothing to add. LocalSend stays under the global "Glass blur" rule (`opacity 0.60`, blur on). A per-app `opacity 1.0` rule would make it fully opaque, because the app itself paints alpha 255.

Optional and untested: if 0.60 is too faint, a per-app rule placed after the global rule can raise just this window (the source read suggests e.g. 0.75 for better text). Check the app-id with `niri msg windows` first.

```kdl
// optional, untested: less fade for LocalSend only
window-rule {
    match app-id=r#"^org\.localsend\.localsend_app$"#
    opacity 0.75
}
```

**Accent tint (tested).** LocalSend is a flatpak. Flatpak forces `XDG_CONFIG_HOME` to the per-app dir, so the app reads GTK CSS from the sandbox's own config dir. No flatpak override is needed:

`~/.var/app/org.localsend.localsend_app/config/gtk-3.0/gtk.css`

Content tested (a fixed hex taken from the matugen primary):

```css
@define-color theme_selected_bg_color #9acbfa;
```

To reuse DMS colours, generate that line from a small user matugen template. DMS's own `gtk-colors.css` template (output `~/.config/gtk-{3,4}.0/dank-colors.css`) defines `accent_color` but not `theme_selected_bg_color`, so it can't be reused as is. The template body:

```css
@define-color theme_selected_bg_color {{colors.primary.default.hex}};
```

Template entry, in the same format as DMS's `matugen/configs/gtk.toml` (the template file name is a proposal):

```toml
[templates.localsend]
input_path = '<user templates dir>/localsend-gtk.css'
output_path = '~/.var/app/org.localsend.localsend_app/config/gtk-3.0/gtk.css'
```

**In-app settings (one time):** Settings → Color mode = **System**, Theme = **Dark**. They are stored in `~/.var/app/org.localsend.localsend_app/data/org.localsend.localsend_app/shared_preferences.json`:

```json
{"flutter.ls_color":"system","flutter.ls_theme":"dark"}
```

The full preference set includes `ls_theme`, `ls_color`, `ls_custom_color`, `ls_enable_animations` and others. None of them controls opacity or transparency.

**Reload:** the accent is read at startup (log line `dynamic_color: Accent color detected.`). After a wallpaper or theme change, restart LocalSend.

## Measured results (LocalSend, tested in a nested niri session)

Each row ran in a fresh nested session, isolated with `--unshare=network`, no session bus and a throwaway HOME. Alpha is from the window screenshot (0-255, reliable).

| # | Setup | Alpha min/avg/max | Observation |
|---|---|---|---|
| 1 | Baseline, default prefs | 255/255/255 | Opaque light mint UI, no glass |
| 2 | sandbox `gtk.css`: `window { background-color: rgba(255,0,0,.3); padding: 40px }` | 255/255/255 | No change. Padding has no effect and the `FlView` covers the whole window |
| 3 | same + `window > * { margin: 40px; }` | 76/223.5/255 (border 76, inner view 255) | A 40 px translucent red frame appears: the CSS is loaded and the GTK surface carries alpha on Wayland. The `FlView` inside stays **opaque black** |
| 4 | Tint: prefs `ls_color=system`, `ls_theme=dark` + `@define-color theme_selected_bg_color #9acbfa;` | 255/255/255 | Dark UI tinted with the matugen primary. Logo and accents are light blue on dark, all readable |
| 4b | Test 4 with 0.60 alpha applied offline to simulate the niri fallback | 153 | Wallpaper visible. Text and icons faded but readable, because the theme is dark |

Test 2 used this exact CSS:

```css
window, window.background { background-color: rgba(255,0,0,0.30); background-image: none; }
```

Test 3 appended `window > * { margin: 40px; }`.

Readability: the dark tint keeps text and logo readable at the 0.60 fallback (4b). With the light default theme (1) at 0.60, contrast is poor on bright wallpapers. No contrast ratios are given here. These composites came from an early pass that treated the premultiplied screenshots as straight alpha, which makes light themes look much too dark, so contrast is still **to re-measure**. Row 4b is a simulated 0.60, not a real niri rule.

## What breaks / caveats

- **No glass route at all** without app source changes (runner C plus Dart theme). GTK CSS only paints the `GtkWindow` behind the `FlView`.
- **`window_manager` doesn't help.** LocalSend bundles `libwindow_manager_plugin.so`, whose `setBackgroundColor` applies `window { background-color: … }` CSS to the `GtkWindow`. LocalSend never calls it (the string is absent from `libapp.so`), and even if it did, it only affects the window behind the opaque `FlView`. The same goes for `yaru_window_linux_plugin`'s `setBackground`. `flutter_acrylic` and `bitsdojo_window` are absent.
- **Light theme on the fallback:** the default light mint theme at 0.60 gives poor text contrast on bright wallpapers. Use the dark theme.
- **Flatpak paths:** config lives under `~/.var/app/org.localsend.localsend_app/`, not `~/.config`. Flatpak ignores `--env=XDG_*`, and the sandbox reads its own `config/gtk-3.0/gtk.css` without extra filesystem permissions.
- **Accent changes need a restart.** No live reload.
- **Single surface.** Even an app that opts in has to do per-role alpha (bars 0.65, menus 1.0) in Dart. The compositor sees one surface.

## Documented only (unverified)

Other Flutter Linux apps (AppFlowy, Spotube, Hiddify, Ente Auth, Ubuntu/Yaru Flutter apps) are not installed and were not run. From the Flutter Linux embedder and plugin sources:

- The stock runner gives an opaque `FlView`. Assume fallback (global niri opacity) unless the app author added transparency.
- An app can only be transparent if it does **both** of these:
  - Runner: in `linux/runner/my_application.cc`, `GdkRGBA c = {0,0,0,0}; fl_view_set_background_color(view, &c);`, plus an RGBA visual and app-paintable on X11. Alternatively, `flutter_acrylic` (`Window.setEffect(WindowEffect.transparent)`) or `window_manager` with a transparent background.
  - Dart: transparent `scaffoldBackgroundColor` and surfaces with per-role alpha.
- Quick per-app check on an installed binary:

```sh
find <app>/lib -name 'libflutter_acrylic_plugin.so'
strings <runner> | grep -E 'fl_view_set_background_color|rgba_visual'
strings <app>/lib/libapp.so | grep -c setBackgroundColor
```

  If nothing matches, it's a fallback app.
- If an app does have built-in transparency, add an `opacity 1.0` niri rule on its app-id after the global "Glass blur" rule, as for other glass apps. This has not been tested for any Flutter app.
