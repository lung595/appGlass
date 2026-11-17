"""The Vulkan glass layer (shims/vklayer), built with the host gcc.

* the SPIR-V it embeds matches its GLSL sources (hash always; byte for byte and
  spirv-val when libshaderc / libSPIRV-Tools are installed);
* the manifest is an explicit layer: it is never on unless the wrapper env names it;
* the .so exports only the three loader entry points;
* end to end on lavapipe with a headless surface: a client makes an OPAQUE swapchain,
  fills it with the launcher's key colours and a white "text" square and presents it.
  With the layer and keys, the presented image has the key pixels at their glass alpha
  (premultiplied), the text at 255, and the layer asked for PRE_MULTIPLIED. Without keys,
  or without the layer, the image is untouched;
* the wrapper appglass-artcraft only adds the layer through its own env (GPU route), and a
  child the launcher starts loses all of it, on both routes (the ck-shim scrub).
"""

import ctypes
import ctypes.util
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(REPO, "shims", "vklayer")
SRC = os.path.join(D, "appglass-vk.c")
GCC = shutil.which("gcc")
LVP = "/usr/share/vulkan/icd.d/lvp_icd.x86_64.json"
LAYER = "VK_LAYER_APPGLASS_glass"


def have_vulkan_dev():
    return GCC and os.path.exists("/usr/include/vulkan/vk_layer.h")


def spirv_arrays(text):
    """{name: [words]} of the uint32_t arrays in glass-spv.h"""
    out = {}
    for name, body in re.findall(r"static const uint32_t (\w+)\[\] = \{(.*?)\};", text, re.S):
        out[name] = [int(w, 16) for w in re.findall(r"0x[0-9a-f]{8}", body)]
    return out


