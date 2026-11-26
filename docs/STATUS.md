# Project status

Where appGlass stands, what works, what does not, and how to pick the work up again.
Read this first when you come back to the project.

## Where it is

- Version **0.1.0**, released 2026-11-19 (tag `v0.1.0`, a GitHub release). `master` is the only branch.
- The engine (`bin/appglass`, `appglass/`), the shims (`shims/`), the DMS plugin (`dms-plugin/`)
  and the docs are in place. Every route listed in the README is written, tested and reviewed.
- The last work round fixed a background flicker. Some apps tell the compositor that their
  window is opaque while they paint it with alpha. At niri `opacity 1.0`, niri then stops
  drawing what is behind them, so the background goes stale or black. Those apps (Feishin,
  VSCodium, Obsidian, the WebKitGTK apps) now get `opacity 0.999`. The WebKit shim also clears
  the opaque region itself. See the blend block in [routes.md](routes.md).
- The round after that fixed false fails of the hidden check on a real desktop at level 0.80.
  The check ran at 0.60 (the DMS level sources were not copied) and judged at 0.80, so every
  checked app failed and went plain. Now the check copies the DMS glass rule and
  `foregroundLayerTransparency`, has your colour scheme, measures the app's own main window
  (never zenity or another dialog), knows Dux Calendar's pane level and Obsidian's vault list,
  and does not judge Discord or an app open on the desktop. A Native route is never paused by
  a failed check, and a check that cannot judge (unverifiable) changes nothing. See
  [engine.md](engine.md#what-a-check-judges-and-what-it-never-does). In a throwaway HOME at 0.80
  these pass: Kiri, ArtCraft, Feishin, Jellyfin, LocalSend, Nautilus, Dux Files, Obsidian,
  Alacritty (204) and Dux Calendar (237, its panes); VLC finds no window (unverifiable).
- The last fix: on the live desktop, hovering Kiri's sidebar left the page bare but for the
  hovered item (WebKitGTK 2.54 repaints only the damaged rects of a frame). The WebKit shim now
  turns WebKit's damage tracking off on a glass view. See [routes.md](routes.md).
- `docs/issue-dms.md` is a draft issue for DankMaterialShell. It has not been posted.

## What works

Measured in a nested test session (see [apps.md](apps.md) for the numbers):

- Terminals: Alacritty, foot, Konsole.
- GTK4 and libadwaita: Nautilus, GNOME Text Editor, Mission Center, Resources.
- GTK3 theme: Solaar, nvidia-settings (dialog bodies stay opaque).
- Qt 6 Widgets style plugin: VLC, Kate and Konsole (flatpak).
- App configs: Kate, mpv, GIMP 3. Zed is partial (it draws its own dark floor).
- App themes: Obsidian, Herdr, Dux Files, Dux Calendar (partial, see the README table).
- Forced routes, after their hidden check: Feishin, VSCodium, Kiri (generic WebKit shim),
  Jellyfin Desktop, LocalSend, ArtCraft Launcher.
- Unfocused fade, DMS level follow, matugen colour follow, automatic routing of new apps.
- `appglass remove` puts every file back. Created files are deleted (with any edits you made
  to them), edited files get their original back, and your later edits to files appglass
  edited are kept.
- A file appglass owns whole that you edited by hand is saved as `<file>.appglass-changed`
  before the next apply or hook run writes it again (once, `doctor --fix` included). A symlink
  you put over a file appglass created is yours: apply, hook runs, restore and remove leave it as is.
- Games, root GUIs, DMS windows and Firefox-family browsers are never touched.

## What does not work, or is not tested

- **Lian Li Linux:** the shim paints the glass, but the hidden check cannot judge it (with its
  daemon hidden it shows a "Waiting for daemon" dialog): unverifiable, so it stays opaque
  unless you switch it on (then it stays glass).
  Also, in the test session its window opened as `lianli-gui`, while the family matches
  `^com\.sgtaziz\.lianlilinux$`. Check the app id on a real install and add it if it differs.
- **Discord (Vencord):** written and unit-tested, not measured (it needs a signed-in account).
  The hidden check cannot run it (the client, its patch and the login are in `~/.config/discord`,
  not copied), so it is always unverifiable and goes live only when you switch it on yourself.
- **Apps you keep open** (a terminal, say) are not checked while a window of them is open: the
  check waits in the queue until they are closed.
- **Untested, same route as a tested app:** kitty, Ghostty, WezTerm, other libadwaita apps,
  other GTK3 and Qt 6 Widgets apps, other WebKitGTK 4.x and Tauri apps.
- **No route (fallback, opaque by default):** Steam, Chrome, Java, Tk, X11 apps,
  Electron apps with no hook, plain GTK4 apps without libadwaita.
- **WebKit shim apps** keep the whole opaque region for a few seconds after the window maps,
  until the page first paints. The 0.999 rule covers that time.
- **GTK theme flip:** at a DMS colour change that changes GTK CSS, every open GTK app redraws
  once (one frame). It never happens at idle. See [engine.md](engine.md).
- **Measured by reasoning only, not by a run:** the opaque region of Vencord, Jellyfin and VLC
  (they did not start without a session bus in the test session). They stay at `opacity 1.0`.

## Open items

From the last review. They are minor, and none of them blocked 0.1.0:

- The screenshots and GIFs use a third-party wallpaper. Retake them on a wallpaper you may
  publish before a release.
- `docs/guide.md`, `docs/engine.md` and `docs/plugin.md` still hold `TODO(...)` lines.
  They match the Roadmap in the README.
- The Opaque chip text does not say that timeshift-gtk also gets `blur false` (games block).
- Safety corner cases that were kept on purpose (nothing is lost in any of them):
  an unnamed `.orig` when a commit only backs up (the next apply refuses with a `.damaged` hint);
  a cut inside remove's undo write of a file you edited (the original comes back, the cut
  bytes are saved aside).
