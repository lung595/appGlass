"""Core: colour helpers, levels, palette, sandbox guard, state, writes."""

import json
import os
import shutil
import unittest

from fixtures.sandbox import Sandbox, fixture
from appglass import core


class ColourHelpers(unittest.TestCase):
    def test_alpha(self):
        self.assertEqual(core.alpha8(0.6), 153)
        self.assertEqual(core.alpha_hex(0.6), "99")
        self.assertEqual(core.alpha_hex(1.0), "ff")
        self.assertEqual(core.rgba("#101418", 0.6), "rgba(16, 20, 24, 0.60)")
        self.assertEqual(core.rgba("#ffffff", 0.65), "rgba(255, 255, 255, 0.65)")
        self.assertEqual(core.norm_hex("#AABBCCDD"), "#aabbcc")
        with self.assertRaises(ValueError):
            core.norm_hex("blue")

    def test_contrast(self):
        self.assertAlmostEqual(core.contrast("#000000", "#ffffff"), 21.0, places=3)
        # outline on the dark glass fails over a white backdrop
        self.assertLess(core.worst_contrast("#8c9198", "#101418", 0.6), 2.0)
        # inside the glass range there is always a backdrop that matches
        self.assertEqual(core.worst_contrast("#606060", "#101418", 0.6), 1.0)

    def test_readable(self):
        for mode_bg in ("#101418", "#f7f9ff"):
            for fg in ("#8c9198", "#cf80fb", "#ff729d", "#787300", "#6c7279", "#1e567e"):
                r = core.readable(fg, mode_bg, 0.6)
                self.assertGreaterEqual(core.worst_contrast(r, mode_bg, 0.6), 2.25, (fg, r))
        ok = "#e0e2e8"
        self.assertEqual(core.readable(ok, "#101418", 0.6), ok)


class LevelsAndPalette(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.cleanup()

    def test_levels_from_settings(self):
        self.sb.seed_dms()
        lv = core.Levels.from_env(core.Env(self.sb.env))
        self.assertEqual((lv.content8, lv.bar8, lv.popup8), (153, 166, 255))
        self.assertAlmostEqual(lv.bar, 0.65)

    def test_levels_default_and_high(self):
        lv = core.Levels.from_env(core.Env(self.sb.env))
        self.assertEqual(lv.content8, 153)
        self.sb.write("dms/settings.json", json.dumps({"foregroundLayerTransparency": 0.8}))
        lv = core.Levels.from_env(core.Env(self.sb.env))
        self.assertEqual((lv.content8, lv.bar8), (204, 204))

    def test_palette_sources(self):
        self.sb.seed_dms()
        env = core.Env(self.sb.env)
        p = core.Palette(env)
        self.assertEqual(p.mode, "dark")
        self.assertTrue(p.source.endswith("dms/dms-colors.json"))
        self.assertEqual(p.get("surface"), "#101418")
        self.assertEqual(len(p.dank16), 16)
        # the hook output wins
        os.makedirs(env.state_dir)
        with open(os.path.join(env.state_dir, "colors.json"), "w") as f:
            json.dump({"mode": "light", "colors": {"surface": "#FAFAFA"},
                       "dank16term": {"color%d" % i: "#00000%d" % (i % 10) for i in range(16)}}, f)
        p = core.Palette(env)
        self.assertEqual((p.mode, p.get("surface")), ("light", "#fafafa"))
        self.assertEqual(p.term16[1], "#000001")
        with self.assertRaises(core.AppglassError):
            p.get("no_such_role")

    def test_malformed_hook_output_falls_back(self):
        self.sb.seed_dms()
        env = core.Env(self.sb.env)
        os.makedirs(env.state_dir)
        with open(os.path.join(env.state_dir, "colors.json"), "w") as f:
            f.write("{not json")
        p = core.Palette(env)
        self.assertTrue(p.source.endswith("dms-colors.json"))


class Sandboxing(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")

    def tearDown(self):
        self.sb.cleanup()

    def test_write_outside_sandbox_exits_2_and_writes_nothing(self):
        jail = self.sb.path("jail")
        os.mkdir(jail)
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty",
                                     env={"APPGLASS_SANDBOX": jail})
        self.assertEqual(code, 2, err)
        self.assertIn("refusing to write", err)
        self.assertEqual(self.sb.tree_hash(), before)
        for cmd in (["remove"], ["hook", "install"]):
            code, _, _ = self.sb.run(*cmd, env={"APPGLASS_SANDBOX": jail})
            self.assertEqual(code, 2)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_empty_sandbox_refused(self):
        # set but empty must refuse, never mean "no sandbox"
        before = self.sb.tree_hash()
        for cmd in (["apply", "--only", "alacritty"], ["apply", "--from-hook"], ["remove"],
                    ["hook", "install"], ["status"]):
            code, out, err = self.sb.run(*cmd, assume="alacritty", env={"APPGLASS_SANDBOX": ""})
            self.assertEqual(code, 2, (cmd, err))
            self.assertIn("APPGLASS_SANDBOX is set but empty", err)
            code, _, err = self.sb.run(*cmd, assume="alacritty", env={"APPGLASS_SANDBOX": "  "})
            self.assertEqual(code, 2, (cmd, err))
        self.assertEqual(self.sb.tree_hash(), before)

    def test_outside_target_refused(self):
        outside = Sandbox()
        try:
            outside.seed_niri()
            ob = outside.tree_hash()
            code, _, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty",
                                       env={"NIRI_CONFIG": outside.cfg("niri", "config.kdl")})
            self.assertEqual(code, 2, err)
            self.assertEqual(outside.tree_hash(), ob)
        finally:
            outside.cleanup()

    def test_dry_run_writes_nothing(self):
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--dry-run", assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertIn("would write", out)
        self.assertIn("niri: would write", out)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_status_and_unknown_family(self):
        code, out, _ = self.sb.run("status", assume="alacritty")
        self.assertEqual(code, 0)
        self.assertIn("content 0.60 (153)", out)
        code, _, err = self.sb.run("apply", "--only", "nope")
        self.assertEqual(code, 1)
        self.assertIn("unknown family", err)


