import contextlib
import io
import os
from unittest.mock import patch

from herdworks.cli import main
from herdworks.gate import check_gate
from herdworks.projects import new_task
from herdworks.runs import read_task
from herdworks.talk import inbox, say
from tests.support import RunCase


class ImpactTests(RunCase):
    def setUp(self):
        super().setUp()
        self.caller = dict(state='live', address='t-coord', status='idle',
                           cwd=str(self.project / 'coordinator'),
                           labels={'hw': 'project:unit', 'role': 'coordinator'})

    def run_cli(self, *args, expected=0):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(list(args)), expected, error.getvalue())
        return (out.getvalue() if expected == 0 else error.getvalue()).strip()

    @patch('herdworks.hc.call')
    def test_proposal_survives_message_handoff_and_replay(self, call):
        reason = 'Reproduced with a straightforward CSS fix'
        text = 'Fix mobile overflow\nKeep the current layout'
        with patch('herdworks.hc.get', return_value=self.caller):
            self.assertEqual(say(self.project, text, impact='green', impact_reason=reason), (1, False))
            path, repeat = new_task(self.project, message=1)
            self.assertFalse(repeat)
            self.assertEqual((path / 'brief.md').read_text(), text)
            self.assertEqual(read_task(path)['impact'], dict(level='green', reason=reason))
            self.assertEqual(self.run_cli('task', 'impact', 'unit', 'HE-2', 'yellow',
                                          '--reason', 'A migration is needed'),
                             'HE-2 [impact=yellow (proposed) A migration is needed]')
            self.assertEqual(say(self.project, number=1), (1, True))
            self.assertEqual(new_task(self.project, message=1), (path, True))
            with self.assertRaisesRegex(ValueError, 'original impact proposal'):
                say(self.project, number=1, impact='yellow', impact_reason='A migration is needed')
            self.assertEqual(len(inbox(self.project)), 1)
            self.assertIn('HE-2 queued', self.run_cli('tasks', 'unit'))
            self.assertIn('impact=yellow (proposed) A migration is needed', self.run_cli('tasks', 'unit'))
            self.assertIn('impact=yellow (proposed) A migration is needed', self.run_cli('status', 'unit'))
        self.assertEqual(call.call_args_list[0].args, ('send', 't-coord', 'MESSAGE 1\n' + text))
        self.assertEqual(call.call_args_list[0], call.call_args_list[1])

    @patch('herdworks.hc.call')
    def test_legacy_intake_and_invalid_proposals(self, call):
        with patch('herdworks.hc.get', return_value=self.caller):
            for flags in (['--impact', 'green'], ['--impact-reason', 'missing level'],
                          ['--confidence', 'low'], ['--reproduction', 'unreproduced'],
                          ['--impact', 'green', '--impact-reason', '  '],
                          ['--impact', 'green', '--impact-reason', 'one\ntwo']):
                with self.subTest(flags=flags):
                    self.assertIn('single-line reason', self.run_cli('say', 'unit', 'Intake', *flags, expected=1))
            self.assertEqual(inbox(self.project), [])
            call.assert_not_called()
            self.assertEqual(self.run_cli('say', 'unit', 'Legacy intake'), 'delivered 1')
            self.assertNotIn('impact', inbox(self.project)[0])
            path, _ = new_task(self.project, message=1)
            self.assertNotIn('impact', read_task(path))
            self.assertNotIn('impact=', self.run_cli('tasks', 'unit'))

    @patch('herdworks.hc.call')
    def test_reproduction_and_confidence_travel_separately_from_impact(self, call):
        flags = ('--impact', 'yellow', '--impact-reason', 'Requires a production migration',
                 '--reproduction', 'unreproduced', '--confidence', 'low')
        expected = dict(level='yellow', reason='Requires a production migration',
                        reproduction='unreproduced', confidence='low')
        with patch('herdworks.hc.get', return_value=self.caller):
            self.assertEqual(self.run_cli('say', 'unit', 'Investigate password manager', *flags), 'delivered 1')
            self.assertEqual(inbox(self.project)[0]['impact'], expected)
            path, _ = new_task(self.project, message=1)
            self.assertEqual(read_task(path)['impact'], expected)
            for command in ('tasks', 'status'):
                self.assertIn('[impact=yellow (proposed) Requires a production migration '
                              'reproduction=unreproduced confidence=low]', self.run_cli(command, 'unit'))
            self.run_cli('task', 'impact', 'unit', 'HE-2', 'yellow', '--reason', 'Migration confirmed',
                         '--confidence', 'medium')
            expected.update(reason='Migration confirmed', confidence='medium')
            self.assertEqual(read_task(path)['impact'], expected)
            self.assertEqual(self.run_cli('say', 'unit', '--number', '1', *flags), 'delivered 1 repeat')
            self.assertEqual(new_task(self.project, message=1), (path, True))
            self.assertEqual(read_task(path)['impact'], expected)
            self.assertIn('original impact proposal', self.run_cli('say', 'unit', '--number', '1',
                          *flags[:-1], 'high', expected=1))

    def test_owner_correction_is_protected_and_does_not_affect_authority(self):
        gate_before = check_gate(self.path)
        project_before = (self.project / 'project.json').read_bytes()
        self.run_cli('task', 'impact', 'unit', 'HE-1', 'yellow', '--reason', 'Migration',
                     '--reproduction', 'unreproduced', '--confidence', 'low')
        command = ('task', 'correct-impact', 'unit', 'HE-1', 'red', '--reason', 'Needs Architect',
                   '--confidence', 'high')
        corrected = '[impact=red (owner correction) Needs Architect reproduction=unreproduced confidence=high]'
        with patch.dict(os.environ, HW_CALLER_TERMINAL='t-coord'):
            self.assertIn('owner outside Herdworks sessions', self.run_cli(*command, expected=1))
        with patch('herdworks.hc.require_owner') as require_owner:
            self.assertEqual(self.run_cli(*command), 'HE-1 ' + corrected)
            require_owner.assert_called_once()
        with patch.dict(os.environ, HW_CALLER_TERMINAL='t-coord'), patch('herdworks.hc.get', return_value=self.caller):
            self.assertIn('owner correction is in effect',
                          self.run_cli('task', 'impact', 'unit', 'HE-1', 'green', '--reason', 'Local fix', expected=1))
            self.assertIn('HE-1 queued', self.run_cli('tasks', 'unit'))
            for command in ('tasks', 'status'):
                self.assertIn(corrected, self.run_cli(command, 'unit'))
            self.assertIn('has not granted push, draft-pr', self.run_cli('pr', 'unit', 'HE-1', expected=1))
        self.assertEqual(check_gate(self.path), gate_before)
        self.assertEqual((self.project / 'project.json').read_bytes(), project_before)
