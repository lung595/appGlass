"""inactive: the level maths, the settings block, the niri instant fallback."""

import types
import unittest

from fixtures.sandbox import Sandbox
from appglass import core, inactive, niri, settings


class Maths(unittest.TestCase):
    def test_level_and_floor(self):
        self.assertEqual(inactive.level(0.80, 0.90), 0.72)
        self.assertEqual(inactive.level(0.65, 0.90), 0.60)   # floored
        self.assertEqual(inactive.level(0.60, 0.80), 0.60)   # at the floor: unchanged
        self.assertEqual(inactive.level(0.40, 0.80), 0.40)   # under it: unchanged
        self.assertEqual(inactive.level(1.0, 1.0), 1.0)
        self.assertEqual(inactive.ratio(0.80, 0.90), 0.9)
        self.assertEqual(inactive.ratio(0.60, 0.90), 1.0)

    def test_default_fade_is_visible(self):
        """The defaults (factor 0.90, 180 ms, ease-out-cubic) give an
        unfocused window a fade one can see: 0.80 -> 0.72, never under the
        0.60 floor; the vibrancy ratio is the same fade."""
        d = settings.validate({})["inactive"]
        self.assertEqual((d["enabled"], d["factor"], d["durationMs"], d["easing"]),
                         (True, 0.9, 180, "ease-out-cubic"))
        self.assertEqual(inactive.FLOOR, 0.60)
        self.assertEqual(inactive.level(0.80, d["factor"]), 0.72)
        self.assertEqual(inactive.ratio(0.80, d["factor"]), 0.9)
        for c in (0.70, 0.80, 0.90, 1.0):
            lv = inactive.level(c, d["factor"])
            self.assertGreaterEqual(round(c - lv, 4), 0.07, c)
            self.assertGreaterEqual(lv, inactive.FLOOR)
        self.assertEqual(inactive.level(0.65, d["factor"]), 0.60)
        self.assertGreater(inactive.ease(d["easing"], 0.25), 0.5)    # most of it early

    def test_active(self):
        s = settings.validate({})
        self.assertTrue(inactive.active(s, 0.8))
        self.assertFalse(inactive.active(s, 0.6))
        self.assertFalse(inactive.active(settings.validate({"inactive": {"enabled": False}}), 0.8))
        self.assertFalse(inactive.active(settings.validate({"inactive": {"factor": 1.0}}), 0.8))

    def test_transition_and_easing(self):
        s = settings.validate({})
        self.assertEqual(inactive.transition("background-color", s),
                         "background-color 180ms cubic-bezier(0.33, 1, 0.68, 1)")
        s = settings.validate({"inactive": {"durationMs": 0}})
        self.assertEqual(inactive.transition("background-color", s), "none")
        s = settings.validate({"inactive": {"easing": "linear", "durationMs": 250}})
        self.assertEqual(inactive.transition("x", s), "x 250ms linear")
        for name in inactive.EASINGS:
            self.assertEqual(inactive.ease(name, 0), 0)
            self.assertEqual(inactive.ease(name, 1), 1)
            self.assertEqual(inactive.ease(name, 2), 1)
            vals = [inactive.ease(name, i / 20) for i in range(21)]
            self.assertEqual(vals, sorted(vals))
        self.assertAlmostEqual(inactive.ease("ease-in-out", 0.5), 0.5)
        self.assertGreater(inactive.ease("ease-out-cubic", 0.5), 0.8)


class Schema(unittest.TestCase):
    def test_defaults(self):
        s = settings.validate({})
        self.assertEqual(s["inactive"], {"enabled": True, "factor": 0.9, "durationMs": 180,
                                         "easing": "ease-out-cubic",
                                         "instantFallback": False})

    def test_values(self):
        s = settings.validate({"inactive": {"factor": 0.8, "durationMs": 400.0,
                                            "easing": "ease-in-out", "enabled": False}})
        self.assertEqual(s["inactive"]["durationMs"], 400)
        self.assertIsInstance(s["inactive"]["durationMs"], int)
        self.assertEqual(s["inactive"]["factor"], 0.8)
        self.assertEqual(settings.validate(s), s)

    def test_bad(self):
        for b in ({"inactive": []}, {"inactive": {"factor": 0.5}},
                  {"inactive": {"factor": 1.1}}, {"inactive": {"durationMs": 401}},
                  {"inactive": {"durationMs": -1}}, {"inactive": {"durationMs": 12.5}},
                  {"inactive": {"durationMs": True}}, {"inactive": {"easing": "bounce"}},
                  {"inactive": {"enabled": "yes"}}, {"inactive": {"instantFallback": 1}},
                  {"inactive": {"level": 0.9}}):
            with self.subTest(b=b):
                with self.assertRaises(settings.SettingsError):
                    settings.validate(b)

    def test_set_get_cli(self):
        sb = Sandbox()
        try:
            sb.seed_dms()
            code, out, err = sb.run("set", "inactive.durationMs", "250")
            self.assertEqual(code, 0, err)
            code, out, err = sb.run("get", "inactive.durationMs")
            self.assertEqual(out.strip(), "250")
            code, out, err = sb.run("set", "inactive.durationMs", "999")
            self.assertNotEqual(code, 0)
        finally:
            sb.cleanup()


