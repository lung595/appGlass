"""appglass status scans the desktop files once per run: detected() starts
from the scan engine.records() already made, and gives the same records as
a scan of its own."""

import io
import json
import os
import unittest
from unittest import mock

from fixtures.sandbox import Sandbox, fixture
from appglass import core, engine


class StatusOneScan(unittest.TestCase):
    def setUp(self):
        sb = self.sb = Sandbox()
        sb.seed_dms()
        sb.seed_niri()
        for n in ("vlc.desktop", "org.jeffvli.feishin.desktop"):
            sb.seed(os.path.join("launchers", n), os.path.join("applications", n),
                    base=sb.data)

    def tearDown(self):
        self.sb.cleanup()

    def app(self):
        return core.App(self.sb.env, out=io.StringIO(), err=io.StringIO())

    def test_status_scans_once(self):
        real = engine.scan
        with mock.patch.object(engine, "scan", side_effect=real) as scan:
            code, out, err = self.sb.run("status", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(scan.call_count, 1)

    def test_same_records_as_a_scan_of_its_own(self):
        fresh = core.detected(self.app())
        app = self.app()
        engine.records(app)
        self.assertEqual(json.dumps(core.detected(app), sort_keys=True),
                         json.dumps(fresh, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
