"""docs/apps.md is generated from docs/apps.json (python3 -m appglass.appstable)."""

import json
import os
import tempfile
import unittest

from appglass import appstable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def shot(mode=153, share=0.9, text=5000, popup=None, error=None):
    return {"level": 153, "window": {"alpha_mode": mode, "share_at_level": share,
                                     "light_text_px_255": text},
            "popup": popup, "error": error}


class Verdict(unittest.TestCase):
    def test_pass(self):
        v = appstable.verdict(shot(popup={"share_255": 0.9}))
        self.assertEqual((v["result"], v["bg"], v["popup"]), ("PASS", 153, 0.9))

    def test_bg_off_level_fails(self):
        v = appstable.verdict(shot(mode=194))
        self.assertEqual(v["result"], "FAIL")
        self.assertIn("bg 194", v["why"])

    def test_small_share_fails(self):
        self.assertEqual(appstable.verdict(shot(share=0.3))["result"], "FAIL")

    def test_no_opaque_text_fails(self):
        self.assertIn("text", appstable.verdict(shot(text=0))["why"])

    def test_translucent_popup_fails(self):
        v = appstable.verdict(shot(popup={"share_255": 0.2}))
        self.assertEqual(v["result"], "FAIL")
        self.assertIn("popup", v["why"])

    def test_run_error_fails(self):
        self.assertEqual(appstable.verdict(shot(error="no window"))["result"], "FAIL")


ROW = {"app": "foot", "toolkit": "own", "family": "foot", "route": "alpha",
       "tested": "here", "result": "glass", "evidence": "adapters/foot.json"}


class Render(unittest.TestCase):
    def test_measured_row(self):
        row = dict(ROW, measured={"result": "PASS", "bg": 153, "share": 0.99, "text": 900,
                                  "popup": None})
        md = appstable.render([row])
        self.assertIn("| foot |", md)
        self.assertIn("PASS: bg 153 (99%), text 255, no popup", md)

    def test_opaque_needs_a_reason(self):
        with self.assertRaises(ValueError):
            appstable.render([dict(ROW, result="opaque", tested="no")])

    def test_tested_here_needs_a_measurement(self):
        with self.assertRaises(ValueError):
            appstable.render([ROW])

    def test_unknown_values_refused(self):
        for k, v in (("tested", "maybe"), ("result", "shiny")):
            with self.assertRaises(ValueError):
                appstable.render([dict(ROW, measured={"result": "PASS"}, **{k: v})])

    def test_collect_fills_measurements(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "foot.json"), "w") as f:
                json.dump(shot(), f)
            rows = appstable.collect([dict(ROW)], d)
        self.assertEqual(rows[0]["measured"]["result"], "PASS")


class Docs(unittest.TestCase):
    def setUp(self):
        self.rows = appstable.load(os.path.join(REPO, "docs", "apps.json"))

    def test_apps_md_is_generated(self):
        with open(os.path.join(REPO, "docs", "apps.md")) as f:
            self.assertEqual(f.read(), appstable.render(self.rows),
                             "run: python3 -m appglass.appstable --write")

    def test_every_family_has_a_row(self):
        fams = {f[:-3] for f in os.listdir(os.path.join(REPO, "appglass", "families"))
                if f.endswith(".py") and not f.startswith("_")}
        listed = {r.get("family") for r in self.rows}
        self.assertEqual(sorted(fams - listed), [])

    def test_no_measurement_says_fail_on_a_glass_row(self):
        for r in self.rows:
            m = r.get("measured")
            if m and r["result"] == "glass":
                self.assertEqual(m["result"], "PASS", r["app"])


if __name__ == "__main__":
    unittest.main()
