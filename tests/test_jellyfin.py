import json
import os
import re
import subprocess
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

    def test_gen_css_takes_only_hex_colours(self):
        """A colour that is not 6 hex digits (here one that would end the
        sed expression and add a command) falls back to the built-in one."""
        self.enable()
        self.apply()
        p = os.path.join(self.w.sb.cache, "dms", "dms-colors.json")
        d = json.loads(self.w.sb.read(p))
        d["mode"] = "dark"
        d["colors"]["dark"]["surface_container"] = "#1/;w x"
        d["colors"]["dark"]["on_surface"] = "#ABCDEF"
        with open(p, "w") as f:
            json.dump(d, f)
        lib = self.w.user(L)
        out = os.path.join(self.w.sb.root, "gen.css")
        r = subprocess.run([os.path.join(lib, "gen-css.sh"),
                            os.path.join(lib, "jellyfin-glass.css.tmpl"), out],
                           env=self.w.sb.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        css = self.w.sb.read(out)
        self.assertIn("rgb(33, 34, 26)", css)                    # 21221a, the fallback
        self.assertIn("rgb(171, 205, 239)", css)                 # ABCDEF taken
        self.assertFalse(os.path.exists(os.path.join(self.w.sb.root, " x")))


if __name__ == "__main__":
    unittest.main()
