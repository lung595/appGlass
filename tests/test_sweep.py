"""The uninstall sweep: the rescue copy of the CLI and remove --if-gone.

A registry install (DMS clones the repository, links its dms-plugin) loses
the repository on a DMS uninstall. ``appglass hook install`` keeps a copy of
the CLI in $XDG_DATA_HOME/appglass/cli (``appglass sync`` refreshes it when
it differs); the plugin's sweep runs that copy with
``remove --if-gone <plugin.json>`` once its folder is gone.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import unittest

from fixtures.sandbox import Sandbox, REPO
from appglass import core, rescue


class RescueCopy(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.env = core.Env(self.sb.env)
        self.cli = rescue.path(self.env)

    def tearDown(self):
        self.sb.cleanup()

    def test_hook_install_writes_the_copy_and_hook_remove_drops_it(self):
        before = self.sb.tree_hash()
        code, _, err = self.sb.run("hook", "install")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.cli, os.path.join(self.sb.data, "appglass", "cli"))
        self.assertTrue(os.access(rescue.bin_path(self.env), os.X_OK))
        for rel in rescue.sources(REPO):
            self.assertEqual(self.sb.readb(os.path.join(self.cli, rel)),
                             self.sb.readb(os.path.join(REPO, rel)), rel)
        names = [n for _, dns, fns in os.walk(self.cli) for n in dns + fns]
        self.assertNotIn("__pycache__", names)
        self.assertFalse(any(n.endswith(".pyc") for n in names))
        self.assertFalse(os.path.exists(os.path.join(self.cli, "templates")))
        self.assertFalse(os.path.exists(os.path.join(self.cli, "shims")))
        self.assertEqual(self.sb.run("hook", "remove")[0], 0)
        self.assertFalse(os.path.lexists(self.cli))
        self.assertEqual(self.sb.tree_hash(), before)

    def test_dry_run_writes_no_copy(self):
        self.assertEqual(self.sb.run("hook", "install", "--dry-run")[0], 0)
        self.assertFalse(os.path.lexists(self.cli))

    def test_sync_refreshes_only_when_it_differs(self):
        self.sb.seed_niri()
        f = self.sb.write("s.json", json.dumps({"fallback": {"mode": "off"}}),
                          base=self.sb.root)
        none = ",".join(core.discover())
        sync = lambda: self.sb.run("sync", "--settings-file", f, assume="", assume_not=none)
        # no hook installed: sync writes no copy
        self.assertEqual(sync()[0], 0)
        self.assertFalse(os.path.lexists(self.cli))
        self.assertEqual(self.sb.run("hook", "install")[0], 0)
        ino = os.stat(self.cli).st_ino
        self.assertEqual(sync()[0], 0)
        self.assertEqual(os.stat(self.cli).st_ino, ino, "an equal copy was written again")
        # an older copy (another version, other files): replaced whole
        stale = os.path.join(self.cli, "appglass", "gone.py")
        with open(stale, "w") as fh:
            fh.write("")
        with open(os.path.join(self.cli, rescue.MANIFEST), "w") as fh:
            fh.write('{"version": "0.0.1", "files": []}')
        code, _, err = sync()
        self.assertEqual(code, 0, err)
        self.assertNotEqual(os.stat(self.cli).st_ino, ino)
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(rescue.current(self.env, REPO))
        # no temp dir left beside it
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.cli))), ["cli"])

    def test_typed_apply_refreshes_a_stale_copy(self):
        self.sb.seed_niri()
        self.assertEqual(self.sb.run("hook", "install")[0], 0)
        with open(os.path.join(self.cli, rescue.MANIFEST), "w") as fh:
            fh.write('{"version": "0.0.1", "files": []}')
        code, _, err = self.sb.run("apply", "--all")
        self.assertEqual(code, 0, err)
        self.assertTrue(rescue.current(self.env, REPO))

    def test_full_remove_drops_it(self):
        self.assertEqual(self.sb.run("hook", "install")[0], 0)
        self.assertTrue(os.path.isdir(self.cli))
        self.assertEqual(self.sb.run("remove")[0], 0)
        self.assertFalse(os.path.lexists(self.cli))


class IfGone(unittest.TestCase):
    """remove --if-gone FILE: the plugin's sweep."""

    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.env = core.Env(self.sb.env)
        self.others = ",".join(n for n in core.discover() if n != "alacritty")
        self.settings = self.sb.write("s.json", json.dumps({"fallback": {"mode": "off"}}),
                                      base=self.sb.root)

    def tearDown(self):
        self.sb.cleanup()

    def run_ag(self, *a, **kw):
        return self.sb.run(*a, assume="alacritty", assume_not=self.others, **kw)

    def glass(self):
        self.assertEqual(self.run_ag("hook", "install")[0], 0)
        code, _, err = self.run_ag("sync", "--settings-file", self.settings)
        self.assertEqual(code, 0, err)
        self.assertIn("appglass", self.sb.read(self.sb.cfg("alacritty", "alacritty.toml")))

    def test_file_there_exits_kept_and_touches_nothing(self):
        self.glass()
        manifest = self.sb.write("plugin.json", "{}", base=self.sb.root)
        before = self.sb.tree_hash()
        code, out, err = self.run_ag("remove", "--if-gone", manifest,
                                     env={"APPGLASS_SWEEP_GRACE": "0"})
        self.assertEqual((code, out), (core.EXIT_KEPT, ""), err)
        self.assertEqual(core.EXIT_KEPT, 3)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_file_back_within_the_grace_exits_kept(self):
        self.glass()
        manifest = os.path.join(self.sb.root, "plugin.json")
        before = self.sb.tree_hash()
        # an update re-cloning the repository
        t = threading.Timer(0.2, lambda: self.sb.write("plugin.json", "{}", base=self.sb.root))
        t.start()
        try:
            code, _, err = self.run_ag("remove", "--if-gone", manifest,
                                       env={"APPGLASS_SWEEP_GRACE": "1"})
        finally:
            t.join()
        self.assertEqual(code, core.EXIT_KEPT, err)
        os.remove(manifest)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_if_gone_refuses_only(self):
        code, _, err = self.run_ag("remove", "--if-gone", "/nonexistent", "--only", "niri",
                                   env={"APPGLASS_SWEEP_GRACE": "0"})
        self.assertNotEqual(code, 0)
        self.assertIn("--if-gone", err)

    def test_gone_restores_everything_from_the_copy_with_the_repository_deleted(self):
        """The registry case end to end, as processes: a clone of the
        repository sets the glass up, the clone is deleted, the rescue copy
        takes every file out (itself last)."""
        clone = os.path.join(self.sb.root, "repos", "abc123")
        for rel in ("bin", "appglass", "templates", "shims", "dms-plugin"):
            shutil.copytree(os.path.join(REPO, rel), os.path.join(clone, rel), symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__", "tests"))
        env = dict(self.sb.env, APPGLASS_ASSUME_INSTALLED="alacritty",
                   APPGLASS_ASSUME_NOT_INSTALLED=self.others, APPGLASS_SWEEP_GRACE="0")
        py = sys.executable or "python3"

        def ag(binary, *a):
            return subprocess.run([py, "-I", "-B", binary] + list(a), env=env, cwd=self.sb.root,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True, timeout=300)

        before = self.sb.tree_hash(self.sb.home)
        cbin = os.path.join(clone, "bin", "appglass")
        r = ag(cbin, "hook", "install")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = ag(cbin, "sync", "--settings-file", self.settings)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("appglass", self.sb.read(self.sb.cfg("alacritty", "alacritty.toml")))
        unit = os.path.join(self.sb.config, "systemd", "user", "appglass-sync.path")
        self.assertTrue(os.path.isfile(unit))
        manifest = os.path.join(clone, "dms-plugin", "plugin.json")
        shutil.rmtree(clone)                    # DMS's RemoveAll
        r = ag(rescue.bin_path(self.env), "remove", "--if-gone", manifest)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.lexists(rescue.path(self.env)))
        self.assertEqual(self.sb.tree_hash(self.sb.home), before, r.stdout)


class PluginContract(unittest.TestCase):
    def test_the_plugin_runs_this_copy_and_reads_this_code(self):
        with open(os.path.join(REPO, "dms-plugin", "components", "logic.js")) as fh:
            js = fh.read()
        self.assertIn("\nvar EXIT_KEPT = %d;\n" % core.EXIT_KEPT, js)
        env = core.Env({"HOME": "/h"})
        self.assertEqual(rescue.bin_path(env), "/h/.local/share/appglass/cli/bin/appglass")
        self.assertIn('d + "/appglass/cli/bin/appglass"', js)
        self.assertIn('["python3", "-I", "-B", rescue, "remove", "--if-gone", manifest]', js)

if __name__ == "__main__":
    unittest.main()
