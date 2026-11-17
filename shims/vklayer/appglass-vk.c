// libappglass-vk.so: "colour-key glass" for Vulkan apps that present opaque swapchains.
// An explicit Vulkan layer (manifest appglass-vk.json, never installed as an implicit layer):
// the launch wrapper turns it on for one app with
//     VK_ADD_LAYER_PATH=<private dir> VK_INSTANCE_LAYERS=VK_LAYER_APPGLASS_glass APPGLASS_KEYS="121316:0.60,..."
// [APPGLASS_TOL=0.02] [APPGLASS_SNAP=0.75] [APPGLASS_DEBUG=1] [APPGLASS_TRACE=file]
// (the same key format and defaults as appglass-ck.so, which the wrapper preloads as well for the
// opaque region and the child env scrub).
//
// With keys set, vkCreateSwapchainKHR asks for compositeAlpha PRE_MULTIPLIED (the app asked for
// OPAQUE) and adds INPUT_ATTACHMENT to the image usage, but only when the surface offers both, the
// format is 8-bit UNORM with alpha (RGBA, BGRA, ABGR), the colour space is sRGB-nonlinear and
// every queue the app made can do graphics. Otherwise the swapchain is created exactly as asked
// (opaque) and the reason is logged. vkQueuePresentKHR then runs one full-screen draw per presented
// image (glass.frag) between the app's rendering and the present: the image is both the input
// attachment and the colour attachment, each fragment reads its own pixel and writes the keyed,
// premultiplied value. One submit per keyed swapchain, chained on the app's wait semaphores; the
// present waits on the last one. Without APPGLASS_KEYS the layer only passes calls through.
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <vulkan/vk_layer.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "glass-spv.h"

#define EXPORT __attribute__((visibility("default")))
#define LAYER_NAME "VK_LAYER_APPGLASS_glass"

static int dbg(void) { static int d = -1; if (d < 0) d = getenv("APPGLASS_DEBUG") != NULL; return d; }
#define LOG(...) do { if (dbg()) { fprintf(stderr, "[appglass-vk] " __VA_ARGS__); fputc('\n', stderr); } } while (0)

/* ---------------- keys (same syntax as appglass-ck.c) ---------------- */
#define MAXK 8
static struct { uint32_t key[MAXK]; float prm[4]; } pc;   /* push constants: 0xRRGGBBAA, (n, tol, snap, 0) */
static int nkeys;
static void parse_keys(void) {
    const char *s = getenv("APPGLASS_KEYS"), *e;
    float tol = 0.02f, snap = 0.75f;
    if ((e = getenv("APPGLASS_TOL"))) tol = strtof(e, NULL);
    if ((e = getenv("APPGLASS_SNAP"))) snap = strtof(e, NULL);
    while (s && *s && nkeys < MAXK) {
        unsigned rgb; float a; int n = 0;
        if (sscanf(s, "%6x:%f%n", &rgb, &a, &n) != 2) break;
        if (a < 0) a = 0;
        if (a > 1) a = 1;
        pc.key[nkeys++] = (rgb & 0xffffffu) << 8 | (uint32_t)(a * 255.0f + 0.5f);
        s += n; while (*s == ',' || *s == ' ') s++;
    }
    pc.prm[0] = (float)nkeys; pc.prm[1] = tol; pc.prm[2] = snap;
    LOG("%d keys, tol %.3f snap %.2f", nkeys, tol, snap);
}
static pthread_once_t keys_once = PTHREAD_ONCE_INIT;
static int keys(void) { pthread_once(&keys_once, parse_keys); return nkeys; }

/* ---------------- dispatch ---------------- */
static void *key_of(const void *h) { return *(void *const *)h; }   /* the loader's dispatch table pointer */
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;

typedef struct inst {
    void *key; VkInstance h; struct inst *next;
    PFN_vkGetInstanceProcAddr gipa;
    PFN_vkDestroyInstance DestroyInstance;
    PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR GetPhysicalDeviceSurfaceCapabilitiesKHR;
    PFN_vkGetPhysicalDeviceQueueFamilyProperties GetPhysicalDeviceQueueFamilyProperties;
} inst;
static inst *insts;

