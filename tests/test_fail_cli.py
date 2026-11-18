"""`appglass fail <key>`: the key appglass status shows records a failed
launch; any other key is refused with a clear error, never a traceback."""

import json
import os
import unittest

from fixtures.sandbox import Sandbox
from appglass import engine

LS = "org.localsend.localsend_app"


class FailCli(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.sb.seed_niri()

    def tearDown(self):
        self.sb.cleanup()

    def test_an_unknown_key_is_refused(self):
        for key in ("nosuchapp", "localsend"):
            code, out, err = self.sb.run("fail", key)
            self.assertEqual(code, 1, (key, out, err))
            self.assertIn("no app %s" % key, err)
            self.assertIn("appglass status", err)

    def test_the_status_key_counts(self):
        code, out, err = self.sb.run("status", "--json")
        self.assertIn(LS, [a["key"] for a in json.loads(out)["apps"]])
        code, out, err = self.sb.run("fail", LS)
        self.assertEqual(code, 0, err)
        self.assertIn("failed launch 1", out + err)

    def test_a_fails_entry_with_no_count_starts_at_one(self):
        """An entry with no count (the old fp-None case) is reset, not a
        KeyError."""
        st = os.path.join(self.sb.state, "appglass")
        self.sb.run("status")
        self.assertEqual(self.sb.run("fail", LS)[0], 0)
        path = os.path.join(st, "engine.json")
        doc = self.sb.json(path)
        fp = doc["apps"][LS]["fails"]["fp"]
        doc["apps"][LS]["fails"] = {"fp": fp}
        with open(path, "w") as f:
            json.dump(doc, f)
        code, out, err = self.sb.run("fail", LS)
        self.assertEqual(code, 0, err)
        self.assertIn("failed launch 1", out + err)


if __name__ == "__main__":
    unittest.main()
