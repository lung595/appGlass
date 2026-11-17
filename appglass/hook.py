"""matugen hook: re-render the colours and re-apply on every DMS theme change.

``appglass hook install`` adds a ``[templates.appglass]`` section to the user
matugen config, $XDG_CONFIG_HOME/matugen/config.toml (created when missing,
backed up and appended to when it exists). DMS runs the user's matugen
templates after its own (``dms matugen generate/queue``, with
``--run-user-templates``, the default, "Run user templates" in the DMS theme
settings). matugen then renders templates/colors.json to
$XDG_STATE_HOME/appglass/colors.json and runs the post_hook,
``bin/appglass apply --from-hook --quiet``: it re-applies only the families
recorded in state.json (applied and not removed since), and does nothing
before the first ``appglass apply``. Installing over an older hook section
(any post_hook string) replaces it.

It also installs the sync units: shims/sync/appglass-sync.path and
.service, verbatim, in ~/.config/systemd/user, and ~/.local/bin/appglass-sync,
which execs the repo's bin/appglass-sync. The path unit fires when the DMS
window rules (the opacity) or the DMS colours change; the script runs
``appglass apply --from-hook --list-changed`` and nudges Herdr and GTK only
when one of their files changed. appglass-discord.path/.service watch
~/.config/discord (Discord writes there all the time): the script, with
--discord, exits at once unless the newest Discord host dir lacks Vencord,
and only then puts it back (while the vencord family is applied) and
re-applies. Also shims/sync/appglass-vibrancy.service and
~/.local/bin/appglass-vibrancy (``bin/appglass vibrancy``, the Alacritty
inactive fade, appglass/vibrancy.py). Then ``systemctl --user daemon-reload``,
``enable --now`` the two path units and ``enable`` + ``restart``
appglass-vibrancy.service (not in a sandbox, unless $APPGLASS_SYSTEMCTL names
a stand-in). Hand-made units and script are Conflicts until ``appglass adopt``.

``appglass hook remove`` restores the matugen config byte-identical, drops
the rendered colors.json, restores (or deletes) the units and the script and
disables the path units and the vibrancy service again when they were not
enabled before install.
"""

import json
import os
import re
import shlex
import subprocess

from .core import Conflict

