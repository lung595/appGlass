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
        level = repr(float(json.loads(self.w.run("levels")[1])["content"]))
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

    def test_not_installed(self):
        os.remove(os.path.join(self.w.bin, "vlc"))
        self.apply()
        self.assertEqual(self.w.tc.builds(), [])
        self.assertFalse(os.path.exists(self.w.user(SO)))


if __name__ == "__main__":
    unittest.main()
