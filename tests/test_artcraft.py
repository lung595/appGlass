import os
import re
import subprocess
import unittest

from fixtures.shimcase import ShimCase

L = ".local/lib/appglass/artcraft/"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "shims", "ck-shim", "appglass-ck.c")


class ArtCraft(ShimCase, unittest.TestCase):
    FAMILY = "artcraft"
    KEY = "ai.storyteller.artcraft-launcher"
    BINS = ("artcraft-launcher",)
    SYSTEM = "ai.storyteller.artcraft-launcher.desktop"
    LAUNCHER = ".local/share/applications/ai.storyteller.artcraft-launcher.desktop"
    FILES = {L + "appglass-ck.so": 0o755, L + "appglass-ck.c": 0o644,
             ".local/bin/appglass-artcraft": 0o755}
    BUILDS = 1

    def test_launcher_exec_only(self):
        self.enable()
        self.apply()
        text = self.w.sb.read(self.w.user(self.LAUNCHER))
        self.assertEqual(re.findall(r"(?m)^Exec=(.*)$", text),
                         [self.w.user(".local/bin/appglass-artcraft")])
        # every other line is the system launcher's
        strip = lambda t: [l for l in t.splitlines() if not l.startswith("Exec=")]
        self.assertEqual(strip(text), strip(self.system))

    def test_wrapper(self):
        self.enable()
        self.apply()
        w = self.w.sb.read(self.w.user(".local/bin/appglass-artcraft"))
        self.assertNotIn("Projects/", w.replace(REPO, ""))
        self.assertIn('APPGLASS_MAXFPS="${APPGLASS_MAXFPS:-60}"', w)
        self.assertIn("APPGLASS_SCRUB=", w)
        self.assertIn('LD_PRELOAD="$LIB/appglass-ck.so', w)
        self.assertIn('LIB="$HOME/.local/lib/appglass/artcraft"', w)
        r = subprocess.run(["sh", "-n", self.w.user(".local/bin/appglass-artcraft")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_same_source_as_localsend(self):
        self.enable()
        self.apply()
        with open(SRC, "rb") as f:
            self.assertEqual(self.w.sb.readb(self.w.user(L + "appglass-ck.c")), f.read())

    def test_adopt_owner_per_app(self):
        """The ck-shim hand files go to the family of their app."""
        ls = ".local/lib/appglass/localsend/appglass-ck.so"
        mine = list(self.FILES) + [self.LAUNCHER]
        for rel in mine + [ls]:
            self.w.hand(rel, b"hand " + rel.encode() + b"\n", 0o644)
        self.run_ok("adopt", *["~/" + r for r in mine + [ls]])
        owners = self.w.state()["owners"]
        got = {r: o for o, rec in owners.items() for p in rec.get("files", {})
               for r in [os.path.relpath(p, self.w.user(""))]}
        for rel in mine:
            self.assertEqual(got.get(rel), "artcraft", rel)
        self.assertEqual(got.get(ls), "localsend")

    def test_route(self):
        from appglass import adapters
        from appglass.core import discover
        rec = {"key": self.KEY, "toolkit": "egui", "names": [self.KEY]}
        r = adapters.resolve(rec, discover())
        self.assertEqual((r["adapter"], r["tier"], r["family"]), ("ck-shim", "forced", "artcraft"))
        self.assertEqual(r["effective"], "fallback")      # opt-in
        r = adapters.resolve(rec, discover(), {"apps": {"artcraft": {"enabled": True}}})
        self.assertEqual(r["effective"], "glass")


if __name__ == "__main__":
    unittest.main()
