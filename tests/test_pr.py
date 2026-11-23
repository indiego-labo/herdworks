import hashlib
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
from unittest.mock import patch
from herdworks.cli import main, task_lines
from herdworks.gate import check_gate
from herdworks.pr import open_pr, repository_identity
from herdworks.projects import grant_project, read_project
from herdworks.runs import derive_status, events, git
from tests.support import GateCase, write_claims


class PRTests(GateCase):
    def setUp(self):
        super().setUp()
        self.remote = self.root / 'remote.git'
        git(self.root, 'init', '--bare', self.remote)
        git(self.repo, 'remote', 'add', 'origin', self.remote)
        self.fake = Path(__file__).resolve().parents[1] / 'fixtures/hello/planted/fake-gh.sh'
        self.log = self.root / 'fake-gh.jsonl'
        self.environment_owner = patch.dict(os.environ, CODEX_SANDBOX='', HC_TERMINAL_ID='')
        self.environment_owner.start()
        self.addCleanup(self.environment_owner.stop)
        grant_project(self.project, True, True, gh=str(self.fake))
        self.commands = self.verify / 'evidence/commands.json'
        self.commands.write_text(json.dumps([
            dict(command='python3 hello.py Ada', output='Hello, Ada!\n')]))

    def assert_no_external_effect(self):
        self.assertFalse(self.log.exists())
        self.assertEqual(git(self.remote, 'for-each-ref', '--format=%(refname)'), '')

    def select_visuals(self, *entries, unavailable=()):
        media = []
        for name, content, caption, source in entries:
            (self.commands.parent / name).write_bytes(content)
            media.append(dict(file=name, caption=caption, source=source,
                              sha256=hashlib.sha256(content).hexdigest()))
        (self.review / 'visuals.json').write_text(json.dumps(dict(media=media, unavailable=list(unavailable))))
        (self.review / 'review.md').touch()

    def test_existing_grant_publishes_inline_images_and_motion_on_older_gh(self):
        self.select_visuals(('result.png', b'screenshot bytes', 'After submitting', 'live'),
                            ('flow.gif', b'preview bytes', 'Fixture interaction', 'stand-in'),
                            ('flow.mp4', b'video bytes', 'Original recording', 'live'))
        with patch('herdworks.pr.repository_identity', return_value='github.com/fixture/hello'):
            open_pr(self.path)
        call = json.loads(self.log.read_text())
        self.assertFalse(call['isDraft'])
        self.assertNotIn('--attach', call['args'])
        ref = git(self.remote, 'for-each-ref', '--format=%(refname)', 'refs/tags/hw-evidence')
        media_commit = git(self.remote, 'rev-parse', ref)
        self.assertIn(f'![After submitting](../blob/{media_commit}/visual-1.png?raw=true)', call['body'])
        self.assertIn(f'![Stand-in: Fixture interaction](../blob/{media_commit}/visual-2.gif?raw=true)', call['body'])
        self.assertIn('Original recording stayed in Project evidence', call['body'])
        self.assertEqual(git(self.remote, 'ls-tree', '--name-only', media_commit), 'visual-1.png\nvisual-2.gif')
        self.assertEqual(git(self.remote, 'show', f'{media_commit}:visual-1.png'), 'screenshot bytes')
        self.assertEqual(git(self.remote, 'show', f'{media_commit}:visual-2.gif'), 'preview bytes')
        self.assertEqual(git(self.remote, 'rev-parse', 'refs/heads/hw/HE-1'), self.sha)

    def test_native_attachments_render_video_and_screenshot_with_captions(self):
        (self.root / 'fake-gh-attachments').touch()
        self.select_visuals(('result.png', b'screenshot bytes', 'After submitting', 'live'),
                            ('flow.mp4', b'video bytes', 'Fixture interaction', 'stand-in'))
        with patch('herdworks.pr.repository_identity', return_value='github.com/fixture/hello'):
            open_pr(self.path)
        call = json.loads(self.log.read_text())
        self.assertFalse(call['isDraft'])
        self.assertIn('![After submitting](https://github.invalid/user-attachments/assets/visual-1.png)', call['body'])
        self.assertIn('Stand-in: Fixture interaction\n\nhttps://github.invalid/user-attachments/assets/visual-2.mp4',
                      call['body'])
        self.assertEqual(call['assets']['visual-2.mp4'], hashlib.sha256(b'video bytes').hexdigest())
        self.assertEqual(git(self.remote, 'for-each-ref', 'refs/tags/hw-evidence'), '')

    def test_manual_pr_discloses_missing_and_changed_visuals(self):
        self.environment_verdict()
        self.select_visuals(('result.png', b'approved bytes', 'After submitting', 'live'),
                            unavailable=['Target device video was unavailable.'])
        (self.commands.parent / 'result.png').write_bytes(b'modified bytes')
        open_pr(self.path, manual_verification=True)
        call = json.loads(self.log.read_text())
        self.assertFalse(call['isDraft'])
        self.assertIn('Target device video was unavailable.', call['body'])
        self.assertIn('changed after evidence review', call['body'])
        self.assertIn('## Needs manual verification', call['body'])
        self.assertNotIn('![', call['body'])
        self.assertEqual(git(self.remote, 'for-each-ref', 'refs/tags/hw-evidence'), '')

    def test_visual_symlink_is_not_published(self):
        self.select_visuals(('result.png', b'approved bytes', 'After submitting', 'live'))
        outside = self.root / 'outside.png'
        (self.commands.parent / 'result.png').rename(outside)
        (self.commands.parent / 'result.png').symlink_to(outside)
        open_pr(self.path)
        self.assertIn('could not be read', json.loads(self.log.read_text())['body'])
        self.assertEqual(git(self.remote, 'for-each-ref', 'refs/tags/hw-evidence'), '')

    def test_visual_manifest_from_after_review_prevents_publication(self):
        self.select_visuals(('result.png', b'approved bytes', 'After submitting', 'live'))
        manifest = self.review / 'visuals.json'
        later = manifest.stat().st_mtime + 1
        os.utime(manifest, (later, later))
        with self.assertRaisesRegex(ValueError, 'before review.md'):
            open_pr(self.path)
        self.assert_no_external_effect()

    def test_new_project_grants_are_off_and_remote_is_named(self):
        from herdworks.projects import add_project
        project = add_project('other', self.repo)
        self.assertEqual(read_project(project)['grants'], {'push': False, 'draft-pr': False})
        self.assertEqual(read_project(project)['remote'], 'origin')

    def test_refuses_each_missing_grant(self):
        for push, draft_pr, missing in [(False, True, 'push'), (True, False, 'draft-pr'), (False, False, 'push, draft-pr')]:
            with self.subTest(missing=missing):
                grant_project(self.project, push, draft_pr)
                with self.assertRaisesRegex(ValueError, 'has not granted ' + missing):
                    open_pr(self.path)
                self.assert_no_external_effect()

    def test_refuses_current_gate_failures_even_after_saved_pass(self):
        from herdworks.gate import gate
        self.assertTrue(gate(self.path)[0])
        self.verdict.write_text(f'FAIL\nCommit: {self.sha}\n')
        with self.assertRaisesRegex(ValueError, 'gate refused'):
            open_pr(self.path)
        self.assert_no_external_effect()

    def test_changed_head_refuses_push(self):
        (self.repo / 'later').write_text('unverified')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'test: unverified change')
        with self.assertRaisesRegex(ValueError, 'gate refused'):
            open_pr(self.path)
        self.assert_no_external_effect()

    def test_real_push_pr_body_and_second_pr_refusal(self):
        with patch('herdworks.pr.git', wraps=git) as observed:
            url = open_pr(self.path)
        pushes = [c.args for c in observed.call_args_list if c.args[1] == 'push']
        self.assertEqual(pushes, [(str(self.repo), 'push', 'origin', f'{self.sha}:refs/heads/hw/HE-1')])
        self.assertFalse(any('force' in str(arg) or str(arg).startswith('+') for arg in pushes[0][2:]))
        self.assertEqual(git(self.remote, 'rev-parse', 'refs/heads/hw/HE-1'), self.sha)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['args'][:2], ['pr', 'create'])
        self.assertFalse(calls[0]['isDraft'])
        self.assertEqual(calls[0]['args'][calls[0]['args'].index('--repo') + 1], str(self.remote))
        body = calls[0]['body']
        self.assertEqual([line for line in body.splitlines() if line.startswith('## ')],
                         ['## Why', '## Scope', '## Blast Radius', '## Verification'])
        for required in ('ORIGINAL REQUEST', 'PASS', self.sha, 'python3 hello.py Ada', 'Hello, Ada!', 'CONFIRMED'):
            self.assertIn(required, body)
        self.assertEqual(events(self.path)[-1]['url'], url)
        self.assertEqual(derive_status(self.path), 'for review')
        with patch('herdworks.hc.sessions', return_value=[]), patch('herdworks.hc.get', return_value={'state': 'missing'}):
            self.assertIn(f'HE-1 for review {self.sha} {url}', next(task_lines(self.project)))
        with self.assertRaisesRegex(ValueError, 'already opened'):
            open_pr(self.path)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_body_uses_short_command_records_without_dumping_artifacts(self):
        timestamp = self.verdict.stat().st_mtime
        self.verdict.write_text(f'PASS\nCommit: {self.sha}\nVERDICT DETAIL SHOULD STAY LOCAL\n')
        os.utime(self.verdict, (timestamp, timestamp))
        (self.verify / 'evidence/private.txt').write_text('UNRELATED PRIVATE ARTIFACT\n' * 1000)
        (self.verify / 'evidence/nested').mkdir()
        (self.verify / 'evidence/nested/trace.txt').write_text('NESTED TRACE SHOULD STAY LOCAL')
        self.commands.write_text(json.dumps([
            dict(command='python3 hello.py Ada', output='Hello, Ada!\n' + 'verbose detail\n' * 1000),
            dict(command='python3 -m unittest', output='Ran 2 tests\nOK\n')]))
        open_pr(self.path)
        body = json.loads(self.log.read_text())['body']
        for required in ('PASS', self.sha, 'CONFIRMED', 'python3 hello.py Ada',
                         'Hello, Ada!', 'python3 -m unittest', 'OK', 'verify-1/evidence/commands.json'):
            self.assertIn(required, body)
        for private in ('UNRELATED PRIVATE ARTIFACT', 'NESTED TRACE SHOULD STAY LOCAL',
                        'VERDICT DETAIL SHOULD STAY LOCAL'):
            self.assertNotIn(private, body)
        self.assertLess(len(body), 3000)

    def test_https_credentials_are_absent_from_gh_arguments(self):
        def configured_url(repo, *args, **kwargs):
            if args[:2] == ('remote', 'get-url'):
                return 'https://fixture-user:fixture-token@github.com/owner/repository.git'
            return git(repo, *args, **kwargs)
        with patch('herdworks.pr.git', side_effect=configured_url):
            open_pr(self.path)
        args = json.loads(self.log.read_text())['args']
        self.assertEqual(args[args.index('--repo') + 1], 'github.com/owner/repository')
        self.assertNotIn('fixture-token', ' '.join(args))
        self.assertEqual(git(self.remote, 'rev-parse', 'refs/heads/hw/HE-1'), self.sha)

    def test_repository_identity_normalizes_network_remotes(self):
        for address in ('git@github.com:owner/repository.git',
                        'ssh://git:fixture-token@github.com/owner/repository.git',
                        'https://fixture-user:fixture-token@github.com/owner/repository.git?token=fixture-token'):
            with self.subTest(address=address):
                self.assertEqual(repository_identity(address), 'github.com/owner/repository')
        self.assertEqual(repository_identity(str(self.remote)), str(self.remote))
        with self.assertRaisesRegex(ValueError, 'host, owner and repository'):
            repository_identity('https://fixture-user:fixture-token@github.com/owner')

    def test_body_redacts_sensitive_values_in_command_records(self):
        self.commands.write_text(json.dumps([dict(
            command='check --token=fixture-secret',
            output='API_KEY=fixture-key\nAuthorization: Bearer fixture-bearer\nhttps://user:fixture-url@example.invalid/repo')]))
        open_pr(self.path)
        body = json.loads(self.log.read_text())['body']
        for secret in ('fixture-secret', 'fixture-key', 'fixture-bearer', 'fixture-url'):
            self.assertNotIn(secret, body)
        self.assertIn('[REDACTED]', body)

    def test_missing_or_invalid_command_records_prevent_external_effects(self):
        for content in (None, '{}', '[{"command": "check"}]', '[]'):
            with self.subTest(content=content):
                if content is None:
                    self.commands.unlink()
                else:
                    self.commands.write_text(content)
                with self.assertRaises(ValueError):
                    open_pr(self.path)
                self.assert_no_external_effect()

    def test_forwarded_coordinator_cannot_grant_its_own_project(self):
        with patch.dict(os.environ, HW_CALLER_TERMINAL='t-caller'):
            with self.assertRaisesRegex(ValueError, 'owner outside Herdworks sessions'):
                grant_project(self.project, True, True)

    def test_push_disables_hooks(self):
        hooks = self.root / 'hooks'
        hooks.mkdir()
        sentinel = self.root / 'hook-ran'
        hook = hooks / 'pre-push'
        hook.write_text(f'#!/bin/sh\ntouch "{sentinel}"\nexit 1\n')
        hook.chmod(0o755)
        git(self.repo, 'config', 'core.hooksPath', hooks)
        open_pr(self.path)
        self.assertFalse(sentinel.exists())

    def test_failed_push_does_not_call_gh_and_can_retry(self):
        git(self.repo, 'remote', 'set-url', 'origin', self.root / 'absent.git')
        with self.assertRaises(RuntimeError):
            open_pr(self.path)
        self.assert_no_external_effect()
        git(self.repo, 'remote', 'set-url', 'origin', self.remote)
        self.assertTrue(open_pr(self.path).endswith('/pull/1'))

    def test_uncertain_creation_refuses_retry(self):
        original = subprocess.run
        with patch('herdworks.pr.subprocess.run', wraps=original) as run:
            def fail_gh(args, **kwargs):
                if args[0] == str(self.fake):
                    raise OSError('connection lost')
                return original(args, **kwargs)
            run.side_effect = fail_gh
            with self.assertRaisesRegex(OSError, 'connection lost'):
                open_pr(self.path)
        with self.assertRaisesRegex(ValueError, 'outcome uncertain'):
            open_pr(self.path)
        self.assertFalse(self.log.exists())

    def test_moving_head_after_push_refuses_pr(self):
        original = git
        def move(repo, *args, **kwargs):
            result = original(repo, *args, **kwargs)
            if args[0] == 'push':
                (self.repo / 'later').write_text('unverified')
                original(self.repo, 'add', '.')
                original(self.repo, 'commit', '-m', 'test: move after push')
            return result
        with patch('herdworks.pr.git', side_effect=move):
            with self.assertRaisesRegex(ValueError, 'gate changed'):
                open_pr(self.path)
        self.assertFalse(self.log.exists())
        self.assertEqual(git(self.remote, 'rev-parse', 'refs/heads/hw/HE-1'), self.sha)

    def test_unsafe_remote_and_mismatched_task_refused(self):
        with self.assertRaisesRegex(ValueError, 'remote'):
            grant_project(self.project, remote='--all')
        data = json.loads((self.path / 'task.json').read_text())
        data['branch'] = 'main'
        (self.path / 'task.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'identity'):
            open_pr(self.path)
        self.assert_no_external_effect()

    def test_factory_session_cannot_grant(self):
        with patch.dict(os.environ, HC_TERMINAL_ID='t2'), patch('herdworks.hc.get', return_value={'labels': {'hw': 'unit:HE-1'}}):
            with self.assertRaisesRegex(ValueError, 'owner outside Herdworks sessions'):
                grant_project(self.project, True, True)
        with patch.dict(os.environ, HW_HC_HOP='1'):
            with self.assertRaisesRegex(ValueError, 'owner outside Herdworks sessions'):
                grant_project(self.project, True, True)

    def test_forwarded_grant_is_refused_before_the_hop(self):
        program = Path(__file__).resolve().parents[1] / 'bin/hw'
        result = subprocess.run([str(program), 'project', 'grant', 'unit', '--push'],
                                env=dict(os.environ, HW_HC_HOP='1', HC_TERMINAL_ID='t-caller'),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('owner outside Herdworks sessions', result.stderr)

    def test_cli_grant_and_pr(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['project', 'grant', 'unit', '--no-push']), 0)
        self.assertFalse(read_project(self.project)['grants']['push'])
        with redirect_stdout(output):
            self.assertEqual(main(['project', 'grant', 'unit', '--push', '--pull-request']), 0)
            self.assertEqual(main(['pr', 'unit', 'HE-1']), 0)
        self.assertIn('https://github.invalid/fixture/hello/pull/1', output.getvalue())

    def environment_verdict(self, first='INCONCLUSIVE', remaining=True):
        timestamp = self.verdict.stat().st_mtime
        text = (f'{first}\nCommit: {self.sha}\nCause: external-prerequisite\n'
                'BLOCKED-BY-ENVIRONMENT: Verify on the target device; no device or emulator is available\n')
        if remaining:
            text += 'PASSED-OTHER-CHECKS: CLI and unit tests passed; evidence/commands.json\n'
        self.verdict.write_text(text)
        os.utime(self.verdict, (timestamp, timestamp))
        if first == 'INCONCLUSIVE':
            write_claims(self.verify, 'PROVED', 'NOT_PROVED')

    def test_manual_verification_pr_title_body_label_status_and_no_merge(self):
        self.environment_verdict()
        self.assertFalse(check_gate(self.path)[0])
        output = io.StringIO()
        with redirect_stdout(output), patch('herdworks.pr.subprocess.run', wraps=subprocess.run) as run:
            self.assertEqual(main(['pr', 'unit', 'HE-1', '--manual-verification', '--title', 'Add a concise shout flag']), 0)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        args = calls[0]['args']
        self.assertEqual(args[:2], ['pr', 'create'])
        self.assertFalse(calls[0]['isDraft'])
        self.assertEqual(args[args.index('--title') + 1], '[Needs manual verification] Add a concise shout flag')
        self.assertEqual(args[args.index('--label') + 1], 'needs-manual-verification')
        body = calls[0]['body']
        for value in ('## Needs manual verification', 'Verify on the target device', 'no device or emulator',
                      'Agents must not merge this pull request.', 'INCONCLUSIVE', self.sha):
            self.assertIn(value, body)
        self.assertNotIn('Verified commit:', body)
        self.assertEqual(derive_status(self.path), 'needs manual verification')
        self.assertFalse(check_gate(self.path)[0])
        self.assertTrue(events(self.path)[-1]['manual_verification'])
        gh_calls = [c.args[0] for c in run.call_args_list if c.args[0][0] == str(self.fake)]
        self.assertEqual([c[1:3] for c in gh_calls], [['pr', 'create']])
        result = subprocess.run([str(Path(__file__).resolve().parents[1] / 'bin/hw'), 'merge', 'unit', 'HE-1'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)
        self.assertEqual(git(self.remote, 'rev-parse', 'refs/heads/hw/HE-1'), self.sha)
        with self.assertRaisesRegex(ValueError, 'already opened'):
            open_pr(self.path, manual_verification=True)

    def test_manual_verification_refuses_code_failure_and_missing_remaining_proof(self):
        for first, remaining in [('FAIL', True), ('CONFIRMED', True), ('INCONCLUSIVE', False), ('PASS', False)]:
            with self.subTest(first=first, remaining=remaining):
                self.environment_verdict(first, remaining)
                with self.assertRaisesRegex(ValueError, 'gate refused'):
                    open_pr(self.path, manual_verification=True)
                self.assert_no_external_effect()

    def test_manual_verification_requires_each_grant(self):
        self.environment_verdict()
        for push, draft in [(False, True), (True, False), (False, False)]:
            with self.subTest(push=push, draft=draft):
                grant_project(self.project, push=push, draft_pr=draft)
                with self.assertRaisesRegex(ValueError, 'has not granted'):
                    open_pr(self.path, manual_verification=True)
                self.assert_no_external_effect()

    def test_manual_verification_preserves_provenance_commit_and_review_checks(self):
        self.environment_verdict()
        originals = {p: (p.read_bytes(), p.stat().st_mtime) for p in
                     [self.verdict, self.review / 'review.md', self.path / 'events.jsonl']}
        for failure in ('override', 'missing-review', 'rejected-review', 'wrong-commit', 'unrecorded-verifier'):
            with self.subTest(failure=failure):
                history = events(self.path)
                if failure == 'override':
                    for event in history:
                        if event.get('role') == 'verify':
                            event['launch_source'] = 'override'
                elif failure == 'missing-review':
                    (self.review / 'review.md').unlink()
                elif failure == 'rejected-review':
                    (self.review / 'review.md').write_text('REJECTED\n')
                elif failure == 'wrong-commit':
                    self.verdict.write_text(self.verdict.read_text().replace(self.sha, 'f' * 40))
                else:
                    history = [e for e in history if e.get('role') != 'verify']
                (self.path / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in history))
                with self.assertRaisesRegex(ValueError, 'gate refused'):
                    open_pr(self.path, manual_verification=True)
                self.assert_no_external_effect()
                for file, (content, timestamp) in originals.items():
                    file.write_bytes(content)
                    os.utime(file, (timestamp, timestamp))

    def test_manual_verification_requires_a_blocker(self):
        with self.assertRaisesRegex(ValueError, 'requires an environment-blocked requirement'):
            open_pr(self.path, manual_verification=True)
        self.assert_no_external_effect()

    def test_evidence_reviewer_environment_blocker_is_listed(self):
        review = self.review / 'review.md'
        timestamp = review.stat().st_mtime
        review.write_text('INCONCLUSIVE\nBLOCKED-BY-ENVIRONMENT: Inspect visual output; required device unavailable\n'
                          'PASSED-OTHER-CHECKS: All CLI command records and commit evidence inspected\n')
        os.utime(review, (timestamp, timestamp))
        url = open_pr(self.path, manual_verification=True)
        self.assertIn('Inspect visual output', json.loads(self.log.read_text())['body'])
        self.assertEqual(derive_status(self.path), 'needs manual verification')

    def test_empty_blocker_is_not_accepted_as_verified_or_manual(self):
        timestamp = self.verdict.stat().st_mtime
        self.verdict.write_text(f'PASS\nCommit: {self.sha}\nBLOCKED-BY-ENVIRONMENT:\nPASSED-OTHER-CHECKS: CLI passed\n')
        os.utime(self.verdict, (timestamp, timestamp))
        self.assertFalse(check_gate(self.path)[0])
        self.assertFalse(check_gate(self.path, manual_verification=True)[0])
        with self.assertRaisesRegex(ValueError, 'gate refused'):
            open_pr(self.path, manual_verification=True)
        self.assert_no_external_effect()

    def test_default_title_is_only_the_briefs_first_sentence(self):
        (self.path / 'brief.md').write_text('Improve the greeting. ' + 'Additional implementation detail ' * 30)
        open_pr(self.path)
        args = json.loads(self.log.read_text())['args']
        self.assertEqual(args[args.index('--title') + 1], 'Improve the greeting.')

    def test_default_title_cuts_a_long_first_sentence_to_72_characters(self):
        sentence = 'Improve ' + 'greeting details ' * 10 + '.'
        (self.path / 'brief.md').write_text(sentence + ' More instructions follow.')
        open_pr(self.path)
        args = json.loads(self.log.read_text())['args']
        self.assertEqual(args[args.index('--title') + 1], sentence[:72].rstrip())

    def test_pr_opens_against_the_tasks_base_branch(self):
        data = json.loads((self.path / 'task.json').read_text())
        data['base_branch'] = 'feature/x'
        (self.path / 'task.json').write_text(json.dumps(data))
        open_pr(self.path)
        call = json.loads(self.log.read_text())
        self.assertEqual(call['args'][call['args'].index('--base') + 1], 'feature/x')
        self.assertIn('based on feature/x at ' + data['base'], call['body'])

    def test_coordinator_can_pass_an_explicit_title(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['pr', 'unit', 'HE-1', '--title', 'Add a concise shout flag']), 0)
        args = json.loads(self.log.read_text())['args']
        self.assertEqual(args[args.index('--title') + 1], 'Add a concise shout flag')
