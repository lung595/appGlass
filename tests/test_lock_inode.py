"""The appglass lock outlives the state dir it sits in: a run that takes
the dir (and its .lock) out does it under the lock, and a run that waited
on the old .lock takes the lock again on the live one."""

import os
import threading
import time
import unittest

from fixtures.sandbox import Sandbox
from appglass import core


class LockInode(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.env = core.Env(self.sb.env)
        self.path = os.path.join(self.env.state_dir, ".lock")

    def tearDown(self):
        self.sb.cleanup()

    def test_a_waiter_holds_the_live_lock_file(self):
        lockf, created = core._lock(self.env)
        self.assertTrue(created)        # a fresh state dir: the unlock takes it out
        got = []
        t = threading.Thread(target=lambda: got.append(core._lock(self.env)))
        t.start()
        time.sleep(0.3)                 # B waits on the flock
        core._unlock(self.env, lockf, created, None)
        t.join(5)
        self.assertTrue(got, "the waiter never got the lock")
        f, _ = got[0]
        try:
            # B's lock is the .lock a third run would open: one holder only
            self.assertEqual(os.fstat(f.fileno()).st_ino, os.stat(self.path).st_ino)
        finally:
            f.close()


if __name__ == "__main__":
    unittest.main()
