import json
from unittest.mock import patch
from herdworks.talk import inbox, read, say, up
from tests.support import RunCase


class TalkTests(RunCase):
    def live(self, status='idle'):
        return dict(name='hw-unit-coord', address='t1', state='live', status=dict(state=status),
                    cwd=str(self.project / 'coordinator'), labels=dict(hw='project:unit'))

    def test_numbers_rise_text_is_exact_and_repeats_are_marked(self):
        text = 'quotes " $()`\nsecond line'
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call') as call:
            self.assertEqual(say(self.project, text), (1, False))
            self.assertEqual(say(self.project, 'next'), (2, False))
            self.assertEqual(say(self.project, number=1), (1, True))
            with self.assertRaisesRegex(ValueError, 'original text'):
                say(self.project, 'changed', 1)
        self.assertEqual(len(inbox(self.project)), 2)
        self.assertEqual(inbox(self.project)[0]['text'], text)
        self.assertEqual(call.call_args_list[0].args, ('send', 't1', 'MESSAGE 1\n' + text))
        self.assertEqual(call.call_args_list[2].args, call.call_args_list[0].args)
        self.assertFalse(any('--force' in c.args for c in call.call_args_list))

    def test_read_since_and_invalid_opening(self):
        outbox = self.project / 'coordinator/outbox'
        for number, kind in enumerate(('REPLY', 'QUESTION', 'DONE'), 1):
            (outbox / f'{number:06}.md').write_text(kind + '\nTask: HE-1')
        self.assertEqual([n for n, _ in read(self.project, 1)], [2, 3])
        (outbox / '000004.md').write_text('PASS\nforged')
        with self.assertRaisesRegex(ValueError, 'invalid outbox'):
            read(self.project, 4)

    def test_blocked_is_reported_without_delivery_or_inbox_write(self):
        with patch('herdworks.hc.get', return_value=self.live('blocked')), patch('herdworks.hc.call') as call:
            with self.assertRaisesRegex(ValueError, 'blocked'):
                say(self.project, 'hello')
        call.assert_not_called()
        self.assertEqual(inbox(self.project), [])

    def test_lost_send_can_be_replayed_with_same_number(self):
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call', side_effect=RuntimeError('lost reply')):
            with self.assertRaises(RuntimeError):
                say(self.project, 'answer')
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call') as call:
            self.assertEqual(say(self.project, number=1), (1, True))
            call.assert_called_once_with('send', 't1', 'MESSAGE 1\nanswer')
        self.assertEqual(len(inbox(self.project)), 1)

    def test_up_launches_without_parent_and_refuses_live_duplicate(self):
        with patch('herdworks.hc.get', return_value=dict(state='missing')), patch('herdworks.hc.launch') as launch:
            launch.return_value = dict(name='hw-unit-coord', address='t2', first_message=dict(sent=True))
            up(self.project)
            args = launch.call_args.kwargs
            self.assertEqual(args['name'], 'hw-unit-coord')
            self.assertEqual(args['cwd'], self.project / 'coordinator')
            self.assertIsNone(args.get('parent'))
            self.assertEqual(args['template'], 'hw-coordinator')
            self.assertIn('rule 18', args['task'])
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.launch') as launch:
            with self.assertRaisesRegex(ValueError, 'alive'):
                up(self.project)
            launch.assert_not_called()

    def test_say_starts_a_missing_coordinator(self):
        with patch('herdworks.hc.get', return_value=dict(state='missing')), patch('herdworks.hc.launch') as launch, patch('herdworks.hc.call') as call:
            launch.return_value = dict(name='hw-unit-coord', address='t2', first_message=dict(sent=True))
            self.assertEqual(say(self.project, 'hello'), (1, False))
            self.assertIn('Read inbox.jsonl', launch.call_args.kwargs['task'])
            self.assertEqual(inbox(self.project)[0]['text'], 'hello')
            call.assert_not_called()

    def test_up_reconciles_uncertain_live_launch(self):
        (self.project / '.coordinator-pending.json').write_text('{"name":"hw-unit-coord"}')
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.launch') as launch:
            self.assertEqual(up(self.project)['address'], 't1')
            launch.assert_not_called()
        self.assertFalse((self.project / '.coordinator-pending.json').exists())

    def test_startup_guard_retries_only_when_nothing_was_typed(self):
        from herdworks import hc
        error = hc.HCError(5, 'still starting: nothing was typed')
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call', side_effect=[error, {}, {}]) as call:
            self.assertEqual(say(self.project, 'hello'), (1, False))
            self.assertEqual(call.call_args_list[1].args[:2], ('wait', 't1'))
            self.assertEqual(call.call_args_list[0].args, call.call_args_list[2].args)

    def test_unsent_startup_is_relaunched_before_say(self):
        failed = dict(name='hw-unit-coord', address='t1', first_message=dict(sent=False))
        ready = dict(name='hw-unit-coord', address='t2', first_message=dict(sent=True))
        with patch('herdworks.hc.get', return_value=dict(state='missing')), patch('herdworks.hc.launch', return_value=failed):
            with self.assertRaisesRegex(RuntimeError, 'first message'):
                up(self.project)
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.launch', return_value=ready) as launch, patch('herdworks.hc.call') as call:
            self.assertEqual(say(self.project, 'hello'), (1, False))
            launch.assert_called_once()
            self.assertIn('Read inbox.jsonl', launch.call_args.kwargs['task'])
            self.assertEqual(call.call_args_list[0].args, ('kill', 't1'))
            self.assertEqual(call.call_args_list[1].args, ('rm', 't1'))
            self.assertFalse(any(c.args[0] == 'send' for c in call.call_args_list))
        self.assertFalse((self.project / '.coordinator-pending.json').exists())

    def test_say_after_reconciling_a_sent_startup_still_delivers_new_message(self):
        marker = self.project / '.coordinator-pending.json'
        marker.write_text(json.dumps(dict(name='hw-unit-coord', result=dict(first_message=dict(sent=True)))))
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.launch') as launch, patch('herdworks.hc.call') as call:
            self.assertEqual(say(self.project, 'new message after startup'), (1, False))
            launch.assert_not_called()
            call.assert_called_once_with('send', 't1', 'MESSAGE 1\nnew message after startup')
        self.assertFalse(marker.exists())


class OutboxPublicationTests(RunCase):
    def test_atomic_temporary_entry_is_not_a_published_reply(self):
        from herdworks.talk import read
        outbox = self.project / 'coordinator/outbox'
        (outbox / '.000001.md.tmp').write_text('RE')
        (outbox / '.tmp-000001.md').write_text('RE')
        (outbox / '000002.md.tmp').write_text('RE')
        self.assertEqual(read(self.project), [])
        (outbox / '000001.md').write_text('REPLY\nTask: HE-1\n')
        self.assertEqual(len(read(self.project)), 1)
