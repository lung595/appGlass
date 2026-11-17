"""ck-shim: ArtCraft Launcher (artcraft-launcher, egui / winit / wgpu).

A forced adapter (off until apps.artcraft or apps.ai.storyteller.artcraft-launcher
is enabled). The wrapper moves the launcher from Vulkan to Mesa EGL + wgpu's
GL backend (llvmpipe) and LD_PRELOADs appglass-ck.so (built from shims/ck-shim
with gcc), which colour-keys the launcher's dark background colours to the
glass levels, drops the whole-window opaque region winit sends (with it the
window is glass when the launcher commits but dark when niri redraws it without
a commit: a blinking cursor flashes the whole window) and caps swaps at
APPGLASS_MAXFPS (60).

Files (owned; adopted hand files restored by remove):
  ~/.local/lib/appglass/artcraft/appglass-ck.so   (stamp: source + gcc)
  ~/.local/lib/appglass/artcraft/appglass-ck.c    its source, for reference
  ~/.local/bin/appglass-artcraft                  the launch wrapper (levels at launch)
  ~/.local/share/applications/ai.storyteller.artcraft-launcher.desktop -> the wrapper
"""

from .. import shims

NAME = "artcraft"
ADAPTER = "ck-shim"
OPT_IN = True
KEYS = ("ai.storyteller.artcraft-launcher",)
# the colour keys (the launcher is dark only), seeded into
# ~/.cache/appglass/keys/<key>/<version>/dark.json (appglass keys)
KEY_DEFAULTS = {"dark": (("121316", "content"), ("151517", "content"), ("060607", "bar"))}
APP_IDS = [r"^ai\.storyteller\.artcraft-launcher$"]
APP = "artcraft"
COMMAND = "artcraft-launcher"
DESKTOP = "ai.storyteller.artcraft-launcher.desktop"
WRAPPER = "appglass-artcraft"


def installed(env):
    return bool(env.which(COMMAND))


def apply(ctx):
    paths = [shims.c_shim(ctx, ADAPTER, APP, "appglass-ck.c", "appglass-ck.so")]
    paths += shims.copy(ctx, ADAPTER, APP, ("appglass-ck.c",))
    w = shims.wrapper(ctx, ADAPTER, WRAPPER)
    paths.append(w)
    p = shims.launcher(ctx, DESKTOP, w, command=COMMAND)
    if p:
        paths.append(p)
    return paths
