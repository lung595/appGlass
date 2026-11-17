"""Obsidian family: the vault snippet, appearance.json, readability, restore."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from fixtures.sandbox import Sandbox
from appglass import core
from appglass.families import obsidian as fam

FLATPAK_CFG = os.path.join(".var", "app", "md.obsidian.Obsidian", "config", "obsidian",
                           "obsidian.json")
TEXT_VARS = ("text-normal", "text-muted", "text-faint", "text-accent", "text-error",
             "link-color", "icon-color", "code-comment",
             # syntax highlighting and callouts derive from the named colours
             "color-red", "color-orange", "color-yellow", "color-green",
             "color-cyan", "color-blue", "color-purple", "color-pink",
             # hard-coded in Obsidian (#9e9e9e), not derived from the named colours
             "callout-quote")
# on the opaque menu colour: notices, tooltips (Obsidian's own are #fafafa,
# made for a dark surface in both themes), an error tooltip
MENU_TEXT_VARS = ("notice-color", "tooltip-color", "ag-menu-error", "text-normal", "text-muted")

# what Obsidian itself writes: 2-space indent, no final newline
APPEARANCE = json.dumps({"theme": "obsidian", "accentColor": "",
                         "enabledCssSnippets": ["mine"]}, indent=2)


def css_vars(css):
    """The focused-window vars (the inactive section 5 left out)."""
    css = css.split("/* 5. inactive window")[0]
    return dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", css))


def inactive_vars(css):
    if "/* 5. inactive window" not in css:
        return None
    return dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", css.split("/* 5. inactive window")[1]))


class Obsidian(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.seed()

    def seed(self, light=False, flatpak=True):
        self.sb.seed_dms(light=light)
        self.sb.seed_niri()
        self.vault = os.path.join(self.sb.home, "Notes")
        self.sb.write("note.md", "# note\n", base=self.vault)
        self.sb.write(os.path.join(".obsidian", "appearance.json"), APPEARANCE, base=self.vault)
        self.sb.write(os.path.join(".obsidian", "app.json"), "{}", base=self.vault)
        self.config = self.obsidian_json([self.vault], flatpak=flatpak)
        self.before = self.sb.tree_hash()

    def obsidian_json(self, paths, flatpak=True):
        data = {"vaults": {"%016x" % (i + 1): {"path": p, "ts": 1, "open": i == 0}
                           for i, p in enumerate(paths)}}
        if flatpak:
            return self.sb.write(FLATPAK_CFG, json.dumps(data), base=self.sb.home)
        return self.sb.write(os.path.join("obsidian", "obsidian.json"), json.dumps(data))

    def tearDown(self):
        self.sb.cleanup()

    def apply(self, *extra):
        code, out, err = self.sb.run("apply", "--only", "obsidian", *extra, assume="obsidian")
        self.assertEqual(code, 0, err)
        return out, err

    def snippet_path(self, vault=None):
        return os.path.join(vault or self.vault, ".obsidian", "snippets", "appglass.css")

    def appearance_path(self, vault=None):
        return os.path.join(vault or self.vault, ".obsidian", "appearance.json")

    def css(self, vault=None):
        return self.sb.read(self.snippet_path(vault))

    # content
    def test_content_and_keys(self):
        self.apply()
        css = self.css()
        v = css_vars(css)
        self.assertEqual(v["ag-content"], "rgba(16, 20, 24, 0.60)")      # surface @ content
        self.assertEqual(v["ag-bar"], "rgba(30, 34, 38, 0.65)")          # surface_container @ bar
        self.assertEqual(v["ag-menu"], "#282c30")                        # opaque
        self.assertEqual(v["background-primary"], "var(--ag-content)")
        self.assertEqual(v["background-secondary"], "var(--ag-bar)")
        self.assertEqual(v["icon-opacity"], "1")
        self.assertEqual(v["text-normal"], "#e0e2e8")
        # the stock faint text is lifted from outline until it reads on every glass
        self.assertNotEqual(v["text-faint"], "#8c9198")
        for bg, a in self.glasses("#101418", "#1e2226", "#e0e2e8"):
            self.assertGreaterEqual(core.worst_contrast(v["text-faint"], bg, a), fam.TARGET)
        self.assertEqual(v["background-primary-alt"], "rgba(224, 226, 232, 0.04)")
        self.assertEqual(v["tab-background-active"], "rgba(224, 226, 232, 0.06)")
        # disabled icons are dimmed by colour, never by opacity
        self.assertRegex(css, r"\.clickable-icon\[aria-disabled=true\][^{]*\{\s*"
                              r"opacity: 1 !important;\s*color: var\(--text-faint\) !important;")
        self.assertRegex(css, r"\.clickable-icon\.is-disabled[^{]*\{\s*opacity: 1 !important;")
        # code comments sit on the code-block tint: set, and readable there
        code_glass = self.glasses("#101418", "#1e2226", "#e0e2e8")[2]
        self.assertGreaterEqual(core.worst_contrast(v["code-comment"], *code_glass), fam.TARGET)
        # the status bar sits on the content: painted so the sum is the bar level
        bar_over = core.Levels(0.6).bar_over_content
        self.assertIn(".status-bar { background-color: %s"
                      % "var(--ag-bar-over-content)", css)
        self.assertEqual(v["ag-bar-over-content"], core.rgba("#1e2226", bar_over))
        for sel in (".menu", ".modal", ".prompt", ".notice", ".tooltip", ".suggestion-container"):
            self.assertIn(sel, css)
        # no alpha on text roles
        for k in TEXT_VARS:
            self.assertRegex(v[k], r"^#[0-9a-f]{6}$", k)

    def test_accent_palette(self):
        # Obsidian's own accent colours (--code-operator: red, --code-value:
        # purple, callouts, ...) are under 2:1 on glass: set from DMS, lifted
        self.apply()
        v = css_vars(self.css())
        for k in fam.ACCENTS:
            c = v["color-" + k]
            self.assertRegex(c, r"^#[0-9a-f]{6}$", k)
            self.assertEqual(v["color-%s-rgb" % k], "%d, %d, %d" % core.hex_to_rgb(c))
            self.assertNotEqual(c, fam.OBSIDIAN_ACCENTS["dark"][k])
        # red is DMS's terminal red (dank16 color1) moved toward white until readable
        c = "#ff729d"
        glass = self.glasses("#101418", "#1e2226", "#e0e2e8")
        for _ in range(4):
            for bg, a in glass:
                c = core.readable(c, bg, a, fam.TARGET)
        self.assertEqual(v["color-red"], c)
        # Obsidian's stock colours really fail on this glass (the bug)
        glass = self.glasses("#101418", "#1e2226", "#e0e2e8")
        self.assertLess(min(core.worst_contrast(fam.OBSIDIAN_ACCENTS["dark"]["red"], bg, a)
                            for bg, a in glass), 2.0)
        # both selectors carry them (one rule for dark and light)
        block = self.css().split("body.theme-dark, body.theme-light {", 1)[1].split("}", 1)[0]
        self.assertIn("--color-purple:", block)

    def test_accent_palette_without_dank16(self):
        p = os.path.join(self.sb.cache, "dms", "dms-colors.json")
        d = self.sb.json(p)
        del d["dank16"]
        with open(p, "w") as f:
            json.dump(d, f)
        self.apply()
        v = css_vars(self.css())
        for k in fam.ACCENTS:
            for bg, a in self.glasses("#101418", "#1e2226", "#e0e2e8"):
                self.assertGreaterEqual(core.worst_contrast(v["color-" + k], bg, a), fam.TARGET)

    def test_both_theme_selectors(self):
        self.apply()
        css = self.css()
        self.assertIn("body.theme-dark, body.theme-light {", css)
        self.assertIn("color-scheme: dark;", css)

    def test_appearance_merged(self):
        self.apply()
        text = self.sb.read(self.appearance_path())
        d = json.loads(text)
        self.assertEqual(d["enabledCssSnippets"], ["mine", "appglass"])
        self.assertEqual(d["theme"], "obsidian")
        self.assertEqual(d["accentColor"], "")
        self.assertEqual(text, json.dumps(d, indent=2))   # Obsidian's own format
        self.assertEqual(self.sb.read(os.path.join(self.vault, ".obsidian", "app.json")), "{}")

    def test_appearance_created_when_missing(self):
        os.remove(self.appearance_path())
        before = self.sb.tree_hash()
        self.apply()
        self.assertEqual(self.sb.json(self.appearance_path()), {"enabledCssSnippets": ["appglass"]})
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_vault_without_dot_obsidian(self):
        shutil.rmtree(os.path.join(self.vault, ".obsidian"))
        before = self.sb.tree_hash()
        self.apply()
        self.assertTrue(os.path.isfile(self.snippet_path()))
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_already_enabled_untouched(self):
        p = self.appearance_path()
        text = json.dumps({"enabledCssSnippets": ["appglass", "mine"]})
        self.sb.write(p, text, base="/")
        self.apply()
        self.assertEqual(self.sb.read(p), text)

    def test_idempotent(self):
        self.apply()
        h = self.sb.tree_hash()
        out, _ = self.apply()
        self.assertIn("obsidian: up to date", out)
        self.assertEqual(self.sb.tree_hash(), h)

    def test_remove_byte_identical(self):
        self.apply()
        self.apply()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)
        self.assertFalse(os.path.exists(self.sb.path("home", ".local", "state", "appglass")))

    def test_foreign_snippet_protected(self):
        p = self.sb.write(os.path.join(".obsidian", "snippets", "appglass.css"),
                          "/* mine */\n", base=self.vault)
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "obsidian", assume="obsidian")
        self.assertEqual(code, 0)
        self.assertIn("obsidian: skipped", err)
        self.assertEqual(self.sb.read(p), "/* mine */\n")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_bad_appearance_is_conflict(self):
        for text in ("{not json", "[1, 2]", '{"enabledCssSnippets": "appglass"}'):
            self.sb.write(self.appearance_path(), text, base="/")
            before = self.sb.tree_hash()
            code, out, err = self.sb.run("apply", "--only", "obsidian", assume="obsidian")
            self.assertEqual(code, 0)
            self.assertIn("obsidian: skipped", err, text)
            self.assertEqual(self.sb.tree_hash(), before, text)

    def test_user_change_after_apply_kept(self):
        self.apply()
        p = self.appearance_path()
        # Obsidian rewrites the file when a setting changes in the app
        d = self.sb.json(p)
        d["theme"] = "moonstone"
        d["enabledCssSnippets"].append("later")
        self.sb.write(p, json.dumps(d, indent=2), base="/")
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        d = self.sb.json(p)
        self.assertEqual(d["theme"], "moonstone")
        self.assertEqual(d["enabledCssSnippets"], ["mine", "later"])
        self.assertFalse(os.path.exists(self.snippet_path()))

    def test_user_change_then_reapply_kept(self):
        """A user change, then a re-apply (the hook does one on every theme or
        wallpaper change), then remove: the change must survive. The core
        marks the file as changed at the re-apply, so remove strips only the
        appglass parts instead of writing the old backup back."""
        self.apply()
        p = self.appearance_path()
        d = self.sb.json(p)
        d["enabledCssSnippets"].append("later")
        d["baseFontSize"] = 18
        self.sb.write(p, json.dumps(d, indent=2), base="/")
        self.apply("--quiet")
        self.assertIn("appglass", self.sb.json(p)["enabledCssSnippets"])
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        d = self.sb.json(p)
        self.assertEqual(d["enabledCssSnippets"], ["mine", "later"])
        self.assertEqual(d.get("baseFontSize"), 18)

    def test_created_then_user_change_remove_drops_only_ours(self):
        os.remove(self.appearance_path())
        before = self.sb.tree_hash()
        self.apply()
        p = self.appearance_path()
        d = {"enabledCssSnippets": ["mine", "appglass", "foo"], "baseFontSize": 18}
        self.sb.write(p, json.dumps(d, indent=2), base="/")
        self.apply("--quiet")
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.json(p), {"enabledCssSnippets": ["mine", "foo"],
                                           "baseFontSize": 18})
        # the user's change only reordered/kept ours: nothing of theirs -> deleted
        self.apply()
        d = self.sb.json(p)
        self.sb.write(p, json.dumps(d), base="/")     # reformatted by Obsidian
        self.sb.run("remove")
        self.assertEqual(self.sb.json(p), {"enabledCssSnippets": ["mine", "foo"],
                                           "baseFontSize": 18})
        os.remove(p)
        self.apply()
        self.sb.write(p, json.dumps({"enabledCssSnippets": ["appglass"]}, indent=2) + "\n",
                      base="/")
        self.apply("--quiet")
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), before)

    def test_user_turned_snippet_off_stays_off(self):
        """Settings > Appearance > CSS snippets > appglass off writes the list
        without "appglass": the hook re-apply must not turn it back on."""
        self.apply()
        p = self.appearance_path()
        d = self.sb.json(p)
        d["enabledCssSnippets"] = ["mine"]
        off = json.dumps(d, indent=2)
        self.sb.write(p, off, base="/")
        code, out, err = self.sb.run("apply", "--from-hook", "--quiet")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(p), off)
        self.assertIn("turned off", err)
        code, out, err = self.sb.run("apply", "--from-hook", "--quiet")
        self.assertEqual(self.sb.read(p), off)
        self.assertNotIn("turned off", err)           # said once
        _, err = self.apply()
        self.assertEqual(self.sb.read(p), off)
        self.assertTrue(os.path.isfile(self.snippet_path()))   # still kept up to date
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.read(p), off)
        self.assertFalse(os.path.exists(self.snippet_path()))
        # remove + apply turns it on again
        self.apply()
        self.assertIn("appglass", self.sb.json(p)["enabledCssSnippets"])

    def test_enable_snippet_changed(self):
        self.assertEqual(fam.enable_snippet('{"enabledCssSnippets": []}', changed=True),
                         '{"enabledCssSnippets": []}')
        self.assertIn("appglass", fam.enable_snippet('{"enabledCssSnippets": []}'))

    def second_vault(self, name="Work"):
        v = os.path.join(self.sb.home, name)
        self.sb.write(os.path.join(".obsidian", "appearance.json"), APPEARANCE, base=v)
        return v

    def test_conflict_in_one_vault_skips_only_that_vault(self):
        cases = [("snippets/appglass.css", "/* mine */\n"), ("appearance.json", "{not json")]
        for rel, text in cases:
            other = self.second_vault()
            self.sb.write(os.path.join(".obsidian", rel), text, base=other)
            self.obsidian_json([other, self.vault])
            before = self.sb.tree_hash()
            out, err = self.apply()
            self.assertIn("vault %s skipped" % other, err, rel)
            self.assertNotIn("obsidian: skipped", err, rel)
            self.assertTrue(os.path.isfile(self.snippet_path()), rel)
            self.assertIn("appglass", self.sb.json(self.appearance_path())["enabledCssSnippets"])
            self.assertEqual(self.sb.read(os.path.join(other, ".obsidian", rel)), text)
            if rel == "appearance.json":
                self.assertFalse(os.path.exists(self.snippet_path(other)))
            else:
                self.assertEqual(self.sb.read(self.appearance_path(other)), APPEARANCE)
            self.apply()                                     # still idempotent
            code, out, err = self.sb.run("remove")
            self.assertEqual(code, 0, err)
            self.assertEqual(self.sb.tree_hash(), before, rel)
            shutil.rmtree(other)

    def test_conflict_in_a_configured_vault_keeps_everything(self):
        other = self.second_vault()
        self.obsidian_json([self.vault, other])
        self.apply()
        # Obsidian half way through writing the file
        self.sb.write(self.appearance_path(other), "{\n  \"theme\"", base="/")
        h = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "obsidian", assume="obsidian")
        self.assertEqual(code, 0)
        self.assertIn("obsidian: skipped", err)
        self.assertEqual(self.sb.tree_hash(), h)

    def test_unreadable_obsidian_json_keeps_everything(self):
        self.apply()
        self.sb.write(self.config, '{"vaults": {', base="/")
        h = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "obsidian", assume="obsidian")
        self.assertEqual(code, 0)
        self.assertIn("obsidian: skipped", err)
        self.assertEqual(self.sb.tree_hash(), h)

    @unittest.skipUnless(shutil.which("niri"), "niri not installed")
    def test_all_vaults_gone_reverts(self):
        self.apply()
        self.obsidian_json([])
        out, err = self.apply()
        self.assertIn("reverted", err)
        self.assertFalse(os.path.exists(self.snippet_path()))
        self.assertEqual(self.sb.read(self.appearance_path()), APPEARANCE)
        kdl = self.sb.read(self.sb.cfg("niri", "appglass.kdl")) \
            if os.path.exists(self.sb.cfg("niri", "appglass.kdl")) else ""
        self.assertNotIn("obsidian", kdl.lower())
        r = subprocess.run(["niri", "validate", "-c", self.sb.cfg("niri", "config.kdl")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        h = self.sb.tree_hash()
        self.apply()                                         # idempotent while empty
        self.assertEqual(self.sb.tree_hash(), h)
        self.obsidian_json([self.vault])                     # and back
        self.apply()
        self.assertTrue(os.path.isfile(self.snippet_path()))
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_edit_helpers(self):
        for src in ("", "{}", APPEARANCE, APPEARANCE + "\n",
                    '{"enabledCssSnippets": []}', '{"theme": "x"}'):
            out = fam.enable_snippet(src)
            self.assertIn("appglass", json.loads(out)["enabledCssSnippets"])
            self.assertEqual(fam.enable_snippet(out), out)
            self.assertEqual(out.endswith("\n"), src.endswith("\n"))
            back = json.loads(fam.undo(None, None, out))
            self.assertNotIn("appglass", back.get("enabledCssSnippets", []))

    def test_no_vaults_skipped(self):
        os.remove(self.config)
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("apply", "--only", "obsidian", assume="obsidian")
        self.assertEqual(code, 0)
        self.assertIn("obsidian: skipped", err)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_missing_vault_warned(self):
        gone = os.path.join(self.sb.home, "Gone")
        self.obsidian_json([gone, self.vault])
        out, err = self.apply()
        self.assertIn("Gone", out + err)
        self.assertFalse(os.path.exists(gone))
        self.assertTrue(os.path.isfile(self.snippet_path()))

    def test_not_installed(self):
        code, out, err = self.sb.run("apply", "--only", "obsidian", assume_not="obsidian")
        self.assertIn("not installed", out)
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_native_and_flatpak_deduped(self):
        second = os.path.join(self.sb.home, "Work")
        os.makedirs(second)
        self.obsidian_json([self.vault, second], flatpak=False)
        env = core.Env(self.sb.env)
        self.assertEqual(fam.vaults(env), [self.vault, second])
        self.apply()
        self.assertTrue(os.path.isfile(self.snippet_path(second)))
        self.assertEqual(self.sb.json(self.appearance_path(second)),
                         {"enabledCssSnippets": ["appglass"]})
        self.sb.run("remove")
        self.assertFalse(os.path.exists(os.path.join(second, ".obsidian")))

    def test_vault_removed_from_list_is_reverted(self):
        self.apply()
        other = os.path.join(self.sb.home, "Work")
        os.makedirs(other)
        self.obsidian_json([other])
        self.apply()
        self.assertTrue(os.path.isfile(self.snippet_path(other)))
        self.assertFalse(os.path.exists(self.snippet_path()))
        self.assertEqual(self.sb.read(self.appearance_path()), APPEARANCE)

    def sync(self):
        code, out, err = self.sb.run("get")
        self.assertEqual(code, 0, err)
        p = os.path.join(self.tmp_settings, "plugin-settings.json")
        with open(p, "w") as f:
            f.write(out)
        code, out, err = self.sb.run("sync", "--settings-file", p, assume="obsidian")
        self.assertEqual(code, 0, out + err)
        return out + err

    def test_a_vault_gone_for_a_while_keeps_its_records(self):
        # two vaults, B on a drive that is not mounted at the plugin's next
        # sync: the sync (an event) keeps B's records and touches nothing;
        # with B back, remove gives both vaults back byte-identical
        self.tmp_settings = tempfile.mkdtemp(prefix="appglass-obs-")
        self.addCleanup(shutil.rmtree, self.tmp_settings, True)
        b = os.path.join(self.sb.home, "Drive", "VaultB")
        self.sb.write("b.md", "# b\n", base=b)
        self.sb.write(os.path.join(".obsidian", "appearance.json"), APPEARANCE, base=b)
        self.obsidian_json([self.vault, b])
        before = self.sb.tree_hash()
        self.sync()
        self.assertTrue(os.path.isfile(self.snippet_path(b)))
        self.assertIn('"appglass"', self.sb.read(self.appearance_path(b)))
        recs = sorted(json.loads(self.sb.read(os.path.join(
            self.sb.state, "appglass", "state.json")))["owners"]["obsidian"]["files"])
        away = b + ".unmounted"
        os.rename(b, away)                      # the drive goes
        out = self.sync()
        self.assertNotIn("left deleted", out)
        st = json.loads(self.sb.read(os.path.join(self.sb.state, "appglass", "state.json")))
        self.assertEqual(sorted(st["owners"]["obsidian"]["files"]), recs)
        # doctor does not take the kept records for drift to re-render
        code, out, err = self.sb.run("doctor")
        self.assertNotIn("VaultB", out + err)
        os.rename(away, b)                      # and comes back
        self.sync()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.read(self.appearance_path(b)), APPEARANCE)
        self.assertFalse(os.path.exists(self.snippet_path(b)))
        self.assertEqual(self.sb.tree_hash(), before)

    def two_vaults_synced(self):
        self.tmp_settings = tempfile.mkdtemp(prefix="appglass-obs-")
        self.addCleanup(shutil.rmtree, self.tmp_settings, True)
        b = os.path.join(self.sb.home, "Drive", "VaultB")
        self.sb.write("b.md", "# b\n", base=b)
        self.sb.write(os.path.join(".obsidian", "appearance.json"), APPEARANCE, base=b)
        self.obsidian_json([self.vault, b])
        before = self.sb.tree_hash()
        self.sync()
        return b, before

    def records(self):
        st = json.loads(self.sb.read(os.path.join(self.sb.state, "appglass", "state.json")))
        return sorted(st["owners"]["obsidian"]["files"])

    def back_and_removed(self, b, away, before):
        os.rename(away, b)
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.read(self.appearance_path(b)), APPEARANCE)
        self.assertFalse(os.path.exists(self.snippet_path(b)))
        self.assertEqual(self.sb.tree_hash(), before)

    def test_a_typed_apply_keeps_the_records_of_a_vault_not_mounted(self):
        # a user action is no reason to forget a vault whose drive is away:
        # its folder is gone, not its files
        b, before = self.two_vaults_synced()
        recs = self.records()
        away = b + ".unmounted"
        os.rename(b, away)
        code, out, err = self.sb.run("apply", "--all", assume="obsidian")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("left deleted", err)
        self.assertIn("VaultB", err)
        self.assertEqual(self.records(), recs)
        self.assertFalse(os.path.exists(b))
        self.back_and_removed(b, away, before)

    def test_glass_off_keeps_the_records_of_a_vault_not_mounted(self):
        b, before = self.two_vaults_synced()
        recs = self.records()
        away = b + ".unmounted"
        os.rename(b, away)
        code, out, err = self.sb.run("get")
        p = os.path.join(self.tmp_settings, "off.json")
        with open(p, "w") as f:
            json.dump(dict(json.loads(out), enabled=False), f)
        code, out, err = self.sb.run("sync", "--settings-file", p, assume="obsidian")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("left deleted", err)
        self.assertEqual([r for r in self.records() if r.startswith(b)],
                         [r for r in recs if r.startswith(b)])
        self.assertFalse(os.path.exists(b))
        self.back_and_removed(b, away, before)

    def test_an_event_keeps_every_byte_and_record_of_a_vault_no_longer_listed(self):
        # B is taken out of obsidian.json, its files all still there: the
        # plugin's sync and the hook's apply (events) leave B's bytes and
        # records as they are; the typed apply gives B back
        b, before = self.two_vaults_synced()
        state = os.path.join(self.sb.state, "appglass", "state.json")
        recs = json.loads(self.sb.read(state))["owners"]["obsidian"]["files"]
        self.obsidian_json([self.vault])
        snap = self.sb.tree_hash(b)
        for run in (self.sync, lambda: self.sb.run("apply", "--from-hook", "--quiet")):
            run()
            self.assertEqual(self.sb.tree_hash(b), snap)
            now = json.loads(self.sb.read(state))["owners"]["obsidian"]["files"]
            self.assertEqual(sorted(now), sorted(recs))
            for p, rec in recs.items():
                self.assertEqual({k: v for k, v in now[p].items() if k != "unplanned"},
                                 {k: v for k, v in rec.items() if k != "unplanned"}, p)
        code, out, err = self.sb.run("apply", "--all", assume="obsidian")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.sb.read(self.appearance_path(b)), APPEARANCE)
        self.assertFalse(os.path.exists(self.snippet_path(b)))

    def test_a_vault_whose_snippets_dir_the_user_deleted_is_forgotten(self):
        # the vault is there: a snippets folder appglass made and the user
        # deleted is their opt-out, not a drive that went away
        self.apply()
        shutil.rmtree(os.path.dirname(self.snippet_path()))
        self.obsidian_json([])
        self.apply()
        self.assertNotIn(self.snippet_path(),
                         self.sb.json(os.path.join(self.sb.state, "appglass", "state.json"))
                         .get("owners", {}).get("obsidian", {}).get("files", {}))

    def test_rescue_takes_the_folders_appglass_made_out_again(self):
        self.apply()
        shutil.rmtree(os.path.join(self.sb.state, "appglass"))
        code, out, err = self.sb.run("adopt", "--rescue", assume="obsidian")
        self.assertEqual(code, 0, out + err)
        self.apply()
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, out + err)
        self.assertFalse(os.path.exists(os.path.dirname(self.snippet_path())))
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_vault_outside_sandbox_refused(self):
        outside = os.path.realpath(tempfile.mkdtemp(prefix="appglass-outside-"))
        try:
            self.obsidian_json([outside])
            code, out, err = self.sb.run("apply", "--only", "obsidian", assume="obsidian")
            self.assertEqual(code, 2, out + err)
            self.assertEqual(os.listdir(outside), [])
        finally:
            shutil.rmtree(outside)

    # readability
    @staticmethod
    def glasses(surface, bar, tint, content=0.6, bar_a=0.65):
        """content, bar, code block (tint over content), active tab (tint over bar)."""
        def over(t_a, bg, bg_a):
            a = t_a + bg_a * (1 - t_a)
            t, b = core.hex_to_rgb(tint), core.hex_to_rgb(bg)
            return core.rgb_to_hex(tuple((t[i] * t_a + b[i] * bg_a * (1 - t_a)) / a
                                         for i in range(3))), a
        return [(surface, content), (bar, bar_a), over(0.04, surface, content),
                over(0.06, bar, bar_a)]

    def _check_readable(self, surface, bar, tint, content=0.6, bar_a=0.65):
        v = css_vars(self.css())
        for k in TEXT_VARS:
            for bg, a in self.glasses(surface, bar, tint, content, bar_a):
                self.assertGreaterEqual(core.worst_contrast(v[k], bg, a), fam.TARGET, (k, bg, a))
        for k in MENU_TEXT_VARS:
            self.assertGreaterEqual(core.contrast(v[k], v["ag-menu"]), fam.TARGET, k)
        self.assertIn(".tooltip.mod-error { color: var(--ag-menu-error) !important; }", self.css())

    def test_dark_readability(self):
        self.apply()
        self._check_readable("#101418", "#1e2226", "#e0e2e8")

    def test_light_mode_readability(self):
        self.sb.cleanup()
        self.sb = Sandbox()
        self.seed(light=True)
        self.apply()
        css = self.css()
        v = css_vars(css)
        self.assertIn("color-scheme: light;", css)
        self.assertIn("body.theme-dark, body.theme-light {", css)
        self.assertEqual(v["mono-rgb-0"], "255, 255, 255")
        self.assertTrue(v["ag-content"].startswith("rgba(247, 249, 255, "), v["ag-content"])
        env = core.Env(self.sb.env)
        pal = core.Palette(env)
        self._check_readable(pal.get("surface"), pal.get("surface_container"),
                             pal.get("on_surface"))
        self.assertEqual(v["text-normal"],
                         core.readable(core.readable("#181c20", "#f7f9ff", 0.6),
                                       pal.get("surface_container"), 0.65))
        self.sb.run("remove")
        self.assertEqual(self.sb.tree_hash(), self.before)

    def test_levels_follow_dms_setting(self):
        self.sb.set_level(0.8)
        self.apply()
        v = css_vars(self.css())
        self.assertEqual(v["ag-content"], "rgba(16, 20, 24, 0.80)")
        self.assertEqual(v["ag-bar"], "rgba(30, 34, 38, 0.80)")
        self.assertEqual(v["ag-bar-over-content"], "rgba(30, 34, 38, 0.00)")
        self._check_readable("#101418", "#1e2226", "#e0e2e8", 0.8, 0.8)

    def test_inactive_window_fades(self):
        # default content 0.60 is the floor: no inactive section
        self.apply()
        self.assertIsNone(inactive_vars(self.css()))
        self.sb.set_level(0.8)
        self.apply()
        css = self.css()
        iv = inactive_vars(css)
        self.assertEqual(iv["ag-content"], "rgba(16, 20, 24, 0.72)")
        self.assertEqual(iv["ag-bar"], "rgba(30, 34, 38, 0.72)")
        self.assertIn("body.theme-dark:not(.is-focused)", css)
        self.assertIn("transition: background-color 180ms cubic-bezier(0.33, 1, 0.68, 1);", css)
        # text colours are not touched by the inactive section
        self.assertEqual(set(iv), {"ag-content", "ag-bar", "ag-bar-over-content"})
        self.sb.run("set", "inactive.enabled", "false")
        self.apply()
        self.assertIsNone(inactive_vars(self.css()))

    @unittest.skipUnless(shutil.which("niri"), "niri not installed")
    def test_niri_rule(self):
        self.apply()
        kdl = self.sb.read(self.sb.cfg("niri", "appglass.kdl"))
        self.assertIn('match app-id=r#"^md\\.obsidian\\.Obsidian$"#', kdl)
        self.assertIn('match app-id=r#"^obsidian$"#', kdl)
        r = subprocess.run(["niri", "validate", "-c", self.sb.cfg("niri", "config.kdl")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