#define DEV_FNS(X) X(DestroyDevice) X(CreateSwapchainKHR) X(DestroySwapchainKHR) X(GetSwapchainImagesKHR) X(QueuePresentKHR) \
    X(GetDeviceQueue) X(GetDeviceQueue2) X(CreateImageView) X(DestroyImageView) X(CreateShaderModule) X(DestroyShaderModule) \
    X(CreateRenderPass) X(DestroyRenderPass) X(CreateFramebuffer) X(DestroyFramebuffer) X(CreateDescriptorSetLayout) \
    X(DestroyDescriptorSetLayout) X(CreatePipelineLayout) X(DestroyPipelineLayout) X(CreateGraphicsPipelines) X(DestroyPipeline) \
    X(CreateDescriptorPool) X(DestroyDescriptorPool) X(AllocateDescriptorSets) X(UpdateDescriptorSets) X(CreateCommandPool) \
    X(DestroyCommandPool) X(AllocateCommandBuffers) X(BeginCommandBuffer) X(EndCommandBuffer) X(CmdBeginRenderPass) \
    X(CmdEndRenderPass) X(CmdBindPipeline) X(CmdBindDescriptorSets) X(CmdPushConstants) X(CmdSetViewport) X(CmdSetScissor) \
    X(CmdDraw) X(QueueSubmit) X(CreateFence) X(DestroyFence) X(WaitForFences) X(ResetFences) X(CreateSemaphore) X(DestroySemaphore)

typedef struct pipe { VkFormat fmt; VkRenderPass rp; VkDescriptorSetLayout dsl; VkPipelineLayout pl; VkPipeline p; } pipe;
#define MAXQ 16
typedef struct dev {
    void *key; VkDevice h; VkPhysicalDevice pd; inst *in; struct dev *next;
    PFN_vkGetDeviceProcAddr gdpa; PFN_vkSetDeviceLoaderData set_data;
    int graphics_only;                   /* every queue family the app asked for can do graphics */
    struct { VkQueue q; uint32_t fam; } qs[MAXQ]; int nq;
    pipe pp;                             /* the pass for one format (rebuilt when another one shows up) */
#define X(n) PFN_vk##n n;
    DEV_FNS(X)
#undef X
} dev;
static dev *devs;

static inst *inst_by_key(void *k) { for (inst *i = insts; i; i = i->next) if (i->key == k) return i; return NULL; }
static dev *dev_by_key(void *k) { for (dev *d = devs; d; d = d->next) if (d->key == k) return d; return NULL; }

/* ---------------- swapchains ---------------- */
#define MAXI 16
typedef struct sc {
    VkSwapchainKHR h; dev *d; struct sc *next;
    VkExtent2D ext; uint32_t n; VkCommandPool pool; VkDescriptorPool dp;
    VkImage img[MAXI]; VkImageView view[MAXI]; VkFramebuffer fb[MAXI]; VkDescriptorSet ds[MAXI];
    VkCommandBuffer cb[MAXI]; VkFence fence[MAXI]; VkSemaphore sem[MAXI];
} sc;
static sc *scs;
static sc *sc_find(VkSwapchainKHR h) { for (sc *s = scs; s; s = s->next) if (s->h == h) return s; return NULL; }

static void sc_free(sc *s) {
    dev *d = s->d;
    for (uint32_t i = 0; i < s->n; i++) {
        if (s->fence[i]) { d->WaitForFences(d->h, 1, &s->fence[i], VK_TRUE, 1000000000ull); d->DestroyFence(d->h, s->fence[i], NULL); }
        if (s->sem[i]) d->DestroySemaphore(d->h, s->sem[i], NULL);
        if (s->fb[i]) d->DestroyFramebuffer(d->h, s->fb[i], NULL);
        if (s->view[i]) d->DestroyImageView(d->h, s->view[i], NULL);
    }
    if (s->pool) d->DestroyCommandPool(d->h, s->pool, NULL);
    if (s->dp) d->DestroyDescriptorPool(d->h, s->dp, NULL);
    free(s);
}

static void pipe_free(dev *d) {
    pipe *p = &d->pp;
    if (p->p) d->DestroyPipeline(d->h, p->p, NULL);
    if (p->pl) d->DestroyPipelineLayout(d->h, p->pl, NULL);
    if (p->dsl) d->DestroyDescriptorSetLayout(d->h, p->dsl, NULL);
    if (p->rp) d->DestroyRenderPass(d->h, p->rp, NULL);
    memset(p, 0, sizeof *p);
}

