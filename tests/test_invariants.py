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
# (and a literal argv with a "remove" word in it: [root.bin, "remove"])
QML_SINKS = re.compile(r"\b(uninstallArgv|unlinkArgv|launchRemove)\b|ACTION_IDS\.uninstall\b"
                       r"|\[[^\[\]]*[\"']remove[\"']")
LOGIC_CALL = re.compile(r"\bLogic\.(\w+)\s*\(")


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
    # logic.js (imported as Logic): its functions are followed too
    logic = {}
    for path, text in sources.items():
        if path.endswith("logic.js"):
            logic = qml_units(text)[0]
    for path, text in sources.items():
        funcs, roots = qml_units(text)
        for label, body in roots:
            seen, todo = set(), [(body, funcs)]
            while todo:
                # the deferred end of a confirmed Uninstall (a sync was running
                # when it was asked): holding is set by runAction only
                b, scope = todo.pop()
                b = GATED.sub("", b)
                hit = QML_SINKS.search(b)
                if hit:
                    out.append((path, label, hit.group(0)))
                    break
                # an action runner reached from an event: Uninstall is an action
                if re.search(r"\brunAction\s*\(", b) and label not in ("onConfirmed", "onClicked"):
                    out.append((path, label, "runAction"))
                    break
                for m in LOGIC_CALL.finditer(b):
                    n = m.group(1)
                    if n in logic and ("Logic", n) not in seen:
                        seen.add(("Logic", n))
                        todo.append((logic[n][1], logic))
                # a bare call: a function of the same file (logic.js: of logic.js)
                for n in _called(re.sub(r"\bLogic\.\w+", "", b), scope):
                    if (id(scope), n) not in seen:
                        seen.add((id(scope), n))
                        todo.append((scope[n][1], scope))
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

def py_sources():
    """{module name: source text} of the appglass package."""
    out = {}
    for dp, dns, fns in os.walk(PKG):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in fns:
            if fn.endswith(".py"):
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, PKG)[:-3].replace(os.sep, ".")
                with open(p) as f:
                    out[rel] = f.read()
    return out


def _modules(sources=None):
    mods = {}
    for rel, text in (py_sources() if sources is None else sources).items():
        init = rel == "__init__" or rel.endswith(".__init__")
        name = rel[:-len("__init__")].rstrip(".") if init else rel
        tree = ast.parse(text, rel)
        tree.package = name.split(".") if init else name.split(".")[:-1]
        mods[name] = tree
    return mods


def _functions(tree):
    """[(qualified name, node)]: module-level functions and the methods of
    module-level classes (Class.method)."""
    out = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef):
            out.append((n.name, n))
        elif isinstance(n, ast.ClassDef):
            out.extend(("%s.%s" % (n.name, f.name), f) for f in n.body
                       if isinstance(f, ast.FunctionDef))
    return out


