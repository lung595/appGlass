"""The sync reloads Herdr's theme from where appglass wrote the layout: a moved
XDG_CONFIG_HOME, or an absolute HERDR_APP_HOME, not a fixed ~/.config."""

import os
import shutil
import subprocess
import tempfile
import unittest

from fixtures.sandbox import REPO
from fixtures.shimworld import ShimWorld


class HerdrReloadHome(unittest.TestCase):
    def setUp(self):
        self.w = ShimWorld()
        self.run_dir = tempfile.mkdtemp(prefix="appglass-run-")

    def tearDown(self):
        self.w.cleanup()
        shutil.rmtree(self.run_dir, ignore_errors=True)

    def reloads(self, home, **extra):
        """One sync after an apply that wrote Herdr's layout under home, with
        stub pgrep (herdr-app runs) and herdr-app; its reload calls."""
        layout = os.path.join(home, "layouts", "appglass.json")
        os.makedirs(os.path.dirname(layout))
        with open(layout, "w") as f:
            f.write('{"theme": "appglass"}\n')
        bindir = os.path.join(self.run_dir, "bin")
        os.makedirs(bindir)
        hlog = os.path.join(self.run_dir, "herdr.log")
        for name, body in (
                ("pgrep", '[ "$2" = herdr-app ]\n'),
                ("herdr-app", 'echo "$*" >> "%s"\n' % hlog),
                ("appglass", 'echo "%s"\n' % layout)):
            with open(os.path.join(bindir, name), "w") as f:
                f.write("#!/bin/sh\n" + body)
            os.chmod(os.path.join(bindir, name), 0o755)
        env = dict(self.w.sb.env, XDG_RUNTIME_DIR=self.run_dir, APPGLASS_SYNC_SETTLE="0",
                   APPGLASS_BIN=os.path.join(bindir, "appglass"),
                   APPGLASS_RPMDB=os.path.join(self.run_dir, "no-rpmdb"),
                   PATH=bindir + os.pathsep + os.environ.get("PATH", "/usr/bin"), **extra)
        del env["APPGLASS_SANDBOX"]      # the reload runs only outside a sandbox
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        r = subprocess.run([os.path.join(REPO, "bin", "appglass-sync")], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        if not os.path.exists(hlog):
            return []
        with open(hlog) as f:
            return f.read().splitlines()

    def test_a_moved_config_home_still_reloads(self):
        cfg = os.path.join(self.w.sb.home, "cfg")
        self.assertEqual(self.reloads(os.path.join(cfg, "herdr-app"), XDG_CONFIG_HOME=cfg),
                         ["do app.theme --name appglass"])

    def test_herdr_app_home_reloads(self):
        home = os.path.join(self.w.sb.home, "hh")
        self.assertEqual(self.reloads(home, HERDR_APP_HOME=home),
                         ["do app.theme --name appglass"])

    def test_a_relative_herdr_app_home_is_ignored(self):
        # app_home ignores a relative HERDR_APP_HOME: the default dir it is
        self.assertEqual(self.reloads(os.path.join(self.w.sb.config, "herdr-app"),
                                      HERDR_APP_HOME="hh"),
                         ["do app.theme --name appglass"])


if __name__ == "__main__":
    unittest.main()
