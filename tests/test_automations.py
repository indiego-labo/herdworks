import contextlib
import io
import json
from unittest.mock import patch
from herdworks import automations as a
from herdworks.cli import main
from herdworks.talk import read, say
from tests.support import RunCase, GateCase


def issue(number=1, author='owner', state='OPEN', labels=('herdworks',)):
    return dict(number=number, title='Small task', body='Do the task', url=f'https://github.invalid/o/r/issues/{number}',
                author=dict(login=author), state=state, labels=[dict(name=n) for n in labels])


class AutomationsTests(RunCase):
    def add(self, trigger='schedule', **kwargs):
        return a.add('daily', 'unit', 'owner', trigger, 'Check the docs', now=1000,
                     authors=['owner'] if trigger == 'github-issue' else [], **kwargs)

    def live(self):
        return dict(state='live', status='idle', address='t1', cwd=str(self.project / 'coordinator'),
                    labels={'hw': 'project:unit'})

    def test_schedule_due_cap_day_and_off(self):
        self.add()
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call'):
            self.assertEqual(a.tick(1059), [])
            self.assertEqual(a.tick(1060)[0]['result'], 'sent')
            self.assertEqual(a.tick(1120)[0]['result'], 'capped')
            self.assertEqual(len((self.project / 'inbox.jsonl').read_text().splitlines()), 1)
            a.switch('daily', False)
            self.assertEqual(a.tick(1180), [])
            a.switch('daily', True, now=86400)
            self.assertEqual(a.tick(86460)[0]['result'], 'sent')
        self.assertEqual(len(a.history('daily')), 3)

    def test_issue_taken_once_filters_and_cap(self):
        self.add('github-issue')
        with patch('herdworks.automations.gh', return_value=json.dumps([issue(), issue(2), issue(3, author='stranger'), issue(4, state='CLOSED')])) as gh, patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call'):
            a.tick(1060)
            a.tick(1120)
            self.assertEqual(len((self.project / 'inbox.jsonl').read_text().splitlines()), 1)
            edits = [c for c in gh.call_args_list if c.args[1:3] == ('issue', 'edit')]
            self.assertEqual(len(edits), 1)
            self.assertIn('--remove-label', edits[0].args)
            a.switch('daily', True, now=86400)
            a.tick(86460)
            messages = [json.loads(line) for line in (self.project / 'inbox.jsonl').read_text().splitlines()]
            self.assertIn('issue #2', messages[-1]['text'])
        with patch('herdworks.automations.gh', return_value=json.dumps([issue(author='stranger'), issue(2, state='CLOSED'), issue(3, labels=())])):
            self.assertEqual(a.preview('daily'), [])

    def test_second_automation_does_not_retake_same_project_issue(self):
        self.add('github-issue')
        a.add('other', 'unit', 'owner', 'github-issue', 'Check it', authors=['owner'], now=1000)
        with patch('herdworks.automations.gh', return_value=json.dumps([issue()])), patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call'):
            a.tick(1060)
        self.assertEqual(len((self.project / 'inbox.jsonl').read_text().splitlines()), 1)
        self.assertEqual(len(a.load('other')['deliveries']), 0)

    def test_issue_queries_filter_each_allowed_author_before_the_limit(self):
        a.add('daily', 'unit', 'owner', 'github-issue', 'Check status', authors=['alice', 'bob'], now=1000)
        def github(project, *args):
            self.assertIn('--author', args)
            author = args[args.index('--author') + 1]
            return json.dumps([issue(1 if author == 'alice' else 2, author=author)])
        with patch('herdworks.automations.gh', side_effect=github) as query:
            self.assertEqual(len(a.preview('daily')), 2)
        self.assertEqual({call.args[call.args.index('--author') + 1] for call in query.call_args_list}, {'alice', 'bob'})

    def test_three_failures_problem_is_readable(self):
        self.add()
        with patch('herdworks.automations.say', side_effect=RuntimeError('delivery failed')):
            for now in (1060, 1120, 1180):
                a.tick(now)
        self.assertFalse(a.load('daily')['enabled'])
        self.assertEqual(a.load('daily')['failures'], 3)
        self.assertTrue(read(self.project)[0][1].startswith('PROBLEM\n'))
        self.assertEqual(a.tick(1240), [])

    def test_idle_switches_off(self):
        self.add()
        with patch('herdworks.automations.say') as send:
            self.assertIn('PROBLEM', a.tick(1121)[0]['result'])
            send.assert_not_called()
        self.assertFalse(a.load('daily')['enabled'])

    def test_preview_sends_nothing_and_changes_nothing(self):
        self.add()
        before = a.path_for('daily').read_bytes()
        with patch('herdworks.automations.say') as send, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['automation', 'test', 'daily']), 0)
            send.assert_not_called()
        self.assertIn('Check the docs', output.getvalue())
        self.assertEqual(before, a.path_for('daily').read_bytes())
        self.assertFalse((a.folder() / 'runs.jsonl').exists())

    def test_delivery_key_survives_uncertain_send(self):
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call', side_effect=RuntimeError('lost response')):
            with self.assertRaises(RuntimeError):
                say(self.project, 'hello', delivery_key='unique')
        with patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call') as call:
            self.assertEqual(say(self.project, 'hello', delivery_key='unique'), (1, True))
            self.assertIn('MESSAGE 1', call.call_args.args[-1])
        self.assertEqual(len((self.project / 'inbox.jsonl').read_text().splitlines()), 1)

    def test_retry_on_new_day_counts_toward_that_days_cap(self):
        self.add('github-issue')
        with patch('herdworks.automations.gh', return_value=json.dumps([issue(), issue(2)])), patch('herdworks.automations.say', side_effect=RuntimeError('offline')):
            a.tick(1060)
        a.switch('daily', True, now=86400)
        with patch('herdworks.automations.gh', return_value=json.dumps([issue(), issue(2)])), patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call'):
            a.tick(86460)
        self.assertEqual(len((self.project / 'inbox.jsonl').read_text().splitlines()), 1)

    def test_label_failure_recovers_without_second_message(self):
        self.add('github-issue')
        def gh(project, *args):
            if args[:2] == ('issue', 'list'):
                return json.dumps([issue()])
            raise RuntimeError('label failed')
        with patch('herdworks.automations.gh', side_effect=gh), patch('herdworks.hc.get', return_value=self.live()), patch('herdworks.hc.call'):
            a.tick(1060)
        with patch('herdworks.automations.gh', return_value='[]'), patch('herdworks.automations.say') as send:
            a.tick(1120)
            send.assert_not_called()
        self.assertEqual(len((self.project / 'inbox.jsonl').read_text().splitlines()), 1)
        self.assertTrue(a.load('daily')['deliveries'][0]['done'])

    def test_owner_only_cli(self):
        with patch.dict('os.environ', HW_CALLER_TERMINAL='worker'), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['automations', 'tick']), 1)
            self.assertEqual(main(['automation', 'add', 'bad', '--project', 'unit', '--owner', 'worker', '--trigger', 'schedule', '--instructions', 'x']), 1)
        self.assertFalse(a.path_for('bad').exists())


