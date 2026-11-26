"""shims.appglass_cmd under HOME: only the $HOME prefix may expand, a $ in
the rest of the repo path stays literal (the outside-HOME form already)."""

import os
import subprocess
import unittest

from fixtures.sandbox import fixture  # noqa: F401  (sets sys.path)
from appglass import core, shims, verify


class Dollar(unittest.TestCase):
    def test_dollar_in_the_repo_path_under_home(self):
        home = "/h"
        p = home + "/src/app$glass `x` \"q\" \\b/bin/appglass"
        cmd = shims.appglass_cmd(core.Env({"HOME": home}), p)
        self.assertTrue(cmd.startswith("$HOME/"), cmd)
        out = subprocess.run(["sh", "-c", 'printf %s "' + cmd + '"'], capture_output=True, text=True,
                             env={"HOME": home, "PATH": os.environ.get("PATH", "")}).stdout
        self.assertEqual(out, p)

    def test_rehome_keeps_the_repo_escaped(self):
        # the throwaway HOME holds no repo: the $HOME form becomes the absolute one, still escaped
        class E:
            home = "/h"
            config_home, data_home = "/h/.config", "/h/.local/share"
            state_home, cache_home = "/h/.local/state", "/h/.cache"
        old = shims.REPO
        shims.REPO = "/h/src/app$glass"
        self.addCleanup(setattr, shims, "REPO", old)
        text = 'exec "%s" levels' % shims.appglass_cmd(E, shims.REPO + "/bin/appglass")
        self.assertEqual(verify._rehome(E, "/x/t", text), 'exec "/h/src/app\\$glass/bin/appglass" levels')


if __name__ == "__main__":
    unittest.main()
