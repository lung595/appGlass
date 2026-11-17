// appglass-vkprobe: is there a Vulkan device that is not the CPU (lavapipe)?
// appglass-artcraft runs it before it takes the GPU route, with the launcher's own Vulkan env and the
// glass layer on, so a driver that is broken or missing, a host where only lavapipe answers, or a
// damaged layer shows up here and the launcher takes the CPU route instead of opening no window.
// appglass status runs it the same way to say which route the wrapper takes.
//
//   stdout: one line per device, "gpu <name>" or "cpu <name>"
//   exit 0: at least one device that is not VK_PHYSICAL_DEVICE_TYPE_CPU
//        1: only CPU devices
//        2: no Vulkan loader, no instance or no device
// Only the headers are needed to build it: the loader is dlopen'd (no libvulkan.so dev symlink).
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <dlfcn.h>
#include <stdio.h>

int main(void) {
    void *l = dlopen("libvulkan.so.1", RTLD_NOW | RTLD_LOCAL);
    if (!l) { fprintf(stderr, "appglass-vkprobe: no Vulkan loader: %s\n", dlerror()); return 2; }
    PFN_vkGetInstanceProcAddr gipa = (PFN_vkGetInstanceProcAddr)dlsym(l, "vkGetInstanceProcAddr");
    PFN_vkCreateInstance create = gipa ? (PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance") : NULL;
    if (!create) { fputs("appglass-vkprobe: the loader has no vkCreateInstance\n", stderr); return 2; }
    VkApplicationInfo ai = { VK_STRUCTURE_TYPE_APPLICATION_INFO, NULL, "appglass-vkprobe", 1, NULL, 0, VK_API_VERSION_1_0 };
    VkInstanceCreateInfo ci = { VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, NULL, 0, &ai, 0, NULL, 0, NULL };
    VkInstance in;
    VkResult r = create(&ci, NULL, &in);
    if (r) { fprintf(stderr, "appglass-vkprobe: vkCreateInstance: %d\n", r); return 2; }
    PFN_vkEnumeratePhysicalDevices en = (PFN_vkEnumeratePhysicalDevices)gipa(in, "vkEnumeratePhysicalDevices");
    PFN_vkGetPhysicalDeviceProperties props = (PFN_vkGetPhysicalDeviceProperties)gipa(in, "vkGetPhysicalDeviceProperties");
    PFN_vkDestroyInstance destroy = (PFN_vkDestroyInstance)gipa(in, "vkDestroyInstance");
    VkPhysicalDevice pd[16]; uint32_t n = 16;
    int gpu = 0;
    if (!en || !props || en(in, &n, pd) < 0) n = 0;
    for (uint32_t i = 0; i < n; i++) {
        VkPhysicalDeviceProperties p; props(pd[i], &p);
        int cpu = p.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU;
        printf("%s %s\n", cpu ? "cpu" : "gpu", p.deviceName);
        if (!cpu) gpu = 1;
    }
    if (destroy) destroy(in, NULL);
    if (!n) { fputs("appglass-vkprobe: no Vulkan device\n", stderr); return 2; }
    return gpu ? 0 : 1;
}
