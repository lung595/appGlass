# ArtCraft Launcher on the GPU (Vulkan layer)

The ArtCraft family (`ck-shim` family `artcraft`, wrapper `appglass-artcraft`) keeps the launcher on the GPU:

- `shims/vklayer/` holds a small explicit Vulkan layer, `VK_LAYER_APPGLASS_glass`.
- The layer asks the WSI for a `PRE_MULTIPLIED` swapchain.
- It runs the same colour key as `appglass-ck.so` as one GPU draw before each present.

Without it, wgpu's Vulkan swapchain is opaque, and the only glass route is the CPU one: Mesa EGL, wgpu's GL backend and llvmpipe ([gpu.md](gpu.md)).

## Install and routes

`appglass apply --only artcraft` (the family is off until `apps.artcraft.enabled = true`) builds and records, next to `appglass-ck.so`:

- `~/.local/lib/appglass/artcraft/vk/libappglass-vk.so`, built with the host `cc` from `appglass-vk.c` and `glass-spv.h` (rebuilt only when they or the compiler change);
- `~/.local/lib/appglass/artcraft/vk/appglass-vk.json`, the explicit manifest (`library_path` `./libappglass-vk.so`).

Nothing is written to `/usr/share/vulkan`, `/etc/vulkan` or `~/.local/share/vulkan`. `appglass remove --only artcraft` deletes both files with the rest of the family (a hand-made file it adopted is put back).

The one wrapper, `appglass-artcraft`, picks the route at every start:

| Case | Route |
|---|---|
| `APPGLASS_ARTCRAFT=off`, no `appglass-ck.so`, or a light system theme | plain (opaque, as the launcher ships) |
| both layer files there, a `/dev/dri/renderD*` node, and a Vulkan driver that is not lavapipe (an ICD json in `/etc/vulkan/icd.d`, `/usr/share/vulkan/icd.d` or `/usr/local/share/vulkan/icd.d`, or `VK_DRIVER_FILES` / `VK_ICD_FILENAMES` set) | **GPU**: `WGPU_BACKEND=vulkan`, the layer, the keys; no fps cap |
| `APPGLASS_ARTCRAFT=cpu`, or no layer, or no Vulkan GPU, and Mesa EGL is installed | **CPU**: Mesa EGL, `WGPU_BACKEND=gl`, llvmpipe 4 threads, the keys, `APPGLASS_MAXFPS=60` |
| none of the above | plain |

Both routes read the levels from `appglass levels` at start and scrub everything they add from the programs the launcher starts.

When the layer does not build (no Vulkan headers, for example), apply warns once, the CPU route is still installed, and status gives the reason.

`appglass status` shows the route on the family line, `artcraft   installed, applied (renders on the GPU): ...` or `(renders on the CPU: <why>)`. `status --json` has `render` and `render_why` on the family, and the app's route reason says it too, which is what the plugin's app row shows. `appglass doctor` prints `render: artcraft on the GPU` (an information line, not drift). They make the same checks as the wrapper, without `APPGLASS_ARTCRAFT`.

**Result**

- The NVIDIA Wayland WSI offers `PRE_MULTIPLIED` alpha, and the window really is translucent on it.
- wgpu picks the NVIDIA GPU: with `APPGLASS_DEBUG=1` the layer logs `device: NVIDIA ... (vendor 0x10de ...)` at `vkCreateDevice` (harness, ArtCraft 0.19.2). It is the only device the launcher creates.
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

  In every other case the swapchain is created exactly as asked (opaque), and the reason is logged with `APPGLASS_DEBUG`. If the driver refuses the rewritten swapchain, or the layer cannot build its pass (or the swapchain has more than 16 images), the layer recreates the swapchain exactly as asked. That retry passes no `oldSwapchain`: the first call has already retired it. The app never sees an error from the layer.
- **The pass.** Each swapchain image is both the input attachment and the colour attachment of a one-subpass render pass:
  - load and store, layout `GENERAL`, `PRESENT_SRC` before and after;
  - a full-screen triangle where each fragment reads its own pixel (`subpassLoad`) and writes the keyed, premultiplied value.

  This works for both RGBA and BGRA, needs no device feature, no copy and no extra image.
  - The render pass and pipeline are built once per device and format and kept until `vkDestroyDevice`, so swapchains of different formats on one device each keep theirs.
  - One command buffer is recorded per image at the first present, for the queue family of that present. A later present from another family waits for the swapchain's last passes and records again.
- **The present.** For each keyed swapchain the layer submits one batch to the presenting queue:
  - the batch waits on the app's semaphores and signals a semaphore that belongs to the layer;
  - the real `vkQueuePresentKHR` waits on that semaphore;
  - a fence per image keeps a command buffer from being resubmitted before its last run has finished;
  - every wait semaphore of the app's present is waited on, also past 64;
  - the layer's lock only guards its lists. The fence wait and the submit run without it, so a slow present on one swapchain does not hold up another thread.
- **The formula.** The layer uses the same formula as `appglass-ck.c`: colour-to-alpha against the nearest key, glass alpha `1 - (1 - a)(1 - A)`, premultiplied rgb, `tol` 0.02, and `snap` (0.25 in the wrapper). There is one addition:
  - A channel within one 8-bit level of a key counts as the key.
  - wgpu on Vulkan dithers its output. On the GL route it does not. So a translucent egui fill lands on the key ±1 level at random.
  - Against the dark bar key `060607`, one level is 1/6 of the colour-to-alpha range. Without the slack, the search box and badges came out speckled: 509 pixels at alpha 219 inside the 166 glass, shot `gpu-window-noslack.png`.
  - With the slack, the pixel counts match the CPU route (57 against 46).
