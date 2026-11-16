"""The real appglass-ck.so (shims/ck-shim), built with the host gcc: the
opaque-region hook against a fake libwayland-client, its exports and the
pidfd_spawnp env scrub."""

import os
import shutil
import subprocess
import tempfile
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

    def test_maxfps_and_trace_in_source(self):
        with open(SRC) as f:
            s = f.read()
        self.assertIn('getenv("APPGLASS_MAXFPS")', s)
        self.assertIn('getenv("APPGLASS_TRACE")', s)

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
