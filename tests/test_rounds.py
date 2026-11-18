import os
import time
from unittest.mock import patch
from herdworks.gate import gate
from herdworks.runs import append_event, events, git
from herdworks.spawn import spawn
from tests.support import RunCase, write_claims


class BuildScenario(RunCase):
    def setUp(self):
        super().setUp()
        (self.home / "config.json").write_text(' {"max_worktrees": 20, "max_same_reason_failures": 9} ')
        (self.notes / "intent.md").write_text("DONE CHECK")
        append_event(self.path, dict(event="session", role="coordinator", name="hw-unit-coord", address="t1"))
        self.launcher = patch("herdworks.hc.launch", side_effect=self.launch)
        self.launcher.start()
        self.addCleanup(self.launcher.stop)
        self.getter = patch("herdworks.hc.get", return_value={"state": "missing"})
        self.getter.start()
        self.addCleanup(self.getter.stop)

    def launch(self, **kwargs):
        return dict(address=kwargs["name"], name=kwargs["name"], first_message={"sent": True})

    def ready(self):
        event = [e for e in events(self.path) if e.get("role") == "build"][-1]
        wt = self.path / event["folder"] / "wt"
        git(wt, "commit", "--allow-empty", "-m", f"test: build {event['folder']}")
        commit = git(wt, "rev-parse", "HEAD")
        (wt.parent / "report.md").write_text(f"READY {commit}\nDiagnosis: prior cause {event['folder']}\n")
        return commit

    def fail(self):
        spawn(self.path, "verify")
        verifier = [e for e in events(self.path) if e.get("role") == "verify"][-1]
        (self.path / verifier["folder"] / "verdict.md").write_text(
            f"FAIL\nCommit: {verifier['commit']}\nFinding: wrong output\n")
        gate(self.path)