class HookScope(unittest.TestCase):
    """apply --from-hook (the matugen post_hook) refreshes only what was applied."""

    ASSUME = "alacritty,dux,gtk3,gtk4,herdr,obsidian"

    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        self.before = self.sb.tree_hash()

    def tearDown(self):
        self.sb.cleanup()

    def run_ag(self, *argv):
        code, out, err = self.sb.run(*argv, assume=self.ASSUME)
        self.assertEqual(code, 0, err)
        return out, err

    def owners(self):
        p = self.sb.path("home", ".local", "state", "appglass", "state.json")
        return sorted(self.sb.json(p)["owners"]) if os.path.exists(p) else []

    def test_hook_reapplies_only_recorded_families(self):
        self.run_ag("apply", "--only", "alacritty,dux")
        self.assertEqual(self.owners(), ["alacritty", "dux", "niri"])
        self.run_ag("apply", "--from-hook", "--quiet")
        self.assertEqual(self.owners(), ["alacritty", "dux", "niri"])
        self.run_ag("remove", "--only", "dux")
        self.run_ag("apply", "--from-hook", "--quiet")
        self.assertEqual(self.owners(), ["alacritty", "niri"])
        self.assertNotIn("dux", self.sb.read(self.sb.cfg("niri", "appglass.kdl")))
        self.assertFalse(os.path.exists(self.sb.cfg("dankcal", "ui-settings.json")))
        self.run_ag("remove")
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_hook_refreshes_colours(self):
        self.run_ag("apply", "--only", "alacritty")
        p = self.sb.cfg("alacritty", "appglass.toml")
        old = self.sb.read(p)
        self.sb.seed_dms(light=True)
        self.run_ag("apply", "--from-hook", "--quiet")
        self.assertNotEqual(self.sb.read(p), old)

    def test_hook_without_apply_is_a_noop(self):
        out, _ = self.run_ag("apply", "--from-hook")
        self.assertIn("nothing to refresh", out)
        self.assertEqual(self.sb.tree_hash(), self.before)
        # only the hook installed: still nothing applied
        self.run_ag("hook", "install")
        installed = self.sb.tree_hash()
        self.run_ag("apply", "--from-hook", "--quiet")
        self.assertEqual(self.owners(), ["hook"])
        self.assertEqual(self.sb.tree_hash(), installed)
        self.run_ag("remove")
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_hook_after_full_remove_is_a_noop(self):
        self.run_ag("apply", "--only", "alacritty")
        self.run_ag("remove", "--only", "alacritty")
        self.run_ag("apply", "--from-hook", "--quiet")
        self.assertEqual(self.sb.tree_hash(), self.before)

    def _backups(self):
        d = self.sb.path("home", ".local", "state", "appglass")
        b = os.path.join(d, "backup")
        have = sorted(os.listdir(b)) if os.path.isdir(b) else []
        st = self.sb.json(os.path.join(d, "state.json"))
        used = sorted(os.path.basename(r["backup"]) for o in st["owners"].values()
                      for r in o["files"].values() if r.get("backup"))
        return have, used

    def test_remove_only_drops_its_backups(self):
        self.sb.seed("matugen/config.toml", "matugen/config.toml")
        before = self.sb.tree_hash()
        self.run_ag("hook", "install")
        self.run_ag("apply", "--only", "alacritty")
        have, used = self._backups()
        self.assertEqual(have, used)
        self.assertEqual(len(have), 3)        # matugen config, niri config, alacritty.toml
        self.run_ag("remove", "--only", "alacritty")
        have, used = self._backups()
        self.assertEqual(have, used)
        self.assertEqual(len(have), 1)        # the hook's stays (niri has no app left)
        # the auto-remove of an uninstalled family drops its backups too
        self.run_ag("apply", "--only", "alacritty")
        code, out, err = self.sb.run("apply", "--from-hook", "--quiet",
                                     assume_not="alacritty")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.owners(), ["hook"])
        have, used = self._backups()
        self.assertEqual(have, used)
        self.assertEqual(len(have), 1)
        self.run_ag("remove")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_manual_apply_unchanged(self):
        self.run_ag("apply", "--only", "alacritty")
        self.run_ag("apply")
        self.assertIn("dux", self.owners())


