import os
import json
import time
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from herdworks.gate import check_gate, gate, reap
from herdworks import hc
from herdworks.runs import append_event, derive_status, events, git, read_task
from tests.support import GateCase


class GateTests(GateCase):
    def set_launch_source(self, role, source):
        history = events(self.path)
        for event in history:
            if event.get('role') == role:
                event['launch_source'] = source
        (self.path / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in history))

    def test_overridden_verifier_is_refused(self):
        self.set_launch_source('verify', 'override')
        self.assert_refused('verdict session must come from the verifier template')

    def test_overridden_evidence_reviewer_is_refused(self):
        self.set_launch_source('evidence', 'override')
        self.assert_refused('review session must come from the evidence-reviewer template')

    def test_missing_provenance_is_not_trusted(self):
        self.set_launch_source('verify', None)
        self.assert_refused('verdict session must come from the verifier template')

    def forged_override(self, role):
        import io
        from contextlib import redirect_stdout
        from herdworks.cli import main
        self.set_launch_source(role, 'override')
        folder = self.path / f'{role}-1'
        cwd = folder / 'work'
        cwd.mkdir()
        brief = folder / 'brief.md'
        brief.write_text('Attempt provenance forgery.\n')
        program = Path(__file__).parent / 'planted/forge-source.py'

        def direct_launch(*args):
            # Substitute only the hc transport; execute its real direct-program argv.
            result = subprocess.run(list(map(str, args[args.index('--') + 1:])),
                                    cwd=cwd, capture_output=True, text=True, check=True)
            print(result.stdout, end='')
            return {'address': 'planted', 'output': result.stdout}

        with patch('herdworks.hc.call', side_effect=direct_launch):
            result = hc.launch(name='planted', cwd=cwd, template='unused', task=str(brief),
                               identity='unit', role=role, program=str(program))
        if role == 'verify':
            # The tools record the subsequent evidence step after this verdict.
            history = events(self.path)
            for event in history:
                if event.get('role') == 'evidence':
                    event['started_at'] = time.time()
            (self.path / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in history))
            (self.review / 'review.md').write_text('CONFIRMED\n')
        output = io.StringIO()
        with patch('herdworks.cli.task_path', return_value=self.path), patch('herdworks.cli.project_path', return_value=self.project), redirect_stdout(output):
            code = main(['gate', 'unit', 'HE-1'])
        print(output.getvalue(), end='')
        self.assertEqual(code, 1, output.getvalue())
        self.assertTrue(output.getvalue().startswith('REFUSED\n'))
        with patch('herdworks.cli.task_path', return_value=self.path), patch('herdworks.cli.project_path', return_value=self.project), \
                patch('herdworks.hc.sessions', return_value=[]), \
                patch('herdworks.hc.get', return_value={'state': 'missing'}), redirect_stdout(output):
            self.assertEqual(main(['tasks', 'unit']), 0)
        self.assertNotEqual(output.getvalue().splitlines()[-1].split()[1], 'verified')
        self.assertIn('DENIED events.jsonl', result['output'])

    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS sandbox-exec')
    def test_forged_evidence_override_is_refused(self):
        self.forged_override('evidence')

    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS sandbox-exec')
    def test_forged_verifier_override_is_refused(self):
        self.forged_override('verify')

    def assert_refused(self, reason):
        passed, _, reasons = gate(self.path)
        self.assertFalse(passed)
        self.assertTrue(any(reason in item for item in reasons), reasons)
        self.assertNotEqual(derive_status(self.path), 'verified')

    def test_complete_case_and_derived_status(self):
        self.assertEqual(gate(self.path), (True, self.sha, []))
        self.assertEqual(derive_status(self.path), 'verified')
        self.assertEqual(events(self.path)[-1]['event'], 'gate')
        self.assertTrue(events(self.path)[-1]['passed'])

    def test_passing_gate_takes_precedence_over_resolved_ask_note(self):
        (self.notes / 'ask.md').write_text('Resolved question: nothing remains pending')
        self.assertEqual(derive_status(self.path), 'verified')

    def test_lowercase_verdict(self):
        self.verdict.write_text(f'pass\n{self.sha}\n')
        self.assert_refused('exactly PASS')

    def test_other_commit(self):
        self.verdict.write_text('PASS\nCommit: ' + 'f' * 40)
        self.assert_refused('name the current built commit')

    def test_new_commit_invalidates_verdict(self):
        (self.repo / 'extra.txt').write_text('later')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'test: later commit')
        self.assert_refused('current branch head')
        self.report.write_text('READY ' + git(self.repo, 'rev-parse', 'HEAD'))
        self.assert_refused('name the current built commit')

    def test_unrecorded_verifier(self):
        records = [e for e in events(self.path) if e.get('role') != 'verify']
        import json
        (self.path / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in records))
        self.assert_refused('recorded independent verify session')

    def test_empty_evidence(self):
        (self.verify / 'evidence/cli.txt').unlink()
        self.assert_refused('at least one file')

    def test_missing_review(self):
        (self.review / 'review.md').unlink()
        self.assert_refused('review must open CONFIRMED')

    def test_rejected_review(self):
        (self.review / 'review.md').write_text('REJECTED\n')
        self.assert_refused('review must open CONFIRMED')

    def test_verdict_before_build_is_refused(self):
        self.report.touch()
        self.assert_refused('started after the build')

    def test_review_before_verdict_is_refused(self):
        self.verdict.touch()
        self.assert_refused('started after the verdict')

    @patch('herdworks.hc.call')
    @patch('herdworks.hc.get')
    def test_reap_preserves_proof_and_removes_only_verifier_worktree(self, get, call):
        git(self.repo, 'worktree', 'add', '--detach', self.verify / 'wt', self.sha)
        get.return_value = {'state': 'live'}
        call.return_value = {'text': 'last screen'}
        self.assertEqual(len(reap(self.path)), 3)
        self.assertFalse((self.verify / 'wt').exists())
        self.assertEqual((self.verify / 'last-screen.txt').read_text(), 'last screen')
        self.assertTrue((self.verify / 'evidence/cli.txt').is_file())
        self.assertTrue(check_gate(self.path)[0])
        self.assertEqual([c.args for c in call.call_args_list if c.args[0] == 'kill'],
                         [('kill', 't2'), ('kill', 't3'), ('kill', 't4')])
        get.return_value = {'state': 'finished'}
        call.reset_mock()
        reap(self.path)
        call.assert_not_called()

    @patch('herdworks.hc.call', return_value={'text': 'screen'})
    @patch('herdworks.hc.get', return_value={'state': 'finished'})
    def test_reap_removes_verifier_worktree_without_evidence_and_keeps_its_files(self, get, call):
        import shutil
        shutil.rmtree(self.verify / 'evidence')
        self.verdict.write_text(f'INCONCLUSIVE\nCommit: {self.sha}\nBLOCKED-BY-ENVIRONMENT: no device\n')
        wt = self.verify / 'wt'
        git(self.repo, 'worktree', 'add', '--detach', wt, self.sha)
        (wt / 'notes.txt').write_text('left in the worktree')
        reap(self.path)
        self.assertFalse(wt.exists())
        self.assertIn('left in the worktree', (self.verify / 'unsaved.patch').read_text())

    @patch('herdworks.hc.call', return_value={'text': 'plain program exited'})
    @patch('herdworks.hc.get', return_value={'state': 'finished'})
    def test_reap_saves_already_exited_program_screen(self, get, call):
        reap(self.path)
        self.assertEqual((self.build / 'last-screen.txt').read_text(), 'plain program exited')
        self.assertFalse(any(c.args[0] == 'kill' for c in call.call_args_list))

    def test_incidental_sha_does_not_override_verified_commit(self):
        self.verdict.write_text('PASS\nCommit: ' + 'f' * 40 + f'\nCompared against {self.sha}\n')
        self.assert_refused('name the current built commit')

    def test_cli_gate_reports_and_exits_with_decision(self):
        import io
        from contextlib import redirect_stdout
        from herdworks.cli import main
        output = io.StringIO()
        with patch('herdworks.cli.task_path', return_value=self.path), patch('herdworks.cli.project_path', return_value=self.project), redirect_stdout(output):
            self.assertEqual(main(['gate', 'unit', 'HE-1']), 0)
        self.assertEqual(output.getvalue(), f'VERIFIED {self.sha}\n')
        (self.review / 'review.md').unlink()
        output = io.StringIO()
        with patch('herdworks.cli.task_path', return_value=self.path), patch('herdworks.cli.project_path', return_value=self.project), redirect_stdout(output):
            self.assertEqual(main(['gate', 'unit', 'HE-1']), 1)
        self.assertTrue(output.getvalue().startswith('REFUSED\n'))
        self.assertIn('review must open CONFIRMED', output.getvalue())

    @patch('herdworks.hc.get', return_value={'state': 'missing', 'status': 'missing', 'turn': 0})
    @patch('herdworks.hc.sessions', return_value=[])
    def test_status_exposes_overrides_after_sessions_exit(self, sessions, get):
        import io
        from contextlib import redirect_stdout
        from herdworks.cli import main
        self.set_launch_source('verify', 'override')
        output = io.StringIO()
        with patch('herdworks.cli.task_path', return_value=self.path), patch('herdworks.cli.project_path', return_value=self.project), redirect_stdout(output):
            self.assertEqual(main(['tasks', 'unit']), 0)
        self.assertIn('overrides=verify', output.getvalue())
        self.assertIn('in progress', output.getvalue())
