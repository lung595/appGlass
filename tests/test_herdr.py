"""Herdr family: alpha theme, glass layout from main.json, shared.json merge."""

import json
import os
import shutil
import subprocess
import unittest

from fixtures.sandbox import Sandbox, fixture
from appglass import core
from appglass.families import herdr as fam


def load_fixture(*p):
    with open(fixture(*p)) as f:
        return json.load(f)


def node(tree, nid):
    for n in fam._nodes(tree):
        if n.get("id") == nid:
            return n
    return None


class Herdr(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.seed()

    def seed(self, light=False, home="herdr-app"):
        self.home = home
        self.sb.seed_dms(light=light)
        self.sb.seed_niri()
        self.sb.seed("herdr/main.json", os.path.join(home, "layouts", "main.json"))
        self.sb.seed("herdr/shared.json", os.path.join(home, "shared.json"))
        self.before = self.sb.tree_hash()

    def tearDown(self):
        self.sb.cleanup()

    def p(self, *rel):
        return self.sb.cfg(self.home, *rel)

    def apply(self, *extra, env=None):
        code, out, err = self.sb.run("apply", "--only", "herdr", *extra, assume="herdr", env=env)
        self.assertEqual(code, 0, err)
        return out, err

    def theme(self):
        return self.sb.json(self.p("themes", "appglass.json"))

    def layout(self):
        return self.sb.json(self.p("layouts", "appglass.json"))

    # content
    def test_theme_content_and_keys(self):
        self.apply()
        t = self.theme()
        self.assertEqual(set(t), {"background", "foreground", "selection", "cursor",
                                  "ansi", "colors"})
        self.assertEqual(len(t["ansi"]), 16)
        c = t["colors"]
        self.assertEqual(c["canvas"], "#10141899")      # surface @ 0.60 (153)
        self.assertEqual(c["chrome"], "#101418a6")      # surface @ 0.65 (166)
        self.assertEqual(c["background"], "#10141800")
        self.assertEqual(t["background"], "#101418")
        # text roles solid: no alpha on muted/dim/border/foreground/ansi
        for k in ("muted", "dim", "border"):
            self.assertRegex(c[k], r"^#[0-9a-f]{6}$", k)
        self.assertRegex(t["foreground"], r"^#[0-9a-f]{6}$")
        for v in t["ansi"]:
            self.assertRegex(v, r"^#[0-9a-f]{6}$")
        # popups stay Herdr's opaque derivations
        for k in ("popover", "surface", "raised"):
            self.assertNotIn(k, c)
        self.assertEqual(c["muted"], core.readable("#c2c7cf", "#101418", 0.6, fam.TARGET))
        self.assertEqual(t["ansi"][8], core.readable("#c2c7cf", "#101418", 0.6, fam.TARGET))
        self.assertEqual(t["ansi"][0], core.readable("#8c9198", "#101418", 0.6, fam.TARGET))
        self.assertEqual(c["border"], "#4d5259")

    def test_levels_follow_dms_setting(self):
        self.sb.write("dms/settings.json", json.dumps({"foregroundLayerTransparency": 0.75}))
        self.apply()
        c = self.theme()["colors"]
        self.assertEqual(c["canvas"], "#101418bf")      # 191
        self.assertEqual(c["chrome"], "#101418bf")      # max(0.75, 0.65)

    def test_layout_derived_from_main(self):
        self.apply()
        lay = self.layout()
        main = load_fixture("herdr", "main.json")
        self.assertIs(lay["window_blur"], True)
        self.assertEqual(lay["theme"], "appglass")
        self.assertEqual(lay["terminal_opacity"], 0)
        self.assertEqual(lay["background"], "#00000000")
        self.assertIsNone(node(lay, "sidebar")["background"])
        self.assertEqual(node(lay, "work-body")["background"], "canvas")
        # everything else is main.json as shipped
        exp = fam.layout(main)
        self.assertEqual(lay, exp)
        def own(n):     # a node's own keys, without its subtree
            return {k: v for k, v in n.items() if k != "children"}
        for n in fam._nodes(main):
            if n.get("id") and n["id"] not in ("root", "sidebar", "work-body"):
                self.assertEqual(own(node(lay, n["id"])), own(n))

    def test_layout_follows_main_updates(self):
        self.apply()
        main = load_fixture("herdr", "main.json")
        main["terminal_padding"] = [20, 18]
        self.sb.write(os.path.join(self.home, "layouts", "main.json"), json.dumps(main))
        self.apply()
        self.assertEqual(self.layout()["terminal_padding"], [20, 18])

    def test_shared_json_merge(self):
        p = self.p("shared.json")
        ino = os.stat(p).st_ino
        self.apply()
        d = self.sb.json(p)
        self.assertEqual(d["layout"], "appglass")
        self.assertEqual(d["frame.welcomed"], "finished")
        self.assertEqual(d["space.colors"], {"sp1": "ansi6"})
        self.assertEqual(os.stat(p).st_ino, ino)

    def test_idempotent(self):
        self.apply()
        h = self.sb.tree_hash()
        out, _ = self.apply()
        self.assertIn("herdr: up to date", out)
        self.assertEqual(self.sb.tree_hash(), h)

    def test_remove_byte_identical(self):
        self.apply()
        self.apply()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)
        self.assertFalse(os.path.exists(self.sb.path("home", ".local", "state", "appglass")))

    def test_remove_after_herdr_rewrote_shared(self):
        self.apply()
        # Herdr rewrites shared.json compactly with its own new keys
        p = self.p("shared.json")
        d = self.sb.json(p)
        d["space.colors"]["sp2"] = "ansi3"
        with open(p, "w") as f:
            f.write(json.dumps(d, separators=(",", ":")))
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        d = self.sb.json(p)
        self.assertEqual(d["layout"], "main")
        self.assertEqual(d["space.colors"], {"sp1": "ansi6", "sp2": "ansi3"})
        self.assertFalse(os.path.exists(self.p("themes", "appglass.json")))
        self.assertFalse(os.path.exists(self.p("layouts", "appglass.json")))

    def _herdr_rewrites(self, **extra):
        """Herdr rewrites shared.json compactly with new keys of its own."""
        p = self.p("shared.json")
        d = self.sb.json(p)
        d["space.colors"]["sp2"] = "ansi3"
        d.update(extra)
        with open(p, "w") as f:
            f.write(json.dumps(d, separators=(",", ":")))
        return p

    def test_reapply_then_remove_keeps_herdr_keys(self):
        # the matugen hook re-applies after Herdr rewrote shared.json
        self.apply()
        p = self._herdr_rewrites(**{"win98.init": 1})
        self.apply()
        self.assertEqual(self.sb.json(p)["layout"], "appglass")
        self.apply()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.json(p), {
            "layout": "main", "frame.welcomed": "finished",
            "space.colors": {"sp1": "ansi6", "sp2": "ansi3"}, "win98.init": 1})
        self.assertFalse(os.path.exists(self.sb.path("home", ".local", "state", "appglass")))

    def test_reapply_after_compact_rewrite_restores_original_bytes(self):
        # Herdr rewrote the file but added nothing: remove gives the bytes back
        self.apply()
        p = self.p("shared.json")
        d = self.sb.json(p)
        with open(p, "w") as f:
            f.write(json.dumps(d, separators=(",", ":")))
        self.apply()
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_layout_switch_kept(self):
        # the user switches Herdr to another layout; re-apply and remove keep it
        self.apply()
        p = self._herdr_rewrites(layout="win98")
        out, err = self.apply()
        self.assertIn("'win98'", err)
        self.assertEqual(self.sb.json(p)["layout"], "win98")
        self.assertTrue(os.path.isfile(self.p("layouts", "appglass.json")))
        self.sb.run("remove")
        d = self.sb.json(p)
        self.assertEqual(d["layout"], "win98")
        self.assertEqual(d["space.colors"], {"sp1": "ansi6", "sp2": "ansi3"})
        # after a remove, apply selects the glass layout again
        self.apply()
        self.assertEqual(self.sb.json(p)["layout"], "appglass")

    def test_layout_switch_hook_warns_once_and_keeps_files_current(self):
        self.apply()
        p = self._herdr_rewrites(layout="win98")
        hook = lambda: self.sb.run("apply", "--from-hook", "--quiet", assume="herdr")
        code, _, err = hook()
        self.assertEqual(code, 0, err)
        self.assertIn("'win98'", err)
        theme = self.theme()
        self.sb.seed_dms(light=True)
        code, _, err = hook()
        self.assertEqual(code, 0, err)
        self.assertNotIn("'win98'", err)            # said once already
        self.assertEqual(self.sb.json(p)["layout"], "win98")
        self.assertNotEqual(self.theme(), theme)    # the theme still follows DMS
        self.assertTrue(os.path.isfile(self.p("layouts", "appglass.json")))
        code, _, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.json(p)["layout"], "win98")
        self.assertFalse(os.path.exists(self.p("themes", "appglass.json")))
        self.assertFalse(os.path.exists(self.p("layouts", "appglass.json")))

    def test_created_shared_rewritten_by_herdr(self):
        # no shared.json at apply; Herdr writes its own before remove
        os.remove(self.p("shared.json"))
        self.apply()
        p = self.p("shared.json")
        with open(p, "w") as f:
            f.write('{"layout":"appglass","frame.welcomed":"finished"}')
        self.apply()
        self.sb.run("remove")
        self.assertEqual(self.sb.json(p), {"frame.welcomed": "finished"})

    def test_low_alpha_warns(self):
        self.sb.write("dms/settings.json", json.dumps({"foregroundLayerTransparency": 0.3}))
        out, err = self.apply()
        self.assertIn("too clear for readable text", err)
        self.sb.write("dms/settings.json", json.dumps({"foregroundLayerTransparency": 0.6}))
        out, err = self.apply()
        self.assertNotIn("too clear", err)

    def test_no_shared_json(self):
        os.remove(self.p("shared.json"))
        before = self.sb.tree_hash()
        self.apply()
        self.assertEqual(self.sb.json(self.p("shared.json")), {"layout": "appglass"})
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_foreign_theme_protected(self):
        p = self.sb.write(os.path.join(self.home, "themes", "appglass.json"), '{"mine": 1}\n')
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "herdr", assume="herdr")
        self.assertEqual(code, 0)
        self.assertIn("herdr: skipped", err)
        self.assertEqual(self.sb.read(p), '{"mine": 1}\n')
        self.assertEqual(self.sb.tree_hash(), before)

    def test_foreign_layout_protected(self):
        p = self.sb.write(os.path.join(self.home, "layouts", "appglass.json"), '{"mine": 2}\n')
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "herdr", assume="herdr")
        self.assertIn("herdr: skipped", err)
        self.assertEqual(self.sb.read(p), '{"mine": 2}\n')
        self.assertEqual(self.sb.tree_hash(), before)

    def test_no_main_layout_skipped(self):
        os.remove(self.p("layouts", "main.json"))
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "herdr", assume="herdr")
        self.assertEqual(code, 0)
        self.assertIn("herdr: skipped", err)
        self.assertIn("main.json", err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_unusable_main_layout_skipped(self):
        for text in ("not json", '{"id": "root", "children": [{"id": "x"}]}', "[]"):
            self.sb.write(os.path.join(self.home, "layouts", "main.json"), text)
            before = self.sb.tree_hash()
            code, out, err = self.sb.run("apply", "--only", "herdr", assume="herdr")
            self.assertIn("herdr: skipped", err, text)
            self.assertEqual(self.sb.tree_hash(), before, text)

    def test_shared_json_not_object_skipped(self):
        self.sb.write(os.path.join(self.home, "shared.json"), "[1, 2]")
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "herdr", assume="herdr")
        self.assertIn("herdr: skipped", err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_shared_json_directory_skipped(self):
        p = self.p("shared.json")
        os.remove(p)
        os.makedirs(p)
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "herdr", assume="herdr")
        self.assertEqual(code, 0, err)
        self.assertIn("herdr: skipped", err)
        self.assertIn("not a regular file", err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_deleted_shared_json_not_recreated(self):
        self.apply()
        os.remove(self.p("shared.json"))
        code, out, err = self.sb.run("apply", "--from-hook", "--quiet", assume="herdr")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.p("shared.json")))
        self.assertIn("deleted since apply", err)
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.p("shared.json")))
        self.assertFalse(os.path.exists(self.p("themes", "appglass.json")))

    def test_herdr_app_home(self):
        self.sb.cleanup()
        self.sb = Sandbox()
        self.seed(home="elsewhere")
        env = {"HERDR_APP_HOME": self.sb.cfg("elsewhere")}
        self.apply(env=env)
        self.assertTrue(os.path.isfile(self.p("themes", "appglass.json")))
        self.assertFalse(os.path.exists(self.sb.cfg("herdr-app")))
        code, out, err = self.sb.run("remove", env=env)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_not_installed(self):
        code, out, err = self.sb.run("apply", "--only", "herdr", assume_not="herdr")
        self.assertIn("not installed", out)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_installed_detection(self):
        env = core.Env(dict(self.sb.env, PATH=self.sb.path("nobin")))
        self.assertFalse(fam.installed(env))
        b = self.sb.write("herdr-app/herdr-app", "#!/bin/sh\n", base=self.sb.data)
        os.chmod(b, 0o755)
        self.assertTrue(fam.installed(env))

    # readability
    def _check_readable(self, bg):
        t = self.theme()
        texts = [t["foreground"], t["colors"]["muted"], t["colors"]["dim"]] + t["ansi"]
        for c in texts:
            self.assertGreaterEqual(core.worst_contrast(c, bg, 0.6), 2.0, c)
        # bars: the same text on the (more opaque) chrome
        for c in texts:
            self.assertGreaterEqual(core.worst_contrast(c, bg, 0.65), 2.0, c)

    def test_dark_readability(self):
        self.apply()
        self._check_readable("#101418")
        # the default bright black (dank16 color8 #3e4347) would be ~1.1:1
        self.assertLess(core.worst_contrast("#3e4347", "#101418", 0.6), 2.0)

    def test_light_mode_readability(self):
        self.sb.cleanup()
        self.sb = Sandbox()
        self.seed(light=True)
        self.apply()
        t = self.theme()
        self.assertEqual(t["background"], "#f7f9ff")
        self.assertEqual(t["colors"]["canvas"], "#f7f9ff99")
        self.assertEqual(t["colors"]["muted"],
                         core.readable("#42474e", "#f7f9ff", 0.6, fam.TARGET))
        self._check_readable("#f7f9ff")
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), self.before)

    @unittest.skipUnless(shutil.which("niri"), "niri not installed")
    def test_niri_rule(self):
        self.apply()
        kdl = self.sb.read(self.sb.cfg("niri", "appglass.kdl"))
        self.assertIn('match app-id=r#"^herdr-app$"#', kdl)
        r = subprocess.run(["niri", "validate", "-c", self.sb.cfg("niri", "config.kdl")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