/* render pass + pipeline for one swapchain format */
static int pipe_for(dev *d, VkFormat fmt) {
    pipe *p = &d->pp;
    if (p->p && p->fmt == fmt) return 1;
    pipe_free(d);
    p->fmt = fmt;
    VkAttachmentDescription at = { 0, fmt, VK_SAMPLE_COUNT_1_BIT, VK_ATTACHMENT_LOAD_OP_LOAD, VK_ATTACHMENT_STORE_OP_STORE,
        VK_ATTACHMENT_LOAD_OP_DONT_CARE, VK_ATTACHMENT_STORE_OP_DONT_CARE, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR };
    VkAttachmentReference ref = { 0, VK_IMAGE_LAYOUT_GENERAL };   /* input and colour at once: GENERAL */
    VkSubpassDescription sp = { 0, VK_PIPELINE_BIND_POINT_GRAPHICS, 1, &ref, 1, &ref, NULL, NULL, 0, NULL };
    const VkPipelineStageFlags st = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT;
    VkSubpassDependency dep[2] = {
        { VK_SUBPASS_EXTERNAL, 0, st, st, 0,
          VK_ACCESS_INPUT_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, 0 },
        { 0, VK_SUBPASS_EXTERNAL, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,
          VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, 0, 0 } };
    VkRenderPassCreateInfo rpi = { VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO, NULL, 0, 1, &at, 1, &sp, 2, dep };
    if (d->CreateRenderPass(d->h, &rpi, NULL, &p->rp)) goto fail;
    VkDescriptorSetLayoutBinding b = { 0, VK_DESCRIPTOR_TYPE_INPUT_ATTACHMENT, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL };
    VkDescriptorSetLayoutCreateInfo dli = { VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, NULL, 0, 1, &b };
    if (d->CreateDescriptorSetLayout(d->h, &dli, NULL, &p->dsl)) goto fail;
    VkPushConstantRange pr = { VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof pc };
    VkPipelineLayoutCreateInfo pli = { VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, NULL, 0, 1, &p->dsl, 1, &pr };
    if (d->CreatePipelineLayout(d->h, &pli, NULL, &p->pl)) goto fail;
    VkShaderModule vs = 0, fs = 0;
    VkShaderModuleCreateInfo vmi = { VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, NULL, 0, sizeof glass_vert_spv, glass_vert_spv };
    VkShaderModuleCreateInfo fmi = { VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, NULL, 0, sizeof glass_frag_spv, glass_frag_spv };
    if (d->CreateShaderModule(d->h, &vmi, NULL, &vs) || d->CreateShaderModule(d->h, &fmi, NULL, &fs)) {
        if (vs) d->DestroyShaderModule(d->h, vs, NULL);
        goto fail;
    }
    VkPipelineShaderStageCreateInfo stages[2] = {
        { VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_VERTEX_BIT, vs, "main", NULL },
        { VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_FRAGMENT_BIT, fs, "main", NULL } };
    VkPipelineVertexInputStateCreateInfo vi = { VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO };
    VkPipelineInputAssemblyStateCreateInfo ia = { VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, NULL, 0, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST, VK_FALSE };
    VkPipelineViewportStateCreateInfo vp = { VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, NULL, 0, 1, NULL, 1, NULL };
    VkPipelineRasterizationStateCreateInfo rs = { VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, NULL, 0, VK_FALSE, VK_FALSE,
        VK_POLYGON_MODE_FILL, VK_CULL_MODE_NONE, VK_FRONT_FACE_COUNTER_CLOCKWISE, VK_FALSE, 0, 0, 0, 1.0f };
    VkPipelineMultisampleStateCreateInfo ms = { VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, NULL, 0, VK_SAMPLE_COUNT_1_BIT };
    VkPipelineColorBlendAttachmentState cba = { VK_FALSE, 0, 0, 0, 0, 0, 0, 0xf };
    VkPipelineColorBlendStateCreateInfo cb = { VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, NULL, 0, VK_FALSE, 0, 1, &cba, { 0 } };
    VkDynamicState dyn[2] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR };
    VkPipelineDynamicStateCreateInfo ds = { VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO, NULL, 0, 2, dyn };
    VkGraphicsPipelineCreateInfo gpi = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, NULL, 0, 2, stages, &vi, &ia, NULL, &vp, &rs, &ms,
        NULL, &cb, &ds, p->pl, p->rp, 0, 0, -1 };
    VkResult r = d->CreateGraphicsPipelines(d->h, 0, 1, &gpi, NULL, &p->p);
    d->DestroyShaderModule(d->h, vs, NULL); d->DestroyShaderModule(d->h, fs, NULL);
    if (r) goto fail;
    return 1;
