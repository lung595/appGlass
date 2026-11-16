import os
import re
import unittest

from fixtures.shimcase import ShimCase

L = ".local/lib/appglass/localsend/"


class LocalSend(ShimCase, unittest.TestCase):
    FAMILY = "localsend"
    KEY = "org.localsend.localsend_app"
    FLATPAK = KEY
    SYSTEM = "org.localsend.localsend_app.desktop"
    LAUNCHER = ".local/share/applications/org.localsend.localsend_app.desktop"
    FILES = {L + "appglass-ck.so": 0o755, L + "appglass-ck.c": 0o644,
             ".local/bin/appglass-localsend": 0o755}
    BUILDS = 1

    def test_launcher_keeps_file_args(self):
        self.enable()
        self.apply()
        text = self.w.sb.read(self.w.user(self.LAUNCHER))
        self.assertEqual(re.findall(r"(?m)^Exec=(.*)$", text),
                         [self.w.user(".local/bin/appglass-localsend") + " %U"])

    def test_other_ck_shim_apps_not_listed(self):
        from appglass import adapters
        from appglass.core import discover
        rec = {"key": "ai.storyteller.artcraft-launcher", "toolkit": "egui",
               "names": ["ai.storyteller.artcraft-launcher"]}
        r = adapters.resolve(rec, discover())
        self.assertEqual(r["adapter"], "ck-shim")
        self.assertIsNone(r["family"])
        self.assertEqual(r["effective"], "fallback")


if __name__ == "__main__":
    unittest.main()