class Writes(unittest.TestCase):
    """ctx.merge_json / edit_text / write_owned through the App, without a family."""

    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()

    def tearDown(self):
        self.sb.cleanup()

    def _app(self):
        return core.App(self.sb.env)

    def test_merge_json_in_place_and_restore(self):
        p = self.sb.write("app/settings.json", '{"a": 1,  "keep": "x"}\n')
        ino = os.stat(p).st_ino
        before = self.sb.tree_hash()
        app = self._app()
        ctx = app.ctx("t")
        ctx.merge_json(p, {"a": 2, "new": True})
        app.commit(ctx)
        self.assertEqual(os.stat(p).st_ino, ino)
        self.assertEqual(self.sb.json(p), {"a": 2, "keep": "x", "new": True})
        # re-apply: identical bytes
        data = self.sb.readb(p)
        app = self._app()
        ctx = app.ctx("t")
        ctx.merge_json(p, {"a": 2, "new": True})
        self.assertEqual(app.commit(ctx), [])
        self.assertEqual(self.sb.readb(p), data)
        app.remove_owner("t")
        app.finish()
        self.assertEqual(self.sb.tree_hash(), before)
        self.assertEqual(os.stat(p).st_ino, ino)

    def test_merge_json_app_rewrote_file(self):
        p = self.sb.write("app/settings.json", '{"a": 1}\n')
        app = self._app()
        ctx = app.ctx("t")
        ctx.merge_json(p, {"a": 2, "new": 1})
        app.commit(ctx)
        with open(p, "w") as f:
            json.dump({"a": 2, "new": 1, "user": "kept"}, f)
        app = self._app()
        app.remove_owner("t")
        app.finish()
        self.assertEqual(self.sb.json(p), {"a": 1, "user": "kept"})

    def test_merge_json_reapply_after_app_rewrote(self):
        # the hook re-applies between the app's rewrite and remove
        p = self.sb.write("app/settings.json", '{"a": 1}\n')
        app = self._app()
        ctx = app.ctx("t")
        ctx.merge_json(p, {"a": 2, "new": 1})
        app.commit(ctx)
        with open(p, "w") as f:
            json.dump({"a": 2, "new": 1, "user": "kept"}, f)
        for _ in range(2):
            app = self._app()
            ctx = app.ctx("t")
            ctx.merge_json(p, {"a": 2, "new": 1})
            app.commit(ctx)
        app = self._app()
        app.remove_owner("t")
        app.finish()
        self.assertEqual(self.sb.json(p), {"a": 1, "user": "kept"})

    def test_merge_json_keys_taken_out_stay_out(self):
        # the user drops appglass's keys from a merged file: an opt-out the
        # hook keeps (warned once); keys still there are refreshed; remove
        # leaves the dropped ones out and puts the others back
        p = self.sb.write("app/settings.json", '{"a": 1, "keep": "x"}\n')

        def run():
            app = self._app()
            app.from_hook = True
            ctx = app.ctx("t")
            ctx.merge_json(p, {"a": 2, "new": 1, "b": 3})
            app.commit(ctx)
            return ctx.messages
        run()
        with open(p, "w") as f:
            json.dump({"keep": "x", "b": 3, "user": 1}, f)
        msgs = run()
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("a, new", msgs[0])
        self.assertEqual(run(), [])
        self.assertEqual(self.sb.json(p), {"keep": "x", "b": 3, "user": 1})
        app = self._app()
        app.warn = lambda m: None
        app.remove_owner("t")
        app.finish()
        self.assertEqual(self.sb.json(p), {"keep": "x", "user": 1})

    def test_merge_json_emptied_or_recreated_without_keys(self):
        for how in ("empty", "recreate"):
            with self.subTest(how=how):
                p = self.sb.write("app/%s.json" % how, '{"a": 1}\n')

                def run():
                    app = self._app()
                    app.from_hook = True
                    app.warn = lambda m: None
                    ctx = app.ctx("t")
                    ctx.merge_json(p, {"a": 2})
                    app.commit(ctx)
                run()
                if how == "recreate":
                    os.remove(p)
                    run()
                    self.assertFalse(os.path.lexists(p))
                with open(p, "w") as f:
                    f.write('{"mine": 1}')
                run()
                run()
                self.assertEqual(self.sb.read(p), '{"mine": 1}')
                app = self._app()
                app.warn = lambda m: None
                app.remove_owner("t")
                app.finish()
                # the pre-apply value is not put into the user's new file,
                # and its bytes are left as they are
                self.assertEqual(self.sb.read(p), '{"mine": 1}')

    def test_merge_json_directory_is_conflict(self):
        p = self.sb.cfg("app", "settings.json")
        os.makedirs(p)
        ctx = self._app().ctx("t")
        with self.assertRaises(core.Conflict):
            ctx.merge_json(p, {"a": 1})

    def _edit(self, p):
        app = self._app()
        ctx = app.ctx("t")
        ctx.edit_text(p, lambda t: t if "ours\n" in t else t + "ours\n")
        app.commit(ctx)

    def test_edit_text_user_change_survives_reapply(self):
        # user edit, then re-applies (the hook), then remove: the edit is kept
        p = self.sb.write("app/conf", "line\n")
        self._edit(p)
        with open(p, "a") as f:
            f.write("user\n")
        self._edit(p)
        self._edit(p)
        self.assertEqual(self.sb.read(p), "line\nours\nuser\n")
        app = self._app()
        err = []
        app.warn = err.append
        app.remove_owner("t")
        app.finish()
        # no undo for this owner: the original back, the user's version saved
        self.assertEqual(self.sb.read(p), "line\n")
        self.assertEqual(self.sb.read(p + ".appglass-changed"), "line\nours\nuser\n")
        self.assertTrue(err)

    def test_edit_text_created_then_user_change_survives_reapply(self):
        p = self.sb.cfg("app", "conf")
        os.makedirs(os.path.dirname(p))
        self._edit(p)
        with open(p, "a") as f:
            f.write("user\n")
        self._edit(p)
        self._edit(p)
        app = self._app()
        app.warn = lambda m: None
        app.remove_owner("t")
        app.finish()
        self.assertEqual(self.sb.read(p), "ours\nuser\n")

    def test_edit_text_unchanged_reapply_still_rebuilds_from_original(self):
        p = self.sb.write("app/conf", "line\n")
        before = self.sb.tree_hash()
        self._edit(p)
        self._edit(p)
        app = self._app()
        app.remove_owner("t")
        app.finish()
        self.assertEqual(self.sb.tree_hash(), before)

    def _edit_undo(self, p):
        app = self._app()
        ctx = app.ctx("t")
        changed = ctx.changed_since_apply(p)   # keep a user's opt-out
        ctx.edit_text(p, lambda t: t if "ours\n" in t or changed else "base\nours\n" + t,
                      undo=lambda t: t.replace("ours\n", ""))
        app.commit(ctx)
        return app

    def _remove_with_undo(self):
        app = self._app()
        app._undo_for = lambda owner, path: (lambda t: t.replace("ours\n", ""))
        err = []
        app.warn = err.append
        app.remove_owner("t")
        app.finish()
        return err

    def test_created_edit_changed_remove_runs_undo(self):
        p = self.sb.cfg("app", "conf")
        os.makedirs(os.path.dirname(p))
        self._edit_undo(p)
        self.assertEqual(self.sb.read(p), "base\nours\n")
        with open(p, "a") as f:
            f.write("user\n")
        self._edit_undo(p)
        err = self._remove_with_undo()
        self.assertEqual(self.sb.read(p), "base\nuser\n")
        self.assertTrue(err)

    def test_created_edit_changed_nothing_of_the_user_left_deleted(self):
        p = self.sb.cfg("app", "conf")
        os.makedirs(os.path.dirname(p))
        for user in ("base\n", "", "\nbase\nours\n\n", "base\nmine\n"):
            self._edit_undo(p)
            with open(p, "w") as f:
                f.write(user)       # our part out, emptied, blank lines, a user line
            self._edit_undo(p)
            self.assertEqual(self.sb.read(p), user)
            self._remove_with_undo()
            if "mine" in user:
                self.assertEqual(self.sb.read(p), user)
                os.remove(p)
            else:
                self.assertFalse(os.path.exists(p), repr(user))

    def test_changed_since_apply(self):
        p = self.sb.cfg("app", "conf")
        os.makedirs(os.path.dirname(p))
        app = self._app()
        self.assertFalse(app.ctx("t").changed_since_apply(p))
        self._edit_undo(p)
        self.assertFalse(self._app().ctx("t").changed_since_apply(p))
        with open(p, "a") as f:
            f.write("user\n")
        self.assertTrue(self._app().ctx("t").changed_since_apply(p))
        self._edit_undo(p)
        # sticky: the file now matches what was written, but it is the user's
        self.assertTrue(self._app().ctx("t").changed_since_apply(p))
        self.assertFalse(self._app().ctx("other").changed_since_apply(p))

    def test_deleted_file_kept_deleted(self):
        # edit_text / merge_json: a recorded file the user deleted is left
        # deleted on every apply (record kept, warned once); remove is clean
        made = self.sb.cfg("app", "made.conf")
        os.makedirs(os.path.dirname(made))
        js = self.sb.cfg("app", "made.json")
        mod = self.sb.write("app/mine.conf", "line\n")
        mjs = self.sb.write("app/mine.json", '{"a": 1}\n')
        before = self.sb.tree_hash()

        def run():
            app = self._app()
            ctx = app.ctx("t")
            for p in (made, mod):
                ctx.edit_text(p, lambda t: t if "ours\n" in t else t + "ours\n")
            for p in (js, mjs):
                ctx.merge_json(p, {"g": 1})
            app.commit(ctx)
            return app, ctx
        run()
        for p in (made, mod, js, mjs):
            os.remove(p)
        for i in range(2):
            app, ctx = run()
            for p in (made, mod, js, mjs):
                self.assertFalse(os.path.lexists(p), p)
                self.assertIn(p, app.state.owners["t"]["files"])
                self.assertTrue(ctx.changed_since_apply(p))
            self.assertEqual(len(ctx.messages), 4 if i == 0 else 0, ctx.messages)
        app = self._app()
        err = []
        app.warn = err.append
        app.remove_owner("t")
        app.finish()
        for p in (made, mod, js, mjs):
            self.assertFalse(os.path.lexists(p), p)       # backups not put back
        self.assertEqual(len(err), 2, err)                  # the two pre-existing files
        self.assertFalse(os.path.exists(self.sb.path("home", ".local", "state", "appglass")))

    def test_deleted_owned_file_kept_on_hook_runs_only(self):
        p = self.sb.cfg("app", "own.conf")

        def run(hook):
            app = self._app()
            app.from_hook = hook
            ctx = app.ctx("t")
            ctx.write_owned(p, "x\n")
            app.commit(ctx)
            return ctx
        run(False)
        os.remove(p)
        ctx = run(True)
        self.assertFalse(os.path.lexists(p))
        self.assertTrue(ctx.messages)
        self.assertEqual(run(True).messages, [])
        run(False)
        self.assertEqual(self.sb.read(p), "x\n")

    def test_stale_deleted_modified_file_not_restored(self):
        # the family no longer plans a file the user deleted: the backup is
        # not written back, and it is dropped
        p = self.sb.write("app/mine.conf", "line\n")
        app = self._app()
        ctx = app.ctx("t")
        ctx.edit_text(p, lambda t: t + "ours\n")
        ctx.write_owned(self.sb.cfg("app", "own"), "x\n")
        app.commit(ctx)
        os.remove(p)
        app = self._app()
        app.warn = lambda m: None
        ctx = app.ctx("t")
        ctx.write_owned(self.sb.cfg("app", "own"), "x\n")
        app.commit(ctx)
        self.assertFalse(os.path.lexists(p))
        b = self.sb.path("home", ".local", "state", "appglass", "backup")
        self.assertEqual(os.listdir(b) if os.path.isdir(b) else [], [])

    def test_read_of_directory_or_unreadable_is_conflict(self):
        d = self.sb.cfg("app", "dir.json")
        os.makedirs(d)
        ctx = self._app().ctx("t")
        with self.assertRaises(core.Conflict):
            ctx.read_text(d)
        with self.assertRaises(core.Conflict):
            ctx.edit_text(d, lambda t: t)
        if os.geteuid() != 0:
            p = self.sb.write("app/locked.json", "{}\n")
            os.chmod(p, 0)
            try:
                for f in (ctx.read_text, lambda p: ctx.merge_json(p, {"a": 1}),
                          lambda p: ctx.edit_text(p, lambda t: t)):
                    with self.assertRaises(core.Conflict):
                        f(p)
            finally:
                os.chmod(p, 0o644)

    def test_warn_once(self):
        def run():
            app = self._app()
            ctx = app.ctx("t")
            ctx.write_owned(self.sb.cfg("app", "x"), "x\n")
            if hit:
                ctx.warn_once("k", "careful")
            app.commit(ctx)
            return ctx.messages
        hit = True
        self.assertEqual(run(), ["careful"])
        self.assertEqual(run(), [])
        hit = False
        self.assertEqual(run(), [])
        hit = True
        self.assertEqual(run(), ["careful"])

    def test_write_owned_refuses_foreign_file(self):
        p = self.sb.write("app/x.conf", "mine\n")
        ctx = self._app().ctx("t")
        with self.assertRaises(core.Conflict):
            ctx.write_owned(p, "theirs\n")

    def test_other_owner_conflict(self):
        p = self.sb.cfg("app", "own.conf")
        app = self._app()
        ctx = app.ctx("a")
        ctx.write_owned(p, "a\n")
        app.commit(ctx)
        ctx = app.ctx("b")
        with self.assertRaises(core.Conflict):
            ctx.write_owned(p, "b\n")
        with self.assertRaises(core.Conflict):
            ctx.edit_text(p, lambda t: t)
        app.remove_owner("a")
        app.finish()
        self.assertFalse(os.path.exists(p))
        self.assertFalse(os.path.exists(self.sb.cfg("app")))

    def test_edit_text_changed_by_user_without_undo(self):
        p = self.sb.write("app/conf", "line\n")
        app = self._app()
        ctx = app.ctx("t")
        ctx.edit_text(p, lambda t: t + "ours\n")
        app.commit(ctx)
        with open(p, "a") as f:
            f.write("user\n")
        app = self._app()
        err = []
        app.warn = err.append
        app.remove_owner("t")
        app.finish()
        self.assertEqual(self.sb.read(p), "line\n")
        self.assertEqual(self.sb.read(p + ".appglass-changed"), "line\nours\nuser\n")
        self.assertTrue(err)

    def test_non_utf8_is_conflict(self):
        p = self.sb.write("app/bin", b"\xff\xfe\x00")
        ctx = self._app().ctx("t")
        with self.assertRaises(core.Conflict):
            ctx.edit_text(p, lambda t: t)

    def test_discover_finds_alacritty(self):
        fams = core.discover()
        self.assertIn("alacritty", fams)
        for f in fams.values():
            self.assertTrue(f.APP_IDS)


if __name__ == "__main__":
    unittest.main()
