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
        # the gate in place of OPT_IN: on, but waiting for its check
        self.assertIs(routes["discord"]["enabled"], True)
        self.assertEqual(routes["discord"]["state"], "waiting")
        self.assertEqual(routes["discord"]["effective"], "fallback")
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

    def test_a_family_removed_by_hand_says_so(self):
        self.sb.seed_dms()
        # gtk4 stays applied: a remove of the last family takes the state out
        code, out, err = self.sb.run("apply", "--only", "gtk3,gtk4", assume="gtk3,gtk4")
        self.assertEqual(code, 0, err)
        self.assertEqual({a["key"]: a for a in self.doc()["apps"]}["solaar"]["effective"], "glass")
        code, out, err = self.sb.run("remove", "--only", "gtk3", assume="gtk3,gtk4")
        self.assertEqual(code, 0, err)
        solaar = {a["key"]: a for a in self.doc()["apps"]}["solaar"]
        self.assertEqual(solaar["effective"], "fallback")
        self.assertIn("family gtk3 removed", solaar["reason"])
        code, out, err = self.sb.run("status", assume="gtk3,gtk4")
        line = next(l for l in out.splitlines() if l.strip().startswith("solaar"))
        self.assertIn("family gtk3 removed", line)
        self.assertEqual(line.split()[3], "fallback")

    def test_a_user_gtk_css_keeps_the_gtk4_apps_off_glass(self):
        # w2 r2: apply skips gtk4 over a user stylesheet (no glass for its
        # apps), so status must not count them as glass
        user = "/* my own css */ window { color: red; }\n"
        self.sb.write("gtk-4.0/gtk.css", user)
        apps = {a["key"]: a for a in self.doc()["apps"]}
        for key in ("org.gnome.Nautilus", "com.github.tchx84.Flatseal"):
            self.assertEqual((apps[key]["effective"], apps[key]["state"]), ("fallback", "opaque"), key)
            self.assertIn("user stylesheet", apps[key]["reason"])
        # the opt-in line the skip names: glass again
        self.sb.write("gtk-4.0/gtk.css", '@import url("dank-colors.css");\n'
                      '@import url("dank-glass.css");\n' + user)
        apps = {a["key"]: a for a in self.doc()["apps"]}
        self.assertEqual(apps["org.gnome.Nautilus"]["effective"], "glass")
        # only DMS's import (apply merges it) or none (apply writes it): glass
        self.sb.write("gtk-4.0/gtk.css", '@import url("dank-colors.css");\n')
        self.assertEqual({a["key"]: a for a in self.doc()["apps"]}["org.gnome.Nautilus"]["effective"],
                         "glass")

    def test_obsidian_with_no_vault_is_not_glass(self):
        from appglass.families import obsidian
        env = core.Env(self.sb.env)
        rec = {"key": "md.obsidian.Obsidian", "flatpak": None}
        self.assertIn("no Obsidian vaults found", obsidian.skip_reason(env, rec))
        vault = os.path.join(self.sb.home, "Notes")
        os.makedirs(vault)
        self.sb.write(os.path.join("obsidian", "obsidian.json"),
                      json.dumps({"vaults": {"a": {"path": vault}}}))
        self.assertIsNone(obsidian.skip_reason(env, rec))
        # an obsidian.json that does not read: apply keeps the files, not known
        self.sb.write(os.path.join("obsidian", "obsidian.json"), "{")
        self.assertIsNone(obsidian.skip_reason(env, rec))

    def test_not_installed_family(self):
        routes = {a["key"]: a for a in json.loads(self.sb.run(
            "status", "--json", assume_not="gtk3")[1])["apps"]}
        self.assertEqual(routes["solaar"]["effective"], "fallback")
        self.assertIn("not installed", routes["solaar"]["reason"])

    def test_route_choices(self):
        apps = {a["key"]: a for a in self.doc()["apps"]}
        # the family's adapter first, then the app-id route, then the toolkit's
        # a toolkit adapter whose families do not list the app is left out:
        # picked, it would only give the fallback
        self.assertEqual(apps["discord"]["routes"], ["electron-vencord"])
        self.assertEqual(apps["md.example.Electron"]["routes"], [])
        self.assertEqual(apps["org.example.Flutter"]["routes"], [])
        # Steam has no route: opaque, no switch (docs/steam.md)
        self.assertEqual(apps["steam"]["routes"], [])
        self.assertEqual((apps["steam"]["adapter"], apps["steam"]["state"]), ("niri-fallback", "opaque"))
        self.assertIsNone(apps["steam"]["enabled"])
        self.assertEqual(apps["vlc"]["routes"], ["qt-style"])
        self.assertEqual(apps["Alacritty"]["routes"], ["terminal"])
        for key in ("org.mozilla.firefox", "Pinball"):
            self.assertEqual(apps[key]["routes"], [], key)
        self.assertIsNone(apps["discord"]["route"])
        self.assertEqual(self.sb.run("set", "apps.discord.route", "electron-hook")[0], 0)
        apps = {a["key"]: a for a in self.doc()["apps"]}
        self.assertEqual(apps["discord"]["route"], "electron-hook")
        self.assertEqual(apps["discord"]["adapter"], "electron-hook")
        self.assertEqual(apps["discord"]["routes"], ["electron-vencord"])

    def test_every_route_offered_is_the_route_taken(self):
        """Each route an app offers, once picked, is the adapter resolve
        gives it (never the fallback of a family that does not list it)."""
        from appglass import settings
        path = settings.path(core.Env(self.sb.env))
        base = json.loads(self.sb.run("get")[1])
        doc = self.doc()
        for a in doc["apps"]:
            for r in a["routes"]:
                # written as the plugin hands it over (app keys may hold dots)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    json.dump(dict(base, apps={a["key"]: {"route": r}}), f)
                got = {x["key"]: x for x in self.doc()["apps"]}[a["key"]]
                self.assertEqual(got["adapter"], r, (a["key"], r))
                self.assertNotIn("does not list this app", got["reason"], (a["key"], r))

    def test_conflicts(self):
        apps = {a["key"]: a for a in self.doc()["apps"]}
        # a hand-made VLC launcher appglass does not own: vlc shows it
        self.assertEqual(apps["vlc"]["conflicts"], ["~/.local/share/applications/vlc.desktop"])
        self.assertEqual(apps["solaar"]["conflicts"], [])
        self.assertEqual(apps["Pinball"]["conflicts"], [])

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
