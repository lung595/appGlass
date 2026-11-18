"""matugen hook: config section, install/remove byte-identical, template."""

import json
import os
import tomllib
import unittest

from fixtures.sandbox import Sandbox, fixture, REPO
from appglass import core, hook


class Hook(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.env = core.Env(self.sb.env)

    def tearDown(self):
        self.sb.cleanup()

    def test_install_creates_config_and_remove_restores(self):
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("hook", "install")
        self.assertEqual(code, 0, err)
        p = self.sb.cfg("matugen", "config.toml")
        with open(p, "rb") as f:
            cfg = tomllib.load(f)
        t = cfg["templates"]["appglass"]
        self.assertEqual(t["input_path"], os.path.join(REPO, "templates", "colors.json"))
        self.assertTrue(os.path.isabs(t["input_path"]) and os.path.exists(t["input_path"]))
        self.assertEqual(t["output_path"], os.path.join(self.sb.state, "appglass", "colors.json"))
        self.assertEqual(t["post_hook"],
                         os.path.join(REPO, "bin", "appglass") + " apply --from-hook --quiet")
        self.assertIn("config", cfg)
        # idempotent
        data = self.sb.readb(p)
        code, out, _ = self.sb.run("hook", "install")
        self.assertIn("already installed", out)
        self.assertEqual(self.sb.readb(p), data)
        code, out, _ = self.sb.run("hook", "remove")
        self.assertEqual(code, 0)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_set_up_again_after_remove_brings_the_hook_and_units_back(self):
        """The plugin's Set up again after an Uninstall: get, sync of the
        stored settings, then hook install. The sync alone (an event run)
        never writes the hook or the units back."""
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        others = ",".join(n for n in core.discover() if n != "alacritty")
        run = lambda *a: self.sb.run(*a, assume="alacritty", assume_not=others)
        units = [hook.unit_path(self.env, n) for n in hook.UNITS]
        f = self.sb.write("plugin.json.tmp", json.dumps({"fallback": {"mode": "off"}}),
                          base=self.sb.root)
        self.assertEqual(run("hook", "install")[0], 0)
        self.assertEqual(run("sync", "--settings-file", f)[0], 0)
        self.assertEqual(run("remove")[0], 0)
        self.assertFalse(any(os.path.lexists(u) for u in units))
        self.assertEqual(run("get")[0], 0)
        code, out, err = run("sync", "--settings-file", f)
        self.assertEqual(code, 0, err)
        self.assertIn("appglass", self.sb.read(self.sb.cfg("alacritty", "alacritty.toml")))
        self.assertFalse(any(os.path.lexists(u) for u in units), "a sync wrote a unit")
        code, out, err = run("hook", "install")
        self.assertEqual(code, 0, err)
        self.assertTrue(all(os.path.isfile(u) for u in units), units)
        with open(self.sb.cfg("matugen", "config.toml"), "rb") as fh:
            self.assertIn("appglass", tomllib.load(fh)["templates"])
        self.assertEqual(run("doctor")[0], 0)
        # and the next Uninstall takes them out again
        self.assertEqual(run("remove")[0], 0)
        self.assertFalse(any(os.path.lexists(u) for u in units))

    def test_existing_config_appended_and_restored(self):
        self.sb.seed("matugen/config.toml", "matugen/config.toml")
        before = self.sb.tree_hash()
        self.sb.run("hook", "install")
        p = self.sb.cfg("matugen", "config.toml")
        text = self.sb.read(p)
        with open(fixture("matugen", "config.toml")) as f:
            self.assertTrue(text.startswith(f.read()))
        cfg = tomllib.loads(text)
        self.assertEqual(set(cfg["templates"]), {"mine", "appglass"})
        # the rendered output and a later apply are dropped with the hook
        os.makedirs(self.env.state_dir, exist_ok=True)
        with open(hook.output_path(self.env), "w") as f:
            f.write("{}")
        self.sb.run("hook", "remove")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_user_edit_after_install_kept(self):
        self.sb.seed("matugen/config.toml", "matugen/config.toml")
        self.sb.run("hook", "install")
        p = self.sb.cfg("matugen", "config.toml")
        with open(p, "a") as f:
            f.write("\n[templates.later]\ninput_path = 'a'\noutput_path = 'b'\n")
        self.sb.run("hook", "remove")
        cfg = tomllib.loads(self.sb.read(p))
        self.assertEqual(set(cfg["templates"]), {"mine", "later"})

    def _install_old(self):
        # what an older version wrote: post_hook without --from-hook
        orig = hook.HOOK_ARGS
        hook.HOOK_ARGS = "apply --quiet"
        try:
            code, _, err = self.sb.run("hook", "install")
        finally:
            hook.HOOK_ARGS = orig
        self.assertEqual(code, 0, err)

    def test_install_over_old_hook(self):
        for seed in (False, True):
            if seed:
                self.sb.seed("matugen/config.toml", "matugen/config.toml")
            before = self.sb.tree_hash()
            self._install_old()
            p = self.sb.cfg("matugen", "config.toml")
            self.assertIn('apply --quiet"', self.sb.read(p))
            code, out, err = self.sb.run("hook", "install")
            self.assertEqual(code, 0, err)
            self.assertIn("hook: updated", out)
            text = self.sb.read(p)
            self.assertEqual(text.count("[templates.appglass]"), 1)
            self.assertEqual(text.count(hook.BEGIN), 1)
            post = tomllib.loads(text)["templates"]["appglass"]["post_hook"]
            self.assertTrue(post.endswith(" apply --from-hook --quiet"), post)
            data = self.sb.readb(p)
            code, out, _ = self.sb.run("hook", "install")
            self.assertIn("already installed", out)
            self.assertEqual(self.sb.readb(p), data)
            self.sb.run("hook", "remove")
            self.assertEqual(self.sb.tree_hash(), before)

    def test_full_remove_takes_the_hook(self):
        before = self.sb.tree_hash()
        self.sb.run("hook", "install")
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_template(self):
        with open(os.path.join(REPO, "templates", "colors.json")) as f:
            tpl = json.load(f)
        self.assertEqual(tpl["mode"], "{{mode}}")
        with open(fixture("dms", "dms-colors.json")) as f:
            roles = set(json.load(f)["colors"]["dark"])
        self.assertTrue(roles <= set(tpl["colors"]), roles - set(tpl["colors"]))
        for k, v in tpl["colors"].items():
            self.assertEqual(v, "{{colors.%s.default.hex}}" % k)
        self.assertEqual(sorted(tpl["dank16term"]), sorted("color%d" % i for i in range(16)))

    def test_rendered_output_feeds_the_palette(self):
        # what matugen writes from the template, for a light theme
        with open(fixture("dms", "dms-colors-light.json")) as f:
            d = json.load(f)
        rendered = {"mode": "light", "colors": d["colors"]["light"],
                    "dank16term": {k: v["light"] for k, v in d["dank16"].items()}}
        os.makedirs(self.env.state_dir)
        with open(hook.output_path(self.env), "w") as f:
            json.dump(rendered, f)
        p = core.Palette(self.env)
        self.assertEqual(p.mode, "light")
        self.assertEqual(p.source, hook.output_path(self.env))
        self.assertEqual(p.get("surface"), d["colors"]["light"]["surface"])
        self.assertEqual(p.term16[1], d["dank16"]["color1"]["light"])


if __name__ == "__main__":
    unittest.main()
