# Draft issue for DankMaterialShell (not posted)

This is a draft. It has not been posted, and the repo link is a placeholder. Attach only the screenshots listed at the end, after the privacy check.

---

**Title: Per-app glass that follows the window-rule opacity, with text kept opaque (plugin: App Glass)**

## Problem

The usual way to get glass on niri + DMS is the "Glass blur" window rule in `dms/windowrules.kdl` (`opacity 0.60`, blur on). niri applies that opacity to the whole window, so text, icons and logos fade together with the background and take on the colour of whatever is behind. In Alacritty, glyphs measure alpha 153 of 255 under that rule instead of 255. Apps paint opaque backgrounds, so today you choose between faded text and no glass.

## Demo

Same desktop, before and after. The nested-session pairs are at a DMS opacity of 0.60; the after shots of Lian Li, LocalSend, Feishin and ArtCraft come from the real session at 0.80 (background 204):

- *(attach)* Alacritty: before (window rule) / after (terminal opacity key, text at 255)
- *(attach)* Nautilus (GTK4/libadwaita): before / after, plus an opaque popover
- *(attach)* Solaar (GTK3): before / after, focused and unfocused
- *(attach)* VLC (Qt Widgets): before / after
- *(attach)* Herdr (gpui): before / after
- *(attach)* Lian Li (Tauri/WebKitGTK) and LocalSend (Flutter): before / after
- *(attach)* Feishin (Electron): after
- *(attach)* ArtCraft (wgpu): before / after
- *(attach)* a full-screen shot of the real desktop

Measured from window screenshots composited over black and white, in nested niri at 0.60: background alpha 153 at the level, bars at 166 at 0.60 (Dux Files uses one level everywhere), text and icons 255, popups 255. The 0.80 after shots are from the real session, with the background at 204 and the bars at `max(content, 0.65)`, so 204 too. The generated text colours target 2.25:1 over any backdrop, and the end-to-end checks fail under 2:1.

## How it works

