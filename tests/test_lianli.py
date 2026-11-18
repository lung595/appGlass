import os
import shutil
import subprocess
import tempfile
import unittest

from fixtures.shimcase import ShimCase

L = ".local/lib/appglass/lianli/"


class Lianli(ShimCase, unittest.TestCase):
    FAMILY = "lianli"
    KEY = "com.sgtaziz.lianlilinux"
    BINS = ("lianli-gui",)
    SYSTEM = "com.sgtaziz.lianlilinux.desktop"
    LAUNCHER = ".local/share/applications/com.sgtaziz.lianlilinux.desktop"
    FILES = {L + "appglass-wk.so": 0o755, L + "appglass-wk.c": 0o644,
             L + "lianli-glass.css.tmpl": 0o644, L + "lianli-glass.css": 0o644,
             ".local/bin/appglass-lianli": 0o755}
    CSS = L + "lianli-glass.css"
    BUILDS = 1

    def test_css_percent(self):
        self.enable()
        self.w.sb.set_level(0.6)
        self.apply()
        css = self.w.sb.read(self.w.user(self.CSS))
        self.assertIn("var(--bg-base) 60%", css)


GCC = shutil.which("gcc")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "shims", "webkit-shim", "appglass-wk.c")


@unittest.skipUnless(GCC, "no gcc")
class ShimEnvironment(unittest.TestCase):
    """The real appglass-wk.so, built with the host gcc: a process it is
    preloaded in keeps none of it for its children."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="appglass-wk-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.so = os.path.join(self.dir, "appglass-wk.so")
        subprocess.run([GCC, "-shared", "-fPIC", "-O2", "-Wall", "-o", self.so, SRC, "-ldl"],
                       check=True, capture_output=True, timeout=120)
        self.other = os.path.join(self.dir, "other.so")       # another preload of the user
        shutil.copy(self.so, self.other)

    def child_env(self, preload):
        env = {"PATH": os.environ.get("PATH", os.defpath), "LD_PRELOAD": preload,
               "APPGLASS_CSS": "/x/glass.css", "APPGLASS_JS": "/x/end.js",
               "APPGLASS_JS_START": "/x/start.js", "APPGLASS_DEBUG": "1", "KEEP": "1"}
        r = subprocess.run(["sh", "-c", "exec env"], env=env, capture_output=True, text=True,
                           timeout=60, check=True)
        return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)

    def test_children_lose_the_shim(self):
        e = self.child_env(self.so)
        self.assertNotIn("LD_PRELOAD", e)
        self.assertEqual([k for k in e if k.startswith("APPGLASS_")], [])
        self.assertEqual(e.get("KEEP"), "1")

    def test_other_preloads_stay(self):
        e = self.child_env("%s:%s" % (self.so, self.other))
        self.assertEqual(e.get("LD_PRELOAD"), self.other)

    def test_every_ld_preload_entry_is_scrubbed(self):
        """An environment with LD_PRELOAD twice (execve takes any array): the
        shim is out of both, the user's other preload kept. The app passes
        its environ on as it is (no shell to tidy it up)."""
        src = os.path.join(self.dir, "dup.c")
        with open(src, "w") as f:
            f.write("#include <string.h>\n#include <unistd.h>\nextern char **environ;\n"
                    "int main(int c, char **v) {\n"
                    "  if (c > 2 && !strcmp(v[1], \"app\")) {\n"
                    "    char *a[] = { \"cat\", \"/proc/self/environ\", 0 };\n"
                    "    execve(v[2], a, environ); return 1; }\n"
                    "  char *e[] = { v[1], v[2], \"APPGLASS_CSS=/x\", 0 };\n"
                    "  char *a[] = { v[0], \"app\", v[3], 0 };\n"
                    "  execve(v[0], a, e); return 1; }\n")
        exe = os.path.join(self.dir, "dup")
        subprocess.run([GCC, "-o", exe, src], check=True, capture_output=True, timeout=120)
        # the other preload: a plain library (a copy of the shim would scrub too)
        other = os.path.join(self.dir, "plain.so")
        with open(other + ".c", "w") as f:
            f.write("int appglass_test_plain;\n")
        subprocess.run([GCC, "-shared", "-fPIC", "-o", other, other + ".c"], check=True,
                       capture_output=True, timeout=120)
        r = subprocess.run([exe, "LD_PRELOAD=" + self.so, "LD_PRELOAD=%s:%s" % (self.so, other),
                            shutil.which("cat")], capture_output=True, timeout=60, check=True)
        env = [e.decode() for e in r.stdout.split(b"\0") if e]
        self.assertEqual([e for e in env if e.startswith("LD_PRELOAD=")], ["LD_PRELOAD=" + other])
        self.assertEqual([e for e in env if e.startswith("APPGLASS_")], [])

if __name__ == "__main__":
    unittest.main()
