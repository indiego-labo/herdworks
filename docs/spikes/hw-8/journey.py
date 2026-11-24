"""Run from the pinned candidate in the isolated owner shell."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

root = Path.cwd()
scratch = root.parent
evidence = scratch / 'evidence'
hw = root / 'bin/hw'
spec = importlib.util.spec_from_file_location(
    'verify_herdworks', root / '.agents/skills/verify-herdworks/scripts/journey.py')
journey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journey)
project = journey.project_path('live')


def run(*command, expected=0):
    argv = list(map(str, command))
    result = subprocess.run(argv, text=True, capture_output=True, timeout=180)
    with (evidence / 'commands.jsonl').open('a') as stream:
        print(json.dumps(dict(argv=argv, exit=result.returncode,
                              stdout=result.stdout, stderr=result.stderr)), file=stream)
    if expected is not None and result.returncode != expected:
        raise RuntimeError(f'{argv}: exit {result.returncode}: {result.stderr or result.stdout}')
    return result.stdout


def wait_file(file, timeout=25):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if file.is_file() and file.stat().st_size:
            return
        time.sleep(.1)
    raise RuntimeError(f'fixture did not produce {file}')


def check_intake(coordinator):
    request = 'Investigate the password-manager report and required migration'
    proposal = dict(level='yellow', reason='Requires a production migration',
                    reproduction='unreproduced', confidence='low')
    flags = ('--impact', proposal['level'], '--impact-reason', proposal['reason'],
             '--reproduction', proposal['reproduction'], '--confidence', proposal['confidence'])
    assert run(hw, 'say', 'live', request, *flags).strip() == 'delivered 1'
    wait_file(project / 'coordinator/outbox/000001.md')
    wait_file(evidence / 'coordinator-commands.jsonl')
    assert 'Message: 1\nTask: LV-1' in run(hw, 'read', 'live')
    task = project / 'tasks/LV-1'
    assert journey.read_task(task)['impact'] == proposal
    entry = json.loads((project / 'inbox.jsonl').read_text())
    assert entry['number'] == 1 and entry['text'] == request and entry['impact'] == proposal
    assert (task / 'brief.md').read_text() == request
    run('hc', 'read', coordinator, '--json')
    for view in ('tasks', 'status'):
        assert 'reproduction=unreproduced confidence=low' in run(hw, view, 'live')
    journey.save(evidence / 'initial-task.json', journey.read_task(task))

    run('ps', '-p', str(os.getpid()), '-o', 'pid=,ppid=,comm=')
    project_bytes = (project / 'project.json').read_bytes()
    gate_before = run(hw, 'gate', 'live', 'LV-1', expected=1)
    run(hw, 'pr', 'live', 'LV-1', expected=1)
    assert 'has not granted push, draft-pr' in (evidence / 'commands.jsonl').read_text().splitlines()[-1]
    corrected = '[impact=red (owner correction) Needs Architect reproduction=unreproduced confidence=high]'
    assert corrected in run(hw, 'task', 'correct-impact', 'live', 'LV-1', 'red',
                            '--reason', 'Needs Architect', '--confidence', 'high')
    assert run(hw, 'say', 'live', '--number', '1', *flags).strip() == 'delivered 1 repeat'
    wait_file(project / 'coordinator/outbox/000002.md')
    assert 'Repeat for LV-1' in run(hw, 'read', 'live')
    assert len((project / 'inbox.jsonl').read_text().splitlines()) == 1
    assert list((project / 'tasks').glob('*/task.json')) == [task / 'task.json']
    assert journey.read_task(task)['impact'] == dict(proposal, level='red',
                                                    reason='Needs Architect', confidence='high', corrected=True)
    for view in ('tasks', 'status'):
        assert corrected in run(hw, view, 'live')
    assert gate_before == run(hw, 'gate', 'live', 'LV-1', expected=1)
    run(hw, 'pr', 'live', 'LV-1', expected=1)
    assert 'has not granted push, draft-pr' in (evidence / 'commands.jsonl').read_text().splitlines()[-1]
    assert project_bytes == (project / 'project.json').read_bytes()


def check_legacy():
    request = 'Legacy request without assessment'
    assert run(hw, 'say', 'live', request).strip() == 'delivered 2'
    wait_file(project / 'coordinator/outbox/000003.md')
    assert 'Message: 2\nTask: LV-2' in run(hw, 'read', 'live')
    task = project / 'tasks/LV-2'
    assert 'impact' not in journey.read_task(task)
    assert 'impact' not in json.loads((project / 'inbox.jsonl').read_text().splitlines()[1])
    assert (task / 'brief.md').read_text() == request
    deadline = time.monotonic() + 85
    while True:
        launch = next((event for event in journey.events(task) if event['event'] == 'session'), None)
        if launch:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('no recorded worker launch')
        time.sleep(.15)
    observed = json.loads(run('hc', 'get', '--json', launch['address']))
    if observed.get('first_message', {}).get('sent') is False:
        brief = task / 'build-1/brief.md'
        run('hc', 'send', launch['address'], f'Read {brief} in full and do what it says.')
    wait_file(evidence / 'worker-probe.jsonl')
    assert json.loads((evidence / 'worker-probe.jsonl').read_text())['exit'] == 0
    assert launch['role'] == 'build' and launch['launch_source'] == 'template'
    run('hc', 'get', '--json', launch['address'])
    run('hc', 'read', '--json', launch['address'])
    run(hw, 'probe', 'live', 'LV-2')


def main():
    run('git', 'rev-parse', 'HEAD')
    run('git', 'status', '--porcelain')
    run('hc', '--version')
    run('codex', '--version')
    run('uname', '-srm')
    run('python3', '--version')
    run('git', '--version')
    journey.save(evidence / 'doctor.json', journey.doctor())
    baseline = journey.snapshot()
    assert not baseline
    run(hw, 'install')
    fixture = scratch / 'repo'
    journey.fixture(fixture)
    run(hw, 'project', 'add', 'live', '--repo', fixture, '--prefix', 'LV')
    try:
        # Only the scratch core's PATH has the inert Codex stand-in.
        address = json.loads(run('hc', 'run', '--bg', '--json', '--no-parent', '--no-notify',
                                 '--name', 'hw-live-coord', '--label', 'hw=project:live',
                                 '--label', 'role=coordinator', '--cwd', project / 'coordinator',
                                 '--', 'python3', scratch / 'terminal-fixture.py'))
        (project / 'coordinator.json').write_text(json.dumps(address))
        try:
            run('hc', 'wait', address['address'], '--output', 'fixture ready', '--timeout', '10', '--json')
            check_intake(address['address'])
            check_legacy()
        finally:
            run('hc', 'ls', '--all', '--json')
    finally:
        try:
            journey.collect(project, evidence)
        finally:
            journey.cleanup(project, evidence, baseline)
        run('git', '-C', fixture, 'worktree', 'list', '--porcelain')
    run('git', 'status', '--porcelain')


if __name__ == '__main__':
    main()
