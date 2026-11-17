"""niri: appglass.kdl rendering, the include line, validation."""

import os
import shutil
import unittest

from fixtures.sandbox import Sandbox, fixture
from appglass import core, niri

HAVE_NIRI = shutil.which("niri") is not None


class Text(unittest.TestCase):
    def test_render(self):
        t = niri.render([r"^Alacritty$", r"^org\.gnome\.Nautilus$"])
        self.assertEqual(t.count("window-rule {"), 1)
        self.assertIn('    match app-id=r#"^Alacritty$"#\n', t)
        self.assertIn('    match app-id=r#"^org\\.gnome\\.Nautilus$"#\n', t)
        self.assertIn("    opacity 1.0\n}", t)

    def test_include_after_dms_rules(self):
        with open(fixture("niri", "config.kdl")) as f:
            src = f.read()
        out = niri.add_include(src)
        lines = out.splitlines()
        i = next(n for n, l in enumerate(lines) if '"dms/windowrules.kdl"' in l)
        self.assertEqual(lines[i + 1], niri.INCLUDE)
        self.assertEqual(niri.add_include(out), out)
        self.assertEqual(niri.strip_include(out), src)

    def test_include_appended_without_dms_rules(self):
        src = "layout {\n    gaps 8\n}"
        out = niri.add_include(src)
        self.assertTrue(out.endswith("}\n" + niri.INCLUDE + "\n"))
        self.assertEqual(niri.add_include("include \"dms/windowrules.kdl\""),
                         'include "dms/windowrules.kdl"\n' + niri.INCLUDE + "\n")


