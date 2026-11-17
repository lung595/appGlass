# ArtCraft Launcher on the GPU (Vulkan layer prototype)

At the moment, the live ArtCraft route (`ck-shim` family `artcraft`, wrapper `appglass-artcraft`) renders the launcher in software:

- It uses Mesa EGL, wgpu's GL backend and llvmpipe.
- This is because wgpu's Vulkan swapchain is opaque.

This page covers a second route that keeps the launcher on the NVIDIA GPU:

- `shims/vklayer/` holds a small explicit Vulkan layer, `VK_LAYER_APPGLASS_glass`.
- The layer asks the WSI for a `PRE_MULTIPLIED` swapchain.
- It runs the same colour key as `appglass-ck.so` as one GPU draw before each present.

It is a prototype:

- No family installs it.
- The live launcher and `appglass-artcraft` are unchanged.

**Result**

- The NVIDIA Wayland WSI offers `PRE_MULTIPLIED` alpha, and the window really is translucent on it.
- The GPU route gives the same levels as the CPU route: content 153, bar 166, text 255.
- No frame flashed, during hovers or during 14 swapchain rebuilds.
- At 60 Hz the GPU route uses about **24x less CPU** than the llvmpipe route. At 240 Hz it uses about 11x less while presenting 3.5x more frames.

## What the NVIDIA WSI reports

The surface caps were read with a small read-only probe (`vkcaps`):

- It creates a `wl_surface` with no role and no buffer, then a `VkSurfaceKHR`.
- It prints the caps and exits.
- It was run on the real session's display (read only, nothing presented) and inside the headless harness (nested niri in headless gamescope).

| | NVIDIA GPU, proprietary driver (real session and harness) | llvmpipe (Mesa 26.2.6) |
|---|---|---|
| `supportedCompositeAlpha` | `0x3`: `OPAQUE`, `PRE_MULTIPLIED` | `0x3`: `OPAQUE`, `PRE_MULTIPLIED` |
| `supportedUsageFlags` | `0x9f` (includes `INPUT_ATTACHMENT`, `STORAGE`) | `0x8009f` |
| Formats | `R8G8B8A8` / `B8G8R8A8` UNORM and SRGB, `R16G16B16A16_SFLOAT`, `A2R10G10B10`, `A2B10G10R10` | `R8G8B8A8` / `B8G8R8A8` UNORM and SRGB |
| Present modes | MAILBOX, FIFO, and one other | MAILBOX, FIFO |

On both drivers, a Wayland surface gets alpha only when the app asks for it. ArtCraft does not ask:

- eframe makes the window with `transparent: false`.
- wgpu's `alpha_mode: Auto` then resolves to `Opaque`.
- No environment variable changes this.

The layer makes the request in the app's place.

## How the layer works

The layer is enabled only by the environment, through the wrapper:

```
VK_ADD_LAYER_PATH=$LIB/vk    VK_INSTANCE_LAYERS=VK_LAYER_APPGLASS_glass
APPGLASS_KEYS="121316:0.60,151517:0.60,060607:0.65"  APPGLASS_SNAP=0.25
[APPGLASS_TOL=0.02] [APPGLASS_DEBUG=1] [APPGLASS_TRACE=file]
```

- **An explicit layer only.** `appglass-vk.json` has no `enable_environment`, and nothing is written to `/usr/share/vulkan`, `/etc/vulkan` or `~/.local/share/vulkan`. A program that is not started with both variables never loads the layer. Without `APPGLASS_KEYS` the layer passes every call through unchanged.
- **Swapchain creation.** The swapchain is rewritten to `compositeAlpha = PRE_MULTIPLIED` with usage `| INPUT_ATTACHMENT` only when all of these hold:
  - the surface offers both;
  - the format is 8-bit UNORM with alpha (`R8G8B8A8`, `B8G8R8A8`, `A8B8G8R8`);
  - the colour space is sRGB-nonlinear;
  - every queue family the app created can do graphics.

  In every other case the swapchain is created exactly as asked (opaque), and the reason is logged with `APPGLASS_DEBUG`. If the driver refuses the rewritten swapchain, or the layer cannot build its pass, the layer recreates the swapchain exactly as asked. The app never sees an error from the layer.
- **The pass.** Each swapchain image is both the input attachment and the colour attachment of a one-subpass render pass:
  - load and store, layout `GENERAL`, `PRESENT_SRC` before and after;
  - a full-screen triangle where each fragment reads its own pixel (`subpassLoad`) and writes the keyed, premultiplied value.

  This works for both RGBA and BGRA, needs no device feature, no copy and no extra image. One command buffer is recorded per image at the first present.
