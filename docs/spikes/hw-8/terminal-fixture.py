#!/usr/bin/env python3
"""PTY receiver for the scratch coordinator and final Codex adapter boundary."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tty

root = Path(os.environ['HW_HOME']).parent
evidence = root / 'evidence'
hw = root / 'candidate/bin/hw'


def record(filename, **data):
    with (evidence / filename).open('a') as stream:
        print(json.dumps(data), file=stream)


def run(*args):
    result = subprocess.run([str(hw), *args], text=True, capture_output=True, timeout=75)
    record('coordinator-commands.jsonl', argv=[str(hw), *args],
           exit=result.returncode, stdout=result.stdout, stderr=result.stderr)
    return result


def receive():
    # herdr pastes either plain bytes or bracketed paste, then sends Enter.
    data = b''
    while True:
        byte = os.read(0, 1)
        if not byte:
            raise EOFError('scratch PTY closed')
        data += byte
        if data.startswith(b'\x1b[200~'):
            if data.endswith((b'\x1b[201~\r', b'\x1b[201~\n')):
                break
        elif data.endswith((b'\r', b'\n')):
            # The plain delivery itself contains one separator before the request.
            if len(data.splitlines()) >= 2 or not data.startswith(b'MESSAGE '):
                break
    return data.decode().removeprefix('\x1b[200~').removesuffix('\r').removesuffix('\n').removesuffix('\x1b[201~').replace('\r\n', '\n').replace('\r', '\n')


def worker_identity():
    return dict(pid=os.getpid(), cwd=str(Path.cwd()), terminal=os.environ.get('HC_TERMINAL_ID'),
                hop=os.environ.get('HW_HC_HOP'), forwarded_caller=os.environ.get('HW_CALLER_TERMINAL'))


def run_worker(*args):
    argv = [str(hw), *args]
    result = subprocess.run(argv, text=True, capture_output=True, timeout=25)
    print((result.stdout + result.stderr).replace('\n', '\r\n'), end='', flush=True)
    return dict(argv=argv, exit=result.returncode, stdout=result.stdout, stderr=result.stderr,
                **worker_identity())


def worker_checks():
    record('worker-process.jsonl', argv=sys.argv, **worker_identity())
    prompt = receive()
    record('worker-input.jsonl', text=prompt, **worker_identity())
    brief_path = Path('../brief.md').resolve()
    assert 'Legacy request without assessment' in brief_path.read_text()
    assert f'Read {brief_path} in full' in prompt
    print(f'fixture received prompt for {brief_path}\r', flush=True)
    record('worker-probe.jsonl', **run_worker('probe', 'live', 'LV-2'))

    for verb in ('correct-impact', 'impact'):
        stimulus = receive()
        record('worker-input.jsonl', text=stimulus, **worker_identity())
        assert stimulus == f'CHECK WORKER {verb}', stimulus
        record(f'worker-{verb}.jsonl', stimulus=stimulus,
               **run_worker('task', verb, 'live', 'LV-1', 'green',
                            '--reason', f'Build worker attempted {verb}'))
    # Stay live while the driver captures identity and terminal text.
    receive()


def main():
    worker = Path(sys.argv[0]).name == 'codex'
    tty.setraw(0)
    # Advertise bracketed paste and report idle for the automatic first-message guard.
    print('\x1b[?2004h\x1b]7501;state=idle\x07fixture ready\r', flush=True)
    if worker:
        worker_checks()
        return
    for sequence in range(1, 4):
        received = receive()
        print(f'fixture received: {received}'.replace('\n', '\r\n') + '\r', flush=True)
        number, request = re.fullmatch(r'MESSAGE ([0-9]+)\n(.+)', received).groups()
        record('pty-delivery.jsonl', number=int(number), request=request,
               terminal=os.environ.get('HC_TERMINAL_ID'))
        assert run('tidy', 'live').returncode == 0
        created = run('task', 'new', 'live', '--message', number)
        assert created.returncode == 0, created.stderr
        task = created.stdout.split()[0]
        repeated = ' repeat' in created.stdout
        if not repeated:
            intent = Path('tasks') / task / 'intent.md'
            intent.write_text('Read and probe the scratch task using the worker protocol.\n')
        reply = Path('outbox') / f'{sequence:06d}.md'
        temporary = Path('.reply.tmp')
        action = 'Repeat for' if repeated else 'Acknowledged as'
        temporary.write_text(f'REPLY\nMessage: {number}\nTask: {task}\n\n{action} {task}.\n')
        temporary.replace(reply)
        if number == '1' and not repeated:
            denied = run('task', 'correct-impact', 'live', task, 'green', '--reason', 'Session must be denied')
            assert denied.returncode == 1 and 'owner outside Herdworks sessions' in denied.stderr
        if number == '1' and repeated:
            denied = run('task', 'impact', 'live', task, 'green', '--reason', 'Must preserve correction')
            assert denied.returncode == 1 and 'owner correction is in effect' in denied.stderr
        if number == '2':
            os.environ['PATH'] = f"{root / 'shim'}:{os.environ['PATH']}"
            assert Path(shutil.which('codex')).resolve() == Path(__file__).resolve()
            result = run('spawn', 'live', task, 'build')
            assert result.returncode == 0 or 'first message was not sent' in result.stderr, result.stderr
            # Keep the worker's real parent available through evidence capture.
            receive()


if __name__ == '__main__':
    main()
