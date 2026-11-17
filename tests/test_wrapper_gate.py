"""Every launch wrapper of a gated family (OPT_IN, engine.family_gate) reads
the engine's plain/ marker for its key before it injects anything, and
hands its app's pid to launch-check: without them verify and two launches
with no window could not take the app plain."""

import glob
import importlib
import os
import re
import unittest

import fixtures.sandbox  # noqa: F401  (sets sys.path)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def gated():
    """[(family, wrapper source, its key)] for every OPT_IN family with a WRAPPER."""
    out = []
    for p in sorted(glob.glob(os.path.join(REPO, "appglass", "families", "*.py"))):
        name = os.path.basename(p)[:-3]
        if name.startswith("_"):
            continue
        m = importlib.import_module("appglass.families." + name)
        if getattr(m, "OPT_IN", False) and getattr(m, "WRAPPER", None):
            out.append((name, os.path.join(REPO, "shims", m.ADAPTER, m.WRAPPER), m.KEYS[0]))
    return out


def key_of(text):
    """The wrapper's AGKEY, with a "$ID" resolved."""
    v = re.search(r'^AGKEY="?([^"\n]+)"?$', text, re.M).group(1)
    if v == "$ID":
        v = re.search(r'^ID=(\S+)$', text, re.M).group(1)
    return v


class WrapperGate(unittest.TestCase):
    def test_some_wrappers_found(self):
        self.assertGreaterEqual(len(gated()), 6)

    def test_marker_and_launch_check(self):
        for name, path, key in gated():
            with self.subTest(family=name):
                with open(path) as f:
                    text = f.read()
                self.assertIn('appglass/plain/$AGKEY" ] && plain', text)
                self.assertRegex(text, r'setsid -f "@APPGLASS@" launch-check "\$AGKEY" \$')
                self.assertEqual(key_of(text), key)
                # the marker is read before any injection is set up
                self.assertLess(text.index("appglass/plain/$AGKEY"),
                                text.index("@APPGLASS@\" levels") if "\" levels" in text
                                else len(text))


if __name__ == "__main__":
    unittest.main()
