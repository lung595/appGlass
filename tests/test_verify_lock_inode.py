"""verify's store write takes the appglass lock too: when the run it
waited on took the state dir (and its .lock) out, it does not write on a
lock that shuts out no one."""

import os
import threading
import time
import types
import unittest

from fixtures.sandbox import Sandbox
from appglass import core, verify


class VerifyLockInode(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.env = core.Env(self.sb.env)

    def tearDown(self):
        self.sb.cleanup()

    def test_a_waiter_does_not_write_after_the_dir_went(self):
        lockf, created = core._lock(self.env)
        self.assertTrue(created)        # a fresh state dir: the unlock takes it out
        app = types.SimpleNamespace(env=self.env)
        ran, got = [], []
        t = threading.Thread(target=lambda: got.append(
            verify._locked(app, lambda: ran.append(1) or "wrote")))
        t.start()
        time.sleep(0.3)                 # verify waits on the flock
        core._unlock(self.env, lockf, created, None)
        t.join(5)
        self.assertTrue(got, "the waiter never got the lock")
        self.assertEqual(ran, [])       # no state dir: nothing glass to record
        self.assertIsNone(got[0])

    def test_a_live_lock_runs_the_write(self):
        lockf, created = core._lock(self.env)
        lockf.close()
        app = types.SimpleNamespace(env=self.env)
        self.assertEqual(verify._locked(app, lambda: "wrote"), "wrote")


if __name__ == "__main__":
    unittest.main()