class Spirv(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(D, "glass-spv.h")) as f:
            self.h = f.read()

    def test_hash_of_sources(self):
        h = hashlib.sha256()
        for n in ("glass.vert", "glass.frag"):
            with open(os.path.join(D, n), "rb") as f:
                h.update(f.read())
        self.assertIn("// sources sha256 %s" % h.hexdigest(), self.h)

    def test_arrays(self):
        a = spirv_arrays(self.h)
        self.assertEqual(sorted(a), ["glass_frag_spv", "glass_vert_spv"])
        for words in a.values():
            self.assertEqual(words[0], 0x07230203)      # SPIR-V magic

    @unittest.skipUnless(ctypes.util.find_library("shaderc_shared") or
                         os.path.exists("/usr/lib64/libshaderc_shared.so.1"), "no libshaderc")
    def test_regenerates_identical(self):
        r = subprocess.run(["python3", os.path.join(D, "gen-spv.py"), "--check"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    @unittest.skipUnless(os.path.exists("/usr/lib64/libSPIRV-Tools-shared.so"), "no SPIRV-Tools")
    def test_valid_vulkan_spirv(self):
        t = ctypes.CDLL("/usr/lib64/libSPIRV-Tools-shared.so")
        t.spvContextCreate.restype = ctypes.c_void_p
        t.spvContextCreate.argtypes = [ctypes.c_int]
        t.spvValidateBinary.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.c_void_p]
        t.spvContextDestroy.argtypes = [ctypes.c_void_p]
        SPV_ENV_VULKAN_1_1 = 18
        ctx = t.spvContextCreate(SPV_ENV_VULKAN_1_1)
        try:
            for name, words in spirv_arrays(self.h).items():
                buf = (ctypes.c_uint32 * len(words))(*words)
                self.assertEqual(t.spvValidateBinary(ctx, buf, len(words), None), 0, name)
        finally:
            t.spvContextDestroy(ctx)


class Manifest(unittest.TestCase):
    def test_explicit_layer(self):
        with open(os.path.join(D, "appglass-vk.json")) as f:
            m = json.load(f)
        l = m["layer"]
        self.assertEqual(l["name"], LAYER)
        self.assertEqual(l["type"], "INSTANCE")
        self.assertEqual(l["library_path"], "./libappglass-vk.so")   # next to the manifest
        # an implicit layer has these; an explicit one is loaded only when named
        self.assertNotIn("enable_environment", l)
        self.assertNotIn("disable_environment", l)
        self.assertEqual(l["functions"], {"vkGetInstanceProcAddr": "vkGetInstanceProcAddr",
                                          "vkGetDeviceProcAddr": "vkGetDeviceProcAddr"})


CLIENT = r"""
// client <R|B|S> : headless OPAQUE swapchain 64x32 (RGBA, BGRA or BGRA sRGB), fill, present, read
// the presented image back.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define CK(x) do { VkResult r_ = (x); if (r_) { fprintf(stderr, "%s = %d\n", #x, r_); exit(2); } } while (0)
enum { W = 64, H = 32 };
static VkDevice dev; static VkPhysicalDevice pd; static VkQueue q; static VkCommandPool pool;
static uint32_t memtype(uint32_t bits) {
    VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(pd, &mp);
    for (uint32_t i = 0; i < mp.memoryTypeCount; i++)
        if ((bits & (1u << i)) && (mp.memoryTypes[i].propertyFlags & (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) == (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) return i;
    exit(3);
}
static VkCommandBuffer begin(void) {
    VkCommandBufferAllocateInfo ai = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, 0, pool, VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1 };
    VkCommandBuffer c; CK(vkAllocateCommandBuffers(dev, &ai, &c));
    VkCommandBufferBeginInfo bi = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, 0, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT };
    CK(vkBeginCommandBuffer(c, &bi)); return c;
}
static void barrier(VkCommandBuffer c, VkImage im, VkImageLayout from, VkImageLayout to) {
    VkImageMemoryBarrier b = { VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, 0, VK_ACCESS_MEMORY_WRITE_BIT, VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT,
        from, to, VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED, im, { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 } };
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 0, 0, 0, 0, 1, &b);
}
static void put(uint8_t *p, int bgr, uint32_t rgb) {
    uint8_t r = rgb >> 16, g = rgb >> 8, b = rgb;
    p[0] = bgr ? b : r; p[1] = g; p[2] = bgr ? r : b; p[3] = 255;
}
int main(int argc, char **argv) {
    int bgr = argv[1][0] != 'R';
    VkFormat fmt = argv[1][0] == 'S' ? VK_FORMAT_B8G8R8A8_SRGB : bgr ? VK_FORMAT_B8G8R8A8_UNORM : VK_FORMAT_R8G8B8A8_UNORM;
    const char *ie[] = { "VK_KHR_surface", "VK_EXT_headless_surface" };
    VkApplicationInfo app = { VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1 };
    VkInstanceCreateInfo ici = { VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app, .enabledExtensionCount = 2, .ppEnabledExtensionNames = ie };
    VkInstance in; CK(vkCreateInstance(&ici, 0, &in));
    PFN_vkCreateHeadlessSurfaceEXT hs = (PFN_vkCreateHeadlessSurfaceEXT)vkGetInstanceProcAddr(in, "vkCreateHeadlessSurfaceEXT");
    VkHeadlessSurfaceCreateInfoEXT hci = { VK_STRUCTURE_TYPE_HEADLESS_SURFACE_CREATE_INFO_EXT }; VkSurfaceKHR surf; CK(hs(in, &hci, 0, &surf));
    uint32_t n = 1; vkEnumeratePhysicalDevices(in, &n, &pd);
    float prio = 1; VkDeviceQueueCreateInfo qci = { VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, 0, 0, 0, 1, &prio };
    const char *de[] = { "VK_KHR_swapchain" };
    VkDeviceCreateInfo dci = { VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qci, .enabledExtensionCount = 1, .ppEnabledExtensionNames = de };
    CK(vkCreateDevice(pd, &dci, 0, &dev)); vkGetDeviceQueue(dev, 0, 0, &q);
    VkCommandPoolCreateInfo pci = { VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, 0, 0, 0 }; CK(vkCreateCommandPool(dev, &pci, 0, &pool));
    VkSurfaceCapabilitiesKHR caps; CK(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(pd, surf, &caps));
    VkSwapchainCreateInfoKHR sci = { VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR, 0, 0, surf, caps.minImageCount, fmt, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR,
        { W, H }, 1, VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
        VK_SHARING_MODE_EXCLUSIVE, 0, 0, VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR, VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR, VK_PRESENT_MODE_FIFO_KHR, 1, 0 };
    VkSwapchainKHR sc; CK(vkCreateSwapchainKHR(dev, &sci, 0, &sc));
    uint32_t ni = 8; VkImage im[8]; CK(vkGetSwapchainImagesKHR(dev, sc, &ni, im));
    VkBufferCreateInfo bci = { VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, 0, 0, W * H * 4, VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT };
    VkBuffer buf; CK(vkCreateBuffer(dev, &bci, 0, &buf));
    VkMemoryRequirements mr; vkGetBufferMemoryRequirements(dev, buf, &mr);
    VkMemoryAllocateInfo mai = { VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, 0, mr.size, memtype(mr.memoryTypeBits) };
    VkDeviceMemory mem; CK(vkAllocateMemory(dev, &mai, 0, &mem)); CK(vkBindBufferMemory(dev, buf, mem, 0));
    uint8_t *px; CK(vkMapMemory(dev, mem, 0, W * H * 4, 0, (void **)&px));
    for (int y = 0; y < H; y++) for (int x = 0; x < W; x++) {
        uint32_t c = 0x121316;                         /* content key */
        if (y < 8) c = 0x060607;                       /* bar key */
        if (x >= 40 && x < 48 && y >= 16 && y < 24) c = 0xffffff;  /* "text" */
        if (x == 10 && y == 20) c = 0x898a8b;          /* a half-covered glyph edge: half way to white */
        if (x == 20 && y == 4) c = 0x050506;           /* the bar key one level down (wgpu dithers fills) */
        if (x == 20 && y == 24) c = 0x131417;          /* the content key one level up */
        put(px + (y * W + x) * 4, bgr, c);
    }
    VkSemaphoreCreateInfo si = { VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO }; VkSemaphore acq, done; CK(vkCreateSemaphore(dev, &si, 0, &acq)); CK(vkCreateSemaphore(dev, &si, 0, &done));
    VkFenceCreateInfo fci = { VK_STRUCTURE_TYPE_FENCE_CREATE_INFO }; VkFence f; CK(vkCreateFence(dev, &fci, 0, &f));
    uint32_t idx; CK(vkAcquireNextImageKHR(dev, sc, UINT64_MAX, acq, 0, &idx));
    VkCommandBuffer c = begin(); barrier(c, im[idx], VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    VkBufferImageCopy reg = { 0, 0, 0, { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 }, { 0, 0, 0 }, { W, H, 1 } };
    vkCmdCopyBufferToImage(c, buf, im[idx], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &reg);
    barrier(c, im[idx], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR); CK(vkEndCommandBuffer(c));
    VkPipelineStageFlags ws = VK_PIPELINE_STAGE_TRANSFER_BIT;
    VkSubmitInfo sub = { VK_STRUCTURE_TYPE_SUBMIT_INFO, 0, 1, &acq, &ws, 1, &c, 1, &done }; CK(vkQueueSubmit(q, 1, &sub, 0));
    VkPresentInfoKHR pi = { VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, 0, 1, &done, 1, &sc, &idx, 0 }; CK(vkQueuePresentKHR(q, &pi));
    CK(vkQueueWaitIdle(q));
    /* get the same image back: present any other image we are handed */
    uint32_t got = UINT32_MAX;
    for (int t = 0; t < 16 && got != idx; t++) {
        CK(vkAcquireNextImageKHR(dev, sc, UINT64_MAX, 0, f, &got)); CK(vkWaitForFences(dev, 1, &f, 1, UINT64_MAX)); CK(vkResetFences(dev, 1, &f));
        if (got == idx) break;
        VkCommandBuffer o = begin(); barrier(o, im[got], VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR); CK(vkEndCommandBuffer(o));
        VkSubmitInfo os = { VK_STRUCTURE_TYPE_SUBMIT_INFO, 0, 0, 0, 0, 1, &o, 1, &done }; CK(vkQueueSubmit(q, 1, &os, 0));
        VkPresentInfoKHR op = { VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, 0, 1, &done, 1, &sc, &got, 0 }; CK(vkQueuePresentKHR(q, &op)); CK(vkQueueWaitIdle(q));
    }
    if (got != idx) { fprintf(stderr, "image %u never came back\n", idx); return 4; }
    memset(px, 0, W * H * 4);
    VkCommandBuffer r = begin(); barrier(r, im[idx], VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    vkCmdCopyImageToBuffer(r, im[idx], VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buf, 1, &reg); CK(vkEndCommandBuffer(r));
    VkSubmitInfo rs = { VK_STRUCTURE_TYPE_SUBMIT_INFO, 0, 0, 0, 0, 1, &r, 0, 0 }; CK(vkQueueSubmit(q, 1, &rs, 0)); CK(vkQueueWaitIdle(q));
    int at[][2] = { { 30, 20 }, { 30, 2 }, { 44, 20 }, { 10, 20 }, { 20, 4 }, { 20, 24 } };   /* content, bar, text, edge, dithered bar, dithered content */
    for (int i = 0; i < 6; i++) {
        uint8_t *p = px + (at[i][1] * W + at[i][0]) * 4;
        printf("%d %d %d %d\n", bgr ? p[2] : p[0], p[1], bgr ? p[0] : p[2], p[3]);
    }
    vkDestroySwapchainKHR(dev, sc, 0); vkDestroyDevice(dev, 0); vkDestroySurfaceKHR(in, surf, 0); vkDestroyInstance(in, 0);
    return 0;
}
"""


NOMEM = r"""
// built into a test copy of the layer with -Dcalloc=appglass_test_calloc: APPGLASS_TEST_NOMEM=<n>
// makes the n-th calloc of the layer fail (1: the instance record, 2: the device record)
#undef calloc                         /* this file calls the real one */
#include <stdlib.h>
#include <pthread.h>
void *appglass_test_calloc(size_t n, size_t s);
static pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
static int calls;
void *appglass_test_calloc(size_t n, size_t s) {
    const char *e = getenv("APPGLASS_TEST_NOMEM");
    pthread_mutex_lock(&m); int k = ++calls; pthread_mutex_unlock(&m);
    if (e && atoi(e) == k) return NULL;
    return calloc(n, s);
}
"""


MULTI = r"""
// multi <two|old|stress|many> [frames]: the swapchain lifecycles of a real app on headless
// surfaces, two frames in flight, and a clean teardown, so that a validation layer under the glass
// layer sees every object the glass layer makes and uses.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define CK(x) do { VkResult r_ = (x); if (r_ < 0) { fprintf(stderr, "%s = %d\n", #x, r_); exit(2); } } while (0)
#define NX 70                                 /* extra present wait semaphores in "many" (over 64) */
static VkInstance in; static VkDevice dev; static VkPhysicalDevice pd; static VkQueue q; static VkCommandPool pool;
static VkSemaphore ex[NX];
typedef struct { VkSurfaceKHR s; VkSwapchainKHR sc; uint32_t n, w; VkImage im[32]; VkSemaphore acq[2], done[32];
                 VkCommandBuffer cb[2]; VkFence fl[2]; int f; } S;
static VkSemaphore sem(void) { VkSemaphoreCreateInfo si = { VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO }; VkSemaphore s; CK(vkCreateSemaphore(dev, &si, 0, &s)); return s; }
static void drop_sems(S *x) { for (uint32_t i = 0; i < x->n; i++) vkDestroySemaphore(dev, x->done[i], 0); }
static void mk(S *x, VkFormat f, uint32_t cnt, int recreate) {
    VkSwapchainKHR old = 0;
    if (recreate) { CK(vkDeviceWaitIdle(dev)); old = x->sc; drop_sems(x); }
    else {
        memset(x, 0, sizeof *x); x->w = 64;
        PFN_vkCreateHeadlessSurfaceEXT hs = (PFN_vkCreateHeadlessSurfaceEXT)vkGetInstanceProcAddr(in, "vkCreateHeadlessSurfaceEXT");
        VkHeadlessSurfaceCreateInfoEXT hci = { VK_STRUCTURE_TYPE_HEADLESS_SURFACE_CREATE_INFO_EXT }; CK(hs(in, &hci, 0, &x->s));
        VkCommandBufferAllocateInfo ai = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, 0, pool, VK_COMMAND_BUFFER_LEVEL_PRIMARY, 2 };
        CK(vkAllocateCommandBuffers(dev, &ai, x->cb));
        for (int i = 0; i < 2; i++) {
            x->acq[i] = sem();
            VkFenceCreateInfo fci = { VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, 0, VK_FENCE_CREATE_SIGNALED_BIT }; CK(vkCreateFence(dev, &fci, 0, &x->fl[i]));
        }
    }
    VkSurfaceCapabilitiesKHR caps; CK(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(pd, x->s, &caps));
    VkSwapchainCreateInfoKHR sci = { VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR, 0, 0, x->s, cnt ? cnt : caps.minImageCount, f,
        VK_COLOR_SPACE_SRGB_NONLINEAR_KHR, { x->w, 32 }, 1, VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        VK_SHARING_MODE_EXCLUSIVE, 0, 0, VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR, VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR, VK_PRESENT_MODE_FIFO_KHR, 1, old };
    CK(vkCreateSwapchainKHR(dev, &sci, 0, &x->sc));
    if (old) vkDestroySwapchainKHR(dev, old, 0);
    x->n = 32; CK(vkGetSwapchainImagesKHR(dev, x->sc, &x->n, x->im));
    for (uint32_t i = 0; i < x->n; i++) x->done[i] = sem();
}
static void frame(S *x, int nex) {
    int k = x->f++ & 1;
    CK(vkWaitForFences(dev, 1, &x->fl[k], 1, UINT64_MAX)); CK(vkResetFences(dev, 1, &x->fl[k]));
    uint32_t idx; CK(vkAcquireNextImageKHR(dev, x->sc, UINT64_MAX, x->acq[k], 0, &idx));
    VkCommandBuffer c = x->cb[k]; CK(vkResetCommandBuffer(c, 0));
    VkCommandBufferBeginInfo bi = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, 0, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT }; CK(vkBeginCommandBuffer(c, &bi));
    VkImageMemoryBarrier b = { VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, 0, 0, VK_ACCESS_TRANSFER_WRITE_BIT, VK_IMAGE_LAYOUT_UNDEFINED,
        VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, ~0u, ~0u, x->im[idx], { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 } };
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, 0, 0, 0, 1, &b);
    VkClearColorValue cv = { .float32 = { 0x12 / 255.f, 0x13 / 255.f, 0x16 / 255.f, 1 } }; VkImageSubresourceRange r = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 };
    vkCmdClearColorImage(c, x->im[idx], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &cv, 1, &r);
    b.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL; b.newLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR; b.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT; b.dstAccessMask = 0;
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, 0, 0, 0, 0, 0, 1, &b);
    CK(vkEndCommandBuffer(c));
    VkSemaphore sig[NX + 1]; sig[0] = x->done[idx];
    for (int i = 0; i < nex; i++) sig[1 + i] = ex[i];
    VkPipelineStageFlags ws = VK_PIPELINE_STAGE_TRANSFER_BIT;
    VkSubmitInfo sub = { VK_STRUCTURE_TYPE_SUBMIT_INFO, 0, 1, &x->acq[k], &ws, 1, &c, 1 + nex, sig }; CK(vkQueueSubmit(q, 1, &sub, x->fl[k]));
    VkPresentInfoKHR pi = { VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, 0, 1 + nex, sig, 1, &x->sc, &idx, 0 }; CK(vkQueuePresentKHR(q, &pi));
}
static void drop(S *x) {
    CK(vkDeviceWaitIdle(dev)); drop_sems(x);
    for (int i = 0; i < 2; i++) { vkDestroySemaphore(dev, x->acq[i], 0); vkDestroyFence(dev, x->fl[i], 0); }
    vkFreeCommandBuffers(dev, pool, 2, x->cb); vkDestroySwapchainKHR(dev, x->sc, 0); vkDestroySurfaceKHR(in, x->s, 0);
}
int main(int argc, char **argv) {
    const char *m = argc > 1 ? argv[1] : ""; int frames = argc > 2 ? atoi(argv[2]) : 120;
    const char *ie[] = { "VK_KHR_surface", "VK_EXT_headless_surface" };
    VkApplicationInfo app = { VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1 };
    VkInstanceCreateInfo ici = { VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app, .enabledExtensionCount = 2, .ppEnabledExtensionNames = ie };
    CK(vkCreateInstance(&ici, 0, &in));
    uint32_t n = 1; vkEnumeratePhysicalDevices(in, &n, &pd);
    float prio = 1; VkDeviceQueueCreateInfo qci = { VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, 0, 0, 0, 1, &prio };
    const char *de[] = { "VK_KHR_swapchain" };
    VkDeviceCreateInfo dci = { VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qci, .enabledExtensionCount = 1, .ppEnabledExtensionNames = de };
    CK(vkCreateDevice(pd, &dci, 0, &dev)); vkGetDeviceQueue(dev, 0, 0, &q);
    VkCommandPoolCreateInfo pci = { VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, 0, VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, 0 };
    CK(vkCreateCommandPool(dev, &pci, 0, &pool));
    for (int i = 0; i < NX; i++) ex[i] = sem();
    S a, b;
    if (!strcmp(m, "two")) {                  /* BGRA, then RGBA on the same device, then BGRA again */
        mk(&a, VK_FORMAT_B8G8R8A8_UNORM, 0, 0); frame(&a, 0); frame(&a, 0);
        mk(&b, VK_FORMAT_R8G8B8A8_UNORM, 0, 0); frame(&b, 0); frame(&b, 0);
        fprintf(stderr, "--- back to the first\n");
        frame(&a, 0); frame(&a, 0); frame(&b, 0); drop(&b); frame(&a, 0); frame(&a, 0); drop(&a);
    } else if (!strcmp(m, "old")) {           /* recreate with oldSwapchain: too many images to key, then a normal one */
        mk(&a, VK_FORMAT_B8G8R8A8_UNORM, 0, 0); frame(&a, 0); frame(&a, 0);
        fprintf(stderr, "--- recreate with 17 images\n");
        mk(&a, VK_FORMAT_B8G8R8A8_UNORM, 17, 1); frame(&a, 0); frame(&a, 0);
        fprintf(stderr, "--- recreate with the minimum\n");
        mk(&a, VK_FORMAT_B8G8R8A8_UNORM, 0, 1); frame(&a, 0); frame(&a, 0); drop(&a);
    } else if (!strcmp(m, "stress")) {        /* a resize every 25 frames, like wgpu's configure */
        mk(&a, VK_FORMAT_B8G8R8A8_UNORM, 0, 0);
        for (int f = 0; f < frames; f++) { if (f && f % 25 == 0) { a.w += 8; mk(&a, VK_FORMAT_B8G8R8A8_UNORM, 0, 1); } frame(&a, 0); }
        drop(&a);
    } else if (!strcmp(m, "many")) {          /* a present that waits on more than 64 semaphores */
        mk(&a, VK_FORMAT_B8G8R8A8_UNORM, 0, 0); for (int i = 0; i < 4; i++) frame(&a, NX); drop(&a);
    } else return 1;
    CK(vkDeviceWaitIdle(dev));
    for (int i = 0; i < NX; i++) vkDestroySemaphore(dev, ex[i], 0);
    vkDestroyCommandPool(dev, pool, 0); vkDestroyDevice(dev, 0); vkDestroyInstance(in, 0);
    puts("done");
    return 0;
}
"""


def validation_dir():
    """a dir with the Khronos validation layer manifest (APPGLASS_TEST_VVL, else the system's), or None"""
    for d in (os.environ.get("APPGLASS_TEST_VVL", ""), "/usr/share/vulkan/explicit_layer.d",
              "/usr/local/share/vulkan/explicit_layer.d", "/etc/vulkan/explicit_layer.d"):
        if d and os.path.exists(os.path.join(d, "VkLayer_khronos_validation.json")):
            return d
    return None


@unittest.skipUnless(have_vulkan_dev(), "no gcc or Vulkan headers")
class Layer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="appglass-vk-")
        cls.layer_dir = os.path.join(cls.dir, "vk")
        os.mkdir(cls.layer_dir)
        cls.so = os.path.join(cls.layer_dir, "libappglass-vk.so")
        subprocess.run([GCC, "-O2", "-Wall", "-Werror", "-shared", "-fPIC", "-fvisibility=hidden",
                        "-o", cls.so, SRC, "-lpthread"], check=True, capture_output=True, timeout=120)
        shutil.copy(os.path.join(D, "appglass-vk.json"), cls.layer_dir)
        # the same layer with its calloc()s failing on demand (APPGLASS_TEST_NOMEM=<n>: the n-th)
        cls.nomem_dir = os.path.join(cls.dir, "vk-nomem")
        os.mkdir(cls.nomem_dir)
        c = os.path.join(cls.dir, "nomem.c")
        with open(c, "w") as f:
            f.write(NOMEM)
        subprocess.run([GCC, "-O2", "-Wall", "-Werror", "-shared", "-fPIC", "-fvisibility=hidden",
                        "-Dcalloc=appglass_test_calloc", "-o",
                        os.path.join(cls.nomem_dir, "libappglass-vk.so"), SRC, c, "-lpthread"],
                       check=True, capture_output=True, timeout=120)
        shutil.copy(os.path.join(D, "appglass-vk.json"), cls.nomem_dir)
        c = os.path.join(cls.dir, "client.c")
        with open(c, "w") as f:
            f.write(CLIENT)
        cls.client = os.path.join(cls.dir, "client")
        subprocess.run([GCC, "-O1", "-o", cls.client, c, "-lvulkan"], check=True,
                       capture_output=True, timeout=120)
        c = os.path.join(cls.dir, "multi.c")
        with open(c, "w") as f:
            f.write(MULTI)
        cls.multi = os.path.join(cls.dir, "multi")
        subprocess.run([GCC, "-O1", "-o", cls.multi, c, "-lvulkan"], check=True,
                       capture_output=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_exports(self):
        r = subprocess.run(["nm", "-D", "--defined-only", self.so], capture_output=True,
                           text=True, check=True)
        syms = sorted(l.split()[-1] for l in r.stdout.splitlines() if " T " in l)
        self.assertEqual(syms, ["vkGetDeviceProcAddr", "vkGetInstanceProcAddr",
                                "vkNegotiateLoaderLayerInterfaceVersion"])

    def run_client(self, fmt, layer=True, keys="121316:0.60,060607:0.65", **extra):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.dir, "XDG_CACHE_HOME": self.dir,
               "VK_DRIVER_FILES": LVP, "VK_LOADER_LAYERS_DISABLE": "~implicit~",
               "APPGLASS_DEBUG": "1", "LP_NUM_THREADS": "1"}
        if layer:
            env.update(VK_ADD_LAYER_PATH=layer if isinstance(layer, str) else self.layer_dir,
                       VK_INSTANCE_LAYERS=LAYER)
        if keys:
            env["APPGLASS_KEYS"] = keys
        env.update(extra)
        r = subprocess.run([self.client, fmt], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        px = [tuple(map(int, l.split())) for l in r.stdout.split("\n") if l.strip()]
        return px, r.stderr

    def check_keyed(self, fmt):
        (content, bar, text, edge, dbar, dcontent), log = self.run_client(fmt)
        self.assertIn("[appglass-vk]", log)
        self.assertIn("PRE_MULTIPLIED", log)
        self.assertAlmostEqual(content[3], 153, delta=1)          # 0.60
        for got, k in zip(content[:3], (0x12, 0x13, 0x16)):       # premultiplied key
            self.assertAlmostEqual(got, round(k * 0.6), delta=1)
        self.assertAlmostEqual(bar[3], 166, delta=1)              # 0.65
        self.assertEqual(text, (255, 255, 255, 255))
        # a glyph edge (half way between the key and white) stays more opaque than the glass
        self.assertGreater(edge[3], 153)
        self.assertLess(edge[3], 255)
        # wgpu dithers its fills: one 8-bit level off a key is still that key, not a darker speck
        self.assertAlmostEqual(dbar[3], 166, delta=1)
        self.assertAlmostEqual(dcontent[3], 153, delta=1)

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_keyed_rgba(self):
        self.check_keyed("R")

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_keyed_bgra(self):
        self.check_keyed("B")

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_untouched_without_keys(self):
        px, log = self.run_client("B", keys=None)
        self.assertEqual(px[0], (0x12, 0x13, 0x16, 255))
        self.assertEqual(px[1], (0x06, 0x06, 0x07, 255))
        self.assertNotIn("PRE_MULTIPLIED", log)

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_srgb_stays_opaque(self):
        """a format the pass does not key (sRGB: the shader would see linear values): the
        swapchain is made exactly as asked (OPAQUE, no extra usage) and the pixels are untouched"""
        px, log = self.run_client("S")
        self.assertIn("stays opaque: format is not 8-bit UNORM with alpha", log)
        self.assertNotIn("PRE_MULTIPLIED", log)
        self.assertEqual(px[0], (0x12, 0x13, 0x16, 255))
        self.assertEqual(px[1], (0x06, 0x06, 0x07, 255))
        self.assertEqual(px[2], (255, 255, 255, 255))

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_no_instance_record_passes_through(self):
        """no memory for the instance record: the app still gets its instance, device, swapchain
        and presents, opaque and untouched"""
        px, log = self.run_client("B", layer=self.nomem_dir, APPGLASS_TEST_NOMEM="1")
        self.assertIn("no memory for the instance record", log)
        self.assertNotIn("PRE_MULTIPLIED", log)
        self.assertEqual(px[0], (0x12, 0x13, 0x16, 255))
        self.assertEqual(px[1], (0x06, 0x06, 0x07, 255))

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_no_device_record_passes_through(self):
        """no memory for the device record: vkGetDeviceQueue, the swapchain and the present all
        reach the driver as the app made them"""
        px, log = self.run_client("B", layer=self.nomem_dir, APPGLASS_TEST_NOMEM="2")
        self.assertIn("no memory for the device record", log)
        self.assertNotIn("PRE_MULTIPLIED", log)
        self.assertEqual(px[0], (0x12, 0x13, 0x16, 255))
        self.assertEqual(px[1], (0x06, 0x06, 0x07, 255))

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_nomem_build_keys_when_nothing_fails(self):
        """the test build is the same layer: with no calloc failing it keys as usual"""
        (content, *_), log = self.run_client("B", layer=self.nomem_dir)
        self.assertIn("PRE_MULTIPLIED", log)
        self.assertAlmostEqual(content[3], 153, delta=1)

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_untouched_without_layer(self):
        px, log = self.run_client("R", layer=False)
        self.assertEqual(px[0], (0x12, 0x13, 0x16, 255))
        self.assertNotIn("[appglass-vk]", log)

    def run_multi(self, *args, extra=None):
        """the lifecycle client with the layer and keys, and the Khronos validation layer (with
        sync validation) under it when one is installed: (stdout + stderr)"""
        env = {"PATH": "/usr/bin:/bin", "HOME": self.dir, "XDG_CACHE_HOME": self.dir,
               "VK_DRIVER_FILES": LVP, "VK_LOADER_LAYERS_DISABLE": "~implicit~",
               "APPGLASS_DEBUG": "1", "LP_NUM_THREADS": "1", "APPGLASS_KEYS": "121316:0.60",
               "VK_ADD_LAYER_PATH": self.layer_dir, "VK_INSTANCE_LAYERS": LAYER}
        vvl = validation_dir()
        if vvl:
            env["VK_ADD_LAYER_PATH"] += ":" + vvl
            env["VK_INSTANCE_LAYERS"] += ":VK_LAYER_KHRONOS_validation"   # under the glass layer
            env["VK_KHRONOS_VALIDATION_VALIDATE_SYNC"] = "true"
        env.update(extra or {})
        r = subprocess.run([self.multi, *args], env=env, capture_output=True, text=True, timeout=300)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out[-4000:])
        self.assertIn("done", r.stdout)
        self.assertNotIn("Validation Error", out, out[-4000:])
        self.assertNotRegex(out, r"VUID-\w", out[-4000:])
        return out

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_two_formats_on_one_device(self):
        # a second swapchain with another format must not free the first one's pass
        log = self.run_multi("two")
        self.assertRegex(log, r"format 44, \d+ images: compositeAlpha OPAQUE -> PRE_MULTIPLIED")
        self.assertRegex(log, r"format 37, \d+ images: compositeAlpha OPAQUE -> PRE_MULTIPLIED")

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_recreate_with_old_swapchain(self):
        # 17 images is more than the layer keys: it falls back to the swapchain as asked, and
        # that retry must not pass the oldSwapchain the first call already retired
        log = self.run_multi("old")
        self.assertIn("glass setup failed", log)
        self.assertEqual(len(re.findall(r"-> PRE_MULTIPLIED", log)), 2, log)

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_stress_resizes(self):
        log = self.run_multi("stress", "120")
        self.assertEqual(len(re.findall(r"-> PRE_MULTIPLIED", log)), 5, log)

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_present_waits_on_more_than_64(self):
        # every wait semaphore of the present is waited on, none is dropped
        log = self.run_multi("many")
        self.assertIn("-> PRE_MULTIPLIED", log)

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_logs_the_device(self):
        log = self.run_multi("stress", "2")
        self.assertRegex(log, r"\[appglass-vk\] device: .*llvmpipe")
        self.assertNotIn("capped", log)          # no APPGLASS_MAXFPS: no cap

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_cpu_device_capped(self):
        """on a CPU device (wgpu fell back to lavapipe) presents keep to APPGLASS_MAXFPS"""
        t0 = time.monotonic()
        log = self.run_multi("stress", "21", extra={"APPGLASS_MAXFPS": "20"})
        took = time.monotonic() - t0
        self.assertIn("a CPU device: presents capped at 20 fps", log)
        self.assertGreaterEqual(took, 20 / 20.0 - 0.05)    # 21 presents, 20 gaps of 50 ms