class IssueCommentTests(GateCase):
    def test_comment_when_for_review_once_and_recover_response_loss(self):
        from herdworks.runs import append_event
        a.add('daily', 'unit', 'owner', 'github-issue', 'Do it', authors=['owner'], now=1000)
        data = a.load('daily')
        data['deliveries'] = [dict(source='issue:1', issue=1, key='key', day='1970-01-01', at=1000, message=1, done=True)]
        a.write(a.path_for('daily'), data)
        metadata = json.loads((self.path / 'task.json').read_text())
        metadata['message'] = 1
        (self.path / 'task.json').write_text(json.dumps(metadata))
        append_event(self.path, dict(event='pr', commit=self.sha, url='https://github.invalid/o/r/pull/1'))
        with patch('herdworks.hc.get', return_value={'state': 'exited'}), patch('herdworks.automations.gh', return_value='{"comments": []}') as gh:
            a.tick(1060)
            a.tick(1120)
        calls = [c for c in gh.call_args_list if c.args[1:3] == ('issue', 'comment')]
        self.assertEqual(len(calls), 1)
        self.assertIn('https://github.invalid/o/r/pull/1', calls[0].args[-1])
        data = a.load('daily')
        del data['deliveries'][0]['commented']
        a.write(a.path_for('daily'), data)
        with patch('herdworks.hc.get', return_value={'state': 'exited'}), patch('herdworks.automations.gh', return_value='{"comments": [{"body": "<!-- herdworks:daily:key -->"}]}') as gh:
            a.tick(1180)
        self.assertFalse(any(c.args[1:3] == ('issue', 'comment') for c in gh.call_args_list))
