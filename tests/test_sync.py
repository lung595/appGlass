"""appglass hook install: the sync units, ~/.local/bin/appglass-sync, systemctl,
and bin/appglass-sync itself (Vencord re-inject, apply --from-hook)."""

import os
import shutil
import subprocess
import tempfile
import unittest

from fixtures.sandbox import REPO
from fixtures.shimworld import ShimWorld

UNITS = ("appglass-sync.path", "appglass-sync.service", "appglass-vibrancy.service",
         "appglass-discord.path", "appglass-discord.service")
HAND_UNITS = UNITS[:2]
ENABLE = ["--user daemon-reload", "--user enable --now appglass-sync.path",
          "--user enable --now appglass-discord.path",
          "--user enable appglass-vibrancy.service",
          "--user restart appglass-vibrancy.service"]
DISABLE = ["--user disable --now appglass-sync.path",
           "--user disable --now appglass-discord.path",
           "--user disable --now appglass-vibrancy.service"]
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
        vib = self.w.sb.read(self.w.user(".local/bin/appglass-vibrancy"))
        self.assertTrue(vib.rstrip().endswith('/bin/appglass" vibrancy "$@"'), vib)
        self.assertEqual(self.w.mode(self.w.user(".local/bin/appglass-vibrancy")), 0o755)
        self.run_ok("hook", "remove")
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_systemctl_enable_then_disable(self):
        self.ctl(enabled=1)
        self.run_ok("hook", "install")
        self.assertEqual(self.calls(), ["--user is-enabled --quiet appglass-sync.path",
                                        "--user is-enabled --quiet appglass-discord.path",
                                        "--user is-enabled --quiet appglass-vibrancy.service"]
                         + ENABLE)
        self.run_ok("hook", "install")           # again: no new is-enabled
        self.assertEqual(self.calls()[8:], ENABLE)
        open(self.log, "w").close()
        self.run_ok("remove")
        self.assertEqual(self.calls(), DISABLE + ["--user daemon-reload"])
        self.assertEqual(self.w.sb.tree_hash(), self.before)

    def test_hand_units_conflict_then_adopt(self):
        hand = {n: self.w.hand(".config/systemd/user/" + n, repo_unit(n)) for n in HAND_UNITS}
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
        # the hand path unit was enabled: kept; the units appglass created go
        self.assertEqual(self.calls(), ["--user disable --now appglass-discord.path",
                                        "--user disable --now appglass-vibrancy.service",
                                        "--user daemon-reload"])
        self.assertEqual(self.w.sb.read(script), "#!/usr/bin/sh\nhand\n")
        self.assertEqual(self.w.mode(script), 0o755)
        for n, p in hand.items():
            with open(p, "rb") as f:
                self.assertEqual(f.read(), repo_unit(n))


    def ctl_units(self, enabled):
        """A systemctl whose is-enabled says yes for the units in enabled."""
        p = os.path.join(self.tmp, "systemctl")
        cases = "".join('*"is-enabled --quiet %s"*) exit 0 ;; ' % u for u in enabled)
        with open(p, "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "%s"\ncase "$*" in %s*is-enabled*) exit 1 ;; '
                    'esac\nexit 0\n' % (self.log, cases))
        os.chmod(p, 0o755)
        self.w.sb.env["APPGLASS_SYSTEMCTL"] = p

    def test_adopt_records_what_was_enabled(self):
        for n in HAND_UNITS:
            self.w.hand(".config/systemd/user/" + n, repo_unit(n))
        self.w.hand(".local/bin/appglass-sync", "#!/usr/bin/sh\nhand\n", 0o755)
        self.ctl_units(["appglass-sync.path"])
        self.run_ok("adopt")
        self.assertEqual(self.w.state()["owners"]["hook"]["systemd"], {
            "was_enabled": True, "discord_was_enabled": False,
            "vibrancy_was_enabled": False})
        self.run_ok("hook", "install")
        open(self.log, "w").close()
        self.run_ok("hook", "remove")
        self.assertEqual(self.calls(), DISABLE[1:] + ["--user daemon-reload"])

    def test_remove_without_a_systemd_record(self):
        """An owner adopted before the is-enabled record: the units appglass
        created are still disabled, and systemd reloaded."""
        for n in HAND_UNITS:
            self.w.hand(".config/systemd/user/" + n, repo_unit(n))
        self.w.hand(".local/bin/appglass-sync", "#!/usr/bin/sh\nhand\n", 0o755)
        self.run_ok("adopt")
        self.run_ok("hook", "install")            # sandbox: no systemctl, no record
        self.assertNotIn("systemd", self.w.state()["owners"]["hook"])
        self.ctl(enabled=0)
        self.run_ok("hook", "remove")
        self.assertEqual(self.calls(), DISABLE[1:] + ["--user daemon-reload"])

    def test_install_dry_run_changes_nothing(self):
        self.ctl(enabled=1)
        out = self.run_ok("hook", "install", "--dry-run")
        self.assertEqual(self.w.sb.tree_hash(), self.before)
        self.assertEqual(self.calls(), [])
        for n in UNITS:
            self.assertIn("would create ~/.config/systemd/user/" + n, out)
        self.assertIn("would create ~/.config/matugen/config.toml", out)
        self.assertIn("enable --now appglass-discord.path", out)
        code, out, err = self.w.run("hook", "remove", "--dry-run")
        self.assertEqual(code, 1, err)
        self.assertIn("--dry-run goes with install", err)


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

    def sync(self, *args, **extra):
        env = dict(self.w.sb.env, XDG_RUNTIME_DIR=self.run_dir,
                   APPGLASS_SYNC_SETTLE="0", APPGLASS_SYNC_WAIT="0", **extra)
        r = subprocess.run([os.path.join(REPO, "bin", "appglass-sync")] + list(args),
                           env=env, capture_output=True, text=True, timeout=120)
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

    def test_refuses_a_shared_runtime_dir(self):
        os.chmod(self.run_dir, 0o777)
        env = dict(self.w.sb.env, XDG_RUNTIME_DIR=self.run_dir, APPGLASS_SYNC_SETTLE="0")
        r = subprocess.run([os.path.join(REPO, "bin", "appglass-sync")], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing: no private runtime dir", r.stdout)
        self.assertEqual(os.listdir(self.run_dir), [])

    def test_discord_writes_exit_at_once(self):
        """--discord (appglass-discord.service, ~/.config/discord changed): no
        lock, no apply, no output unless the newest host dir lacks Vencord."""
        state = os.path.join(self.w.sb.state, "appglass", "state.json")
        self.assertEqual(self.sync("--discord"), "")          # vencord not applied
        self.assertFalse(os.path.exists(state))
        self.assertEqual(os.listdir(self.run_dir), [])        # not even the lock
        self.w.run("set", "apps.vencord.enabled", "true")
        self.assertEqual(self.w.run("apply", "--only", "vencord")[0], 0)
        out = self.sync("--discord")                          # a new host: inject
        self.assertIn("Vencord injected", out)
        self.assertIn("discord", self.niri())
        before = self.w.sb.tree_hash()
        for _ in range(3):                                    # Discord's own writes
            self.assertEqual(self.sync("--discord"), "")
        self.assertEqual(self.w.sb.tree_hash(), before)
        self.assertEqual(len(self.installs()), 1)

    def test_gtk_nudged_only_when_its_css_changed(self):
        env = {"APPGLASS_ASSUME_INSTALLED": "gtk3"}
        self.assertEqual(self.w.run("apply", "--only", "gtk3", env=env)[0], 0)
        out = self.sync(**env)
        self.assertNotIn("GTK CSS changed", out)              # nothing new
        self.assertNotIn("herdr", out)
        self.w.sb.set_level(0.7)
        out = self.sync(**env)
        self.assertIn("GTK CSS changed", out)
        self.assertNotIn("GTK CSS changed", self.sync(**env))

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
