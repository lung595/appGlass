"""appglass families: one module per app family, auto-discovered.

Every ``appglass/families/<name>.py`` (not starting with ``_``) is loaded by
``appglass.core.discover``. A module that fails to import is skipped with a
warning, the others still run.

Module API
----------
NAME : str
    Family name, used by ``--only`` and as the owner key in state.json.
APP_IDS : list[str]
    niri app-id regexes (written as ``match app-id=r#"..."#`` into the one
    ``window-rule { ... opacity 1.0 }`` of $XDG_CONFIG_HOME/niri/appglass.kdl).
installed(env) -> bool
    Real detection: ``env.which("cmd")``, ``env.flatpak_installed("app.id")``,
    ``os.path.isdir(env.config_path("app"))``. The core lets
    APPGLASS_ASSUME_INSTALLED / APPGLASS_ASSUME_NOT_INSTALLED (comma lists of
    names) override it, for tests.
apply(ctx) -> list[str]
    Plan the family's files through ctx (below) and return the paths. Nothing
    is written by the family itself: the core checks the whole plan against
    the sandbox guard and ownership first, then writes it, then records it in
    state.json. Raise ``appglass.core.Conflict`` (or let ctx raise it) to skip
    the family with a warning; any other exception is reported as an error
    and the family is skipped.
undo(env, path, text) -> str   (optional)
    Only for files changed with ctx.edit_text that the user edited after
    apply: strip the appglass parts from ``text``. Without it, remove
    restores the original and saves the user's version as
    ``<path>.appglass-changed``. (The edit_text ``undo=`` argument is the
    same thing for one apply run; the module-level one is what remove uses.)

render_route(env, owner) -> (str, str)   (optional)
    For a family whose wrapper picks a render route at launch: the route it
    takes as installed ("gpu" | "cpu", or "off" when a knob starts the app
    plain, without glass) and why ("" when there is nothing to say). ``owner`` is the family's state.json record. status, status --json
    (``render``, ``render_why``), doctor and the plugin's app row show it.

There is no remove function: remove is the core's job, from state.json
(created files deleted, modified files restored byte-identical, merged JSON
keys put back). A recorded file the user deleted since apply stays deleted:
apply does not write it again (an owned file only on hook runs, an edited or
merged one until remove + apply), and remove does not restore its backup.

ctx (appglass.core.Ctx)
-----------------------
ctx.mode                 'dark' | 'light'
ctx.colors(role)         '#rrggbb' for a matugen role (surface,
                         surface_container, surface_container_high, on_surface,
                         on_surface_variant, outline, primary, tertiary, error...).
                         Source: $XDG_STATE_HOME/appglass/colors.json (hook
                         output), else $XDG_CACHE_HOME/dms/dms-colors.json.
ctx.dank16               list of the 16 DMS terminal colours for ctx.mode, or None
ctx.levels               .content .bar .popup (floats), .content8 .bar8 .popup8
                         (0-255), .bar_over_content (alpha for a bar painted
                         on top of the content so it lands at .bar)
ctx.alpha_hex(a)         0.60 -> '99'
ctx.rgba(hex, a)         'rgba(16, 20, 24, 0.60)'
ctx.readable(fg, bg, a)  fg moved toward white/black until opaque text on
                         bg-at-alpha glass reaches 2.25:1 over any backdrop
ctx.config_path(*p) / data_path / state_path / cache_path / home_path
ctx.read_text(path)      current text (as planned so far), None if absent;
                         Conflict if the path is a directory or unreadable
ctx.write_owned(path, text)
                         a file appglass owns (deleted on remove). Conflict if
                         the path exists and is not appglass's.
ctx.edit_text(path, fn, undo=None)
                         change a user file: fn(text) -> text, '' when absent.
                         Backed up, restored byte-identical on remove. fn must
                         be idempotent; on re-apply it gets the original text,
                         so a second apply writes identical bytes.
ctx.merge_json(path, dict)
                         merge top-level keys into a JSON object file, written
                         in place (same inode); other keys kept. A key
                         appglass set that is gone from the file since
                         (changed_since_apply) stays out, warned once with
                         key "keys-out:<path>"; remove leaves it out too
ctx.changed_since_apply(path)
                         this owner wrote path (edit/json) and it changed
                         since, deleted included (sticky): keep a user's
                         opt-out instead of putting appglass's part back
ctx.deleted_since_apply(path)
                         this owner wrote path and the user deleted it.
                         edit_text / merge_json then plan nothing and leave
                         it deleted on every apply until remove (the record
                         stays, warned once with key "deleted:<path>");
                         write_owned does the same on --from-hook runs, a
                         manual apply writes the owned file again
ctx.warn(msg)            printed as a warning after apply
ctx.warn_once(key, msg)  the same, but only on the first of consecutive
                         applies that call it with this key (the hook
                         re-applies on every theme change). A second call
                         with the same key in one run is ignored, so a
                         family can word a core warning (e.g. "deleted:<path>")
                         itself by calling it first
ctx.app_ids              None (default: the module's APP_IDS go into the niri
                         rule) or the list of app-id regexes this run
                         configured, for a family of several apps of which
                         only some are installed
ctx.env                  appglass.core.Env (paths, which, flatpak_installed, run)

Colour helpers (appglass.core): norm_hex, hex_to_rgb, rgb_to_hex, mix, scale,
luminance, contrast, worst_contrast, readable, alpha8, alpha_hex, rgba.

Levels: content = DMS settings.json foregroundLayerTransparency (0.60 when
missing), bars = max(content, 0.65), menus/popups/tooltips = 1.0. Text, icons
and logos never get an alpha.
"""
