"""Every shim keeps its own environment to the app it glasses: a child the app
starts (a shell in a terminal, a game from a launcher, a helper) never inherits
APPGLASS_*, LD_PRELOAD of an appglass library, the Qt style override or the
hook's own variables.

The shims are built for real with the host toolchain (a test is skipped when
a compiler or a JS engine is missing), started with the environment their
wrapper gives them, and asked to run ``env`` the way an app starts a child.
"""

import glob
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIMS = os.path.join(REPO, "shims")
GCC = shutil.which("gcc")
GXX = shutil.which("g++")
PKG = shutil.which("pkg-config")
GJS = shutil.which("gjs")


def shim(*p):
    return os.path.join(SHIMS, *p)


def moc():
    for c in ("/usr/lib64/qt6/libexec/moc", "/usr/lib/qt6/libexec/moc"):
        if os.access(c, os.X_OK):
            return c
    return shutil.which("moc-qt6")


def pkg_ok(*mods):
    return bool(PKG) and subprocess.run([PKG, "--exists"] + list(mods)).returncode == 0


def pkg(*args):
    return subprocess.run([PKG] + list(args), capture_output=True, text=True,
                          check=True).stdout.split()


def parse_env(out):
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l and not l.startswith(" "))


def leaks(e):
    """The appglass variables left in a child's environment."""
    bad = [k for k in e if k.startswith(("APPGLASS_", "AGL_", "JFGLASS_"))]
    if "appglass" in e.get("LD_PRELOAD", "") or "jfglass" in e.get("LD_PRELOAD", ""):
        bad.append("LD_PRELOAD")
    if e.get("QT_STYLE_OVERRIDE", "").lower() == "appglass":
        bad.append("QT_STYLE_OVERRIDE")
    if "appglass" in e.get("QT_PLUGIN_PATH", ""):
        bad.append("QT_PLUGIN_PATH")
    return bad


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="appglass-scrub-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def base_env(self, **kw):
        e = {"PATH": os.environ.get("PATH", os.defpath), "HOME": self.dir, "KEEP": "1"}
        e.update(kw)
        return e


# ------------------------------------------------------------------ qt-style

