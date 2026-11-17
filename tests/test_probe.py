import os
from unittest.mock import patch
from herdworks import hc
from herdworks.probe import probe, progress_time
from herdworks.runs import append_event, git
from tests.support import RunCase


class ProbeTests(RunCase):
    @patch("herdworks.hc.call")
    def test_missing_session_does_not_hide_core_failure(self, call):
        call.side_effect = hc.HCError(3, "not found")
        self.assertEqual(hc.get("gone")["state"], "missing")
        call.side_effect = hc.HCError(1, "core unavailable")
        with self.assertRaisesRegex(hc.HCError, "core unavailable"):
            hc.get("gone")

    @patch("herdworks.hc.get", return_value={"state": "live", "status": "idle", "turn": 0})
    def test_newest_commit_working_copy_and_run_file(self, get):
        git(self.repo, "checkout", "-b", "hw/HE-1")
        folder = self.path / "build-1"
        folder.mkdir()
        wt = folder / "wt"
        wt.mkdir()
        changed = wt / "hello.py"
        changed.write_text("changed")
        report = folder / "report.md"
        report.write_text("READY pending")
        event = {"event": "session", "name": "hw-unit-he-1-build-1", "address": "t2", "role": "build",
                 "folder": "build-1", "started_at": 100, "stuck_after_minutes": 60}
        append_event(self.path, event)
        self.commit(1000000000)
        os.utime(changed, (900000000, 900000000))
        os.utime(report, (900000000, 900000000))
        self.assertEqual(progress_time(self.path, event), 1000000000)
        os.utime(changed, (1000000060, 1000000060))
        self.assertEqual(progress_time(self.path, event), 1000000060)
        os.utime(report, (1000000120, 1000000120))
        self.assertEqual(progress_time(self.path, event), 1000000120)
        fact = probe(self.path, clock=lambda: 1000000240)[0]
        self.assertEqual(fact["quiet_minutes"], 2)
        self.assertEqual(fact["turn"], 0)
        self.assertEqual(fact["artifact"], "READY pending")
