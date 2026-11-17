"""The user docs match the code: commands, IPC calls, plugin labels, links,
and the uninstall block really undoes an install."""

import codecs
import os
import re
import subprocess
import unittest

from fixtures.sandbox import Sandbox, REPO
from appglass import core

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
        for name in sorted(os.listdir(DOCS)):
            if not name.endswith(".md"):
                continue
            for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", doc(name)):
                if "://" in target or target.startswith("mailto:"):
                    continue
                self.assertTrue(os.path.exists(os.path.join(DOCS, target)),
                                "%s links %s" % (name, target))

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
        imgs = [f for f in files if re.search(r"\.(png|jpe?g|gif|webp|mp4|webm)$", f, re.I)]
        self.assertEqual(imgs, [])


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
