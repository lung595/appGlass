import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from fixtures.shimcase import ShimCase

L = ".local/lib/appglass/artcraft/"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "shims", "ck-shim", "appglass-ck.c")


class ArtCraft(ShimCase, unittest.TestCase):
    FAMILY = "artcraft"
    KEY = "ai.storyteller.artcraft-launcher"
    BINS = ("artcraft-launcher",)
    SYSTEM = "ai.storyteller.artcraft-launcher.desktop"
    LAUNCHER = ".local/share/applications/ai.storyteller.artcraft-launcher.desktop"
    FILES = {L + "appglass-ck.so": 0o755, L + "appglass-ck.c": 0o644,
             L + "vk/libappglass-vk.so": 0o755, L + "vk/appglass-vk.json": 0o644,
             L + "vk/appglass-vkprobe": 0o755, ".local/bin/appglass-artcraft": 0o755}
    BUILDS = 3            # the colour-key shim, the Vulkan layer and its device probe
    REBUILDS = 1
    WRAPPER = ".local/bin/appglass-artcraft"

    def test_launcher_exec_only(self):
        self.enable()
        self.apply()
        text = self.w.sb.read(self.w.user(self.LAUNCHER))
        self.assertEqual(re.findall(r"(?m)^Exec=(.*)$", text),
                         [self.w.user(".local/bin/appglass-artcraft")])
        # every other line is the system launcher's
        strip = lambda t: [l for l in t.splitlines() if not l.startswith("Exec=")]
        self.assertEqual(strip(text), strip(self.system))

    def test_wrapper(self):
        self.enable()
        self.apply()
        w = self.w.sb.read(self.w.user(".local/bin/appglass-artcraft"))
        self.assertNotIn("Projects/", w.replace(REPO, ""))
        self.assertIn('APPGLASS_MAXFPS="${APPGLASS_MAXFPS:-60}"', w)
        self.assertIn("WGPU_BACKEND=vulkan", w)
        self.assertIn('LAYERS="$LIB/vk${VK_ADD_LAYER_PATH:+:', w)
        for g in ("/usr/share/vulkan/implicit", "/etc/vulkan/implicit", ".local/share/vulkan"):
            self.assertNotIn(g, w)
        self.assertIn("APPGLASS_SCRUB=", w)
        self.assertIn('LD_PRELOAD="$LIB/appglass-ck.so', w)
        self.assertIn('LIB="$HOME/.local/lib/appglass/artcraft"', w)
        r = subprocess.run(["sh", "-n", self.w.user(".local/bin/appglass-artcraft")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_layer_files(self):
        """the layer and its explicit manifest next to it; no global layer dir is touched"""
        self.enable()
        self.apply()
        with open(os.path.join(REPO, "shims", "vklayer", "appglass-vk.json"), "rb") as f:
            self.assertEqual(self.w.sb.readb(self.w.user(L + "vk/appglass-vk.json")), f.read())
        man = json.loads(self.w.sb.read(self.w.user(L + "vk/appglass-vk.json")))
        self.assertEqual(man["layer"]["library_path"], "./libappglass-vk.so")
        self.assertNotIn("enable_environment", man["layer"])
        vk = [c for c in self.w.tc.builds() if "libappglass-vk.so" in c]
        self.assertEqual(len(vk), 1, self.w.tc.builds())
        self.assertIn("appglass-vk.c", vk[0])
        self.assertIn("-shared", vk[0])
        pr = [c for c in self.w.tc.builds() if "appglass-vkprobe" in c]
        self.assertEqual(len(pr), 1, self.w.tc.builds())
        self.assertIn("appglass-vkprobe.c", pr[0])
        self.assertNotIn("-lvulkan", pr[0])          # the loader is dlopen'd: headers are enough
        for root, dirs, files in os.walk(self.w.sb.root):
            self.assertNotIn("vulkan", os.path.relpath(root, self.w.sb.root).split(os.sep), root)
        owned = self.w.state()["owners"]["artcraft"]["files"]
        for rel in ("vk/libappglass-vk.so", "vk/appglass-vk.json", "vk/appglass-vkprobe"):
            self.assertIn(self.w.user(L + rel), owned)

    def test_layer_build_fails_cpu_route(self):
        """no Vulkan headers: the CPU route is installed all the same, and status says why"""
        self.enable()
        self.w.tc.fail_one("libappglass-vk.so", "appglass-vk.c:1:10: fatal error: vulkan/vulkan.h: "
                           "No such file or directory\ncompilation terminated.\n")
        out, err = self.apply()
        self.assertNotIn("skipped", err)
        self.assertIn("CPU", err)
        self.assertIn("Vulkan headers", err)
        for rel in (L + "appglass-ck.so", self.WRAPPER, self.LAUNCHER):
            self.assertTrue(os.path.isfile(self.w.user(rel)), rel)
        self.assertFalse(os.path.lexists(self.w.user(L + "vk")))
        doc = self.status()
        fam = doc["families"]["artcraft"]
        self.assertEqual(fam["render"], "cpu")
        self.assertIn("Vulkan headers", fam["render_why"])
        app = [a for a in doc["apps"] if a["key"] == self.KEY][0]
        self.assertEqual(app["render"], "cpu")
        self.assertIn("CPU", app["reason"])
        # the headers come: the next apply adds the layer
        os.remove(os.path.join(self.w.tc.dir, "fail-libappglass-vk.so"))
        self.apply()
        self.assertTrue(os.path.isfile(self.w.user(L + "vk/libappglass-vk.so")))
        with self.device():
            self.assertEqual(self.status()["families"]["artcraft"]["render"], "gpu")
        self.run_ok("remove")
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_probe_build_fails_cpu_route(self):
        """the probe does not build: no layer either (the wrapper never takes the GPU route blind)"""
        self.enable()
        self.w.tc.fail_one("appglass-vkprobe", "appglass-vkprobe.c:13:10: fatal error: vulkan/vulkan.h: "
                           "No such file or directory\n")
        out, err = self.apply()
        self.assertNotIn("skipped", err)
        self.assertIn("Vulkan headers", err)
        self.assertFalse(os.path.lexists(self.w.user(L + "vk")))
        self.assertTrue(os.path.isfile(self.w.user(self.WRAPPER)))
        self.assertEqual(self.status()["families"]["artcraft"]["render"], "cpu")
        self.run_ok("remove")
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_layer_gone_on_reapply_when_build_fails(self):
        """a layer that no longer builds is taken out: the wrapper falls back to the CPU route"""
        self.enable()
        self.apply()
        so = self.w.user(L + "vk/libappglass-vk.so")
        self.w.tc.fail_one("libappglass-vk.so")
        with mock.patch("appglass.families.artcraft.layer_sources",
                        return_value={"appglass-vk.c": b"changed", "glass-spv.h": b""}):
            out, err = self.apply()
        self.assertNotIn("skipped", err)
        self.assertFalse(os.path.exists(so))
        self.assertTrue(os.path.isfile(self.w.user(L + "appglass-ck.so")))
        self.run_ok("remove")
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    # --- status: which route the wrapper takes

    def status(self):
        out, err = self.run_ok("status", "--json")
        return json.loads(out)

    @contextlib.contextmanager
    def device(self, gpu=True, code=None):
        """the installed probe answers as on a host with a Vulkan GPU (gpu False: only lavapipe;
        code: its own shell code); it is put back after, byte for byte"""
        p = self.w.user(L + "vk/appglass-vkprobe")
        keep = self.w.sb.readb(p) if os.path.exists(p) else None
        log = os.path.join(self.w.sb.root, "probe.env")
        if keep is not None:
            with open(p, "w") as f:
                f.write("#!/bin/sh\n/usr/bin/env > '%s'\n%s\n" % (log, code or (
                    "echo 'gpu Fake GPU'" if gpu else "echo 'cpu llvmpipe (LLVM 99)'; exit 1")))
        try:
            yield log
        finally:
            if keep is not None:
                with open(p, "wb") as f:
                    f.write(keep)
            if os.path.exists(log):
                os.remove(log)

    def test_status_render(self):
        self.enable()
        self.assertNotIn("render", self.status()["families"]["artcraft"])   # not applied
        self.apply()
        with self.device():
            doc = self.status()
            out, err = self.run_ok("status")
            code, dout, derr = self.w.run("doctor")
        self.assertNotIn("render check failed", err)
        self.assertIn("render: artcraft on the GPU\n", dout)
        self.assertEqual(doc["families"]["artcraft"]["render"], "gpu")
        app = [a for a in doc["apps"] if a["key"] == self.KEY][0]
        self.assertEqual(app["render"], "gpu")
        self.assertIn("GPU", app["reason"])
        self.assertRegex(out, r"(?m)^artcraft .*applied \(renders on the GPU\)")
        with self.device(gpu=False):
            fam = self.status()["families"]["artcraft"]
            code, dout, derr = self.w.run("doctor")
        self.assertEqual((fam["render"], fam["render_why"]),
                         ("cpu", "no Vulkan GPU, only llvmpipe (LLVM 99)"))
        self.assertIn("render: artcraft on the CPU (no Vulkan GPU, only llvmpipe (LLVM 99))\n", dout)
        # no driver answers, or the probe crashes (a broken driver or a damaged layer;
        # SIGKILL stands in for SIGBUS: a death by signal; SIGKILL, unlike SIGBUS, never
        # reaches the crash handler, so the stub leaves no core dump record)
        for code in ("exit 2", "kill -KILL $$"):
            with self.device(code=code):
                fam = self.status()["families"]["artcraft"]
            self.assertEqual(fam["render"], "cpu", code)
            self.assertIn("no usable Vulkan device", fam["render_why"])
        # the probe itself is not there (a hand removed it): never GPU
        os.remove(self.w.user(L + "vk/appglass-vkprobe"))
        self.assertEqual(self.status()["families"]["artcraft"]["render"], "cpu")

    def test_status_probe_env(self):
        """status runs the probe as the wrapper does: the layer on, no EGL vendor override"""
        self.enable()
        self.apply()
        with self.device() as log:
            code, out, err = self.w.run("status", "--json", env={
                "VK_INSTANCE_LAYERS": "VK_LAYER_MINE", "__EGL_VENDOR_LIBRARY_FILENAMES": "/x.json"})
            with open(log) as f:
                e = dict(l.split("=", 1) for l in f.read().splitlines() if "=" in l)
        self.assertEqual(code, 0, err)
        self.assertEqual(e["VK_INSTANCE_LAYERS"], "VK_LAYER_APPGLASS_glass:VK_LAYER_MINE")
        self.assertEqual(e["VK_ADD_LAYER_PATH"], self.w.user(L + "vk"))
        self.assertNotIn("__EGL_VENDOR_LIBRARY_FILENAMES", e)

    def test_status_knob(self):
        """APPGLASS_ARTCRAFT in the env status runs with is what the wrapper would see"""
        self.enable()
        self.apply()
        with self.device():
            code, out, err = self.w.run("status", "--json", env={"APPGLASS_ARTCRAFT": "cpu"})
            fam = json.loads(out)["families"]["artcraft"]
            self.assertEqual((fam["render"], fam["render_why"]), ("cpu", "APPGLASS_ARTCRAFT=cpu"))
            # off: no glass at all, so neither the GPU nor the CPU glass route
            off = {"APPGLASS_ARTCRAFT": "off"}
            code, out, err = self.w.run("status", "--json", env=off)
            doc = json.loads(out)
            fam = doc["families"]["artcraft"]
            self.assertEqual((fam["render"], fam["render_why"]), ("off", "APPGLASS_ARTCRAFT=off"))
            app = [a for a in doc["apps"] if a["key"] == self.KEY][0]
            self.assertEqual(app["render"], "off")
            self.assertIn("starts plain, without glass", app["reason"])
            self.assertNotIn("GPU", app["reason"])
            code, out, err = self.w.run("status", env=off)
            self.assertRegex(out, r"(?m)^artcraft .*applied \(starts plain, without glass: "
                                  r"APPGLASS_ARTCRAFT=off\)")
            code, dout, derr = self.w.run("doctor", env=off)
            self.assertIn("render: artcraft plain, without glass (APPGLASS_ARTCRAFT=off)\n", dout)

    def test_status_probes_once(self):
        """one status run asks the probe once, for the family and the app row both"""
        self.enable()
        self.apply()
        count = os.path.join(self.w.sb.root, "probe.count")
        with self.device(code="echo run >> '%s'; echo 'gpu Fake GPU'" % count):
            doc = self.status()
        self.assertEqual(doc["families"]["artcraft"]["render"], "gpu")
        self.assertEqual([a for a in doc["apps"] if a["key"] == self.KEY][0]["render"], "gpu")
        with open(count) as f:
            self.assertEqual(f.read().count("run"), 1)

    # --- the wrapper: gpu, cpu or plain

    def wrapped(self, env=(), gpu=True, code=None, mesa=True, scheme="prefer-dark", rm=()):
        """run the installed wrapper around a stub launcher, the probe answering as device(gpu,
        code) says: the route it took"""
        with self.device(gpu, code):
            return self._wrapped(env, mesa, scheme, rm)

    def _wrapped(self, env, mesa, scheme, rm):
        d = tempfile.mkdtemp(prefix="appglass-wr-")
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, "bin"))
        if mesa:
            open(os.path.join(d, "mesa.json"), "w").close()
        with open(os.path.join(d, "bin", "gsettings"), "w") as f:
            f.write("#!/bin/sh\necho \"'%s'\"\n" % scheme)
        os.chmod(os.path.join(d, "bin", "gsettings"), 0o755)
        app = os.path.join(d, "app")
        with open(app, "w") as f:
            f.write("#!/bin/sh\nprintf '%s\\n' \"WGPU_BACKEND=${WGPU_BACKEND:-}\" "
                    "\"VK_INSTANCE_LAYERS=${VK_INSTANCE_LAYERS:-}\" \"VK_ADD_LAYER_PATH=${VK_ADD_LAYER_PATH:-}\" "
                    "\"APPGLASS_MAXFPS=${APPGLASS_MAXFPS:-}\" \"APPGLASS_KEYS=${APPGLASS_KEYS:-}\" "
                    "\"LD_PRELOAD=${LD_PRELOAD:-}\" \"ARGS=$*\" > \"$OUT\"\n")
        os.chmod(app, 0o755)
        text = self.w.sb.read(self.w.user(self.WRAPPER))
        for var, val in (("BIN", app), ("MESA", os.path.join(d, "mesa.json"))):
            text, n = re.subn(r"(?m)^%s=.*$" % var, "%s='%s'" % (var, val), text)
            self.assertEqual(n, 1, var)
        w = os.path.join(d, "wrapper")
        with open(w, "w") as f:
            f.write(text)
        for rel in rm:
            os.remove(self.w.user(rel))
        e = {"PATH": os.path.join(d, "bin") + ":/usr/bin:/bin", "HOME": self.w.sb.home,
             "XDG_CACHE_HOME": os.path.join(d, "cache"), "OUT": os.path.join(d, "out")}
        e.update(env)
        r = subprocess.run(["sh", w, "--flag"], env=e, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(d, "out")) as f:
            got = dict(l.split("=", 1) for l in f.read().splitlines())
        self.assertEqual(got["ARGS"], "--flag")
        if got["WGPU_BACKEND"] == "vulkan":
            self.assertEqual(got["VK_INSTANCE_LAYERS"], "VK_LAYER_APPGLASS_glass")
            self.assertEqual(got["VK_ADD_LAYER_PATH"], self.w.user(L + "vk"))
            self.assertEqual(got["APPGLASS_MAXFPS"], "60")     # the layer keeps to it on a CPU device only
            self.assertIn("appglass-ck.so", got["LD_PRELOAD"])
            self.assertTrue(got["APPGLASS_KEYS"].startswith("121316:"))
            return "gpu"
        if got["WGPU_BACKEND"] == "gl":
            self.assertEqual(got["VK_INSTANCE_LAYERS"], "")
            self.assertEqual(got["APPGLASS_MAXFPS"], "60")
            self.assertIn("appglass-ck.so", got["LD_PRELOAD"])
            self.assertTrue(got["APPGLASS_KEYS"].startswith("121316:"))
            return "cpu"
        self.assertEqual((got["APPGLASS_KEYS"], got["LD_PRELOAD"], got["VK_INSTANCE_LAYERS"]),
                         ("", "", ""))
        return "plain"

    def test_wrapper_routes(self):
        self.enable()
        self.apply()
        self.assertEqual(self.wrapped(), "gpu")
        self.assertEqual(self.wrapped(mesa=False), "gpu")
        self.assertEqual(self.wrapped(env={"APPGLASS_ARTCRAFT": "cpu"}), "cpu")
        self.assertEqual(self.wrapped(gpu=False), "cpu")
        self.assertEqual(self.wrapped(code="exit 2"), "cpu")
        self.assertEqual(self.wrapped(code="kill -KILL $$"), "cpu")     # a crash, no core
        self.assertEqual(self.wrapped(gpu=False, mesa=False), "plain")
        self.assertEqual(self.wrapped(env={"APPGLASS_ARTCRAFT": "off"}), "plain")
        self.assertEqual(self.wrapped(scheme="prefer-light"), "plain")
        self.assertEqual(self.wrapped(rm=(L + "vk/appglass-vkprobe",)), "cpu")
        self.assertEqual(self.wrapped(rm=(L + "vk/appglass-vk.json",)), "cpu")
        self.assertEqual(self.wrapped(rm=(L + "vk/libappglass-vk.so",)), "cpu")
        self.assertEqual(self.wrapped(rm=(L + "appglass-ck.so",)), "plain")

    def test_same_source_as_localsend(self):
        self.enable()
        self.apply()
        with open(SRC, "rb") as f:
            self.assertEqual(self.w.sb.readb(self.w.user(L + "appglass-ck.c")), f.read())

    def test_adopt_owner_per_app(self):
        """The ck-shim hand files go to the family of their app."""
        ls = ".local/lib/appglass/localsend/appglass-ck.so"
        mine = list(self.FILES) + [self.LAUNCHER]
        for rel in mine + [ls]:
            self.w.hand(rel, b"hand " + rel.encode() + b"\n", 0o644)
        self.run_ok("adopt", *["~/" + r for r in mine + [ls]])
        owners = self.w.state()["owners"]
        got = {r: o for o, rec in owners.items() for p in rec.get("files", {})
               for r in [os.path.relpath(p, self.w.user(""))]}
        for rel in mine:
            self.assertEqual(got.get(rel), "artcraft", rel)
        self.assertEqual(got.get(ls), "localsend")

    def test_route(self):
        from appglass import adapters
        from appglass.core import discover
        rec = {"key": self.KEY, "toolkit": "egui", "names": [self.KEY]}
        r = adapters.resolve(rec, discover())
        self.assertEqual((r["adapter"], r["tier"], r["family"]), ("ck-shim", "forced", "artcraft"))
        self.assertEqual(r["effective"], "fallback")      # opt-in
        r = adapters.resolve(rec, discover(), {"apps": {"artcraft": {"enabled": True}}})
        self.assertEqual(r["effective"], "glass")


if __name__ == "__main__":
    unittest.main()
