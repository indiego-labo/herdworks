import json
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

from herdworks import hc
from herdworks.cli import main, task_lines
from herdworks.home import sandbox_setting
from herdworks.limits import config, role_settings
from herdworks.pickup import close, stop, tidy
from herdworks.projects import new_task
from herdworks.runs import ROOT, append_event, git
from tests.support import RunCase


class HostTests(RunCase):
    def test_sandbox_modes_on_linux_and_mac(self):
        for platform in ('linux', 'darwin'):
            for sandbox in ('on', 'off'):
                (self.home / 'config.json').write_text(json.dumps(dict(sandbox=sandbox)))
                for mode in ('coordinator', 'worker', 'verify'):
                    with self.subTest(platform=platform, sandbox=sandbox, mode=mode), \
                            patch.object(sys, 'argv', ['hw-codex', mode]), \
                            patch.object(sys, 'platform', platform), \
                            patch('os.execvp') as execute, patch('os.getcwd', return_value=str(self.repo)):
                        runpy.run_path(str(ROOT / 'bin/hw-codex'), run_name='__main__')
                        args = execute.call_args.args[1]
                        self.assertEqual('--dangerously-bypass-approvals-and-sandbox' in args, sandbox == 'off')
                        if sandbox == 'off':
                            self.assertNotIn('--approve-for-me', args)
                            self.assertNotIn('-s', args)
                        elif mode == 'worker':
                            self.assertIn('--approve-for-me', args)
                            if platform == 'linux':
                                self.assertIn(str(self.repo / '.git'), args)
                        else:
                            self.assertEqual(args[args.index('-s') + 1], 'workspace-write')
                            self.assertEqual(args[args.index('-a') + 1], 'never')
                self.assertEqual(role_settings(self.project, 'build')['sandboxed'], sandbox == 'on')

    def test_opencode_uses_known_host_installation_without_path_entry(self):
        from herdworks.projects import grant_project
        grant_project(self.project, unsandboxed=True)
        (self.home / 'config.json').write_text(json.dumps(dict(
            agents={'coordinator': dict(agent='opencode', model='deepseek/deepseek-flash')})))
        cwd = self.project / 'coordinator'
        expected = str(Path.home() / '.opencode/bin/opencode')
        with patch.dict(os.environ), patch.object(sys, 'argv', ['hw-opencode', 'coordinator']), \
                patch('os.getcwd', return_value=str(cwd)), patch('os.execv') as execute, \
                patch('shutil.which', side_effect=lambda name: '/bin/hc' if name == 'hc' else None), \
                patch('os.access', return_value=True):
            runpy.run_path(str(ROOT / 'bin/hw-opencode'), run_name='__main__')
        self.assertEqual(execute.call_args.args, (expected, [expected, '--standalone', '--auto']))

    def test_sandbox_validation_and_default(self):
        self.assertEqual(config()['sandbox'], 'on')
        for invalid in (False, None, 1, 'OFF', [], {}):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'sandbox'):
                sandbox_setting(dict(sandbox=invalid))

    def test_role_refused_on_linux_before_task_or_launch(self):
        with patch('herdworks.projects.sys.platform', 'linux'), patch('herdworks.hc.call') as call:
            with self.assertRaisesRegex(ValueError, '--role.*Linux'):
                new_task(self.project, self.brief, roles={'build': '/bin/true'})
            with self.assertRaisesRegex(RuntimeError, '--role'):
                hc.launch(name='bad', cwd=self.repo, template='none', task='none',
                          identity='bad', role='build', program='/bin/true')
            call.assert_not_called()
        self.assertFalse((self.project / 'tasks/HE-2').exists())

    def worktree(self, name, branch=None):
        wt = self.path / name / 'wt'
        wt.parent.mkdir()
        args = ['worktree', 'add', '-b', branch] if branch else ['worktree', 'add', '--detach']
        git(self.repo, *args, wt, 'HEAD')
        return wt

    def test_task_close_removes_only_finished_task_worktrees(self):
        builder = self.worktree('build-1', 'hw/HE-1')
        verifier = self.worktree('verify-1')
        (builder / 'untracked').write_text('left behind')
        artifact = builder.parent / 'report.md'
        artifact.write_text('retained report')
        other = self.root / 'other-worktree'
        git(self.repo, 'worktree', 'add', '--detach', other, 'HEAD')
        memory = self.project / 'memory/retained.md'
        memory.write_text('memory')
        append_event(self.path, dict(event='stop'))
        with patch('herdworks.hc.get', return_value=dict(state='finished')):
            self.assertEqual(main(['task', 'close', 'unit', 'HE-1']), 0)
            self.assertEqual(close(self.path), [])
        self.assertFalse(builder.exists())
        self.assertFalse(verifier.exists())
        self.assertTrue(other.exists())
        self.assertTrue(artifact.exists())
        self.assertTrue(memory.exists())
        self.assertTrue((self.path / 'task.json').exists())
        self.assertTrue((self.repo / '.git').exists())
        self.assertEqual(git(self.repo, 'rev-parse', 'hw/HE-1'), git(self.repo, 'rev-parse', 'HEAD'))

    def test_close_refuses_unfinished_live_and_unregistered_folders(self):
        wt = self.worktree('build-1', 'hw/HE-1')
        with self.assertRaisesRegex(ValueError, 'finished'):
            close(self.path)
        append_event(self.path, dict(event='session', address='owned', role='build'))
        append_event(self.path, dict(event='stop'))
        with patch('herdworks.hc.get', return_value=dict(state='live')):
            with self.assertRaisesRegex(ValueError, 'live workers'):
                close(self.path)
        self.assertTrue(wt.exists())
        git(self.repo, 'worktree', 'remove', '--force', wt)
        wt.mkdir()
        with patch('herdworks.hc.get', return_value=dict(state='finished')):
            with self.assertRaisesRegex(ValueError, 'unregistered'):
                close(self.path)
        self.assertTrue(wt.exists())

    def test_stop_removes_worktrees_and_keeps_unfinished_files(self):
        builder = self.worktree('build-1', 'hw/HE-1')
        (builder / 'draft.txt').write_text('half done')
        with patch('herdworks.hc.sessions', return_value=[]):
            stop(self.path)
        self.assertFalse(builder.exists())
        self.assertIn('half done', (builder.parent / 'unsaved.patch').read_text())
        self.assertEqual(git(self.repo, 'rev-parse', 'hw/HE-1'), git(self.repo, 'rev-parse', 'HEAD'))

    def test_stop_is_recorded_even_when_a_folder_cannot_be_removed(self):
        stray = self.path / 'build-1/wt'
        stray.mkdir(parents=True)
        with patch('herdworks.hc.sessions', return_value=[]):
            stop(self.path)
        from herdworks.runs import events, is_stopped
        self.assertTrue(is_stopped(self.path))
        self.assertIn('unregistered', events(self.path)[-1]['worktree_error'])
        self.assertTrue(stray.exists())

    def test_tidy_closes_merged_and_closed_pull_requests_only(self):
        from herdworks.runs import events
        builder = self.worktree('build-1', 'hw/HE-1')
        git(builder, 'commit', '--allow-empty', '-m', 'test: build')
        commit = git(builder, 'rev-parse', 'HEAD')
        (builder.parent / 'report.md').write_text(f'READY {commit}\n')
        append_event(self.path, dict(event='session', role='build', folder='build-1', address='owned'))
        append_event(self.path, dict(event='pr', url='https://github.com/o/r/pull/1', commit='x'))
        second, _ = new_task(self.project, self.brief)
        append_event(second, dict(event='pr', url='https://github.com/o/r/pull/2', commit='y'))
        states = {'https://github.com/o/r/pull/1': 'MERGED', 'https://github.com/o/r/pull/2': 'OPEN'}
        with patch('herdworks.pickup.pr_state', side_effect=lambda project, url: states[url]), \
                patch('herdworks.hc.get', return_value=dict(state='missing')):
            self.assertEqual(tidy(self.project),
                             ['HE-1 reclaimed 1 worktrees', 'HE-1 closed: pull request merged'])
            self.assertEqual(tidy(self.project), [])
        self.assertFalse(builder.exists())
        self.assertEqual(events(self.path)[-1]['reason'], 'pull request merged')
        self.assertFalse(any(e.get('event') == 'closed' for e in events(second)))
        with patch('herdworks.cli.probe', return_value=[]):
            listed = list(task_lines(self.project))
        self.assertEqual([line.split()[0] for line in listed], [second.name])

    def test_tidy_reports_a_pull_request_it_cannot_check(self):
        append_event(self.path, dict(event='pr', url='https://github.com/o/r/pull/1', commit='x'))
        with patch('herdworks.pickup.pr_state', side_effect=RuntimeError('no network')):
            self.assertEqual(tidy(self.project), ['HE-1 not tidied: no network'])

    def test_tidy_clears_worktrees_left_by_an_older_stop(self):
        builder = self.worktree('build-1', 'hw/HE-1')
        append_event(self.path, dict(event='session', role='build', folder='build-1', address='owned'))
        append_event(self.path, dict(event='stop'))
        with patch('herdworks.hc.get', return_value=dict(state='missing')):
            self.assertEqual(tidy(self.project), ['HE-1 reclaimed 1 worktrees'])
        self.assertFalse(builder.exists())
