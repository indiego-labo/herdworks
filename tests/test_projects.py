import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch
from herdworks.home import hw_home
from herdworks.projects import (add_github_project, add_project, clone_github, new_task,
                                project_path, read_project, repository_slug, task_path, task_paths)
from herdworks.runs import git, read_task
from tests.support import RunCase


class ProjectTests(RunCase):
    def test_home_default_and_override(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(hw_home(), __import__('pathlib').Path.home() / '.herdworks')
        self.assertEqual(hw_home(), self.home)

    def test_project_folders_metadata_and_rejections(self):
        project = add_project('hello', self.repo)
        self.assertEqual(read_project(project), dict(name='hello', repo=str(self.repo), base_branch='main', prefix='HE',
                                                  remote='origin', grants={'push': False, 'draft-pr': False}))
        for folder in ('memory', 'tasks', 'coordinator', 'coordinator/outbox'):
            self.assertTrue((project / folder).is_dir())
        with self.assertRaisesRegex(ValueError, 'already exists'):
            add_project('hello', self.repo)
        for name in ('abcdefghijklm', '../escape', '', 'UPPER'):
            with self.assertRaises(ValueError):
                project_path(name)

    def test_task_ids_rise_and_notes_are_inside_coordinator(self):
        second, repeat = new_task(self.project, self.brief)
        self.assertFalse(repeat)
        self.assertEqual([self.path.name, second.name], ['HE-1', 'HE-2'])
        self.assertEqual(read_task(second)['branch'], 'hw/HE-2')
        self.assertTrue((self.project / 'coordinator/tasks/HE-2').is_dir())
        self.assertEqual((second / 'events.jsonl').read_text(), '')
        for value in ('HE-0', 'OTHER-1', '../escape'):
            with self.assertRaises(ValueError):
                task_path('unit', value)
        self.assertFalse((self.root / 'runs').exists())

    def test_replayed_message_reuses_task(self):
        (self.project / 'inbox.jsonl').write_text(json.dumps(dict(number=1, text='do this')) + '\n')
        first, repeat = new_task(self.project, message=1)
        again, repeat = new_task(self.project, message=1)
        self.assertEqual(again, first)
        self.assertTrue(repeat)
        self.assertEqual(first.name, 'HE-2')
        self.assertEqual((first / 'brief.md').read_text(), 'do this')

    def test_dirty_repository_does_not_allocate_task(self):
        (self.repo / 'pending').touch()
        with self.assertRaisesRegex(ValueError, 'clean'):
            new_task(self.project, self.brief)
        self.assertFalse((self.project / 'tasks/HE-2').exists())

    def test_incomplete_task_setup_is_not_counted_as_a_task(self):
        pending = self.project / 'tasks/.HE-2-pending'
        pending.mkdir()
        (pending / 'task.json').write_text('{}')
        second, _ = new_task(self.project, self.brief)
        self.assertEqual(second.name, 'HE-2')
        self.assertFalse(pending.exists())

    def test_task_ids_have_no_added_numeric_cap(self):
        self.assertEqual(task_path('unit', 'HE-1000000').name, 'HE-1000000')

    def test_interrupted_project_creation_is_hidden_and_retryable(self):
        from pathlib import Path
        write = Path.write_text
        seen = []
        def interrupt(path, *args, **kwargs):
            if path.name == 'project.json' and 'hello' in path.parent.name:
                seen.append(project_path('hello').exists())
                raise OSError('interrupted creation')
            return write(path, *args, **kwargs)
        with patch.object(Path, 'write_text', interrupt):
            with self.assertRaisesRegex(OSError, 'interrupted creation'):
                add_project('hello', self.repo)
        self.assertEqual(seen, [False])
        self.assertFalse(project_path('hello').exists())
        project = add_project('hello', self.repo)
        self.assertEqual(read_project(project)['name'], 'hello')
        self.assertTrue((project / 'coordinator/outbox').is_dir())

    def attach_remote(self):
        remote = self.root / 'remote.git'
        git(self.root, 'clone', '--bare', '--quiet', str(self.repo), str(remote))
        git(self.repo, 'remote', 'add', 'origin', str(remote))
        return remote

    def test_new_task_starts_from_the_latest_remote_base(self):
        remote = self.attach_remote()
        other = self.root / 'other'
        git(self.root, 'clone', '--quiet', str(remote), str(other))
        git(other, 'config', 'user.email', 'test@example.invalid')
        git(other, 'config', 'user.name', 'Fixture')
        (other / 'pushed.txt').write_text('a push to GitHub\n')
        git(other, 'add', '.')
        git(other, 'commit', '-m', 'test: a push to GitHub')
        pushed = git(other, 'rev-parse', 'HEAD')
        git(other, 'push', '--quiet', 'origin', 'main')
        self.assertNotEqual(git(self.repo, 'rev-parse', 'refs/heads/main'), pushed)
        task, _ = new_task(self.project, self.brief)
        data = read_task(task)
        self.assertEqual(data['base'], pushed)
        self.assertEqual(data['base_branch'], 'main')
        self.assertIn('refs/remotes/origin/main',
                      git(self.repo, 'for-each-ref', '--format=%(refname)').splitlines())

    def test_message_base_starts_the_task_from_that_branch(self):
        self.attach_remote()
        git(self.repo, 'branch', 'feature/x')
        git(self.repo, 'push', '--quiet', 'origin', 'feature/x')
        pushed = git(self.repo, 'rev-parse', 'feature/x')
        (self.project / 'inbox.jsonl').write_text(
            json.dumps(dict(number=1, text='backport it', at=1, base='feature/x')) + '\n')
        second, _ = new_task(self.project, message=1)
        data = read_task(second)
        self.assertEqual(data['base_branch'], 'feature/x')
        self.assertEqual(data['base'], pushed)

    def test_unknown_or_malformed_base_branch_allocates_no_task(self):
        self.attach_remote()
        for base, message in (('feature/missing', 'not on origin'), ('bad..name', 'valid branch')):
            with self.subTest(base=base), self.assertRaisesRegex(ValueError, message):
                new_task(self.project, self.brief, base=base)
        self.assertEqual(len(task_paths(self.project)), 1)

    def test_unreachable_remote_refuses_instead_of_using_a_stale_base(self):
        git(self.repo, 'remote', 'add', 'origin', str(self.root / 'absent.git'))
        with self.assertRaisesRegex(ValueError, 'could not fetch origin'):
            new_task(self.project, self.brief)
        self.assertEqual(len(task_paths(self.project)), 1)


class GitHubProjectTests(RunCase):
    def setUp(self):
        super().setUp()
        self.remote = self.root / 'github.git'
        git(self.root, 'clone', '--bare', '--quiet', str(self.repo), str(self.remote))
        git(self.repo, 'branch', 'feature/x')
        git(self.repo, 'push', '--quiet', str(self.remote), 'main', 'feature/x')
        self.home = self.root / 'gh-home'
        self.gh = self.root / 'fake-gh'
        self.gh.write_text(f'''#!{sys.executable}
import os
import sys
args = sys.argv[1:]
if args[:1] == ['api'] and len(args) > 1 and args[1].startswith('repos/'):
    print(os.environ.get('FAKE_GH_PUSH', 'true'))
elif args[:2] == ['repo', 'view']:
    print(os.environ.get('FAKE_GH_BASE', 'main'))
else:
    raise SystemExit('unsupported fake-gh: ' + ' '.join(args))
''')
        self.gh.chmod(0o755)

    def clone_recorder(self, calls):
        def clone(repository, destination, gh):
            calls.append((repository, str(destination), str(gh)))
            git(self.root, 'clone', '--quiet', str(self.remote), str(destination))
        return clone

    def test_repository_slug_normalizes_what_people_type(self):
        for value in ('owner/repo', 'https://github.com/owner/repo.git',
                      'git@github.com:owner/repo.git', 'ssh://git@github.com/owner/repo'):
            with self.subTest(value=value):
                self.assertEqual(repository_slug(value), 'owner/repo')
        for value in ('owner', 'owner/repo/extra', '../escape', 'https://gitlab.com/owner/repo'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'owner/repo'):
                repository_slug(value)

    def test_add_clones_checks_push_and_sets_grants(self):
        calls = []
        with patch('herdworks.projects.clone_github', side_effect=self.clone_recorder(calls)):
            project = add_github_project('demo', 'https://github.com/owner/repo.git',
                                         home=self.home, gh=str(self.gh))
        self.assertEqual(len(calls), 1)
        repository, staging, gh = calls[0]
        self.assertEqual((repository, gh), ('owner/repo', str(self.gh)))
        self.assertEqual(Path(staging).parent, self.home / 'repos/owner')
        self.assertTrue(Path(staging).name.startswith('.demo-clone-'))
        data = read_project(project)
        self.assertEqual(data['repo'], str(self.home / 'repos/owner/repo'))
        self.assertEqual(data['base_branch'], 'main')
        self.assertEqual(data['remote'], 'origin')
        self.assertEqual(data['grants'], {'push': True, 'draft-pr': True, 'unsandboxed': True})
        self.assertEqual(git(data['repo'], 'rev-parse', 'refs/heads/main'),
                         git(self.repo, 'rev-parse', 'refs/heads/main'))

    def test_add_uses_an_explicit_base_branch(self):
        with patch('herdworks.projects.clone_github', side_effect=self.clone_recorder([])):
            project = add_github_project('demo', 'owner/repo', base='feature/x',
                                         home=self.home, gh=str(self.gh))
        data = read_project(project)
        self.assertEqual(data['base_branch'], 'feature/x')
        self.assertEqual(git(data['repo'], 'rev-parse', 'refs/heads/feature/x'),
                         git(self.remote, 'rev-parse', 'refs/heads/feature/x'))

    def test_add_refuses_an_account_without_push_access_and_leaves_nothing(self):
        with patch.dict(os.environ, FAKE_GH_PUSH='false'), \
                patch('herdworks.projects.clone_github') as clone:
            with self.assertRaisesRegex(ValueError, 'cannot push'):
                add_github_project('demo', 'owner/repo', home=self.home, gh=str(self.gh))
        clone.assert_not_called()
        self.assertFalse((self.home / 'projects/demo').exists())
        self.assertFalse((self.home / 'repos/owner/repo').exists())

    def test_add_refuses_when_gh_is_missing(self):
        with patch('herdworks.projects.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'gh auth login'):
                add_github_project('demo', 'owner/repo', home=self.home)
        self.assertFalse((self.home / 'projects/demo').exists())

    def test_add_removes_the_clone_when_the_project_cannot_be_made(self):
        with patch.dict(os.environ, FAKE_GH_BASE='release/nope'), \
                patch('herdworks.projects.clone_github', side_effect=self.clone_recorder([])):
            with self.assertRaisesRegex(ValueError, 'is not on owner/repo'):
                add_github_project('demo', 'owner/repo', home=self.home, gh=str(self.gh))
        self.assertFalse((self.home / 'projects/demo').exists())
        self.assertFalse((self.home / 'repos/owner/repo').exists())
        self.assertEqual(list((self.home / 'repos/owner').iterdir()), [])

    def test_add_removes_project_and_clone_when_grants_are_refused(self):
        with patch('herdworks.projects.clone_github', side_effect=self.clone_recorder([])), \
                patch('herdworks.projects.grant_project', side_effect=ValueError('owner only')):
            with self.assertRaisesRegex(ValueError, 'owner only'):
                add_github_project('demo', 'owner/repo', home=self.home, gh=str(self.gh))
        self.assertFalse((self.home / 'projects/demo').exists())
        self.assertFalse((self.home / 'repos/owner/repo').exists())
        self.assertEqual(list((self.home / 'repos/owner').iterdir()), [])

    def test_clone_uses_https_and_ghs_sign_in(self):
        with patch('herdworks.projects.subprocess.run') as run:
            run.return_value = types.SimpleNamespace(returncode=0, stdout='', stderr='')
            clone_github('owner/repo', self.root / 'dest', '/opt/gh')
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ['git', '-c', 'credential.helper=', '-c'])
        self.assertEqual(args[4], 'credential.helper=!/opt/gh auth git-credential')
        self.assertEqual(args[5:7], ['clone', '--quiet'])
        self.assertEqual(args[7], 'https://github.com/owner/repo.git')
        self.assertEqual(args[8], str(self.root / 'dest'))

    def test_clone_failure_says_the_url_and_reason(self):
        with patch('herdworks.projects.subprocess.run') as run:
            run.return_value = types.SimpleNamespace(
                returncode=1, stdout='', stderr='remote: Repository not found.\nfatal: clone failed')
            with self.assertRaisesRegex(ValueError,
                                        'clone of https://github.com/owner/repo.git failed: fatal: clone failed'):
                clone_github('owner/repo', self.root / 'dest', '/opt/gh')
