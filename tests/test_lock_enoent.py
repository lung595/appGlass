"""A run that takes the state dir out can land between a waiter's check
(makedirs, isdir) and its open of .lock: the waiter starts over instead
of dying on ENOENT."""

import os
import shutil
import types
import unittest
from unittest import mock

from fixtures.sandbox import Sandbox
from appglass import core, verify


class LockEnoent(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.env = core.Env(self.sb.env)

    def tearDown(self):
        self.sb.cleanup()

    def test_core_lock_retries_when_the_dir_goes_before_open(self):
        real, d, calls = os.makedirs, self.env.state_dir, []

        def racing(p, *a, **kw):
            real(p, *a, **kw)
            if p == d and not calls:
                calls.append(1)
                shutil.rmtree(d)        # the other run's destroy()
        with mock.patch.object(core.os, "makedirs", racing):
            f, _ = core._lock(self.env)
        try:
            self.assertEqual(os.fstat(f.fileno()).st_ino,
                             os.stat(os.path.join(d, ".lock")).st_ino)
        finally:
            f.close()

    def test_verify_locked_returns_none_when_the_dir_goes_before_open(self):
        real, seen = os.path.isdir, []

        def racing(p):
            if not seen:                # the dir was there at the check
                seen.append(1)
                return True
            return real(p)
        app = types.SimpleNamespace(env=self.env)
        self.assertFalse(real(self.env.state_dir))
        with mock.patch.object(verify.os.path, "isdir", racing):
            self.assertIsNone(verify._locked(app, lambda: "wrote"))


if __name__ == "__main__":
    unittest.main()
