"""ctx.desktop_override, ctx.artifact, adopt and apply --all."""

import json
import os
import subprocess
import shutil
import unittest
from unittest import mock

from fixtures.sandbox import Sandbox
from fixtures.apps import World
from appglass import adapters, core, niri

SYSTEM = """[Desktop Entry]
Type=Application
Name=Foo
Exec=foo %U
Icon=foo
"""

HAND_KDL = """window-rule {
    opacity 1.0
}
window-rule {
    match app-id="^discord$"
    opacity 0.70
}
"""


def themed(text):
    return text.replace("Exec=foo", "Exec=env FOO_GLASS=1 foo") + "X-AppGlass=1\n"


class Override(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sys = self.sb.write("applications/foo.desktop", SYSTEM,
                                 base=self.sb.path("usr", "share"))
        self.sb.env["XDG_DATA_DIRS"] = self.sb.path("usr", "share")
        self.sb.env["FLATPAK_SYSTEM_DIR"] = self.sb.path("no-flatpak")
        self.dest = os.path.join(self.sb.data, "applications", "foo.desktop")

    def tearDown(self):
        self.sb.cleanup()

    def apply(self, fn=themed):
        app = core.App(self.sb.env)
        ctx = app.ctx("testfam")
        p = ctx.desktop_override("foo.desktop", fn)
        app.commit(ctx)
        return app, p

    def test_created_regenerated_removed(self):
        before = self.sb.tree_hash()
        app, p = self.apply()
        self.assertEqual(p, self.dest)
        self.assertEqual(self.sb.read(p), themed(SYSTEM))
        rec = app.state.owners["testfam"]["files"][p]
        self.assertEqual(rec["meta"]["source"], self.sys)
        old_sha = rec["meta"]["source_sha256"]
        # a package update changes the system launcher: the override follows
        self.sb.write("applications/foo.desktop", SYSTEM.replace("Icon=foo", "Icon=foo2"),
                      base=self.sb.path("usr", "share"))
        app, p = self.apply()
        self.assertIn("Icon=foo2", self.sb.read(p))
        self.assertIn("FOO_GLASS", self.sb.read(p))
        self.assertNotEqual(app.state.owners["testfam"]["files"][p]["meta"]["source_sha256"],
                            old_sha)
        with open(self.sys, "w") as f:
            f.write(SYSTEM)
        app = core.App(self.sb.env)
        app.remove_owner("testfam")
        app.finish()
        self.assertEqual(self.sb.tree_hash(), before)

    def test_no_system_launcher(self):
        app = core.App(self.sb.env)
        ctx = app.ctx("testfam")
        self.assertIsNone(ctx.desktop_override("bar.desktop", themed))

    def test_hand_file_conflict_until_adopted(self):
        hand = "[Desktop Entry]\nType=Application\nName=Foo (mine)\nExec=foo --mine\n"
        self.sb.write("applications/foo.desktop", hand, base=self.sb.data)
        with self.assertRaises(core.Conflict) as cm:
            self.apply()
        self.assertIn("appglass adopt", str(cm.exception))
        self.assertEqual(self.sb.read(self.dest), hand)
        app = core.App(self.sb.env)
        core.adopt_path(app, self.dest, "testfam")
        self.assertEqual(self.sb.read(self.dest), hand)   # adopt alone writes nothing
        app, p = self.apply()
        self.assertEqual(self.sb.read(p), themed(SYSTEM))
        app.remove_owner("testfam")
        self.assertEqual(self.sb.read(self.dest), hand)    # byte-identical original

    def test_symlink_conflict(self):
        os.makedirs(os.path.dirname(self.dest))
        os.symlink(self.sys, self.dest)
        with self.assertRaises(core.Conflict):
            self.apply()

    def test_artifact_stamp(self):
        calls = []

        def build():
            calls.append(1)
            return b"\x7fELF shim %d" % len(calls)

        before = self.sb.tree_hash()
        for stamp in ("v1", "v1", "v2"):
            app = core.App(self.sb.env)
            ctx = app.ctx("testfam")
            p = ctx.artifact("shim.so", build, stamp)
            app.commit(ctx)
        self.assertEqual(len(calls), 2)
        self.assertEqual(p, os.path.join(self.sb.cache, "appglass", "testfam", "shim.so"))
        self.assertEqual(self.sb.readb(p), b"\x7fELF shim 2")
        rec = app.state.owners["testfam"]["files"][p]
        self.assertEqual(rec["meta"], {"artifact": True, "stamp": "v2"})
        app.remove_owner("testfam")
        app.finish()
        self.assertEqual(self.sb.tree_hash(), before)


class Adopt(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        cfg = self.sb.cfg("niri", "config.kdl")
        with open(cfg, "a") as f:
            f.write('include optional=true "appglass-test.kdl"\n')
        self.hand = self.sb.write("niri/appglass-test.kdl", HAND_KDL)

    def tearDown(self):
        self.sb.cleanup()

    def test_conflict_until_adopted_then_stub_and_restore(self):
        code, out, err = self.sb.run("apply", assume="alacritty", assume_not="gtk3,gtk4,herdr,dux,obsidian")
        self.assertIn("appglass-test.kdl is a hand-made file", err)
        self.assertIn("appglass adopt", err)
        self.assertEqual(self.sb.read(self.hand), HAND_KDL)
        before_adopt = self.sb.readb(self.hand)
        code, out, err = self.sb.run("adopt", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("would adopt ~/.config/niri/appglass-test.kdl", out + err)
        self.assertEqual(self.sb.readb(self.hand), before_adopt)
        code, out, err = self.sb.run("adopt")
        self.assertEqual(code, 0, err)
        self.assertIn("adopted ~/.config/niri/appglass-test.kdl", out + err)
        st = self.sb.json(os.path.join(self.sb.state, "appglass", "state.json"))
        rec = st["owners"]["niri"]["files"][self.hand]
        self.assertTrue(rec["adopted"])
        code, out, err = self.sb.run("apply", assume="alacritty", assume_not="gtk3,gtk4,herdr,dux,obsidian")
        self.assertEqual(code, 0, err)
        self.assertNotIn("hand-made", err)
        self.assertEqual(self.sb.read(self.hand), niri.ADOPTED_STUB)
        if shutil.which("niri"):
            r = subprocess.run(["niri", "validate", "-c", self.sb.cfg("niri", "config.kdl")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        code, out, err = self.sb.run("status", "--json")
        h = [x for x in json.loads(out)["hand_files"] if x["path"].endswith("appglass-test.kdl")]
        self.assertEqual(h[0]["status"], "adopted")
        self.assertEqual(self.sb.run("remove")[0], 0)
        self.assertEqual(self.sb.readb(self.hand), before_adopt)

    def test_apply_all_adopt_dry_run(self):
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--all", "--adopt", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("would adopt ~/.config/niri/appglass-test.kdl", out)
        line = [x for x in out.splitlines() if x.startswith("niri: would write")][0]
        self.assertIn(self.hand, line)
        self.assertNotIn("leaves it alone", err)
        self.assertEqual(self.sb.tree_hash(), before)
        code, out, err = self.sb.run("apply", "--all", "--adopt")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(self.hand), niri.ADOPTED_STUB)
        self.assertEqual(self.sb.run("remove")[0], 0)
        self.assertEqual(self.sb.read(self.hand), HAND_KDL)

    def test_adopt_unknown_and_unimplemented(self):
        code, out, err = self.sb.run("adopt", self.sb.cfg("niri", "config.kdl"))
        self.assertEqual(code, 1)
        self.assertIn("not a hand-made file appglass knows", err)
        self.sb.write("applications/obs.desktop", "[Desktop Entry]\n", base=self.sb.data)
        extra = ((".local/share/applications/obs.desktop", "obs-plugin", "a test file"),)
        with mock.patch.object(adapters, "HAND_FILES", adapters.HAND_FILES + extra):
            code, out, err = self.sb.run("adopt", "~/.local/share/applications/obs.desktop")
        self.assertEqual(code, 0, err)
        self.assertIn("not implemented yet", err)
        self.assertFalse(os.path.exists(os.path.join(self.sb.state, "appglass", "state.json")))


class ApplyAll(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.world = World(self.sb).build()
        self.sb.env.update(self.world.env())

    def tearDown(self):
        self.sb.cleanup()

    def test_dry_run_writes_nothing(self):
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--all", "--adopt", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("apps: 1 delegated", out)
        self.assertIn("steam-cdp", out)
        self.assertIn("niri: would write", out)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_value_mode_gets_fallback_ids_and_hook_keeps_them(self):
        self.assertEqual(self.sb.run("set", "fallback.mode", "value")[0], 0)
        code, out, err = self.sb.run("apply", "--all")
        self.assertEqual(code, 0, err)
        kdl = self.sb.read(self.sb.cfg("niri", "appglass.kdl"))
        fallback = kdl.split("// fallback: whole-window")[1].split("// games")[0]
        self.assertIn('match app-id=r#"^discord$"#', fallback)
        self.assertIn('match app-id=r#"^steam$"#', fallback)
        self.assertNotIn("firefox", kdl)
        self.assertNotIn("steam_app_480", kdl)   # covered by ^steam_app_\d+$
        code, out, err = self.sb.run("apply", "--from-hook")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(self.sb.cfg("niri", "appglass.kdl")), kdl)
        self.assertEqual(self.sb.run("remove")[0], 0)
        self.assertFalse(os.path.exists(self.sb.cfg("niri", "appglass.kdl")))

    def test_adopt_needs_all(self):
        code, out, err = self.sb.run("apply", "--adopt")
        self.assertEqual(code, 1)
        self.assertIn("--adopt goes with --all", err)


if __name__ == "__main__":
    unittest.main()
