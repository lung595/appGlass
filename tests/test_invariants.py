"""S6: no event removes anything. Only the user's explicit Uninstall (the
confirmed sheet in Settings > Advanced) or `appglass remove` typed in a
terminal reaches `appglass remove` / core.cmd_remove. Events are the
plugin's teardown, timers, file watches, IPC handlers, its sync and status
runs, the path units, the matugen post_hook and the vibrancy daemon.

The checks are static: the plugin QML/JS is cut into handlers and
functions and walked from every event root; the Python package is walked
with ast from the event entry points. Each checker also runs on a planted
violation, so a checker that finds nothing proves it can find something."""

import ast
import os
import re
import unittest

from fixtures.sandbox import REPO

PLUGIN = os.path.join(REPO, "dms-plugin")
PKG = os.path.join(REPO, "appglass")

# What runs `appglass remove` or `appglass plugin remove` in the plugin
# `if (root.holding) <statement>`: holding is the Uninstall token, set only
# in runAction's uninstall branch (test_holding_is_set_by_uninstall_only)
GATED = re.compile(r"if\s*\(\s*root\.holding\s*\)\s*(\{[^{}]*\}|[^;\n]*;?)")
QML_SINKS = re.compile(r"\b(uninstallArgv|unlinkArgv|launchRemove)\b|ACTION_IDS\.uninstall\b")


# ---------------------------------------------------------------- QML/JS

def _skip_str(text, i):
    q = text[i]
    i += 1
    while i < len(text) and text[i] != q:
        i += 2 if text[i] == "\\" else 1
    return i + 1


