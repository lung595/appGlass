"""status --json: adapter routes for the fixture world (golden)."""

import json
import os
import unittest

from fixtures.sandbox import Sandbox
from fixtures.apps import World
from appglass import adapters, core

GOLDEN = os.path.join(os.path.dirname(__file__), "fixtures", "status", "golden.json")


class Status(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.world = World(self.sb).build()
        self.sb.env.update(self.world.env())

    def tearDown(self):
        self.sb.cleanup()

    def doc(self, *extra):
        code, out, err = self.sb.run("status", "--json", *extra)
        self.assertEqual(code, 0, err)
        return json.loads(out.replace(self.sb.root, "<ROOT>"))

    def test_golden(self):
        got = self.doc()
        if os.environ.get("APPGLASS_REGEN"):
            with open(GOLDEN, "w") as f:
                f.write(json.dumps(got, indent=2, sort_keys=True) + "\n")
        with open(GOLDEN) as f:
            self.assertEqual(got, json.load(f))

    def test_deterministic_and_read_only(self):
        before = sorted(os.walk(self.sb.root))
        self.assertEqual(self.doc(), self.doc())
        self.assertEqual(sorted(os.walk(self.sb.root)), before)

    def test_routes(self):
        routes = {a["key"]: a for a in self.doc()["apps"]}
        self.assertEqual(routes["org.mozilla.firefox"]["effective"], "delegated")
        self.assertEqual(routes["Pinball"]["effective"], "opaque")
        self.assertEqual(routes["discord"]["tier"], "mod")
        self.assertIs(routes["discord"]["enabled"], False)
        self.assertEqual(routes["solaar"]["family"], "gtk3")
        self.assertEqual(routes["vlc"]["adapter"], "qt-style")
        self.assertEqual(routes["vlc"]["family"], "qtstyle")
        self.assertEqual(routes["vlc"]["effective"], "glass")

    def test_settings_switch_and_route(self):
        self.assertEqual(self.sb.run("set", "apps.solaar.enabled", "false")[0], 0)
        self.assertEqual(self.sb.run("set", "apps.vlc.route", "kvantum")[0], 0)
        routes = {a["key"]: a for a in self.doc()["apps"]}
        self.assertEqual(routes["solaar"]["effective"], "fallback")
        self.assertEqual(routes["solaar"]["reason"], "off in settings")
        self.assertEqual(routes["vlc"]["adapter"], "kvantum")

    def test_not_installed_family(self):
        routes = {a["key"]: a for a in json.loads(self.sb.run(
            "status", "--json", assume_not="gtk3")[1])["apps"]}
        self.assertEqual(routes["solaar"]["effective"], "fallback")
        self.assertIn("not installed", routes["solaar"]["reason"])

    def test_catalogue(self):
        fams = core.discover()
        for a in adapters.CATALOGUE:
            self.assertIn(a.TIER, adapters.TIERS)
            for f in a.FAMILIES:
                self.assertIn(f, fams, a.NAME)
            self.assertEqual(a.FAMILY, a.FAMILIES[0] if a.FAMILIES else None, a.NAME)
        self.assertEqual({f for a in adapters.CATALOGUE for f in a.FAMILIES}, set(fams))
        for rel, ad, what in adapters.HAND_FILES:
            self.assertTrue(ad in (None, "hook") or ad in adapters.BY_NAME, rel)


if __name__ == "__main__":
    unittest.main()
