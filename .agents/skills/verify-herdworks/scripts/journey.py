#!/usr/bin/env python3
"""Real Project journeys in an explicitly selected scratch core and Herdworks home."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from herdworks import hc
from herdworks.home import hw_home
from herdworks.projects import project_path, task_paths
from herdworks.runs import built_commit, coordinator_task, events, git, read_task, task_key
from herdworks.talk import coordinator_name, read as replies


def command(*args, check=True):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]}: {result.stderr or result.stdout}")
    return result


def doctor(agent='codex'):
    session = os.environ.get('HC_SESSION', 'default')
    if not session or session == 'default':
        raise RuntimeError('refusing the default herdr core; select a scratch HC_SESSION')
    for name in ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR'):
        value = os.environ.get(name)
        if not value or not Path(value).is_absolute():
            raise RuntimeError(f'absolute scratch {name} is required')
    defaults = (Path.home() / '.config', Path.home() / '.local/state', Path('/run/user') / str(os.getuid()))
    for name, default in zip(('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR'), defaults):
        if Path(os.environ[name]).resolve().is_relative_to(default.resolve()):
            raise RuntimeError(f'refusing the real {name}; select a scratch folder')
    if not os.environ.get('HW_HOME') or hw_home() == (Path.home() / '.herdworks').resolve():
        raise RuntimeError('refusing the real Herdworks home; set a scratch HW_HOME')
    if hw_home().is_relative_to(ROOT.resolve()):
        raise RuntimeError('refusing a Herdworks home inside the checkout')
    for program in ('hc', agent, 'git'):
        if not shutil.which(program):
            raise RuntimeError(f'missing {program}')
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 required')
    identity = hc.call('server', 'status', '--json')
    return dict(session=session, root=str(ROOT), home=str(hw_home()), core=identity,
                python=sys.version.split()[0])


def snapshot():
    return {item['address'] for item in hc.call('ls', '--all', '--json')['terminals']}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def fixture(destination):
    shutil.copytree(ROOT / 'fixtures/hello', destination,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    git(destination, 'init', '-b', 'main')
    git(destination, 'config', 'user.name', 'Herdworks fixture')
    git(destination, 'config', 'user.email', 'hw@example.invalid')
    git(destination, 'add', '.')
    git(destination, 'commit', '-m', 'test: initialize hello fixture')


def state_word(result):
    value = result.get('status')
    return value.get('state') if isinstance(value, dict) else value


def collect(project, evidence):
    for name in ('inbox.jsonl', 'project.json', 'coordinator.json', 'coordinator-sessions.jsonl'):
        if (project / name).exists():
            shutil.copyfile(project / name, evidence / name)
    for folder in ('coordinator/outbox', 'coordinator/tasks'):
        shutil.copytree(project / folder, evidence / folder, dirs_exist_ok=True)
    for item in task_paths(project):
        path = item.parent
        target = evidence / 'tasks' / path.name
        target.mkdir(parents=True, exist_ok=True)
        for name in ('task.json', 'brief.md', 'events.jsonl'):
            shutil.copyfile(path / name, target / name)
            if path.name == 'HE-1':
                shutil.copyfile(path / name, evidence / name)
        for folder in path.iterdir():
            if folder.is_dir() and folder.name.split('-')[0] in ('build', 'verify', 'evidence'):
                destination = target / folder.name
                destination.mkdir(exist_ok=True)
                for artifact in folder.iterdir():
                    if artifact.is_file() and artifact.name != '.git':
                        shutil.copyfile(artifact, destination / artifact.name)
                if (folder / 'evidence').is_dir():
                    shutil.copytree(folder / 'evidence', destination / 'evidence', dirs_exist_ok=True)
        for pattern, name in (('verify-*/verdict.md', 'verdict.md'), ('evidence-*/review.md', 'review.md')):
            sources = sorted(path.glob(pattern), key=lambda p: int(p.parent.name.split('-')[-1]))
            if sources:
                shutil.copyfile(sources[-1], evidence / name)


def initial_reply(project):
    candidates = [p for p in (project / 'coordinator/outbox').glob('*.md')
                  if p.read_text().startswith('REPLY\n')
                  and 'Message: 1' in p.read_text().splitlines()]
    return min(candidates, key=lambda p: p.stat().st_mtime)


def cleanup(project, evidence, baseline, keep_worktrees=False):
    owned = []
    for session in hc.call('ls', '--all', '--json')['terminals']:
        labels = hc.get(session['address']).get('labels', {})
        label = labels.get('hw', '')
        if label == f'project:{project.name}' or label.startswith(project.name + ':'):
            owned.append(session['address'])
    errors = []
    for address in reversed(owned):
        if address in baseline:
            errors.append(f'refused baseline terminal {address}')
            continue
        try:
            (evidence / f'last-{address}.txt').write_text(hc.call('read', address, '--json')['text'])
            if hc.get(address).get('state') == 'live':
                hc.call('kill', address)
            hc.call('rm', address)
        except Exception as error:
            errors.append(str(error))
    for item in ([] if keep_worktrees else task_paths(project)):
        data = read_task(item.parent)
        for wt in item.parent.glob('*/wt'):
            if wt.exists():
                try:
                    git(data['repo'], 'worktree', 'remove', '--force', wt)
                except Exception as error:
                    errors.append(str(error))
    after = snapshot()
    save(evidence / 'cleanup.json', dict(baseline=sorted(baseline), after=sorted(after), owned=owned,
                                       errors=errors, foreign_preserved=baseline <= after,
                                       foreign_missing=sorted(baseline - after),
                                       foreign_untouched=not bool(set(owned) & baseline),
                                       owned_remaining=sorted(set(owned) & after)))
    if errors or set(owned) & after:
        raise RuntimeError('cleanup failed; see cleanup.json')


JOURNEYS = ('converse', 'question-and-answer', 'fail-and-fix', 'pickup', 'repeat-message', 'stop', 'draft-pr', 'no-grant', 'environment-blocked')


def run_journey(kind, evidence, timeout, project_name='hello', remote=False):
    evidence.mkdir(parents=True, exist_ok=False)
    save(evidence / 'doctor.json', doctor('opencode'))
    baseline = snapshot()
    save(evidence / 'baseline.json', sorted(baseline))
    repo = evidence / 'repo'
    fixture(repo)
    project = project_path(project_name)
    frames = []
    start = time.monotonic()
    failure = None
    status_sent = answered = picked_up = remembered = repeated = False
    status_number = remember_number = None
    stop_number = None
    def hw(*args, **kwargs):
        return command(ROOT / 'bin/hw', *args, **kwargs).stdout
    def frame(text):
        file = evidence / f'screen-{len(frames):04}.txt'
        file.write_text(text)
        frames.append(dict(at=time.monotonic() - start, captured_at=time.time(), path=file.name))
    try:
        hw('install')
        (evidence / 'added.txt').write_text(hw('project', 'add', project.name, '--repo', repo, '--prefix', 'HE'))
        if kind in ('draft-pr', 'no-grant', 'environment-blocked'):
            remote = evidence / 'remote.git'
            git(evidence, 'init', '--bare', remote)
            git(repo, 'remote', 'add', 'origin', remote)
            grant = ['--push', '--draft-pr'] if kind in ('draft-pr', 'environment-blocked') else []
            (evidence / 'grant.txt').write_text(hw('project', 'grant', project.name,
                '--gh', ROOT / 'fixtures/hello/planted/fake-gh.sh', *grant))
        from herdworks.limits import ROLES
        settings = dict(agents={role: dict(agent='opencode', model='deepseek/deepseek-flash') for role in ROLES})
        if remote:
            settings['sandbox'] = 'off'
            save(evidence / 'disk-before.json', dict(free=shutil.disk_usage(hw_home()).free))
        save(hw_home() / 'config.json', settings)
        hw('project', 'grant', project.name, '--unsandboxed')
        (evidence / 'config.txt').write_text(hw('config'))
        output = hw('up', project.name)
        (evidence / 'started.txt').write_text(output)
        assert f'started {coordinator_name(project)}' in output
        if kind == 'environment-blocked':
            assert shutil.which('hello-device-probe') is None, 'fixture requires the external device tool to be absent'
            save(evidence / 'environment.json', dict(missing_tool='hello-device-probe', simulated=False))
        brief = repo / 'briefs' / ('environment-blocked.md' if kind == 'environment-blocked' else
                                  'ambiguous.md' if kind == 'question-and-answer' else 'shout.md')
        output = hw('say', project.name, '--file', brief)
        assert output.strip() == 'delivered 1'
        frame(f'$ bin/hw say {project.name} --file {brief}\n{output}')
        while time.monotonic() - start < timeout:
            items = task_paths(project)
            path = items[0].parent if items else None
            history = events(path) if path else []
            builds = [e for e in history if e.get('role') == 'build' and e.get('event') == 'session']
            verifiers = [e for e in history if e.get('role') == 'verify' and e.get('event') == 'session']
            outbox = replies(project)
            status = hw('tasks', project.name)
            (evidence / 'tasks.txt').write_text(status)
            text = hw('read', project.name)
            frame(status + '\n' + text)
            current = hc.get(coordinator_name(project))
            with (evidence / 'status.jsonl').open('a') as stream:
                stream.write(json.dumps(dict(elapsed=time.monotonic() - start, coordinator=current)) + '\n')
            if state_word(current) == 'blocked':
                raise RuntimeError('coordinator is blocked; inspect last screen')
            if path and kind == 'fail-and-fix' and not builds:
                data = read_task(path)
                data['roles'] = dict(build=str(ROOT / 'fixtures/hello/planted/apply-wrong.sh'))
                save(path / 'task.json', data)
            if path and kind == 'fail-and-fix' and (path / 'build-1/report.md').exists():
                data = read_task(path)
                if data.get('roles', {}).get('build'):
                    data['roles'].pop('build')
                    save(path / 'task.json', data)
            if kind == 'converse' and builds and not status_sent and not (path / 'build-1/report.md').exists():
                output = hw('say', project.name, 'What is the status of that task?')
                status_number = int(output.split()[1])
                (evidence / 'status-message.txt').write_text(output)
                status_sent = True
            if kind == 'converse' and status_sent and not (evidence / 'never-busy.json').exists():
                matches = [(n, t) for n, t in outbox if t.startswith('REPLY\n') and f'Message: {status_number}\n' in t and 'HE-1' in t]
                if matches:
                    saved = dict(reply=matches[0], reply_at=time.time(), report_exists=(path / 'build-1/report.md').exists())
                    save(evidence / 'never-busy.json', saved)
                    assert not saved['report_exists'], 'status reply arrived after builder report'
            if kind == 'repeat-message' and path and not repeated:
                output = hw('say', project.name, '--number', '1')
                assert output.strip() == 'delivered 1 repeat'
                (evidence / 'repeat.txt').write_text(output)
                repeated = True
            if kind == 'question-and-answer' and not answered and any(t.startswith('QUESTION\n') for _, t in outbox):
                assert 'HE-1 waiting on you' in status
                assert not builds, 'preference question should precede build'
                assert git(repo, 'rev-parse', 'HEAD') == read_task(path)['base']
                (evidence / 'waiting-tasks.txt').write_text(status)
                question = next(t for _, t in outbox if t.startswith('QUESTION\n'))
                (evidence / 'question.txt').write_text(question)
                assert len([t for _, t in outbox if t.startswith('QUESTION\n')]) == 1
                (evidence / 'answer.txt').write_text(hw('say', project.name, 'Choose Welcome aboard, Ada! as the approved brand greeting.'))
                answered = True
            if kind == 'pickup' and not picked_up and verifiers:
                worker = verifiers[-1]
                if not (path / worker['folder'] / 'verdict.md').exists() and state_word(hc.get(worker['address'])) == 'working':
                    save(evidence / 'pickup-before.json', hc.get(worker['address']))
                    hc.call('kill', current['address'])
                    save(evidence / 'pickup-after.json', hc.get(worker['address']))
                    (evidence / 'pickup-up.txt').write_text(hw('up', project.name))
                    picked_up = True
                    continue
            if kind == 'stop' and builds and stop_number is None:
                worker = hc.get(builds[-1]['address'])
                if worker.get('state') == 'live' and state_word(worker) == 'working' and not (path / builds[-1]['folder'] / 'report.md').exists():
                    save(evidence / 'stop-before.json', dict(worker=worker, coordinator=current, report_exists=False))
                    output = hw('say', project.name, 'Stop task HE-1 now. Leave a catchup and DONE, and stay available.')
                    stop_number = int(output.split()[1])
                    (evidence / 'stop-message.txt').write_text(output)
            if kind == 'stop':
                done = next((t for _, t in outbox if t.startswith('DONE\n') and 'Task: HE-1' in t.splitlines()
                             and f'Message: {stop_number}' in t.splitlines()), None)
                if done:
                    assert stop_number is not None
                    assert 'HE-1 stopped' in status
                    assert any(e.get('event') == 'stop' for e in history)
                    workers = [hc.get(s['address']) for s in hc.sessions()]
                    workers = [s for s in workers if s.get('labels', {}).get('hw') == task_key(path)]
                    assert not any(s.get('state') == 'live' for s in workers), 'stopped task has a live worker'
                    assert current.get('state') == 'live', 'stop killed the coordinator'
                    catchup = coordinator_task(path) / 'catchup.md'
                    assert catchup.is_file() and catchup.read_text().strip(), 'missing stop catchup'
                    save(evidence / 'stop-after.json', dict(workers=workers, coordinator=current, done=done,
                                                          catchup=catchup.read_text(), tasks=status))
                    frame(status + '\n' + text + '\n' + catchup.read_text())
                    collect(project, evidence)
                    break
                hc.call('wait', current['address'], '--timeout', '3', '--json')
                continue
            done = next((t for _, t in outbox if t.startswith('DONE\n') and 'HE-1' in t), None)
            if done and path:
                commit = built_commit(path)
                assert commit and commit in done
                if kind in ('draft-pr', 'environment-blocked'):
                    url = 'https://github.invalid/fixture/hello/pull/1'
                    expected = 'needs manual verification' if kind == 'environment-blocked' else 'for review'
                    assert f'HE-1 {expected} {commit} {url}' in status
                    assert url in done
                    assert git(remote, 'rev-parse', 'refs/heads/hw/HE-1') == commit
                    calls = [json.loads(line) for line in (evidence / 'fake-gh.jsonl').read_text().splitlines()]
                    assert len(calls) == 1 and calls[0]['args'][:2] == ['pr', 'create'] and not calls[0]['isDraft']
                    body = calls[0]['body']
                    headings = ['## Why', '## Scope', '## Blast Radius', '## Verification']
                    positions = [body.index(heading + '\n') for heading in headings]
                    assert positions == sorted(positions)
                    if kind == 'environment-blocked':
                        args = calls[0]['args']
                        assert args[args.index('--title') + 1].startswith('[Needs manual verification]')
                        assert args[args.index('--label') + 1] == 'needs-manual-verification'
                        assert '## Needs manual verification' in body and 'hello-device-probe' in body
                        assert 'Agents must not merge this pull request.' in body
                        assert len(verifiers) == 1 and len(builds) == 1, 'environment blocker was retried'
                        verdict = (path / verifiers[0]['folder'] / 'verdict.md').read_text()
                        assert verdict.startswith('INCONCLUSIVE\n') and 'BLOCKED-BY-ENVIRONMENT:' in verdict
                        assert 'PASSED-OTHER-CHECKS:' in verdict
                        assert any(t.startswith('REPLY\n') and 'hello-device-probe' in t for _, t in outbox)
                    else:
                        assert commit in body and 'PASS' in body and 'CONFIRMED' in body
                    assert 'python' in body and 'HELLO, ADA!' in body
                    (evidence / 'pr-body.md').write_text(body)
                    save(evidence / 'remote.json', dict(branch='hw/HE-1', commit=commit, url=url))
                    entry = next(e for e in history if e.get('event') == 'pr')
                    inbox_time = json.loads((project / 'inbox.jsonl').read_text().splitlines()[0])['at']
                    save(evidence / 'timing.json', dict(message_to_pr_seconds=entry['at'] - inbox_time))
                else:
                    assert f'HE-1 verified {commit}' in status
                if kind == 'no-grant':
                    assert git(remote, 'for-each-ref', '--format=%(refname)') == ''
                    assert not (evidence / 'fake-gh.jsonl').exists()
                    assert 'not opened' in done.lower() and 'push' in done and 'draft-pr' in done
                    (evidence / 'remote-refs.txt').write_text('No refs; no push occurred.\n')
                if (path / 'pr-body.md').exists():
                    shutil.copyfile(path / 'pr-body.md', evidence / 'pr-body.md')
                if kind == 'converse' and not remembered:
                    assert status_sent and (evidence / 'never-busy.json').exists()
                    output = hw('say', project.name, 'What did you just do for that one?')
                    remember_number = int(output.split()[1])
                    (evidence / 'remember-message.txt').write_text(output)
                    remembered = True
                    continue
                if kind == 'converse' and not any(t.startswith('REPLY\n') and f'Message: {remember_number}\n' in t and 'HE-1' in t for _, t in outbox):
                    hc.call('wait', current['address'], '--timeout', '5', '--json')
                    continue
                if kind == 'pickup' and not repeated:
                    output = hw('say', project.name, '--number', '1')
                    assert output.strip() == 'delivered 1 repeat'
                    (evidence / 'repeat.txt').write_text(output)
                    repeated = True
                    continue
                if kind in ('pickup', 'repeat-message', 'stop'):
                    assert repeated and len(items) == 1
                    if not any('repeat' in t.lower() and t.startswith('REPLY\n') for _, t in outbox):
                        hc.call('wait', current['address'], '--timeout', '5', '--json')
                        continue
                if kind == 'environment-blocked':
                    gate = hw('gate', project.name, 'HE-1', check=False)
                    assert gate.startswith('REFUSED') and 'blocked by environment' in gate
                    (evidence / 'gate.txt').write_text(gate)
                    frame(f'$ bin/hw gate {project.name} HE-1\n{gate}\n{hw("tasks", project.name)}\n{hw("read", project.name)}')
                    from herdworks.gate import check_gate
                    assert check_gate(path, manual_verification=True)[:2] == (True, commit)
                    save(evidence / 'manual-handoff.json', dict(commit=commit, verifiers=len(verifiers),
                         builds=len(builds), status='needs manual verification', normal_gate='REFUSED'))
                else:
                    gate = hw('gate', project.name, 'HE-1')
                    assert gate.strip() == f'VERIFIED {commit}'
                    (evidence / 'gate.txt').write_text(gate)
                    frame(f'$ bin/hw gate {project.name} HE-1\n{gate}\n{hw("tasks", project.name)}\n{hw("read", project.name)}')
                    assert (path / verifiers[-1]['folder'] / 'verdict.md').read_text().startswith('PASS\n')
                    reviews = list(path.glob('evidence-*/review.md'))
                    assert reviews and reviews[-1].read_text().startswith('CONFIRMED\n')
                wt = evidence / 'check-wt'
                git(repo, 'worktree', 'add', '--detach', wt, commit)
                try:
                    normal = command(sys.executable, wt / 'hello.py', 'Ada').stdout
                    shout = command(sys.executable, wt / 'hello.py', '--shout', 'Ada').stdout if kind != 'question-and-answer' else normal
                    assert normal == ('Welcome aboard, Ada!\n' if kind == 'question-and-answer' else 'Hello, Ada!\n')
                    assert shout == ('Welcome aboard, Ada!\n' if kind == 'question-and-answer' else 'HELLO, ADA!\n')
                    (evidence / 'cli-output.txt').write_text(normal + shout)
                finally:
                    git(repo, 'worktree', 'remove', '--force', wt)
                if kind == 'fail-and-fix':
                    assert len(builds) == 2 and builds[0]['name'] != builds[1]['name']
                    assert (path / verifiers[0]['folder'] / 'verdict.md').read_text().startswith('FAIL\n')
                    assert 'diagnos' in (path / builds[1]['folder'] / 'report.md').read_text().lower()
                if kind == 'pickup':
                    assert picked_up and len(builds) == 1
                if kind == 'question-and-answer':
                    assert answered
                assert len(items) == 1
                assert any(t.startswith('REPLY\n') and 'HE-1' in t for _, t in outbox)
                acknowledgement = initial_reply(project)
                inbox_time = json.loads((project / 'inbox.jsonl').read_text().splitlines()[0])['at']
                assert acknowledgement.stat().st_mtime - inbox_time <= 60, 'acknowledgement exceeded one minute'
                collect(project, evidence)
                (evidence / 'git-log.txt').write_text(git(repo, 'log', '--all', '--oneline'))
                break
            hc.call('wait', current['address'], '--timeout', '3', '--json')
        else:
            raise RuntimeError(f'journey exceeded {timeout}s')
    except BaseException as error:
        failure = error
        (evidence / 'result.txt').write_text(f'FAIL {kind}: {error}\n')
        if project.exists():
            collect(project, evidence)
    finally:
        save(evidence / 'screens.json', frames)
        if project.exists():
            cleanup(project, evidence, baseline, keep_worktrees=remote)
    if failure:
        raise failure
    (evidence / 'result.txt').write_text(f'PASS {kind}\n')
    return evidence


FP3_JOURNEYS = ('two-at-once', 'queued', 'memory-carries', 'verifier-blind', 'disk-floor')


def run_fp3(kind, evidence, timeout, project_name):
    from herdworks.limits import ROLES
    from herdworks.projects import new_task
    from herdworks.runs import derive_status
    evidence.mkdir(parents=True, exist_ok=False)
    save(evidence / 'doctor.json', doctor('opencode'))
    baseline = snapshot()
    repo = evidence / 'repo'
    fixture(repo)
    project = project_path(project_name)
    start = time.monotonic()
    frames = []
    def hw(*args, check=True):
        return command(ROOT / 'bin/hw', *args, check=check)
    try:
        hw('install')
        hw('project', 'add', project_name, '--repo', repo, '--prefix', 'HE')
        home = hw_home()
        settings = dict(agents={role: dict(agent='opencode', model='deepseek/deepseek-flash') for role in ROLES})
        if kind == 'queued':
            settings['max_tasks_at_once'] = 1
        if kind == 'disk-floor':
            settings['min_free_disk_gb'] = shutil.disk_usage(home).free / 1024 ** 3 + 100
        save(home / 'config.json', settings)
        hw('project', 'grant', project_name, '--unsandboxed')
        (evidence / 'config.txt').write_text(hw('config').stdout)
        if kind == 'disk-floor':
            path, _ = new_task(project, repo / 'briefs/shout.md')
            result = hw('spawn', project_name, path.name, 'build', check=False)
            assert result.returncode and 'min_free_disk_gb' in result.stderr
            status = hw('tasks', project_name).stdout
            (evidence / 'tasks.txt').write_text(status)
            (evidence / 'spawn.txt').write_text(result.stdout + result.stderr)
            assert 'queued' in status and 'min_free_disk_gb' in status
            assert not events(path)
            assert snapshot() == baseline
        else:
            hw('up', project_name)
            first = (repo / 'briefs/shout.md').read_text()
            second = ('Add a --farewell flag to hello.py. python3 hello.py --farewell Ada must print exactly Goodbye, Ada! followed by a newline. Without the flag the original Hello, Ada! stays. Add a unittest, run python3 -m unittest, and commit locally. This is independent of the shout task; start from the Project base. The coordinator owns independent verification.')
            if kind in ('two-at-once', 'queued'):
                text = ('This message gives TWO independent tasks. Create one task-specific brief per task using task new --brief, track both ids in messages.tsv, and acknowledge both. Run both up to the tool limits and finish both through the independent gate.\n\nTask A:\n' + first + '\n\nTask B:\n' + second)
            elif kind == 'memory-carries':
                text = first + '\nThe builder must also record Project memory titled Test command containing exactly: python3 -m unittest. Use the memory command supplied in the builder brief before the READY report. This is builder handoff bookkeeping for Herdworks memory-carries journey, checked directly by the journey through memory read and the next builder packet. It is not an acceptance condition for the committed product: the independent product verifier must check the CLI, unittest and commit requirements above, using only its filtered memory packet, and must not certify or inspect same-task live memory.'
            else:
                plant = evidence / 'plant-memory.sh'
                import shlex
                plant.write_text('#!/bin/sh\nset -eu\n' + shlex.join(['env', f'HW_HOME={home}', str(ROOT / 'bin/hw'), 'memory', 'add', project_name, '--task', 'HE-1', '--title', 'Blindness marker', '--text', 'BUILDER-SAYS-IT-WORKS']) + '\n')
                plant.chmod(0o755)
                text = first + f'\nThe builder must run {plant} before its READY report. This plants a memory entry for a verifier-blindness check. The verifier should verify product behavior independently and need not repeat that setup script.'
            hw('say', project_name, text)
            expected = 2 if kind in ('two-at-once', 'queued', 'memory-carries') else 1
            second_sent = False
            overlap = None
            queued_seen = None
            while time.monotonic() - start < timeout:
                paths = [p.parent for p in task_paths(project)]
                status = hw('tasks', project_name).stdout
                out = hw('read', project_name).stdout
                number = len(frames)
                screen = evidence / f'screen-{number:04}.txt'
                screen.write_text(status + '\n' + out)
                frames.append(dict(at=time.monotonic() - start, captured_at=time.time(), path=screen.name))
                (evidence / 'tasks.txt').write_text(status)
                if len(paths) == 2 and 'HE-2 queued' in status and 'max_tasks_at_once' in status:
                    queued_seen = dict(at=time.time(), tasks=status)
                    save(evidence / 'queued-observation.json', queued_seen)
                builds = [(p, e) for p in paths for e in events(p) if e.get('event') == 'session' and e.get('role') == 'build']
                live = [(p, e) for p, e in builds if hc.get(e['address']).get('state') == 'live']
                if len(live) == 2 and overlap is None:
                    overlap = dict(at=time.time(), sessions=[e for p, e in live], worktrees=[str(p / e['folder'] / 'wt') for p, e in live])
                    save(evidence / 'overlap.json', overlap)
                done = [p for p in paths if derive_status(p) == 'verified']
                if kind == 'memory-carries' and len(done) == 1 and not second_sent:
                    (evidence / 'memory.txt').write_text(hw('memory', 'read', project_name).stdout)
                    assert 'python3 -m unittest' in (evidence / 'memory.txt').read_text()
                    hw('say', project_name, second)
                    second_sent = True
                if len(paths) == expected and len(done) == expected and out.count('DONE\n') >= expected:
                    if kind == 'two-at-once':
                        assert overlap, 'builders never observed alive together'
                        metadata = [read_task(p) for p in paths]
                        assert metadata[0]['base'] == metadata[1]['base']
                        assert metadata[0]['branch'] != metadata[1]['branch']
                    if kind == 'queued':
                        assert queued_seen, 'queue reason never observed'
                        first_gate = [e for e in events(paths[0]) if e.get('event') == 'gate' and e.get('passed')]
                        second_build = [e for e in events(paths[1]) if e.get('event') == 'session'][0]
                        assert first_gate
                        assert second_build['started_at'] > min(e['at'] for e in first_gate)
                    if kind == 'memory-carries':
                        brief = next(paths[1].glob('build-*/brief.md')).read_text()
                        assert '# Test command' in brief and 'python3 -m unittest' in brief
                    if kind == 'verifier-blind':
                        for file in [*paths[0].glob('verify-*/brief.md'), *paths[0].glob('evidence-*/brief.md')]:
                            assert 'BUILDER-SAYS-IT-WORKS' not in file.read_text()
                        assert 'BUILDER-SAYS-IT-WORKS' in hw('memory', 'read', project_name).stdout
                    for path in paths:
                        result = hw('gate', project_name, path.name)
                        (evidence / f'gate-{path.name}.txt').write_text(result.stdout)
                        sha = built_commit(path)
                        target = evidence / f'check-{path.name}'
                        git(repo, 'worktree', 'add', '--detach', target, sha)
                        try:
                            flag, output = ('--shout', 'HELLO, ADA!\n') if path == paths[0] else ('--farewell', 'Goodbye, Ada!\n')
                            actual = command(sys.executable, target / 'hello.py', flag, 'Ada').stdout
                            assert actual == output
                            (evidence / f'cli-{path.name}.txt').write_text(actual)
                        finally:
                            git(repo, 'worktree', 'remove', '--force', target)
                    break
                current = hc.get(coordinator_name(project))
                if current.get('state') != 'live':
                    raise RuntimeError('coordinator ended before the tasks completed')
                hc.call('wait', current['address'], '--timeout', '3', '--json')
            else:
                raise RuntimeError(f'journey exceeded {timeout}s')
        collect(project, evidence)
        shutil.copytree(project / 'memory', evidence / 'memory', dirs_exist_ok=True)
        for item in task_paths(project):
            launches = [e for e in events(item.parent) if e.get('event') == 'session']
            assert all(e.get('agent') == 'opencode' and e.get('model') == 'deepseek/deepseek-flash' and e.get('sandboxed') is False for e in launches)
        (evidence / 'result.txt').write_text(f'PASS {kind}\n')
    except BaseException as error:
        (evidence / 'result.txt').write_text(f'FAIL {kind}: {error}\n')
        if project.exists():
            collect(project, evidence)
        raise
    finally:
        save(evidence / 'screens.json', frames)
        if project.exists():
            cleanup(project, evidence, baseline)
    return evidence


def regression(evidence, base):
    evidence.mkdir(parents=True, exist_ok=False)
    save(evidence / 'doctor.json', doctor())
    baseline = snapshot()
    checkout = evidence / 'parent-checkout'
    parent = git(ROOT, 'rev-parse', '--verify', base)
    save(evidence / 'commits.json', dict(parent=parent, head=git(ROOT, 'rev-parse', 'HEAD')))
    try:
        git(ROOT, 'worktree', 'add', '--detach', checkout, parent)
        for label, root, journey in (('parent', checkout, 'verified'), ('head', ROOT, 'converse')):
            result = command(sys.executable, root / '.agents/skills/verify-herdworks/scripts/journey.py',
                             journey, '--evidence', evidence / label)
            (evidence / f'{label}.txt').write_text(result.stdout)
    finally:
        if checkout.exists():
            git(ROOT, 'worktree', 'remove', '--force', checkout)
        command(ROOT / 'bin/hw', 'install')
    save(evidence / 'cleanup.json', dict(baseline=sorted(baseline), after=sorted(snapshot())))
    assert baseline == snapshot()
    (evidence / 'result.txt').write_text('PASS parent verified and head converse\n')
    return evidence


def run_disk(evidence, converse, project_name):
    from herdworks.pickup import close
    identity = json.loads((converse / 'doctor.json').read_text())
    os.environ['HW_HOME'] = identity['home']
    evidence.mkdir(parents=True, exist_ok=False)
    project = project_path(project_name)
    repo = json.loads((project / 'project.json').read_text())['repo']
    before = json.loads((converse / 'disk-before.json').read_text())['free']
    removed = []
    for item in task_paths(project):
        removed.extend(close(item.parent))
    registered = git(repo, 'worktree', 'list', '--porcelain')
    after = shutil.disk_usage(hw_home()).free
    save(evidence / 'disk.json', dict(before=before, after=after, delta=after-before,
                                    removed=removed, registered=registered))
    assert not list((project / 'tasks').glob('*/*/wt')), 'closed task worktree remains'
    assert str(project / 'tasks') not in registered, 'closed worktree still registered'
    assert abs(after - before) <= 200 * 1024 ** 2, 'disk differs by more than 200 MB'
    assert all(item.exists() for item in task_paths(project)), 'task records removed'
    (evidence / 'result.txt').write_text('PASS disk: task folders retained, no closed worktrees, free space within 200 MB\n')


FP6_JOURNEYS = ('schedule', 'issue-pickup', 'cap-and-switch')


def run_fp6(kind, evidence, timeout, project_name):
    from herdworks.limits import ROLES
    from herdworks.talk import inbox
    evidence.mkdir(parents=True, exist_ok=False)
    save(evidence / 'doctor.json', doctor('opencode'))
    baseline = snapshot()
    repo = evidence / 'repo'
    fixture(repo)
    project = project_path(project_name)
    def hw(*args):
        return command(ROOT / 'bin/hw', *args)
    try:
        hw('install')
        hw('project', 'add', project_name, '--repo', repo, '--prefix', 'HE')
        save(hw_home() / 'config.json', dict(agents={role: dict(agent='opencode', model='deepseek/deepseek-flash') for role in ROLES}))
        hw('project', 'grant', project_name, '--unsandboxed', '--gh', repo / 'planted/fake-gh.sh')
        git(repo, 'remote', 'add', 'origin', 'https://github.invalid/fixture/hello.git')
        trigger = 'schedule' if kind == 'schedule' else 'github-issue'
        instructions = 'Status question only: reply with the Project name and whether it has any tasks. Do not create a task.'
        args = ['automation', 'add', 'check-in', '--project', project_name, '--owner', 'fixture-owner',
                '--trigger', trigger, '--instructions', instructions, '--daily-cap', '1']
        if trigger == 'github-issue':
            args += ['--author', 'fixture-owner']
        hw(*args)
        data = json.loads((hw_home() / 'automations/check-in.json').read_text())
        due = data['next_run']
        def issues(numbers):
            save(evidence / 'fake-gh-issues.json', [dict(number=n, title='Project status question',
                body='Please answer the status question in the instructions; no task is requested.',
                url=f'https://github.invalid/fixture/hello/issues/{n}', state='OPEN',
                author=dict(login='fixture-owner'), labels=[dict(name='herdworks')]) for n in numbers])
        issues([1, 2] if kind == 'cap-and-switch' else [1])
        (evidence / 'preview.txt').write_text(hw('automation', 'test', 'check-in').stdout)
        assert not inbox(project)
        (evidence / 'early-tick.txt').write_text(hw('automations', 'tick', '--at', str(due - 1)).stdout)
        assert not inbox(project)
        (evidence / 'tick-1.txt').write_text(hw('automations', 'tick', '--at', str(due)).stdout)
        (evidence / 'tick-2.txt').write_text(hw('automations', 'tick', '--at', str(due + 60)).stdout)
        if kind == 'cap-and-switch':
            hw('automation', 'off', 'check-in')
            issues([3])
            (evidence / 'tick-off.txt').write_text(hw('automations', 'tick', '--at', str(due + 120)).stdout)
        messages = inbox(project)
        assert len(messages) == 1 and instructions in messages[0]['text']
        if trigger == 'github-issue':
            calls = [json.loads(line) for line in (evidence / 'fake-gh.jsonl').read_text().splitlines()]
            assert len([c for c in calls if c['args'][:2] == ['issue', 'edit']]) == 1
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(text.startswith('REPLY\n') for _, text in replies(project)):
                break
            session = hc.get(coordinator_name(project))
            if session.get('state') != 'live' or state_word(session) == 'blocked':
                raise RuntimeError('coordinator unavailable; inspect retained screen')
            hc.call('wait', session['address'], '--timeout', '10', '--json')
        else:
            raise RuntimeError('no real coordinator REPLY before deadline')
        (evidence / 'automations.txt').write_text(hw('automations').stdout)
        (evidence / 'history.txt').write_text(hw('automation', 'history', 'check-in').stdout)
        (evidence / 'status.txt').write_text(hw('status', project_name).stdout)
        shutil.copytree(hw_home() / 'automations', evidence / 'automations')
        save(evidence / 'result.json', dict(result='PASS', journey=kind, messages=len(messages),
             clock=due, boundary='Real CLI, hc, say and opencode/DeepSeek; fake gh, status-only fixture message. No timer installed.'))
    finally:
        if project.exists():
            collect(project, evidence)
            cleanup(project, evidence, baseline)
    return evidence


TIDY_GH = '''#!/usr/bin/env python3
import json, os
from pathlib import Path
import sys

args = sys.argv[1:]
record = dict(args=args)
if args[:2] == ['pr', 'create'] and '--draft' in args:
    record['body'] = Path(args[args.index('--body-file') + 1]).read_text()
    output = 'https://github.invalid/fixture/hello/pull/1'
elif args[:2] == ['pr', 'view']:
    state = Path(os.environ.get('HW_HOME', '.')) / 'fake-gh-state.txt'
    output = state.read_text().strip() if state.exists() else 'OPEN'
else:
    raise SystemExit('unsupported tidy-gh command')
log = Path.cwd().parent / 'fake-gh.jsonl'
with log.open('a') as stream:
    stream.write(json.dumps(record) + '\\n')
print(output)
'''


def run_tidy(evidence, timeout, project_name):
    evidence.mkdir(parents=True, exist_ok=False)
    save(evidence / 'doctor.json', doctor('opencode'))
    baseline = snapshot()
    save(evidence / 'baseline.json', sorted(baseline))
    repo = evidence / 'repo'
    fixture(repo)
    project = project_path(project_name)
    frames = []
    start = time.monotonic()
    failure = None
    def hw(*args, **kwargs):
        return command(ROOT / 'bin/hw', *args, **kwargs).stdout
    def frame(text):
        file = evidence / f'screen-{len(frames):04}.txt'
        file.write_text(text)
        frames.append(dict(at=time.monotonic() - start, captured_at=time.time(), path=file.name))
    gh = evidence / 'tidy-gh.sh'
    gh.write_text(TIDY_GH)
    gh.chmod(0o755)
    try:
        hw('install')
        (evidence / 'added.txt').write_text(hw('project', 'add', project_name, '--repo', repo, '--prefix', 'HE'))
        remote = evidence / 'remote.git'
        git(evidence, 'init', '--bare', remote)
        git(repo, 'remote', 'add', 'origin', remote)
        (evidence / 'grant.txt').write_text(hw('project', 'grant', project_name,
            '--gh', gh, '--push', '--draft-pr'))
        from herdworks.limits import ROLES
        settings = dict(agents={role: dict(agent='opencode', model='deepseek/deepseek-flash') for role in ROLES})
        save(hw_home() / 'config.json', settings)
        hw('project', 'grant', project_name, '--unsandboxed')
        (evidence / 'config.txt').write_text(hw('config'))
        output = hw('up', project_name)
        (evidence / 'started.txt').write_text(output)
        assert f'started {coordinator_name(project)}' in output
        brief = repo / 'briefs/shout.md'
        output = hw('say', project_name, '--file', brief)
        assert output.strip() == 'delivered 1'
        frame(f'$ bin/hw say {project_name} --file {brief}\n{output}')
        while time.monotonic() - start < timeout:
            items = task_paths(project)
            path = items[0].parent if items else None
            history = events(path) if path else []
            builds = [e for e in history if e.get('role') == 'build' and e.get('event') == 'session']
            outbox = replies(project)
            status = hw('tasks', project_name)
            (evidence / 'tasks.txt').write_text(status)
            text = hw('read', project_name)
            frame(status + '\n' + text)
            current = hc.get(coordinator_name(project))
            with (evidence / 'status.jsonl').open('a') as stream:
                stream.write(json.dumps(dict(elapsed=time.monotonic() - start, coordinator=current)) + '\n')
            if state_word(current) == 'blocked':
                raise RuntimeError('coordinator is blocked; inspect last screen')
            if path and not builds:
                data = read_task(path)
                data['roles'] = dict(build=str(ROOT / 'fixtures/hello/planted/apply-wrong.sh'))
                save(path / 'task.json', data)
            if path and (path / 'build-1/report.md').exists():
                data = read_task(path)
                if data.get('roles', {}).get('build'):
                    data['roles'].pop('build')
                    save(path / 'task.json', data)
            done = next((t for _, t in outbox if t.startswith('DONE\n') and 'HE-1' in t), None)
            if done and path:
                commit = built_commit(path)
                assert commit and commit in done
                url = 'https://github.invalid/fixture/hello/pull/1'
                assert f'HE-1 for review {commit} {url}' in status
                assert url in done
                assert git(remote, 'rev-parse', 'refs/heads/hw/HE-1') == commit
                assert len(builds) == 2, f'expected one fix round (two builders), got {len(builds)}'
                assert builds[0]['name'] != builds[1]['name'], 'fix round reused the first builder'
                bws = sorted(p.name for p in path.glob('build-*/wt'))
                assert len(bws) == 1, f'expected one builder worktree after the fix round, got {bws}'
                save(evidence / 'worktrees-before-tidy.json', dict(
                    builders=bws,
                    verifiers=sorted(p.name for p in path.glob('verify-*/wt')),
                    all=sorted(p.name for p in path.glob('*/wt'))))
                (hw_home() / 'fake-gh-state.txt').write_text('MERGED\n')
                tidied = hw('tidy', project_name)
                (evidence / 'tidy.txt').write_text(tidied)
                assert 'HE-1 closed' in tidied, f'tidy did not close HE-1: {tidied}'
                remaining = sorted(p.name for p in [*path.glob('build-*/wt'), *path.glob('verify-*/wt')])
                save(evidence / 'worktrees-after-tidy.json', remaining)
                assert remaining == [], f'worktrees remain after tidy: {remaining}'
                branch = git(repo, 'rev-parse', 'refs/heads/hw/HE-1')
                save(evidence / 'branch-after-tidy.json', dict(branch=branch, commit=commit))
                assert branch == commit, 'the task branch was not kept after tidy'
                after_tasks = hw('tasks', project_name)
                (evidence / 'tasks-after-tidy.txt').write_text(after_tasks)
                save(evidence / 'tasks-lists-after-tidy.json', dict(listed='HE-1' in after_tasks, output=after_tasks))
                assert 'HE-1' not in after_tasks, 'hw tasks still lists the closed task'
                collect(project, evidence)
                break
            hc.call('wait', current['address'], '--timeout', '3', '--json')
        else:
            raise RuntimeError(f'journey exceeded {timeout}s')
    except BaseException as error:
        failure = error
        (evidence / 'result.txt').write_text(f'FAIL tidy: {error}\n')
        if project.exists():
            collect(project, evidence)
    finally:
        save(evidence / 'screens.json', frames)
        if project.exists():
            cleanup(project, evidence, baseline)
    if failure:
        raise failure
    (evidence / 'result.txt').write_text('PASS tidy\n')
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('journey', choices=['doctor', 'regression', 'remote-converse', 'disk', 'tidy', *JOURNEYS, *FP3_JOURNEYS, *FP6_JOURNEYS])
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--converse-evidence', type=Path)
    parser.add_argument('--base', default='fh-3')
    parser.add_argument('--project', default='hello', help='unique scratch Project name for this journey')
    args = parser.parse_args()
    if args.journey == 'doctor':
        print(json.dumps(doctor()))
        return
    if not args.evidence:
        parser.error('--evidence is required')
    evidence = args.evidence.resolve()
    doctor('opencode')
    if args.journey == 'disk':
        if not args.converse_evidence:
            parser.error('--converse-evidence is required for disk')
        run_disk(evidence, args.converse_evidence.resolve(), args.project)
        print(f'PASS disk: {evidence}')
        return
    if args.journey == 'remote-converse' and not sys.platform.startswith('linux'):
        parser.error('remote-converse runs on the Linux host through hc exec --on')
    os.environ['HW_HOME'] = str(hw_home() / evidence.name)
    result = (regression(evidence, args.base) if args.journey == 'regression' else
              run_tidy(evidence, args.timeout, args.project) if args.journey == 'tidy' else
              run_fp6(args.journey, evidence, args.timeout, args.project) if args.journey in FP6_JOURNEYS else
              run_fp3(args.journey, evidence, args.timeout, args.project) if args.journey in FP3_JOURNEYS else
              run_journey('converse' if args.journey == 'remote-converse' else args.journey, evidence, args.timeout, args.project, remote=args.journey == 'remote-converse'))
    print(f'PASS {args.journey}: {result}')


if __name__ == '__main__':
    main()
