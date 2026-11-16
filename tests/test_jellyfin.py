import os
import re
import unittest

from fixtures.shimcase import ShimCase

L = ".local/lib/appglass/jellyfin/"


class Jellyfin(ShimCase, unittest.TestCase):
    FAMILY = "jellyfin"
    KEY = "org.jellyfin.JellyfinDesktop"
    FLATPAK = KEY
    SYSTEM = "org.jellyfin.JellyfinDesktop.desktop"
    LAUNCHER = ".local/share/applications/org.jellyfin.JellyfinDesktop.desktop"
    FILES = {L + "libjfglass.so": 0o644, L + "jfglass.cpp": 0o644,
             L + "jellyfin-glass.css.tmpl": 0o644, L + "gen-css.sh": 0o755,
             L + "jellyfin-glass.css": 0o644, ".local/bin/appglass-jellyfin": 0o755}
    CSS = L + "jellyfin-glass.css"
    BUILDS = 1

    def test_launcher_actions(self):
        self.enable()
        self.apply()
        w = self.w.user(".local/bin/appglass-jellyfin")
        text = self.w.sb.read(self.w.user(self.LAUNCHER))
        self.assertEqual(re.findall(r"(?m)^Exec=(.*)$", text),
                         [w, w + " --fullscreen --desktop", w + " --windowed --desktop",
                          w + " --fullscreen --tv", w + " --windowed --tv"])

    def test_runtime_update_rebuilds(self):
        self.enable()
        self.apply()
        meta = self.w.sb.path("flatpak", "app", self.FLATPAK, "current", "active", "metadata")
        with open(meta, "w") as f:
            f.write("[Application]\nname=%s\nruntime=org.kde.Platform/x86_64/6.11\n" % self.FLATPAK)
        self.apply()
        self.assertEqual(len(self.w.tc.builds()), 2)

    def test_css_colours(self):
        self.enable()
        self.apply()
        css = self.w.sb.read(self.w.user(self.CSS))
        self.assertNotIn("{{", css)
        self.assertRegex(css, r"\d+, \d+, \d+")


if __name__ == "__main__":
    unittest.main()