- Roadmap items: `appglass setup`, `appglass pause/resume`, a per-app off for Native apps that
  takes their files out, `appglass set` with dotted app ids, a generic Electron route, fade for
  more routes. See the README.

## How to resume

1. **Run the tests.** The unit suite takes about 20 minutes. It needs a short `TMPDIR`
   (the broadway socket path has a length limit):

   ```sh
   TMPDIR=$(mktemp -d /tmp/ag.XXXX) python3 -m unittest discover -s tests
   sh dms-plugin/tests/qml/run.sh
   ```

   Run them with a throwaway `HOME`, so no test can reach your real config.
   Some tests skip when an optional tool is missing: gcc, g++, moc, Qt 6, gjs, node, luac, niri,
   bwrap, ffmpeg, jq, the Vulkan headers, lavapipe, SPIRV-Tools or shaderc, and a few more. Six
   always skip: shared shim tests that do not apply to a family ("no rendered CSS", "nothing
   built"). On the last full run 8 skipped: those six, plus luac and node missing.

2. **End-to-end tests** (`tests/e2e/<family>.sh`) run the real apps in a nested niri session.
   They need `APPGLASS_HARNESS` set to the nested-session script, `tests/e2e/harness.sh`
   (its state goes to `${XDG_CACHE_HOME:-~/.cache}/appglass-harness`).
   The header of `tests/e2e/lib.sh` lists what they need. Keep the test session away from
   your real one: no user bus, no systemd user runtime dir, a temp `HOME`.

3. **Where to look first:**
   - [engine.md](engine.md): how a route is picked, the backups and the record.
   - [routes.md](routes.md): what each route writes, per app, with the measured result.
   - [apps.md](apps.md) and `apps.json`: every tested app and its result.
   - `CHANGELOG.md`: what 0.1.0 holds.

4. **Next steps that make sense:** retake the media, clear the open items above, then the
   Roadmap's **Next** list. Bump the version in `appglass/__init__.py`, `dms-plugin/plugin.json`,
   `dms-plugin/components/logic.js` and `CHANGELOG.md` together (`tests/test_docs.py` checks it).
