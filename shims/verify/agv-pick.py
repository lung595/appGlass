"""appglass verify: pick the app's window in the hidden session.

    agv-pick.py APID APPID_REGEX < `niri msg -j windows`

Prints "<window id> <app-id>" of the app's own main window, or nothing
(the harness polls again; no window at the end is unverifiable). A window
is the app's when it is of APID (the launcher the harness started) or a
child of it, or of a process that carries the private XDG_RUNTIME_DIR (it
left the tree: double-forked, D-Bus activated), or when its app-id matches
APPID_REGEX (a single-instance hand-off). An app often names its window
after its binary, not its launcher (org.example.FnGtk2 shows "gtkfn"), so
the app-id alone misses it. In this order: a tiled window of ours whose
app-id matches; a tiled window of ours; a tiled window whose app-id
matches; a floating one whose app-id matches. A floating window of another
app-id (a dialog, a splash) and a helper dialog tool's window (zenity: the
Discord updater) are never measured.
AGV_PROC: another /proc (tests).
"""

import json
import os
import re
import sys

# dialog tools a launcher shows before (or instead of) the app
HELPERS = re.compile(r"^(zenity|org\.gnome\.Zenity|kdialog|org\.kde\.kdialog|yad|"
                     r"xmessage|gxmessage|Xdialog)$", re.I)


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
    ws = [w for w in ws if not HELPERS.match(w.get("app_id") or "")]

    def of_ours(w):
        return w.get("pid") in mine or (isinstance(w.get("pid"), int)
                                        and ours(proc, w["pid"], rt))

    def match(w):
        return bool(re.search(rx, w.get("app_id") or ""))

    def tiled(w):
        return not w.get("is_floating")

    tests = (lambda w: tiled(w) and match(w) and of_ours(w),
             lambda w: tiled(w) and of_ours(w),
             lambda w: tiled(w) and match(w),
             lambda w: match(w) and of_ours(w),
             match)
    for t in tests:
        for w in ws:
            if t(w):
                print("%s %s" % (w["id"], w.get("app_id") or ""))
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
