"""appglass hook install: the sync units, ~/.local/bin/appglass-sync, systemctl,
and bin/appglass-sync itself (Vencord re-inject, apply --from-hook)."""

import os
import shutil
import subprocess
import tempfile
import unittest

from fixtures.sandbox import REPO
from fixtures.shimworld import ShimWorld

UNITS = ("appglass-sync.path", "appglass-sync.service")
CTL = """#!/bin/sh
echo "$*" >> "%(log)s"
case "$*" in *is-enabled*) exit %(enabled)d ;; esac
exit 0
"""


def unit(w, n):
    return w.user(".config/systemd/user", n)


def repo_unit(n):
    with open(os.path.join(REPO, "shims", "sync", n), "rb") as f:
        return f.read()


class SyncUnits(unittest.TestCase):
    def setUp(self):
        self.w = ShimWorld()
        self.tmp = tempfile.mkdtemp(prefix="appglass-ctl-")
        self.log = os.path.join(self.tmp, "calls")
        self.before = self.w.sb.tree_hash()

    def tearDown(self):
        self.w.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctl(self, enabled=1):
        p = os.path.join(self.tmp, "systemctl")
        with open(p, "w") as f:
            f.write(CTL % {"log": self.log, "enabled": enabled})
        os.chmod(p, 0o755)
        self.w.sb.env["APPGLASS_SYSTEMCTL"] = p

    def calls(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def run_ok(self, *argv):
        code, out, err = self.w.run(*argv)
        self.assertEqual(code, 0, err)
        return out + err

    def test_install_writes_units_and_shim(self):
        out = self.run_ok("hook", "install")
        self.assertIn("systemctl skipped", out)
        for n in UNITS:
            with open(unit(self.w, n), "rb") as f:
                self.assertEqual(f.read(), repo_unit(n))
            self.assertEqual(self.w.mode(unit(self.w, n)), 0o644)
        shim = self.w.user(".local/bin/appglass-sync")
        self.assertEqual(self.w.mode(shim), 0o755)
        text = self.w.sb.read(shim)
        self.assertIn('exec "', text)
        self.assertTrue(text.rstrip().endswith('/bin/appglass-sync" "$@"'), text)
        self.run_ok("hook", "remove")
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_systemctl_enable_then_disable(self):
        self.ctl(enabled=1)
        self.run_ok("hook", "install")
        self.assertEqual(self.calls(), ["--user is-enabled --quiet appglass-sync.path",
                                        "--user daemon-reload",
                                        "--user enable --now appglass-sync.path"])
        self.run_ok("hook", "install")           # again: no new is-enabled
        self.assertEqual(self.calls()[3:], ["--user daemon-reload",
                                            "--user enable --now appglass-sync.path"])
        open(self.log, "w").close()
        self.run_ok("remove")
        self.assertEqual(self.calls(), ["--user disable --now appglass-sync.path",
                                        "--user daemon-reload"])
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_hand_units_conflict_then_adopt(self):
        hand = {n: self.w.hand(".config/systemd/user/" + n, repo_unit(n)) for n in UNITS}
        script = self.w.hand(".local/bin/appglass-sync", "#!/usr/bin/sh\nhand\n", 0o755)
        self.ctl(enabled=0)
        code, out, err = self.w.run("hook", "install")
        self.assertEqual(code, 1)
        self.assertIn("appglass adopt", err)
        self.assertFalse(os.path.exists(self.w.user(".config/matugen/config.toml")))
        self.assertEqual(self.calls(), [])
        out = self.run_ok("adopt")
        self.assertIn("owner hook", out)
        self.run_ok("hook", "install")
        self.assertIn("bin/appglass-sync", self.w.sb.read(script))
        open(self.log, "w").close()
        self.run_ok("hook", "remove")
        self.assertEqual(self.calls(), ["--user daemon-reload"])   # was enabled: kept
        self.assertEqual(self.w.sb.read(script), "#!/usr/bin/sh\nhand\n")
        self.assertEqual(self.w.mode(script), 0o755)
        for n, p in hand.items():
            with open(p, "rb") as f:
                self.assertEqual(f.read(), repo_unit(n))


class SyncScript(unittest.TestCase):
    """bin/appglass-sync run the way the service runs it."""

    def setUp(self):
        self.w = ShimWorld()
        self.run_dir = tempfile.mkdtemp(prefix="appglass-run-")
        self.host = self.w.user(".config/discord/app-1.0.170/resources")
        os.makedirs(self.host)
        open(os.path.join(self.host, "app.asar"), "w").close()
        self.inst_log = os.path.join(self.run_dir, "installer")
        self.w.hand(".local/share/appglass/VencordInstallerCli-linux",
                    '#!/bin/sh\necho "$*" >> "%s"\ntouch "$3/resources/_app.asar"\n'
                    % self.inst_log, 0o755)
        self.w.hand(".config/Vencord/settings/settings.json", "{}\n")

    def tearDown(self):
        self.w.cleanup()
        shutil.rmtree(self.run_dir, ignore_errors=True)

    def sync(self):
        env = dict(self.w.sb.env, XDG_RUNTIME_DIR=self.run_dir,
                   APPGLASS_SYNC_SETTLE="0", APPGLASS_SYNC_WAIT="0")
        r = subprocess.run([os.path.join(REPO, "bin", "appglass-sync")], env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout + r.stderr

    def niri(self):
        return self.w.sb.read(os.path.join(self.w.sb.config, "niri", "appglass.kdl"))

    def installs(self):
        try:
            with open(self.inst_log) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def test_reinjects_only_with_vencord_applied(self):
        self.sync()
        self.assertEqual(self.installs(), [])
        self.w.run("set", "apps.vencord.enabled", "true")
        code, out, err = self.w.run("apply", "--only", "vencord")
        self.assertEqual(code, 0, err)
        self.assertIn("Vencord is not in", err)
        self.assertNotIn("discord", self.niri())
        out = self.sync()
        self.assertIn("Vencord injected", out)
        self.assertEqual(self.installs(), ["-install -location " + os.path.dirname(self.host)])
        self.assertIn("discord", self.niri())    # apply --from-hook after the inject
        self.sync()                               # injected: nothing to do
        self.assertEqual(len(self.installs()), 1)

    def test_colours_rerender_the_theme(self):
        self.w.run("set", "apps.vencord.enabled", "true")
        self.w.run("apply", "--only", "vencord")
        theme = self.w.user(".config/Vencord/themes/appglass-discord.css")
        css = self.w.sb.read(theme)
        p = os.path.join(self.w.sb.cache, "dms", "dms-colors.json")
        with open(p) as f:
            text = f.read()
        old = self.w.sb.json(p)["colors"][self.w.sb.json(p)["mode"]]["primary"]
        self.assertIn(old, css)
        with open(p, "w") as f:
            f.write(text.replace(old, "#123456"))
        self.sync()
        new = self.w.sb.read(theme)
        self.assertIn("#123456", new)
        self.assertNotIn(old, new)


if __name__ == "__main__":
    unittest.main()