def _block_end(text, i):
    """text[i] == '{': the index after the matching '}' (strings and
    comments skipped)."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            i = _skip_str(text, i)
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i)
            i = n if j < 0 else j + 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _strip_comments(text):
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            j = _skip_str(text, i)
            out.append(text[i:j])
            i = j
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


FUNC = re.compile(r"\bfunction\s+(\w+)\s*\(([^)]*)\)\s*(?::\s*[\w.<>]+\s*)?\{")
HANDLER = re.compile(r"(?m)^\s*((?:Component\.|Keys\.)?on[A-Z]\w*)\s*:\s*")
OBJECT = re.compile(r"(?m)^\s*(\w+)\s*\{")


def _handler_body(text, j):
    """The handler expression starting at j: a block, an arrow function or
    one statement up to the end of its line."""
    k = j
    m = re.match(r"(?:\w+|\([^)]*\))\s*=>\s*", text[k:])
    if m:
        k += m.end()
    if k < len(text) and text[k] == "{":
        return text[j:_block_end(text, k)]
    e = text.find("\n", j)
    return text[j:len(text) if e < 0 else e]


def qml_units(text):
    """(functions, roots): functions {name: (params, body)} and the event
    roots [(label, body)]: every on<Signal> handler and every function
    declared in an IpcHandler, Timer or Connections object."""
    text = _strip_comments(text)
    funcs, roots = {}, []
    for m in FUNC.finditer(text):
        body = text[m.end() - 1:_block_end(text, m.end() - 1)]
        funcs.setdefault(m.group(1), (m.group(2), body))
    for m in HANDLER.finditer(text):
        roots.append((m.group(1), _handler_body(text, m.end())))
    for m in OBJECT.finditer(text):
        if m.group(1) in ("IpcHandler", "Timer", "Connections", "FileView", "Process"):
            start = m.end() - 1
            obj = text[start:_block_end(text, start)]
            for f in FUNC.finditer(obj):
                body = obj[f.end() - 1:_block_end(obj, f.end() - 1)]
                roots.append(("%s.%s" % (m.group(1), f.group(1)), body))
    return funcs, roots


def _called(body, names):
    return {n for n in re.findall(r"\b(\w+)\s*\(", body) if n in names}


def qml_violations(sources):
    """Event roots of sources {path: text} that reach a remove sink or an
    action runner. [(path, root, why)]."""
    out = []
    for path, text in sources.items():
        funcs, roots = qml_units(text)
        for label, body in roots:
            seen, todo = set(), [body]
            while todo:
                # the deferred end of a confirmed Uninstall (a sync was running
                # when it was asked): holding is set by runAction only
                b = GATED.sub("", todo.pop())
                hit = QML_SINKS.search(b)
                if hit:
                    out.append((path, label, hit.group(0)))
                    break
                # an action runner reached from an event: Uninstall is an action
                if re.search(r"\brunAction\s*\(", b) and label not in ("onConfirmed", "onClicked"):
                    out.append((path, label, "runAction"))
                    break
                for n in _called(b, funcs) - seen:
                    seen.add(n)
                    todo.append(funcs[n][1])
    return out


def uninstall_call_sites(sources):
    """Every call that names the uninstall action: [(path, line text)]."""
    out = []
    for path, text in sources.items():
        for ln in _strip_comments(text).splitlines():
            if re.search(r"""\b(run|runAction)\s*\(\s*["']uninstall["']""", ln):
                out.append((path, ln.strip()))
    return out


def plugin_sources():
    out = {}
    for dp, dns, fns in os.walk(PLUGIN):
        dns[:] = [d for d in dns if d != "tests"]
        for fn in fns:
            if fn.endswith((".qml", ".js")):
                p = os.path.join(dp, fn)
                with open(p) as f:
                    out[os.path.relpath(p, PLUGIN)] = f.read()
    return out


# ---------------------------------------------------------------- Python

def _modules():
    mods = {}
    for dp, dns, fns in os.walk(PKG):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in fns:
            if fn.endswith(".py"):
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, PKG)[:-3].replace(os.sep, ".")
                init = rel == "__init__" or rel.endswith(".__init__")
                name = rel[:-len("__init__")].rstrip(".") if init else rel
                with open(p) as f:
                    tree = ast.parse(f.read(), p)
                tree.package = name.split(".") if init else name.split(".")[:-1]
                mods[name] = tree
    return mods


def call_graph(mods):
    """{(module, function): {(module, function) called}} for module-level
    functions; calls are resolved through `from . import x` and
    `from .x import f` and plain names in the same module."""
    defs = {(m, n.name) for m, tree in mods.items() for n in tree.body
            if isinstance(n, ast.FunctionDef)}
    graph = {}
    for m, tree in mods.items():
        alias = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                parts = [x for x in tree.package if x]
                parts = parts[:len(parts) - (node.level - 1)]
                base = ".".join(parts + ([node.module] if node.module else []))
                for a in node.names:
                    if (base, a.name) in defs:
                        alias[a.asname or a.name] = ("fn", (base, a.name))
                    else:
                        sub = (base + "." + a.name) if base else a.name
                        alias[a.asname or a.name] = ("mod", sub if sub in mods else a.name)
        for fn in tree.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            calls = set()
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if isinstance(f, ast.Name):
                    if (m, f.id) in defs:
                        calls.add((m, f.id))
                    elif alias.get(f.id, ("", None))[0] == "fn":
                        calls.add(alias[f.id][1])
                elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                    kind, target = alias.get(f.value.id, ("", None))
                    if kind == "mod" and (target, f.attr) in defs:
                        calls.add((target, f.attr))
            graph[(m, fn.name)] = calls
    return graph


def reach(graph, roots, cut=()):
    seen, todo = set(), list(roots)
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        todo.extend(c for c in graph.get(n, ()) if (n, c) not in cut)
    return seen


PY_SINKS = {("core", "cmd_remove"), ("hook", "remove"), ("plugin", "remove")}
# event entry points: the matugen post_hook and the sync units (apply
# --from-hook), the plugin's sync and status runs, the vibrancy daemon,
# and doctor (it repairs, it never takes anything out)
PY_ROOTS = [("core", "cmd_apply"), ("core", "cmd_apply_all"), ("core", "cmd_sync"),
            ("core", "status_doc"), ("core", "cmd_doctor"), ("vibrancy", "run")]


def _function(mods, mod, name):
    return next(n for n in mods[mod].body if isinstance(n, ast.FunctionDef) and n.name == name)


def pause_calls_ok(mods):
    """cmd_sync's calls to cmd_remove: all keep_hook=True and under a test
    of the saved settings' enabled (the user's pause). (bad, total)"""
    fn = _function(mods, "core", "cmd_sync")
    bad, total = [], 0

    def visit(node, guards):
        nonlocal total
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "cmd_remove":
            total += 1
            kw = {k.arg: k.value for k in node.keywords}
            keep = isinstance(kw.get("keep_hook"), ast.Constant) and kw["keep_hook"].value is True
            paused = any(g.startswith("not ") and "enabled" in g for g in guards)
            if not (keep and paused):
                bad.append(ast.unparse(node))
        for child in ast.iter_child_nodes(node):
            visit(child, guards + [ast.unparse(node.test)] if isinstance(node, ast.If)
                  and child is not node.test else guards)
    visit(fn, [])
    return bad, total


class QmlInvariant(unittest.TestCase):
    def test_no_plugin_event_reaches_remove(self):
        self.assertEqual(qml_violations(plugin_sources()), [])

    def test_uninstall_is_only_the_confirmed_sheet(self):
        sites = uninstall_call_sites(plugin_sources())
        self.assertEqual(len(sites), 1, sites)
        path, line = sites[0]
        self.assertTrue(line.startswith("onConfirmed:"), line)
        text = plugin_sources()[path]
        i = text.find(line)
        sheet = text.rfind("ConfirmSheet {", 0, i)
        self.assertIn('objectName: "confirmUninstall"', text[sheet:i])

    def test_sinks_live_in_the_action_path_only(self):
        # whoever uses the remove argv is reached from runAction only
        users = set()
        for path, text in plugin_sources().items():
            funcs, _ = qml_units(text)
            for name, (_, body) in funcs.items():
                if QML_SINKS.search(GATED.sub("", body)) and not path.endswith("logic.js"):
                    users.add(name)
        self.assertTrue(users, "the checker found no remove sink at all")
        self.assertLessEqual(users, {"runAction", "launchRemove", "removeDone"}, users)

    def test_holding_is_set_by_uninstall_only(self):
        sets = []
        for path, text in plugin_sources().items():
            funcs, _ = qml_units(text)
            for name, (_, body) in funcs.items():
                for m in re.finditer(r"\bholding\s*=\s*true", body):
                    branch = body.rfind('if (name === "uninstall")', 0, m.start())
                    sets.append((path, name, branch >= 0))
        self.assertTrue(sets)
        self.assertEqual({(n, ok) for _, n, ok in sets}, {("runAction", True)})

    def test_checker_catches_a_planted_violation(self):
        planted = {
            "a.qml": "Item {\n    Component.onDestruction: root.cleanup()\n"
                     "    function cleanup() { root.launchRemove(); }\n"
                     "    function launchRemove() { Proc.runCommand(Logic.ACTION_IDS.uninstall, "
                     "Logic.uninstallArgv(root.bin)); }\n}\n",
            "b.qml": "Item {\n    Timer {\n        onTriggered: root.runAction(\"uninstall\")\n    }\n}\n",
            "c.qml": "Item {\n    IpcHandler {\n        target: \"x\"\n"
                     "        function wipe(): string {\n            root.runAction(\"uninstall\");\n"
                     "            return \"ok\";\n        }\n    }\n}\n",
            "e.qml": "Item {\n    function syncDone() { if (root.busy) root.launchRemove(); }\n"
                     "    Timer {\n        onTriggered: root.syncDone()\n    }\n}\n",
            "d.qml": "Item {\n    // root.launchRemove() in a comment is not a call\n"
                     "    Component.onCompleted: root.ok()\n    function ok() { return 1; }\n}\n",
        }
        hits = {p for p, _, _ in qml_violations(planted)}
        self.assertEqual(hits, {"a.qml", "b.qml", "c.qml", "e.qml"})


class PythonInvariant(unittest.TestCase):
    def setUp(self):
        self.mods = _modules()
        self.graph = call_graph(self.mods)

    def test_graph_resolves_the_known_edges(self):
        self.assertIn(("core", "cmd_remove"), self.graph[("core", "cmd_sync")])
        self.assertIn(("hook", "remove"), self.graph[("core", "cmd_remove")])
        self.assertIn(("core", "cmd_apply"), self.graph[("core", "cmd_apply_all")])
        for r in PY_ROOTS:
            self.assertTrue(r in self.graph, r)

    def test_no_event_entry_reaches_remove(self):
        cut = {(("core", "cmd_sync"), ("core", "cmd_remove"))}
        got = reach(self.graph, PY_ROOTS, cut) & PY_SINKS
        self.assertEqual(got, set())

    def test_sync_removes_only_for_the_pause(self):
        bad, total = pause_calls_ok(self.mods)
        self.assertEqual(bad, [])
        self.assertEqual(total, 1)
        # and the pause keeps the hook: hook.remove sits behind not keep_hook
        fn = _function(self.mods, "core", "cmd_remove")
        for node in ast.walk(fn):
            if isinstance(node, ast.If):
                body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
                if "hook.remove(" in body:
                    self.assertIn("not keep_hook", ast.unparse(node.test))

    def test_checker_catches_a_planted_violation(self):
        g = dict(self.graph)
        g[("vibrancy", "run")] = set(g[("vibrancy", "run")]) | {("core", "cmd_remove")}
        self.assertIn(("core", "cmd_remove"), reach(g, PY_ROOTS))

    def test_scripts_and_units_never_run_remove(self):
        files = [os.path.join(REPO, "bin", "appglass-sync")]
        sync_dir = os.path.join(REPO, "shims", "sync")
        files += [os.path.join(sync_dir, n) for n in sorted(os.listdir(sync_dir))]
        for p in files:
            with open(p) as f:
                for ln in f:
                    code = ln.split("#", 1)[0] if not ln.startswith(("ExecStart", "Exec")) else ln
                    self.assertIsNone(re.search(r"\bremove\b", code), "%s: %s" % (p, ln))


if __name__ == "__main__":
    unittest.main()