- **The present.** For each keyed swapchain the layer submits one batch to the presenting queue:
  - the batch waits on the app's semaphores and signals a semaphore that belongs to the layer;
  - the real `vkQueuePresentKHR` waits on that semaphore;
  - a fence per image keeps a command buffer from being resubmitted before its last run has finished.
- **The formula.** The layer uses the same formula as `appglass-ck.c`: colour-to-alpha against the nearest key, glass alpha `1 - (1 - a)(1 - A)`, premultiplied rgb, `tol` 0.02, and `snap` (0.25 in the wrapper). There is one addition:
  - A channel within one 8-bit level of a key counts as the key.
  - wgpu on Vulkan dithers its output. On the GL route it does not. So a translucent egui fill lands on the key ±1 level at random.
  - Against the dark bar key `060607`, one level is 1/6 of the colour-to-alpha range. Without the slack, the search box and badges came out speckled: 509 pixels at alpha 219 inside the 166 glass, shot `gpu-window-noslack.png`.
  - With the slack, the pixel counts match the CPU route (57 against 46).
- **The opaque region.** `appglass-ck.so` is still preloaded, for two reasons:
  - winit sets a full opaque region on a window made with `transparent: false`, and the shim replaces it with none;
  - the shim scrubs `APPGLASS_SCRUB` from children.

  Its EGL hooks stay idle on Vulkan.
- **Children.** The wrapper lists `WGPU_BACKEND`, `VK_ADD_LAYER_PATH` and `VK_INSTANCE_LAYERS` in `APPGLASS_SCRUB` when it added them itself. The shim drops them, every `APPGLASS_*` variable and `appglass-ck.so` from `LD_PRELOAD` on every exec or spawn of another program. Apps and games started from the launcher (flatpak, xdg-open) never load the layer. `tests/test_vklayer.py` (`Wrapper.test_child_scrubbed`) checks this.

### Shaders

`glass.vert` and `glass.frag` are compiled by `gen-spv.py` into `glass-spv.h`, which is checked in:

- It uses `libshaderc_shared` through ctypes, so it needs no `glslc`.
- The header records the sha256 of both sources.
- `gen-spv.py --check`, and the test suite, fail when the header is stale.
- The test suite also runs the SPIR-V through `spvValidateBinary` (Vulkan 1.1) when `libSPIRV-Tools-shared` is installed.

### Files

| File | What |
|---|---|
| `shims/vklayer/appglass-vk.c` | the layer (about 500 lines of C, no dependencies beyond the Vulkan headers) |
| `shims/vklayer/appglass-vk.json` | explicit layer manifest, `library_path` `./libappglass-vk.so` (next to it) |
| `shims/vklayer/glass.vert`, `glass.frag`, `gen-spv.py`, `glass-spv.h` | the pass and its generated SPIR-V |
| `shims/vklayer/appglass-artcraft-gpu` | prototype wrapper: `$LIB/vk/` layer dir, `WGPU_BACKEND=vulkan`, same keys, levels, light-theme and `APPGLASS_ARTCRAFT=off` handling as `appglass-artcraft` |
| `tests/test_vklayer.py` | SPIR-V freshness and validity, manifest, exports, and the layer on lavapipe |

The layer tests run a small C client on lavapipe through `VK_EXT_headless_surface`, with no display:

- The client presents an OPAQUE 64x32 swapchain filled with the keys, a white square and a half-covered edge.
- It re-acquires the image and reads it back.

The tests then check:

- content 153 and bar 166, with premultiplied rgb;
- text 255;
- an edge between 153 and 255;
- a key ±1 level still gives the glass level;
- both RGBA and BGRA;
- nothing changes without keys, and without the layer.

To build it by hand (for example to try it):

```
LIB=~/.local/lib/appglass/artcraft
gcc -O2 -shared -fPIC -fvisibility=hidden -o $LIB/vk/libappglass-vk.so shims/vklayer/appglass-vk.c -lpthread
cp shims/vklayer/appglass-vk.json $LIB/vk/
```

## Measurements (headless harness)

**Harness setup.**