- **The opaque region.** `appglass-ck.so` is still preloaded, for two reasons:
  - winit sets a full opaque region on a window made with `transparent: false`, and the shim replaces it with none;
  - the shim scrubs `APPGLASS_SCRUB` from children.

  Its EGL hooks stay idle on Vulkan.
- **Children.** The wrapper always lists `WGPU_BACKEND`, `VK_ADD_LAYER_PATH` and `VK_INSTANCE_LAYERS` in `APPGLASS_SCRUB`. The shim drops them, every `APPGLASS_*` variable and `appglass-ck.so` from `LD_PRELOAD` on every exec or spawn of another program. Apps and games started from the launcher (flatpak, xdg-open) never load the layer.
  - When the user had set one of the three before, the wrapper saves that value as `APPGLASS_ORIG_<var>`, and the shim gives it back to the child as it was, without the layer in it.
  - `tests/test_vklayer.py` (`Wrapper.test_child_scrubbed`, `test_child_gets_the_users_own_values`) checks both cases.

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
| `shims/ck-shim/appglass-artcraft` | the wrapper: picks the GPU, CPU or plain route (table above) |
| `appglass/families/artcraft.py` | builds and records the layer, `render_route()` for status |
| `tests/test_vklayer.py` | SPIR-V freshness and validity, manifest, exports, the layer on lavapipe, and the wrapper's env and scrub on both routes |
| `tests/test_artcraft.py` | the family's files, a failed layer build, status/doctor render, and every wrapper route |

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

A second client (`multi`) runs the swapchain lifecycles of a real app, with two frames in flight and a clean teardown:

- two swapchains with different formats on one device, presented in turn;
- recreation with `oldSwapchain`: one too large to key (17 images), then a normal one;
- 120 frames with a resize every 25 frames;
- presents that wait on 70 semaphores.

When the Khronos validation layer is installed (or `APPGLASS_TEST_VVL` names a dir with its manifest), these runs put it under the glass layer with sync validation on, so it checks every call the glass layer makes, and any validation error fails the test. Before round 1 of fixes these runs found a use-after-free of the render pass with two formats (the process crashed), a retired `oldSwapchain` passed again, and dropped wait semaphores past 64. They now report no errors.

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

After round 1 of fixes (per-format passes, the unlocked present), a re-run of the GPU route gave the same numbers, also after 10 width changes (`shots/gpu/b1b-fix1/`).

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

## The installed family (headless harness)

The same harness, with the files installed by `appglass apply --only artcraft` into a sandbox HOME (real `cc`, real Vulkan headers) and the launcher started through the installed `appglass-artcraft`, 60 Hz output, no network:

- `appglass status`: `artcraft   installed, applied (renders on the GPU)`, the app row `family artcraft, renders on the GPU`; `appglass doctor`: `render: artcraft on the GPU`, no drift.
- Default start: the GPU route. `APPGLASS_DEBUG=1` logs `device: NVIDIA ... (vendor 0x10de ...)` and `compositeAlpha OPAQUE -> PRE_MULTIPLIED` for each swapchain.
- `APPGLASS_ARTCRAFT=cpu`: the CPU route (Mesa EGL, `WGPU_BACKEND=gl`, `LP_NUM_THREADS=4`, `APPGLASS_MAXFPS=60`); the layer is not loaded.

| | GPU route | CPU route |
|---|---|---|
| Content alpha (mode) | 153, 88 % of the window | 153, 87 % |
| Bar alpha | 166 | 166 |
| White glyph pixels at 255 | 3421 | 3423 |
| measure.py | pass | pass |
| CPU while scrolling the app grid (3 x 12 notches down and up, about 17 s), run 1 | 0.73 s (4.1 % of one core), 939 presents | 18.46 s (114.5 %), 844 presents |
| run 2 | 0.67 s (3.8 %), 936 presents | 18.20 s (113.4 %), 841 presents |
| CPU per present | 0.7-0.8 ms | 21.6-21.9 ms |
| Idle 10 s | 0 | 0 |

Scrolling costs about 25 times less CPU on the GPU route. Shots, logs and scripts: `shots/artgpu/` in the probe notes.

## Limits and open points

- **Not tried on the real session.**
  - Every run was in the headless harness (also the run with the installed family, below). The real session's outputs have other refresh rates and scales than the harness, and the real niri might treat the window differently.
  - The real driver was only probed read-only, for its caps.
- **Formats.**
  - sRGB swapchain formats are refused (left opaque): the pass would need sRGB-aware keys.
  - 10-bit, float formats and HDR colour spaces are also refused.
  - ArtCraft uses `R8G8B8A8_UNORM` in sRGB-nonlinear, so it is covered.
- **Queues.** If an app creates a queue family without graphics, every swapchain of that app stays opaque, because the layer draws on the presenting queue. lavapipe has one queue family, so the re-recording for a present from another family is not covered by a test.
- **Other Vulkan apps.**
  - The layer is generic, but its keys are ArtCraft's.
  - Any other app needs its own keys and the same scrub.
  - Games must never get it: they are children of the launcher, and the scrub covers that case.
- **Dither slack.** It differs from `appglass-ck.so` by one 8-bit level. A UI colour within one level of a key now becomes glass too, but ArtCraft's dark palette has no such colour.
