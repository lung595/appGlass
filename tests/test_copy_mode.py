"""Copies of the user's files (backup/, ring blobs, .appglass-changed) are
private (0600): the original may hold a token. The files appglass writes
for the apps keep the usual umask mode."""

import os
import stat
import unittest

from fixtures.sandbox import Sandbox
from appglass import core


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


class CopyMode(unittest.TestCase):
    def setUp(self):
        self.old_umask = os.umask(0o022)
        sb = self.sb = Sandbox()
        sb.seed_dms()
        sb.seed_niri()
        self.conf = sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        os.chmod(self.conf, 0o600)
        self.state_dir = os.path.join(sb.state, "appglass")

    def tearDown(self):
        os.umask(self.old_umask)
        self.sb.cleanup()

    def copies(self):
        out = []
        for sub in ("backup", "ring"):
            for root, _, names in os.walk(os.path.join(self.state_dir, sub)):
                out += [os.path.join(root, n) for n in names if n != "manifest.json"]
        return out

    def test_backups_and_blobs_are_private(self):
        code, out, err = self.sb.run("apply", "--only", "alacritty", assume="alacritty")
        self.assertEqual(code, 0, err)
        copies = self.copies()
        self.assertTrue(copies)
        for p in copies:
            self.assertEqual(mode(p), 0o600, p)
        # a file appglass creates for the app: the umask mode, as before
        self.assertEqual(mode(self.sb.cfg("alacritty", "appglass.toml")), 0o644)
        self.assertEqual(mode(self.conf), 0o600)

    def test_write_durable_new_file(self):
        p = os.path.join(self.sb.root, "copy")
        core._write_durable(p, b"x")
        self.assertEqual(mode(p), 0o600)

    def test_atomic_write_new_file_keeps_umask_mode(self):
        p = os.path.join(self.sb.root, "new")
        core._atomic_write(p, b"x")
        self.assertEqual(mode(p), 0o644)


if __name__ == "__main__":
    unittest.main()