- **The level comes from DMS.** The content level is the opacity of the DMS glass window rule. Bars are `max(content, 0.65)`, popups and menus are 1.0, and text roles never get alpha.
- **Each app paints its own alpha, and its niri rule goes back to `opacity 1.0`.** The rule lives in a separate file included after `dms/windowrules.kdl`, the same pattern as `dms-browser-glass.kdl`. Blur stays on. Every window App Glass does not handle gets `opacity 1.0` too (opaque, sharp), so nothing is ever faded twice.
- **Route by toolkit, cleanest first.** The toolkit is found by reading the binary (ELF libraries, Electron fuses, flatpak runtime), without running the app:

  | Toolkit | Route |
  |---|---|
  | terminals (Alacritty, kitty, foot, Ghostty, WezTerm, Konsole) | the terminal's own opacity key |
  | GTK4 / libadwaita | a glass CSS imported next to `dank-colors.css` (flatpaks: a copy in the app's config folder, or read-only access for one launch) |
  | GTK3 | a per-app `GTK_THEME` in a launcher override |
  | Qt Widgets | a small Qt style plugin chosen per launch (host apps, and the Kate and Konsole flatpaks) |
  | gpui (Herdr, Zed) | the app's theme with alpha |
  | mpv, GIMP, Kate | the app's own config: a background colour with alpha, a user CSS, an editor theme |
  | Electron | the app's own CSS hook (Obsidian), or a hook through the Node inspector (Feishin, VSCodium; checked first) |
  | Tauri/WebKitGTK, Flutter/egui, QtQuick | a preload shim scoped to one launch (checked first) |
  | Discord | Vencord's theme support, if the user installed Vencord (checked first) |
  | Firefox family | left to browserGlass |
  | anything else | opaque |

  A GTK3, GTK4 or Qt app no route lists by hand gets its toolkit's route on its own.

  TODO(adapters): a generic `NODE_OPTIONS=--require` route for Electron apps whose fuses allow it.

- **Kept in step with DMS.** A matugen user template with a `post_hook` re-applies on every theme change, and a systemd path unit on `dms/windowrules.kdl` and `dms-colors.json` re-applies when the level changes. Nothing of ours runs while idle except a small reader that fades unfocused Alacritty windows.
- **New and updated apps on their own.** The same path unit watches the application folders, the rpm database and the flatpak `.changed` files, and a daily timer catches apps that update themselves. One short job fingerprints the launchers with `stat` and re-routes only the apps that changed (measured on the prototype: about 25 ms per event, 1.7 s for a cold scan, once); a run with nothing to do exits in about 20 ms.
- **A check before anything loaded into an app.** Shims, the inspector hook and the Vencord route go live only after a hidden headless check (gamescope headless, nested niri, a private D-Bus and a throwaway HOME) shows the background at the level and opaque text. After an app update, that app runs plain until it passes again; a failed check, or two launches with no window, leave it plain until its next update, with one notification. The user can switch any of them off, and turning one back on asks first.

- **Safe by default:**
  - no system files, no sudo; app binaries, asars and flatpak deploys are not modified (the Vencord route, on by default once its check passes, re-runs the user's Vencord installer after a Discord update);
  - every file it writes is recorded and put back as it was on uninstall (files it created are deleted, the user's later edits are kept), with a backup ring of the last 5 applies;
  - games are never touched: no file, env or preload, `opacity 1.0` and blur off;
  - root GUIs stay opaque, password managers get native routes only, and game launchers never get a preload;
  - the preload and style variables are taken out of the environment of the app's child processes;
  - turning the plugin off, reloading or restarting it removes nothing.

## What we would ask from DMS

1. **Alpha by level in the existing matugen templates** (opt-in): background roles at the content or bar level, popups 1.0, text roles solid and readable on glass. GTK3/4, terminals, Qt palettes and Vesktop CSS would then get glass natively, with no plugin code.
2. **The levels as documented values** (`content`, `bar`, `popup`), for example in `dms-colors.json` next to the colours. Tools would then stop parsing `windowrules.kdl`.
3. **A documented slot for plugin-owned niri rules**, included after `dms/windowrules.kdl`, and/or a per-app "paints its own alpha" flag in window rules, so DMS sets `opacity 1.0` for those apps itself.
4. **A stable "theme applied" event or hook for plugins.** Today this means a matugen user template with a `post_hook`, or a path unit on `dms-colors.json`.
5. **Plugin lifecycle: a "disabled by user" signal that is distinct from "unloaded/reloaded"**, so a plugin never has to guess whether to clean up.
6. **Feedback on the plugin's home:** is a plugin with the `process` permission the right shape, or should parts (1-3) live in DMS? Is there interest in listing it in the plugin browser?

## Limits

- **Steam:** the client window stays opaque. Both official routes were measured and give no window alpha: Valve's CEF underlay flags (the page turns transparent, the window stays at alpha 255), and Steam's GL composer option (the main window and menus always use the system composer, which reports "transparent background not supported"; alpha 255). Nothing is injected into Steam, and games are never touched.
- **Chrome and Chromium browsers:** web content has no window alpha, so they stay opaque.
- **Games, Wine/Proton, SDL:** excluded on purpose (opaque, blur off). Nothing runs inside a game process, so there is nothing for an anti-cheat to see.
- **The inspector hook** (Feishin, VSCodium) opens a Node inspector port on 127.0.0.1 (random port, session id private to the wrapper) for the injection, then closes it. An Electron that cannot close it keeps it on loopback only, with the random port and the private session id.
- **Java, Tk, X11 apps that are not GTK, Qt from a flatpak KDE runtime (Kate and Konsole excepted), Electron apps with no hook:** opaque.
- GTK apps and Dux Calendar need a restart after a theme change. Alacritty, Herdr and Dux Files reload live. Quit Obsidian before the first `appglass apply`: Obsidian needs a restart on the first enable (or the snippet toggled off and on), and reloads live after that.
- Apps started outside their launcher (shell, D-Bus activation) do not get launcher-based routes. They stay opaque and sharp.
- Tested on Fedora + niri + NVIDIA, dark scheme first. Light mode has been measured less.
- Dark logos drawn by the app itself can be hard to see on dark glass. CSS cannot reach them.
- The NVIDIA WebKit workarounds (`WEBKIT_DISABLE_DMABUF_RENDERER=1`, `WEBKIT_DISABLE_COMPOSITING_MODE=1`) make a transparent WebView nearly invisible.

## Install / uninstall

```sh
git clone https://github.com/lung595/appGlass ~/.local/share/appglass
cd ~/.local/share/appglass
bin/appglass plugin install         # links the plugin
bin/appglass hook install           # matugen hook + user units
bin/appglass apply --all --dry-run  # preview
bin/appglass apply --all
# then enable "App Glass" in DMS Settings > Plugins
```

TODO(engine): one `appglass setup` for the steps above.

- Settings: global pause, per-app switch and route, and the reason for each app that stays opaque.
- Turning the plugin off removes nothing.
- Uninstall: Settings > Advanced > Uninstall appGlass, or `appglass remove && appglass plugin remove`. Every file is put back as it was (files it created are deleted, later edits are kept), and `appglass remove` takes the hook and the units too.

I'm happy to turn parts of this into PRs (templates, levels in `dms-colors.json`, the niri slot) in whatever shape fits DMS, or to keep it as a plugin.

POC: <!-- link to the appGlass repo -->

---

## Screenshots

The screenshots are kept in the private probe folder (`<probe>` below), never in this repo. Every path below is written in full from `<probe>`. `shots/...` (and `allapps/qt/shots/...`, the Qt style run) are window screenshots from nested niri sessions, except `shots/a4b/*` (screen captures from the real session) and `shots/b1/*`, which come from the real session like `realshims/*`; `.black`/`.white` variants prove the alpha, `.wp.png` is the composite over the blurred wallpaper and looks like the real desktop. Look at each one before attaching.

| Pair | Before | After |
|---|---|---|
| Alacritty | `shots/terminal/C-screen-niri060.png` (`shots/terminal/C.wp.png`) | `shots/terminal/E-op060-palettefix.png` (`shots/terminal/E.pm.wp.png`); or `shots/terminal/D-screen-niri100rule.png` / `shots/terminal/D.wp.png` |
| Nautilus GTK4 | `shots/gtk4/verify-1/plain-noenv.wp.png` | `shots/gtk4/naut-final.wp.png` + `shots/gtk4/naut-final-popover.wp.png` |
| GTK3 (Solaar) | `shots/gtk3/00-baseline-csd.png` | `shots/gtk3/08-theme-v5-focused.wp.png`, unfocused `shots/gtk3/08-theme-v5-backdrop.wp.png` |
| VLC Qt | `shots/qt/vlc-baseline.wp.png` | `allapps/qt/shots/vlc-appglass.wp.png` (the appglass Qt style; `.black`/`.white` beside it) |
| Herdr | `shots/gpu/herdr-baseline.png` | `shots/gpu/herdr-glass3.wp.png` |
| Lian Li (WebKit) | `shots/webkit/lianli-niri-opacity060.wp.png` (or `shots/webkit/lianli-default.wp.png`) | `realshims/lianli-glass.png` (real session) |
| LocalSend (Flutter) | `shots/flutter/ls-baseline.wp.png` | `realshims/localsend-glass.png` (real session) |
| Feishin | (none) | `realshims/feishin-glass.png` (real session) |
| Obsidian | (no clean before) | `shots/electron/x-obsidian-final.png` |
| Dux Files | (none) | `shots/a3/dux/run4/dfiles-run4.png` (config A, what appglass ships); not `shots/qtquick/dfiles-060.wp.png`, which is config B (0.86 panes) |
| ArtCraft | `shots/gpu/artcraft-baseline.wp.png` | `shots/b1/after-new-shim.png` (`shots/b1/before-old-shim.png` is the old shim, not a no-glass baseline) |
| Real desktop | `shots/a4b/pre-<output>.png` (and a `-small` copy) | `shots/a4b/alacritty.png`, `shots/a4b/nautilus.png`, `shots/a4b/nvidia-settings.png`, `shots/a4b/dfiles.png`, `shots/a4b/herdr-new.png` |
| Steam GL composer test | | `shots/steam-gl/main-xcompworkaround-off.png`: proof of the limit (alpha 255 everywhere), not a glass shot |

Paths are relative to `<probe>`. Every file in this table exists there.

Levels: every pair is at 0.60, except the after shots at 0.80 of Lian Li, LocalSend, Feishin (`realshims/*`, real session) and ArtCraft (`shots/b1/after-new-shim.png`, real session). Their before shots are at 0.60. Take those four again at 0.60 for the fresh set.

**Privacy:** `shots/a4b/*`, `shots/b1/*` and `realshims/*` come from the real session. Check them for file names, terminal history, account names and notifications, and crop them before attaching. A fresh set taken once the engine work lands (same apps, same level) would make a cleaner demo.
