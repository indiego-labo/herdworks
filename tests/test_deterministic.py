import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
from unittest.mock import patch
from herdworks.cli import main
from herdworks.gate import check_gate, gate
from herdworks.projects import new_task
from herdworks.runs import derive_status, events, git, read_task
from herdworks.spawn import build_verify_brief, fix_brief, spawn
from tests.support import GateCase, write_claims
from tests.test_rounds import BuildScenario

ROOT = Path(__file__).resolve().parents[1]


def set_json(path, **values):
    data = json.loads(path.read_text()) if path.exists() else {}
    path.write_text(json.dumps(dict(data, **values)))


class ChecksTests(GateCase):
    def test_gate_runs_checks_on_the_committed_tree_and_records_them(self):
        # The checkout people work in is dirty; the checks must see the commit, not these edits.
        (self.repo / 'hello.py').write_text('UNCOMMITTED EDIT\n')
        (self.repo / 'untracked.py').write_text('never committed\n')
        command = 'cat hello.py; ls; git rev-parse HEAD'
        set_json(self.project / 'project.json', checks=command)
        self.assertEqual(gate(self.path), (True, self.sha, []))
        record = events(self.path)[-1]['checks']
        self.assertEqual((record['command'], record['commit'], record['exit']), (command, self.sha, 0))
        self.assertIn("print('changed')", record['tail'])
        self.assertIn(self.sha, record['tail'])
        self.assertNotIn('UNCOMMITTED', record['tail'])
        self.assertNotIn('untracked.py', record['tail'])
        self.assertFalse((self.path / 'checks').exists())
        self.assertEqual(len(git(self.repo, 'worktree', 'list').splitlines()), 1)

    def test_checkout_left_by_an_interrupted_run_is_replaced(self):
        set_json(self.project / 'project.json', checks='cat hello.py')
        git(self.repo, 'worktree', 'add', '--detach', self.path / 'checks', 'main')
        self.assertTrue(gate(self.path)[0])
        self.assertIn("print('changed')", events(self.path)[-1]['checks']['tail'])
        self.assertFalse((self.path / 'checks').exists())
        (self.path / 'checks').mkdir()
        (self.path / 'checks/stray.txt').write_text('unregistered leftover')
        self.assertTrue(gate(self.path)[0])
        self.assertFalse((self.path / 'checks').exists())

    def test_checks_run_the_same_for_the_coordinator_and_the_owner(self):
        set_json(self.project / 'project.json', checks='env')
        with patch.dict(os.environ, HW_CALLER_TERMINAL='t1', HW_HC_HOP='1'):
            self.assertTrue(gate(self.path)[0])
        tail = events(self.path)[-1]['checks']['tail']
        self.assertIn('HW_HOME=', tail)
        self.assertNotIn('HW_CALLER_TERMINAL', tail)
        self.assertNotIn('HW_HC_HOP', tail)

    def test_failing_checks_refuse_a_passing_verdict(self):
        set_json(self.project / 'project.json', checks='echo lint broke; exit 3')
        passed, commit, reasons = gate(self.path)
        self.assertFalse(passed)
        self.assertEqual(reasons, ['checks command exited 3'])
        record = events(self.path)[-1]['checks']
        self.assertEqual((record['exit'], record['tail']), (3, 'lint broke\n'))
        self.assertNotEqual(derive_status(self.path), 'verified')

    def test_verdict_text_alone_cannot_pass_once_checks_are_set(self):
        self.assertTrue(check_gate(self.path)[0])
        set_json(self.project / 'project.json', checks='true')
        passed, _, reasons = check_gate(self.path)
        self.assertFalse(passed)
        self.assertEqual(reasons, ['checks command has not run on the built commit; run hw gate'])
        self.assertNotEqual(derive_status(self.path), 'verified')
        self.assertTrue(gate(self.path)[0])
        self.assertEqual(derive_status(self.path), 'verified')
        # A pass belongs to the command that ran: changing the command needs a new run.
        set_json(self.project / 'project.json', checks='true && true')
        self.assertFalse(check_gate(self.path)[0])

    def test_machine_checks_apply_to_every_project_and_a_project_overrides_them(self):
        set_json(self.home / 'config.json', checks='exit 1')
        self.assertEqual(gate(self.path)[2], ['checks command exited 1'])
        set_json(self.project / 'project.json', checks='true')
        self.assertTrue(gate(self.path)[0])

    def test_without_checks_the_gate_runs_no_command(self):
        with patch('herdworks.gate.subprocess.run', wraps=subprocess.run) as run:
            self.assertTrue(gate(self.path)[0])
        self.assertFalse([c for c in run.call_args_list if c.kwargs.get('shell')])
        self.assertNotIn('checks', events(self.path)[-1])

    def test_failed_checks_output_reaches_the_fix_brief(self):
        (self.notes / 'intent.md').write_text('DONE CHECK')
        set_json(self.project / 'project.json', checks='echo 2 tests failed; exit 1')
        gate(self.path)
        brief = fix_brief(self.path, 1, ROOT)
        self.assertIn('Checks command `echo 2 tests failed; exit 1` exited 1', brief)
        self.assertIn('2 tests failed', brief)