def fake_app(owners, s, content=0.8):
    st = types.SimpleNamespace(owners=owners, families=lambda: sorted(owners))
    return types.SimpleNamespace(settings=settings.validate(s), state=st,
                                 levels=types.SimpleNamespace(content=content))


VIBRANCY = {"files": {"/h/.config/systemd/user/appglass-vibrancy.service": {}}}


class NiriInstant(unittest.TestCase):
    OWNERS = {"gtk4": {"app_ids": [r"^org\.gnome\.Nautilus$"]},
              "herdr": {"app_ids": [r"^herdr$"]},
              "alacritty": {"app_ids": [r"^Alacritty$"]},
              "hook": VIBRANCY}

    def test_off_by_default(self):
        self.assertEqual(niri.instant_inactive(fake_app(self.OWNERS, {})), (None, None))

    def test_only_apps_without_a_fade(self):
        app = fake_app(self.OWNERS, {"inactive": {"instantFallback": True}})
        self.assertEqual(niri.instant_inactive(app), (0.9, [r"^herdr$"]))
        t = niri.render([r"^Alacritty$", r"^herdr$", r"^org\.gnome\.Nautilus$"],
                        inactive=0.9, inactive_ids=[r"^herdr$"])
        self.assertIn('match app-id=r#"^herdr$"# is-active=false', t)
        self.assertNotIn('Alacritty$"# is-active=false', t)
        self.assertIn("opacity 0.90", t)

    def test_nothing_at_the_floor_or_disabled(self):
        on = {"inactive": {"instantFallback": True}}
        self.assertEqual(niri.instant_inactive(fake_app(self.OWNERS, on, 0.6)), (None, None))
        off = {"inactive": {"instantFallback": True, "enabled": False}}
        self.assertEqual(niri.instant_inactive(fake_app(self.OWNERS, off)), (None, None))
        lever_only = {k: v for k, v in self.OWNERS.items() if k != "herdr"}
        self.assertEqual(niri.instant_inactive(fake_app(lever_only, on)), (None, None))

    def test_an_app_a_lever_family_fades_is_not_dimmed_again(self):
        """Kate and Konsole fade through the Qt style: their own families
        are no lever, but the niri dim would dim them a second time."""
        owners = dict(self.OWNERS,
                      kate={"app_ids": [r"^org\.kde\.kate$"]},
                      konsole={"app_ids": [r"^org\.kde\.konsole$"]},
                      qtstyle={"app_ids": [r"^vlc$", r"^org\.kde\.kate$",
                                           r"^org\.kde\.konsole$"]})
        on = {"inactive": {"instantFallback": True}}
        self.assertEqual(niri.instant_inactive(fake_app(owners, on)), (0.9, [r"^herdr$"]))
        del owners["herdr"]
        self.assertEqual(niri.instant_inactive(fake_app(owners, on)), (None, None))

    def test_fallback_inactive_still_wins(self):
        app = fake_app(self.OWNERS, {"fallback": {"inactive": 0.55},
                                     "inactive": {"instantFallback": True}})
        self.assertEqual(niri.instant_inactive(app), (0.55, [r"^herdr$"]))

    def test_fallback_inactive_leaves_the_faded_apps_out(self):
        """w2: fallback.inactive dimmed every glass app, the ones that fade
        their own background too (dimmed twice)."""
        app = fake_app(self.OWNERS, {"fallback": {"inactive": 0.55}})
        self.assertEqual(niri.instant_inactive(app), (0.55, [r"^herdr$"]))
        app = fake_app({"herdr": {"app_ids": [r"^herdr$"]}}, {"fallback": {"inactive": 0.55}})
        self.assertEqual(niri.instant_inactive(app), (0.55, None))

    def test_fallback_inactive_dims_every_app_while_nothing_fades(self):
        """r2: with the fade off (or at the floor) the lever apps do not
        fade either: fallback.inactive must dim them too."""
        off = {"fallback": {"inactive": 0.55}, "inactive": {"enabled": False}}
        self.assertEqual(niri.instant_inactive(fake_app(self.OWNERS, off)), (0.55, None))
        floor = {"fallback": {"inactive": 0.55}}
        self.assertEqual(niri.instant_inactive(fake_app(self.OWNERS, floor, 0.6)), (0.55, None))

    def test_alacritty_fades_only_with_the_vibrancy_unit(self):
        """w2: without appglass-vibrancy.service nothing fades Alacritty:
        it gets the dim like the apps with no lever."""
        owners = {k: v for k, v in self.OWNERS.items() if k != "hook"}
        on = {"inactive": {"instantFallback": True}}
        self.assertEqual(niri.instant_inactive(fake_app(owners, on)),
                         (0.9, [r"^Alacritty$", r"^herdr$"]))
        self.assertEqual(niri.instant_inactive(fake_app(dict(owners, hook=VIBRANCY), on)),
                         (0.9, [r"^herdr$"]))

    def test_every_lever_family_exists(self):
        for name in inactive.LEVER_FAMILIES:
            self.assertIn(name, core.discover())


if __name__ == "__main__":
    unittest.main()
