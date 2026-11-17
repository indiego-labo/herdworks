import contextlib
import io
import os
from unittest.mock import patch
from herdworks.cli import main
from herdworks.projects import add_project, new_task, task_paths
from herdworks.runs import events
from tests.support import RunCase


class AuthorizationTests(RunCase):
    def caller(self):
        return dict(address='t-owner', state='live', cwd=str(self.project / 'coordinator'),
                    labels=dict(hw='project:unit', role='coordinator'))

    def test_coordinator_cannot_say_create_or_stop_in_another_project(self):
        other = add_project('other', self.repo, prefix='OT')
        task, _ = new_task(other, self.brief)
        before = (other / 'inbox.jsonl').read_bytes(), list(task_paths(other)), events(task)
        with patch.dict(os.environ, HW_CALLER_TERMINAL='t-owner'), patch('herdworks.hc.get', return_value=self.caller()), patch('herdworks.hc.call') as call:
            for args in (['say', 'other', 'intrude'], ['task', 'new', 'other', '--brief', str(self.brief)], ['stop', 'other', 'OT-1']):
                with self.subTest(command=args), contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(main(args), 1)
                    self.assertIn('caller', error.getvalue())
            call.assert_not_called()
        self.assertEqual(before, ((other / 'inbox.jsonl').read_bytes(), list(task_paths(other)), events(task)))

    def test_own_project_is_allowed_and_install_is_refused(self):
        with patch.dict(os.environ, HW_CALLER_TERMINAL='t-owner'), patch('herdworks.hc.get', return_value=self.caller()), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['task', 'new', 'unit', '--brief', str(self.brief)]), 0)
            self.assertIn('HE-2', output.getvalue())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['install']), 1)

    def test_missing_worker_or_mismatched_folder_identity_is_refused(self):
        for caller in (dict(state='missing'), dict(self.caller(), labels=dict(hw='unit:HE-1', role='build')),
                       dict(self.caller(), cwd=str(self.root))):
            with self.subTest(caller=caller), patch.dict(os.environ, HW_CALLER_TERMINAL='t-owner'), patch('herdworks.hc.get', return_value=caller), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['task', 'new', 'unit', '--brief', str(self.brief)]), 1)
        self.assertEqual(len(task_paths(self.project)), 1)

    def test_builder_memory_hop_is_limited_to_its_project_task_and_folder(self):
        caller = dict(address='t-builder', state='live', cwd=str(self.path / 'build-1/wt'),
                      labels=dict(hw='unit:HE-1', role='build'))
        with patch.dict(os.environ, HW_CALLER_TERMINAL='t-builder'), patch('herdworks.hc.get', return_value=caller), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['memory', 'add', 'unit', '--task', 'HE-1', '--title', 'Tests', '--text', 'python3 -m unittest']), 0)
            self.assertEqual(main(['memory', 'read', 'unit']), 0)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['memory', 'add', 'unit', '--task', 'HE-2', '--title', 'No', '--text', 'No']), 1)
                self.assertEqual(main(['memory', 'read', 'other']), 1)
                self.assertEqual(main(['project', 'grant', 'unit', '--unsandboxed']), 1)
        caller['cwd'] = str(self.root)
        with patch.dict(os.environ, HW_CALLER_TERMINAL='t-builder'), patch('herdworks.hc.get', return_value=caller), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['memory', 'read', 'unit']), 1)