fail:
    LOG("could not build the pass for format %d", fmt);
    pipe_free(d); return 0;
}

/* per-image views, framebuffers, descriptor sets, fences, semaphores; command buffers come at the first present */
static int sc_init(sc *s, VkFormat fmt) {
    dev *d = s->d;
    if (!pipe_for(d, fmt)) return 0;
    VkDescriptorPoolSize ps = { VK_DESCRIPTOR_TYPE_INPUT_ATTACHMENT, s->n };
    VkDescriptorPoolCreateInfo dpi = { VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, NULL, 0, s->n, 1, &ps };
    if (d->CreateDescriptorPool(d->h, &dpi, NULL, &s->dp)) return 0;
    VkDescriptorSetLayout l[MAXI];
    for (uint32_t i = 0; i < s->n; i++) l[i] = d->pp.dsl;
    VkDescriptorSetAllocateInfo dai = { VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, NULL, s->dp, s->n, l };
    if (d->AllocateDescriptorSets(d->h, &dai, s->ds)) return 0;
    for (uint32_t i = 0; i < s->n; i++) {
        VkImageViewCreateInfo vi = { VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, NULL, 0, s->img[i], VK_IMAGE_VIEW_TYPE_2D, fmt, { 0 },
            { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 } };
        if (d->CreateImageView(d->h, &vi, NULL, &s->view[i])) return 0;
        VkFramebufferCreateInfo fi = { VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, NULL, 0, d->pp.rp, 1, &s->view[i], s->ext.width, s->ext.height, 1 };
        if (d->CreateFramebuffer(d->h, &fi, NULL, &s->fb[i])) return 0;
        VkDescriptorImageInfo ii = { 0, s->view[i], VK_IMAGE_LAYOUT_GENERAL };
        VkWriteDescriptorSet w = { VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, s->ds[i], 0, 0, 1, VK_DESCRIPTOR_TYPE_INPUT_ATTACHMENT, &ii, NULL, NULL };
        d->UpdateDescriptorSets(d->h, 1, &w, 0, NULL);
        VkFenceCreateInfo fci = { VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, NULL, VK_FENCE_CREATE_SIGNALED_BIT };
        if (d->CreateFence(d->h, &fci, NULL, &s->fence[i])) return 0;
        VkSemaphoreCreateInfo sci = { VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO };
        if (d->CreateSemaphore(d->h, &sci, NULL, &s->sem[i])) return 0;
    }
    return 1;
}

static int sc_record(sc *s, uint32_t fam) {
    dev *d = s->d;
    VkCommandPoolCreateInfo pci = { VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, NULL, 0, fam };
    if (d->CreateCommandPool(d->h, &pci, NULL, &s->pool)) return 0;
    VkCommandBufferAllocateInfo ai = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL, s->pool, VK_COMMAND_BUFFER_LEVEL_PRIMARY, s->n };
    if (d->AllocateCommandBuffers(d->h, &ai, s->cb)) return 0;
    for (uint32_t i = 0; i < s->n; i++) {
        VkCommandBuffer c = s->cb[i];
        if (d->set_data) d->set_data(d->h, c); else *(void **)c = d->key;   /* layer-made dispatchable object */
        VkCommandBufferBeginInfo bi = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO };
        if (d->BeginCommandBuffer(c, &bi)) return 0;
        VkRenderPassBeginInfo rb = { VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, NULL, d->pp.rp, s->fb[i], { { 0, 0 }, s->ext }, 0, NULL };
        d->CmdBeginRenderPass(c, &rb, VK_SUBPASS_CONTENTS_INLINE);
        d->CmdBindPipeline(c, VK_PIPELINE_BIND_POINT_GRAPHICS, d->pp.p);
        d->CmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_GRAPHICS, d->pp.pl, 0, 1, &s->ds[i], 0, NULL);
        d->CmdPushConstants(c, d->pp.pl, VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof pc, &pc);
        VkViewport v = { 0, 0, (float)s->ext.width, (float)s->ext.height, 0, 1 };
        VkRect2D r = { { 0, 0 }, s->ext };
        d->CmdSetViewport(c, 0, 1, &v); d->CmdSetScissor(c, 0, 1, &r);
        d->CmdDraw(c, 3, 1, 0, 0);
        d->CmdEndRenderPass(c);
        if (d->EndCommandBuffer(c)) return 0;
    }
    return 1;
}

