"""ck-shim: ArtCraft Launcher (artcraft-launcher, egui / winit / wgpu).

A forced adapter (off until apps.artcraft or apps.ai.storyteller.artcraft-launcher
is enabled). The wrapper appglass-artcraft picks one of two routes at launch:

* GPU (when the layer files are there and the host has a Vulkan GPU): wgpu stays
  on Vulkan, and the explicit layer VK_LAYER_APPGLASS_glass (shims/vklayer, named
  only by the wrapper's env) asks for a PRE_MULTIPLIED swapchain and colour-keys
  the launcher's dark background colours to the glass levels in one GPU draw
  before each present. See docs/artcraft-gpu.md.
* CPU (APPGLASS_ARTCRAFT=cpu, no layer, no Vulkan GPU): Mesa EGL + wgpu's GL
  backend (llvmpipe), the same keys done by appglass-ck.so on each swap, and
  swaps capped at APPGLASS_MAXFPS (60).

On both, appglass-ck.so (built from shims/ck-shim with gcc) drops the
whole-window opaque region winit sends (with it the window is glass when the
launcher commits but dark when niri redraws it without a commit) and scrubs
what the wrapper adds from every program the launcher starts.

A layer that does not build (no Vulkan headers) leaves the CPU route installed;
status says why (``render_route``: status --json ``render``, ``render_why``).

Files (owned; adopted hand files restored by remove):
  ~/.local/lib/appglass/artcraft/appglass-ck.so          (stamp: source + gcc)
  ~/.local/lib/appglass/artcraft/appglass-ck.c           its source, for reference
  ~/.local/lib/appglass/artcraft/vk/libappglass-vk.so    the layer (stamp: sources + gcc)
  ~/.local/lib/appglass/artcraft/vk/appglass-vk.json     its explicit manifest (relative path)
  ~/.local/bin/appglass-artcraft                         the launch wrapper (levels at launch)
  ~/.local/share/applications/ai.storyteller.artcraft-launcher.desktop -> the wrapper
"""

import glob
import os

from .. import shims
from ..core import Conflict

NAME = "artcraft"
ADAPTER = "ck-shim"
OPT_IN = True
KEYS = ("ai.storyteller.artcraft-launcher",)
APP_IDS = [r"^ai\.storyteller\.artcraft-launcher$"]
APP = "artcraft"
COMMAND = "artcraft-launcher"
DESKTOP = "ai.storyteller.artcraft-launcher.desktop"
WRAPPER = "appglass-artcraft"
VK = "vklayer"
LAYER_SO = "libappglass-vk.so"
LAYER_JSON = "appglass-vk.json"
# what the wrapper checks for a Vulkan GPU (status checks the same)
DRI = "/dev/dri"
ICD_DIRS = ("/etc/vulkan/icd.d", "/usr/share/vulkan/icd.d", "/usr/local/share/vulkan/icd.d")


def installed(env):
    return bool(env.which(COMMAND))


def layer_sources():
    return {n: shims.source(VK, n) for n in ("appglass-vk.c", "glass-spv.h")}


def _why(ex):
    """a short reason for a layer build that failed"""
    text = str(ex)
    if "vulkan/" in text and "No such file" in text:
        return "no Vulkan headers (vulkan-headers)"
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return (lines[-1] if lines else "layer build failed")[:200]


def layer(ctx):
    """[so, json] of the Vulkan layer, or raises Conflict when it cannot be built"""
    d = shims.lib_dir(ctx.env, APP, "vk")
    so = shims.build(ctx, VK, os.path.join(d, LAYER_SO), layer_sources(),
                     lambda tc, _: [[tc.cc, "-shared", "-fPIC", "-O2", "-Wall",
                                     "-fvisibility=hidden", "-o", LAYER_SO, "appglass-vk.c",
                                     "-lpthread"]],
                     ("cc",))
    return [so, ctx.write_owned(os.path.join(d, LAYER_JSON), shims.source(VK, LAYER_JSON),
                                mode=0o644)]


def apply(ctx):
    paths = [shims.c_shim(ctx, ADAPTER, APP, "appglass-ck.c", "appglass-ck.so")]
    paths += shims.copy(ctx, ADAPTER, APP, ("appglass-ck.c",))
    why = None
    try:
        paths += layer(ctx)
    except Conflict as ex:
        why = _why(ex)
        ctx.warn_once("cpu:" + why, "the GPU layer was not built (%s): ArtCraft renders on the "
                      "CPU route" % why)
    w = shims.wrapper(ctx, ADAPTER, WRAPPER, meta={"layer_why": why} if why else None)
    paths.append(w)
    p = shims.launcher(ctx, DESKTOP, w, command=COMMAND)
    if p:
        paths.append(p)
    return paths


def vulkan_device(environ):
    """the wrapper's check: a render node and a Vulkan driver that is not
    lavapipe (or one the user names with VK_DRIVER_FILES / VK_ICD_FILENAMES)"""
    if not glob.glob(os.path.join(DRI, "renderD*")):
        return False
    if environ.get("VK_DRIVER_FILES") or environ.get("VK_ICD_FILENAMES"):
        return True
    for d in ICD_DIRS:
        for p in glob.glob(os.path.join(d, "*.json")):
            if not os.path.basename(p).startswith("lvp_icd"):
                return True
    return False


def render_route(env, owner):
    """("gpu" | "cpu", why) for an applied family: the route the wrapper takes
    without APPGLASS_ARTCRAFT"""
    files = owner.get("files", {})
    d = shims.lib_dir(env, APP, "vk")
    layer_files = [os.path.join(d, n) for n in (LAYER_SO, LAYER_JSON)]
    if all(p in files and os.path.isfile(p) for p in layer_files):
        return ("gpu", "") if vulkan_device(env.environ) else ("cpu", "no Vulkan GPU")
    rec = files.get(shims.bin_path(env, WRAPPER)) or {}
    return "cpu", (rec.get("meta") or {}).get("layer_why") or "the GPU layer is not installed"