class ClaimsTests(GateCase):
    def claims(self, *claims):
        (self.verify / 'claims.json').write_text(json.dumps(list(claims)))

    def refused(self, reason):
        passed, _, reasons = gate(self.path)
        self.assertFalse(passed)
        self.assertIn(reason, reasons)

    def test_verdict_without_claims_file_is_refused(self):
        (self.verify / 'claims.json').unlink()
        self.refused('verifier must write claims.json: a list with one graded entry per acceptance criterion')
        for content in ('not json', '[]', '{"id": "AC-1"}', '["AC-1"]'):
            (self.verify / 'claims.json').write_text(content)
            self.assertFalse(check_gate(self.path)[0], content)

    def test_every_criterion_needs_an_id_and_a_grade(self):
        proof = dict(check='python3 hello.py Ada', evidence='../evidence/cli.txt')
        self.claims(dict(id='AC-1', grade='PROVED', **proof), dict(id='AC-2', **proof))
        self.refused('claim AC-2 must be graded PROVED, DISPROVED or NOT_PROVED')
        self.claims(dict(id='AC-1', grade='PROVED', **proof), dict(id='AC-2', grade='LIKELY', **proof))
        self.refused('claim AC-2 must be graded PROVED, DISPROVED or NOT_PROVED')
        self.claims(dict(id='AC-1', grade='PROVED', **proof), dict(id='AC-1', grade='PROVED', **proof))
        self.refused('every claim in claims.json needs its own id')
        self.claims(dict(grade='PROVED', **proof))
        self.refused('every claim in claims.json needs its own id')

    def test_proved_and_disproved_need_a_check_and_existing_evidence(self):
        outside = self.root / 'outside.txt'
        outside.write_text('not saved evidence')
        (self.verify / 'evidence/link.txt').symlink_to(outside)
        for grade in ('PROVED', 'DISPROVED'):
            for proof in (dict(evidence='../evidence/cli.txt'),
                          dict(check='', evidence='../evidence/cli.txt'),
                          dict(check='python3 hello.py Ada'),
                          dict(check='python3 hello.py Ada', evidence='../evidence/missing.txt'),
                          dict(check='python3 hello.py Ada', evidence=str(outside)),
                          dict(check='python3 hello.py Ada', evidence='../evidence/link.txt'),
                          dict(check='python3 hello.py Ada', evidence='../verdict.md')):
                with self.subTest(grade=grade, proof=proof):
                    self.claims(dict(id='AC-1', grade=grade, **proof))
                    self.refused(f'claim AC-1 is {grade} without a check and an existing evidence file')

    def test_evidence_path_may_be_named_from_the_verdict_folder_or_the_worktree(self):
        for evidence in ('evidence/cli.txt', '../evidence/cli.txt', str(self.verify / 'evidence/cli.txt')):
            self.claims(dict(id='AC-1', grade='PROVED', check='python3 hello.py Ada', evidence=evidence))
            self.assertTrue(check_gate(self.path)[0], evidence)

    def test_not_proved_needs_a_reason(self):
        self.claims(dict(id='AC-1', grade='NOT_PROVED'))
        self.refused('claim AC-1 is NOT_PROVED without a reason')

    def test_verdict_must_follow_from_the_grades(self):
        # PASS over a DISPROVED claim is the free-written verdict the gate no longer trusts.
        write_claims(self.verify, 'PROVED', 'DISPROVED')
        self.refused('verdict.md must open FAIL, as claims.json grades it')
        write_claims(self.verify, 'PROVED', 'NOT_PROVED')
        self.refused('verdict.md must open INCONCLUSIVE, as claims.json grades it')
        write_claims(self.verify, 'PROVED', 'PROVED')
        self.verdict.write_text(f'FAIL\nCommit: {self.sha}\n')
        self.refused('verdict.md must open PASS, as claims.json grades it')

    def test_disproved_claim_fails_a_build_task_and_is_named(self):
        write_claims(self.verify, 'PROVED', 'DISPROVED')
        self.verdict.write_text(f'FAIL\nCommit: {self.sha}\n')
        self.refused('claim AC-2 is DISPROVED')
        self.assertNotIn('claim AC-1 is PROVED', gate(self.path)[2])

    def test_pull_request_body_lists_the_grades(self):
        from herdworks.pr import build_body
        (self.verify / 'evidence/commands.json').write_text(
            json.dumps([dict(command='python3 hello.py Ada', output='Hello, Ada!\n')]))
        self.assertIn('Claims: AC-1 PROVED', build_body(self.path, self.sha))