class Sync(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.before = self.sb.tree_hash()
        # these tests drive the rule through alacritty alone: the other
        # families (installed on the test machine or not) count as absent
        others = sorted(n for n in core.discover() if n != "alacritty")
        run = self.sb.run

        def run_alacritty_only(*argv, assume_not=None, **kw):
            names = others + ([assume_not] if assume_not else [])
            return run(*argv, assume_not=",".join(names), **kw)
        self.sb.run = run_alacritty_only

    def tearDown(self):
        self.sb.cleanup()

    @unittest.skipUnless(HAVE_NIRI, "niri not installed")
    def test_validates_and_global_rule_kept(self):
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertEqual(code, 0, err)
        cfg = self.sb.cfg("niri", "config.kdl")
        r = __import__("subprocess").run(["niri", "validate", "-c", cfg],
                                         capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        rules = self.sb.read(self.sb.cfg("niri", "dms", "windowrules.kdl"))
        self.assertIn("opacity 0.60", rules)
        self.assertIn("blur true", rules)

    def test_no_apps_no_rule(self):
        code, out, err = self.sb.run("apply", assume_not="alacritty")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_family_gone_rule_removed(self):
        self.sb.run("apply", assume="alacritty")
        self.assertTrue(os.path.exists(self.sb.cfg("niri", "appglass.kdl")))
        code, out, err = self.sb.run("apply", assume_not="alacritty")
        self.assertEqual(code, 0, err)
        self.assertIn("not installed, files removed", out)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_remove_only_keeps_other_owners(self):
        self.sb.run("apply", assume="alacritty")
        code, out, _ = self.sb.run("remove", "--only", "alacritty")
        self.assertEqual(code, 0)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_missing_config_kdl(self):
        os.remove(self.sb.cfg("niri", "config.kdl"))
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", assume="alacritty")
        self.assertEqual(code, 0)
        self.assertIn("not found", err)
        self.assertFalse(os.path.exists(self.sb.cfg("niri", "appglass.kdl")))
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_foreign_appglass_kdl(self):
        p = self.sb.write("niri/appglass.kdl", "// mine\n")
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertIn("niri: skipped", err)
        self.assertEqual(self.sb.read(p), "// mine\n")
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), before)

    @unittest.skipUnless(HAVE_NIRI, "niri not installed")
    def test_invalid_config_rolls_back(self):
        p = self.sb.cfg("niri", "config.kdl")
        with open(p, "a") as f:
            f.write("window-rule { bogus-node 1; }\n")
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertEqual(code, 1)
        self.assertIn("niri validate failed", err)
        self.assertFalse(os.path.exists(self.sb.cfg("niri", "appglass.kdl")))
        self.assertNotIn("appglass.kdl", self.sb.read(p))
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_an_event_leaves_the_rule_when_validate_fails(self):
        # the hook (an event) wrote the rule and niri validate fails: the
        # event takes nothing out (the user's own config may be what fails)
        fake = self.sb.path("fakebin")
        os.makedirs(fake)
        ok = self.sb.path("niri-ok")
        with open(os.path.join(fake, "niri"), "w") as f:
            f.write("#!/bin/sh\n[ -e %s ] && exit 0\necho broken >&2\nexit 1\n" % ok)
        os.chmod(os.path.join(fake, "niri"), 0o755)
        open(ok, "w").close()
        self.sb.env["PATH"] = fake + os.pathsep + self.sb.env["PATH"]
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertEqual(code, 0, out + err)
        rules = self.sb.cfg("niri", "appglass.kdl")
        with open(rules, "a") as f:
            f.write("// stale\n")
        os.remove(ok)
        cfg = self.sb.read(self.sb.cfg("niri", "config.kdl"))
        code, out, err = self.sb.run("apply", "--from-hook", assume="alacritty")
        self.assertNotEqual(code, 0, out + err)
        self.assertIn("niri validate failed", err)
        self.assertTrue(os.path.isfile(rules))
        self.assertEqual(self.sb.read(self.sb.cfg("niri", "config.kdl")), cfg)
        self.assertIn("niri", self.sb.json(os.path.join(self.sb.state, "appglass",
                                                        "state.json"))["owners"])
        # a command the user types still takes it out
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertEqual(code, 1, out + err)
        self.assertNotIn("appglass.kdl", self.sb.read(self.sb.cfg("niri", "config.kdl")))

    def test_user_edit_of_config_kdl_kept_on_remove(self):
        self.sb.run("apply", assume="alacritty")
        p = self.sb.cfg("niri", "config.kdl")
        with open(p, "a") as f:
            f.write("// user line\n")
        self.sb.run("remove")
        text = self.sb.read(p)
        self.assertIn("// user line", text)
        self.assertNotIn("appglass.kdl", text)
        with open(fixture("niri", "config.kdl")) as f:
            self.assertEqual(text, f.read() + "// user line\n")


    def _hook(self):
        code, out, err = self.sb.run("apply", "--from-hook", "--quiet", assume="alacritty")
        err = "".join(l for l in err.splitlines(True) if "warning: niri:" in l)
        return code, out, err

    def test_include_taken_out_stays_out(self):
        p = self.sb.cfg("niri", "config.kdl")
        with open(fixture("niri", "config.kdl")) as f:
            src = f.read()
        for edit in ("deleted", "commented"):
            with self.subTest(edit=edit):
                self.sb.run("apply", assume="alacritty")
                text = self.sb.read(p)
                self.assertIn(niri.INCLUDE, text)
                if edit == "deleted":
                    text = niri.strip_include(text)
                else:
                    text = text.replace(niri.INCLUDE, "// " + niri.INCLUDE)
                with open(p, "w") as f:
                    f.write(text)
                code, out, err = self._hook()
                self.assertEqual(code, 0, err)
                self.assertEqual(self.sb.read(p), text)
                self.assertIn("no longer includes appglass.kdl", err)
                code, out, err = self._hook()
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(self.sb.read(p), text)
                self.sb.run("apply", assume="alacritty")    # a manual apply too
                self.assertEqual(self.sb.read(p), text)
                self.sb.run("remove")
                self.assertEqual(self.sb.read(p), text)
                self.assertFalse(os.path.exists(self.sb.cfg("niri", "appglass.kdl")))
                with open(p, "w") as f:
                    f.write(src)
                # remove + apply puts it back
                self.sb.run("apply", assume="alacritty")
                self.assertIn(niri.INCLUDE, self.sb.read(p))
                self.sb.run("remove")
                self.assertEqual(self.sb.read(p), src)

    def test_deleted_files_warned_once_and_left_deleted(self):
        self.sb.run("apply", assume="alacritty")
        cfg, rules = self.sb.cfg("niri", "config.kdl"), self.sb.cfg("niri", "appglass.kdl")
        os.remove(rules)
        code, out, err = self._hook()
        self.assertEqual(code, 0, err)
        self.assertIn("appglass.kdl was deleted since apply", err)
        self.assertFalse(os.path.lexists(rules))
        self.assertEqual(self._hook()[2], "")
        os.remove(cfg)
        for i in range(2):
            code, out, err = self._hook()
            self.assertEqual(code, 0, err)
            self.assertFalse(os.path.lexists(cfg))
            self.assertFalse(os.path.lexists(rules))
            if i == 0:
                self.assertIn("config.kdl was deleted since apply", err)
            else:
                self.assertEqual(err, "")
        code, out, err = self.sb.run("apply", assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(cfg))
        self.assertFalse(os.path.lexists(rules))
        self.sb.run("remove")
        self.assertFalse(os.path.lexists(cfg))
        self.assertFalse(os.path.exists(self.sb.path("home", ".local", "state", "appglass")))

if __name__ == "__main__":
    unittest.main()
