"""gimp.css: a begin marker with no end marker must not eat the user's rules."""

import unittest

import fixtures.sandbox  # noqa: F401  (sets sys.path)

from appglass.core import Conflict
from appglass.families import gimp

ORPHAN = "a{}\n" + gimp.BEGIN + "\n.x{}\n.user-rule { color: red; }\n"


class OrphanBegin(unittest.TestCase):
    def test_drop_block_refuses(self):
        with self.assertRaises(Conflict):
            gimp.drop_block(ORPHAN)

    def test_edit_and_undo_refuse(self):
        with self.assertRaises(Conflict):
            gimp.edit(ORPHAN, "BLK\n")
        with self.assertRaises(Conflict):
            gimp.undo(None, "gimp.css", ORPHAN)

    def test_closed_block_still_dropped(self):
        text = "a{}\n" + gimp.BEGIN + "\n.x{}\n" + gimp.END + "\nb{}\n"
        self.assertEqual(gimp.drop_block(text), "a{}\nb{}\n")


if __name__ == "__main__":
    unittest.main()
