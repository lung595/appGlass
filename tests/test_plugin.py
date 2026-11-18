"""The DMS plugin: appglass plugin install|remove (a symlink, sandbox only),
the manifest, the CLI contract the plugin's logic.js is tested against, sync
with glass off keeping the hook, and the QML tests (when Qt's qml is here)."""

import json
import os
import re
import shutil
import subprocess
import unittest

from fixtures.sandbox import REPO, Sandbox, fixture
from fixtures.shimworld import ShimWorld
from appglass import core, inactive, plugin, settings

PLUGIN = os.path.join(REPO, "dms-plugin")


class Install(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.dst = os.path.join(self.sb.config, "dms", "plugins", "appGlass")

    def tearDown(self):
        self.sb.cleanup()

    def test_install_remove(self):
        code, out, err = self.sb.run("plugin", "install", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("would link", out)
        self.assertFalse(os.path.lexists(self.dst))
        code, out, err = self.sb.run("plugin", "install")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.islink(self.dst))
        self.assertEqual(os.path.realpath(self.dst), os.path.realpath(PLUGIN))
        # the plugin's own path to the CLI resolves through the link
        self.assertTrue(os.path.samefile(
            os.path.join(os.path.realpath(self.dst), "..", "bin", "appglass"),
            os.path.join(REPO, "bin", "appglass")))
        code, out, err = self.sb.run("plugin", "install")
        self.assertEqual(code, 0, err)
        self.assertIn("already links", out)
        # the CLI now leaves the settings to the plugin
        code, out, err = self.sb.run("set", "fallback.mode", "off")
        self.assertEqual(code, 1)
        self.assertIn("managed by the DMS plugin", err)
        code, out, err = self.sb.run("plugin", "remove", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.islink(self.dst))
        code, out, err = self.sb.run("plugin", "remove")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(self.dst))
        code, out, err = self.sb.run("plugin", "remove")
        self.assertEqual(code, 0, err)
        self.assertIn("not installed", out)

    def test_remove_keeps_the_plugins_folder(self):
        """DMS watches dms/plugins from its start only: a folder remove took
        out and install made again is never listed (no load until a scan).
        remove takes out the link alone (and the marker an older install
        wrote), never a folder, made by install or not."""
        parent = os.path.dirname(self.dst)
        self.assertFalse(os.path.lexists(os.path.join(self.sb.config, "dms")))
        for other in (False, True):
            code, out, err = self.sb.run("plugin", "install")
            self.assertEqual(code, 0, err)
            if other:
                os.mkdir(os.path.join(parent, "Other"))
            # the marker of an older install (it named the folders it made)
            with open(os.path.join(parent, ".appglass-made"), "w") as f:
                f.write(parent + "\n")
            code, out, err = self.sb.run("plugin", "remove")
            self.assertEqual(code, 0, err)
            self.assertTrue(os.path.isdir(parent))
            self.assertFalse(os.path.lexists(self.dst))
            self.assertEqual(sorted(os.listdir(parent)), ["Other"] if other else [])
        os.rmdir(os.path.join(parent, "Other"))
        # there before install: the same tree after remove
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("plugin", "install")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(os.listdir(parent)), [os.path.basename(self.dst)])
        code, out, err = self.sb.run("plugin", "remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_remove_says_the_glass_files_stay_only_when_there_are_any(self):
        code, out, err = self.sb.run("plugin", "install")
        code, out, err = self.sb.run("plugin", "remove")
        self.assertEqual(code, 0, err)
        self.assertNotIn("glass files stay", out)
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertEqual(code, 0, err)
        code, out, err = self.sb.run("plugin", "install")
        code, out, err = self.sb.run("plugin", "remove")
        self.assertIn("glass files stay", out)

    def test_refuses_what_is_not_ours(self):
        os.makedirs(self.dst)
        before = self.sb.tree_hash()
        for action in ("install", "remove"):
            code, out, err = self.sb.run("plugin", action)
            self.assertEqual(code, 1, (action, out, err))
            self.assertIn("left as is", err)
        self.assertEqual(self.sb.tree_hash(), before)
        os.rmdir(self.dst)
        os.symlink(self.sb.root, self.dst)
        for action in ("install", "remove"):
            code, out, err = self.sb.run("plugin", action)
            self.assertEqual(code, 1, (action, out, err))
        self.assertTrue(os.path.islink(self.dst))

    def test_sandbox_guard(self):
        env = core.Env(dict(self.sb.env, XDG_CONFIG_HOME="/nonexistent-real-config"))
        app = type("A", (), {"env": env, "info": lambda self, m: None})()
        with self.assertRaises(core.SandboxViolation):
            plugin.install(app)
        self.assertFalse(os.path.lexists("/nonexistent-real-config"))


class Manifest(unittest.TestCase):
    def test_manifest(self):
        with open(os.path.join(PLUGIN, "plugin.json")) as f:
            m = json.load(f)
        self.assertEqual(m["id"], settings.PLUGIN_ID)
        self.assertEqual(m["author"], "lung595")
        self.assertEqual(m["type"], "composite")
        self.assertEqual(m["requires_dms"], ">=2.0.0")
        self.assertEqual(sorted(m["permissions"]), ["process", "settings_read", "settings_write"])
        for rel in list(m["components"].values()) + [m["settings"]]:
            self.assertTrue(os.path.isfile(os.path.join(PLUGIN, rel)), rel)

    def test_defaults_contract(self):
        """logic.js is tested against this file: it must stay the CLI's defaults."""
        with open(fixture("plugin", "defaults.json")) as f:
            self.assertEqual(json.load(f), settings.validate({}))

    def test_logic_keys_match_the_schema(self):
        with open(os.path.join(PLUGIN, "components", "logic.js")) as f:
            js = f.read()
        easings = re.search(r"var EASINGS = \[([^\]]*)\]", js).group(1)
        self.assertEqual(sorted(re.findall(r'"([^"]+)"', easings)),
                         sorted(inactive.EASINGS))
        modes = re.search(r"var FALLBACK_MODES = \[([^\]]*)\]", js).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', modes), list(settings.FALLBACK_MODES))


class SyncOffKeepsHook(unittest.TestCase):
    def test_glass_off_keeps_hook(self):
        w = ShimWorld()
        try:
            self.assertEqual(w.run("hook", "install")[0], 0)
            unit = w.user(".config/systemd/user", "appglass-sync.path")
            self.assertTrue(os.path.exists(unit))
            f = w.sb.write("plugin-settings.json", json.dumps({"enabled": False}),
                           base=w.sb.root)
            code, out, err = w.run("sync", "--settings-file", f)
            self.assertEqual(code, 0, err)
            self.assertTrue(os.path.exists(unit), "glass off kept the hook")
            st = w.sb.json(os.path.join(w.sb.state, "appglass", "state.json"))
            self.assertEqual(sorted(st["owners"]), ["hook", "settings"])
            # remove still takes everything out
            self.assertEqual(w.run("remove")[0], 0)
            self.assertFalse(os.path.exists(unit))
        finally:
            w.cleanup()


def qml_tool():
    for t in ("qml6", "qml-qt6", "qml", "/usr/lib64/qt6/bin/qml", "/usr/lib/qt6/bin/qml"):
        if shutil.which(t):
            return t
    return None


@unittest.skipUnless(qml_tool(), "no Qt 6 qml tool")
class Qml(unittest.TestCase):
    def test_qml_suite(self):
        env = {k: v for k, v in os.environ.items()
               if k in ("PATH", "LANG", "LC_ALL", "TMPDIR", "USER", "LOGNAME")}
        r = subprocess.run(["sh", os.path.join(PLUGIN, "tests", "qml", "run.sh")],
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=600, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-4000:])
        self.assertIn("all passed", r.stdout)


if __name__ == "__main__":
    unittest.main()