class RoundTests(BuildScenario):
    def test_three_fixes_numbered_and_fourth_refused(self):
        spawn(self.path)
        self.ready()
        for number in range(1, 4):
            self.fail()
            result = spawn(self.path, "fix")
            self.assertEqual(result["name"], f"hw-unit-he-1-build-{number + 1}")
            brief = (self.path / f"build-{number + 1}/brief.md").read_text()
            for content in (f"Fix round: {number} of 3", "ORIGINAL REQUEST", "Finding: wrong output",
                            "Diagnosis: prior cause build-1", "BEFORE editing"):
                self.assertIn(content, brief)
            self.ready()
        self.fail()
        before = events(self.path)
        with self.assertRaisesRegex(ValueError, "three fix rounds.*ask"):
            spawn(self.path, "fix")
        self.assertEqual(events(self.path), before)
        self.assertFalse((self.path / "build-5").exists())

    def test_fix_rounds_keep_only_the_current_builder_worktree(self):
        spawn(self.path)
        self.ready()
        for number in range(1, 3):
            self.fail()
            spawn(self.path, "fix")
            self.ready()
        builders = sorted(p.parent.name for p in self.path.glob("build-*/wt"))
        self.assertEqual(builders, ["build-3"])
        self.assertTrue((self.path / "build-1/report.md").is_file())
        self.assertFalse((self.path / "build-1/unsaved.patch").exists())

    @patch("herdworks.hc.call", return_value={"text": "last screen"})
    def test_replacement_keeps_round_and_commit(self, call):
        spawn(self.path)
        self.ready()
        spawn(self.path, "verify")
        first = events(self.path)[-1]
        spawn(self.path, "verify", replaces=first["name"])
        replacement = events(self.path)[-1]
        self.assertEqual(replacement["round"], first["round"])
        self.assertEqual(replacement["commit"], first["commit"])
        self.assertEqual(replacement["step"], first["step"])
        saved = (self.path / "verify-1/stalled-1.txt").read_text()
        self.assertTrue(saved.endswith("Screen text:\nlast screen"))
        self.assertIn(f"Commit: {first['commit']}\n", saved)
        (self.path / "verify-2/verdict.md").write_text(f"FAIL\nCommit: {first['commit']}")
        gate(self.path)
        spawn(self.path, "fix")
        self.assertEqual(events(self.path)[-1]["round"], 1)
        self.assertEqual(events(self.path)[-1]["name"], "hw-unit-he-1-build-2")

    def test_stale_failure_cannot_start_another_fix(self):
        spawn(self.path)
        self.ready()
        self.fail()
        spawn(self.path, "fix")
        self.ready()
        with self.assertRaisesRegex(ValueError, "current built commit"):
            spawn(self.path, "fix")
        self.assertFalse((self.path / "build-3").exists())

    @patch("herdworks.hc.call", return_value={"text": "saved screen"})
    def test_replacement_retry_reconciles_partial_setup_without_extra_replacement(self, call):
        spawn(self.path)
        self.ready()
        spawn(self.path, "verify")
        original = events(self.path)[-1]["name"]
        def die_after_add(repo, *args, **kwargs):
            result = git(repo, *args, **kwargs)
            if args[:2] == ("worktree", "add"):
                raise KeyboardInterrupt("process died")
            return result
        with patch("herdworks.spawn.git", side_effect=die_after_add):
            with self.assertRaises(KeyboardInterrupt):
                spawn(self.path, "verify", replaces=original)
        self.assertTrue((self.path / "verify-2/wt/.git").exists())
        spawn(self.path, "verify", replaces=original)
        self.assertEqual(len([e for e in events(self.path) if e.get("event") == "stalled"]), 1)
        self.assertEqual(events(self.path)[-1]["name"], "hw-unit-he-1-verify-2")

    def test_rewind_build_uses_answers_without_resetting_fix_count(self):
        import time
        spawn(self.path)
        self.ready()
        self.fail()
        spawn(self.path, "fix")
        self.ready()
        (self.notes / "answers").mkdir()
        (self.notes / "answers/001.md").write_text("Use the approved greeting")
        append_event(self.path, dict(event="rewind", step="build", at=time.time()))
        spawn(self.path, "build")
        self.assertEqual(events(self.path)[-1]["round"], 1)
        self.assertIn("Use the approved greeting", (self.path / "build-3/brief.md").read_text())
        self.assertIn("ORIGINAL REQUEST", (self.path / "build-3/brief.md").read_text())
        with self.assertRaisesRegex(RuntimeError, "already started"):
            spawn(self.path, "build")

    @patch("herdworks.hc.call", return_value={"text": "empty builder"})
    def test_builder_replacement_pins_commit_and_preserves_unfinished_files(self, call):
        spawn(self.path)
        original = events(self.path)[-1]
        old = self.path / "build-1/wt"
        (old / "unfinished.txt").write_text("keep this work")
        spawn(self.path, "build", replaces=original["name"])
        replacement = events(self.path)[-1]
        self.assertEqual(replacement["commit"], original["commit"])
        self.assertEqual(git(self.path / "build-2/wt", "rev-parse", "HEAD"), original["commit"])
        self.assertFalse(old.exists())
        saved = self.path / "build-1/unsaved.patch"
        self.assertIn("keep this work", saved.read_text())
        git(self.path / "build-2/wt", "apply", saved)
        self.assertEqual((self.path / "build-2/wt/unfinished.txt").read_text(), "keep this work")
        self.assertEqual(replacement["round"], 0)

    @patch("herdworks.hc.call")
    def test_builder_with_unreported_commit_is_not_rewound_by_replacement(self, call):
        spawn(self.path)
        original = events(self.path)[-1]
        wt = self.path / "build-1/wt"
        git(wt, "commit", "--allow-empty", "-m", "test: unreported work")
        head = git(wt, "rev-parse", "HEAD")
        with self.assertRaisesRegex(ValueError, "branch advanced.*ask"):
            spawn(self.path, "build", replaces=original["name"])
        self.assertEqual(git(wt, "rev-parse", "HEAD"), head)
        call.assert_not_called()

    def test_external_prerequisite_requires_answer_after_latest_verdict(self):
        import time
        spawn(self.path)
        self.ready()
        spawn(self.path, "verify")
        verdict = self.path / "verify-1/verdict.md"
        (self.notes / "answers").mkdir()
        old = self.notes / "answers/001.md"
        old.write_text("old answer")
        import os
        os.utime(old, (time.time() - 10, time.time() - 10))
        verdict.write_text("INCONCLUSIVE\nCause: external-prerequisite\nAsk: install hello-prereq")
        with self.assertRaisesRegex(ValueError, "new answer"):
            spawn(self.path, "verify")
        self.assertFalse((self.path / "verify-2").exists())
        (self.notes / "answers/002.md").write_text("new answer")
        spawn(self.path, "verify")
        self.assertEqual(events(self.path)[-1]["name"], "hw-unit-he-1-verify-2")
        self.assertEqual(events(self.path)[-1]["round"], 0)


class EnvironmentBlockerTests(BuildScenario):
    def test_verifier_not_retried_but_partial_evidence_can_be_inspected(self):
        spawn(self.path)
        commit = self.ready()
        spawn(self.path, 'verify')
        verdict = self.path / 'verify-1/verdict.md'
        verdict.write_text(f'INCONCLUSIVE\nCommit: {commit}\n'
                           'BLOCKED-BY-ENVIRONMENT: Test on device; no device available\n'
                           'PASSED-OTHER-CHECKS: Unit tests and CLI passed\n')
        write_claims(verdict.parent, 'PROVED', 'NOT_PROVED')
        with self.assertRaisesRegex(ValueError, 'do not retry'):
            spawn(self.path, 'verify')
        self.assertFalse((self.path / 'verify-2').exists())
        spawn(self.path, 'evidence')
        review = self.path / 'evidence-1/review.md'
        review.write_text('INCONCLUSIVE\nBLOCKED-BY-ENVIRONMENT: Inspect device output; no device\n'
                          'PASSED-OTHER-CHECKS: Remaining evidence inspected\n')
        with self.assertRaisesRegex(ValueError, 'do not retry'):
            spawn(self.path, 'evidence')