class ClaimsSpawnTests(BuildScenario):
    def verdict(self, text='PASS'):
        spawn(self.path)
        commit = self.ready()
        spawn(self.path, 'verify')
        (self.path / 'verify-1/verdict.md').write_text(f'{text}\nCommit: {commit}\n')

    def test_no_reviewer_is_spent_on_a_verdict_without_usable_claims(self):
        self.verdict()
        with patch('herdworks.hc.launch') as launch:
            with self.assertRaisesRegex(ValueError, 'usable claims; rerun the verifier: verifier must write claims.json'):
                spawn(self.path, 'evidence')
            launch.assert_not_called()
        self.assertFalse((self.path / 'evidence-1').exists())

    def test_verifier_is_rerun_once_for_unusable_claims_without_a_fix_round(self):
        self.verdict()
        spawn(self.path, 'verify')
        self.assertEqual(events(self.path)[-1]['folder'], 'verify-2')
        self.assertEqual(events(self.path)[-1]['round'], 0)
        (self.path / 'verify-2/verdict.md').write_text('PASS\n')
        with self.assertRaisesRegex(ValueError, 'rerun exhausted; ask the user'):
            spawn(self.path, 'verify')

    def test_verifier_with_usable_claims_is_not_rerun(self):
        self.verdict()
        write_claims(self.path / 'verify-1')
        with self.assertRaisesRegex(RuntimeError, 'already started'):
            spawn(self.path, 'verify')


class VerifierBriefTests(BuildScenario):
    def verify_brief(self, kind='build'):
        path, _ = new_task(self.project, self.brief, kind=kind)
        (self.project / 'coordinator/tasks' / path.name / 'intent.md').write_text('DONE CHECK')
        return build_verify_brief(path, 'a' * 40, path / 'verify-1/wt')

    def test_brief_asks_for_graded_claims_and_a_written_check(self):
        brief = self.verify_brief()
        for text in ('../claims.json', '"grade": "PROVED"', 'PROVED, DISPROVED or NOT_PROVED',
                     'NOT_PROVED needs a reason',
                     'When an outcome has no repeatable check, write one (a script or test saved in ../evidence/)',
                     'Never grade by reading the code.',
                     'Its first line follows from the grades: FAIL if any is DISPROVED'):
            self.assertIn(text, brief)
        self.assertNotIn('spike', brief)

    def test_spike_brief_reaches_every_role_and_only_spikes(self):
        self.assertIn('This task is a spike', self.verify_brief('spike'))
        with patch('herdworks.spawn.hold_reason', return_value=None):
            for kind, expected in (('spike', True), ('build', False)):
                path, _ = new_task(self.project, self.brief, kind=kind)
                (self.project / 'coordinator/tasks' / path.name / 'intent.md').write_text('DONE CHECK')
                spawn(path)
                wt = path / 'build-1/wt'
                git(wt, 'commit', '--allow-empty', '-m', 'test: findings')
                commit = git(wt, 'rev-parse', 'HEAD')
                (path / 'build-1/report.md').write_text(f'READY {commit}\n')
                spawn(path, 'verify')
                (path / 'verify-1/verdict.md').write_text(f'PASS\nCommit: {commit}\n')
                write_claims(path / 'verify-1', 'DISPROVED' if expected else 'PROVED')
                spawn(path, 'evidence')
                for role in ('build', 'verify', 'evidence'):
                    with self.subTest(kind=kind, role=role):
                        self.assertEqual('This task is a spike' in (path / f'{role}-1/brief.md').read_text(), expected)


