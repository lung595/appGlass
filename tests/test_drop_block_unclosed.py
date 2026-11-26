"""Zed/VSCodium: a begin marker with no end marker must not eat the user's settings."""

import unittest

import fixtures.sandbox  # noqa: F401  (sets sys.path)

from appglass.core import Conflict
from appglass.families import vscodium, zed

UNCLOSED = ('{\n  ' + zed.BEGIN + '\n  "theme_overrides": {},\n'
            '  "font_size": 15,\n  "vim_mode": true\n}\n')


class UnclosedBlock(unittest.TestCase):
    def test_zed_undo_refuses(self):
        # raising sends core._revert to its 'undo failed' path, which keeps the bytes
        with self.assertRaises(Conflict):
            zed.undo(None, "x", UNCLOSED)

    def test_vscodium_undo_refuses(self):
        with self.assertRaises(Conflict):
            vscodium.undo(None, "x", UNCLOSED)

    def test_closed_block_still_dropped(self):
        text = '{\n' + zed.block("T", {"a": "#000000ff"}, True) + '  "font_size": 15\n}\n'
        self.assertEqual(zed.drop_block(text), '{\n  "font_size": 15\n}\n')


if __name__ == "__main__":
    unittest.main()
