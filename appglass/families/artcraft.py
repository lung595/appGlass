"""ck-shim: ArtCraft Launcher (artcraft-launcher, egui / winit / wgpu).

A forced adapter (off until apps.artcraft or apps.ai.storyteller.artcraft-launcher
is enabled). The wrapper appglass-artcraft picks one of two routes at launch:

* GPU (when the layer files are there and appglass-vkprobe, run with the
  route's Vulkan env and the layer on, finds a device that is not the CPU):
  wgpu stays on Vulkan, and the explicit layer VK_LAYER_APPGLASS_glass
  (shims/vklayer, named only by the wrapper's env) asks for a PRE_MULTIPLIED
  swapchain and colour-keys the launcher's dark background colours to the glass
  levels in one GPU draw before each present. Should wgpu still land on
  lavapipe, the layer caps presents at APPGLASS_MAXFPS. See docs/artcraft-gpu.md.
* CPU (APPGLASS_ARTCRAFT=cpu, no layer, or the probe finds only lavapipe, no
  device, or fails): Mesa EGL + wgpu's GL backend (llvmpipe), the same keys
  done by appglass-ck.so on each swap, and swaps capped at APPGLASS_MAXFPS (60).

On both, appglass-ck.so (built from shims/ck-shim with gcc) drops the
whole-window opaque region winit sends (with it the window is glass when the
launcher commits but dark when niri redraws it without a commit) and scrubs
what the wrapper adds from every program the launcher starts.

A layer or probe that does not build (no Vulkan headers) leaves the CPU route installed;
status says why (``render_route``: status --json ``render``, ``render_why``).

Files (owned; adopted hand files restored by remove):
  ~/.local/lib/appglass/artcraft/appglass-ck.so          (stamp: source + gcc)
  ~/.local/lib/appglass/artcraft/appglass-ck.c           its source, for reference
  ~/.local/lib/appglass/artcraft/vk/libappglass-vk.so    the layer (stamp: sources + gcc)
  ~/.local/lib/appglass/artcraft/vk/appglass-vk.json     its explicit manifest (relative path)
  ~/.local/lib/appglass/artcraft/vk/appglass-vkprobe     the device probe (stamp: source + gcc)
  ~/.local/bin/appglass-artcraft                         the launch wrapper (levels at launch)
  ~/.local/share/applications/ai.storyteller.artcraft-launcher.desktop -> the wrapper
"""

import os
import subprocess

from .. import shims
from ..core import Conflict

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
VK = "vklayer"
LAYER_SO = "libappglass-vk.so"
LAYER_JSON = "appglass-vk.json"
PROBE = "appglass-vkprobe"
LAYER = "VK_LAYER_APPGLASS_glass"


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
    """[probe, so, json] of the Vulkan layer, or raises Conflict when one cannot be built
    (the probe first: without it the wrapper never takes the GPU route)"""
    d = shims.lib_dir(ctx.env, APP, "vk")
    probe = shims.build(ctx, VK, os.path.join(d, PROBE),
                        {PROBE + ".c": shims.source(VK, PROBE + ".c")},
                        lambda tc, _: [[tc.cc, "-O2", "-Wall", "-o", PROBE, PROBE + ".c", "-ldl"]],
                        ("cc",))
    try:
        so = shims.build(ctx, VK, os.path.join(d, LAYER_SO), layer_sources(),
                         lambda tc, _: [[tc.cc, "-shared", "-fPIC", "-O2", "-Wall",
                                         "-fvisibility=hidden", "-o", LAYER_SO, "appglass-vk.c",
                                         "-lpthread"]],
                         ("cc",))
    except Conflict:
        ctx.drop(probe)
        raise
    return [probe, so, ctx.write_owned(os.path.join(d, LAYER_JSON), shims.source(VK, LAYER_JSON),
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


def vulkan_device(env, d):
    """(True, "") when appglass-vkprobe in d, run as the wrapper runs it (the
    user's env, the glass layer on, no EGL vendor override), finds a Vulkan
    device that is not the CPU; else (False, why)"""
    e = dict(env.environ)
    for k in ("__EGL_VENDOR_LIBRARY_FILENAMES", "APPGLASS_KEYS", "LD_PRELOAD"):
        e.pop(k, None)
    e["VK_ADD_LAYER_PATH"] = d + (":" + e["VK_ADD_LAYER_PATH"] if e.get("VK_ADD_LAYER_PATH") else "")
    e["VK_INSTANCE_LAYERS"] = LAYER + (":" + e["VK_INSTANCE_LAYERS"]
                                       if e.get("VK_INSTANCE_LAYERS") else "")
    try:
        r = env.run([os.path.join(d, PROBE)], env=e, timeout=10)
    except subprocess.TimeoutExpired:
        return False, "no usable Vulkan device (the probe hung)"
    except OSError as ex:
        return False, "the Vulkan probe does not run (%s)" % (ex.strerror or ex)
    if r.returncode == 0:
        return True, ""
    cpus = [l[4:] for l in r.stdout.splitlines() if l.startswith("cpu ")]
    if r.returncode == 1:
        return False, "no Vulkan GPU, only " + ", ".join(cpus or ["a CPU device"])
    return False, "no usable Vulkan device (the probe %s)" % (
        "exit %d" % r.returncode if r.returncode > 0 else "died of signal %d" % -r.returncode)


def render_route(env, owner):
    """("gpu" | "cpu" | "off", why) for an applied family: the route the wrapper
    takes with the env status runs in (APPGLASS_ARTCRAFT=cpu forces the CPU route;
    =off starts the launcher plain, on its own renderer, without glass: no glass route)"""
    knob = env.environ.get("APPGLASS_ARTCRAFT", "")
    if knob == "cpu":
        return "cpu", "APPGLASS_ARTCRAFT=cpu"
    if knob == "off":
        return "off", "APPGLASS_ARTCRAFT=off"
    files = owner.get("files", {})
    d = shims.lib_dir(env, APP, "vk")
    layer_files = [os.path.join(d, n) for n in (LAYER_SO, LAYER_JSON, PROBE)]
    if all(p in files and os.path.isfile(p) for p in layer_files):
        ok, why = vulkan_device(env, d)
        return ("gpu", "") if ok else ("cpu", why)
    rec = files.get(shims.bin_path(env, WRAPPER)) or {}
    return "cpu", (rec.get("meta") or {}).get("layer_why") or "the GPU layer is not installed"
