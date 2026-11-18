"""settings.json: schema, get/set, sync --settings-file, the plugin as one writer."""

import json
import os
import unittest

from fixtures.sandbox import Sandbox
from appglass import core, settings


class Schema(unittest.TestCase):
    def test_defaults(self):
        s = settings.validate({})
        self.assertEqual(s, settings.DEFAULTS)
        self.assertEqual(s["fallback"]["mode"], "opaque")
        self.assertIsNone(s["levels"]["content"])

    def test_bad_values_rejected(self):
        bad = [
            [],
            {"version": 2},
            {"nope": 1},
            {"enabled": "yes"},
            {"levels": {"content": 1.5}},
            {"levels": {"content": 0.1}},
            {"levels": {"content": True}},
            {"levels": {"content": "0.6"}},
            {"levels": {"content": 0.8, "bar": 0.7}},
            {"levels": {"x": 1}},
            {"fallback": {"mode": "dim"}},
            {"fallback": {"value": 0.2}},
            {"fallback": {"inactive": 2}},
            {"apps": {"bad key": {}}},
            {"apps": {"steam": {"enabled": 1}}},
            {"apps": {"steam": {"route": "a b"}}},
            {"apps": {"steam": {"color": "red"}}},
            {"apps": []},
        ]
        for b in bad:
            with self.subTest(b=b):
                with self.assertRaises(settings.SettingsError):
                    settings.validate(b)

    def test_normalised(self):
        s = settings.validate({"fallback": {"mode": "0.70", "value": 0.7},
                               "levels": {"content": 0.8},
                               "apps": {"steam": {"enabled": False, "route": "cdp"}}})
        self.assertEqual(s["fallback"], {"mode": "value", "value": 0.7, "inactive": None})
        self.assertEqual(s["levels"], {"content": 0.8, "bar": None})
        self.assertEqual(s["apps"]["steam"], {"enabled": False, "route": "cdp"})
        self.assertEqual(settings.validate(s), s)

    def test_set_key(self):
        s = settings.validate({})
        s2 = settings.set_key(s, "apps.vlc.enabled", False)
        self.assertEqual(s2["apps"], {"vlc": {"enabled": False}})
        self.assertEqual(s["apps"], {})
        with self.assertRaises(settings.SettingsError):
            settings.set_key(s, "levels.nope", 1)
        with self.assertRaises(settings.SettingsError):
            settings.set_key(s, "fallback.mode", "dim")
        # a route is an adapter's name; a file that names an unknown one
        # (an older appglass's) still loads
        with self.assertRaises(settings.SettingsError) as cm:
            settings.set_key(s, "apps.gtk3.route", "foo")
        self.assertIn("gtk3", str(cm.exception))
        self.assertEqual(settings.set_key(s, "apps.vlc.route", "gtk3")["apps"],
                         {"vlc": {"route": "gtk3"}})
        self.assertEqual(settings.validate({"apps": {"vlc": {"route": "foo"}}})["apps"],
                         {"vlc": {"route": "foo"}})
        self.assertEqual(settings.parse_value("0.7"), 0.7)
        self.assertIsNone(settings.parse_value("null"))
        self.assertEqual(settings.parse_value("opaque"), "opaque")


