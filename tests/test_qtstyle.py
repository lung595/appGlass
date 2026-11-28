"""qt-style (VLC): the Qt style plugin built with the host Qt, the launcher."""

import json
import os
import re
import unittest

from fixtures.sandbox import fixture
from fixtures.shimworld import ShimWorld

SO = ".local/lib/appglass/qt6/styles/libappglass.so"
LAUNCHER = ".local/share/applications/vlc.desktop"


class QtStyle(unittest.TestCase):
    def setUp(self):
        self.w = ShimWorld(bins=("vlc",))
        with open(fixture("launchers/vlc.desktop")) as f:
            self.system = f.read()
        self.w.launcher("vlc.desktop", self.system)
        self.before = self.w.sb.tree_hash()

    def tearDown(self):
        self.w.cleanup()

    def apply(self, *extra):
        code, out, err = self.w.run("apply", "--only", "qtstyle", *extra)
        return code, out, err

    def expected(self, level="0.8"):
        sb = self.w.sb
        pre = ("env QT_PLUGIN_PATH=%s QT_STYLE_OVERRIDE=appglass APPGLASS_COLORS=%s "
               "APPGLASS_CONTENT=%s " % (os.path.join(sb.home, ".local/lib/appglass/qt6"),
                                         os.path.join(sb.cache, "dms", "dms-colors.json"),
                                         level))
        return re.sub(r"(?m)^Exec=/usr/bin/vlc", lambda m: "Exec=" + pre + "/usr/bin/vlc",
                      self.system)

    def test_apply_and_remove(self):
        code, out, err = self.apply()
        self.assertEqual(code, 0, err)
        so = self.w.user(SO)
        self.assertTrue(self.w.sb.readb(so).startswith(b"FAKE-BUILD libappglass.so"))
        self.assertEqual(self.w.mode(so), 0o755)
        lv = json.loads(self.w.run("levels")[1])
        level = repr(float(lv["content"]))
        self.assertEqual(self.w.sb.read(self.w.user(LAUNCHER)), self.expected(level))
        builds = self.w.tc.builds()
        self.assertEqual(len(builds), 1)
        self.assertIn("-o libappglass.so", builds[0])
        self.assertTrue(any(c.startswith("moc ") and "glassstyle.moc" in c
                            for c in self.w.tc.calls()))
        code, out, err = self.w.run("remove", "--only", "qtstyle")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_stamp_rebuilds_on_qt_update_only(self):
        self.apply()
        self.apply()
        self.assertEqual(len(self.w.tc.builds()), 1)
        self.w.sb.set_level(0.6)
        self.apply()
        self.assertEqual(len(self.w.tc.builds()), 1)        # a level is not a rebuild
        self.assertIn("APPGLASS_CONTENT=0.6 ", self.w.sb.read(self.w.user(LAUNCHER)))
        self.w.tc.qt = "6.12.0"
        self.apply()
        self.assertEqual(len(self.w.tc.builds()), 2)

    def test_an_apply_that_builds_nothing_starts_no_tool(self):
        # the versions in the stamp are kept while the tools and the .pc
        # files stay the same: the hook run stays fast and cacheable
        self.apply()
        n = len(self.w.tc.calls())
        self.apply()
        self.assertEqual(self.w.tc.calls()[n:], [])

    def test_hand_files_conflict_then_adopt(self):
        hand_so = self.w.hand(SO, b"\x7fELF hand-built", 0o755)
        hand_l = self.w.hand(LAUNCHER, self.expected("0.8"))
        before = self.w.sb.tree_hash()
        code, out, err = self.apply()
        self.assertIn("qtstyle: skipped", err)
        self.assertIn("libappglass.so", err)
        self.assertEqual(self.w.sb.tree_hash(), before)
        code, out, err = self.w.run("adopt", "~/" + SO, "~/" + LAUNCHER)
        self.assertEqual(code, 0, err)
        code, out, err = self.apply()
        self.assertEqual(code, 0, err)
        self.assertTrue(self.w.sb.readb(hand_so).startswith(b"FAKE-BUILD"))
        code, out, err = self.w.run("remove", "--only", "qtstyle")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.w.sb.readb(hand_so), b"\x7fELF hand-built")
        self.assertEqual(self.w.mode(hand_so), 0o755)
        self.assertEqual(self.w.sb.read(hand_l), self.expected("0.8"))

    def test_no_toolchain(self):
        self.w.sb.env["PATH"] = self.w.bin
        code, out, err = self.apply()
        self.assertIn("cannot build libappglass.so", err)
        self.assertFalse(os.path.exists(self.w.user(LAUNCHER)))

    def test_build_failure_writes_nothing(self):
        self.w.tc.fail()
        code, out, err = self.apply()
        self.assertIn("qtstyle: skipped", err)
        self.assertIn("building libappglass.so failed", err)
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_dry_run(self):
        code, out, err = self.apply("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.w.tc.builds(), [])
        self.assertIn("would build", out + err)
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def check_rescue(self, whole):
        import shutil
        sd = os.path.join(self.w.sb.state, "appglass")
        self.apply()
        if whole:
            shutil.rmtree(sd)
        else:
            os.remove(os.path.join(sd, "state.json"))
        code, out, err = self.w.run("adopt", "--rescue")
        self.assertEqual(code, 0, err)
        self.assertIn("vlc.desktop", out + err)
        self.assertIn("libappglass.so", out + err)
        code, out2, err2 = self.w.run("remove")
        self.assertEqual(code, 0, err2)
        self.assertEqual(self.w.sb.tree_hash(), self.before, out + err + out2 + err2)

    def test_rescue_after_state_json_lost(self):
        self.check_rescue(False)

    def test_rescue_after_state_dir_lost(self):
        self.check_rescue(True)

    def test_lost_state_guard_names_the_launcher(self):
        self.apply()
        os.remove(os.path.join(self.w.sb.state, "appglass", "state.json"))
        code, out, err = self.apply()
        self.assertNotEqual(code, 0)
        self.assertIn("vlc.desktop", err)
        self.assertIn("libappglass.so", err)

    def test_not_installed(self):
        os.remove(os.path.join(self.w.bin, "vlc"))
        self.apply()
        self.assertEqual(self.w.tc.builds(), [])
        self.assertFalse(os.path.exists(self.w.user(SO)))


KATE = ("[Desktop Entry]\nName=Kate\n"
        "Exec=/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=kate --file-forwarding "
        "org.kde.kate -b @@u %U @@\n\n[Desktop Action newSession]\n"
        "Exec=/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=kate org.kde.kate --startanon\n")


class QtStyleFlatpak(unittest.TestCase):
    """Kate / Konsole from flathub: the launcher passes the style in with
    flatpak run options (read-only plugin and colours dirs, the variables)."""

    def setUp(self):
        self.w = ShimWorld()
        d = self.w.sb.path("flatpak", "app", "org.kde.kate", "current", "active")
        os.makedirs(os.path.join(d, "files"))
        with open(os.path.join(d, "metadata"), "w") as f:
            f.write("[Application]\nname=org.kde.kate\nruntime=org.kde.Platform/x86_64/6.11\n")
        self.w.launcher("org.kde.kate.desktop", KATE, flatpak=True)
        self.before = self.w.sb.tree_hash()

    def tearDown(self):
        self.w.cleanup()

    def test_launcher_flags_and_remove(self):
        code, out, err = self.w.run("apply", "--only", "qtstyle")
        self.assertEqual(code, 0, err)
        sb = self.w.sb
        text = sb.read(self.w.user(".local/share/applications/org.kde.kate.desktop"))
        pd = os.path.join(sb.home, ".local/lib/appglass/qt6")
        dms = os.path.join(sb.cache, "dms")
        lv = json.loads(self.w.run("levels")[1])
        flags = ("--filesystem=%s:ro --filesystem=%s:ro "
                 "--env=QT_PLUGIN_PATH=%s:/app/lib/plugins:/usr/share/runtime/lib/plugins "
                 "--env=QT_STYLE_OVERRIDE=appglass --env=APPGLASS_COLORS=%s "
                 "--env=APPGLASS_CONTENT=%s --env=APPGLASS_BAR=%s "
                 "--env=XDG_CONFIG_DIRS=%s:/app/etc/xdg:/etc/xdg"
                 % (pd, dms, pd, os.path.join(dms, "dms-colors.json"),
                    repr(float(lv["content"])), repr(float(lv["bar_over_content"])),
                    os.path.join(sb.home, ".var/app/org.kde.kate/config/appglass")))
        execs = re.findall(r"(?m)^Exec=(.*)$", text)
        self.assertEqual(execs, [
            "/usr/bin/flatpak run %s --branch=stable --arch=x86_64 --command=kate "
            "--file-forwarding org.kde.kate -b @@u %%U @@" % flags,
            "/usr/bin/flatpak run %s --branch=stable --arch=x86_64 --command=kate "
            "org.kde.kate --startanon" % flags])
        self.assertTrue(sb.readb(self.w.user(SO)).startswith(b"FAKE-BUILD"))
        code, out, err = self.w.run("apply", "--only", "qtstyle")
        self.assertIn("qtstyle: up to date", out)
        code, out, err = self.w.run("remove", "--only", "qtstyle")
        self.assertEqual(code, 0, err)
        self.assertEqual(sb.tree_hash(), self.before)

    def runtime(self, rt):
        d = self.w.sb.path("flatpak", "app", "org.kde.kate", "current", "active")
        with open(os.path.join(d, "metadata"), "w") as f:
            f.write("[Application]\nname=org.kde.kate\nruntime=%s\n" % rt)

    def test_a_runtime_on_another_qt_minor_gets_no_style(self):
        # w2 r2: the host-built style loads only into a KDE runtime of the
        # host Qt minor (6.11 here): with another one the launcher and the
        # glass katerc are not written, and apply and status say why
        sb = self.w.sb
        path = self.w.user(".local/share/applications/org.kde.kate.desktop")
        rc = os.path.join(sb.home, ".var/app/org.kde.kate/config/appglass/katerc")
        code, out, err = self.w.run("apply", "--only", "qtstyle,kate")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(rc))
        self.assertIn("QT_STYLE_OVERRIDE=appglass", sb.read(path))
        for rt in ("org.kde.Platform/x86_64/6.8", "org.freedesktop.Platform/x86_64/25.08"):
            with self.subTest(rt=rt):
                self.runtime(rt)
                code, out, err = self.w.run("apply", "--only", "qtstyle,kate")
                self.assertEqual(code, 0, err)
                self.assertIn("org.kde.kate: ", out + err)
                self.assertFalse(os.path.exists(path) and "appglass" in sb.read(path),
                                 out + err)
                self.assertFalse(os.path.exists(rc), out + err)
                code, out, err = self.w.run("status")
                self.assertEqual(code, 0, err)
                line = [x for x in out.splitlines() if x.startswith("  org.kde.kate ")]
                self.assertEqual(len(line), 1, out)
                self.assertEqual(line[0].split()[3], "fallback", line[0])
                self.assertIn("Qt 6.8" if "6.8" in rt else "not a KDE runtime", line[0])
        self.runtime("org.kde.Platform/x86_64/6.11")
        code, out, err = self.w.run("apply", "--only", "qtstyle,kate")
        self.assertIn("QT_STYLE_OVERRIDE=appglass", sb.read(path))
        code, out, err = self.w.run("remove")
        self.assertEqual(code, 0, err)
        self.assertEqual(sb.tree_hash(), self.before)

    def test_flatpak_start_has_no_fade(self):
        # no unfocused fade reaches the flatpak start (0.1.4)
        self.w.sb.set_level(0.8)
        code, out, err = self.w.run("apply", "--only", "qtstyle")
        self.assertEqual(code, 0, err)
        text = self.w.sb.read(self.w.user(".local/share/applications/org.kde.kate.desktop"))
        self.assertEqual(text.count("--env=APPGLASS_CONTENT=0.8 "), 2)
        self.assertNotIn("APPGLASS_INACTIVE", text)
        self.assertNotIn("APPGLASS_FADE", text)


if __name__ == "__main__":
    unittest.main()