/* why a swapchain stays opaque, or NULL when it can be glass */
static const char *refuse(dev *d, const VkSwapchainCreateInfoKHR *ci) {
    switch (ci->imageFormat) {
    case VK_FORMAT_R8G8B8A8_UNORM: case VK_FORMAT_B8G8R8A8_UNORM: case VK_FORMAT_A8B8G8R8_UNORM_PACK32: break;
    default: return "format is not 8-bit UNORM with alpha";
    }
    if (ci->imageColorSpace != VK_COLOR_SPACE_SRGB_NONLINEAR_KHR) return "colour space is not sRGB nonlinear";
    if (ci->imageArrayLayers != 1) return "layered swapchain";
    if (!d->graphics_only) return "a queue family without graphics";
    if (!d->in->GetPhysicalDeviceSurfaceCapabilitiesKHR) return "no surface caps entry point";
    VkSurfaceCapabilitiesKHR c;
    if (d->in->GetPhysicalDeviceSurfaceCapabilitiesKHR(d->pd, ci->surface, &c)) return "surface caps query failed";
    if (!(c.supportedCompositeAlpha & VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR)) return "the surface offers no PRE_MULTIPLIED alpha";
    if (!(c.supportedUsageFlags & VK_IMAGE_USAGE_INPUT_ATTACHMENT_BIT)) return "the surface offers no INPUT_ATTACHMENT usage";
    return NULL;
}

static VKAPI_ATTR VkResult VKAPI_CALL hk_CreateSwapchainKHR(VkDevice device, const VkSwapchainCreateInfoKHR *ci,
                                                           const VkAllocationCallbacks *al, VkSwapchainKHR *out) {
    pthread_mutex_lock(&mu);
    dev *d = dev_by_key(key_of(device));
    pthread_mutex_unlock(&mu);
    if (!d) return VK_ERROR_INITIALIZATION_FAILED;
    if (!keys()) { LOG("no keys: swapchain passed through"); return d->CreateSwapchainKHR(device, ci, al, out); }
    const char *why = refuse(d, ci);
    if (why) { LOG("swapchain %ux%u stays opaque: %s", ci->imageExtent.width, ci->imageExtent.height, why); return d->CreateSwapchainKHR(device, ci, al, out); }
    VkSwapchainCreateInfoKHR m = *ci;
    m.compositeAlpha = VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR;
    m.imageUsage |= VK_IMAGE_USAGE_INPUT_ATTACHMENT_BIT | VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
    VkResult r = d->CreateSwapchainKHR(device, &m, al, out);
    if (r) { LOG("glass swapchain refused (%d): created as asked", r); return d->CreateSwapchainKHR(device, ci, al, out); }
    sc *s = calloc(1, sizeof *s);
    uint32_t n = 0;
    if (s) { s->h = *out; s->d = d; s->ext = ci->imageExtent; d->GetSwapchainImagesKHR(device, *out, &n, NULL); }
    if (s && n && n <= MAXI) { s->n = n; d->GetSwapchainImagesKHR(device, *out, &s->n, s->img); }
    if (!s || !n || n > MAXI || !sc_init(s, ci->imageFormat)) {
        /* cannot key it: start again with the swapchain the app asked for (opaque, untouched) */
        LOG("glass setup failed: swapchain recreated as asked");
        if (s) { s->n = n <= MAXI ? n : 0; sc_free(s); }
        d->DestroySwapchainKHR(device, *out, al);
        return d->CreateSwapchainKHR(device, ci, al, out);
    }
    LOG("swapchain %ux%u format %d, %u images: compositeAlpha %s -> PRE_MULTIPLIED, usage 0x%x -> 0x%x",
        ci->imageExtent.width, ci->imageExtent.height, ci->imageFormat, s->n,
        ci->compositeAlpha == VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR ? "OPAQUE" : "other", ci->imageUsage, m.imageUsage);
    pthread_mutex_lock(&mu);
    s->next = scs; scs = s;
    pthread_mutex_unlock(&mu);
    return VK_SUCCESS;
}