class Cli(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.seed_dms()
        self.path = self.sb.cfg("appglass", "settings.json")

    def tearDown(self):
        self.sb.cleanup()

    def test_created_settings_recorded_and_removed(self):
        """settings.json written by set (or sync, adopt) is recorded in
        state.json; a full remove with nothing else left deletes it and
        ~/.config/appglass."""
        before = self.sb.tree_hash()
        self.assertEqual(self.sb.run("set", "fallback.mode", "off")[0], 0)
        st = self.sb.json(os.path.join(self.sb.state, "appglass", "state.json"))
        self.assertEqual(st["owners"]["settings"]["files"][self.path]["kind"], "created")
        self.assertEqual(self.sb.run("set", "fallback.value", "0.6")[0], 0)
        self.assertEqual(self.sb.json(self.path)["fallback"]["value"], 0.6)
        self.assertEqual(self.sb.run("remove", "--only", "alacritty")[0], 0)
        self.assertTrue(os.path.exists(self.path))      # not a full remove
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertIn("settings: removed", out)
        self.assertFalse(os.path.exists(self.sb.cfg("appglass")))
        self.assertEqual(self.sb.tree_hash(), before)

    def test_hand_edited_created_settings_kept_on_remove(self):
        self.assertEqual(self.sb.run("set", "fallback.mode", "off")[0], 0)
        with open(self.path, "a") as f:
            f.write("\n")
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(self.path))
        self.assertIn("kept as is", out + err)

    def test_settings_there_before_stay_the_users(self):
        self.sb.write("appglass/settings.json", "{}\n")
        self.assertEqual(self.sb.run("set", "fallback.mode", "off")[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.sb.state, "appglass", "state.json")))
        self.assertEqual(self.sb.run("remove")[0], 0)
        self.assertEqual(self.sb.json(self.path)["fallback"]["mode"], "off")

    def test_get_defaults_writes_nothing(self):
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("get")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), settings.DEFAULTS)
        code, out, err = self.sb.run("get", "fallback.mode")
        self.assertEqual(json.loads(out), "opaque")
        self.assertEqual(self.sb.run("get", "nope")[0], 1)
        self.assertEqual(self.sb.tree_hash(), before)

    def test_set_round_trip(self):
        code, out, err = self.sb.run("set", "levels.content", "0.75")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.json(self.path)["levels"]["content"], 0.75)
        code, out, err = self.sb.run("levels")
        self.assertEqual(json.loads(out)["content8"], 191)
        self.sb.run("set", "apps.steam.enabled", "false")
        self.sb.run("set", "fallback.mode", "value")
        s = json.loads(self.sb.run("get")[1])
        self.assertEqual(s["apps"], {"steam": {"enabled": False}})
        self.assertEqual(s["fallback"]["mode"], "value")
        self.assertEqual(s, settings.validate(self.sb.json(self.path)))
        raw = self.sb.readb(self.path)
        self.assertIn("(unchanged)", self.sb.run("set", "fallback.mode", "value")[1])
        self.assertEqual(self.sb.readb(self.path), raw)

    def test_set_bad_value_keeps_file(self):
        self.sb.run("set", "fallback.mode", "off")
        raw = self.sb.readb(self.path)
        for k, v in (("fallback.mode", "dim"), ("levels.content", "3"),
                     ("levels.bar", "0.1"), ("nope", "1"), ("apps.x.y", "1"),
                     ("apps.gtk3.route", "foo")):
            code, out, err = self.sb.run("set", k, v)
            self.assertEqual(code, 1, (k, v))
            self.assertIn("set %s" % k, err)
        self.assertEqual(self.sb.readb(self.path), raw)

    def test_set_refused_when_plugin_marker(self):
        self.sb.write("dms/plugins/appGlass/plugin.json", '{"id": "appGlass"}')
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("set", "fallback.mode", "off")
        self.assertEqual(code, 1)
        self.assertIn("managed by the DMS plugin", err)
        self.assertEqual(self.sb.tree_hash(), before)
        # DMS has the plugin disabled: the CLI is the writer again
        self.sb.write("dms/plugin_settings.json", '{"appGlass": {"enabled": false}}')
        self.assertEqual(self.sb.run("set", "fallback.mode", "off")[0], 0)

    def test_invalid_file_on_disk(self):
        self.sb.write("appglass/settings.json", '{"fallback": {"mode": "dim"}}')
        code, out, err = self.sb.run("get", "fallback.mode")
        self.assertEqual(json.loads(out), "opaque")
        self.assertIn("settings ignored", err)
        code, out, err = self.sb.run("apply", assume_not=",".join(core.discover()))
        self.assertEqual(code, 1)
        self.assertIn("settings.json is invalid", err)

    def test_sync_validates_saves_applies(self):
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        others = ",".join(n for n in core.discover() if n != "alacritty")
        before = self.sb.tree_hash()
        f = self.sb.write("plugin.json.tmp", json.dumps({"fallback": {"mode": "bogus"}}),
                          base=self.sb.root)
        before = self.sb.tree_hash()
        code, out, err = self.sb.run("sync", "--settings-file", f,
                                     assume="alacritty", assume_not=others)
        self.assertEqual(code, 1)
        self.assertIn("rejected, nothing saved", err)
        self.assertEqual(self.sb.tree_hash(), before)
        with open(f, "w") as fh:
            json.dump({"levels": {"content": 0.8}, "fallback": {"mode": "off"}}, fh)
        code, out, err = self.sb.run("sync", "--settings-file", f,
                                     assume="alacritty", assume_not=others)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sb.json(self.path)["levels"]["content"], 0.8)
        toml = self.sb.read(self.sb.cfg("alacritty", "alacritty.toml"))
        self.assertIn("appglass", toml)
        # enabled false: everything comes out again
        with open(f, "w") as fh:
            json.dump({"enabled": False}, fh)
        code, out, err = self.sb.run("sync", "--settings-file", f,
                                     assume="alacritty", assume_not=others)
        self.assertEqual(code, 0, err)
        st = self.sb.json(os.path.join(self.sb.state, "appglass", "state.json"))
        self.assertEqual(sorted(st["owners"]), ["settings"])    # glass off: settings kept
        self.assertFalse(os.path.exists(self.sb.cfg("niri", "appglass.kdl")))
        # the plugin marker does not stop sync (the plugin is the writer)
        self.sb.write("dms/plugins/appGlass/plugin.json", "{}")
        self.assertEqual(self.sb.run("sync", "--settings-file", f)[0], 0)

    def test_app_switch_off_removes_family(self):
        self.sb.seed_niri()
        self.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        others = ",".join(n for n in core.discover() if n != "alacritty")
        orig = self.sb.read(self.sb.cfg("alacritty", "alacritty.toml"))
        self.sb.run("apply", assume="alacritty", assume_not=others)
        self.sb.run("set", "apps.alacritty.enabled", "false")
        code, out, err = self.sb.run("apply", assume="alacritty", assume_not=others)
        self.assertEqual(code, 0, err)
        self.assertIn("alacritty: off in settings, files removed", out)
        self.assertEqual(self.sb.read(self.sb.cfg("alacritty", "alacritty.toml")), orig)


if __name__ == "__main__":
    unittest.main()
