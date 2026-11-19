from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args, input=None):
    with tempfile.TemporaryDirectory(prefix="hw-hooks-") as hooks:
        result = subprocess.run(["git", "-c", f"core.hooksPath={hooks}", "-C", str(repo), *map(str, args)],
                                capture_output=True, text=True, input=input)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def read_task(path):
    return json.loads((Path(path) / "task.json").read_text())


def coordinator_task(path):
    return Path(path).parents[1] / "coordinator/tasks" / Path(path).name


def coordinator(path):
    record = Path(path).parents[1] / "coordinator.json"
    return json.loads(record.read_text()) if record.exists() else {}


def task_key(path):
    data = read_task(path)
    return f"{data['project']}:{data['id']}"


def events(path):
    return [json.loads(line) for line in (Path(path) / "events.jsonl").read_text().splitlines() if line]


def append_event(path, event):
    with (Path(path) / "events.jsonl").open("a") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")


def write_journal(marker, data):
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(data) + "\n")
    temporary.replace(marker)


@contextmanager
def locked(path):
    with (Path(path) / ".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def first_line(path):
    try:
        return next(iter(Path(path).read_text().splitlines()), "")
    except FileNotFoundError:
        return ""


def built_commit(path):
    data = read_task(path)
    report = newest_artifact(path, "build-*/report.md")
    match = re.fullmatch(r"READY ([0-9a-f]{40,64})", first_line(report) if report else "")
    if not match or match[1] == data["base"]:
        return None
    try:
        head = git(data["repo"], "rev-parse", "--verify", f"refs/heads/{data['branch']}")
    except RuntimeError:
        return None
    return head if match[1] == head else None


def newest_artifact(path, pattern):
    return max(Path(path).glob(pattern), key=lambda p: p.stat().st_mtime, default=None)


def waiting_on_answer(path):
    ask = coordinator_task(path) / 'ask.md'
    return ask.is_file() and not answered_since(path, ask.stat().st_mtime)


def escalation(path):
    """The open escalation event, or None once the user has answered it."""
    event = next((e for e in reversed(events(path)) if e.get('event') == 'escalated'), None)
    return event if event and not answered_since(path, event['at']) else None


def answers(path):
    """The owner's answers to a task, oldest first, as (number, time, text).

    A coordinator saves an answer it accepted as answers/N.md in its own folder; that counts while it
    matches the owner's numbered message. A task `hw run` drives has no coordinator to vouch for those
    files, so its answers are read from the inbox alone: the messages the owner addressed to it with
    `hw say --task`. Agent sessions cannot write the inbox, and only the owner may call that command."""
    inbox = Path(path).parents[1] / 'inbox.jsonl'
    messages = [json.loads(line) for line in inbox.read_text().splitlines() if line]
    if read_task(path).get('driver') == 'run':
        return [(m['number'], m['at'], m['text']) for m in messages if m.get('task') == Path(path).name]
    saved = {int(p.stem): p.read_text() for p in (coordinator_task(path) / 'answers').glob('*.md') if p.stem.isdecimal()}
    return [(m['number'], m['at'], m['text']) for m in messages
            if m['number'] in saved and saved[m['number']].strip() == m['text'].strip()]


def answered_since(path, asked_at):
    return any(at > asked_at for _, at, _ in answers(path))


def unheard(path):
    """Numbers of the owner's answers that the newest builder's brief does not carry.

    Each builder's session record lists the answers its brief quoted. Before the first builder
    there is nothing to miss: its brief will quote them all."""
    builder = next((e for e in reversed(events(path)) if e.get('event') == 'session' and e.get('role') == 'build'), None)
    if builder is None:
        return []
    return [number for number, _, _ in answers(path) if number not in builder.get('answers', [])]


def derive_status(path):
    path = Path(path)
    from .gate import check_gate
    from .pr import recorded_pr
    pr = recorded_pr(path)
    if pr:
        return 'needs manual verification' if pr.get('manual_verification') else 'for review'
    if is_stopped(path):
        return 'stopped'
    passed, commit, _ = check_gate(path)
    if passed:
        return 'verified'
    if escalation(path):
        return 'escalated'
    if waiting_on_answer(path):
        return "waiting on you"
    if any(e.get("event") == "session" and e.get("role") != "coordinator" for e in events(path)):
        return "in progress"
    return "queued"


def is_stopped(path):
    return next((e["event"] == "stop" for e in reversed(events(path))
                 if e.get("event") in ("stop", "session", "resumed")), False)


ARTIFACT = {"build": "report.md", "verify": "verdict.md", "evidence": "review.md"}


def artifact_complete(folder, role):
    line = first_line(folder / ARTIFACT[role])
    if role == "build":
        return line == "BLOCKED" or re.fullmatch(r"READY [0-9a-f]{40,64}", line) is not None
    return line in ({"PASS", "FAIL", "INCONCLUSIVE"} if role == "verify" else {"CONFIRMED", "REJECTED", "INCONCLUSIVE"})
