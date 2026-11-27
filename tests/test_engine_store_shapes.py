"""Store: a hand-edited engine.json of the right version with games, queue
or a plain entry of the wrong shape is reset, not crashed on later."""

import json
import os
import tempfile
import unittest

from fixtures.sandbox import Sandbox  # noqa: F401  (sets sys.path)
from appglass import engine


class Env:
    def __init__(self, d):
        self.state_dir = d

    def guard(self, p):
        pass


class StoreShapes(unittest.TestCase):
    def load(self, doc):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "engine.json"), "w") as f:
            json.dump(dict(doc, version=engine.STORE_VERSION), f)
        return engine.Store(Env(d))

    def test_bad_games_or_queue_resets(self):
        for doc in ({"games": ["x"]}, {"queue": {"a": 1}}, {"queue": "ab"}):
            st = self.load(doc)
            st.queue("k")
            st.dequeue("k")
            self.assertEqual(st.data["games"], {})
            self.assertEqual(st.data["queue"], [])

    def test_bad_plain_resets_and_keeps_a_good_one(self):
        st = self.load({"apps": {"bad": {"plain": "x"},
                                 "ok": {"plain": {"fp": None, "reason": "paused"}}}})
        self.assertEqual(st.plain, {"ok": {"fp": None, "reason": "paused"}})
        st.save()                                   # sync_markers reads each reason

    def test_good_file_is_not_reset(self):
        st = self.load({"apps": {"ok": {"plain": {"fp": "f", "reason": "r"}}},
                        "games": {"g": "steam"}, "queue": ["q"]})
        self.assertIsNone(st._bad)
        self.assertEqual(st.data["queue"], ["q"])


if __name__ == "__main__":
    unittest.main()
