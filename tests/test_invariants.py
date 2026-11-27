"""S6: no event removes anything. Only the user's explicit Uninstall (the
confirmed sheet in Settings > Advanced), `appglass remove` typed in a
terminal, or an uninstall in DMS (UninstallSweep, once plugin.json is gone:
SWEEP_ROOT) reaches `appglass remove` / core.cmd_remove. Events are the
plugin's teardown, timers, file watches, IPC handlers, its sync and status
runs, the path units, the matugen post_hook and the vibrancy daemon.

The checks are static: the plugin QML/JS is cut into handlers and
functions and walked from every event root; the Python package is walked
with ast from the event entry points. Each checker also runs on a planted
violation, so a checker that finds nothing proves it can find something.

The static checks follow names and literal strings: a sink reached by a
name built at run time (getattr(app, name) with name from a variable, an
argv read from a file) is out of their reach. The runtime guard closes that
part: main marks every run that is not a command the user typed as an
event (App.event), and in an event run App._revert, App.remove_owner,
App._drop_backup, State.destroy, cmd_remove, hook.remove and plugin.remove
raise EventRemove whatever reached them (test_safety.EventGuard), and an
event save neither drops a record nor changes what it owes (kind, how,
backup, orig_sha256, adopted); only the user's own switch (App.user_action:
glass off, a family switched off in the plugin) lifts it. That guard is
itself checked here: App.event, State.event_guard and App.no_event are set
only by main, App.user_action and the constructors (event_switches)."""

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
# (and a literal argv with a "remove" word in it: [root.bin, "remove"]; a
# string that is the remove word, to join or concat: root.bin + " remove";
# a remove word in a string handed to a process: execDetached(["sh", "-c",
# "appglass remove"]), command: [..]. Text shown to the user, "run
# appglass remove in a terminal", is none of these)
QML_SINKS = re.compile(r"\b(uninstallArgv|unlinkArgv|launchRemove)\b|ACTION_IDS\.uninstall\b"
                       r"|\[[^\[\]]*[\"']remove[\"']"
                       r"|[\"'`]\s*(?:(?:plugin|hook)\s+)?remove\s*[\"'`]"
                       r"|(?:\b(?:execDetached|startDetached|runCommand)\s*\(|\bcommand\s*[:=])"
                       r"[^;\n]*[\"'`][^\"'`\n]*\bremove\b")


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


_CONCAT = re.compile(r"""(["'`])([^"'`\\\n]*)\1\s*\+\s*(["'`])([^"'`\\\n]*)\3""")


def _fold_concat(text):
    """String literals joined with + made one literal ("re" + "move" is
    "remove"), so the sink patterns see the word the program builds. A word
    built from variables ("re" + x) is past a static check: the engine's
    run-time guard (App.event) stops what this misses."""
    while True:
        new = _CONCAT.sub(lambda m: '"%s%s"' % (m.group(2), m.group(4)), text)
        if new == text:
            return text
        text = new


def qml_units(text, js=False):
    """(functions, roots): functions {name: (params, body)} and the event
    roots [(label, body)]: every on<Signal> handler, every function declared
    in an IpcHandler, Timer or Connections object, and the declarations (the
    file without its functions and handlers: every property binding and
    object, a Process's command among them, is evaluated when it loads; a
    .js library's top level (js) is data: its search keywords, its tables)."""
    text = _fold_concat(_strip_comments(text))
    funcs, roots, spans = {}, [], []
    for m in FUNC.finditer(text):
        end = _block_end(text, m.end() - 1)
        body = text[m.end() - 1:end]
        # two functions of one name (in two objects): both are followed
        old = funcs.get(m.group(1))
        funcs[m.group(1)] = (m.group(2), old[1] + "\n" + body if old else body)
        spans.append((m.start(), end))
    for m in HANDLER.finditer(text):
        body = _handler_body(text, m.end())
        roots.append((m.group(1), body))
        spans.append((m.start(), m.end() + len(body)))
    decl, i = [], 0
    for a, b in sorted(spans):
        if a >= i:
            decl.append(text[i:a])
        i = max(i, b)
    if not js:
        roots.append(("<declarations>", "".join(decl) + text[i:]))
    for m in OBJECT.finditer(text):
        if m.group(1) in ("IpcHandler", "Timer", "Connections", "FileView", "Process"):
            start = m.end() - 1
            obj = text[start:_block_end(text, start)]
            for f in FUNC.finditer(obj):
                body = obj[f.end() - 1:_block_end(obj, f.end() - 1)]
                roots.append(("%s.%s" % (m.group(1), f.group(1)), body))
    return funcs, roots


