"""appglass hook install: the sync units, ~/.local/bin/appglass-sync, systemctl,
and bin/appglass-sync itself (Vencord re-inject, apply --from-hook)."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from fixtures.sandbox import REPO
from fixtures.shimworld import ShimWorld

UNITS = ("appglass-sync.path", "appglass-sync.service", "appglass-vibrancy.service",
         "appglass-discord.path", "appglass-discord.service", "appglass-sync.timer",
         "appglass-verify.service")
HAND_UNITS = UNITS[:2]
ENABLE = ["--user daemon-reload", "--user enable --now appglass-sync.path",
          "--user enable --now appglass-sync.timer"]
# the first follow with no family applied: the family units off (an older
# install had them on)
FOLLOW_OFF = ["--user disable --now appglass-vibrancy.service",
              "--user disable --now appglass-discord.path"]
DISABLE = ["--user disable --now appglass-sync.path",
           "--user disable --now appglass-discord.path",
           "--user disable --now appglass-sync.timer",
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

    def run_ok(self, *argv, **kw):
        code, out, err = self.w.run(*argv, **kw)
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
                                        "--user is-enabled --quiet appglass-sync.timer",
                                        "--user is-enabled --quiet appglass-vibrancy.service"]
                         + ENABLE + FOLLOW_OFF)
        self.run_ok("hook", "install")           # again: no new is-enabled, no follow call
        self.assertEqual(self.calls()[9:], ENABLE)
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
                                        "--user disable --now appglass-sync.timer",
                                        "--user disable --now appglass-vibrancy.service",
                                        "--user daemon-reload"])
        self.assertEqual(self.w.sb.read(script), "#!/usr/bin/sh\nhand\n")
        self.assertEqual(self.w.mode(script), 0o755)
        for n, p in hand.items():
            with open(p, "rb") as f:
                self.assertEqual(f.read(), repo_unit(n))


    def test_family_units_follow_the_family(self):
        """appglass-vibrancy.service and appglass-discord.path run only while
        their family is applied; the daemon is reloaded when a run changed
        what it reads, never on a run that changed nothing."""
        self.w.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.w.sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        self.before = self.w.sb.tree_hash()
        self.ctl(enabled=1)
        self.run_ok("hook", "install")
        self.assertEqual(self.calls()[-2:], FOLLOW_OFF)
        vib = "appglass-vibrancy.service"
        steps = [(("apply", "--only", "alacritty"), ["--user enable --now " + vib]),
                 (("apply", "--only", "alacritty"), []),
                 (("apply", "--from-hook"), []),
                 (("set", "inactive.factor", "0.85"), ["--user reload " + vib]),
                 (("hook", "install"), ENABLE + ["--user restart " + vib]),
                 (("remove", "--only", "alacritty"), ["--user disable --now " + vib])]
        for argv, want in steps:
            open(self.log, "w").close()
            self.run_ok(*argv, assume="alacritty")
            self.assertEqual(self.calls(), want, argv)
        self.assertEqual(self.w.state()["owners"]["hook"]["follow"],
                         {vib: False, "appglass-discord.path": False})
        # the plugin's switch: on, then off
        open(self.log, "w").close()
        self.run_ok("apply", "--only", "alacritty", assume="alacritty")
        code, out, err = self.w.run("get")
        p = os.path.join(self.tmp, "plugin.json")
        obj = json.loads(out)
        obj.setdefault("apps", {})["alacritty"] = {"enabled": False}
        with open(p, "w") as f:
            json.dump(obj, f)
        self.run_ok("sync", "--settings-file", p, assume="alacritty")
        self.assertEqual(self.calls(), ["--user enable --now " + vib, "--user disable --now " + vib])
        open(self.log, "w").close()
        self.run_ok("hook", "remove")
        self.assertEqual(self.calls(), DISABLE + ["--user daemon-reload"])

    def test_a_sync_brings_old_units_up_to_date(self):
        """A plugin update runs no hook install: the sync writes the repo's
        unit again, reloads systemd and restarts the running daemon."""
        self.w.sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
        self.w.sb.seed("alacritty/dank-theme.toml", "alacritty/dank-theme.toml")
        self.before = self.w.sb.tree_hash()
        self.ctl(enabled=1)
        self.run_ok("hook", "install")
        self.run_ok("apply", "--only", "alacritty", assume="alacritty")
        vib = "appglass-vibrancy.service"
        unit = os.path.join(self.w.sb.home, ".config/systemd/user", vib)
        with open(unit, "ab") as f:
            f.write(b"# an older release\n")
        code, out, err = self.w.run("get")
        p = os.path.join(self.tmp, "plugin.json")
        with open(p, "w") as f:
            f.write(out)
        open(self.log, "w").close()
        self.run_ok("sync", "--settings-file", p, assume="alacritty")
        with open(unit, "rb") as f:
            self.assertEqual(f.read(), repo_unit(vib))
        self.assertEqual(self.calls(), ["--user daemon-reload", "--user restart " + vib])
        open(self.log, "w").close()
        self.run_ok("sync", "--settings-file", p, assume="alacritty")
        self.assertEqual(self.calls(), [])

    def test_a_unit_enabled_before_install_is_enabled_again(self):
        """A hand-made vibrancy unit, enabled, adopted: follow turns it off
        (no Alacritty glass), hook remove turns it back on."""
        self.w.hand(".config/systemd/user/appglass-vibrancy.service",
                    repo_unit("appglass-vibrancy.service"))
        self.ctl_units(["appglass-vibrancy.service"])
        self.run_ok("adopt")
        self.assertIn("--user disable --now appglass-vibrancy.service", self.calls())
        open(self.log, "w").close()
        self.run_ok("hook", "remove")
        calls = self.calls()
        self.assertNotIn("--user disable --now appglass-vibrancy.service", calls)
        self.assertEqual(calls[-2:], ["--user daemon-reload",
                                      "--user enable --now appglass-vibrancy.service"])

    def ctl_units(self, enabled):
        """A systemctl whose is-enabled says yes for the units in enabled."""
        p = os.path.join(self.tmp, "systemctl")
        cases = "".join('*"is-enabled --quiet %s"*) exit 0 ;; ' % u for u in enabled)
        with open(p, "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "%s"\ncase "$*" in %s*is-enabled*) exit 1 ;; '
                    'esac\nexit 0\n' % (self.log, cases))
        os.chmod(p, 0o755)
        self.w.sb.env["APPGLASS_SYSTEMCTL"] = p

    def test_install_says_which_units_did_not_enable(self):
        # w2 r2: with no user bus every enable fails; "enabled" was printed anyway
        p = os.path.join(self.tmp, "systemctl")
        with open(p, "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "%s"\ncase "$*" in '
                    '*"enable --now appglass-sync.path"*|*is-enabled*|*daemon-reload*) exit 0 ;; '
                    '*enable*) echo "Failed to connect to bus" >&2; exit 1 ;; esac\nexit 0\n'
                    % self.log)
        os.chmod(p, 0o755)
        self.w.sb.env["APPGLASS_SYSTEMCTL"] = p
        out = self.run_ok("hook", "install")
        line = [l for l in out.splitlines() if "enabled" in l and "failed" not in l]
        self.assertIn("hook: appglass-sync.path enabled", out)
        self.assertRegex(out, r"hook: units written, not enabled: appglass-sync\.timer "
                              r"\(systemctl failed")
        self.assertFalse([l for l in line if "appglass-sync.timer" in l and "not enabled" not in l],
                         line)

    def test_adopt_records_what_was_enabled(self):
        for n in HAND_UNITS:
            self.w.hand(".config/systemd/user/" + n, repo_unit(n))
        self.w.hand(".local/bin/appglass-sync", "#!/usr/bin/sh\nhand\n", 0o755)
        self.ctl_units(["appglass-sync.path"])
        self.run_ok("adopt")
        self.assertEqual(self.w.state()["owners"]["hook"]["systemd"], {
            "was_enabled": True, "discord_was_enabled": False,
            "timer_was_enabled": False, "vibrancy_was_enabled": False})
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
        self.assertIn("enable --now appglass-sync.timer", out)
        self.assertIn("appglass-vibrancy.service, appglass-discord.path while their family "
                      "is applied", out)
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
        # the real session's check (no sandbox: it refuses before appglass runs)
        os.chmod(self.run_dir, 0o777)
        env = dict(self.w.sb.env, XDG_RUNTIME_DIR=self.run_dir, APPGLASS_SYNC_SETTLE="0")
        del env["APPGLASS_SANDBOX"]
        r = subprocess.run([os.path.join(REPO, "bin", "appglass-sync")], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing: no private runtime dir", r.stdout)
        self.assertEqual(os.listdir(self.run_dir), [])

    def test_a_sandboxed_sync_locks_in_its_sandbox(self):
        # never in the runtime dir: a sandbox sync must not wait on the real one
        self.sync()
        self.assertEqual(os.listdir(self.run_dir), [])
        self.assertTrue(os.path.isfile(os.path.join(self.w.sb.root, "appglass-sync.lock")))

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

    def test_a_stop_during_the_theme_flip_puts_the_theme_back(self):
        """A SIGTERM to the unit (a logout) while the GTK theme is flipped
        to '' (the sleep between the two sets): the user's theme goes back."""
        if shutil.which("setsid") is None:
            self.skipTest("no setsid")
        import signal
        import time
        bindir = os.path.join(self.run_dir, "bin")
        os.makedirs(bindir)
        glog = os.path.join(self.run_dir, "gsettings.log")
        mark = os.path.join(self.run_dir, "flipped")
        real_sleep = shutil.which("sleep")
        for name, body in (
                ("gsettings", "[ \"$1\" = get ] && { echo \"'Adwaita'\"; exit 0; }\n"
                              'echo "$*" >> "%s"\n' % glog),
                ("dconf", '[ "$1" = read ] && echo "\'Adwaita\'"\n'),   # set by the user
                # the sleep between the two sets: long, and it says it started
                ("sleep", '[ "$1" = 0.3 ] && { touch "%s"; exec %s 30; }\nexec %s "$@"\n'
                          % (mark, real_sleep, real_sleep)),
                ("appglass", 'echo "%s/gtk-4.0/gtk.css"\n' % self.w.sb.config)):
            with open(os.path.join(bindir, name), "w") as f:
                f.write("#!/bin/sh\n" + body)
            os.chmod(os.path.join(bindir, name), 0o755)
        env = dict(self.w.sb.env, XDG_RUNTIME_DIR=self.run_dir, APPGLASS_SYNC_SETTLE="0",
                   APPGLASS_BIN=os.path.join(bindir, "appglass"),
                   APPGLASS_RPMDB=os.path.join(self.run_dir, "no-rpmdb"),
                   PATH=bindir + os.pathsep + os.environ.get("PATH", "/usr/bin"))
        del env["APPGLASS_SANDBOX"]      # the flip runs only outside a sandbox
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        p = subprocess.Popen([os.path.join(REPO, "bin", "appglass-sync")], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True)
        try:
            for _ in range(200):
                if os.path.exists(mark):
                    break
                time.sleep(0.05)
            self.assertTrue(os.path.exists(mark), "the flip never started")
            os.killpg(p.pid, signal.SIGTERM)     # what systemd sends the cgroup
            p.wait(timeout=20)
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            p.stdout.close()
            p.stderr.close()
        with open(glog) as f:
            sets = f.read().splitlines()
        self.assertEqual(sets[-1], "set org.gnome.desktop.interface gtk-theme 'Adwaita'",
                         sets)
        self.assertNotEqual(p.returncode, 0)

    def flip(self, dconf_value):
        """One full GTK theme flip with stub gsettings and dconf; the
        gsettings calls after the get, in order."""
        bindir = os.path.join(self.run_dir, "bin")
        os.makedirs(bindir)
        glog = os.path.join(self.run_dir, "gsettings.log")
        real_sleep = shutil.which("sleep")
        for name, body in (
                ("gsettings", "[ \"$1\" = get ] && { echo \"'Adwaita'\"; exit 0; }\n"
                              'echo "$*" >> "%s"\n' % glog),
                ("dconf", '[ "$1" = read ] && printf "%%s" "%s"\n' % dconf_value),
                ("sleep", 'exec %s 0\n' % real_sleep),
                ("appglass", 'echo "%s/gtk-4.0/gtk.css"\n' % self.w.sb.config)):
            with open(os.path.join(bindir, name), "w") as f:
                f.write("#!/bin/sh\n" + body)
            os.chmod(os.path.join(bindir, name), 0o755)
        env = dict(self.w.sb.env, XDG_RUNTIME_DIR=self.run_dir, APPGLASS_SYNC_SETTLE="0",
                   APPGLASS_BIN=os.path.join(bindir, "appglass"),
                   APPGLASS_RPMDB=os.path.join(self.run_dir, "no-rpmdb"),
                   PATH=bindir + os.pathsep + os.environ.get("PATH", "/usr/bin"))
        del env["APPGLASS_SANDBOX"]      # the flip runs only outside a sandbox
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        r = subprocess.run([os.path.join(REPO, "bin", "appglass-sync")], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(glog) as f:
            return f.read().splitlines()

    def test_the_flip_leaves_a_default_theme_at_its_default(self):
        """A gtk-theme key the user never set (no dconf value) is reset after
        the flip, not pinned to the theme name it read."""
        self.assertEqual(self.flip(""), [
            "set org.gnome.desktop.interface gtk-theme ''",
            "reset org.gnome.desktop.interface gtk-theme"])

    def test_the_flip_puts_a_set_theme_back(self):
        self.assertEqual(self.flip("'Adwaita'"), [
            "set org.gnome.desktop.interface gtk-theme ''",
            "set org.gnome.desktop.interface gtk-theme 'Adwaita'"])

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



class GlassOffOn(unittest.TestCase):
    """The plugin's glass switch off then on (sync enabled false, then true)
    brings back what `apply --all --adopt` had: the adopted hand files are
    adopted again (same bytes as at off), the hook stays."""

    def setUp(self):
        import json
        from fixtures.sandbox import fixture
        self.json = json
        self.w = w = ShimWorld(bins=("vlc",))
        self.tmp = tempfile.mkdtemp(prefix="appglass-ctl-")
        ctl = os.path.join(self.tmp, "systemctl")
        with open(ctl, "w") as f:
            f.write(CTL % {"log": os.path.join(self.tmp, "calls"), "enabled": 1})
        os.chmod(ctl, 0o755)
        w.sb.env["APPGLASS_SYSTEMCTL"] = ctl
        with open(fixture("launchers/vlc.desktop")) as f:
            system = f.read()
        w.launcher("vlc.desktop", system)
        self.so = w.hand(".local/lib/appglass/qt6/styles/libappglass.so",
                         b"\x7fELF hand-built", 0o755)
        self.desk = w.hand(".local/share/applications/vlc.desktop", system.replace(
            "Exec=/usr/bin/vlc", "Exec=env QT_STYLE_OVERRIDE=appglass /usr/bin/vlc"))
        for n in HAND_UNITS:
            w.hand(".config/systemd/user/" + n, repo_unit(n))
        w.hand(".local/bin/appglass-sync", "#!/usr/bin/sh\nhand\n", 0o755)
        self.hand = {p: self.read(p) for p in (self.so, self.desk)}

    def tearDown(self):
        self.w.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, p):
        with open(p, "rb") as f:
            return f.read()

    def run_ok(self, *argv, **kw):
        code, out, err = self.w.run(*argv, **kw)
        self.assertEqual(code, 0, err)
        return out + err

    def sync(self, settings):
        f = os.path.join(self.tmp, "plugin-settings.json")
        with open(f, "w") as fh:
            fh.write(self.json.dumps(settings))
        return self.run_ok("sync", "--settings-file", f)

    def conflicts(self):
        doc = self.json.loads(self.run_ok("status", "--json"))
        return [h["path"] for h in doc["hand_files"] if h["status"] == "conflict"]

    def test_off_then_on_adopts_again(self):
        self.run_ok("apply", "--all", "--adopt")
        before = sorted(self.w.state()["owners"])
        self.assertIn("qtstyle", before)
        self.assertIn("hook", before)
        on = self.json.loads(self.run_ok("get"))
        self.sync(dict(on, enabled=False))
        # off: the hand files are the user's again, byte-identical
        for p, data in self.hand.items():
            self.assertEqual(self.read(p), data, p)
        self.assertNotIn("qtstyle", self.w.state()["owners"])
        off_owners = sorted(self.w.state()["owners"])
        f = os.path.join(self.tmp, "plugin-settings.json")
        with open(f, "w") as fh:
            fh.write(self.json.dumps(on))
        dry = self.run_ok("sync", "--dry-run", "--settings-file", f)
        self.assertIn("would adopt again", dry)
        self.assertEqual(sorted(self.w.state()["owners"]), off_owners)
        out = self.sync(on)
        self.assertNotIn("qtstyle: skipped", out)
        # the sync saved the plugin's settings.json (owner settings) too
        self.assertEqual(sorted(self.w.state()["owners"]), sorted(set(before) | {"settings"}))
        self.assertNotIn("parked", self.w.state())
        self.assertEqual(self.conflicts(), [])
        # an uninstall still gives the user's bytes back
        self.run_ok("remove")
        for p, data in self.hand.items():
            self.assertEqual(self.read(p), data, p)
        self.assertFalse(os.path.exists(os.path.join(self.w.sb.state, "appglass")))

    def test_a_remove_that_stops_keeps_the_parked_files(self):
        # Uninstall's `appglass remove` failing half way: the plugin sets
        # the glass up again from its settings, which adopts the parked hand
        # files again only while state.json still names them
        from unittest import mock
        from appglass import core
        self.run_ok("apply", "--all", "--adopt")
        on = self.json.loads(self.run_ok("get"))
        self.sync(dict(on, enabled=False))
        parked = dict(self.w.state()["parked"])
        real = core.App.remove_owner

        def stops(app, name):
            if name == "hook":
                raise PermissionError(13, "Permission denied", "unit")
            return real(app, name)
        with mock.patch.object(core.App, "remove_owner", stops):
            code, out, err = self.w.run("remove")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.w.state().get("parked"), parked)
        out = self.sync(on)
        self.assertIn("adopted again", out)

    def test_on_skips_a_hand_file_changed_while_off(self):
        self.run_ok("apply", "--all", "--adopt")
        on = self.json.loads(self.run_ok("get"))
        self.sync(dict(on, enabled=False))
        with open(self.desk, "a") as f:
            f.write("# mine\n")
        out = self.sync(on)
        self.assertIn("changed while glass was off", out)
        # per file: the unchanged .so adopted again, the changed launcher
        # the user's (qtstyle skips it as a conflict)
        self.assertEqual(list(self.w.state()["owners"]["qtstyle"]["files"]), [self.so])
        self.assertIn("# mine", self.read(self.desk).decode())
        self.run_ok("remove")
        self.assertEqual(self.read(self.so), self.hand[self.so])
        self.assertIn("# mine", self.read(self.desk).decode())
        self.assertFalse(os.path.exists(os.path.join(self.w.sb.state, "appglass")))

    def test_apply_all_while_off_leaves_parked_files(self):
        self.run_ok("apply", "--all", "--adopt")
        on = self.json.loads(self.run_ok("get"))
        self.sync(dict(on, enabled=False))
        parked = dict(self.w.state()["parked"])
        out = self.run_ok("apply", "--all")
        self.assertIn("glass is off", out)
        self.assertNotIn("adopted again", out)
        self.assertEqual(self.w.state()["parked"], parked)
        self.assertNotIn("qtstyle", self.w.state()["owners"])
        for p, data in self.hand.items():
            self.assertEqual(self.read(p), data, p)

    def test_on_counts_a_file_adopted_while_off_as_unchanged(self):
        self.run_ok("apply", "--all", "--adopt")
        on = self.json.loads(self.run_ok("get"))
        self.sync(dict(on, enabled=False))
        self.run_ok("adopt", self.desk)
        out = self.sync(on)
        self.assertNotIn("changed while glass was off", out)
        files = self.w.state()["owners"]["qtstyle"]["files"]
        self.assertIn(self.desk, files)
        self.assertIn(self.so, files)
        self.assertNotIn("parked", self.w.state())
        self.run_ok("remove")
        for p, data in self.hand.items():
            self.assertEqual(self.read(p), data, p)

    def test_on_warns_only_for_the_file_that_changed(self):
        self.run_ok("apply", "--all", "--adopt")
        on = self.json.loads(self.run_ok("get"))
        self.sync(dict(on, enabled=False))
        with open(self.desk, "a") as f:
            f.write("# mine\n")
        out = self.sync(on)
        self.assertIn("vlc.desktop changed while glass was off", out)
        self.assertNotIn("libappglass.so changed", out)
        self.assertEqual(self.read(self.so), self.hand[self.so])

    def test_parked_files_are_not_conflicts_while_off(self):
        self.run_ok("apply", "--all", "--adopt")
        on = self.json.loads(self.run_ok("get"))
        self.assertEqual(self.conflicts(), [])
        self.sync(dict(on, enabled=False))
        # glass on adopts them again by itself: not "in the way"
        self.assertEqual(self.conflicts(), [])
        doc = self.json.loads(self.run_ok("status", "--json"))
        st = {h["path"]: h["status"] for h in doc["hand_files"]}
        for p in (self.so, self.desk):
            self.assertEqual(st["~" + p[len(self.w.sb.home):]], "parked", p)
        self.assertEqual({a["key"]: a["conflicts"] for a in doc["apps"] if a["conflicts"]}, {})
        # nor does a bare adopt take them while off; glass on does
        out = self.run_ok("adopt")
        self.assertNotIn("qtstyle", self.w.state()["owners"])
        out = self.sync(on)
        self.assertIn("adopted again", out)
        self.assertEqual(self.conflicts(), [])

    def test_a_parked_file_changed_while_off_is_a_conflict(self):
        # glass on would leave it as is (_adopt_parked): it is in the way
        self.run_ok("apply", "--all", "--adopt")
        on = self.json.loads(self.run_ok("get"))
        self.sync(dict(on, enabled=False))
        with open(self.desk, "a") as f:
            f.write("# mine\n")
        doc = self.json.loads(self.run_ok("status", "--json"))
        st = {h["path"]: h["status"] for h in doc["hand_files"]}
        tilde = lambda p: "~" + p[len(self.w.sb.home):]
        self.assertEqual(st[tilde(self.desk)], "conflict")
        # its unchanged sibling is still parked: glass on adopts each file
        # that kept its bytes (_adopt_parked, per file), the changed one
        # stays the user's
        self.assertEqual(st[tilde(self.so)], "parked")
        self.assertIn(tilde(self.desk), [c for a in doc["apps"] for c in a["conflicts"]])
        self.assertNotIn(tilde(self.so), [c for a in doc["apps"] for c in a["conflicts"]])
        # a link in its place is changed too
        os.remove(self.desk)
        os.symlink(self.so, self.desk)
        doc = self.json.loads(self.run_ok("status", "--json"))
        st = {h["path"]: h["status"] for h in doc["hand_files"]}
        self.assertEqual(st[tilde(self.desk)], "conflict")
        self.assertEqual(st[tilde(self.so)], "parked")
        # glass on does what status said: the sibling adopted again, the
        # changed one left as is (and still in the way)
        out = self.sync(on)
        self.assertIn("vlc.desktop changed while glass was off", out)
        doc = self.json.loads(self.run_ok("status", "--json"))
        st = {h["path"]: h["status"] for h in doc["hand_files"]}
        self.assertEqual(st[tilde(self.so)], "adopted")
        self.assertEqual(st[tilde(self.desk)], "conflict")
        self.assertTrue(os.path.islink(self.desk))

    def test_remove_only_while_off_drops_its_parked_files(self):
        self.run_ok("apply", "--all", "--adopt")
        on = self.json.loads(self.run_ok("get"))
        self.sync(dict(on, enabled=False))
        self.assertIn(self.desk, self.w.state()["parked"])
        self.run_ok("remove", "--only", "qtstyle")
        parked = self.w.state().get("parked", {})
        self.assertFalse([p for p, r in parked.items() if r["owner"] == "qtstyle"], parked)
        out = self.sync(on)
        self.assertNotIn("adopted again ~/.local/share/applications/vlc.desktop", out)
        self.assertNotIn("qtstyle", self.w.state()["owners"])
        for p, data in self.hand.items():
            self.assertEqual(self.read(p), data, p)


if __name__ == "__main__":
    unittest.main()
