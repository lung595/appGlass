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
* the GPU wrapper prototype only adds the layer through its own env, and a child the
  launcher starts loses all of it (the ck-shim scrub).
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
// client <R|B> : headless OPAQUE swapchain 64x32, fill, present, read the presented image back.
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
    int bgr = argv[1][0] == 'B'; VkFormat fmt = bgr ? VK_FORMAT_B8G8R8A8_UNORM : VK_FORMAT_R8G8B8A8_UNORM;
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
    int at[][2] = { { 30, 20 }, { 30, 2 }, { 44, 20 }, { 10, 20 } };   /* content, bar, text, edge */
    for (int i = 0; i < 4; i++) {
        uint8_t *p = px + (at[i][1] * W + at[i][0]) * 4;
        printf("%d %d %d %d\n", bgr ? p[2] : p[0], p[1], bgr ? p[0] : p[2], p[3]);
    }
    vkDestroySwapchainKHR(dev, sc, 0); vkDestroyDevice(dev, 0); vkDestroySurfaceKHR(in, surf, 0); vkDestroyInstance(in, 0);
    return 0;
}
"""


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
        c = os.path.join(cls.dir, "client.c")
        with open(c, "w") as f:
            f.write(CLIENT)
        cls.client = os.path.join(cls.dir, "client")
        subprocess.run([GCC, "-O1", "-o", cls.client, c, "-lvulkan"], check=True,
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

    def run_client(self, fmt, layer=True, keys="121316:0.60,060607:0.65"):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.dir, "XDG_CACHE_HOME": self.dir,
               "VK_DRIVER_FILES": LVP, "VK_LOADER_LAYERS_DISABLE": "~implicit~",
               "APPGLASS_DEBUG": "1", "LP_NUM_THREADS": "1"}
        if layer:
            env.update(VK_ADD_LAYER_PATH=self.layer_dir, VK_INSTANCE_LAYERS=LAYER)
        if keys:
            env["APPGLASS_KEYS"] = keys
        r = subprocess.run([self.client, fmt], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        px = [tuple(map(int, l.split())) for l in r.stdout.split("\n") if l.strip()]
        return px, r.stderr

    def check_keyed(self, fmt):
        (content, bar, text, edge), log = self.run_client(fmt)
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
    def test_untouched_without_layer(self):
        px, log = self.run_client("R", layer=False)
        self.assertEqual(px[0], (0x12, 0x13, 0x16, 255))
        self.assertNotIn("[appglass-vk]", log)


WRAPPER = os.path.join(D, "appglass-artcraft-gpu")


class Wrapper(unittest.TestCase):
    def setUp(self):
        with open(WRAPPER) as f:
            self.text = f.read()

    def test_syntax(self):
        r = subprocess.run(["sh", "-n", WRAPPER], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_private_layer_only(self):
        self.assertIn('VK_ADD_LAYER_PATH="$LIB/vk', self.text)
        self.assertIn("VK_INSTANCE_LAYERS=" + LAYER, self.text)
        self.assertIn("WGPU_BACKEND=vulkan", self.text)
        for g in ("/usr/share/vulkan", "/etc/vulkan", ".local/share/vulkan", "implicit_layer"):
            self.assertNotIn(g, self.text)

    @unittest.skipUnless(GCC, "no gcc")
    def test_child_scrubbed(self):
        """the launcher keeps the layer env; a program it starts gets none of it"""
        d = tempfile.mkdtemp(prefix="appglass-vkw-")
        try:
            lib = os.path.join(d, ".local", "lib", "appglass", "artcraft")
            os.makedirs(os.path.join(lib, "vk"))
            subprocess.run([GCC, "-O2", "-shared", "-fPIC", "-o", os.path.join(lib, "appglass-ck.so"),
                            os.path.join(REPO, "shims", "ck-shim", "appglass-ck.c"), "-ldl", "-lpthread"],
                           check=True, capture_output=True, timeout=120)
            for n in ("libappglass-vk.so", "appglass-vk.json"):
                open(os.path.join(lib, "vk", n), "w").close()
            app = os.path.join(d, "app")
            with open(app, "w") as f:
                # the parent's own env through shell builtins (an exec'd env would already be a child)
                f.write("#!/bin/sh\nprintf '%s\\n' \"VK_INSTANCE_LAYERS=${VK_INSTANCE_LAYERS:-}\" "
                        "\"APPGLASS_KEYS=${APPGLASS_KEYS:-}\" > \"$HOME/parent.env\"\n"
                        "/usr/bin/env > \"$HOME/child.env\"\n")
            os.chmod(app, 0o755)
            w = os.path.join(d, "wrapper")
            with open(w, "w") as f:
                f.write(self.text.replace("BIN=/usr/bin/artcraft-launcher", "BIN=" + app)
                        .replace('"@APPGLASS@" levels', "false"))
            env = {"PATH": "/usr/bin:/bin", "HOME": d, "XDG_CACHE_HOME": os.path.join(d, "c")}
            r = subprocess.run(["sh", w], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(d, "parent.env")) as f:
                parent = f.read()
            with open(os.path.join(d, "child.env")) as f:
                child = f.read()
            self.assertIn("VK_INSTANCE_LAYERS=" + LAYER, parent)
            self.assertIn("APPGLASS_KEYS=121316:", parent)
            for v in ("VK_INSTANCE_LAYERS", "VK_ADD_LAYER_PATH", "WGPU_BACKEND", "APPGLASS_",
                      "appglass-ck.so"):
                self.assertNotIn(v, child)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