class OwnerAncestryTests(RunCase):
    def test_unset_markers_cannot_change_automations_or_grants(self):
        from herdworks import automations
        from herdworks.projects import grant_project
        automations.add('daily', 'unit', 'owner', 'schedule', 'Check status')
        config = automations.path_for('daily').read_bytes()
        project = (self.project / 'project.json').read_bytes()
        ancestry = {100: 'python3 /checkout/bin/hw automation off daily', 50: '/bin/sh', 20: 'opencode'}
        terminal = dict(state='live', pid=20, labels={'hw': 'unit:HE-1'})
        with patch.dict(os.environ):
            for key in ('HW_CALLER_TERMINAL', 'HW_HC_HOP', 'HC_TERMINAL_ID'):
                os.environ.pop(key, None)
            with patch('herdworks.hc.caller_ancestry', return_value=ancestry, create=True), \
                    patch('herdworks.hc.sessions', return_value=[{'address': 't-worker'}]), \
                    patch('herdworks.hc.get', return_value=terminal):
                commands = [['automation', 'off', 'daily'], ['automation', 'on', 'daily'],
                            ['automations', 'tick'], ['project', 'grant', 'unit', '--push'],
                            ['automation', 'add', 'intruder', '--project', 'unit', '--owner', 'worker',
                             '--trigger', 'schedule', '--instructions', 'Check status']]
                for args in commands:
                    with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()) as output:
                        self.assertEqual(main(args), 1)
                        self.assertIn('owner outside Herdworks sessions', output.getvalue())
                with self.assertRaisesRegex(ValueError, 'owner outside Herdworks sessions'):
                    grant_project(self.project, push=True)
        self.assertEqual(automations.path_for('daily').read_bytes(), config)
        self.assertEqual((self.project / 'project.json').read_bytes(), project)
        self.assertFalse(automations.path_for('intruder').exists())

    def test_factory_launcher_ancestor_is_refused_without_terminal_labels(self):
        from herdworks.projects import grant_project
        for launcher in ('hw-opencode', 'hw-codex'):
            ancestry = {100: 'python3 /checkout/bin/hw', 20: f'/Frameworks/Python -u /checkout/bin/{launcher} worker'}
            with self.subTest(launcher=launcher), patch.dict(os.environ):
                for key in ('HW_CALLER_TERMINAL', 'HW_HC_HOP', 'HC_TERMINAL_ID'):
                    os.environ.pop(key, None)
                with patch('herdworks.hc.caller_ancestry', return_value=ancestry, create=True), patch('herdworks.hc.sessions', return_value=[]):
                    with self.assertRaisesRegex(ValueError, 'owner outside Herdworks sessions'):
                        grant_project(self.project, push=True)

    def test_owner_shell_can_change_automation(self):
        from herdworks import automations
        automations.add('daily', 'unit', 'owner', 'schedule', 'Check status')
        with patch.dict(os.environ):
            for key in ('HW_CALLER_TERMINAL', 'HW_HC_HOP', 'HC_TERMINAL_ID'):
                os.environ.pop(key, None)
            with patch('herdworks.hc.caller_ancestry', return_value={100: 'python3 /checkout/bin/hw', 20: '/bin/zsh'}, create=True), \
                    patch('herdworks.hc.sessions', return_value=[{'address': 'unrelated'}]), \
                    patch('herdworks.hc.get', return_value=dict(pid=999, labels={'hw': 'project:other'})), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['automation', 'off', 'daily']), 0)
        self.assertFalse(automations.load('daily')['enabled'])

    def test_process_table_walks_ancestors(self):
        from herdworks import hc
        from types import SimpleNamespace
        table = '100 50 python3 /checkout/bin/hw\n50 20 /bin/sh\n20 1 python3 -u /checkout/bin/hw-opencode worker\n1 0 /sbin/init\n'
        with patch('herdworks.hc.os.getpid', return_value=100), patch('herdworks.hc.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=table)):
            self.assertEqual(list(hc.caller_ancestry()), [100, 50, 20, 1])
        with patch('herdworks.hc.os.getpid', return_value=999), patch('herdworks.hc.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=table)):
            with self.assertRaisesRegex(RuntimeError, 'complete owner process ancestry'):
                hc.caller_ancestry()

    def test_unavailable_ancestry_refuses_mutation(self):
        from herdworks import automations
        automations.add('daily', 'unit', 'owner', 'schedule', 'Check status')
        with patch.dict(os.environ):
            for key in ('HW_CALLER_TERMINAL', 'HW_HC_HOP', 'HC_TERMINAL_ID'):
                os.environ.pop(key, None)
            with patch('herdworks.hc.caller_ancestry', side_effect=RuntimeError('cannot verify owner process ancestry')), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['automation', 'off', 'daily']), 1)
        self.assertTrue(automations.load('daily')['enabled'])

    def test_forward_refuses_owner_mutations_before_hop(self):
        from herdworks import hc
        with patch('herdworks.hc.subprocess.call') as hop, contextlib.redirect_stderr(io.StringIO()):
            for args in (['automation', 'off', 'daily'], ['automation', 'on', 'daily'],
                         ['automations', 'tick'], ['automation', 'add', 'new'], ['project', 'grant', 'unit']):
                self.assertEqual(hc.forward('bin/hw', args), 1)
        hop.assert_not_called()
