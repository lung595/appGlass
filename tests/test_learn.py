"""learn: runtime toolkit from recorded niri windows + a fake /proc."""

import json
import os
import unittest

from fixtures.sandbox import Sandbox
from fixtures.apps import World, elf, fuse_blob, record
from appglass import core, learn

WINDOWS = [
    {"id": 1, "app_id": "com.github.tchx84.Flatseal", "pid": 101, "title": "Flatseal"},
    {"id": 2, "app_id": "discord", "pid": 102, "title": "#general - a friend"},
    {"id": 3, "app_id": "com.sgtaziz.lianlilinux", "pid": 103, "title": "L"},
    {"id": 4, "app_id": "org.example.Flutter", "pid": 104, "title": "F"},
    {"id": 5, "app_id": "Alacritty", "pid": 105, "title": "~"},
    {"id": 6, "app_id": "dev.duxlabs.files", "pid": 106, "title": "Files"},
    {"id": 7, "app_id": "gone", "pid": 107, "title": "x"},
    {"id": 8, "app_id": "discord", "pid": 102, "title": "second window"},
    {"id": 9, "app_id": "oo7-portal", "pid": 109, "title": "Unlock"},
]

MAPS = {
    101: ["/usr/lib64/libgtk-4.so.1.2400.1", "/usr/lib64/libadwaita-1.so.0",
          "/usr/lib64/libwebkitgtk-6.0.so.4.19.5", "/usr/lib64/libjavascriptcoregtk-6.0.so.1"],
    102: ["/home/u/.config/discord/app-1/libffmpeg.so", "/usr/lib64/libgtk-3.so.0.2400.1"],
    103: ["/usr/lib64/libwebkit2gtk-4.1.so.0.19.5", "/usr/lib64/libgtk-3.so.0.2400.1"],
    104: ["/app/lib/libflutter_linux_gtk.so", "/usr/lib/x86_64-linux-gnu/libgtk-3.so.0"],
    105: ["/usr/lib64/libc.so.6"],
    106: ["/usr/lib64/libQt6Widgets.so.6.10.0", "/usr/lib64/libQt6Quick.so.6.10.0"],
    109: ["/usr/lib64/libgtk-4.so.1"],
}


def fake_proc(sb, world_bin):
    root = sb.path("proc")
    exes = {101: "/usr/bin/gjs-console", 103: "/usr/bin/lianli-gui", 104: "/app/localsend_app",
            105: os.path.join(world_bin, "alacritty"), 106: "/usr/bin/dfiles",
            109: "/usr/libexec/oo7-portal"}
    electron = sb.write("discord-bin/Discord", elf(["libgtk-3.so.0"], fuse_blob("44.1.0")),
                        base=sb.root)
    exes[102] = electron
    for pid, libs in MAPS.items():
        d = os.path.join(root, str(pid))
        os.makedirs(d)
        with open(os.path.join(d, "maps"), "w") as f:
            for i, lib in enumerate(libs):
                f.write("7f%010x-7f%010x r-xp 00000000 00:1f 123 %s\n" % (i, i + 1, lib))
            f.write("7ffd0000-7ffd1000 rw-p 00000000 00:00 0 [stack]\n")
        os.symlink(exes[pid], os.path.join(d, "exe"))
        cg = ("0::/user.slice/app.slice/app-flatpak-org.example.Flutter-4242.scope\n"
              if pid == 104 else "0::/user.slice/app.slice/app-dms-x-abc.scope\n")
        with open(os.path.join(d, "cgroup"), "w") as f:
            f.write(cg)
    return root


class Learn(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.world = World(self.sb).build()
        self.sb.env.update(self.world.env())
        wf = self.sb.write("niri-windows.json", json.dumps(WINDOWS), base=self.sb.root)
        self.sb.env["APPGLASS_NIRI_WINDOWS"] = wf
        self.sb.env["APPGLASS_PROC"] = fake_proc(self.sb, self.world.bin)
        self.env = core.Env(self.sb.env)

    def tearDown(self):
        self.sb.cleanup()

    def test_toplevel_priority(self):
        got = {k: v["toolkit"] for k, v in learn.learn(self.env).items()}
        self.assertEqual(got, {
            "com.github.tchx84.Flatseal": "gtk4-adw",   # not webkitgtk
            "discord": "electron",                       # not gtk3
            "com.sgtaziz.lianlilinux": "webkitgtk",      # Tauri: webkit without gtk4
            "org.example.Flutter": "flutter",
            "Alacritty": "terminal",
            "dev.duxlabs.files": "qt-quick",
            "gone": "unknown",
            "oo7-portal": "gtk4",
        })

    def test_flatpak_from_cgroup_and_no_titles(self):
        found = learn.learn(self.env)
        self.assertEqual(found["org.example.Flutter"]["flatpak"], "org.example.Flutter")
        self.assertIsNone(found["discord"]["flatpak"])
        self.assertNotIn("a friend", json.dumps(found))

    def test_cli_saves_and_remove_forgets(self):
        code, out, err = self.sb.run("learn", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["com.github.tchx84.Flatseal"]["toolkit"], "gtk4-adw")
        p = learn.path(self.env)
        self.assertFalse(os.path.exists(p))
        self.assertEqual(self.sb.run("learn", "--dry-run")[0], 0)
        self.assertFalse(os.path.exists(p))
        code, out, err = self.sb.run("learn")
        self.assertEqual(code, 0, err)
        doc = self.sb.json(p)
        self.assertEqual(doc["apps"]["discord"]["toolkit"], "electron")
        self.assertNotIn("second window", json.dumps(doc))
        code, out, err = self.sb.run("remove")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(p))

    def test_detect_merges_runtime(self):
        code, out, err = self.sb.run("detect", "--json")
        self.assertEqual(code, 0, err)
        recs = json.loads(out)
        fl = record(recs, "com.github.tchx84.Flatseal")
        self.assertEqual(fl["toolkit"], "gtk4-adw")
        self.assertEqual(fl["toolkit_static"], "gtk4")
        dux = record(recs, "dev.duxlabs.files")
        self.assertEqual(dux["toolkit"], "qt-quick")
        self.assertEqual(dux["toolkit_static"], "go-launcher")
        portal = record(recs, "oo7-portal")
        self.assertEqual(portal["source"], "learned")
        self.assertEqual(portal["app_ids"], [r"^oo7-portal$"])

    def test_no_niri(self):
        del self.sb.env["APPGLASS_NIRI_WINDOWS"]
        env = dict(self.sb.env)
        env.pop("NIRI_SOCKET", None)
        self.assertIsNone(learn.learn(core.Env(env)))
        code, out, err = self.sb.run("learn")
        self.assertEqual(code, 1)
        self.assertIn("no niri session", err)


if __name__ == "__main__":
    unittest.main()