- `env -i` + `dbus-run-session`, with a private bus config that has no service directories, so no portal can start.
- Private `XDG_RUNTIME_DIR` and sandbox `HOME`.
- Headless gamescope (`-r 60` or `-r 240`) hosting nested niri.
- Scale 1.5 and the user's ArtCraft glass rule (blur 3/5.4, background-effect blur, clip, radius 16).
- ArtCraft 0.19.2 started through both wrappers, in a user+network namespace with no network.
- Hover: three card hovers through a virtual pointer.
- CPU: `utime + stime` of the launcher from `/proc`.
- Frames: wlr-screencopy with damage, one frame per compositor repaint.

**Levels.** The window shot was taken with `screenshot-window`, with the rule's `opacity 0.80` turned off for the measurement, and judged by `tests/e2e/measure.py`.

| | GPU route (layer) | CPU route (llvmpipe) |
|---|---|---|
| Content alpha (mode) | 153 (0.60), 88 % of the window | 153, 87 % |
| Bar alpha | 166 (0.65) | 166 |
| White glyph pixels at 255 | 3421 | 3423 |
| Fully opaque pixels | 34163 | 34427 |
| measure.py | pass | pass |

**CPU and pacing.** Three hovers; idle is 10 s with the pointer outside.

| Output | Route | Idle CPU | Hover CPU | Presents | Gap median | CPU per present |
|---|---|---|---|---|---|---|
| 60 Hz | GPU (layer) | 0 | **0.11 s** | 120 | 17.9 ms | 0.9 ms |
| 60 Hz | CPU (llvmpipe, 4 threads) | 0 | 2.68 s | 120 | 16.7 ms | 22.3 ms |
| 240 Hz | GPU (layer) | 0 | **0.24 s** | 432 | 4.2 ms | 0.56 ms |
| 240 Hz | CPU (llvmpipe, 60 fps cap) | 0 | 2.75 s | 123 | 16.7 ms | 22.4 ms |
| 240 Hz | plain Vulkan, no layer (opaque) | 0 | 0.24 s | n/a | n/a | n/a |

- On the CPU the layer's present hook takes under 0.01 ms per present (`APPGLASS_TRACE`, third column).
- Plain Vulkan without the layer costs the same CPU (0.24 s), so the layer adds no measurable CPU cost.
- The time the pass takes on the GPU was not measured: no timestamp queries were used.

**Flashes.**

- A frame analysis (`flash.py`) of every recorded frame counted two things:
  - pixels inside the window that still show an unkeyed key colour, which a frame presented opaque would show;
  - the mean colour of a static region away from the hovered card.
- The control run (plain Vulkan, opaque) shows 77157 such pixels in every frame (1/9 sample). This proves the check catches an opaque frame.

| Run | Frames | Max unkeyed pixels per frame | Static region spread |
|---|---|---|---|
| GPU 240 Hz, hovers | 174 | 0 | 0.0 |
| GPU 60 Hz, hovers | 58 | 0 | 0.0 |
| GPU 60 Hz, 13 width changes (14 swapchains rebuilt) | 58 | 0 | changes only because the window moves |
| CPU 240 Hz, hovers | 115 | 2 | 0.0 |
| CPU 60 Hz, hovers | 111 | 2 | 0.0 |

All shots, logs, traces, recordings (`frames.tsv`, `flash.tsv`) and the harness scripts are kept outside the repo, in the probe notes for this step (`shots/gpu/b1b/`).

## Limits and open points

- **Not installed.**
  - Making it the live route takes two steps: a `vklayer` adapter or family change that builds `libappglass-vk.so` into `~/.local/lib/appglass/artcraft/vk/`, and writing `appglass-artcraft-gpu` in place of `appglass-artcraft`.
  - That is a separate step: the live launcher was not to change here.
  - The CPU route stays the default until then.
- **Not tried on the real session.**
  - Every run was in the headless harness. The real session's outputs have other refresh rates and scales than the harness, and the real niri might treat the window differently.
  - The real driver was only probed read-only, for its caps.
- **Formats.**
  - sRGB swapchain formats are refused (left opaque): the pass would need sRGB-aware keys.
  - 10-bit, float formats and HDR colour spaces are also refused.
  - ArtCraft uses `R8G8B8A8_UNORM` in sRGB-nonlinear, so it is covered.
- **Queues.** If an app creates a queue family without graphics, every swapchain of that app stays opaque, because the layer draws on the presenting queue.
- **Other Vulkan apps.**
  - The layer is generic, but its keys are ArtCraft's.
  - Any other app needs its own keys and the same scrub.
  - Games must never get it: they are children of the launcher, and the scrub covers that case.
- **Dither slack.** It differs from `appglass-ck.so` by one 8-bit level. A UI colour within one level of a key now becomes glass too, but ArtCraft's dark palette has no such colour.