@unittest.skipUnless(GXX and moc() and pkg_ok("Qt6Widgets"), "no g++/moc/Qt6Widgets")
class QtStyle(Tmp):
    """libappglass.so as the style: QT_STYLE_OVERRIDE, the plugin path and the
    APPGLASS_* settings are read once, then gone for the children (Konsole's
    shell, Kate's external tools, Dolphin's 'open with')."""

    PROBE = textwrap.dedent(r"""
        #include <QtWidgets>
        #include <cstdio>
        #include <cstdlib>
        int main(int argc, char **argv) {
            QApplication app(argc, argv);
            QWidget top; QWidget *child = new QWidget(&top);
            child->setAttribute(Qt::WA_OpaquePaintEvent);
            QMenu *menu = new QMenu(&top); QWidget *item = new QWidget(menu);
            item->setAttribute(Qt::WA_OpaquePaintEvent);
            top.ensurePolished(); child->ensurePolished(); menu->ensurePolished(); item->ensurePolished();
            std::printf(" style=%s\n", qPrintable(app.style()->name()));
            std::printf(" child_opaque=%d\n", child->testAttribute(Qt::WA_OpaquePaintEvent) ? 1 : 0);
            std::printf(" popup_child_opaque=%d\n", item->testAttribute(Qt::WA_OpaquePaintEvent) ? 1 : 0);
            const char *x = std::getenv("XDG_CONFIG_DIRS");
            std::printf(" xdg_early=%s\n", x ? x : "-");
            std::fflush(stdout);
            int rc = 0;   // children start from the event loop
            QTimer::singleShot(0, &app, [&] { rc = std::system("env"); app.quit(); });
            app.exec();
            return rc;
        }
    """)

    def build(self, src=None):
        b = os.path.join(self.dir, "build")
        os.makedirs(os.path.join(self.dir, "plugins", "styles"))
        os.makedirs(b)
        shutil.copy(src or shim("qt-style", "glassstyle.cpp"), os.path.join(b, "glassstyle.cpp"))
        shutil.copy(shim("qt-style", "appglass.json"), b)
        inc = pkg("--cflags-only-I", "Qt6Widgets")
        subprocess.run([moc()] + inc + ["glassstyle.cpp", "-o", "glassstyle.moc"], cwd=b,
                       check=True, capture_output=True, timeout=120)
        so = os.path.join(self.dir, "plugins", "styles", "libappglass.so")
        subprocess.run([GXX, "-O1", "-shared", "-fPIC", "-std=c++17", "-I.", "glassstyle.cpp",
                        "-o", so] + pkg("--cflags", "--libs", "Qt6Widgets"),
                       cwd=b, check=True, capture_output=True, timeout=300)
        with open(os.path.join(b, "probe.cpp"), "w") as f:
            f.write(self.PROBE)
        self.probe = os.path.join(b, "probe")
        subprocess.run([GXX, "-O1", "-fPIC", "-std=c++17", "probe.cpp", "-o", self.probe]
                       + pkg("--cflags", "--libs", "Qt6Widgets"),
                       cwd=b, check=True, capture_output=True, timeout=300)

    def run_probe(self):
        colors = os.path.join(self.dir, "dms-colors.json")
        with open(colors, "w") as f:
            f.write('{"mode":"dark","colors":{"dark":{"surface":"#101418"}}}')
        plugins = os.path.join(self.dir, "plugins")
        env = self.base_env(QT_QPA_PLATFORM="offscreen", QT_STYLE_OVERRIDE="appglass",
                            QT_PLUGIN_PATH=plugins + ":/opt/other/plugins",
                            APPGLASS_COLORS=colors, APPGLASS_CONTENT="0.8", APPGLASS_BAR="0",
                            APPGLASS_DIALOGS="glass", XDG_RUNTIME_DIR=self.dir,
                            XDG_CONFIG_DIRS="/x/kate/config/appglass:/app/etc/xdg:/etc/xdg")
        r = subprocess.run([self.probe], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout, parse_env(r.stdout)

    def test_children_lose_the_style(self):
        self.build()
        out, e = self.run_probe()
        self.assertIn(" style=appglass", out)
        self.assertEqual(leaks(e), [])
        self.assertEqual(e.get("QT_PLUGIN_PATH"), "/opt/other/plugins")
        self.assertEqual(e.get("KEEP"), "1")

    def test_kate_glass_config_kept_for_kconfig_only(self):
        # the Kate launcher's glass katerc dir: KConfig reads the cascade
        # while the app starts, the children (Kate's terminal, its tools, a
        # plain kate started from there) never see it
        self.build()
        out, e = self.run_probe()
        self.assertIn(" xdg_early=/x/kate/config/appglass:/app/etc/xdg:/etc/xdg", out)
        self.assertEqual(e.get("XDG_CONFIG_DIRS"), "/app/etc/xdg:/etc/xdg")

    def test_opaque_paint_children_cleared(self):
        # KTextEditor's view sets WA_OpaquePaintEvent and then fills only
        # what it paints: on glass that leaves holes. Children of a glass
        # window drop the flag; a popup's children keep it (popups are opaque).
        self.build()
        out, _ = self.run_probe()
        self.assertIn(" child_opaque=0", out)
        self.assertIn(" popup_child_opaque=1", out)


# ------------------------------------------------------------------ ck-shim

@unittest.skipUnless(GCC, "no gcc")
class CkShim(Tmp):
    """appglass-ck.so: with APPGLASS_SCRUB set (every wrapper sets it), an exec
    or spawn of another binary drops the shim and the keys."""

    PROBE = textwrap.dedent(r"""
        #include <spawn.h>
        #include <stdio.h>
        #include <stdlib.h>
        #include <sys/wait.h>
        #include <unistd.h>
        extern char **environ;
        int main(int argc, char **argv) {
            pid_t p; char *args[] = {"env", NULL};
            if (posix_spawnp(&p, "env", NULL, NULL, args, environ)) return 3;
            int st; waitpid(p, &st, 0);
            fflush(stdout);
            printf(" ---\n"); fflush(stdout);
            execvp("env", args);
            return 4;
        }
    """)

    def setUp(self):
        super().setUp()
        self.so = os.path.join(self.dir, "appglass-ck.so")
        subprocess.run([GCC, "-shared", "-fPIC", "-O2", "-o", self.so, shim("ck-shim", "appglass-ck.c"),
                        "-ldl"], check=True, capture_output=True, timeout=120)
        src = os.path.join(self.dir, "probe.c")
        with open(src, "w") as f:
            f.write(self.PROBE)
        self.probe = os.path.join(self.dir, "probe")
        subprocess.run([GCC, "-O1", "-o", self.probe, src], check=True, capture_output=True,
                       timeout=120)

    def test_spawn_and_exec_scrub(self):
        env = self.base_env(LD_PRELOAD=self.so, APPGLASS_KEYS="121316:0.6", APPGLASS_SCRUB="",
                            APPGLASS_MAXFPS="60")
        r = subprocess.run([self.probe], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        spawned, execd = r.stdout.split(" ---\n")
        for out in (spawned, execd):
            e = parse_env(out)
            self.assertEqual(leaks(e), [])
            self.assertEqual(e.get("KEEP"), "1")

    def test_wrapper_script_hands_the_shim_to_the_app(self):
        """A flatpak command is often a script that execs the real binary
        (/app/bin/subl -> /app/extra/sublime_text/sublime_text). That one exec,
        named in APPGLASS_KEEP, keeps the shim; everything else is scrubbed."""
        src = os.path.join(self.dir, "wrap.c")
        with open(src, "w") as f:
            f.write(textwrap.dedent(r"""
                #include <spawn.h>
                #include <stdio.h>
                #include <sys/wait.h>
                #include <unistd.h>
                extern char **environ;
                int main(int argc, char **argv) {
                    pid_t p; char *s[] = {"/usr/bin/env", NULL}, *x[] = {"/usr/bin/printenv", NULL};
                    if (posix_spawn(&p, s[0], NULL, NULL, s, environ)) return 3;
                    int st; waitpid(p, &st, 0);
                    printf(" ---\n"); fflush(stdout);
                    execve(x[0], x, environ);
                    return 4;
                }
            """))
        wrap = os.path.join(self.dir, "wrap")
        subprocess.run([GCC, "-O1", "-o", wrap, src], check=True, capture_output=True, timeout=120)
        env = self.base_env(LD_PRELOAD=self.so, APPGLASS_KEYS="303841:0.6", APPGLASS_SCRUB="",
                            APPGLASS_KEEP="/usr/bin/printenv")
        r = subprocess.run([wrap], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        other, app = (parse_env(o) for o in r.stdout.split(" ---\n"))
        self.assertEqual(leaks(other), [])
        self.assertEqual((app.get("LD_PRELOAD"), app.get("APPGLASS_KEYS")),
                         (self.so, "303841:0.6"))

    def test_every_ck_wrapper_turns_the_scrub_on(self):
        for w in glob.glob(shim("ck-shim", "appglass-*")):
            if w.endswith(".c"):
                continue
            with open(w) as f:
                text = f.read()
            self.assertRegex(text, r"APPGLASS_SCRUB=", os.path.basename(w))


# ------------------------------------------------------------------ webkit-shim

@unittest.skipUnless(GCC, "no gcc")
class WebkitShim(Tmp):
    def test_children_lose_the_shim(self):
        so = os.path.join(self.dir, "appglass-wk.so")
        subprocess.run([GCC, "-shared", "-fPIC", "-O2", "-o", so, shim("webkit-shim", "appglass-wk.c"),
                        "-ldl"], check=True, capture_output=True, timeout=120)
        env = self.base_env(LD_PRELOAD=so, APPGLASS_CSS="/x/glass.css", APPGLASS_JS="/x/end.js")
        r = subprocess.run(["sh", "-c", "exec env"], env=env, capture_output=True, text=True,
                           timeout=60, check=True)
        e = parse_env(r.stdout)
        self.assertEqual(leaks(e), [])
        self.assertEqual(e.get("KEEP"), "1")


# ------------------------------------------------------------------ qtquick-shim

@unittest.skipUnless(GXX and moc() and pkg_ok("Qt6Quick", "Qt6Qml"), "no g++/moc/Qt6Quick")
class QtQuickShim(Tmp):
    """libjfglass.so preloaded in jellyfin-desktop: its children (mpv helpers,
    the browser opened from a link) get neither the preload nor JFGLASS_*."""

    MODULES = ("Qt6Quick", "Qt6Qml", "Qt6Gui", "Qt6Core")

    def test_children_lose_the_shim(self):
        b = self.dir
        shutil.copy(shim("qtquick-shim", "jfglass.cpp"), b)
        subprocess.run([moc()] + pkg("--cflags-only-I", *self.MODULES) + ["jfglass.cpp", "-o", "jfglass.moc"],
                       cwd=b, check=True, capture_output=True, timeout=120)
        so = os.path.join(b, "libjfglass.so")
        subprocess.run([GXX, "-O1", "-shared", "-fPIC", "-std=c++17", "-I.", "jfglass.cpp", "-o", so]
                       + pkg("--cflags", "--libs", *self.MODULES) + ["-ldl"],
                       cwd=b, check=True, capture_output=True, timeout=300)
        src = os.path.join(b, "probe.c")
        with open(src, "w") as f:
            f.write('#include <stdlib.h>\nint main(void) { return system("env"); }\n')
        exe = os.path.join(b, "jellyfin-desktop")   # the shim acts only in this binary
        subprocess.run([GCC or GXX, "-O1", "-o", exe, src], check=True, capture_output=True,
                       timeout=120)
        env = self.base_env(LD_PRELOAD=so, JFGLASS_CSS=os.path.join(b, "glass.css"),
                            JFGLASS_LOG="1", QT_QPA_PLATFORM="offscreen")
        r = subprocess.run([exe], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        e = parse_env(r.stdout)
        self.assertEqual(leaks(e), [])
        self.assertEqual(e.get("KEEP"), "1")


# ------------------------------------------------------------------ electron-hook

HARNESS = r"""
var env = %(env)s;
var process = {env: env, type: 'browser', argv0: 'electron', pid: 1};
var module = {exports: {}};
var console = {error: function () {}, log: function () {}};
function setTimeout() {}
function require(m) { if (m === 'fs') return {readFileSync: function () { return ''; }}; throw new Error('no ' + m); }
(function (require, process, module, console, setTimeout) {
%(src)s
})(require, process, module, console, setTimeout);
print(JSON.stringify(process.env));
"""


@unittest.skipUnless(GJS, "no JS engine (gjs)")
class ElectronHook(Tmp):
    """agl-hook.js in the main process: it keeps what it needs from AGL_* and
    deletes them, so the VS Code terminal, the extension host and every helper
    the app starts after the injection run without them."""

    def run_hook(self, env):
        import json
        with open(shim("electron-hook", "agl-hook.js")) as f:
            src = f.read()
        js = os.path.join(self.dir, "h.js")
        with open(js, "w") as f:
            f.write(HARNESS % {"env": json.dumps(env), "src": src})
        r = subprocess.run([GJS, js], capture_output=True, text=True, timeout=60,
                           env={"PATH": os.environ.get("PATH", os.defpath), "HOME": self.dir})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_hook_env_deleted(self):
        e = self.run_hook({"AGL_CSS": "/x/glass.css", "AGL_MATCH": "x", "AGL_LOG": "1",
                           "AGL_NOMENU": "1", "KEEP": "1",
                           "NODE_OPTIONS": "--max-old-space-size=99 --require /l/agl-hook.js"})
        self.assertEqual(leaks(e), [])
        self.assertEqual(e.get("KEEP"), "1")
        self.assertEqual(e.get("NODE_OPTIONS"), "--max-old-space-size=99")

    def test_wrappers_pass_only_hook_env(self):
        for w in glob.glob(shim("electron-hook", "appglass-*")):
            with open(w) as f:
                text = f.read()
            for var in re.findall(r"--env=([A-Z_]+)=", text):
                self.assertTrue(var.startswith("AGL_"), (os.path.basename(w), var))
            self.assertNotIn("LD_PRELOAD", text)


class Coverage(unittest.TestCase):
    """A new shim comes with its scrub test here."""

    COVERED = {"qt-style": QtStyle, "ck-shim": CkShim, "webkit-shim": WebkitShim,
               "qtquick-shim": QtQuickShim, "electron-hook": ElectronHook}
    NO_ENV = {"electron-vencord": "a stylesheet read by Vencord, no process env",
              "sync": "systemd units of appglass itself, no app env"}

    def test_every_shim_has_a_scrub_test(self):
        dirs = sorted(d for d in os.listdir(SHIMS) if os.path.isdir(shim(d)))
        self.assertEqual(sorted(set(self.COVERED) | set(self.NO_ENV)), dirs)


if __name__ == "__main__":
    unittest.main()