class Probe(unittest.TestCase):
    """appglass-vkprobe: 0 with a device that is not the CPU, 1 with only lavapipe, else 2 (or a crash)"""

    @classmethod
    def setUpClass(cls):
        if not have_vulkan_dev():
            raise unittest.SkipTest("no gcc or Vulkan headers")
        cls.dir = tempfile.mkdtemp(prefix="appglass-vkp-")
        cls.probe = os.path.join(cls.dir, "appglass-vkprobe")
        subprocess.run([GCC, "-O2", "-Wall", "-Werror", "-o", cls.probe,
                        os.path.join(D, "appglass-vkprobe.c"), "-ldl"],
                       check=True, capture_output=True, timeout=120)
        cls.layer_dir = os.path.join(cls.dir, "vk")
        os.mkdir(cls.layer_dir)
        subprocess.run([GCC, "-O2", "-Wall", "-shared", "-fPIC", "-fvisibility=hidden", "-o",
                        os.path.join(cls.layer_dir, "libappglass-vk.so"), SRC, "-lpthread"],
                       check=True, capture_output=True, timeout=120)
        shutil.copy(os.path.join(D, "appglass-vk.json"), cls.layer_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_probe(self, layer_dir=None, **env):
        e = {"PATH": "/usr/bin:/bin", "HOME": self.dir, "XDG_CACHE_HOME": self.dir}
        if layer_dir:
            e.update(VK_ADD_LAYER_PATH=layer_dir, VK_INSTANCE_LAYERS=LAYER)
        e.update(env)
        return subprocess.run([self.probe], env=e, capture_output=True, text=True, timeout=60)

    def test_loader_dlopened(self):
        r = subprocess.run(["nm", "-D", "--undefined-only", self.probe], capture_output=True,
                           text=True, check=True)
        self.assertNotIn("vkCreateInstance", r.stdout)      # the loader is dlopen'd

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_lavapipe_only_is_cpu(self):
        r = self.run_probe(VK_DRIVER_FILES=LVP)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertRegex(r.stdout, r"(?m)^cpu llvmpipe")
        self.assertNotRegex(r.stdout, r"(?m)^gpu ")

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_with_the_layer(self):
        r = self.run_probe(self.layer_dir, VK_DRIVER_FILES=LVP)
        self.assertEqual(r.returncode, 1, r.stderr)

    def test_no_driver(self):
        r = self.run_probe(VK_DRIVER_FILES="/nonexistent/icd.json")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    @unittest.skipUnless(os.path.exists(LVP), "no lavapipe")
    def test_damaged_layer(self):
        """a truncated layer takes the probe down (or the loader refuses it), never exit 0"""
        bad = os.path.join(self.dir, "bad")
        os.makedirs(bad, exist_ok=True)
        with open(os.path.join(self.layer_dir, "libappglass-vk.so"), "rb") as f:
            head = f.read(4096)
        with open(os.path.join(bad, "libappglass-vk.so"), "wb") as f:
            f.write(head)
        shutil.copy(os.path.join(D, "appglass-vk.json"), bad)
        r = subprocess.run(["sh", "-c", "ulimit -c 0; exec \"$0\"", self.probe], timeout=60,
                           env={"PATH": "/usr/bin:/bin", "HOME": self.dir, "VK_DRIVER_FILES": LVP,
                                "VK_ADD_LAYER_PATH": bad, "VK_INSTANCE_LAYERS": LAYER},
                           capture_output=True, text=True)
        self.assertNotIn(r.returncode, (0, 1))


WRAPPER = os.path.join(REPO, "shims", "ck-shim", "appglass-artcraft")


def stub_appglass(text):
    """the wrapper with the appglass calls stubbed: no levels, the family's default dark keys,
    no launch-check"""
    return (text.replace('"@APPGLASS@" levels', "false")
            .replace('"@APPGLASS@" keys "$AGKEY" dark', "echo 121316:0.6,151517:0.6,060607:0.65")
            .replace('setsid -f "@APPGLASS@" launch-check', "true"))


class Wrapper(unittest.TestCase):
    def setUp(self):
        with open(WRAPPER) as f:
            self.text = f.read()

    def test_syntax(self):
        r = subprocess.run(["sh", "-n", WRAPPER], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_private_layer_only(self):
        self.assertIn('LAYERS="$LIB/vk${VK_ADD_LAYER_PATH:+:', self.text)
        self.assertIn('VK_ADD_LAYER_PATH="$LAYERS"', self.text)
        self.assertIn("INST=" + LAYER, self.text)
        self.assertIn("WGPU_BACKEND=vulkan", self.text)
        for g in ("explicit_layer", "implicit_layer", ".local/share/vulkan"):
            self.assertNotIn(g, self.text)
        # no system Vulkan dir at all: the probe asks the loader
        self.assertEqual([l for l in self.text.splitlines() if "/vulkan" in l and not l.startswith("#")], [])

    def run_wrapped(self, gpu=True, probe=None, **user):
        """the wrapper around a fake launcher on a host where the Vulkan probe finds a GPU (or, gpu
        False, only lavapipe; probe: the stub probe's own shell code), with the user's env plus
        `user`: (parent env, child env); the probe's env is in self.probe_env"""
        d = tempfile.mkdtemp(prefix="appglass-vkw-")
        try:
            lib = os.path.join(d, ".local", "lib", "appglass", "artcraft")
            os.makedirs(os.path.join(lib, "vk"))
            open(os.path.join(d, "mesa.json"), "w").close()
            with open(os.path.join(lib, "vk", "appglass-vkprobe"), "w") as f:
                f.write("#!/bin/sh\n/usr/bin/env > \"$HOME/probe.env\"\n%s\n"
                        % (probe or ("echo 'gpu Fake GPU'" if gpu else "echo 'cpu llvmpipe'; exit 1")))
            os.chmod(os.path.join(lib, "vk", "appglass-vkprobe"), 0o755)
            subprocess.run([GCC, "-O2", "-shared", "-fPIC", "-o", os.path.join(lib, "appglass-ck.so"),
                            os.path.join(REPO, "shims", "ck-shim", "appglass-ck.c"), "-ldl", "-lpthread"],
                           check=True, capture_output=True, timeout=120)
            for n in ("libappglass-vk.so", "appglass-vk.json"):
                open(os.path.join(lib, "vk", n), "w").close()
            app = os.path.join(d, "app")
            with open(app, "w") as f:
                # the parent's own env through shell builtins (an exec'd env would already be a child)
                f.write("#!/bin/sh\nprintf '%s\\n' \"VK_INSTANCE_LAYERS=${VK_INSTANCE_LAYERS:-}\" "
                        "\"VK_ADD_LAYER_PATH=${VK_ADD_LAYER_PATH:-}\" \"WGPU_BACKEND=${WGPU_BACKEND:-}\" "
                        "\"APPGLASS_KEYS=${APPGLASS_KEYS:-}\" \"APPGLASS_MAXFPS=${APPGLASS_MAXFPS:-}\" "
                        "\"__EGL_VENDOR_LIBRARY_FILENAMES=${__EGL_VENDOR_LIBRARY_FILENAMES:-}\" "
                        "\"LP_NUM_THREADS=${LP_NUM_THREADS:-}\" > \"$HOME/parent.env\"\n"
                        "/usr/bin/env > \"$HOME/child.env\"\n")
            os.chmod(app, 0o755)
            w = os.path.join(d, "wrapper")
            text = stub_appglass(self.text)
            for var, val in (("BIN", app), ("MESA", os.path.join(d, "mesa.json"))):
                text, n = re.subn(r"(?m)^%s=.*$" % var, "%s='%s'" % (var, val), text)
                self.assertEqual(n, 1, var)
            os.makedirs(os.path.join(d, "bin"))
            with open(os.path.join(d, "bin", "gsettings"), "w") as f:
                f.write("#!/bin/sh\necho \"'prefer-dark'\"\n")
            os.chmod(os.path.join(d, "bin", "gsettings"), 0o755)
            with open(w, "w") as f:
                f.write(text)
            env = {"PATH": os.path.join(d, "bin") + ":/usr/bin:/bin", "HOME": d,
                   "XDG_CACHE_HOME": os.path.join(d, "c")}
            env.update(user)
            r = subprocess.run(["sh", w], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(d, "parent.env")) as f:
                parent = f.read()
            with open(os.path.join(d, "child.env")) as f:
                child = f.read()
            self.probe_env = None
            if os.path.exists(os.path.join(d, "probe.env")):
                with open(os.path.join(d, "probe.env")) as f:
                    self.probe_env = dict(l.split("=", 1) for l in f.read().splitlines() if "=" in l)
            return parent, child
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(GCC, "no gcc")
    def test_child_scrubbed(self):
        """the launcher keeps the layer env; a program it starts gets none of it"""
        parent, child = self.run_wrapped()
        self.assertIn("VK_INSTANCE_LAYERS=" + LAYER, parent)
        self.assertIn("APPGLASS_KEYS=121316:", parent)
        for v in ("VK_INSTANCE_LAYERS", "VK_ADD_LAYER_PATH", "WGPU_BACKEND", "APPGLASS_",
                  "appglass-ck.so"):
            self.assertNotIn(v, child)

    @unittest.skipUnless(GCC, "no gcc")
    def test_child_gets_the_users_own_values(self):
        """values the user had set reach the children as they were, without the layer in them"""
        user = {"VK_INSTANCE_LAYERS": "VK_LAYER_MINE", "VK_ADD_LAYER_PATH": "/opt/mine",
                "WGPU_BACKEND": "gl", "VK_DRIVER_FILES": "/opt/icd.json",
                "__EGL_VENDOR_LIBRARY_FILENAMES": "/opt/50_mesa.json", "LP_NUM_THREADS": "2",
                "APPGLASS_MAXFPS": "30"}
        parent, child = self.run_wrapped(**user)
        self.assertIn("__EGL_VENDOR_LIBRARY_FILENAMES=\n", parent)   # NVIDIA's Vulkan WSI needs its EGL
        self.assertIn("LP_NUM_THREADS=2\n", parent)
        self.assertIn("VK_INSTANCE_LAYERS=%s:VK_LAYER_MINE\n" % LAYER, parent)
        self.assertIn("/vk:/opt/mine\n", parent)
        self.assertIn("WGPU_BACKEND=vulkan\n", parent)
        env = dict(l.split("=", 1) for l in child.splitlines() if "=" in l)
        for k, v in user.items():
            self.assertEqual(env.get(k), v, k)
        self.assertFalse([k for k in env if k.startswith("APPGLASS_") and k != "APPGLASS_MAXFPS"])
        self.assertNotIn(LAYER, child)
        self.assertNotIn("appglass-ck.so", child)
        self.assertNotIn("artcraft/vk", child)

    @unittest.skipUnless(GCC, "no gcc")
    def test_gpu_route_env(self):
        """GPU route: the cap is there for the layer, which keeps to it only on a CPU device, and
        llvmpipe is held to 4 threads (in case wgpu still lands on lavapipe); no EGL vendor
        override; a child gets none of it"""
        parent, child = self.run_wrapped()
        for line in ("WGPU_BACKEND=vulkan", "APPGLASS_MAXFPS=60", "LP_NUM_THREADS=4",
                     "__EGL_VENDOR_LIBRARY_FILENAMES="):
            self.assertIn(line + "\n", parent)
        for v in ("LP_NUM_THREADS", "__EGL_VENDOR_LIBRARY_FILENAMES", "APPGLASS_"):
            self.assertNotIn(v, child)

    @unittest.skipUnless(GCC, "no gcc")
    def test_probe_env(self):
        """the probe sees the launcher's Vulkan env with the glass layer on, no keys"""
        self.run_wrapped(VK_INSTANCE_LAYERS="VK_LAYER_MINE", __EGL_VENDOR_LIBRARY_FILENAMES="/x.json")
        e = self.probe_env
        self.assertEqual(e["VK_INSTANCE_LAYERS"], LAYER + ":VK_LAYER_MINE")
        self.assertTrue(e["VK_ADD_LAYER_PATH"].endswith("/.local/lib/appglass/artcraft/vk"), e)
        for k in ("__EGL_VENDOR_LIBRARY_FILENAMES", "APPGLASS_KEYS", "LD_PRELOAD"):
            self.assertNotIn(k, e)

    @unittest.skipUnless(GCC, "no gcc")
    def test_probe_fails_cpu_route(self):
        """no device, only lavapipe or a crash (a damaged layer: SIGBUS): the CPU route, not a
        launcher without a window"""
        for code in ("exit 2", "kill -BUS $$", "echo 'gpu x'; kill -SEGV $$"):
            parent, child = self.run_wrapped(probe=code)
            self.assertIn("WGPU_BACKEND=gl\n", parent, code)
        parent, child = self.run_wrapped(gpu=False)
        self.assertIn("WGPU_BACKEND=gl\n", parent)

    @unittest.skipUnless(GCC, "no gcc")
    def test_cpu_route_child_gets_the_users_own_values(self):
        user = {"WGPU_BACKEND": "vulkan", "__EGL_VENDOR_LIBRARY_FILENAMES": "/opt/10_nvidia.json",
                "LP_NUM_THREADS": "2", "APPGLASS_MAXFPS": "30"}
        parent, child = self.run_wrapped(gpu=False, **user)
        for line in ("WGPU_BACKEND=gl", "LP_NUM_THREADS=2", "APPGLASS_MAXFPS=30"):
            self.assertIn(line + "\n", parent)
        self.assertNotIn("__EGL_VENDOR_LIBRARY_FILENAMES=/opt/10_nvidia.json\n", parent)
        env = dict(l.split("=", 1) for l in child.splitlines() if "=" in l)
        for k, v in user.items():
            self.assertEqual(env.get(k), v, k)
        self.assertFalse([k for k in env if k.startswith("APPGLASS_") and k != "APPGLASS_MAXFPS"])

    @unittest.skipUnless(GCC, "no gcc")
    def test_cpu_route_child_scrubbed(self):
        """the CPU route (no Vulkan GPU): the launcher gets llvmpipe and the cap, a child none of it"""
        parent, child = self.run_wrapped(gpu=False)
        self.assertIn("WGPU_BACKEND=gl\n", parent)
        self.assertIn("APPGLASS_MAXFPS=60\n", parent)
        self.assertIn("LP_NUM_THREADS=4\n", parent)
        self.assertIn("VK_INSTANCE_LAYERS=\n", parent)
        for v in ("VK_INSTANCE_LAYERS", "VK_ADD_LAYER_PATH", "WGPU_BACKEND", "APPGLASS_",
                  "__EGL_VENDOR_LIBRARY_FILENAMES", "LP_NUM_THREADS", "appglass-ck.so"):
            self.assertNotIn(v, child)

    @unittest.skipUnless(GCC, "no gcc")
    def test_cpu_knob(self):
        parent, child = self.run_wrapped(APPGLASS_ARTCRAFT="cpu")
        self.assertIn("WGPU_BACKEND=gl\n", parent)
        self.assertIn("VK_INSTANCE_LAYERS=\n", parent)
        self.assertNotIn("APPGLASS_", child)


if __name__ == "__main__":
    unittest.main()