static VKAPI_ATTR void VKAPI_CALL hk_DestroySwapchainKHR(VkDevice device, VkSwapchainKHR h, const VkAllocationCallbacks *al) {
    pthread_mutex_lock(&mu);
    dev *d = dev_by_key(key_of(device));
    sc *s = NULL;
    for (sc **p = &scs; *p; p = &(*p)->next) if ((*p)->h == h) { s = *p; *p = s->next; break; }
    pthread_mutex_unlock(&mu);
    if (s) sc_free(s);
    if (d) d->DestroySwapchainKHR(device, h, al);
}

static double now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e3 + t.tv_nsec / 1e6; }
static FILE *trace_f; static double last_present;
static pthread_once_t trace_once = PTHREAD_ONCE_INIT;
static void trace_init(void) { const char *e = getenv("APPGLASS_TRACE"); if (e && *e) trace_f = fopen(e, "ae"); }

static int fam_of(dev *d, VkQueue q, uint32_t *fam) {
    for (int i = 0; i < d->nq; i++) if (d->qs[i].q == q) { *fam = d->qs[i].fam; return 1; }
    return 0;
}

static VKAPI_ATTR VkResult VKAPI_CALL hk_QueuePresentKHR(VkQueue q, const VkPresentInfoKHR *pi) {
    pthread_mutex_lock(&mu);
    dev *d = dev_by_key(key_of(q));
    if (!d) { pthread_mutex_unlock(&mu); return VK_ERROR_DEVICE_LOST; }
    double t0 = now_ms();
    uint32_t nw = pi->waitSemaphoreCount; const VkSemaphore *w = pi->pWaitSemaphores;
    VkSemaphore last = 0; int keyed = 0;
    VkPipelineStageFlags st[64];
    for (uint32_t i = 0; i < 64; i++) st[i] = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT;
    for (uint32_t k = 0; k < pi->swapchainCount; k++) {
        sc *s = sc_find(pi->pSwapchains[k]);
        uint32_t idx = pi->pImageIndices[k], fam;
        if (!s || idx >= s->n) continue;
        if (!s->pool) {
            if (!fam_of(d, q, &fam) || !sc_record(s, fam)) {
                LOG("present: could not record the pass, swapchain left as is");
                if (s->pool) { d->DestroyCommandPool(d->h, s->pool, NULL); }
                s->pool = 0; continue;
            }
        }
        d->WaitForFences(d->h, 1, &s->fence[idx], VK_TRUE, UINT64_MAX);
        d->ResetFences(d->h, 1, &s->fence[idx]);
        VkSubmitInfo si = { VK_STRUCTURE_TYPE_SUBMIT_INFO, NULL, last ? 1 : (nw <= 64 ? nw : 64), last ? &last : w, st, 1, &s->cb[idx], 1, &s->sem[idx] };
        VkResult r = d->QueueSubmit(q, 1, &si, s->fence[idx]);
        if (r) { pthread_mutex_unlock(&mu); return r; }
        last = s->sem[idx]; keyed++;
    }
    pthread_once(&trace_once, trace_init);
    if (trace_f && keyed) { fprintf(trace_f, "%.2f %.2f %.2f\n", t0, last_present > 0 ? t0 - last_present : 0, now_ms() - t0); fflush(trace_f); }
    if (keyed) last_present = t0;
    pthread_mutex_unlock(&mu);
    if (!keyed) return d->QueuePresentKHR(q, pi);
    VkPresentInfoKHR m = *pi;
    m.waitSemaphoreCount = 1; m.pWaitSemaphores = &last;
    return d->QueuePresentKHR(q, &m);
}

static void note_queue(VkDevice device, uint32_t fam, VkQueue q) {
    pthread_mutex_lock(&mu);
    dev *d = dev_by_key(key_of(device));
    if (d && q) {
        int i; for (i = 0; i < d->nq; i++) if (d->qs[i].q == q) break;
        if (i == d->nq && d->nq < MAXQ) { d->qs[d->nq].q = q; d->qs[d->nq].fam = fam; d->nq++; }
    }
    pthread_mutex_unlock(&mu);
}
static VKAPI_ATTR void VKAPI_CALL hk_GetDeviceQueue(VkDevice device, uint32_t fam, uint32_t idx, VkQueue *q) {
    pthread_mutex_lock(&mu); dev *d = dev_by_key(key_of(device)); pthread_mutex_unlock(&mu);
    if (!d) return;
    d->GetDeviceQueue(device, fam, idx, q); note_queue(device, fam, *q);
}
static VKAPI_ATTR void VKAPI_CALL hk_GetDeviceQueue2(VkDevice device, const VkDeviceQueueInfo2 *qi, VkQueue *q) {
    pthread_mutex_lock(&mu); dev *d = dev_by_key(key_of(device)); pthread_mutex_unlock(&mu);
    if (!d || !d->GetDeviceQueue2) return;
    d->GetDeviceQueue2(device, qi, q); note_queue(device, qi->queueFamilyIndex, *q);
}

