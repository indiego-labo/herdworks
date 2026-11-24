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


def main():
    worker = Path(sys.argv[0]).name == 'codex'
    tty.setraw(0)
    # Advertise bracketed paste and leave a visible prompt for herdr's startup guard.
    print('\x1b[?2004hfixture ready\r', flush=True)
    if worker:
        record('worker-process.jsonl', pid=os.getpid(), cwd=str(Path.cwd()),
               terminal=os.environ.get('HC_TERMINAL_ID'), argv=sys.argv)
    for sequence in range(1, 4):
        received = receive()
        print(f'fixture received: {received}'.replace('\n', '\r\n') + '\r', flush=True)
        if worker:
            record('worker-input.jsonl', text=received)
            brief = Path('../brief.md').read_text()
            assert 'Legacy request without assessment' in brief
            expected_path = Path('../brief.md').resolve()
            assert f'Read {expected_path} in full' in received
            assert run_worker_probe(brief)
            return
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


def run_worker_probe(brief):
    result = run('probe', 'live', 'LV-2')
    record('worker-probe.jsonl', brief=brief, exit=result.returncode,
           stdout=result.stdout, stderr=result.stderr)
    return result.returncode == 0


if __name__ == '__main__':
    main()
