"""detect: static toolkit detection over a fake world (no real system read)."""

import json
import os
import unittest

from fixtures.sandbox import Sandbox
from fixtures.apps import World, elf, record
from appglass import core, detect


class Elf(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.cleanup()

    def test_needed(self):
        p = self.sb.write("x/bin", elf(["libgtk-4.so.1", "libadwaita-1.so.0"]))
        self.assertEqual(detect.elf_needed(p), ["libgtk-4.so.1", "libadwaita-1.so.0"])
        self.assertTrue(detect.is_elf(p))

    def test_not_elf(self):
        p = self.sb.write("x/sh", "#!/bin/sh\n")
        self.assertEqual(detect.elf_needed(p), [])
        self.assertEqual(detect.elf_needed(self.sb.path("missing")), [])
        p = self.sb.write("x/trunc", b"\x7fELF\x02\x01")
        self.assertEqual(detect.elf_needed(p), [])

    def test_resolve_app_every_component(self):
        root = self.sb.path("files")
        os.makedirs(os.path.join(root, "real"))
        open(os.path.join(root, "real", "bin"), "w").close()
        os.makedirs(os.path.join(root, "opt"))
        os.symlink("/app/real", os.path.join(root, "opt", "x"))
        os.symlink("/app/opt/x/bin", os.path.join(root, "cmd"))
        self.assertEqual(detect.resolve("/app/cmd", root), os.path.join(root, "real", "bin"))
        self.assertEqual(detect.resolve(os.path.join(root, "opt/x/bin"), root),
                         os.path.join(root, "real", "bin"))

    def test_exec_argv(self):
        self.assertEqual(detect.exec_argv("env A=1 B=2 /usr/bin/vlc --x %U"),
                         ["/usr/bin/vlc", "--x"])
        self.assertEqual(detect.exec_argv("env -u X FOO=1 app"), ["app"])
        self.assertEqual(detect.exec_argv('"/opt/My App/run" %f'), ["/opt/My App/run"])


class Scan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sb = Sandbox()
        cls.world = World(cls.sb).build()
        cls.sb.env.update(cls.world.env())
        env = core.Env(cls.sb.env)
        cls.recs = detect.scan(env)

    @classmethod
    def tearDownClass(cls):
        cls.sb.cleanup()

    def rec(self, key):
        return record(self.recs, key)

    def test_toolkits(self):
        want = {
            "org.gnome.Nautilus": "gtk4-adw",
            "vlc": "qt-widgets",
            "solaar": "gtk3",
            "com.github.tchx84.Flatseal": "gtk4",
            "Alacritty": "terminal",
            "herdr-app": "gpui",
            "dev.duxlabs.files": "go-launcher",
            "nvidia-settings": "gtk3",
            "org.mozilla.firefox": "gecko",
            "discord": "electron",
            "steam": "cef",
            "Pinball": "game",
            "org.example.Flutter": "flutter",
            "md.example.Electron": "electron",
            "ghost": "unknown",
        }
        got = {k: self.rec(k)["toolkit"] for k in want}
        self.assertEqual(got, want)

    def test_skipped_entries(self):
        keys = {r["key"] for r in self.recs}
        self.assertNotIn("hidden", keys)
        self.assertNotIn("link", keys)

    def test_app_ids(self):
        self.assertEqual(self.rec("org.gnome.Nautilus")["app_ids"], [r"^org\.gnome\.Nautilus$"])
        self.assertEqual(self.rec("Pinball")["app_ids"], [r"^steam_app_480$"])
        self.assertEqual(self.rec("discord")["names"][0], "discord")
        self.assertIn("firefox", self.rec("org.mozilla.firefox")["names"])

    def test_user_override_shadows_system(self):
        r = self.rec("vlc")
        self.assertEqual(r["path"], os.path.join(self.world.apps, "vlc.desktop"))
        self.assertEqual(r["overridden_by"], os.path.join(self.world.user_apps, "vlc.desktop"))
        self.assertIsNone(self.rec("herdr-app")["overridden_by"])

    def test_flatpak_app_remap(self):
        r = self.rec("org.example.Flutter")
        self.assertTrue(r["exec"].endswith("/files/real/localsend_app"), r["exec"])
        self.assertIn("links libflutter_linux_gtk.so -> flutter", r["evidence"])
        self.assertEqual(r["flatpak"]["installation"], "system")
        self.assertFalse(self.rec("org.example.Missing")["installed"])

    def test_electron_fuses(self):
        r = self.rec("md.example.Electron")
        self.assertEqual(r["fuses"]["electron"], "43.8.9")
        self.assertEqual(r["fuses"]["EnableCookieEncryption"], "1")
        self.assertEqual(r["fuses"]["EnableNodeOptionsEnvironmentVariable"], "0")
        self.assertIn("flatpak base org.electronjs.Electron2.BaseApp -> electron", r["evidence"])

    def test_discord_updater_and_vencord(self):
        r = self.rec("discord")
        self.assertTrue(r["vencord"])
        self.assertEqual(r["fuses"]["electron"], "44.1.0")
        self.assertTrue(any("Discord updater" in e for e in r["evidence"]))

    def test_weak_evidence_marked(self):
        r = self.rec("com.github.tchx84.Flatseal")
        self.assertTrue(r["evidence"][0].endswith("(weak)"))

    def test_cli_json(self):
        code, out, err = self.sb.run("detect", "--json")
        self.assertEqual(code, 0, err)
        got = json.loads(out)
        # the engine adds each launcher's fingerprint (engine.fingerprint)
        self.assertTrue(all(len(r.pop("fp")) == 16 for r in got))
        self.assertEqual(got, json.loads(json.dumps(self.recs)))
        code, out, err = self.sb.run("detect")
        self.assertIn("org.gnome.Nautilus", out)
        self.assertNotIn("org.example.Missing", out)


if __name__ == "__main__":
    unittest.main()
