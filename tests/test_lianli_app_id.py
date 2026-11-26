"""Lian Li: the niri rules must match the window's real app-id, lianli-gui."""

import re
import unittest

import fixtures.sandbox  # noqa: F401  (sets sys.path)

from appglass.families import lianli


class LianliAppId(unittest.TestCase):
    def test_window_app_id_matched(self):
        # docs/webkit.md: the window is 'lianli-gui', not the desktop file's id
        for app_id in ("lianli-gui", "com.sgtaziz.lianlilinux"):
            self.assertTrue(any(re.search(p, app_id) for p in lianli.APP_IDS), app_id)


if __name__ == "__main__":
    unittest.main()