BEGIN = "# >>> appglass hook (appglass hook remove takes it out) >>>"
END = "# <<< appglass hook <<<"
HOOK_ARGS = "apply --from-hook --quiet"
_BLOCK = re.compile(r"(?ms)^\n?" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?")


UNITS = ("appglass-sync.path", "appglass-sync.service", "appglass-vibrancy.service",
         "appglass-discord.path", "appglass-discord.service")
PATH_UNIT = UNITS[0]
VIBRANCY_UNIT = UNITS[2]
DISCORD_UNIT = UNITS[3]
# (state key, unit, the systemctl calls of install); remove disables a unit
# that was not enabled before install
ENABLED = (("was_enabled", PATH_UNIT, (("enable", "--now"),)),
           ("discord_was_enabled", DISCORD_UNIT, (("enable", "--now"),)),
           # restart: a running daemon picks up new code from the repo
           ("vibrancy_was_enabled", VIBRANCY_UNIT, (("enable",), ("restart",))))


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def template_path():
    return os.path.join(repo_root(), "templates", "colors.json")


def bin_path():
    return os.path.join(repo_root(), "bin", "appglass")


def sync_script():
    return os.path.join(repo_root(), "bin", "appglass-sync")


def unit_path(env, name):
    return env.config_path("systemd", "user", name)


def sync_path(env):
    return env.home_path(".local", "bin", "appglass-sync")


def vibrancy_path(env):
    return env.home_path(".local", "bin", "appglass-vibrancy")


def vibrancy_shim(env):
    from . import shims
    return ("#!/bin/sh\n"
            "# appglass-vibrancy: written by appglass hook install (appglass hook remove\n"
            "# takes it out); run by appglass-vibrancy.service.\n"
            'exec "%s" vibrancy "$@"\n' % shims.appglass_cmd(env, bin_path()))


def sync_shim(env):
    from . import shims
    return ("#!/bin/sh\n"
            "# appglass-sync: written by appglass hook install (appglass hook remove\n"
            "# takes it out); run by appglass-sync.service.\n"
            'exec "%s" "$@"\n' % shims.appglass_cmd(env, sync_script()))


def systemctl(env):
    """systemctl, or None in a sandbox (unless $APPGLASS_SYSTEMCTL is set)."""
    if env.sandbox is not None:
        return env.environ.get("APPGLASS_SYSTEMCTL") or None
    return env.which("systemctl")


def _ctl(app, *args):
    tool = systemctl(app.env)
    if not tool:
        return None
    try:
        return app.env.run([tool, "--user"] + list(args), timeout=60)
    except (OSError, subprocess.TimeoutExpired) as ex:
        app.warn("hook: systemctl %s: %s" % (" ".join(args), ex))
        return None


def config_path(env):
    return env.config_path("matugen", "config.toml")


def output_path(env):
    return os.path.join(env.state_dir, "colors.json")


def _toml_str(s):
    # TOML basic strings accept JSON string escapes
    return json.dumps(s)


def section(env):
    hook = "%s %s" % (shlex.quote(bin_path()), HOOK_ARGS)
    return "\n".join([
        BEGIN,
        "[templates.appglass]",
        "input_path = %s" % _toml_str(template_path()),
        "output_path = %s" % _toml_str(output_path(env)),
        "post_hook = %s" % _toml_str(hook),
        END,
        "",
    ])


def add(text, block):
    if BEGIN in text:
        return _BLOCK.sub(lambda m: ("\n" if m.group(0).startswith("\n") else "") + block, text, 1)
    if not text.strip():
        return "[config]\n\n" + block
    if not text.endswith("\n"):
        text += "\n"
    return text + "\n" + block


def strip(text):
    return _BLOCK.sub("", text, 1)


def undo_for(app, path):
    if os.path.abspath(path) == config_path(app.env):
        return strip
    return None


def installed(app):
    """hook install ran (its matugen section is recorded), not only adopt."""
    o = app.state.owners.get("hook")
    return bool(o) and config_path(app.env) in o.get("files", {})


def hand_sync_live(app):
    """A hand-made ~/.local/bin/appglass-sync, not replaced by hook install
    (nor about to be, in an adopt dry run): it still runs the hand pieces."""
    if installed(app) or getattr(app, "hook_planned", False):
        return False
    return os.path.lexists(sync_path(app.env))


def record_enabled(app, sd):
    """Fill in sd[key] (was the unit enabled?) for every unit not known yet;
    nothing without systemctl. Returns sd."""
    if systemctl(app.env):
        for key, unit, _ in ENABLED:
            if key not in sd:
                r = _ctl(app, "is-enabled", "--quiet", unit)
                sd[key] = r is not None and r.returncode == 0
    return sd


def unit_render(name):
    """The repo's bytes of a sync unit (installed verbatim)."""
    with open(os.path.join(repo_root(), "shims", "sync", name), "rb") as f:
        return f.read()


def plan(app, ctx=None):
    """What hook install writes, planned in a ctx (doctor compares it with
    the disk). Raises Conflict for a hand-made unit or script."""
    env = app.env
    ctx = ctx or app.ctx("hook")
    block = section(env)
    ctx.edit_text(config_path(env), lambda t: add(t, block), undo=strip)
    for n in UNITS:
        ctx.write_owned(unit_path(env, n), unit_render(n), mode=0o644)
    ctx.write_owned(sync_path(env), sync_shim(env), mode=0o755)
    ctx.write_owned(vibrancy_path(env), vibrancy_shim(env), mode=0o755)
    return ctx


def install(app, dry_run=False):
    from .core import refuse_orphans
    env = app.env
    refuse_orphans(app)
    for p in (template_path(), bin_path()):
        if not os.path.exists(p):
            app.error("hook: %s is missing" % p)
            return
    try:
        ctx = plan(app)
    except Conflict as ex:
        app.error("hook: %s (appglass adopt takes the hand-made sync files over)" % ex)
        return
    had = "hook" in app.state.owners
    tool = systemctl(env)
    if dry_run:
        changed = app.commit(ctx, dry_run=True)
        for p in changed:
            app.info("hook: would %s %s" % ("write" if os.path.lexists(p) else "create",
                                           env.tilde(p)))
        if not changed:
            app.info("hook: already installed in %s" % config_path(env))
        app.info("hook: would run systemctl --user daemon-reload, %s"
                 % ", ".join(" ".join(c + (u,)) for _, u, calls in ENABLED for c in calls)
                 if tool else "hook: systemctl skipped (sandbox)")
        return changed
    sd = record_enabled(app, dict((app.state.owners.get("hook") or {}).get("systemd") or {}))
    changed = app.commit(ctx)
    o = app.state.owners.get("hook")
    if o is not None and tool and o.get("systemd") != sd:
        o["systemd"] = sd
        app.state.save()
    if tool:
        _ctl(app, "daemon-reload")
        for _, unit, calls in ENABLED:
            for c in calls:
                args = c + (unit,)
                r = _ctl(app, *args)
                if r is not None and r.returncode != 0:
                    app.warn("hook: systemctl %s failed: %s"
                             % (" ".join(args), (r.stderr or r.stdout).strip()))
        app.info("hook: %s enabled" % ", ".join(u for _, u, _ in ENABLED))
    else:
        app.info("hook: systemctl skipped (sandbox): %s not enabled"
                 % ", ".join(u for _, u, _ in ENABLED))
    if changed:
        app.info("hook: %s in %s" % ("updated" if had else "installed", config_path(env)))
    else:
        app.info("hook: already installed in %s" % config_path(env))
    app.info("hook: matugen renders %s, then runs %s %s"
             % (output_path(env), bin_path(), HOOK_ARGS))
    return changed


def remove(app):
    from .core import refuse_orphans
    env = app.env
    refuse_orphans(app)
    out = output_path(env)
    o = app.state.owners.get("hook") or {}
    sd = o.get("systemd") or {}
    recs = {n: o.get("files", {}).get(unit_path(env, n)) for n in UNITS}
    for key, unit, _ in ENABLED:
        # disabled when its file goes (appglass created it) or it was off
        # before install; stopping the vibrancy daemon puts back the
        # Alacritty windows it faded
        rec = recs[unit]
        if (rec is not None and rec.get("kind") == "created") or sd.get(key) is False:
            _ctl(app, "disable", "--now", unit)
    removed = app.remove_owner("hook")
    if removed and any(recs.values()):
        _ctl(app, "daemon-reload")      # unit files deleted or restored
    if os.path.exists(out):
        env.guard(out)
        os.remove(out)
    app.info("hook: removed" if removed else "hook: not installed")