class EvidenceGateTests(BuildScenario):
    def passed_verdict(self):
        spawn(self.path)
        commit = self.ready()
        spawn(self.path, 'verify')
        verifier = [e for e in events(self.path) if e.get('role') == 'verify'][-1]
        verdict = self.path / verifier['folder'] / 'verdict.md'
        verdict.write_text(f'PASS\nCommit: {commit}\n')
        write_claims(verdict.parent)
        return commit, verifier, verdict

    def stale_review(self, commit, verifier, verdict):
        """Record a review that began three seconds before its verdict (the HW-1 shape)."""
        now = time.time()
        os.utime(verdict, (now, now))
        folder = self.path / 'evidence-1'
        folder.mkdir()
        (folder / 'review.md').write_text('CONFIRMED\n')
        os.utime(folder / 'review.md', (now, now))
        append_event(self.path, dict(event='session', role='evidence', address='t4',
                                     name='hw-unit-he-1-evidence-1', folder='evidence-1',
                                     started_at=now - 3, stuck_after_minutes=20,
                                     launch_source='template', commit=commit,
                                     verifier=verifier['name']))
        return folder

    def test_evidence_refused_while_verdict_is_missing(self):
        spawn(self.path)
        self.ready()
        spawn(self.path, 'verify')
        with patch('herdworks.hc.launch') as launch:
            with self.assertRaisesRegex(ValueError, 'must wait for the verdict.*missing'):
                spawn(self.path, 'evidence')
            launch.assert_not_called()
        self.assertFalse((self.path / 'evidence-1').exists())

    def test_evidence_refused_while_verdict_is_being_written(self):
        spawn(self.path)
        self.ready()
        spawn(self.path, 'verify')
        (self.path / 'verify-1/verdict.md').write_text('')
        with patch('herdworks.hc.launch') as launch:
            with self.assertRaisesRegex(ValueError, 'must wait for the verdict.*still being written'):
                spawn(self.path, 'evidence')
            launch.assert_not_called()
        self.assertFalse((self.path / 'evidence-1').exists())

    def test_evidence_refused_while_verifier_session_is_live(self):
        commit, verifier, verdict = self.passed_verdict()
        with patch('herdworks.hc.get', return_value={'state': 'live'}):
            with patch('herdworks.hc.launch') as launch:
                with self.assertRaisesRegex(ValueError, 'must wait for the verdict.*still live'):
                    spawn(self.path, 'evidence')
                launch.assert_not_called()
        self.assertFalse((self.path / 'evidence-1').exists())

    def test_stale_review_is_replaced_by_one_spawn_and_gate_accepts_it(self):
        commit, verifier, verdict = self.passed_verdict()
        old = self.stale_review(commit, verifier, verdict)
        result = spawn(self.path, 'evidence')
        fresh = events(self.path)[-1]
        self.assertEqual(fresh['folder'], 'evidence-2')
        self.assertEqual(fresh['step'], f'evidence:{commit}')
        self.assertGreaterEqual(fresh['started_at'], verdict.stat().st_mtime)
        self.assertEqual(result['address'], fresh['address'])
        self.assertTrue((old / 'review.md').is_file())
        (self.path / 'evidence-2/review.md').write_text('CONFIRMED\n')
        passed, gate_commit, reasons = gate(self.path)
        self.assertTrue(passed, reasons)
        self.assertEqual(gate_commit, commit)

    def test_stale_review_replacement_counts_against_session_budget(self):
        commit, verifier, verdict = self.passed_verdict()
        self.stale_review(commit, verifier, verdict)
        (self.home / 'config.json').write_text('{"max_sessions_per_task": 3}')
        with patch('herdworks.hc.launch') as launch:
            with self.assertRaisesRegex(ValueError, 'budget'):
                spawn(self.path, 'evidence')
            launch.assert_not_called()
        self.assertFalse((self.path / 'evidence-2').exists())

    def test_review_after_verdict_still_passes_gate_and_is_not_duplicated(self):
        commit, verifier, verdict = self.passed_verdict()
        spawn(self.path, 'evidence')
        folder = self.path / events(self.path)[-1]['folder']
        (folder / 'review.md').write_text('CONFIRMED\n')
        passed, gate_commit, reasons = gate(self.path)
        self.assertTrue(passed, reasons)
        self.assertEqual(gate_commit, commit)
        with self.assertRaisesRegex(RuntimeError, 'already started'):
            spawn(self.path, 'evidence')
        self.assertFalse((self.path / 'evidence-2').exists())
