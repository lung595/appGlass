"""A dms-colors.json whose colors (or the mode's entry) is not an object:
every command runs on, it never dies with a traceback."""

import json
import unittest

from fixtures.sandbox import Sandbox


class MalformedDmsColors(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()

    def tearDown(self):
        self.sb.cleanup()

    def check(self, data):
        self.sb.write("dms/dms-colors.json", json.dumps(data), base=self.sb.cache)
        for args in (("levels",), ("status",), ("apply", "--dry-run")):
            code, out, err = self.sb.run(*args)
            self.assertNotIn("Traceback", err, args)
            self.assertNotIn("AttributeError", err, args)

    def test_colors_a_list(self):
        self.check({"colors": [1]})

    def test_mode_entry_a_list(self):
        self.check({"colors": {"dark": [1]}})


if __name__ == "__main__":
    unittest.main()