/* ---------------- instance / device ---------------- */
static VKAPI_ATTR VkResult VKAPI_CALL hk_CreateInstance(const VkInstanceCreateInfo *ci, const VkAllocationCallbacks *al, VkInstance *out) {
    VkLayerInstanceCreateInfo *li = (VkLayerInstanceCreateInfo *)ci->pNext;
    while (li && !(li->sType == VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO && li->function == VK_LAYER_LINK_INFO))
        li = (VkLayerInstanceCreateInfo *)li->pNext;
    if (!li) return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr next = li->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    li->u.pLayerInfo = li->u.pLayerInfo->pNext;
    PFN_vkCreateInstance create = (PFN_vkCreateInstance)next(NULL, "vkCreateInstance");
    if (!create) return VK_ERROR_INITIALIZATION_FAILED;
    VkResult r = create(ci, al, out);
    if (r) return r;
    inst *i = calloc(1, sizeof *i);
    if (!i) return VK_SUCCESS;          /* no memory: the layer just stays out of the way */
    i->h = *out; i->key = key_of(*out); i->gipa = next;
    i->DestroyInstance = (PFN_vkDestroyInstance)next(*out, "vkDestroyInstance");
    i->GetPhysicalDeviceSurfaceCapabilitiesKHR = (PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR)next(*out, "vkGetPhysicalDeviceSurfaceCapabilitiesKHR");
    i->GetPhysicalDeviceQueueFamilyProperties = (PFN_vkGetPhysicalDeviceQueueFamilyProperties)next(*out, "vkGetPhysicalDeviceQueueFamilyProperties");
    pthread_mutex_lock(&mu); i->next = insts; insts = i; pthread_mutex_unlock(&mu);
    LOG("instance: layer on, %d keys", keys());
    return VK_SUCCESS;
}

static VKAPI_ATTR void VKAPI_CALL hk_DestroyInstance(VkInstance h, const VkAllocationCallbacks *al) {
    pthread_mutex_lock(&mu);
    inst *i = NULL;
    for (inst **p = &insts; *p; p = &(*p)->next) if ((*p)->h == h) { i = *p; *p = i->next; break; }
    pthread_mutex_unlock(&mu);
    if (!i) return;
    i->DestroyInstance(h, al);
    free(i);
}

static VKAPI_ATTR VkResult VKAPI_CALL hk_CreateDevice(VkPhysicalDevice pd, const VkDeviceCreateInfo *ci, const VkAllocationCallbacks *al, VkDevice *out) {
    VkLayerDeviceCreateInfo *li = NULL, *cb = NULL;
    for (VkLayerDeviceCreateInfo *p = (VkLayerDeviceCreateInfo *)ci->pNext; p; p = (VkLayerDeviceCreateInfo *)p->pNext) {
        if (p->sType != VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO) continue;
        if (p->function == VK_LAYER_LINK_INFO && !li) li = p;
        if (p->function == VK_LOADER_DATA_CALLBACK && !cb) cb = p;
    }
    if (!li) return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr ngipa = li->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr ngdpa = li->u.pLayerInfo->pfnNextGetDeviceProcAddr;
    li->u.pLayerInfo = li->u.pLayerInfo->pNext;
    pthread_mutex_lock(&mu); inst *in = inst_by_key(key_of(pd)); pthread_mutex_unlock(&mu);
    PFN_vkCreateDevice create = (PFN_vkCreateDevice)ngipa(in ? in->h : NULL, "vkCreateDevice");
    if (!create) return VK_ERROR_INITIALIZATION_FAILED;
    VkResult r = create(pd, ci, al, out);
    if (r || !in) return r;
    dev *d = calloc(1, sizeof *d);
    if (!d) return VK_SUCCESS;
    d->h = *out; d->key = key_of(*out); d->pd = pd; d->in = in; d->gdpa = ngdpa;
    d->set_data = cb ? cb->u.pfnSetDeviceLoaderData : NULL;
#define X(n) d->n = (PFN_vk##n)ngdpa(*out, "vk" #n);
    DEV_FNS(X)
#undef X
    /* the pass is a draw: every queue the app can present on must do graphics */
    VkQueueFamilyProperties qf[32]; uint32_t nf = 32;
    in->GetPhysicalDeviceQueueFamilyProperties(pd, &nf, qf);
    d->graphics_only = 1;
    for (uint32_t i = 0; i < ci->queueCreateInfoCount; i++) {
        uint32_t f = ci->pQueueCreateInfos[i].queueFamilyIndex;
        if (f >= nf || !(qf[f].queueFlags & VK_QUEUE_GRAPHICS_BIT)) d->graphics_only = 0;
    }
    pthread_mutex_lock(&mu); d->next = devs; devs = d; pthread_mutex_unlock(&mu);
    return VK_SUCCESS;
}