def _chain_root(node):
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def call_graph(mods):
    """{(module, function): {(module, function) it may run}}. Nodes are the
    module-level functions and the class methods (core.App.commit). An edge
    is any reference, called or not (f = cmd_remove; map(cmd_remove, ..)):
    plain names in the same module, `from . import x` / `from .x import f`
    names and x.f of an imported module. obj.name on anything else (self,
    app, ctx.app, fam: attribute dispatch) may run every method called name
    and every families.* function called name (fam.apply(ctx))."""
    defs = {(m, q) for m, tree in mods.items() for q, _ in _functions(tree)}
    dispatch = {}
    for m, q in defs:
        if "." in q or m.startswith("families."):
            dispatch.setdefault(q.rsplit(".", 1)[-1], set()).add((m, q))
    graph = {}
    for m, tree in mods.items():
        alias, absolute = {}, set()
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
            elif isinstance(node, ast.Import):
                absolute.update((a.asname or a.name).split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                absolute.update(a.asname or a.name for a in node.names)
        for q, fn in _functions(tree):
            calls = set()
            for node in ast.walk(fn):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    if (m, node.id) in defs:
                        calls.add((m, node.id))
                    elif alias.get(node.id, ("", None))[0] == "fn":
                        calls.add(alias[node.id][1])
                elif isinstance(node, ast.Attribute):
                    v = node.value
                    if isinstance(v, ast.Name) and alias.get(v.id, ("", None))[0] == "mod":
                        target = alias[v.id][1]
                        if (target, node.attr) in defs:
                            calls.add((target, node.attr))
                        continue
                    if _chain_root(v) in absolute or isinstance(v, ast.Constant):
                        continue
                    calls |= dispatch.get(node.attr, set())
            graph[(m, q)] = calls
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


# what takes glass files out: the remove commands, an owner's removal, a
# file's revert to its original, the state dir's removal
PY_SINKS = {("core", "cmd_remove"), ("hook", "remove"), ("plugin", "remove"),
            ("core", "App.remove_owner"), ("core", "App._revert"), ("core", "State.destroy")}
# event entry points: the matugen post_hook and the sync units (apply
# --from-hook), the plugin's sync and status runs (its start too), the
# vibrancy daemon, and doctor (it repairs, it never takes anything out)
PY_ROOTS = [("core", "cmd_apply"), ("core", "cmd_apply_all"), ("core", "cmd_sync"),
            ("core", "status_doc"), ("core", "cmd_doctor"), ("vibrancy", "run")]
# The edges to a sink that are the user's own switch, each allowed only when
# every use of the sink in the caller sits under a guard (an `if` test, one
# of its `and` terms) that matches:
#  - sync: the user's pause (settings enabled false; keeps the hook, checked
#    by test_sync_removes_only_for_the_pause);
#  - apply: a family the user switched off, never from the hook, and a family
#    gone only when the user typed appglass apply (_user_removes);
#  - commit: a file the owner no longer writes is reverted, never from the
#    hook (the next apply or sync does it);
#  - niri.sync: the rule with no glass app left, never from the hook; and the
#    rule niri validate rejects (its own write taken back: S7, every failure
#    ends opaque).
GUARDED = {
    (("core", "cmd_sync"), ("core", "cmd_remove")): r"not .*\benabled\b.*",
    (("core", "cmd_apply"), ("core", "App.remove_owner")): r"_user_removes\(app, why\)",
    (("core", "App.commit"), ("core", "App._revert")): r"not self\.from_hook",
    (("niri", "sync"), ("core", "App.remove_owner")): r"not app\.from_hook|ok is False",
}


def _function(mods, mod, name):
    return next(n for q, n in _functions(mods[mod]) if q == name)


def _guarded_uses(fn, attr):
    """[(use text, [guard terms])] for every reference to attr (a name or
    .attr) in fn; guard terms are the `and` terms of the enclosing if tests
    (an else branch adds not (test))."""
    out = []

    def terms(test, negate):
        if negate:
            return ["not (%s)" % ast.unparse(test)]
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            return [ast.unparse(v) for v in test.values]
        return [ast.unparse(test)]

    def visit(node, guards):
        if ((isinstance(node, ast.Name) and node.id == attr)
                or (isinstance(node, ast.Attribute) and node.attr == attr)):
            out.append((ast.unparse(node), guards))
        if isinstance(node, (ast.If, ast.IfExp)):
            visit(node.test, guards)
            body = node.body if isinstance(node.body, list) else [node.body]
            orelse = node.orelse if isinstance(node.orelse, list) else [node.orelse]
            for c in body:
                visit(c, guards + terms(node.test, False))
            for c in orelse:
                visit(c, guards + terms(node.test, True))
            return
        for c in ast.iter_child_nodes(node):
            visit(c, guards)
    visit(fn, [])
    return out


def allowed_edges(mods, graph):
    """The GUARDED edges whose every use sits under its guard."""
    ok = set()
    for (caller, sink), rx in GUARDED.items():
        if caller not in graph or sink not in graph[caller]:
            continue
        uses = _guarded_uses(_function(mods, *caller), sink[1].rsplit(".", 1)[-1])
        if uses and all(any(re.fullmatch(rx, g) for g in gs) for _, gs in uses):
            ok.add((caller, sink))
    return ok


def remove_argv(mods, nodes):
    """A list or tuple literal holding "remove" (an argv for appglass remove,
    plugin remove or hook remove) in a function of nodes: [(node, text)]."""
    out = []
    for m, q in sorted(nodes):
        if m not in mods:
            continue
        for node in ast.walk(_function(mods, m, q)):
            if isinstance(node, (ast.List, ast.Tuple)) and any(
                    isinstance(e, ast.Constant) and e.value == "remove" for e in node.elts):
                out.append(((m, q), ast.unparse(node)))
    return out


def py_violations(sources=None):
    """What an event entry reaches that takes something out: the sinks
    reached (besides the allowed edges) and the remove argv literals."""
    mods = _modules(sources)
    graph = call_graph(mods)
    seen = reach(graph, PY_ROOTS, allowed_edges(mods, graph))
    return sorted(seen & PY_SINKS), remove_argv(mods, seen)


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


def plant(sources, mod, func, line):
    """sources with line put first in mod's function func (after its
    docstring), at that body's indentation."""
    text = sources[mod]
    fn = _function(_modules({mod: text}), mod, func)
    body = fn.body
    first = body[1] if (len(body) > 1 and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)) else body[0]
    lines = text.splitlines(True)
    lines.insert(first.lineno - 1, " " * first.col_offset + line + "\n")
    return dict(sources, **{mod: "".join(lines)})


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


    def test_checker_catches_violations_planted_in_the_daemon(self):
        # the real DaemonBody.qml with one line added: a literal remove argv
        # in the teardown, and the remove argv reached through logic.js
        src = plugin_sources()
        path = os.path.join("components", "DaemonBody.qml")
        body = src[path]
        teardown = "    Component.onDestruction: {\n"
        self.assertEqual(body.count(teardown), 1)
        plants = (
            teardown + '        Proc.runCommand("x", [root.bin, "remove"], null);\n',
            teardown + '        Proc.runCommand("x", Logic.actionArgv("uninstall", root.bin), null);\n',
            teardown + '        Proc.runCommand("x", Logic.cliArgv(root.bin, ["plugin", "remove"]), null);\n',
        )
        for plant in plants:
            with self.subTest(plant=plant.splitlines()[1].strip()):
                hits = qml_violations(dict(src, **{path: body.replace(teardown, plant)}))
                self.assertEqual([(p, r) for p, r, _ in hits],
                                 [(path, "Component.onDestruction")], hits)


