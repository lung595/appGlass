"""The real appglass-ck.so (shims/ck-shim), built with the host gcc: the
opaque-region hook against a fake and the real libwayland-client (variadic,
array and dlsym() paths), the swap cap and trace against a fake libEGL, its
exports and the pidfd_spawnp env scrub."""

import os
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "shims", "ck-shim", "appglass-ck.c")
GCC = shutil.which("gcc")


FAKE_WL = r"""
#include <stdint.h>
#include <stdio.h>
struct wl_proxy { const char *cls; };
union wl_argument { void *o; };
static void *last = (void *)1;
const char *wl_proxy_get_class(struct wl_proxy *p) { return p->cls; }
struct wl_proxy *wl_proxy_marshal_array_flags(struct wl_proxy *p, uint32_t op, const void *i,
        uint32_t v, uint32_t fl, union wl_argument *a) { last = a[0].o; return 0; }
struct wl_proxy *wl_proxy_marshal_array_constructor(struct wl_proxy *p, uint32_t op,
        union wl_argument *a, const void *i) { last = a[0].o; return 0; }
struct wl_proxy *wl_proxy_marshal_array_constructor_versioned(struct wl_proxy *p, uint32_t op,
        union wl_argument *a, const void *i, uint32_t v) { last = a[0].o; return 0; }
void *fake_last(void) { return last; }
"""

CLIENT = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
struct wl_proxy { const char *cls; };
union wl_argument { void *o; };
struct wl_proxy *wl_proxy_marshal_array_flags(struct wl_proxy *, uint32_t, const void *, uint32_t,
        uint32_t, union wl_argument *);
struct wl_proxy *wl_proxy_marshal_array_constructor(struct wl_proxy *, uint32_t,
        union wl_argument *, const void *);
struct wl_proxy *wl_proxy_marshal_array_constructor_versioned(struct wl_proxy *, uint32_t,
        union wl_argument *, const void *, uint32_t);
void *fake_last(void);
int main(int argc, char **argv) {
    static int region;
    struct wl_proxy p = { argv[1] };
    uint32_t op = (uint32_t)atoi(argv[2]);
    union wl_argument a[1] = { { &region } };
    wl_proxy_marshal_array_flags(&p, op, 0, 1, 0, a);
    printf("%s", fake_last() ? "kept" : "null");
    wl_proxy_marshal_array_constructor(&p, op, a, 0);
    printf(" %s", fake_last() ? "kept" : "null");
    wl_proxy_marshal_array_constructor_versioned(&p, op, a, 0, 1);
    printf(" %s\n", fake_last() ? "kept" : "null");
    return a[0].o == &region ? 0 : 3;     /* the caller's args are never changed */
}
"""

SPAWN = r"""
#define _GNU_SOURCE
#include <spawn.h>
#include <sys/pidfd.h>
#include <sys/wait.h>
#include <stdio.h>
extern char **environ;
int main(int argc, char **argv) {
    int fd; char *a[] = { "env", NULL };
    if (pidfd_spawnp(&fd, "env", NULL, NULL, a, environ)) return 2;
    siginfo_t si; return waitid(P_PIDFD, fd, &si, WEXITED) ? 4 : 0;
}
"""


FAKE_EGL = r"""
void *eglGetCurrentContext(void) { return 0; }          /* EGL_NO_CONTEXT: the key pass skips */
unsigned eglSwapBuffers(void *d, void *s) { return 1; }
void *eglGetProcAddress(const char *n) { return 0; }
unsigned eglQuerySurface(void *d, void *s, int a, int *v) { return 0; }
"""

SWAP = r"""
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
unsigned eglSwapBuffers(void *, void *);
static int n;
static void *run(void *x) { for (int i = 0; i < n; i++) eglSwapBuffers(0, 0); return 0; }
int main(int argc, char **argv) {          /* swap <threads> <swaps per thread> <trace path> */
    int t = atoi(argv[1]); n = atoi(argv[2]); pthread_t th[8];
    for (int i = 0; i < t; i++) pthread_create(&th[i], 0, run, 0);
    for (int i = 0; i < t; i++) pthread_join(th[i], 0);
    int cloexec = -1; char l[4096], q[64];  /* is the trace fd close-on-exec? */
    for (int fd = 3; fd < 256; fd++) {
        snprintf(q, sizeof q, "/proc/self/fd/%d", fd); ssize_t k = readlink(q, l, sizeof l - 1);
        if (k > 0) { l[k] = 0; if (!strcmp(l, argv[3])) cloexec = !!(fcntl(fd, F_GETFD) & FD_CLOEXEC); }
    }
    printf("%d\n", cloexec); return 0;
}
"""

REAL_WL = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
#include <wayland-client.h>
typedef struct wl_proxy *(*flags_fn)(struct wl_proxy *, uint32_t, const struct wl_interface *, uint32_t,
                                     uint32_t, union wl_argument *);
typedef struct wl_proxy *(*ctorv_fn)(struct wl_proxy *, uint32_t, union wl_argument *,
                                     const struct wl_interface *, uint32_t);
/* real <variadic|dlsym_flags|dlsym_ctor>: sends set_opaque_region and set_input_region with a
 * region on a wl_surface over a socketpair, prints the region id each request carried (0 = NULL) */
int main(int argc, char **argv) {
    int sv[2]; if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv)) return 2;
    struct wl_display *d = wl_display_connect_to_fd(sv[0]); if (!d) return 2;
    struct wl_registry *r = wl_display_get_registry(d);
    struct wl_compositor *c = wl_registry_bind(r, 1, &wl_compositor_interface, 4);
    struct wl_surface *s = wl_compositor_create_surface(c);
    struct wl_region *g = wl_compositor_create_region(c);
    union wl_argument a[1]; a[0].o = (struct wl_object *)g;
    if (!strcmp(argv[1], "variadic")) {
        wl_surface_set_opaque_region(s, g);
    } else {
        void *h = dlopen("libwayland-client.so.0", RTLD_NOW | RTLD_NOLOAD); if (!h) return 2;
        if (!strcmp(argv[1], "dlsym_flags")) {
            flags_fn f = (flags_fn)dlsym(h, "wl_proxy_marshal_array_flags");
            f((struct wl_proxy *)s, WL_SURFACE_SET_OPAQUE_REGION, NULL, wl_proxy_get_version((struct wl_proxy *)s), 0, a);
        } else {
            ctorv_fn f = (ctorv_fn)dlsym(h, "wl_proxy_marshal_array_constructor_versioned");
            f((struct wl_proxy *)s, WL_SURFACE_SET_OPAQUE_REGION, a, NULL, wl_proxy_get_version((struct wl_proxy *)s));
        }
    }
    wl_surface_set_input_region(s, g);
    if (wl_display_flush(d) < 0) return 2;
    uint32_t buf[1024]; ssize_t k = recv(sv[1], buf, sizeof buf, MSG_DONTWAIT); if (k <= 0) return 2;
    uint32_t sid = wl_proxy_get_id((struct wl_proxy *)s);
    for (size_t i = 0; i + 2 <= (size_t)k / 4; ) {
        uint32_t id = buf[i], op = buf[i + 1] & 0xffff, sz = buf[i + 1] >> 16; if (sz < 8) return 2;
        if (id == sid && (op == 4 || op == 5)) printf("%s=%s ", op == 4 ? "opaque" : "input",
                buf[i + 2] == 0 ? "null" : buf[i + 2] == wl_proxy_get_id((struct wl_proxy *)g) ? "region" : "?");
        i += sz / 4;
    }
    printf("\n"); return a[0].o == (struct wl_object *)g ? 0 : 3;
}
"""