def _code(text):
    """text with its string literals emptied (a template literal keeps
    what its ${..} runs): a word in a string is not a reference."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            j = _skip_str(text, i)
            out.append(c + " ".join(re.findall(r"\$\{([^}]*)\}", text[i:j]) if c == "`" else ())
                       + c)
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


SUBSCRIPT = re.compile(r"""\[\s*["'`](\w+)["'`]\s*\]""")


def _refs(body, names):
    """The names of names that body refers to, called or not: f(), a
    function handed over (Qt.callLater(f), sig.connect(f), a handler that
    is a bare name), x.f through any x (an alias of Logic), x["f"]."""
    words = set(re.findall(r"\b[A-Za-z_]\w*\b", _code(body))) | set(SUBSCRIPT.findall(body))
    return {n for n in words if n in names}


# The one event root allowed to reach remove: a DMS uninstall (the user's
# own Uninstall in DMS) deleted plugin.json, and the sweep runs the rescue
# copy with `remove --if-gone`, which does nothing while plugin.json exists
SWEEP_ROOT = ("components/UninstallSweep.qml", "Component.onDestruction")
SWEEP_SINK = "Logic.sweepArgv("


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
        funcs, roots = qml_units(text, js=path.endswith(".js"))
        for label, body in roots:
            if (path, label) == SWEEP_ROOT:
                # only its sweepArgv call is allowed: any other sink still counts
                body = body.replace(SWEEP_SINK, "(")
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
                # an action runner reached from an event (called or held):
                # Uninstall is an action
                if (_refs(b, ("runAction",)) and label not in ("onConfirmed", "onClicked")):
                    out.append((path, label, "runAction"))
                    break
                # a logic.js function, by any name of Logic (L = Logic; L.f())
                for n in _refs(b, logic):
                    if ("Logic", n) not in seen:
                        seen.add(("Logic", n))
                        todo.append((logic[n][1], logic))
                # a function of the same file (logic.js: of logic.js)
                for n in _refs(re.sub(r"\bLogic\s*\.\s*\w+", "", b), scope):
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
            ("core", "App.remove_owner"), ("core", "App._revert"), ("core", "App._revert_stale"),
            ("core", "State.destroy"),
            # typed only: restore puts an entry back (files the entry says were
            # absent deleted), adopt --rescue moves originals no file names
            ("core", "cmd_restore"), ("core", "cmd_rescue")}
# event entry points: the matugen post_hook and the sync units (apply
# --from-hook), the plugin's sync and status runs (its start too), the
# vibrancy daemon, and doctor (it repairs, it never takes anything out); the
# dispatcher every one of them goes through (main) and its lock release
PY_ROOTS = [("core", "cmd_apply"), ("core", "cmd_apply_all"), ("core", "cmd_sync"),
            ("core", "status_doc"), ("core", "cmd_doctor"), ("vibrancy", "run"),
            ("core", "main"), ("core", "_unlock")]
# The edges to a sink that are the user's own switch, each allowed only when
# every use of the sink in the caller sits under a guard (an `if` test, one
# of its `and` terms) that matches:
#  - sync: the user's pause (settings enabled false; keeps the hook, checked
#    by test_sync_removes_only_for_the_pause);
#  - apply: a family the user switched off (in an event run: in this very
#    sync), never from the hook, and a family gone only when the user typed
#    appglass apply (_user_removes);
#  - commit: a file the owner no longer writes is reverted, never in an
#    event run (the record is kept, marked unplanned);
#  - niri.sync: the rule with no glass app left, and the rule niri validate
#    rejects (S7, every failure ends opaque), never in an event run (the
#    owner is marked, the next typed command validates again);
#  - main: the remove commands the user typed (appglass remove, hook remove,
#    plugin remove, restore, adopt --rescue);
#  - _unlock: the state dir of a run, not an event, that ended with nothing
#    owned.
# A guard is a regex or a tuple of regexes that each match one guard term.
GUARDED = {
    (("core", "cmd_sync"), ("core", "cmd_remove")): r"not .*\benabled\b.*",
    (("core", "cmd_apply"), ("core", "App.remove_owner")): r"_user_removes\(app, why, name\)",
    (("core", "App.commit"), ("core", "App._revert_stale")): r"not self\.event",
    (("niri", "sync"), ("core", "App.remove_owner")): r"not app\.event",
    (("core", "main"), ("core", "cmd_remove")): r"args\.cmd == 'remove'",
    (("core", "main"), ("hook", "remove")): (
        r"args\.cmd == 'hook'", r"not \(args\.action == 'install'\)", r"not \(args\.dry_run\)"),
    (("core", "main"), ("plugin", "remove")): (
        r"args\.cmd == 'plugin'", r"not \(args\.action == 'install'\)"),
    (("core", "main"), ("core", "cmd_restore")): r"args\.cmd == 'restore'",
    (("core", "main"), ("core", "cmd_rescue")): (r"args\.cmd == 'adopt'", r"args\.rescue"),
    (("core", "_unlock"), ("core", "State.destroy")): (
        r"not \(st\.owners or st\.data\.get\('parked'\) or app\.keep_state_dir\)",
        r"not app\.event"),
}


def _function(mods, mod, name):
    return next(n for q, n in _functions(mods[mod]) if q == name)


def _guarded_uses(fn, attr, module=None):
    """[(use text, [guard terms])] for every reference to attr (a name or
    .attr; with module, a module-level function: the name or module.attr)
    in fn; guard terms are the `and` terms of the enclosing if tests (an
    else branch adds not (test))."""
    out = []
    base = module.rsplit(".", 1)[-1] if module else None

    def terms(test, negate):
        if negate:
            return ["not (%s)" % ast.unparse(test)]
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            return [ast.unparse(v) for v in test.values]
        return [ast.unparse(test)]

    def visit(node, guards):
        if ((isinstance(node, ast.Name) and node.id == attr)
                or (isinstance(node, ast.Attribute) and node.attr == attr
                    and (base is None or (isinstance(node.value, ast.Name)
                                          and node.value.id == base)))):
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
        mod = None if "." in sink[1] else (None if sink[0] == caller[0] else sink[0])
        uses = _guarded_uses(_function(mods, *caller), sink[1].rsplit(".", 1)[-1], mod)
        rxs = (rx,) if isinstance(rx, str) else rx
        if uses and all(all(any(re.fullmatch(r, g) for g in gs) for r in rxs)
                        for _, gs in uses):
            ok.add((caller, sink))
    return ok


# the names a sink is reached by without a reference: getattr(hook,
# "remove"), an argv word
SINK_NAMES = {q.rsplit(".", 1)[-1] for _, q in PY_SINKS}
# what runs a command line: a "remove" word in one of its strings
RUNNERS = re.compile(r"system|popen|Popen|run|call|check_call|check_output|getoutput"
                     r"|getstatusoutput|exec\w*|spawn\w*")
# the parser's own words: the subcommand names and choices, the cmd tests
PARSER_CALLS = ("add_parser", "add_argument")


def _str_value(node, names=None):
    """The string an expression of literals builds ("re" + "move",
    "".join(["re", "move"])), else None; names: {name: string} of the
    function's variables that hold one (w = "re"; w + "move")."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and names:
        return names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _str_value(node.left, names), _str_value(node.right, names)
        return None if a is None or b is None else a + b
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "join" and len(node.args) == 1
            and isinstance(node.args[0], (ast.List, ast.Tuple))):
        sep = _str_value(node.func.value, names)
        parts = [_str_value(e, names) for e in node.args[0].elts]
        if sep is not None and None not in parts:
            return sep.join(parts)
    return None


def _str_names(fn):
    """{name: string} of the variables fn sets to a string of literals."""
    out = {}
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            v = _str_value(node.value, out)
            if v is not None:
                out[node.targets[0].id] = v
    return out


# what deletes (or moves away) a file or a dir by hand, not through a sink
DELETES = {("shutil", "rmtree"), ("os", "remove"), ("os", "unlink"), ("os", "rmdir"),
           ("os", "removedirs"), ("os", "rename"), ("os", "renames"), ("os", "replace"),
           ("shutil", "move")}
# pathlib.Path methods that delete or move (on any receiver: no str method
# has these names) and the ones that do on a Path(..) receiver only
PATH_DELETES = {"unlink", "rmdir", "rename"}
PATH_ONLY = {"replace"}
# the event-path functions allowed to delete, each for its own files only:
DELETE_SITES = {
    ("core", "App._retire_file"),  # a retired hand file (adopted, its backup kept)
    ("core", "App._drop_backup"),  # a backup no record names (after a user's revert)
    ("core", "App._unpend"),       # the backup its own failed write made, of bytes
                                   # the file still holds (no original is lost)
    ("core", "State._drop_partial"),  # a backup a kill cut short, of bytes the
                                   # file still holds whole (no original is lost)
    ("core", "App._ring_entry"),   # ring entries past RING_KEEP, half-written ones
    ("core", "_unlock"),           # its own lock and the dirs the lock made
    ("core", "_atomic_write"),     # a write: its own temp file moved over the target
    ("core", "doctor_drift"),      # a dangling plugin link, snapshotted first
    ("shims", "build"),            # its own temporary build dir
    ("engine", "Store.sync_markers"),  # its own plain/ markers (engine state, no
                                   # owned file: what runs plain, never glass)
    ("inputs", "drop"),            # the hook digest: its own temp file moved over it
    ("inputs", "save"),            # (engine state, no owned file)
    ("rescue", "write"),           # its own rescue copy of the CLI, replaced whole
}


def _module_aliases(tree):
    """{name: module} for the names a module binds to os, shutil or pathlib
    (import os as _o, _o = os)."""
    mods = ("os", "shutil", "pathlib")
    out = {m: m for m in mods}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in mods:
                    out[a.asname or a.name] = a.name
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) \
                and node.value.id in out:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = out[node.value.id]
    return out


def _is_path_call(node):
    f = getattr(node, "func", None) if isinstance(node, ast.Call) else None
    return ((isinstance(f, ast.Name) and f.id in ("Path", "PurePath"))
            or (isinstance(f, ast.Attribute) and f.attr in ("Path", "PurePath")))


def deletes(mods, nodes):
    """Deletions by hand (os.remove, shutil.rmtree, os.rename, shutil.move,
    Path.unlink .., through an alias of os too) in a function of nodes
    outside DELETE_SITES: [(node, text)]."""
    out = []
    for m, q in sorted(nodes):
        if m not in mods or (m, q) in DELETE_SITES:
            continue
        alias = _module_aliases(mods[m])
        for node in ast.walk(_function(mods, m, q)):
            f = getattr(node, "func", None)
            if not (isinstance(node, ast.Call) and isinstance(f, ast.Attribute)):
                continue
            if (isinstance(f.value, ast.Name) and f.value.id in alias
                    and (alias[f.value.id], f.attr) in DELETES):
                out.append(((m, q), ast.unparse(node)))
            elif f.attr in PATH_DELETES or (f.attr in PATH_ONLY and _is_path_call(f.value)):
                out.append(((m, q), ast.unparse(node)))
    return out


# the only functions that run the user's own switch inside an event run
USER_ACTION_SITES = {("core", "cmd_apply"), ("core", "cmd_sync")}


def user_actions(mods):
    """Every reference to user_action outside USER_ACTION_SITES (and its
    own definition), in any function: [(node, text)]."""
    out = []
    for m, tree in sorted(mods.items()):
        for q, fn in _functions(tree):
            if (m, q) in USER_ACTION_SITES or q == "App.user_action":
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Attribute) and node.attr == "user_action") or (
                        isinstance(node, ast.Name) and node.id == "user_action"):
                    out.append(((m, q), ast.unparse(node)))
    return out


# the run-time guard: App.event (main marks an event run, the user's own
# switch lifts it), State.event_guard (App arms it) and App.no_event. Set
# only at these sites; anywhere else only made stricter (x.event = True,
# x.state.event_guard = x.no_event)
GUARD_ATTRS = {"event", "event_guard", "no_event"}
SWITCH_SITES = {("core", "main"), ("core", "App.user_action"), ("core", "App.__init__"),
                ("core", "State.__init__")}


def _stricter(target, value):
    return ((target.attr == "event" and isinstance(value, ast.Constant) and value.value is True)
            or (target.attr == "event_guard" and isinstance(value, ast.Attribute)
                and value.attr == "no_event"))


def event_switches(mods):
    """The run-time guard switched off or swapped outside SWITCH_SITES, in
    any function of the package (reached from an event or not): an
    assignment, an augmented one or a del of .event, .event_guard or
    .no_event, setattr/delattr with that name, x["event"] = .. (vars(),
    __dict__) and any __dict__ or vars() of an object. [(site, text)]"""
    out = []

    def bad(site, node):
        out.append((site, ast.unparse(node)))

    def attrs(t):
        if isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                yield from attrs(e)
        elif isinstance(t, ast.Starred):
            yield from attrs(t.value)
        elif isinstance(t, ast.Attribute) and t.attr in GUARD_ATTRS:
            yield t

    def check(site, root):
        if site in SWITCH_SITES:
            return
        for node in ast.walk(root):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    for a in attrs(t):
                        if not (a is t and _stricter(a, node.value)):
                            bad(site, node)
                    if (isinstance(t, ast.Subscript)
                            and _str_value(t.slice) in GUARD_ATTRS):
                        bad(site, node)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                if list(attrs(node.target)) or (isinstance(node.target, ast.Subscript)
                                                and _str_value(node.target.slice) in GUARD_ATTRS):
                    bad(site, node)
            elif isinstance(node, ast.Delete):
                if any(list(attrs(t)) for t in node.targets):
                    bad(site, node)
            elif isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if name in ("setattr", "delattr", "__setattr__", "__delattr__") and \
                        len(node.args) >= 2 and _str_value(node.args[1]) in GUARD_ATTRS | {None}:
                    bad(site, node)
                elif name == "vars" or any(k.arg in GUARD_ATTRS for k in node.keywords
                                           if name == "update"):
                    bad(site, node)
            elif isinstance(node, ast.Attribute) and node.attr == "__dict__":
                bad(site, node)

    for m, tree in sorted(mods.items()):
        tops = set()
        for q, fn in _functions(tree):
            tops.add(id(fn))
            check((m, q), fn)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for c in node.body:
                    if id(c) not in tops:
                        check((m, node.name), c)
            elif id(node) not in tops:
                check((m, "<module>"), node)
    return out


# what writes bytes to a file
WRITERS = {"_inplace_write", "_atomic_write", "write", "write_bytes", "write_text"}


def restores(mods, nodes):
    """An original written back by hand (a revert outside the sinks): a
    write whose data is backup_bytes(..), directly or through a variable.
    [(node, text)]"""
    def reads_backup(e):
        return any(isinstance(c, ast.Call) and (
            getattr(c.func, "attr", None) == "backup_bytes"
            or getattr(c.func, "id", None) == "backup_bytes") for c in ast.walk(e))
    out = []
    for m, q in sorted(nodes):
        if m not in mods:
            continue
        fn = _function(mods, m, q)
        tainted = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and reads_backup(node.value):
                tainted.update(t.id for t in node.targets if isinstance(t, ast.Name))
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name not in WRITERS:
                continue
            for a in list(node.args) + [k.value for k in node.keywords]:
                if reads_backup(a) or any(isinstance(c, ast.Name) and c.id in tainted
                                          for c in ast.walk(a)):
                    out.append(((m, q), ast.unparse(node)))
                    break
    return out


def _files_subscript(node, keys=("files",)):
    """node is X["files"] or X.get("files", ..) (an owner's records); with
    keys ("files", "owners"), the owners too (X["owners"], X.owners)."""
    if isinstance(node, ast.Subscript):
        return _str_value(node.slice) in keys
    if isinstance(node, ast.Attribute) and "owners" in keys:
        return node.attr == "owners"
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get" and bool(node.args) and _str_value(node.args[0]) in keys)


RECORDS = ("files", "owners")


def _empty_owner(node):
    """A dict literal of an owner with no file: {"files": {}}."""
    return isinstance(node, ast.Dict) and any(
        _str_value(k) == "files" and isinstance(v, ast.Dict) and not v.keys
        for k, v in zip(node.keys, node.values) if k is not None)


# the event-path functions allowed to forget a record: none (remove_owner,
# _revert_stale and the restore and rescue commands are sinks or typed)
FORGET_SITES = set()


def forgets(mods, nodes):
    """Records forgotten in a function of nodes: a file's or a whole
    owner's: X["files"].pop(..), .clear(), .popitem(), del X["files"][..],
    the same on X.owners / X["owners"], X["files"] = .., X["owners"] = ..,
    X.owners = .., X.data = .. and an owner made again empty
    (o = {"files": {}}). [(node, text)]"""
    out = []
    for m, q in sorted(nodes):
        if m not in mods or (m, q) in FORGET_SITES:
            continue
        for node in ast.walk(_function(mods, m, q)):
            f = getattr(node, "func", None)
            if (isinstance(node, ast.Call) and isinstance(f, ast.Attribute)
                    and f.attr in ("pop", "clear", "popitem")
                    and _files_subscript(f.value, RECORDS)):
                out.append(((m, q), ast.unparse(node)))
            elif isinstance(node, ast.Delete) and any(
                    isinstance(t, ast.Subscript) and _files_subscript(t.value, RECORDS)
                    for t in node.targets):
                out.append(((m, q), ast.unparse(node)))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any((isinstance(t, ast.Subscript) and _str_value(t.slice) in RECORDS)
                       or (isinstance(t, ast.Attribute) and t.attr in ("owners", "data"))
                       for t in targets) or _empty_owner(node.value):
                    out.append(((m, q), ast.unparse(node)))
    return out


def remove_argv(mods, nodes):
    """In a function of nodes: a list or tuple literal holding "remove" (an
    argv for appglass remove, plugin remove or hook remove), a string that is
    a sink's name ("remove", "remove_owner": getattr, an argv word kept in a
    variable) and a command line string with a remove word in a call that
    runs one (os.system("appglass remove")). The parser's own words (its
    subcommands and choices, args.cmd == "remove") are not. [(node, text)]"""
    out = []
    for m, q in sorted(nodes):
        if m not in mods:
            continue
        fn = _function(mods, m, q)
        names = _str_names(fn)
        skip = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Compare):
                # the compared words themselves (args.cmd in ("apply",
                # "remove")), not a call compared (run([.., "remove"]).returncode)
                for c in [node.left] + node.comparators:
                    skip.add(id(c))
                    if isinstance(c, (ast.Tuple, ast.List, ast.Set)):
                        skip.update(id(e) for e in c.elts)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in PARSER_CALLS):
                skip.update(id(n) for a in node.args[:1] for n in ast.walk(a))
                skip.update(id(n) for k in node.keywords if k.arg == "choices"
                            for n in ast.walk(k.value))
        for node in ast.walk(fn):
            if id(node) in skip:
                continue
            if isinstance(node, (ast.List, ast.Tuple)) and any(
                    _str_value(e, names) == "remove" for e in node.elts):
                out.append(((m, q), ast.unparse(node)))
            elif (isinstance(node, (ast.Constant, ast.BinOp, ast.Call))
                    and _str_value(node, names) in SINK_NAMES):
                out.append(((m, q), repr(_str_value(node, names))))
            elif isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if not RUNNERS.fullmatch(name):
                    continue
                for a in list(node.args) + [k.value for k in node.keywords]:
                    for c in ast.walk(a):
                        if (isinstance(c, ast.Constant) and isinstance(c.value, str)
                                and c.value != "remove"
                                and re.search(r"\bremove\b", c.value)):
                            out.append(((m, q), ast.unparse(node)))
    return out


def py_violations(sources=None):
    """What an event entry reaches that takes something out: the sinks
    reached (besides the allowed edges) and the remove argv literals."""
    mods = _modules(sources)
    graph = call_graph(mods)
    seen = reach(graph, PY_ROOTS, allowed_edges(mods, graph))
    return sorted(seen & PY_SINKS), (remove_argv(mods, seen) + deletes(mods, seen)
                                     + forgets(mods, seen) + restores(mods, seen)
                                     + user_actions(mods) + event_switches(mods))


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

    def test_the_sweep_allows_its_own_argv_only(self):
        # the real UninstallSweep.qml passes; a second remove argv planted in
        # its teardown is still a violation
        src = plugin_sources()
        path, root = SWEEP_ROOT
        self.assertIn(SWEEP_SINK, src[path])
        self.assertEqual([h for h in qml_violations(src) if h[0] == path], [])
        teardown = "    Component.onDestruction: {\n"
        self.assertEqual(src[path].count(teardown), 1)
        plant = teardown + '        Proc.runCommand("x", [sweep.rescue, "remove"], null);\n'
        hits = qml_violations(dict(src, **{path: src[path].replace(teardown, plant)}))
        self.assertEqual([(p, r) for p, r, _ in hits], [(path, root)], hits)

    def test_checker_catches_declared_and_built_argvs(self):
        # a remove argv in a declaration (a Process object, a property) run
        # from the teardown, and an argv built from a " remove" string
        src = plugin_sources()
        path = os.path.join("components", "DaemonBody.qml")
        body = src[path]
        teardown = "    Component.onDestruction: {\n"
        plants = (
            '    Process { id: wipe; command: [root.bin, "remove"] }\n'
            + teardown + '        wipe.running = true;\n',
            '    property var wipeArgv: [root.bin, "remove"]\n'
            + teardown + '        Proc.runCommand("x", root.wipeArgv, null);\n',
            teardown + '        Proc.runCommand("x", (root.bin + " remove").split(" "), null);\n',
            teardown + '        Quickshell.execDetached(["sh", "-c", root.bin + " remove"]);\n',
            teardown + '        const verb = "remove";\n        Proc.runCommand("x", [root.bin].concat(verb), null);\n',
            # a remove word put together from literals
            teardown + '        Proc.runCommand("x", Logic.cliArgv(root.bin, ["re" + "move"]), null);\n',
            teardown + "        Proc.runCommand('x', [root.bin, 'rem' + 'ov' + 'e'], null);\n",
        )
        for plant in plants:
            with self.subTest(plant=plant):
                hits = qml_violations(dict(src, **{path: body.replace(teardown, plant)}))
                self.assertTrue([h for h in hits if h[0] == path], plant)

    def test_checker_follows_a_logic_helper_that_builds_the_argv(self):
        # logic.js with a helper that concatenates the remove word, called
        # from the teardown: the helper's body is followed and folded
        src = plugin_sources()
        path = os.path.join("components", "DaemonBody.qml")
        lpath = os.path.join("components", "logic.js")
        teardown = "    Component.onDestruction: {\n"
        helper = ('\nfunction wipeArgv(bin) {\n    return [bin, "re" + "move"];\n}\n')
        planted = dict(src, **{
            lpath: src[lpath] + helper,
            path: src[path].replace(teardown, teardown
                                    + '        Proc.runCommand("x", Logic.wipeArgv(root.bin), null);\n')})
        hits = qml_violations(planted)
        self.assertEqual([(p, r) for p, r, _ in hits], [(path, "Component.onDestruction")], hits)

    def test_checker_follows_references_not_only_calls(self):
        # plants a grep for "name(" misses: a function handed over, not
        # called (callLater, connect, a handler that is a bare name); a
        # second function of the same name; logic.js through another name;
        # runAction kept in a variable
        logic = ('function wipe(bin) {\n    return [bin, "re" + "move"];\n}\n'
                 'function safe() {\n    return 1;\n}\n')
        plants = {
            "later.qml": "Item {\n    Timer {\n        onTriggered: Qt.callLater(root.cleanup)\n    }\n"
                         "    function cleanup() { root.launchRemove(); }\n}\n",
            "connect.qml": "Item {\n    Component.onCompleted: root.closing.connect(cleanup)\n"
                           "    function cleanup() { root.launchRemove(); }\n}\n",
            "bare.qml": "Item {\n    Timer {\n        onTriggered: cleanup\n    }\n"
                        "    function cleanup() { root.launchRemove(); }\n}\n",
            "shadow.qml": "Item {\n    Item {\n        function cleanup() { return 0; }\n    }\n"
                          "    Component.onDestruction: cleanup()\n"
                          "    function cleanup() { root.launchRemove(); }\n}\n",
            "alias.qml": "Item {\n    Component.onDestruction: {\n        const L = Logic;\n"
                         "        Proc.runCommand(\"x\", L.wipe(root.bin), null);\n    }\n}\n",
            "index.qml": "Item {\n    Component.onDestruction: {\n"
                         "        Proc.runCommand(\"x\", Logic[\"wipe\"](root.bin), null);\n    }\n}\n",
            "held.qml": "Item {\n    Timer {\n        onTriggered: {\n"
                        "            const go = root.runAction;\n            go(\"uninstall\");\n"
                        "        }\n    }\n}\n",
            # none of these reaches anything: no hit
            "fine.qml": "Item {\n    Component.onCompleted: { Logic.safe(); root.ok(); }\n"
                        "    function ok() { return \"cleanup\"; }\n"
                        "    function cleanup() { root.launchRemove(); }\n    // cleanup in a comment\n}\n",
        }
        for name, text in plants.items():
            with self.subTest(plant=name):
                hits = {p for p, _, _ in qml_violations({"logic.js": logic, name: text})}
                self.assertEqual(hits, set() if name == "fine.qml" else {name})


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
        self.assertIn(("core", "App._revert_stale"), g[("core", "App.commit")])
        self.assertIn(("core", "App._revert"), g[("core", "App._revert_stale")])
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
            # the dispatcher and the lock release run on every event too
            ("core", "main", "if args.from_hook: cmd_remove(app)"),
            ("core", "main", "if args.from_hook: hook.remove(app)"),
            ("core", "_unlock", "app.state.destroy()"),
            # a sink named, not referenced
            ("core", "cmd_sync", "getattr(hook, 'remove')(app)"),
            ("core", "cmd_sync", "getattr(app, 'remove_owner')('hook')"),
            # a remove command built, not written as a list
            ("vibrancy", "run", "a = 'remove'; subprocess.run([sys.argv[0], a])"),
            ("vibrancy", "run", "os.system('appglass remove')"),
            ("vibrancy", "run", "os.system('%s remove' % sys.argv[0])"),
            # the remove word put together from literals
            ("vibrancy", "run", "subprocess.run([sys.argv[0], 're' + 'move'])"),
            ("core", "cmd_sync", "getattr(app, 'remove' + '_owner')('hook')"),
            ("core", "cmd_sync", "subprocess.run([sys.argv[0], ''.join(['re', 'move'])])"),
            # files or the state dir taken out by hand, not through a sink
            ("core", "cmd_apply_all", "shutil.rmtree(app.env.state_dir)"),
            ("core", "cmd_apply_all", "os.remove(app.state.path)"),
            ("core", "cmd_apply_all",
             "[os.remove(p) for o in app.state.owners.values() for p in o['files']]"),
            ("core", "cmd_sync", "os.unlink(app.state.path)"),
            # in commit, the write path of every event: a file deleted by
            # hand, a record forgotten
            ("core", "App.commit", "os.remove(next(iter(ctx.ops)))"),
            ("core", "App.commit",
             "self.state.owners[ctx.owner]['files'].pop(next(iter(ctx.ops)))"),
            ("core", "App.commit", "del self.state.owners[ctx.owner]['files'][ctx.order[0]]"),
            ("core", "cmd_sync", "app.state.owners['niri'].get('files', {}).clear()"),
            # a whole owner forgotten
            ("core", "cmd_apply_all", "app.state.owners.pop('obsidian', None)"),
            ("core", "cmd_apply_all", "del app.state.owners['obsidian']"),
            ("core", "cmd_apply_all", "app.state.data['owners'] = {}"),
            ("core", "App.commit", "self.state.owners[ctx.owner]['files'] = {}"),
            ("core", "App.commit", "owner = {'files': {}}"),
            # deleted by a move, a rename, a Path or an alias of os
            ("core", "cmd_apply_all", "os.rename(app.state.path, app.state.path + '.x')"),
            ("core", "cmd_apply_all", "os.replace(app.state.path, '/dev/null')"),
            ("core", "cmd_apply_all", "shutil.move(app.state.path, '/tmp')"),
            ("core", "cmd_apply_all", "pathlib.Path(app.state.path).unlink()"),
            ("core", "cmd_apply_all", "_o = os; _o.remove(app.state.path)"),
            # the user's own switch taken outside its two sites
            ("core", "cmd_apply_all", "with app.user_action(): app._drop_backup({})"),
            # a remove word built from a variable
            ("vibrancy", "run", "w = 're'; subprocess.run([sys.argv[0], w + 'move'])"),
            # a revert done by writing an original back
            ("core", "App.commit", "_inplace_write(next(iter(ctx.ops)), self.backup_bytes({}))"),
            ("core", "App.commit", "orig = self.backup_bytes({}); _atomic_write('x', orig)"),
            # the typed restore and rescue
            ("core", "cmd_apply_all", "cmd_rescue(app)"),
            ("core", "cmd_apply_all", "cmd_restore(app)"),
            # the run-time guard switched off (S6: only main and the user's
            # own switch set App.event; nothing but State and App set the
            # save guard): anywhere, reached from an event or not
            ("core", "cmd_sync", "app.event = False"),
            ("core", "cmd_sync", "app.event = 0"),
            ("verify", "cmd_keys", "app.event = False"),
            ("core", "App.commit", "self.state.event_guard = None"),
            ("core", "cmd_sync", "app.state.event_guard = lambda what: None"),
            ("core", "cmd_sync", "app.event, x = False, 1"),
            ("core", "cmd_sync", "app.event &= False"),
            ("core", "cmd_sync", "del app.state.event_guard"),
            ("core", "cmd_sync", "setattr(app, 'event', False)"),
            ("core", "cmd_sync", "setattr(app.state, 'event_' + 'guard', None)"),
            ("core", "cmd_sync", "vars(app)['event'] = False"),
            ("core", "cmd_sync", "app.__dict__.update(event=False)"),
            ("core", "cmd_sync", "app.no_event = print"),
            ("core", "cmd_sync", "core.App.no_event = lambda self, what: None"),
            ("engine", "store", "app.event = False"),
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

    def test_the_guard_may_be_made_stricter_anywhere(self):
        src = py_sources()
        for mod, func, line in (("core", "cmd_sync", "app.event = True"),
                                ("verify", "cmd_keys", "app.state.event_guard = app.no_event")):
            with self.subTest(line=line):
                self.assertEqual(event_switches(_modules(plant(src, mod, func, line))), [])
        self.assertEqual(event_switches(self.mods), [])

    def test_checker_catches_a_guard_taken_out(self):
        src = py_sources()
        for mod, old, new in (
                ("core", "if not self.event:", "if True:"),
                ("core", "if name in app.state.owners and _user_removes(app, why, name):",
                 "if name in app.state.owners:"),
                ("niri", 'if "niri" in app.state.owners and not dry_run and not app.event:',
                 'if "niri" in app.state.owners and not dry_run:'),
                ("niri", "if ok is False and not app.event:", "if ok is False:"),
                ("core", 'elif args.cmd == "remove":', "elif True:"),
                ("core", "if not (st.owners or st.data.get(\"parked\") or app.keep_state_dir) "
                 "and not app.event and (", "if not (st.owners or st.data.get(\"parked\") "
                 "or app.keep_state_dir) and (")):
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
