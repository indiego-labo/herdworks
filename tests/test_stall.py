import os
import json
from unittest.mock import patch
from herdworks.probe import probe, format_fact
from herdworks.runs import append_event, events
from herdworks.spawn import spawn, replace_session
from tests import test_rounds as rounds
from tests.support import RunCase


class StallTests(RunCase):
    @patch("herdworks.hc.get", return_value={"state": "live", "status": None})
    def test_fake_clock_stall_progress_waiting_and_artifact(self, get):
        folder = self.path / "verify-1"
        folder.mkdir()
        append_event(self.path, dict(event="session", name="hw-unit-he-1-verify-1", role="verify", address="t2",
                                    folder="verify-1", started_at=1000, stuck_after_minutes=20))
        self.assertTrue(probe(self.path, clock=lambda: 2261)[0]["stalled"])
        self.assertIn("STALLED", format_fact(probe(self.path, clock=lambda: 2261)[0]))
        progress = folder / "progress.txt"
        progress.write_text("working")
        os.utime(progress, (2201, 2201))
        self.assertFalse(probe(self.path, clock=lambda: 2261)[0]["stalled"])
        progress.unlink()
        (self.notes / "ask.md").write_text("Waiting for you")
        self.assertFalse(probe(self.path, clock=lambda: 2261)[0]["stalled"])
        os.utime(self.notes / 'ask.md', (2000, 2000))
        (self.project / 'inbox.jsonl').write_text(json.dumps(dict(number=2, text='Approved', at=2100)) + '\n')
        (self.notes / 'answers').mkdir()
        (self.notes / 'answers/2.md').write_text('Approved')
        self.assertTrue(probe(self.path, clock=lambda: 2261)[0]['stalled'])
        (self.notes / "ask.md").unlink()
        verdict = folder / "verdict.md"
        verdict.write_text("INCONCLUSIVE\nCause: external-prerequisite\nAsk: install hello-prereq")
        os.utime(verdict, (1000, 1000))
        fact = probe(self.path, clock=lambda: 2261)[0]
        self.assertFalse(fact["stalled"])
        self.assertIn("Cause: external-prerequisite", format_fact(fact))
        self.assertIn("Ask: install hello-prereq", format_fact(fact))


class ReplacementTests(rounds.BuildScenario):

    @patch("herdworks.hc.call", return_value={"text": "saved stalled screen"})
    def test_third_replacement_refused(self, call):
        spawn(self.path)
        self.ready()
        spawn(self.path, "verify")
        for number in (1, 2):
            spawn(self.path, "verify", replaces=events(self.path)[-1]["name"])
        before = events(self.path)
        with self.assertRaisesRegex(ValueError, "two replacements.*ask"):
            spawn(self.path, "verify", replaces=events(self.path)[-1]["name"])
        self.assertEqual(events(self.path), before)
        self.assertEqual(len([e for e in before if e.get("event") == "stalled"]), 2)
        self.assertFalse((self.path / "verify-4").exists())


class SavedScreenTests(RunCase):
    @patch("herdworks.spawn.time.time", return_value=2000000000)
    @patch("herdworks.hc.get", return_value={"state": "live", "status": {"state": "working"}})
    @patch("herdworks.hc.call")
    def test_saved_screen_has_context_and_preserves_text_or_explains_empty_screen(self, call, get, clock):
        for role, text in (("verify", "verifier started\n"), ("build", ""), ("evidence", " \n\t")):
            with self.subTest(role=role, text=text):
                folder = self.path / f"{role}-1"
                folder.mkdir()
                progress = folder / "progress.txt"
                progress.write_text("progress")
                os.utime(progress, (1999999910, 1999999910))
                event = dict(name=f"hw-unit-he-1-{role}-1", role=role, address="t2", folder=folder.name,
                             commit="a" * 40, step=f"{role}:test", started_at=1999999880,
                             stuck_after_minutes=1)
                call.return_value = {"text": text}
                replace_session(self.path, event)
                saved = (folder / "stalled-1.txt").read_text()
                for fact in (f"Session: {event['name']}\n", f"Role: {role}\n",
                             f"Commit: {'a' * 40}\n", f"Step: {role}:test\n",
                             "Started: 2033-05-18T03:31:20+00:00\n",
                             "Last progress: 2033-05-18T03:31:50+00:00\n",
                             "Captured: 2033-05-18T03:33:20+00:00\n",
                             "Quiet: 1.50 minutes; stuck-after: 1 minutes\n",
                             "Herdr core state: live\n", "Herdr core status: working\n"):
                    self.assertIn(fact, saved)
                if text.strip():
                    self.assertTrue(saved.endswith("Screen text:\n" + text))
                else:
                    self.assertTrue(saved.endswith("Screen text:\nThe session's screen was empty.\n"))


class PartialArtifactTests(RunCase):
    @patch("herdworks.hc.get", return_value={"state": "live"})
    @patch("herdworks.hc.call")
    def test_diagnosis_report_does_not_hide_stall_or_get_reaped(self, call, get):
        from herdworks.gate import reap
        folder = self.path / "build-1"
        folder.mkdir()
        report = folder / "report.md"
        report.write_text("IN PROGRESS\nDiagnosis: before fixing")
        os.utime(report, (1000, 1000))
        append_event(self.path, dict(event="session", name="builder", role="build", address="t2",
                                    folder="build-1", started_at=1000, stuck_after_minutes=60))
        self.assertTrue(probe(self.path, clock=lambda: 4661)[0]["stalled"])
        self.assertEqual(reap(self.path), [])
        call.assert_not_called()