@unittest.skipUnless(GCC, "no gcc")
class CkShimReal(unittest.TestCase):
    """The real appglass-ck.so, built with the host gcc."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="appglass-ck-")
        cls.so = os.path.join(cls.dir, "appglass-ck.so")
        cls.cc([GCC, "-shared", "-fPIC", "-O2", "-Wall", "-o", cls.so, SRC, "-ldl"])
        wl = os.path.join(cls.dir, "wl")
        os.mkdir(wl)
        cls.cc([GCC, "-shared", "-fPIC", "-o", os.path.join(wl, "libwayland-client.so.0"),
                cls.src("fake.c", FAKE_WL)])
        cls.client = os.path.join(cls.dir, "client")
        cls.cc([GCC, "-o", cls.client, cls.src("client.c", "#include <stdlib.h>\n" + CLIENT),
                os.path.join(wl, "libwayland-client.so.0"), "-Wl,-rpath," + wl])
        egl = os.path.join(cls.dir, "egl")
        os.mkdir(egl)
        cls.cc([GCC, "-shared", "-fPIC", "-Wl,-soname,libEGL.so.1", "-o",
                os.path.join(egl, "libEGL.so.1"), cls.src("fakeegl.c", FAKE_EGL)])
        cls.swap = os.path.join(cls.dir, "swap")
        cls.cc([GCC, "-o", cls.swap, cls.src("swap.c", SWAP), os.path.join(egl, "libEGL.so.1"),
                "-Wl,-rpath," + egl, "-lpthread"])
        cls.real_wl = os.path.join(cls.dir, "realwl")
        cls.real_wl_ok = subprocess.run([GCC, "-o", cls.real_wl, cls.src("realwl.c", REAL_WL),
                                         "-lwayland-client", "-ldl"],
                                        capture_output=True).returncode == 0
        cls.spawn = os.path.join(cls.dir, "spawn")
        cls.spawn_ok = subprocess.run([GCC, "-o", cls.spawn, cls.src("spawn.c", SPAWN)],
                                      capture_output=True).returncode == 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, True)

    @classmethod
    def src(cls, name, text):
        p = os.path.join(cls.dir, name)
        with open(p, "w") as f:
            f.write(text)
        return p

    @staticmethod
    def cc(argv):
        subprocess.run(argv, check=True, capture_output=True, timeout=120)

    def run_client(self, cls, op, keys=True):
        env = {"PATH": os.environ.get("PATH", os.defpath), "LD_PRELOAD": self.so}
        if keys:
            env["APPGLASS_KEYS"] = "121316:0.6"
        r = subprocess.run([self.client, cls, str(op)], env=env, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_exports(self):
        r = subprocess.run(["nm", "-D", "--defined-only", self.so], capture_output=True,
                           text=True, check=True)
        names = set(l.split()[-1] for l in r.stdout.splitlines() if l.strip())
        for n in ("eglSwapBuffers", "dlsym", "execve", "posix_spawnp", "pidfd_spawn",
                  "pidfd_spawnp", "wl_proxy_marshal_array_flags",
                  "wl_proxy_marshal_array_constructor",
                  "wl_proxy_marshal_array_constructor_versioned"):
            self.assertIn(n, names)

    def test_opaque_region_dropped(self):
        self.assertEqual(self.run_client("wl_surface", 4), "null null null")

    def test_opaque_region_kept_without_keys(self):
        self.assertEqual(self.run_client("wl_surface", 4, keys=False), "kept kept kept")

    def test_other_requests_untouched(self):
        self.assertEqual(self.run_client("wl_surface", 5), "kept kept kept")   # set_input_region
        self.assertEqual(self.run_client("wl_subsurface", 4), "kept kept kept")

    def run_swap(self, threads, swaps, **env):
        trace = os.path.join(self.dir, "trace-%d-%d-%s" % (threads, swaps, env.get("APPGLASS_MAXFPS", "0")))
        e = {"PATH": os.environ.get("PATH", os.defpath), "LD_PRELOAD": self.so,
             "APPGLASS_KEYS": "121316:0.6", "APPGLASS_TRACE": trace}
        e.update(env)
        t = time.monotonic()
        r = subprocess.run([self.swap, str(threads), str(swaps), trace], env=e,
                           capture_output=True, text=True, timeout=60)
        took = time.monotonic() - t
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(trace) as f:
            rows = [[float(x) for x in l.split()] for l in f]
        return r.stdout.strip(), rows, took

    def test_maxfps_caps_the_whole_process(self):
        # 2 threads x 8 swaps at 50 fps: one shared slot every 20 ms, whichever thread swaps
        cloexec, rows, took = self.run_swap(2, 8, APPGLASS_MAXFPS="50")
        self.assertEqual(len(rows), 16)
        self.assertGreaterEqual(took, 15 * 0.020)
        gaps = sorted(r[1] for r in rows)
        self.assertEqual(gaps[0], 0)                        # the first swap has no previous one
        self.assertGreaterEqual(gaps[1], 19.9, gaps)
        self.assertEqual(cloexec, "1")                      # the trace fd is O_CLOEXEC

    def test_no_cap_without_maxfps(self):
        cloexec, rows, took = self.run_swap(1, 50)
        self.assertEqual(len(rows), 50)
        self.assertLess(took, 0.9)                           # 50 swaps at a 20 ms cap would be 1 s
        self.assertEqual(cloexec, "1")

    def run_real_wl(self, mode, keys=True):
        if not self.real_wl_ok:
            self.skipTest("no libwayland-client headers")
        env = {"PATH": os.environ.get("PATH", os.defpath), "LD_PRELOAD": self.so}
        if keys:
            env["APPGLASS_KEYS"] = "121316:0.6"
        r = subprocess.run([self.real_wl, mode], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_real_libwayland_paths(self):
        # through the system libwayland-client: the variadic request (GTK, C clients) and the
        # array functions a dlopen client (Rust wayland-sys) gets from dlsym()
        for mode in ("variadic", "dlsym_flags", "dlsym_ctor"):
            self.assertEqual(self.run_real_wl(mode), "opaque=null input=region", mode)
            self.assertEqual(self.run_real_wl(mode, keys=False), "opaque=region input=region", mode)

    def test_pidfd_spawnp_scrubs(self):
        if not self.spawn_ok:
            self.skipTest("libc without pidfd_spawnp")
        env = {"PATH": os.environ.get("PATH", os.defpath), "LD_PRELOAD": self.so + " other.so",
               "APPGLASS_KEYS": "121316:0.6", "APPGLASS_SCRUB": "WGPU_BACKEND",
               "WGPU_BACKEND": "gl", "KEEP": "1"}
        r = subprocess.run([self.spawn], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        e = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
        self.assertEqual(e.get("KEEP"), "1")
        self.assertEqual(e.get("LD_PRELOAD"), "other.so")
        self.assertNotIn("WGPU_BACKEND", e)
        self.assertFalse([k for k in e if k.startswith("APPGLASS_")])


if __name__ == "__main__":
    unittest.main()
