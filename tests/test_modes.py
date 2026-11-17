"""write_owned modes, ctx.retire, dry-run artifacts and opt-in families."""

import os
import unittest

from fixtures.sandbox import Sandbox
from appglass import core


class Modes(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.bin = os.path.join(self.sb.home, ".local", "bin")
        self.before = self.sb.tree_hash()

    def tearDown(self):
        self.sb.cleanup()

    def run_ctx(self, fn, dry=False):
        app = core.App(self.sb.env)
        app.dry_run = dry
        ctx = app.ctx("testfam")
        out = fn(ctx)
        self.messages = ctx.messages
        app.commit(ctx, dry_run=dry)
        return app, out

    def mode(self, p):
        return os.stat(p).st_mode & 0o777

    def test_owned_mode_and_remove(self):
        p = os.path.join(self.bin, "tool")
        app, _ = self.run_ctx(lambda c: c.write_owned(p, "#!/bin/sh\n", mode=0o755))
        self.assertEqual(self.mode(p), 0o755)
        os.chmod(p, 0o644)                  # a mode change alone is repaired
        self.run_ctx(lambda c: c.write_owned(p, "#!/bin/sh\n", mode=0o755))
        self.assertEqual(self.mode(p), 0o755)
        app = core.App(self.sb.env)
        app.remove_owner("testfam")
        app.finish()
        self.assertEqual(self.sb.tree_hash(), self.before)

    def adopt(self, rel, data, mode):
        p = os.path.join(self.sb.home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        os.chmod(p, mode)
        self.before = self.sb.tree_hash()
        app = core.App(self.sb.env)
        core.adopt_path(app, p, "testfam")
        return p

    def test_adopted_rewrite_restores_bytes_and_mode(self):
        p = self.adopt(".local/bin/hand", b"#!/bin/sh\necho hand\n", 0o750)
        self.run_ctx(lambda c: c.write_owned(p, "#!/bin/sh\necho ours\n", mode=0o755))
        self.assertEqual(self.mode(p), 0o755)
        app = core.App(self.sb.env)
        app.remove_owner("testfam")
        self.assertEqual(self.sb.readb(p), b"#!/bin/sh\necho hand\n")
        self.assertEqual(self.mode(p), 0o750)

    def test_retire(self):
        p = os.path.join(self.bin, "old")
        os.makedirs(self.bin)
        with open(p, "w") as f:
            f.write("old\n")
        _, got = self.run_ctx(lambda c: c.retire(p))   # not adopted: left alone
        self.assertIsNone(got)
        self.assertTrue(os.path.exists(p))
        os.remove(p)
        p = self.adopt(".local/bin/old", b"#!/bin/sh\nold\n", 0o755)
        h = self.sb.tree_hash()
        self.run_ctx(lambda c: c.retire(p), dry=True)
        self.assertTrue(os.path.exists(p))
        self.assertEqual(self.sb.tree_hash(), h)
        app, got = self.run_ctx(lambda c: c.retire(p))
        self.assertEqual(got, p)
        self.assertFalse(os.path.exists(p))
        self.run_ctx(lambda c: c.retire(p))            # stays retired
        self.assertFalse(os.path.exists(p))
        app = core.App(self.sb.env)
        app.remove_owner("testfam")
        self.assertEqual(self.sb.readb(p), b"#!/bin/sh\nold\n")
        self.assertEqual(self.mode(p), 0o755)

    def test_dry_artifact_never_builds(self):
        calls = []
        dest = os.path.join(self.sb.home, ".local", "lib", "x.so")

        def build():
            calls.append(1)
            return b"so"
        app, _ = self.run_ctx(lambda c: c.artifact("x.so", build, "s1", dest=dest), dry=True)
        self.assertEqual(calls, [])
        self.assertTrue(any("would build" in w for w in self.messages), self.messages)
        self.assertEqual(self.sb.tree_hash(), self.before)


class OptIn(unittest.TestCase):
    def test_opt_in_default_off(self):
        class Fam:
            NAME, OPT_IN, KEYS = "f", True, ("org.x.app",)
        sb = Sandbox()
        try:
            app = core.App(sb.env)
            app.families = {"f": Fam}
            # the engine's gate replaces OPT_IN (spec 1.4): on unless switched
            # off, engine.family_gate says when it goes live
            app.settings = {}
            self.assertTrue(core._family_enabled(app, "f"))
            app.settings = {"apps": {"org.x.app": {"enabled": False}}}
            self.assertFalse(core._family_enabled(app, "f"))
            app.settings = {"apps": {"org.x.app": {"enabled": True}}}
            self.assertTrue(core._family_enabled(app, "f"))
            app.settings = {"apps": {"org.x.app": {"enabled": True}, "f": {"enabled": False}}}
            self.assertFalse(core._family_enabled(app, "f"))
        finally:
            sb.cleanup()


if __name__ == "__main__":
    unittest.main()
