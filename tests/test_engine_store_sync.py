"""Store: a changed marker is rewritten (a reset reads it), a hand-edited
engine.json of the right version is reset, not crashed on; family_gate reads
the switch the way adapters.switch does (the family wins)."""

import json
import os
import tempfile
import unittest
from unittest import mock

from fixtures.sandbox import Sandbox  # noqa: F401  (sets sys.path)
from appglass import engine


class Env:
    def __init__(self, d):
        self.state_dir = d

    def guard(self, p):
        pass


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.env = Env(self.d)

    def test_marker_rewritten_when_reason_changes(self):
        st = engine.Store(self.env)
        st.set_plain("foo", "fp1", engine.WAITING, why="waiting")
        st.save()
        st.set_plain("foo", "fp1", "check failed: white window")
        st.save()
        with open(engine.marker(self.env, "foo")) as f:
            self.assertEqual(f.read().strip(), "check failed: white window")
        with open(os.path.join(self.d, "engine.json"), "w") as f:
            f.write("{broken")
        p = engine.Store(self.env).get("foo")["plain"]
        self.assertEqual(p["why"], "kept")

    def test_apps_not_a_dict_resets(self):
        for apps in (["x"], {"k": "str"}):
            with open(os.path.join(self.d, "engine.json"), "w") as f:
                json.dump({"version": engine.STORE_VERSION, "apps": apps}, f)
            st = engine.Store(self.env)
            self.assertEqual(st.plain, {})
            self.assertEqual(st.get("k"), {})


class Fam:
    OPT_IN = True
    KEYS = ("discord",)


class App:
    def __init__(self, d, settings):
        self.env = Env(d)
        self.settings = settings
        self.families = {"vencord": Fam}


class FamilyGateTest(unittest.TestCase):
    def test_family_switch_wins_over_app_key(self):
        app = App(tempfile.mkdtemp(), {"apps": {"vencord": {"enabled": True},
                                                "discord": {"enabled": False}}})
        self.assertTrue(engine.explicit_on(app, "vencord", "discord"))
        with mock.patch.object(engine, "record_for", return_value=None):
            self.assertIsNone(engine.family_gate(app, "vencord"))


if __name__ == "__main__":
    unittest.main()
