"""appglass plugin install|remove: the DMS plugin as a symlink.

    $XDG_CONFIG_HOME/dms/plugins/appGlass -> <repository>/dms-plugin

The plugin runs bin/appglass of the repository its folder points into, so
the link (not a copy) keeps the two in step. Install refuses a folder or a
link to somewhere else that is already there; remove takes out only a link
to this repository's dms-plugin. Neither touches state.json: the link holds
no user file, and ``appglass remove`` leaves it (the plugin's own switch
and DMS's plugin list are where it is turned off). The folders install made
for the link (no dms/plugins yet) are named in a dot file beside it, which
DMS does not list; remove takes them out again once they are empty.
"""

import json
import os

from . import settings as _settings


def source():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "dms-plugin")


def target(env):
    return _settings.plugin_dir(env)


def _ours(path):
    return os.path.islink(path) and os.path.realpath(path) == os.path.realpath(source())


def install(app, dry_run=False):
    from .core import AppglassError
    env, src, dst = app.env, source(), target(app.env)
    if not os.path.isfile(os.path.join(src, "plugin.json")):
        raise AppglassError("plugin: %s/plugin.json is missing" % src)
    if _ours(dst):
        app.info("plugin: %s already links to %s" % (env.tilde(dst), src))
        return
    if os.path.lexists(dst):
        what = "a link to %s" % os.readlink(dst) if os.path.islink(dst) else "a folder"
        raise AppglassError("plugin: %s is %s, not this repository's plugin: left as is "
                            "(move it away first)" % (env.tilde(dst), what))
    env.guard(dst)
    if dry_run:
        app.info("plugin: would link %s -> %s" % (env.tilde(dst), src))
        return
    from .core import _missing_dirs
    made = _missing_dirs(os.path.dirname(dst))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.symlink(src, dst)
    if made:
        with open(_made_file(dst), "w") as f:
            f.write("\n".join(made) + "\n")
    app.info("plugin: linked %s -> %s" % (env.tilde(dst), src))
    app.info("plugin: enable App Glass in DMS Settings > Plugins (scan for plugins "
             "if it is not listed)")


def remove(app, dry_run=False):
    from .core import AppglassError
    if not dry_run:
        app.no_event("take the plugin link out")
    env, dst = app.env, target(app.env)
    if not os.path.lexists(dst):
        app.info("plugin: not installed (%s)" % env.tilde(dst))
        return
    if not _ours(dst):
        raise AppglassError("plugin: %s is not a link to this repository's plugin: left "
                            "as is" % env.tilde(dst))
    env.guard(os.path.dirname(dst))
    if dry_run:
        app.info("plugin: would remove the link %s" % env.tilde(dst))
        return
    os.unlink(dst)
    _drop_made(env, dst)
    app.info("plugin: removed the link %s%s" % (
        env.tilde(dst), " (the glass files stay: appglass remove takes them out)"
        if _glass_recorded(env) else ""))


def _made_file(dst):
    return os.path.join(os.path.dirname(dst), ".appglass-made")


def _drop_made(env, dst):
    """The folders install made for the link, once only the dot file
    naming them is left in them."""
    mark = _made_file(dst)
    parent = os.path.dirname(dst)
    try:
        with open(mark) as f:
            made = [d for d in f.read().splitlines() if d]
        if os.listdir(parent) != [os.path.basename(mark)]:
            return      # another plugin (or the user's file) is in it: kept
    except OSError:
        return
    env.guard(mark)
    os.remove(mark)
    for d in sorted(made, key=len, reverse=True):
        if d == parent or parent.startswith(d.rstrip(os.sep) + os.sep):
            env.guard(d)
            try:
                os.rmdir(d)
            except OSError:
                break


def _glass_recorded(env):
    """state.json records files appglass wrote (or cannot be read)."""
    p = os.path.join(env.state_dir, "state.json")
    if not os.path.lexists(p):
        return False
    try:
        with open(p) as f:
            owners = json.load(f).get("owners") or {}
        return any((o or {}).get("files") for o in owners.values())
    except (OSError, ValueError, AttributeError):
        return True
