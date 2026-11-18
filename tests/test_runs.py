import json
import os
from unittest.mock import patch
from herdworks.cli import install
from herdworks.runs import append_event, built_commit, derive_status, git
from tests.support import RunCase


class TaskTests(RunCase):
    def test_status_from_current_artifacts(self):
        self.assertEqual(derive_status(self.path), 'queued')
        append_event(self.path, dict(event='session', role='build'))
        self.assertEqual(derive_status(self.path), 'in progress')
        git(self.repo, 'checkout', '-b', 'hw/HE-1')
        (self.path / 'build-1').mkdir()
        sha = self.commit()
        report = self.path / 'build-1/report.md'
        report.write_text(f'READY {sha}\n')
        self.assertEqual(built_commit(self.path), sha)
        self.assertEqual(derive_status(self.path), 'in progress')
        self.notes.joinpath('ask.md').write_text('Which greeting?')
        self.assertEqual(derive_status(self.path), 'waiting on you')

    def test_new_numbered_answer_clears_stale_question_in_tasks(self):
        from herdworks.cli import task_lines
        ask = self.notes / 'ask.md'
        ask.write_text('Which greeting?')
        os.utime(ask, (1000, 1000))
        inbox = self.project / 'inbox.jsonl'
        messages = [dict(number=1, text='Original request', at=900),
                    dict(number=2, text='What is the status?', at=1100)]
        inbox.write_text(''.join(json.dumps(m) + '\n' for m in messages))
        self.assertIn('waiting on you', next(task_lines(self.project)))
        answers = self.notes / 'answers'
        answers.mkdir()
        (answers / '1.md').write_text('Original request')
        self.assertIn('waiting on you', next(task_lines(self.project)))
        messages.append(dict(number=3, text='Use Welcome aboard, Ada!', at=1200))
        inbox.write_text(''.join(json.dumps(m) + '\n' for m in messages))
        (answers / '003.md').write_text('Different message')
        self.assertIn('waiting on you', next(task_lines(self.project)))
        (answers / '003.md').write_text(messages[-1]['text'] + '\n')
        self.assertIn('HE-1 queued', next(task_lines(self.project)))
        self.assertTrue(ask.exists())
        os.utime(ask, (1300, 1300))
        self.assertIn('waiting on you', next(task_lines(self.project)))

    def test_install_refuses_foreign_or_edited_template(self):
        source = self.root / 'templates'
        source.mkdir()
        (source / 'hw-coordinator.md').write_text('command: {{CODEX}} coordinator')
        destination = self.root / 'installed'
        install(self.root, destination)
        install(self.root, destination)
        installed = destination / 'hw-coordinator.md'
        self.assertIn(str(self.root / 'bin/hw-codex'), installed.read_text())
        installed.write_text('foreign')
        with self.assertRaisesRegex(ValueError, 'refusing to overwrite'):
            install(self.root, destination)


from tests.support import GateCase, write_claims


class ManualVerificationStatusTests(GateCase):
    def test_manual_draft_status_survives_stop_without_claiming_verified(self):
        from herdworks.cli import task_lines
        from herdworks.gate import check_gate
        timestamp = self.verdict.stat().st_mtime
        self.verdict.write_text(f'INCONCLUSIVE\nCommit: {self.sha}\n'
                                'BLOCKED-BY-ENVIRONMENT: Run on target device; device unavailable\n'
                                'PASSED-OTHER-CHECKS: All executable checks passed\n')
        os.utime(self.verdict, (timestamp, timestamp))
        write_claims(self.verify, 'PROVED', 'NOT_PROVED')
        append_event(self.path, dict(event='pr', commit=self.sha, manual_verification=True,
                                    url='https://github.invalid/fixture/hello/pull/1'))
        with patch('herdworks.hc.get', return_value={'state': 'missing'}):
            line = next(task_lines(self.project))
        self.assertIn(f'HE-1 needs manual verification {self.sha} https://github.invalid/fixture/hello/pull/1', line)
        self.assertFalse(check_gate(self.path)[0])
        self.assertTrue(check_gate(self.path, manual_verification=True)[0])
        append_event(self.path, dict(event='stop'))
        self.assertEqual(derive_status(self.path), 'needs manual verification')
        self.verdict.write_text(f'FAIL\nCommit: {self.sha}\nCode output is wrong\n')
        self.assertEqual(derive_status(self.path), 'needs manual verification')
        self.assertFalse(check_gate(self.path)[0])

    def test_recorded_draft_keeps_for_review_status_after_stop(self):
        from herdworks.cli import task_lines
        append_event(self.path, dict(event='pr', commit=self.sha,
                                    url='https://github.invalid/fixture/hello/pull/1'))
        append_event(self.path, dict(event='stop'))
        self.assertEqual(derive_status(self.path), 'for review')
        self.report.write_text('Post-handoff report unavailable')
        with patch('herdworks.hc.get', return_value={'state': 'missing'}):
            line = next(task_lines(self.project))
        self.assertIn(f'HE-1 for review {self.sha} https://github.invalid/fixture/hello/pull/1', line)
