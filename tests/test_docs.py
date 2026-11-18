"""The user docs match the code: commands, IPC calls, plugin labels, links,
and the uninstall block really undoes an install."""

import codecs
import json
import os
import re
import subprocess
import unittest

from fixtures.sandbox import Sandbox, REPO
from appglass import core, settings

DOCS = os.path.join(REPO, "docs")
NEW = ("guide.md", "engine.md", "routes.md", "plugin.md", "issue-dms.md")
# tool names, rot13 so this file does not hold them
TRACES = codecs.decode("pynhqr|nagubcvp", "rot13")
TODO_OK = re.compile(r"TODO\((engine|fade|adapters)\)")


def read(*p):
    with open(os.path.join(REPO, *p)) as f:
        return f.read()


def doc(name):
    return read("docs", name)


def subcommands():
    return set(re.findall(r'sub\.add_parser\("([a-z-]+)"', read("appglass", "core.py")))


def ipc_functions():
    body = read("dms-plugin", "components", "DaemonBody.qml")
    block = body[body.index("IpcHandler {"):]
    return set(re.findall(r"^\s+function (\w+)\(", block, re.M))


def index_labels():
    js = read("dms-plugin", "components", "settings", "SettingsIndex.js")
    cats = js[js.index("var CATEGORIES"):js.index("var ENTRIES")]
    ents = js[js.index("var ENTRIES"):js.index("function appEntries")]
    return (re.findall(r'"name": "([^"]+)"', cats),
            re.findall(r'"label": "([^"]+)"', ents))