class SpikeTests(GateCase):
    def spike(self):
        set_json(self.path / 'task.json', kind='spike')

    def test_task_new_records_the_kind_and_build_stays_the_default(self):
        self.assertNotIn('kind', read_task(self.path))
        git(self.repo, 'checkout', 'main')
        output = io.StringIO()
        with redirect_stdout(output), patch('herdworks.cli.hold_reason', return_value=None):
            self.assertEqual(main(['task', 'new', 'unit', '--brief', str(self.brief), '--kind', 'spike']), 0)
        self.assertEqual(read_task(self.project / 'tasks' / output.getvalue().split()[0])['kind'], 'spike')
        with self.assertRaisesRegex(ValueError, 'build or spike'):
            new_task(self.project, self.brief, kind='research')

    def test_evidenced_no_go_passes_a_spike_and_fails_a_build(self):
        write_claims(self.verify, 'PROVED', 'DISPROVED')
        self.assertFalse(gate(self.path)[0])
        self.spike()
        self.assertEqual(gate(self.path), (True, self.sha, []))
        self.assertEqual(derive_status(self.path), 'verified')

    def test_spike_not_proved_needs_a_stated_reason(self):
        self.spike()
        proof = dict(check='python3 hello.py Ada', evidence='../evidence/cli.txt')
        claims = [dict(id='AC-1', grade='DISPROVED', **proof), dict(id='AC-2', grade='NOT_PROVED')]
        (self.verify / 'claims.json').write_text(json.dumps(claims))
        self.assertEqual(gate(self.path)[2], ['claim AC-2 is NOT_PROVED without a reason'])
        claims[1]['reason'] = 'needs production traffic to measure'
        (self.verify / 'claims.json').write_text(json.dumps(claims))
        self.assertTrue(gate(self.path)[0])

    def test_spike_claims_must_still_be_complete_and_evidenced(self):
        self.spike()
        (self.verify / 'claims.json').write_text(json.dumps(
            [dict(id='AC-1', grade='DISPROVED', check='python3 hello.py Ada', evidence='../evidence/none.txt')]))
        self.assertEqual(gate(self.path)[2], ['claim AC-1 is DISPROVED without a check and an existing evidence file'])
        (self.verify / 'claims.json').unlink()
        self.assertFalse(gate(self.path)[0])