class PythonInvariant(unittest.TestCase):
    def setUp(self):
        self.mods = _modules()
        self.graph = call_graph(self.mods)

    def test_graph_resolves_the_known_edges(self):
        g = self.graph
        self.assertIn(("core", "cmd_remove"), g[("core", "cmd_sync")])
        self.assertIn(("hook", "remove"), g[("core", "cmd_remove")])
        self.assertIn(("core", "cmd_apply"), g[("core", "cmd_apply_all")])
        # methods, attribute dispatch and the families
        self.assertIn(("core", "App.commit"), g[("core", "cmd_apply")])
        self.assertIn(("core", "App._revert"), g[("core", "App.commit")])
        self.assertIn(("families.alacritty", "apply"), g[("core", "cmd_apply")])
        self.assertIn(("core", "Ctx.write_owned"), g[("families.alacritty", "apply")])
        for r in PY_ROOTS:
            self.assertTrue(r in g, r)

    def test_the_guarded_edges_are_all_allowed(self):
        self.assertEqual(allowed_edges(self.mods, self.graph), set(GUARDED))

    def test_no_event_entry_reaches_remove(self):
        self.assertEqual(py_violations(), ([], []))

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

    def test_checker_catches_planted_violations(self):
        src = py_sources()
        plants = [
            # a method on the write path of every sync
            ("core", "App.commit", "cmd_remove(self)"),
            ("core", "App.commit", "self.remove_owner(ctx.owner)"),
            # a family: fam.apply(ctx) is attribute dispatch
            ("families.alacritty", "apply", "ctx.app.remove_owner('alacritty')"),
            ("families.alacritty", "apply", "__import__('appglass').core.cmd_remove(ctx.app)"),
            # a function passed on or renamed
            ("core", "cmd_apply_all", "f = cmd_remove; f(app)"),
            ("core", "status_doc", "list(map(cmd_remove, [app]))"),
            ("vibrancy", "run", "subprocess.run(['appglass', 'remove'])"),
            ("core", "cmd_apply_all", "app.state.destroy()"),
        ]
        for mod, func, line in plants:
            with self.subTest(line=line):
                sinks, argv = py_violations(plant(src, mod, func, line))
                if "__import__" in line:
                    continue   # not resolvable statically; the import form is
                self.assertTrue(sinks or argv, line)
        # the import a family would really use
        fam = src["families.alacritty"].replace(
            "from ..core import", "from .. import core\nfrom ..core import", 1)
        sinks, _ = py_violations(plant(dict(src, **{"families.alacritty": fam}),
                                       "families.alacritty", "apply", "core.cmd_remove(ctx.app)"))
        self.assertIn(("core", "cmd_remove"), sinks)

    def test_checker_catches_a_guard_taken_out(self):
        src = py_sources()
        for mod, old, new in (
                ("core", "if not self.from_hook:", "if True:"),
                ("core", "if name in app.state.owners and _user_removes(app, why):",
                 "if name in app.state.owners:")):
            with self.subTest(old=old):
                self.assertTrue(old in src[mod], old)
                sinks, _ = py_violations(dict(src, **{mod: src[mod].replace(old, new, 1)}))
                self.assertTrue(sinks, old)

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
