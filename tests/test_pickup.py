import json
from unittest.mock import patch
from herdworks.pickup import stop, tidy
from herdworks.runs import append_event, derive_status, git
from tests.support import RunCase


class StopTests(RunCase):
    def test_stop_only_ends_this_tasks_workers(self):
        sessions = [dict(address=n) for n in ('worker', 'coordinator', 'foreign')]
        def get(address):
            labels = {'worker': 'unit:HE-1', 'coordinator': 'project:unit', 'foreign': 'other:HE-1'}
            return dict(address=address, name=address, state='live', labels=dict(hw=labels[address]))
        with patch('herdworks.hc.sessions', return_value=sessions), patch('herdworks.hc.get', side_effect=get), patch('herdworks.hc.call') as call:
            self.assertEqual(stop(self.path), ['worker'])
            call.assert_called_once_with('kill', 'worker')
        self.assertEqual(derive_status(self.path), 'stopped')


class ReclaimTests(RunCase):
    def checkout(self, name, *, record=True):
        wt = self.path / name / 'wt'
        wt.parent.mkdir()
        sha = git(self.repo, 'rev-parse', 'HEAD')
        git(self.repo, 'worktree', 'add', '--detach', wt, sha)
        if record:
            append_event(self.path, dict(event='session', role='verify', folder=name,
                                         address=name, commit=sha))
        return wt

    def test_generated_dirs_are_opt_in_and_only_allow_ignored_directory_contents(self):
        names = ('generated', 'private', 'untracked', 'similar', 'symlink', 'file', 'changed')
        worktrees = {name: self.checkout(f'verify-{n}') for n, name in enumerate(names, 1)}
        ignores = self.root / 'ignores'
        git(self.repo, 'config', 'core.excludesFile', ignores)
        ignores.write_text('/node_modules\n/.cache/*.bin\n/.env.local\n/node_modules-extra/\n')
        for name, wt in worktrees.items():
            (wt.parent / 'verdict.md').write_text('PASS\n')
            if name not in ('symlink', 'file'):
                (wt / 'node_modules').mkdir()
                (wt / 'node_modules' / 'dependency').touch()
        (worktrees['generated'] / '.cache').mkdir()
        (worktrees['generated'] / '.cache' / 'line\nbreak.bin').touch()
        (worktrees['private'] / '.env.local').touch()
        (worktrees['untracked'] / '.cache').mkdir()
        (worktrees['untracked'] / '.cache' / 'untracked.txt').touch()
        (worktrees['similar'] / 'node_modules-extra').mkdir()
        (worktrees['similar'] / 'node_modules-extra' / 'local-data').touch()
        (worktrees['symlink'] / 'node_modules').symlink_to(self.repo, target_is_directory=True)
        (worktrees['file'] / 'node_modules').touch()
        (worktrees['changed'] / 'hello.py').write_text('local change\n')

        config = self.project / 'project.json'
        data = json.loads(config.read_text())
        with patch('herdworks.hc.get', return_value=dict(state='missing')):
            self.assertEqual(tidy(self.project), [])
            config.write_text(json.dumps(dict(data, generated_worktree_dirs=['../repo'])))
            self.assertIn('generated_worktree_dirs must be', tidy(self.project)[0])
            self.assertTrue(all(wt.exists() for wt in worktrees.values()))
            config.write_text(json.dumps(dict(data, generated_worktree_dirs=['node_modules', '.cache'])))
            self.assertEqual(tidy(self.project), ['HE-1 reclaimed 1 worktrees'])
            self.assertEqual(tidy(self.project), [])
        self.assertFalse(worktrees['generated'].exists())
        self.assertTrue(all(worktrees[name].exists() for name in names[1:]))
        self.assertTrue((self.repo / 'hello.py').exists())

    def test_tidy_reclaims_only_clean_ended_workers_with_artifacts(self):
        names = ('finished', 'active', 'idle', 'dirty', 'ignored', 'needed', 'foreign', 'moved', 'locked')
        worktrees = {name: self.checkout(f'verify-{n}', record=name != 'foreign')
                     for n, name in enumerate(names, 1)}
        for name, wt in worktrees.items():
            if name != 'needed':
                (wt.parent / 'verdict.md').write_text('PASS\n')
        (worktrees['dirty'] / 'hello.py').write_text('uncommitted\n')
        git(self.repo, 'config', 'core.excludesFile', self.root / 'ignores')
        (self.root / 'ignores').write_text('local-data\n')
        (worktrees['ignored'] / 'local-data').write_text('ignored content\n')
        git(worktrees['moved'], 'commit', '--allow-empty', '-m', 'test: detached work')
        git(self.repo, 'worktree', 'lock', worktrees['locked'])

        def get(address):
            if address in ('verify-2', 'verify-3'):
                return dict(state='live', status='working' if address == 'verify-2' else 'idle')
            return dict(state='missing')

        with patch('herdworks.hc.get', side_effect=get):
            self.assertEqual(tidy(self.project), ['HE-1 reclaimed 1 worktrees'])
            self.assertEqual(tidy(self.project), [])
        self.assertFalse(worktrees['finished'].exists())
        self.assertTrue((worktrees['finished'].parent / 'verdict.md').is_file())
        self.assertTrue(all(worktrees[name].exists() for name in names[1:]))

    def test_tidy_does_not_force_removal_when_a_pull_request_ended(self):
        wt = self.checkout('verify-1')
        (wt.parent / 'verdict.md').write_text('PASS\n')
        (wt / 'untracked').write_text('keep this\n')
        append_event(self.path, dict(event='pr', url='fixture', commit='x'))
        with patch('herdworks.pickup.pr_state', return_value='MERGED'), \
                patch('herdworks.hc.get', return_value=dict(state='missing')):
            self.assertIn('worker folders retained', tidy(self.project)[0])
        self.assertEqual((wt / 'untracked').read_text(), 'keep this\n')
