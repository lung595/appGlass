"""The sync path unit and script follow XDG_CONFIG_HOME / XDG_CACHE_HOME, and a
GTK CSS write by the matugen post_hook, during the sync's settle, still gets
the GTK theme flip."""

import os
import shutil
import subprocess
import tempfile
import time
import unittest

from fixtures.sandbox import REPO
from fixtures.shimworld import ShimWorld


class PathUnitXdg(unittest.TestCase):
    def setUp(self):
        self.w = ShimWorld()

    def tearDown(self):
        self.w.cleanup()

    def unit(self):
        return self.w.sb.read(self.w.user(".config/systemd/user", "appglass-sync.path"))

    def test_default_xdg_keeps_the_repo_unit(self):
        self.assertEqual(self.w.run("hook", "install")[0], 0)
        with open(os.path.join(REPO, "shims", "sync", "appglass-sync.path")) as f:
            self.assertEqual(self.unit(), f.read())

    def test_moved_xdg_dirs_are_watched(self):
        cfg = os.path.join(self.w.sb.home, "dot files", "config")
        cache = os.path.join(self.w.sb.home, "cache%x")
        for d in (cfg, cache):
            os.makedirs(d)
        self.w.sb.env.update(XDG_CONFIG_HOME=cfg, XDG_CACHE_HOME=cache)
        code, out, err = self.w.run("hook", "install")
        self.assertEqual(code, 0, err)
        with open(os.path.join(cfg, "systemd", "user", "appglass-sync.path")) as f:
            text = f.read()
        self.assertIn("PathChanged=%s/niri/dms/windowrules.kdl\n" % cfg, text)
        self.assertIn("PathModified=%s/niri/dms\n" % cfg, text)
        # % is a systemd specifier: doubled
        self.assertIn("PathChanged=%s/dms/dms-colors.json\n"
                      % cache.replace("%", "%%"), text)
        self.assertNotIn("%h/.config", text)
        self.assertNotIn("%h/.cache", text)
        self.assertIn("PathChanged=%h/.local/share/applications\n", text)
        # doctor sees the render it wrote, not a drift
        self.assertNotIn("appglass-sync.path", self.w.run("doctor")[1])

    def test_moved_data_home_is_watched(self):
        data = os.path.join(self.w.sb.home, "data share")
        os.makedirs(data)
        self.w.sb.env.update(XDG_DATA_HOME=data)
        code, out, err = self.w.run("hook", "install")
        self.assertEqual(code, 0, err)
        text = self.unit()
        self.assertIn("PathChanged=%s/applications\n" % data, text)
        self.assertIn("PathChanged=%s/flatpak/.changed\n" % data, text)
        self.assertNotIn("%h/.local/share", text)


class PostHookRace(unittest.TestCase):
    def setUp(self):
        self.w = ShimWorld()
        self.run_dir = tempfile.mkdtemp(prefix="appglass-run-")

    def tearDown(self):
        self.w.cleanup()
        shutil.rmtree(self.run_dir, ignore_errors=True)

    def test_a_post_hook_write_during_the_settle_still_flips(self):
        env = {"APPGLASS_ASSUME_INSTALLED": "gtk3"}
        self.assertEqual(self.w.run("apply", "--only", "gtk3", env=env)[0], 0)
        self.w.sb.set_level(0.7)
        senv = dict(self.w.sb.env, XDG_RUNTIME_DIR=self.run_dir,
                    APPGLASS_SYNC_SETTLE="3", **env)
        p = subprocess.Popen([os.path.join(REPO, "bin", "appglass-sync")], env=senv,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # the sync's start mark first: a CSS written before it is no "change during the settle"
        mark = os.path.join(senv["APPGLASS_SANDBOX"], "appglass-sync.start.%d" % p.pid)
        deadline = time.monotonic() + 30
        while not os.path.exists(mark) and time.monotonic() < deadline:
            time.sleep(0.05)
        # the matugen post_hook writes the new CSS first; the sync's own
        # apply then finds nothing to change
        self.assertEqual(self.w.run("apply", "--from-hook", "--quiet", env=env)[0], 0)
        out = p.communicate(timeout=120)[0]
        self.assertEqual(p.returncode, 0, out)
        self.assertIn("GTK CSS changed", out)


if __name__ == "__main__":
    unittest.main()