static VKAPI_ATTR void VKAPI_CALL hk_DestroyDevice(VkDevice h, const VkAllocationCallbacks *al) {
    pthread_mutex_lock(&mu);
    dev *d = NULL;
    for (dev **p = &devs; *p; p = &(*p)->next) if ((*p)->h == h) { d = *p; *p = d->next; break; }
    for (sc **p = &scs; d && *p;) {            /* swapchains the app never destroyed */
        if ((*p)->d == d) { sc *s = *p; *p = s->next; sc_free(s); } else p = &(*p)->next;
    }
    pthread_mutex_unlock(&mu);
    if (!d) return;
    pipe_free(d);
    d->DestroyDevice(h, al);
    free(d);
}

static PFN_vkVoidFunction dev_hook(const char *n) {
#define H(x) if (!strcmp(n, "vk" #x)) return (PFN_vkVoidFunction)hk_##x;
    H(CreateSwapchainKHR) H(DestroySwapchainKHR) H(QueuePresentKHR) H(GetDeviceQueue) H(GetDeviceQueue2) H(DestroyDevice)
#undef H
    return NULL;
}

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL layer_gdpa(VkDevice device, const char *n) {
    if (!strcmp(n, "vkGetDeviceProcAddr")) return (PFN_vkVoidFunction)layer_gdpa;
    pthread_mutex_lock(&mu); dev *d = device ? dev_by_key(key_of(device)) : NULL; pthread_mutex_unlock(&mu);
    if (!d) return NULL;
    PFN_vkVoidFunction h = dev_hook(n);
    if (h) {
        if (!strcmp(n, "vkGetDeviceQueue2") && !d->GetDeviceQueue2) return NULL;
        return h;
    }
    return d->gdpa(device, n);
}

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL layer_gipa(VkInstance instance, const char *n) {
    if (!strcmp(n, "vkGetInstanceProcAddr")) return (PFN_vkVoidFunction)layer_gipa;
    if (!strcmp(n, "vkCreateInstance")) return (PFN_vkVoidFunction)hk_CreateInstance;
    if (!strcmp(n, "vkDestroyInstance")) return (PFN_vkVoidFunction)hk_DestroyInstance;
    if (!strcmp(n, "vkCreateDevice")) return (PFN_vkVoidFunction)hk_CreateDevice;
    if (!strcmp(n, "vkGetDeviceProcAddr")) return (PFN_vkVoidFunction)layer_gdpa;
    PFN_vkVoidFunction h = dev_hook(n);
    if (h) return h;
    pthread_mutex_lock(&mu); inst *i = instance ? inst_by_key(key_of(instance)) : NULL; pthread_mutex_unlock(&mu);
    return i ? i->gipa(instance, n) : NULL;
}

EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(VkInstance instance, const char *n) { return layer_gipa(instance, n); }
EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(VkDevice device, const char *n) { return layer_gdpa(device, n); }
EXPORT VKAPI_ATTR VkResult VKAPI_CALL vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface *v) {
    if (!v || v->sType != LAYER_NEGOTIATE_INTERFACE_STRUCT) return VK_ERROR_INITIALIZATION_FAILED;
    if (v->loaderLayerInterfaceVersion >= 2) {
        v->pfnGetInstanceProcAddr = layer_gipa;
        v->pfnGetDeviceProcAddr = layer_gdpa;
        v->pfnGetPhysicalDeviceProcAddr = NULL;
        v->loaderLayerInterfaceVersion = 2;
    }
    return VK_SUCCESS;
}
