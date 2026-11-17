"""docs/apps.md is generated from docs/apps.json (python3 -m appglass.appstable)."""

import json
import os
import tempfile
import unittest

from appglass import appstable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def shot(mode=153, share=0.9, text=5000, popup=None, error=None, regions=None):
    rep = {"level": 153, "window": {"alpha_mode": mode, "share_at_level": share,
                                    "light_text_px_255": text},
           "popup": popup, "error": error}
    if regions:
        rep["regions"] = regions
    return rep


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

    def test_opaque_glass_region_fails(self):
        # a large bg share can hide an opaque strip (a terminal panel, a breadcrumb bar)
        v = appstable.verdict(shot(regions={
            "terminal": {"glass": True, "opaque_share": 0.97},
            "editor": {"glass": True, "opaque_share": 0.02}}))
        self.assertEqual(v["result"], "FAIL")
        self.assertIn("terminal opaque (97%)", v["why"])
        self.assertNotIn("editor", v["why"])

    def test_region_not_expected_glass_may_be_opaque(self):
        v = appstable.verdict(shot(regions={"menu": {"glass": False, "opaque_share": 1.0},
                                            "editor": {"glass": True, "opaque_share": 0.1}}))
        self.assertEqual((v["result"], v["regions"]), ("PASS", 1))


ROW = {"app": "foot", "toolkit": "own", "family": "foot", "route": "alpha",
       "tested": "here", "result": "glass", "evidence": "adapters/foot.json"}


class Shown(unittest.TestCase):
    """The Result column is derived from the evidence, never taken from a hope."""

    def test_no_family_needs_an_adapter(self):
        for fam in (None, "", "-"):     # apps.json writes "-" for none
            self.assertEqual(appstable.shown(dict(ROW, family=fam, tested="probe", reason="x")),
                             "needs adapter")

    def test_family_not_verified_is_untested(self):
        for t in ("probe", "no"):
            self.assertEqual(appstable.shown(dict(ROW, tested=t)), "untested")

    def test_verified_rows_keep_their_result(self):
        self.assertEqual(appstable.shown(dict(ROW, tested="earlier", result="partial")), "partial")
        self.assertEqual(appstable.shown(dict(ROW, measured={"result": "PASS"})), "glass")

    def test_glass_without_an_opened_popup_says_so(self):
        # a toolkit that opens popups (menus, popovers) but the verify opened none
        for tk in ("GTK4 / libadwaita", "GTK3", "Qt6 Widgets", "Electron"):
            with self.subTest(toolkit=tk):
                self.assertEqual(appstable.shown(dict(ROW, toolkit=tk, measured={
                    "result": "PASS", "popup": None})), "glass (popups unverified)")
                self.assertEqual(appstable.shown(dict(ROW, toolkit=tk, measured={
                    "result": "PASS", "popup": 0.9})), "glass")
        # a terminal draws no popup surface: nothing to verify
        self.assertEqual(appstable.shown(dict(ROW, toolkit="own (pixman)", measured={
            "result": "PASS", "popup": None})), "glass")

    def test_failed_measurement_is_not_glass(self):
        self.assertEqual(appstable.shown(dict(ROW, measured={"result": "FAIL", "why": "x"},
                                              reason="y")), "partial")


class Render(unittest.TestCase):
    def test_counts_rows_and_derived_results(self):
        rows = [dict(ROW, app="Solaar, nvidia-settings", measured={"result": "PASS", "bg": 153,
                                                                    "share": 0.9, "popup": None}),
                dict(ROW, app="Ptyxis", family=None, tested="probe", evidence="b5b"),
                dict(ROW, app="kitty", family="kitty", tested="no", evidence=None)]
        md = appstable.render(rows)
        self.assertIn("3 rows (a row can name several apps)", md)
        self.assertIn("1 glass, 0 partial, 0 opaque, 1 untested, 1 needs adapter", md)
        self.assertIn("| Ptyxis | own | - | alpha | probe | needs adapter | probe: glass |", md)
        self.assertIn("| kitty | own | kitty | alpha | no | untested | expected: glass |", md)

    def test_popups_unverified_counts_as_glass(self):
        md = appstable.render([dict(ROW, toolkit="GTK3", measured={
            "result": "PASS", "bg": 153, "share": 0.9, "popup": None})])
        self.assertIn("1 glass (1 with popups unverified), 0 partial", md)
        self.assertIn("| here | glass (popups unverified) |", md)

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

    def test_family_must_exist(self):
        """A family is a module in appglass/families or '-' (needs adapter):
        keys passed by hand to the ck-shim are not a family."""
        with self.assertRaises(ValueError):
            appstable.render([dict(ROW, family="ck-shim (learned keys)", tested="no")])
        md = appstable.render([dict(ROW, family="-", tested="no")])
        self.assertIn("needs adapter", md)

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

    def test_glass_only_with_evidence(self):
        for r in self.rows:
            if appstable.shown(r).startswith("glass"):
                self.assertIn(r["tested"], ("here", "earlier"), r["app"])
                self.assertTrue(r.get("family"), r["app"])


if __name__ == "__main__":
    unittest.main()
