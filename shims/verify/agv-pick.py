"""appglass verify: pick the app's window in the hidden session.

    agv-pick.py APID APPID_REGEX < `niri msg -j windows`

Prints "<window id> <app-id>" of the first window that is the app's, or
nothing. In this order: a window of APID (the launcher the harness started)
or of a child of it; a window of a process that carries the private
XDG_RUNTIME_DIR (it left the tree: double-forked, D-Bus activated); a
window whose app-id matches APPID_REGEX (a single-instance hand-off). An
app often names its window after its binary, not its launcher
(org.example.FnGtk2 shows "gtkfn"), so the app-id alone misses it.
AGV_PROC: another /proc (tests).
"""

import json
import os
import re
import sys


def parents(proc):
    out = {}
    try:
        names = os.listdir(proc)
    except OSError:
        return out
    for n in names:
        if not n.isdigit():
            continue
        try:
            with open(os.path.join(proc, n, "stat")) as f:
                out[int(n)] = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
    return out


def tree(proc, root):
    kids = {}
    for c, p in parents(proc).items():
        kids.setdefault(p, []).append(c)
    seen, todo = {root}, [root]
    while todo:
        for c in kids.get(todo.pop(), ()):
            if c not in seen:
                seen.add(c)
                todo.append(c)
    return seen


def ours(proc, pid, rt):
    if not rt:
        return False
    try:
        with open(os.path.join(proc, str(pid), "environ"), "rb") as f:
            return ("XDG_RUNTIME_DIR=" + rt).encode() in f.read().split(b"\0")
    except OSError:
        return False


def main(argv):
    apid, rx = int(argv[1]), argv[2]
    proc = os.environ.get("AGV_PROC") or "/proc"
    rt = os.environ.get("XDG_RUNTIME_DIR") or ""
    try:
        ws = [w for w in json.load(sys.stdin) if isinstance(w, dict) and "id" in w]
    except ValueError:
        return 0
    mine = tree(proc, apid)
    tests = (lambda w: w.get("pid") in mine,
             lambda w: isinstance(w.get("pid"), int) and ours(proc, w["pid"], rt),
             lambda w: bool(re.search(rx, w.get("app_id") or "")))
    for t in tests:
        for w in ws:
            if t(w):
                print("%s %s" % (w["id"], w.get("app_id") or ""))
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
