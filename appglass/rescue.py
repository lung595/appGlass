"""The rescue copy of the CLI: $XDG_DATA_HOME/appglass/cli.

A registry install of the DMS plugin clones the whole repository into
~/.config/dms/plugins/.repos/<hash>/ and links its dms-plugin folder; a DMS
uninstall deletes that clone, and with it the CLI that could take the glass
files out. ``appglass hook install`` keeps a copy of what ``appglass
remove`` needs (bin/appglass and the appglass package, no __pycache__),
``appglass sync`` and a typed ``appglass apply`` refresh it when it differs from the running CLI (the
version and the size and mtime of every file, in MANIFEST), and a full
``appglass remove`` and ``appglass hook remove`` take it out. The plugin's
sweep runs ``python3 -I -B <copy>/bin/appglass remove --if-gone
<plugin.json>`` once its folder is gone. It is no file of the state: no
record, no backup (it holds nothing of the user's).

A copy is written in a temporary folder beside it, then renamed into
place: a half copy is never run.
"""

import importlib
import json
import os
import shutil
import tempfile

from . import __version__

MANIFEST = "MANIFEST.json"


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def path(env):
    return env.data_path("appglass", "cli")


def bin_path(env):
    return os.path.join(path(env), "bin", "appglass")


def sources(root):
    """The files of the copy, relative to root, sorted."""
    out = [os.path.join("bin", "appglass")]
    for dp, dns, fns in os.walk(os.path.join(root, "appglass")):
        dns[:] = sorted(d for d in dns if d != "__pycache__")
        out += [os.path.relpath(os.path.join(dp, f), root) for f in fns if f.endswith(".py")]
    return sorted(out)


def manifest(root):
    files = []
    for rel in sources(root):
        st = os.stat(os.path.join(root, rel))
        files.append([rel, st.st_size, st.st_mtime_ns])
    return {"version": __version__, "files": files}


def current(env, root):
    """The copy matches root's files."""
    try:
        with open(os.path.join(path(env), MANIFEST)) as f:
            return json.load(f) == manifest(root)
    except (OSError, ValueError):
        return False


def write(app, root=None):
    """Write the copy when it differs from root (default: this CLI). True
    when written. Never from the copy itself."""
    env = app.env
    root = root or repo_root()
    dest = path(env)
    if os.path.realpath(root) == os.path.realpath(dest) or current(env, root):
        return False
    parent = os.path.dirname(dest)
    env.guard(parent)
    os.makedirs(parent, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".cli-", dir=parent)
    try:
        for rel in sources(root):
            d = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(os.path.join(root, rel), d)
        with open(os.path.join(tmp, MANIFEST), "w") as f:
            json.dump(manifest(root), f)
        os.chmod(tmp, 0o755)
        old = None
        if os.path.lexists(dest):
            old = tempfile.mkdtemp(prefix=".cli-old-", dir=parent)
            os.rename(dest, os.path.join(old, "cli"))
        os.rename(tmp, dest)
        tmp = None
        if old:
            shutil.rmtree(old, ignore_errors=True)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return True


def drop(env):
    """Take the copy out (and its appglass folder, when left empty). True
    when there was one."""
    dest = path(env)
    if not os.path.lexists(dest):
        return False
    env.guard(dest)
    if os.path.realpath(repo_root()) == os.path.realpath(dest):
        # this run is the copy (the sweep): what it imports later must
        # already be loaded once its files are gone
        _import_all(dest)
    if os.path.islink(dest) or not os.path.isdir(dest):
        os.remove(dest)
    else:
        shutil.rmtree(dest)
    try:
        os.rmdir(os.path.dirname(dest))
    except OSError:
        pass
    return True


def _import_all(root):
    for rel in sources(root):
        if rel.startswith("appglass" + os.sep):
            name = rel[:-len(".py")].replace(os.sep, ".")
            if name.endswith(".__init__"):
                name = name[:-len(".__init__")]
            importlib.import_module(name)


def refresh(app):
    """hook install, sync and a typed apply: the copy kept in step, a failure only a warning
    (the glass does not depend on it)."""
    try:
        if write(app):
            app.info("rescue: %s updated" % app.env.tilde(path(app.env)))
    except OSError as ex:
        app.warn("rescue: cannot write %s: %s" % (app.env.tilde(path(app.env)), ex))