def code_lines(text):
    """The code of a doc: each line of a fenced block, each inline code span
    (with the rest of its line, for the TODO marker)."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            out.append(line)
            continue
        for span in re.findall(r"`([^`]+)`", line):
            m = TODO_OK.search(line)
            out.append(span + ("  " + m.group(0) if m else ""))
    return out


def dangling_links(docs):
    """(doc, target) for each relative link in docs/*.md whose file is missing."""
    out = []
    for name in sorted(os.listdir(docs)):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(docs, name)) as f:
            text = f.read()
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
            if "://" in target or target.startswith("mailto:"):
                continue
            if not os.path.exists(os.path.join(docs, target)):
                out.append((name, target))
    return out


def images(files):
    return [f for f in files if re.search(r"\.(png|jpe?g|gif|webp|mp4|webm)$", f, re.I)]


def section(text, heading):
    """The body of the markdown section whose heading starts with heading."""
    m = re.search(r"(?m)^(#+) %s.*$" % re.escape(heading), text)
    if not m:
        return ""
    rest = text[m.end():]
    end = re.search(r"(?m)^#{1,%d} " % len(m.group(1)), rest)
    return rest[:end.start()] if end else rest


def snapshot(root):
    out = {}
    for dp, dns, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            r = os.path.relpath(p, root)
            if os.path.islink(p):
                out[r] = "L " + os.readlink(p)
            else:
                with open(p, "rb") as f:
                    out[r] = f.read()
    return out


class Docs(unittest.TestCase):
    def test_new_docs_exist_and_the_readme_links_them(self):
        readme = doc("README.md")
        for name in NEW:
            self.assertTrue(os.path.exists(os.path.join(DOCS, name)), name)
            self.assertIn("(%s)" % name, readme, name)

    def test_relative_links_resolve(self):
        self.assertEqual(dangling_links(DOCS), [])

    def test_the_link_guard_finds_a_dangling_link(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.md"), "w") as f:
                f.write("[ok](b.md) [web](https://x.org/y.md) [gone](nope.md#x)\n")
            open(os.path.join(d, "b.md"), "w").close()
            self.assertEqual(dangling_links(d), [("a.md", "nope.md")])

    def test_no_tool_traces_and_no_private_paths(self):
        for name in NEW + ("README.md",):
            t = doc(name)
            self.assertIsNone(re.search(TRACES, t, re.I), name)
            self.assertNotIn("/home/", t, name)

    def test_todo_markers_name_their_stream(self):
        for name in NEW:
            for line in doc(name).splitlines():
                if "TODO" in line:
                    self.assertRegex(line, TODO_OK, "%s: %s" % (name, line))

    def test_every_appglass_command_exists_or_is_marked_todo(self):
        real = subcommands()
        self.assertIn("doctor", real)
        for name in NEW:
            for line in code_lines(doc(name)):
                if TODO_OK.search(line):
                    continue
                for cmd in re.findall(r"(?<![\w.-])appglass ([a-z][a-z-]*)", line):
                    self.assertIn(cmd, real, "%s: %s" % (name, line))

    def test_every_ipc_call_exists_and_every_function_is_documented(self):
        funcs = ipc_functions()
        self.assertEqual(funcs, {"sync", "status", "toggle", "pause", "resume", "app"})
        plugin = doc("plugin.md")
        for f in funcs:
            self.assertRegex(plugin, r"dms ipc call appGlass %s\b" % f, f)
        for name in NEW:
            for line in code_lines(doc(name)):
                if TODO_OK.search(line):
                    continue
                for f in re.findall(r"dms ipc call appGlass (\w+)", line):
                    self.assertIn(f, funcs, "%s: %s" % (name, line))

    def test_plugin_doc_names_every_rail_page_and_setting(self):
        cats, labels = index_labels()
        self.assertEqual(cats, ["Glass", "Apps", "Fade", "Fallback", "Advanced", "About"])
        plugin = doc("plugin.md")
        for c in cats:
            self.assertRegex(plugin, r"(?m)^#+ %s\b" % re.escape(c), c)
        for label in labels:
            self.assertIn(label, plugin, label)

    def test_settings_keys_in_the_docs_are_real(self):
        from appglass import settings
        for name in NEW:
            for line in code_lines(doc(name)):
                for key in re.findall(r"appglass (?:set|get) ([a-zA-Z.<>]+)", line):
                    if key.startswith("<"):
                        continue  # a placeholder: <key>
                    self.assertIn(key.split(".")[0], settings.DEFAULTS, "%s: %s" % (name, line))
                for key, val in re.findall(r"appglass set ([\w.-]+) (\S+)", line):
                    # the whole key, as `appglass set` takes it
                    settings.set_key(settings.DEFAULTS, key, settings.parse_value(val))

    def test_issue_draft_follows_the_spec_shape(self):
        t = doc("issue-dms.md")
        for h in ("Problem", "Demo", "How it works", "What we would ask from DMS",
                  "Limits", "Install / uninstall", "Screenshots"):
            self.assertRegex(t, r"(?m)^#+ %s" % re.escape(h), h)
        self.assertIn("max(content, %.2f)" % core.BAR_MIN, t)
        self.assertIn("appglass remove && appglass plugin remove", t)
        self.assertNotIn("/home/", t)
        self.assertNotIn("being checked", t)    # Steam was measured: opaque

    def test_the_bar_level_in_the_docs_is_the_code_s(self):
        for name in ("engine.md", "routes.md", "issue-dms.md"):
            self.assertIn("%.2f" % core.BAR_MIN, doc(name), name)

    def test_no_images_in_the_repo(self):
        try:
            files = subprocess.run(["git", "-C", REPO, "ls-files"], capture_output=True,
                                   text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout")
        # docs/media holds the README hero and GIFs only: built in a test
        # session, each viewed before commit, each under 5 MB
        self.assertEqual([f for f in images(files) if not f.startswith("docs/media/")], [])
        readme = read("README.md")
        for f in images(files):
            if f.startswith("docs/media/"):
                self.assertIn(f, readme, f)
                self.assertLess(os.path.getsize(os.path.join(REPO, f)), 5 * 1024 * 1024, f)

    def test_the_image_guard_finds_an_image(self):
        self.assertEqual(images(["docs/a.md", "shots/x.PNG", "a.webm", "png.txt"]),
                         ["shots/x.PNG", "a.webm"])


class DocsSayWhatTheCodeDoes(unittest.TestCase):
    """Claims the review measured against the code: each one is pinned to
    the behaviour, so a change in the engine shows up here."""

    def test_the_cli_takes_no_dotted_app_id(self):
        from appglass import settings
        with self.assertRaises(settings.SettingsError):
            settings.set_key(settings.DEFAULTS, "apps.org.gnome.Nautilus.enabled", False)
        g = section(doc("guide.md"), "Per-app switch")
        self.assertNotIn("or the app id shown by `appglass status`", g)
        self.assertRegex(g, r"dots?\b.*(IPC|settings page)")

    def test_steam_s_status_route_is_documented(self):
        from appglass import adapters
        from appglass.core import discover
        r = adapters.resolve({"key": "steam", "names": ["steam"], "toolkit": "cef"}, discover())
        if r["adapter"] != "steam-cdp":
            self.skipTest("the steam-cdp route is gone: drop the TODO in routes.md")
        self.assertEqual((r["tier"], r["effective"], r["state"]), ("forced", "fallback", "off"))
        on = adapters.resolve({"key": "steam", "names": ["steam"], "toolkit": "cef"},
                              discover(), {"apps": {"steam": {"enabled": True}}})
        # switched on, Steam is still opaque: the switch does nothing
        self.assertEqual((on["effective"], on["state"]), ("fallback", "opaque"))
        self.assertEqual(on["reason"], adapters.NO_ROUTE["cef"])
        self.assertEqual(r["reason"], adapters.NO_ROUTE["cef"])
        for name in ("routes.md", "engine.md"):
            text = doc(name)
            self.assertNotIn("adapter steam-cdp not implemented yet", text, name)
            lines = [l for l in text.splitlines() if "steam-cdp" in l]
            self.assertTrue(lines, name)
            self.assertTrue(any("TODO(adapters)" in l for l in lines), name)
            self.assertTrue(any("does nothing" in l for l in lines), name)
            self.assertIn("no injection, it stays opaque", text, name)

    def test_the_issue_demo_names_the_level_of_each_shot(self):
        t = doc("issue-dms.md")
        demo = section(t, "Demo")
        self.assertNotIn("same DMS opacity (0.60), before and after", demo)
        self.assertIn("realshims/", t)
        self.assertRegex(demo, r"real.session[^\n]*0\.80")
        shots = section(t, "Screenshots")
        self.assertRegex(shots, r"(?m)^.*0\.80.*Lian Li.*LocalSend.*Feishin.*$")
        self.assertIn("a3/dux/run4/dfiles-run4.png", shots)
        self.assertRegex(shots, r"dfiles-060\.wp\.png[^|\n]*config B")

    def test_routes_cite_no_private_probe_files(self):
        r = doc("routes.md")
        for bad in ("realshims/", "universal/jf2", "b1/after", "B4 real-session",
                    "because Electron cannot close it"):
            self.assertNotIn(bad, r)

    def test_routes_list_what_the_code_writes_and_needs(self):
        r = doc("routes.md")
        self.assertIn("autostart/solaar.desktop", section(r, "GTK3"))
        self.assertIn("llvmpipe", section(r, "LocalSend and ArtCraft"))
        jf = section(r, "Jellyfin")
        self.assertIn("Qt 6.11", jf)
        self.assertNotIn("at least as new as the flatpak runtime", jf)

    def test_engine_claims_match_the_code(self):
        e = doc("engine.md")
        self.assertNotIn("never from appGlass settings", e)
        self.assertIn("levels.content", section(e, "The levels"))
        self.assertNotIn("86 launchers", e)
        self.assertIn("86 fingerprint keys (46 launchers)", e)
        self.assertNotIn("The first route that is implemented and switched on wins", e)
        # niri validate: a typed run takes the rule out, an event run reports
        self.assertNotIn("the change is rolled back.", e)
        for sec in ("The idea in one line", "When something fails"):
            self.assertRegex(section(e, sec), r"hook or sync run[^\n]*next typed",
                             sec)

    def test_readme_matches_the_sync(self):
        r = doc("README.md")
        self.assertNotIn("(or its family is switched off)", r)
        self.assertRegex(section(r, "Apps"), r"TODO\(adapters\)")


class PerAppSwitch(unittest.TestCase):
    """`appglass set apps.<key>.enabled false --apply` takes files out only
    for a family key: an app inside a shared family keeps them."""

    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")

    def tearDown(self):
        self.sb.cleanup()

    def test_off_inside_a_shared_family_keeps_the_files_and_the_docs_say_so(self):
        code, out, err = self.sb.run("apply", "--all", assume="alacritty")
        self.assertEqual(code, 0, err)
        launcher = os.path.join(self.sb.data, "applications", "solaar.desktop")
        before = self.sb.readb(launcher)
        self.assertIn(b"GTK_THEME=AppGlass", before)
        code, out, err = self.sb.run("set", "apps.solaar.enabled", "false", "--apply",
                                     assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.readb(launcher), before)     # still glass
        code, out, err = self.sb.run("set", "apps.gtk3.enabled", "false", "--apply",
                                     assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(launcher))            # the family key does
        # the plugin's switch writes the status key: Alacritty, not alacritty
        code, out, err = self.sb.run("apply", "--all", assume="alacritty")
        s = dict(settings.DEFAULTS, apps={"Alacritty": {"enabled": False}})
        path = os.path.join(self.sb.root, "plugin-settings.json")
        with open(path, "w") as f:
            json.dump(s, f)
        code, out, err = self.sb.run("sync", "--settings-file", path, assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertIn("alacritty", self.sb.json(os.path.join(self.sb.state, "appglass", "state.json"))["owners"])
        g = section(doc("guide.md"), "Per-app switch")
        self.assertNotIn("off: that app's files are restored", g)
        self.assertIn("only for a Forced or Mod app", g)
        self.assertRegex(g, r"TODO\((engine|adapters)\)")
        self.assertNotIn("Off restores that app's files", doc("plugin.md"))
        self.assertRegex(section(doc("plugin.md"), "Apps"), r"Forced or Mod app, off takes")
        self.assertIn("Native app in Settings > Apps takes nothing out",
                      section(doc("engine.md"), "Safety"))
        intro = doc("routes.md").split("\n## ")[0]
        self.assertIn("Forced or Mod app", intro)


class PluginOwnsTheSettings(unittest.TestCase):
    """With the plugin installed, `appglass set` refuses and a typed
    `remove --only` lasts only until the next sync: the documented way to
    take a Native family out is the IPC family key."""

    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.launcher = os.path.join(self.sb.data, "applications", "solaar.desktop")

    def tearDown(self):
        self.sb.cleanup()

    def sync(self, apps):
        """The plugin's sync with its data: `dms ipc call appGlass app
        <key> off` saves apps.<key>.enabled false (Logic.withApp)."""
        s = dict(settings.DEFAULTS, apps=apps)
        path = os.path.join(self.sb.root, "plugin-settings.json")
        with open(path, "w") as f:
            json.dump(s, f)
        code, out, err = self.sb.run("sync", "--settings-file", path, assume="alacritty")
        self.assertEqual(code, 0, err)

    def test_the_documented_way_takes_a_native_family_out(self):
        for argv in (("plugin", "install"), ("apply", "--all")):
            code, out, err = self.sb.run(*argv, assume="alacritty")
            self.assertEqual(code, 0, (argv, err))
        self.assertTrue(os.path.exists(self.launcher))
        code, out, err = self.sb.run("set", "apps.gtk3.enabled", "false", "--apply",
                                     assume="alacritty")
        self.assertNotEqual(code, 0)
        self.assertIn("managed by the DMS plugin", err)
        self.assertTrue(os.path.exists(self.launcher))
        # remove --only: back with the next sync, and with a typed apply --all
        code, out, err = self.sb.run("remove", "--only", "gtk3", assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.launcher))
        self.sync({})
        self.assertTrue(os.path.exists(self.launcher))
        self.sb.run("remove", "--only", "gtk3", assume="alacritty")
        code, out, err = self.sb.run("apply", "--all", assume="alacritty")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(self.launcher))
        # the family key through IPC: out, and it stays out
        self.sync({"gtk3": {"enabled": False}})
        self.assertFalse(os.path.exists(self.launcher))
        self.sync({"gtk3": {"enabled": False}})
        self.assertFalse(os.path.exists(self.launcher))
        # the docs say so
        ipc = "dms ipc call appGlass app gtk3 off"
        g = section(doc("guide.md"), "Per-app switch")
        self.assertIn(ipc, g)
        self.assertRegex(g, r"`appglass set`[^\n]*only without the plugin")
        self.assertRegex(g, r"remove --only[^\n]*until the next sync")
        undo = section(doc("guide.md"), "Undo")
        self.assertRegex(undo, r"until the next sync")
        self.assertIn(ipc, section(doc("plugin.md"), "Apps"))
        self.assertIn(ipc, section(doc("engine.md"), "Safety"))
        intro = doc("routes.md").split("\n## ")[0]
        self.assertIn(ipc, intro)
        self.assertRegex(intro, r"until the next sync")

    def test_status_says_off_for_a_native_app_that_keeps_its_glass(self):
        code, out, err = self.sb.run("apply", "--all", assume="alacritty")
        self.assertEqual(code, 0, err)
        kdl = os.path.join(self.sb.config, "niri", "appglass.kdl")
        before = self.sb.readb(kdl)
        self.sync({"Alacritty": {"enabled": False}})
        self.assertEqual(self.sb.readb(kdl), before)
        self.assertIn(b"Alacritty", before)
        code, out, err = self.sb.run("status", "--json", assume="alacritty")
        row = [r for r in json.loads(out)["apps"] if r["key"] == "Alacritty"][0]
        self.assertEqual((row["effective"], row["reason"]), ("fallback", "off in settings"))
        for name, sec in (("guide.md", "Per-app switch"), ("engine.md", "How an app gets its route")):
            self.assertRegex(section(doc(name), sec), r"off in settings[^\n]*keeps its glass",
                             name)


class DocsRound2(unittest.TestCase):
    """Claims checked in the second review round."""

    def test_obsidian_needs_a_restart_on_the_first_enable(self):
        first = section(doc("guide.md"), "First run")
        self.assertNotIn("and the Obsidian snippet reload live", first)
        self.assertRegex(first, r"Obsidian[^\n]*restart[^\n]*first enable")
        lim = section(doc("issue-dms.md"), "Limits")
        self.assertNotIn("Dux Files and Obsidian reload live", lim)
        self.assertRegex(lim, r"Obsidian[^\n]*first enable")
        self.assertNotIn("Dux Files and the Obsidian snippet reload live", doc("engine.md"))

    def test_undo_says_what_happens_to_an_edited_file(self):
        u = section(doc("guide.md"), "Undo")
        self.assertNotIn("If you edited one of those files after appglass, only "
                         "appglass's part is taken out and your edit stays.", u)
        self.assertIn("created whole", u)
        self.assertIn(".appglass-changed", u)

    def test_an_edited_file_appglass_created_whole_goes_on_remove(self):
        sb = Sandbox()
        try:
            sb.seed_dms()
            sb.seed_niri()
            code, out, err = sb.run("apply", "--all", assume="alacritty")
            self.assertEqual(code, 0, err)
            theme = os.path.join(sb.data, "themes", "AppGlass", "gtk-3.0", "gtk.css")
            launcher = os.path.join(sb.data, "applications", "solaar.desktop")
            for p in (theme, launcher):
                with open(p, "a") as f:
                    f.write("# mine\n")
            code, out, err = sb.run("remove", "--only", "gtk3", assume="alacritty")
            self.assertEqual(code, 0, err)
            self.assertFalse(os.path.exists(theme))           # created whole: gone
            self.assertIn(b"# mine", sb.readb(launcher))      # edited into: kept
            self.assertNotIn(b"AppGlass", sb.readb(launcher))
        finally:
            sb.cleanup()

    def test_screenshot_paths_are_written_in_full(self):
        shots = section(doc("issue-dms.md"), "Screenshots")
        rows = [l for l in shots.splitlines() if l.startswith("| ") and "---" not in l][1:]
        self.assertTrue(rows)
        for row in rows:
            for p in re.findall(r"`([^`]+\.png)`", row):
                self.assertRegex(p, r"^(shots|realshims)/", row)
        self.assertRegex(shots, r"shots/a4b[^\n]*real session")
        self.assertNotRegex(shots, r"`<probe>/shots/\.\.\.` are window screenshots from nested")

    def test_the_demo_levels_are_right(self):
        demo = section(doc("issue-dms.md"), "Demo")
        self.assertIn("bars at 166 at 0.60", demo)
        self.assertNotRegex(demo, r"Measured in nested niri[^\n]*204 at 0\.80")
        bullets = "\n".join(l for l in demo.splitlines() if l.startswith("- "))
        for app in ("Feishin", "ArtCraft"):
            self.assertIn(app, bullets)

    def test_install_lists_what_vlc_and_jellyfin_need(self):
        i = section(doc("guide.md"), "Install")
        self.assertRegex(i, r"VLC[^\n]*on by default")
        self.assertIn("Qt 6.11", i)

    def test_no_step_labels_and_the_hidden_check_is_honest(self):
        self.assertNotIn("A1 probe", doc("README.md"))
        s = section(doc("engine.md"), "Safety")
        self.assertNotIn("background alpha 153 everywhere", s)
        # verify's text check: at least 12 opaque pixels (verify.judge)
        self.assertNotIn("text check has not been shown", doc("engine.md"))
        self.assertRegex(s, r"12 opaque pixels")
        from appglass import verify
        hist = {153: 1000, 255: 11}
        self.assertEqual(verify.judge(None, None, 0.60, hist)["reason"],
                         "no opaque text on screen")
        hist[255] = 12
        self.assertEqual(verify.judge(None, None, 0.60, hist)["result"], "pass")


class DocsRound2Minors(unittest.TestCase):
    """The round-2 minors: Obsidian's first apply, and when `appglass set`
    refuses (settings.plugin_active: installed AND not disabled in DMS)."""

    QUIT = "Quit Obsidian before the first `appglass apply`"

    def test_obsidian_says_quit_before_the_first_apply(self):
        for text in (section(doc("guide.md"), "First run"),
                     section(doc("issue-dms.md"), "Limits"),
                     section(doc("routes.md"), "Obsidian"),
                     doc("engine.md"), doc("electron.md")):
            self.assertIn(self.QUIT, text)

    def test_set_refuses_only_while_the_plugin_is_installed_and_enabled(self):
        sb = Sandbox()
        try:
            sb.write("dms/plugins/appGlass/plugin.json", '{"id": "appGlass"}')
            self.assertEqual(sb.run("set", "fallback.mode", "off")[0], 1)
            sb.write("dms/plugin_settings.json", '{"appGlass": {"enabled": false}}')
            self.assertEqual(sb.run("set", "fallback.mode", "off")[0], 0)
        finally:
            sb.cleanup()
        both = "installed and enabled"
        g = doc("guide.md")
        self.assertIn(both, section(g, "Per-app switch"))
        self.assertNotIn("while the plugin is installed it refuses", g)
        self.assertNotIn("While the plugin is installed it owns", g)
        p = doc("plugin.md")
        self.assertIn("## While the plugin is installed and enabled", p)
        self.assertIn("`appglass set` refuses while the plugin is installed and enabled", p)
        self.assertIn("disabled in DMS", section(p, "While the plugin is installed"))
        for name in ("routes.md", "engine.md"):
            text = doc(name)
            self.assertNotIn("off` while the plugin is installed (", text, name)
            self.assertIn("off` while the plugin is installed and enabled (", text, name)


class FadeRecorded(unittest.TestCase):
    """Each fading route says what its recorded fade did, or why none was
    recorded (a frame-by-frame capture in a headless niri session)."""

    def test_recorded_routes_give_the_curve(self):
        r = doc("routes.md")
        for sec in ("Qt Widgets", "Feishin and VSCodium", "Jellyfin", "LocalSend and ArtCraft"):
            self.assertRegex(section(r, sec), r"\*\*Fade, recorded:\*\*[^\n]*0\.80", sec)
        self.assertRegex(section(r, "LocalSend and ArtCraft"),
                         r"Fade, recorded:\*\*[^\n]*no fade")

    def test_discord_says_why_its_fade_is_not_recorded(self):
        d = section(doc("routes.md"), "Discord (Vencord)")
        self.assertRegex(d, r"\*\*Fade, not recorded:\*\*[^\n]*signed-in")
        self.assertIn("html:not(.app-focused)", d)

    def test_the_feishin_opaque_region_issue_is_written_down(self):
        f = section(doc("routes.md"), "Feishin and VSCodium")
        self.assertIn("set_opaque_region", f)
        self.assertRegex(f, r"opacity 0\.999")
        self.assertRegex(f, r"TODO\(engine\)[^\n]*opaque")


def uninstall_block():
    """The commands of the fenced block under '## Uninstall' in guide.md."""
    t = doc("guide.md")
    sec = t[t.index("\n## Uninstall"):]
    block = re.search(r"```sh\n(.*?)```", sec, re.S).group(1)
    cmds = []
    for line in block.splitlines():
        line = line.split("#")[0].strip()
        for part in filter(None, (p.strip() for p in line.split("&&"))):
            cmds.append(part)
    return cmds


class Uninstall(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")

    def tearDown(self):
        self.sb.cleanup()

    def test_the_documented_uninstall_restores_every_file(self):
        cmds = uninstall_block()
        self.assertEqual(cmds, ["appglass remove", "appglass plugin remove"])
        before = snapshot(self.sb.root)
        for argv in (("plugin", "install"), ("hook", "install"), ("apply", "--all")):
            code, out, err = self.sb.run(*argv, assume="alacritty")
            self.assertEqual(code, 0, (argv, out, err))
        self.assertNotEqual(snapshot(self.sb.root), before)
        for c in cmds:
            argv = c.split()[1:]
            code, out, err = self.sb.run(*argv, assume="alacritty")
            self.assertEqual(code, 0, (c, out, err))
        self.assertEqual(snapshot(self.sb.root), before)
        # the hook went with remove: the old third command is harmless
        code, out, _ = self.sb.run("hook", "remove")
        self.assertEqual(code, 0)
        self.assertIn("not installed", out)


if __name__ == "__main__":
    unittest.main()
