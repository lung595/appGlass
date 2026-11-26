"""appglass restore puts back only paths under the home folder or the XDG
dirs: a ring manifest naming any other path (edited by hand, an older
build) is refused whole, before any file changes."""

import json
import os
import unittest

from fixtures.sandbox import Sandbox


class RestoreOutsideHome(unittest.TestCase):
    def setUp(self):
        sb = self.sb = Sandbox()
        sb.seed_dms()
        sb.seed_niri()
        sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        code, out, err = sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertEqual(code, 0, err)
        self.ring = os.path.join(sb.state, "appglass", "ring")

    def tearDown(self):
        self.sb.cleanup()

    def test_a_path_outside_is_refused(self):
        # in the sandbox (so its guard lets it through) but not under home
        outside = os.path.join(self.sb.root, "outside", "keep")
        os.makedirs(os.path.dirname(outside))
        with open(outside, "w") as f:
            f.write("mine")
        entry = sorted(os.listdir(self.ring))[-1]
        mp = os.path.join(self.ring, entry, "manifest.json")
        with open(mp) as f:
            m = json.load(f)
        m["files"][outside] = {"absent": True}
        with open(mp, "w") as f:
            json.dump(m, f)
        before = self.sb.tree_hash(os.path.join(self.sb.home, ".config"))
        code, out, err = self.sb.run("restore", assume="alacritty")
        self.assertNotEqual(code, 0)
        self.assertIn(outside, err)
        self.assertTrue(os.path.isfile(outside))
        self.assertEqual(self.sb.tree_hash(os.path.join(self.sb.home, ".config")), before)


if __name__ == "__main__":
    unittest.main()
