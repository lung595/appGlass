import os
import tempfile
import unittest

from fixtures.sandbox import Sandbox  # noqa: F401 (puts appglass on sys.path)
from appglass import detect


class ElectronFusesEof(unittest.TestCase):
    def test_sentinel_at_eof_is_unknown_not_crash(self):
        # A truncated binary ending on the sentinel must not abort the scan.
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "app")
            with open(p, "wb") as f:
                f.write(b"\x7fELFxxxx" + detect.FUSE_SENTINEL + b"\x01")
            self.assertIsNone(detect.electron_fuses(p))


if __name__ == "__main__":
    unittest.main()