class RoundCapTests(BuildScenario):
    def configure(self, **values):
        set_json(self.home / 'config.json', **values)

    def fail(self, disproved='AC-1'):
        """A verifier disproves one criterion on the current commit, and the gate records the refusal."""
        spawn(self.path, 'verify')
        verifier = [e for e in events(self.path) if e.get('role') == 'verify'][-1]
        folder = self.path / verifier['folder']
        (folder / 'evidence').mkdir()
        (folder / 'evidence/out.txt').write_text('wrong output\n')
        (folder / 'claims.json').write_text(json.dumps([dict(
            id=disproved, grade='DISPROVED', check='python3 hello.py Ada', evidence='../evidence/out.txt')]))
        (folder / 'verdict.md').write_text(f"FAIL\nCommit: {verifier['commit']}\nFinding: wrong output\n")
        return gate(self.path)

    def two_failures(self, second='AC-1'):
        spawn(self.path)
        self.ready()
        self.fail()
        spawn(self.path, 'fix')
        self.ready()
        return self.fail(second)

    def test_second_failure_for_the_same_reason_escalates_instead_of_building(self):
        self.configure(max_same_reason_failures=2)
        _, commit, reasons = self.two_failures()
        escalated = events(self.path)[-1]
        self.assertEqual((escalated['event'], escalated['failures'], escalated['commit']), ('escalated', 2, commit))
        self.assertEqual(escalated['reasons'], reasons)
        self.assertIn('claim AC-1 is DISPROVED', reasons)
        self.assertEqual(derive_status(self.path), 'escalated')
        for role in ('fix', 'verify', 'build'):
            with patch('herdworks.hc.launch') as launch:
                with self.assertRaisesRegex(ValueError, 'task is escalated.*ask the user'):
                    spawn(self.path, role)
                launch.assert_not_called()
        self.assertFalse((self.path / 'build-3').exists())

    def test_gate_command_and_task_list_surface_the_escalation(self):
        self.configure(max_same_reason_failures=2)
        self.two_failures()
        output = io.StringIO()
        with patch('herdworks.cli.task_path', return_value=self.path), \
                patch('herdworks.cli.project_path', return_value=self.project), redirect_stdout(output):
            self.assertEqual(main(['gate', 'unit', 'HE-1']), 1)
            self.assertEqual(main(['tasks', 'unit']), 0)
        self.assertIn('REFUSED\n', output.getvalue())
        self.assertIn('ESCALATED after 2 refusals for the same reason; start no worker and ask the user', output.getvalue())
        self.assertIn('HE-1 escalated', output.getvalue())
        # Asking the gate again about the same commit is not another failure.
        self.assertEqual(sum(e.get('event') == 'escalated' for e in events(self.path)), 1)

    def test_a_different_reason_does_not_escalate(self):
        self.configure(max_same_reason_failures=2)
        self.two_failures(second='AC-2')
        self.assertFalse(any(e.get('event') == 'escalated' for e in events(self.path)))
        self.assertEqual(spawn(self.path, 'fix')['name'], 'hw-unit-he-1-build-3')

    def test_repeating_the_gate_on_one_commit_does_not_escalate(self):
        self.configure(max_same_reason_failures=2)
        spawn(self.path)
        self.ready()
        self.fail()
        gate(self.path)
        gate(self.path)
        self.assertFalse(any(e.get('event') == 'escalated' for e in events(self.path)))
        self.assertEqual(derive_status(self.path), 'in progress')

    def test_the_number_is_configurable_for_the_machine_and_a_project(self):
        self.configure(max_same_reason_failures=3)
        self.two_failures()
        self.assertEqual(derive_status(self.path), 'in progress')
        spawn(self.path, 'fix')
        self.ready()
        self.fail()
        self.assertEqual(derive_status(self.path), 'escalated')
        second, _ = new_task(self.project, self.brief)
        set_json(self.project / 'project.json', max_same_reason_failures=1)
        self.assertFalse(gate(second)[0])
        self.assertEqual(derive_status(second), 'escalated')
        for value in (0, True, 'two'):
            set_json(self.project / 'project.json', max_same_reason_failures=value)
            with self.assertRaisesRegex(ValueError, 'max_same_reason_failures'):
                gate(second)

    def test_the_users_answer_lets_work_resume_and_counts_afresh(self):
        self.configure(max_same_reason_failures=2)
        self.two_failures()
        at = events(self.path)[-1]['at']
        (self.project / 'inbox.jsonl').write_text(
            json.dumps(dict(number=1, text='ORIGINAL REQUEST', at=at - 100)) + '\n'
            + json.dumps(dict(number=2, text='Drop the cache and try again', at=at + 1)) + '\n')
        (self.notes / 'answers').mkdir()
        (self.notes / 'answers/1.md').write_text('ORIGINAL REQUEST')
        self.assertEqual(derive_status(self.path), 'escalated')
        (self.notes / 'answers/2.md').write_text('Drop the cache and try again')
        self.assertEqual(derive_status(self.path), 'in progress')
        self.assertEqual(spawn(self.path, 'fix')['name'], 'hw-unit-he-1-build-3')
        self.ready()
        self.fail()
        self.assertEqual(derive_status(self.path), 'in progress')

    def test_fix_needs_the_gates_refusal_of_the_current_commit(self):
        spawn(self.path)
        self.ready()
        spawn(self.path, 'verify')
        (self.path / 'verify-1/verdict.md').write_text('FAIL\nFinding: wrong output\n')
        with patch('herdworks.hc.launch') as launch:
            with self.assertRaisesRegex(ValueError, 'run hw gate first'):
                spawn(self.path, 'fix')
            launch.assert_not_called()
        gate(self.path)
        self.assertEqual(spawn(self.path, 'fix')['name'], 'hw-unit-he-1-build-2')
