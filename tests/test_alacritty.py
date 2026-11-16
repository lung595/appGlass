"""Alacritty family: appglass.toml, the main-file edit, readability, restore."""

import json
import os
import shutil
import subprocess
import time
import tomllib
import unittest

from fixtures.sandbox import Sandbox, fixture
from appglass import core
from appglass.families import alacritty as fam

NAMES = fam.NAMES


def merged(sb):
    """Effective colours: dank-theme.toml, then appglass.toml (import order)."""
    out = {}
    for name in ("dank-theme.toml", "appglass.toml"):
        p = sb.cfg("alacritty", name)
        if os.path.exists(p):
            with open(p, "rb") as f:
                d = tomllib.load(f)
            for sec, vals in d.get("colors", {}).items():
                if isinstance(vals, dict):
                    out.setdefault(sec, {}).update(vals)
    return out


class Alacritty(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.seed()

    def seed(self, light=False):
        self.sb.seed_dms(light=light)
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.sb.seed("alacritty/dank-theme-light.toml" if light else "alacritty/dank-theme.toml",
                     "alacritty/dank-theme.toml")
        self.before = self.sb.tree_hash()

    def tearDown(self):
        self.sb.cleanup()

    def apply(self, *extra):
        code, out, err = self.sb.run("apply", "--only", "alacritty", *extra, assume="alacritty")
        self.assertEqual(code, 0, err)
        return out, err

    def ours(self):
        with open(self.sb.cfg("alacritty", "appglass.toml"), "rb") as f:
            return tomllib.load(f)

    def main_text(self):
        return self.sb.read(self.sb.cfg("alacritty", "alacritty.toml"))

    # content
    def test_content_and_keys(self):
        self.apply()
        d = self.ours()
        self.assertEqual(d["window"]["opacity"], 0.6)
        self.assertIs(d["colors"]["transparent_background_colors"], False)
        env = core.Env(self.sb.env)
        pal = core.Palette(env)
        self.assertEqual(d["colors"]["normal"]["black"],
                         core.readable(pal.get("outline"), "#101418", 0.6))
        self.assertEqual(d["colors"]["normal"]["magenta"],
                         core.readable(pal.get("tertiary"), "#101418", 0.6))
        self.assertEqual(d["colors"]["bright"]["black"],
                         core.readable(pal.get("on_surface_variant"), "#101418", 0.6))
        # the theme's too-dark red (color1) is lifted, its hue kept
        self.assertNotEqual(d["colors"]["normal"]["red"], "#cf80fb")
        self.assertEqual(set(d["colors"]["dim"]), set(NAMES))
        self.assertIn("dim_foreground", d["colors"]["primary"])
        # nothing the theme sets as text colour is left alone for selection/cursor
        self.assertNotIn("selection", d["colors"])

    def test_opacity_follows_dms_setting(self):
        self.sb.set_level(0.75)
        self.apply()
        self.assertEqual(self.ours()["window"]["opacity"], 0.75)

    def test_main_file_edit(self):
        self.apply()
        text = self.main_text()
        d = tomllib.loads(text)
        imp = d["general"]["import"]
        self.assertEqual(imp, ["~/.config/alacritty/dank-theme.toml",
                               "~/.config/alacritty/appglass.toml"])
        self.assertNotIn("opacity", d["window"])
        self.assertIn("# appglass-off: opacity = 1.0", text)
        self.assertEqual(d["window"]["decorations"], "None")

    def test_idempotent(self):
        self.apply()
        h = self.sb.tree_hash()
        out, _ = self.apply()
        self.assertIn("alacritty: up to date", out)
        self.assertEqual(self.sb.tree_hash(), h)

    def test_remove_byte_identical(self):
        self.apply()
        self.apply()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)
        self.assertFalse(os.path.exists(self.sb.path("home", ".local", "state", "appglass")))

    def test_foreign_appglass_toml_protected(self):
        p = self.sb.write("alacritty/appglass.toml", "# my own file\n")
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertEqual(code, 0)
        self.assertIn("alacritty: skipped", err)
        self.assertEqual(self.sb.read(p), "# my own file\n")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_opacity_in_unsupported_form_is_conflict(self):
        p = self.sb.write("alacritty/alacritty.toml",
                          'window = { opacity = 1.0 }\n[general]\nimport = []\n')
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertIn("alacritty: skipped", err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_main_without_import_and_missing_main(self):
        p = self.sb.write("alacritty/alacritty.toml", "[window]\nopacity = 0.9\n")
        self.apply()
        d = tomllib.loads(self.main_text())
        self.assertEqual(d["general"]["import"], ["~/.config/alacritty/appglass.toml"])
        self.assertNotIn("opacity", d["window"])
        self.sb.run("remove")
        self.assertEqual(self.sb.read(p), "[window]\nopacity = 0.9\n")
        os.remove(p)
        before = self.sb.tree_hash()
        self.apply()
        d = tomllib.loads(self.main_text())
        self.assertEqual(d["general"]["import"][-1], "~/.config/alacritty/appglass.toml")
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_edit_cases(self):
        env = core.Env(self.sb.env)
        ours = env.config_path("alacritty", "appglass.toml")
        ent = "~/.config/alacritty/appglass.toml"
        cases = [
            ('general.import = ["a.toml"]\n', ["a.toml", ent]),
            ('[general]\nimport = [\n  "~/.config/alacritty/dank-theme.toml", # theme\n'
             '  "x.toml",\n]\n', ["~/.config/alacritty/dank-theme.toml", ent, "x.toml"]),
            ("[general]\nlive_config_reload = true\n", [ent]),
            ('[window]\nopacity = 1\n[general]\nimport = []\n', [ent]),
        ]
        for src, want in cases:
            out = fam.edit_main(src, env, ours)
            d = tomllib.loads(out)
            self.assertEqual(d["general"]["import"], want, src)
            self.assertNotIn("opacity", d.get("window", {}))
            self.assertEqual(fam.edit_main(out, env, ours), out)
            self.assertEqual(fam.undo(env, None, out), src, src)

    def test_user_change_after_apply_kept(self):
        self.apply()
        p = self.sb.cfg("alacritty", "alacritty.toml")
        with open(p, "a") as f:
            f.write("\n[font]\nsize = 13.0\n")
        self.sb.run("remove")
        with open(fixture("alacritty", "alacritty.toml")) as f:
            self.assertEqual(self.sb.read(p), f.read() + "\n[font]\nsize = 13.0\n")

    def test_user_opacity_after_apply_kept_and_valid_toml(self):
        # the user sets their own [window] opacity after apply: the hook keeps
        # it, and remove leaves valid TOML with the user's line in force
        p = self.sb.cfg("alacritty", "alacritty.toml")
        for hook in (True, False):
            self.apply()
            t = self.main_text().replace("[window]\n", "[window]\nopacity = 0.9\n", 1)
            with open(p, "w") as f:
                f.write(t)
            if hook:
                code, _, err = self.sb.run("apply", "--from-hook", "--quiet",
                                           assume="alacritty")
                self.assertEqual(code, 0, err)
                self.assertEqual(self.main_text(), t)          # kept as the user left it
            code, _, err = self.sb.run("remove")
            self.assertEqual(code, 0, err)
            d = tomllib.loads(self.main_text())                # valid TOML
            self.assertEqual(d["window"]["opacity"], 0.9)
            self.assertIn("opacity = 0.9\n", self.main_text())
            self.assertNotIn("appglass", self.main_text())
            self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")

    def test_undo_keeps_toml_valid(self):
        env = core.Env(self.sb.env)
        ours = env.config_path("alacritty", "appglass.toml")
        with open(fixture("alacritty", "alacritty.toml")) as f:
            src = f.read()
        out = fam.edit_main(src, env, ours).replace("[window]\n", "[window]\nopacity = 0.5\n", 1)
        back = fam.undo(env, None, out)
        self.assertEqual(tomllib.loads(back)["window"]["opacity"], 0.5)
        self.assertIn("# opacity = 1.0", back)

    def test_not_installed(self):
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume_not="alacritty")
        self.assertIn("not installed", out)
        self.assertEqual(self.sb.tree_hash(), self.before)

    # readability
    def _check_readable(self, bg):
        cols = merged(self.sb)
        texts = [cols["primary"]["foreground"]]
        texts += [cols[s][n] for s in ("normal", "bright", "dim") for n in NAMES]
        texts.append(cols["primary"]["dim_foreground"])
        for t in texts:
            self.assertGreaterEqual(core.worst_contrast(t, bg, 0.6), 2.0, t)

    def test_dark_readability(self):
        self.apply()
        self._check_readable("#101418")

    def test_light_mode_readability(self):
        self.sb.cleanup()
        self.sb = Sandbox()
        self.seed(light=True)
        self.apply()
        d = self.ours()
        self.assertEqual(d["colors"]["normal"]["black"],
                         core.readable("#6c7279", "#f7f9ff", 0.6))
        self._check_readable("#f7f9ff")
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), self.before)

    # hook freshness
    def test_hook_colours_win_over_stale_theme(self):
        env = core.Env(self.sb.env)
        os.makedirs(env.state_dir)
        t16 = ["#121318", "#ff7298", "#7fff93", "#fff872", "#99b0f2", "#2f4578", "#b1c5ff",
               "#eff4ff", "#3f4248", "#ff9fb9", "#a5ffb3", "#fffba5", "#bccdff", "#c8d6ff",
               "#dbe4ff", "#f8faff"]
        with open(fixture("dms", "dms-colors.json")) as f:
            cols = json.load(f)["colors"]["dark"]
        cols = dict(cols, background="#121318")
        colors = os.path.join(env.state_dir, "colors.json")
        theme = self.sb.cfg("alacritty", "dank-theme.toml")
        now = time.time()
        os.utime(theme, (now - 10, now - 10))
        with open(colors, "w") as f:
            json.dump({"mode": "dark", "colors": cols,
                       "dank16term": {"color%d" % i: c for i, c in enumerate(t16)}}, f)
        self.apply()
        d = self.ours()
        self.assertEqual(d["colors"]["normal"]["red"], core.readable("#ff7298", "#121318", 0.6))
        # DMS then rewrites dank-theme.toml with the same colours: no change
        lines = ["[colors.primary]", "background = '#121318'",
                 "foreground = '%s'" % cols["on_surface"], "[colors.normal]"]
        lines += ["%s = '%s'" % (n, c) for n, c in zip(NAMES, t16[:8])]
        lines += ["[colors.bright]"] + ["%s = '%s'" % (n, c) for n, c in zip(NAMES, t16[8:])]
        with open(theme, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.utime(theme, (now + 10, now + 10))
        out, _ = self.apply()
        self.assertIn("alacritty: up to date", out)

    @unittest.skipUnless(shutil.which("niri"), "niri not installed")
    def test_niri_rule(self):
        self.apply()
        kdl = self.sb.read(self.sb.cfg("niri", "appglass.kdl"))
        self.assertIn('match app-id=r#"^Alacritty$"#', kdl)
        r = subprocess.run(["niri", "validate", "-c", self.sb.cfg("niri", "config.kdl")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipUnless(shutil.which("alacritty"), "alacritty not installed")
    def test_alacritty_accepts_config(self):
        self.apply()
        # alacritty migrate --dry-run parses the config and its imports
        r = subprocess.run(["alacritty", "migrate", "--dry-run", "-c",
                            self.sb.cfg("alacritty", "alacritty.toml")],
                           capture_output=True, text=True, env=self.sb.env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
