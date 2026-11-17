"""Shared tests of the opt-in shim families (a mixin: subclasses set the
class attributes and setup_world). Every family is checked for:

* off by default (a forced / mod adapter writes nothing until enabled);
* apply: every file of FILES with its mode, the launcher pointing at the
  wrapper with the system launcher's arguments, the wrapper calling this
  repo's bin/appglass; remove gives the tree back;
* hand files: a conflict (nothing written), adopt hands them over and
  switches the family on, remove restores them byte-identical with modes;
* step 13: a level change re-renders the CSS on apply --from-hook, without
  a rebuild;
* a dry run writes nothing and builds nothing.
"""

import json
import os
import re

from fixtures.sandbox import fixture  # noqa: F401  (sets sys.path)
from appglass import shims
from fixtures.sandbox import fixture
from fixtures.shimworld import ShimWorld


class ShimCase:
    FAMILY = None
    KEY = None
    FILES = {}            # rel path -> mode
    LAUNCHER = None       # rel path of the override
    SYSTEM = None         # fixture name under launchers/
    FLATPAK = None        # app id: the system launcher is a flatpak export
    BINS = ()
    CSS = None            # rel path of a rendered CSS (step 13)
    BUILDS = 0            # compiler runs of one build
    REBUILDS = None       # compiler runs to rebuild the first .so of FILES (default BUILDS)

    def setUp(self):
        self.w = ShimWorld(bins=self.BINS)
        with open(fixture("launchers/" + self.SYSTEM)) as f:
            self.system = f.read()
        if self.FLATPAK:
            meta = self.w.sb.path("flatpak", "app", self.FLATPAK, "current", "active",
                                  "metadata")
            os.makedirs(os.path.dirname(meta))
            with open(meta, "w") as f:
                f.write("[Application]\nname=%s\nruntime=org.kde.Platform/x86_64/6.10\n"
                        % self.FLATPAK)
        self.w.launcher(self.SYSTEM, self.system, flatpak=bool(self.FLATPAK))
        self.before = self.w.sb.tree_hash()

    def tearDown(self):
        self.w.cleanup()

    def run_ok(self, *argv):
        code, out, err = self.w.run(*argv)
        self.assertEqual(code, 0, err)
        return out, err

    def settings(self, apps):
        """settings.json with apps (by app key: `appglass set` takes no
        dotted app keys; the DMS plugin writes them this way)."""
        p = os.path.join(self.w.sb.config, "appglass", "settings.json")
        if apps is None:
            os.remove(p)
            return
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump({"apps": apps}, f)

    def enable(self):
        self.settings({self.KEY: {"enabled": True}})
        self.before = self.w.sb.tree_hash()

    def apply(self, *extra):
        return self.run_ok("apply", "--only", self.FAMILY, *extra)

    def test_off_by_default(self):
        out, err = self.apply()
        # the engine's gate (spec 1.4): an injected route waits for its check
        self.assertIn("%s: waiting, skipped" % self.FAMILY, out + err)
        self.assertEqual(self.w.sb.tree_hash(), self.before)
        self.assertEqual(self.w.tc.builds(), [])
        self.settings({self.FAMILY: {"enabled": False}})
        out, err = self.apply()
        self.assertIn("%s: off in settings, skipped" % self.FAMILY, out + err)
        self.assertEqual(self.w.tc.builds(), [])

    def test_apply_and_remove(self):
        self.enable()
        out, err = self.apply()
        for rel, mode in self.FILES.items():
            p = self.w.user(rel)
            self.assertTrue(os.path.isfile(p), rel)
            self.assertEqual(self.w.mode(p), mode, rel)
        self.assertEqual(len(self.w.tc.builds()), self.BUILDS)
        launcher = self.w.sb.read(self.w.user(self.LAUNCHER))
        execs = re.findall(r"(?m)^Exec=(.*)$", launcher)
        self.assertTrue(execs)
        wrapper = None
        for line in execs:
            wrapper = line.split()[0]
            self.assertEqual(os.path.dirname(wrapper), self.w.user(".local/bin"))
            self.assertNotIn("@@", line)
        self.assertIn(wrapper, [self.w.user(r) for r in self.FILES])
        scripts = [self.w.sb.readb(self.w.user(r)) for r, m in self.FILES.items() if m == 0o755
                   and not r.endswith(".so")]
        self.assertTrue(any(shims.APPGLASS.encode() in t for t in scripts))
        self.assertFalse(any(shims.PLACEHOLDER.encode() in t for t in scripts))
        if self.CSS:
            self.assertNotIn("{{", self.w.sb.read(self.w.user(self.CSS)))
        state = self.w.state()
        self.assertIn(self.FAMILY, state["owners"])
        self.run_ok("remove")
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_hand_files_conflict_then_adopt(self):
        hand = {}
        for rel, mode in self.FILES.items():
            hand[rel] = (b"hand-made " + rel.encode() + b"\n", 0o700 if mode == 0o755 else 0o640)
            self.w.hand(rel, *hand[rel])
        hand[self.LAUNCHER] = (b"[Desktop Entry]\nExec=hand\n", 0o644)
        self.w.hand(self.LAUNCHER, *hand[self.LAUNCHER])
        self.settings({self.KEY: {"enabled": True}})
        out, err = self.apply()
        self.assertIn("%s: skipped" % self.FAMILY, err)
        for rel, (data, mode) in hand.items():
            self.assertEqual(self.w.sb.readb(self.w.user(rel)), data, rel)
        self.assertNotIn(self.FAMILY, self.w.state()["owners"])
        self.settings(None)
        out, err = self.run_ok("adopt", *["~/" + r for r in hand])
        self.assertIn("apps.%s.enabled" % self.FAMILY, out + err)
        out, err = self.apply()
        self.assertNotIn("skipped", err)
        for rel in self.FILES:
            self.assertNotEqual(self.w.sb.readb(self.w.user(rel)), hand[rel][0], rel)
        self.run_ok("remove")
        for rel, (data, mode) in hand.items():
            p = self.w.user(rel)
            self.assertEqual(self.w.sb.readb(p), data, rel)
            self.assertEqual(self.w.mode(p), mode, rel)

    def test_level_change_rerenders_css_only(self):
        if not self.CSS:
            self.skipTest("no rendered CSS")
        self.enable()
        self.apply()
        css = self.w.sb.read(self.w.user(self.CSS))
        others = {r: self.w.sb.readb(self.w.user(r)) for r in self.FILES if r != self.CSS}
        builds = len(self.w.tc.builds())
        self.w.sb.set_level(0.55)
        self.run_ok("apply", "--from-hook")
        self.assertNotEqual(self.w.sb.read(self.w.user(self.CSS)), css)
        self.assertEqual(len(self.w.tc.builds()), builds)
        for r, data in others.items():
            self.assertEqual(self.w.sb.readb(self.w.user(r)), data, r)

    def test_dry_run(self):
        self.enable()
        out, err = self.apply("--dry-run")
        self.assertIn("%s: would write" % self.FAMILY, out)
        self.assertEqual(self.w.tc.builds(), [])
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_build_stamp(self):
        if not self.BUILDS:
            self.skipTest("nothing built")
        self.enable()
        self.apply()
        self.apply()
        self.assertEqual(len(self.w.tc.builds()), self.BUILDS)
        so = [r for r in self.FILES if r.endswith(".so")][0]
        os.chmod(self.w.user(so), 0o644)
        with open(self.w.user(so), "ab") as f:
            f.write(b"changed by hand")
        self.apply()
        again = self.BUILDS if self.REBUILDS is None else self.REBUILDS
        self.assertEqual(len(self.w.tc.builds()), self.BUILDS + again)

    # adopt --rescue: every file the family wrote is recorded again, so
    # remove gives the tree back (state.json lost, then the whole state dir)
    def rescue_tree(self):
        sd = os.path.join(self.w.sb.state, "appglass")
        out = {}
        for dp, dns, fns in os.walk(self.w.sb.root):
            if dp == sd or dp.startswith(sd + os.sep):
                continue
            out[os.path.relpath(dp, self.w.sb.root) + "/"] = None
            for fn in fns:
                q = os.path.join(dp, fn)
                with open(q, "rb") as f:
                    out[os.path.relpath(q, self.w.sb.root)] = (f.read(), os.stat(q).st_mode)
        return out

    def check_rescue(self, whole):
        import shutil
        self.enable()
        before = self.rescue_tree()
        self.apply()
        sd = os.path.join(self.w.sb.state, "appglass")
        if whole:
            shutil.rmtree(sd)
        else:
            os.remove(os.path.join(sd, "state.json"))
        out, err = self.run_ok("adopt", "--rescue")
        for rel in list(self.FILES) + [self.LAUNCHER]:
            self.assertIn(os.path.basename(rel), out + err, rel)
        out2, err2 = self.run_ok("remove")
        after = self.rescue_tree()
        diff = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        self.assertEqual(diff, [], out + err + out2 + err2)

    def test_rescue_after_state_json_lost(self):
        self.check_rescue(False)

    def test_rescue_after_state_dir_lost(self):
        self.check_rescue(True)
