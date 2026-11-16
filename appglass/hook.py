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

``appglass hook remove`` restores the matugen config byte-identical and drops
the rendered colors.json.
"""

import json
import os
import re
import shlex

BEGIN = "# >>> appglass hook (appglass hook remove takes it out) >>>"
END = "# <<< appglass hook <<<"
HOOK_ARGS = "apply --from-hook --quiet"
_BLOCK = re.compile(r"(?ms)^\n?" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?")


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def template_path():
    return os.path.join(repo_root(), "templates", "colors.json")


def bin_path():
    return os.path.join(repo_root(), "bin", "appglass")


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


def install(app):
    env = app.env
    for p in (template_path(), bin_path()):
        if not os.path.exists(p):
            app.error("hook: %s is missing" % p)
            return
    ctx = app.ctx("hook")
    block = section(env)
    ctx.edit_text(config_path(env), lambda t: add(t, block), undo=strip)
    had = "hook" in app.state.owners
    changed = app.commit(ctx)
    if changed:
        app.info("hook: %s in %s" % ("updated" if had else "installed", config_path(env)))
    else:
        app.info("hook: already installed in %s" % config_path(env))
    app.info("hook: matugen renders %s, then runs %s %s"
             % (output_path(env), bin_path(), HOOK_ARGS))


def remove(app):
    env = app.env
    out = output_path(env)
    removed = app.remove_owner("hook")
    if os.path.exists(out):
        env.guard(out)
        os.remove(out)
    app.info("hook: removed" if removed else "hook: not installed")
