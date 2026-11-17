"""Golden files: the apps the gtk3, qtstyle and gtk4 families listed by hand
before the engine routes records to them (gtk3 APPS, qtstyle LAUNCHERS, gtk4
APPS) render byte-identical files. tests/fixtures/golden/b5.json was written
by the code before the change (GOLDEN_WRITE=1 rewrites it)."""

import hashlib
import json
import os
import unittest

from fixtures.sandbox import fixture
from fixtures.shimworld import ShimWorld
from appglass.families import gtk4

GOLDEN = fixture("golden", "b5.json")


def world():
    w = ShimWorld(bins=("vlc", "solaar", "nvidia-settings", "nautilus", "zenity"))
    sb = w.sb
    with open(fixture("launchers/vlc.desktop")) as f:
        w.launcher("vlc.desktop", f.read())
    for n in ("solaar.desktop", "nvidia-settings.desktop"):
        with open(fixture("gtk/applications/" + n)) as f:
            w.launcher(n, f.read())
    sysconf = sb.path("etc-xdg")
    sb.seed("gtk/autostart/solaar.desktop", "autostart/solaar.desktop", base=sysconf)
    sb.env["XDG_CONFIG_DIRS"] = sysconf
    sb.seed("gtk/dank-colors.css", "gtk-3.0/dank-colors.css")
    sb.seed("gtk/dank-colors.css", "gtk-4.0/dank-colors.css")
    libexec = sb.path("libexec")
    os.makedirs(libexec)
    w.exe("../../libexec/xdg-desktop-portal-gnome")
    return w, libexec


def rendered(w):
    """{rel path: sha256 of the content, the sandbox root written @ROOT@}."""
    sb = w.sb
    out = {}
    for top in (sb.home,):
        for dp, dns, fns in os.walk(top):
            dns[:] = [d for d in dns if os.path.join(dp, d) not in (sb.state, sb.cache)]
            for fn in fns:
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, sb.root)
                if rel.startswith(("home/.config/dms/", "home/.config/gtk-3.0/dank-colors",
                                   "home/.config/gtk-4.0/dank-colors")):
                    continue
                data = sb.readb(p) if not os.path.islink(p) else os.readlink(p).encode()
                data = data.replace(sb.root.encode(), b"@ROOT@")
                out[rel] = hashlib.sha256(data).hexdigest()
    return out


class Golden(unittest.TestCase):
    def setUp(self):
        self.w, libexec = world()
        self._libexec = gtk4.LIBEXEC_DIRS
        gtk4.LIBEXEC_DIRS = (libexec,)

    def tearDown(self):
        gtk4.LIBEXEC_DIRS = self._libexec
        self.w.cleanup()

    def test_hand_listed_apps_render_the_same_files(self):
        code, out, err = self.w.run("apply", "--only", "gtk3,qtstyle,gtk4")
        self.assertEqual(code, 0, err)
        got = rendered(self.w)
        if os.environ.get("GOLDEN_WRITE"):
            os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
            with open(GOLDEN, "w") as f:
                json.dump(got, f, indent=1, sort_keys=True)
                f.write("\n")
        with open(GOLDEN) as f:
            want = json.load(f)
        self.assertEqual(got, want)
        # the hand-listed apps are all there
        for rel in ("home/.local/share/applications/solaar.desktop",
                    "home/.local/share/applications/nvidia-settings.desktop",
                    "home/.local/share/applications/vlc.desktop",
                    "home/.config/autostart/solaar.desktop",
                    "home/.config/gtk-4.0/dank-glass.css",
                    "home/.config/niri/appglass.kdl"):
            self.assertIn(rel, got)
        kdl = self.w.sb.read(self.w.sb.cfg("niri", "appglass.kdl"))
        for rx in ("solaar|nvidia-settings", "vlc", "Nautilus", "Zenity", "portal-gnome"):
            self.assertIn(rx, kdl)


if __name__ == "__main__":
    unittest.main()
