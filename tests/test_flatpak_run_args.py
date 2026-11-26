"""Flatpak wrappers run the app's current branch and arch: no
--branch=stable --arch=x86_64 pinned (a beta branch or an aarch64 machine
would get 'not installed', the plain fallback too)."""

import os
import unittest

SHIMS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shims")
WRAPPERS = ("qtquick-shim/appglass-jellyfin", "ck-shim/appglass-localsend",
            "electron-hook/appglass-feishin", "electron-hook/appglass-vscodium")


class RunArgs(unittest.TestCase):
    def test_no_branch_or_arch_pinned(self):
        for w in WRAPPERS:
            with open(os.path.join(SHIMS, w)) as f:
                text = f.read()
            self.assertIn("flatpak", text, w)
            self.assertNotIn("--branch=", text, w)
            self.assertNotIn("--arch=", text, w)


if __name__ == "__main__":
    unittest.main()
