from pathlib import Path
from unittest.mock import patch
from herdworks.runs import append_event, events, git, read_task
from herdworks.spawn import build_verify_brief, spawn
from tests.support import RunCase, write_claims

ROOT = Path(__file__).resolve().parents[1]


class VerifyBriefTests(RunCase):
    def setUp(self):
        super().setUp()
        (self.notes / 'intent.md').write_text('Journeys: verify-hello; original acceptance criteria apply.')
        append_event(self.path, dict(event='session', name='hw-unit-coord', role='coordinator', address='t1'))
        self.result = dict(address='t2', name='hw-unit-he-1-build-1', parent='t1', first_message={'sent': True})
        with patch('herdworks.hc.launch', return_value=self.result):
            spawn(self.path)
        wt = self.path / 'build-1/wt'
        skill = wt / '.agents/skills/verify-hello/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('Verify direct CLI outputs.')
        (wt / 'hello.py').write_text("print('changed')\n")
        git(wt, 'add', '.')
        git(wt, 'commit', '-m', 'feat: change')
        self.sha = git(wt, 'rev-parse', 'HEAD')
        (self.path / 'build-1/report.md').write_text(f'READY {self.sha}\nBUILDER-SAYS-IT-WORKS\nsecret conclusion')
        self.result.update(address='t3', name='hw-unit-he-1-verify-1')

    def test_brief_is_independent_of_entire_builder_report(self):
        wt = self.path / 'verify-1/wt'
        git(self.repo, 'worktree', 'add', '--detach', wt, self.sha)
        brief = build_verify_brief(self.path, self.sha, wt)
        for text in ('ORIGINAL REQUEST', self.sha, read_task(self.path)['base'], str(wt),
                     str(wt / '.agents/skills/verify-hello/SKILL.md'), 'Journeys: verify-hello',
                     str(self.project / 'inbox.jsonl'), str(self.path / 'events.jsonl')):
            self.assertIn(text, brief)
        for text in (self.path / 'build-1/report.md').read_text().splitlines():
            self.assertNotIn(text, brief)

    @patch('herdworks.hc.launch')
    def test_verifier_detached_and_evidence_requires_pass(self, launch):
        launch.return_value = self.result
        spawn(self.path, 'verify')
        wt = self.path / 'verify-1/wt'
        self.assertEqual(git(wt, 'rev-parse', 'HEAD'), self.sha)
        self.assertEqual(git(wt, 'branch', '--show-current'), '')
        self.assertEqual(events(self.path)[-1]['commit'], self.sha)
        self.assertEqual(events(self.path)[-1]['launch_source'], 'template')
        self.assertEqual(launch.call_args.kwargs['template'], 'hw-verifier')
        with self.assertRaisesRegex(ValueError, 'wait for the verdict'):
            spawn(self.path, 'evidence')
        (self.path / 'verify-1/verdict.md').write_text(f'FAIL\n{self.sha}')
        with self.assertRaisesRegex(ValueError, 'PASS'):
            spawn(self.path, 'evidence')
        (self.path / 'verify-1/verdict.md').write_text(f'PASS\n{self.sha}')
        write_claims(self.path / 'verify-1')
        spawn(self.path, 'evidence')
        self.assertEqual(launch.call_args.kwargs['template'], 'hw-evidence-reviewer')
        self.assertEqual(launch.call_args.kwargs['cwd'], self.path / 'evidence-1/work')
        self.assertIn(str(self.path / 'verify-1/evidence'), (self.path / 'evidence-1/brief.md').read_text())

    @patch('herdworks.hc.launch', side_effect=FileNotFoundError('missing hc'))
    def test_verifier_launch_failure_rolls_back_without_deleting_build(self, launch):
        with self.assertRaises(FileNotFoundError):
            spawn(self.path, 'verify')
        self.assertFalse((self.path / 'verify-1').exists())
        self.assertEqual(git(self.repo, 'rev-parse', 'hw/HE-1'), self.sha)
        self.assertTrue((self.path / 'build-1/wt').is_dir())

    @patch('herdworks.hc.launch', side_effect=RuntimeError('reply lost'))
    def test_verifier_uncertain_launch_keeps_marker_and_refuses_duplicate(self, launch):
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):
            spawn(self.path, 'verify')
        self.assertTrue((self.path / 'verify-1/launch-pending.json').exists())
        with patch('herdworks.hc.get', side_effect=RuntimeError('core unavailable; uncertain')):
            with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                spawn(self.path, 'verify')
        self.assertEqual(launch.call_count, 1)

    @patch('herdworks.hc.launch')
    def test_evidence_setup_failure_and_uncertain_launch_share_recovery(self, launch):
        launch.return_value = self.result
        spawn(self.path, 'verify')
        (self.path / 'verify-1/verdict.md').write_text(f'PASS\n{self.sha}')
        write_claims(self.path / 'verify-1')
        launch.side_effect = FileNotFoundError('missing hc')
        with self.assertRaises(FileNotFoundError):
            spawn(self.path, 'evidence')
        self.assertFalse((self.path / 'evidence-1').exists())
        launch.side_effect = RuntimeError('reply lost')
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):
            spawn(self.path, 'evidence')
        self.assertTrue((self.path / 'evidence-1/launch-pending.json').exists())
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):
            spawn(self.path, 'evidence')

    def test_numbered_answers_reach_verifier_in_message_order(self):
        folder = self.notes / 'answers'
        folder.mkdir()
        (folder / '10.md').write_text('later answer')
        (folder / '2.md').write_text('earlier answer')
        brief = build_verify_brief(self.path, self.sha, self.path / 'verify-1/wt')
        self.assertLess(brief.index('earlier answer'), brief.index('later answer'))
