"""`hw run`: take one task from a request to a verified branch or draft pull request.

No coordinator agent is involved. The loop reads the records the gate reads, does the one next
thing they call for with the existing tools (spawn, gate, reap, pr) and repeats. A resumed run
is the same loop, so it continues from whatever already exists."""
from dataclasses import dataclass
import fcntl
import json
import math
import os
import tempfile
import time
from pathlib import Path
from . import hc, monitor
from .gate import blocked_requirements, check_gate, checks_command, claim_problems, environment_only, gate, reap, run_checks
from .limits import role_settings
from .pickup import stop
from .pr import open_pr, recorded_pr
from .probe import probe
from .projects import new_task, read_project
from .runs import (ARTIFACT, ROOT, answered_since, append_event, artifact_complete, built_commit, coordinator_task,
                   escalation, events, first_line, is_stopped, locked, newest_artifact, read_task, task_key)
from .spawn import spawn

SETTLE = 20  # seconds a live worker gets to end its turn after its artifact appears
INTENT = ("Goal and done check: the original request in brief.md, exactly as written. `hw run` started this\n"
          "task without a coordinator, so nobody restated it: derive the acceptance criteria from the request.\n")
EXIT = {"done": 0, "blocked": 2, "failed": 1}


@dataclass
class Step:
    """What one turn of the loop found: the task's state and stage, and whether to wait before the next turn."""
    state: str = "running"
    stage: str = "queued"
    action: str = None
    reason: str = None
    next_step: str = None
    wait: bool = False
    retry: tuple = None  # the (role, replaces) a limit is holding back; only that start is tried again


def commands(path):
    data = read_task(path)
    name, task = data["project"], data["id"]
    resume = f"hw run -p {name} --resume {task}"
    return dict(resume=resume, answer=f'hw say {name} --task {task} "YOUR DECISION"',
                inspect=f"look at it with: hw status {task}. {resume} tries the same step again; if that cannot pass, "
                        f"end it with: hw stop {name} {task}, and start a fresh task with: hw run -p {name} \"...\"")


def positive(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def drivable(path):
    """Refuse a task `hw run` must not touch, before anything about it is changed."""
    data = read_task(path)
    if data.get("driver") != "run":
        raise ValueError(f"{data['id']} is the Project coordinator's task; hw run continues only tasks it started")
    if any(e.get("event") == "closed" for e in events(path)):
        raise ValueError(f"{data['id']} is closed; start a new task with: hw run -p {data['project']} \"...\"")
    return data


def create(project, text, base=None, kind="build", max_minutes=None, max_tokens=None):
    """Create a task that `hw run` drives. Settings that would stop its first worker are refused here."""
    read_project(project)
    if not text or not text.strip():
        raise ValueError('say what you want: hw run -p PROJECT "..."')
    for role in ("build", "verify", "evidence"):
        role_settings(project, role)
    extra = {"driver": "run"}
    for name, value in (("max_minutes", max_minutes), ("max_tokens", max_tokens)):
        if value is not None:
            extra[name] = positive(name, value)
    with tempfile.TemporaryDirectory(prefix="hw-run-") as folder:
        brief = Path(folder) / "brief.md"
        brief.write_text(text)
        path, _ = new_task(project, brief, base=base, kind=kind, extra=extra)
    # Worker briefs quote the coordinator's restated intent; without a coordinator the request stands as written.
    (coordinator_task(path) / "intent.md").write_text(INTENT)
    now = time.time()
    monitor.write(path, state="running", stage="queued", pid=os.getpid(), active_seconds=0,
                  run_started_at=now, heartbeat_at=now, ended_at=None)
    return path


def set_budget(path, max_minutes=None, max_tokens=None):
    drivable(path)
    changes = {name: positive(name, value) for name, value in (("max_minutes", max_minutes), ("max_tokens", max_tokens))
               if value is not None}
    if changes:
        with locked(path):
            data = dict(read_task(path), **changes)
            temporary = path / ".task.json.tmp"
            temporary.write_text(json.dumps(data, indent=2) + "\n")
            temporary.replace(path / "task.json")


def start(path, role, replaces=None):
    stage = "build" if role == "fix" else role
    try:
        spawn(path, role, replaces=replaces)
    except ValueError as error:
        text = str(error)
        if text.startswith("queued: "):
            return Step(stage="queued", action=f"waiting for a free place: held by {text[8:]}", wait=True,
                        retry=(role, replaces))
        return Step("blocked", stage, reason=f"no {role} worker was started: {text}", next_step=commands(path)["inspect"])
    return Step(stage=stage)


def deliver(path, commit, manual=False):
    """End a task the gate passed: a draft pull request when the Project grants it, else the verified branch."""
    data = read_task(path)
    name, task = data["project"], data["id"]
    where = f"commit {commit} on branch {data['branch']} in {data['repo']}"
    grants = read_project(path.parents[1]).get("grants", {})
    missing = [grant for grant in ("push", "draft-pr") if grants.get(grant) is not True]
    flag = " --manual-verification" if manual else ""
    if missing and manual:
        return Step("blocked", "pr", reason="needs manual verification of: " + "; ".join(blocked_requirements(path))
                    + f". Everything else passed for {where}",
                    next_step=f"check those by hand; to hand it over as a draft: hw project grant {name} --push --draft-pr, "
                              f"then hw pr {name} {task}{flag}")
    if missing:
        return Step("done", "done", reason=f"verified: {where}. No pull request, because the Project has not granted "
                    + ", ".join(missing),
                    next_step=f"review the branch; for draft pull requests: hw project grant {name} --push --draft-pr")
    try:
        url = open_pr(path, manual_verification=manual)
    except (ValueError, RuntimeError) as error:
        return Step("blocked", "pr", reason=f"{'built' if manual else 'verified'}: {where}, but the draft pull request "
                    f"was not opened: {error}", next_step=f"fix the cause, then: hw pr {name} {task}{flag}")
    return Step("done", "done", reason=("needs manual verification; " if manual else "verified; ") + f"draft pull request: {url}",
                next_step="review and merge it")


def escalated(path):
    raised = escalation(path)
    if not raised:
        return None
    return Step("blocked", "gate", reason=f"the gate refused {raised['failures']} commits for the same reasons: "
                + "; ".join(raised["reasons"]), next_step=f"decide what should change, then: {commands(path)['answer']}")


def judge(path, checks=None):
    """Run the gate and act on its answer: deliver, start a fix round, hand over, or stop for a person."""
    if checks is None:
        # Checks that passed on this commit before its verifier started are not run a second time.
        checks = next((e["checks"] for e in reversed(events(path)) if e.get("event") == "run" and e.get("checks")
                       and e.get("checked") == built_commit(path)), None)
    passed, commit, reasons = gate(path, checks=checks)
    if passed:
        return deliver(path, commit)
    raised = escalated(path)
    if raised:
        return raised
    verdict = newest_artifact(path, "verify-*/verdict.md")
    review = newest_artifact(path, "evidence-*/review.md")
    spike = read_task(path).get("kind") == "spike"  # a spike reports findings; a no is never "fixed" into a yes
    if (any(reason.startswith("checks command exited") for reason in reasons)
            or (not spike and ((verdict and first_line(verdict) == "FAIL") or (review and first_line(review) == "REJECTED")))):
        return start(path, "fix")
    if blocked_requirements(path) and check_gate(path, manual_verification=True)[0]:
        return deliver(path, commit, manual=True)
    return Step("blocked", "gate", reason="the gate refused: " + "; ".join(reasons), next_step=commands(path)["inspect"])


def advance(path, now=None):
    """Do the one next thing the task's records call for and say what state that leaves it in."""
    path = Path(path)
    now = time.time() if now is None else now
    data, history, say = read_task(path), events(path), commands(path)
    pr = recorded_pr(path)
    if pr:
        return Step("done", "done", reason=("needs manual verification; " if pr.get("manual_verification") else "verified; ")
                    + f"draft pull request: {pr['url']}", next_step="review and merge it")
    workers = [e for e in history if e.get("event") == "session" and e.get("role") in ARTIFACT]
    last = workers[-1] if workers else None
    if is_stopped(path):
        return Step("blocked", last["role"] if last else "queued", reason="stopped: its workers were ended",
                    next_step=f"continue with: {say['resume']}")
    raised = escalated(path)
    if raised:
        return raised
    if last is None:
        return start(path, "build")
    role, folder = last["role"], path / last["folder"]
    artifact = folder / ARTIFACT[role]
    session = hc.get(last["address"])
    live = session.get("state") == "live"
    if not artifact_complete(folder, role):
        if live and not next((fact["stalled"] for fact in probe(path) if fact["name"] == last["name"]), False):
            return Step(stage=role, wait=True)
        # A stalled or dead worker without its artifact is replaced; spawn allows two replacements a step.
        return start(path, role, replaces=last["name"])
    status = session.get("status")
    status = status.get("state") if isinstance(status, dict) else status
    if live and status not in ("idle", "done") and now - artifact.stat().st_mtime < SETTLE:
        return Step(stage=role, wait=True)
    reap(path)
    opening = first_line(artifact)
    if role == "build":
        if opening == "BLOCKED":
            if answered_since(path, artifact.stat().st_mtime):
                append_event(path, {"event": "rewind", "at": time.time()})
                return start(path, "build")  # a held start is retried by the loop, so one answer rewinds once
            question = " ".join(artifact.read_text().splitlines()[1:2]) or f"see {artifact}"
            return Step("blocked", "build", reason=f"the builder needs a decision: {question}", next_step=say["answer"])
        commit = built_commit(path)
        if not commit:
            return Step("blocked", "build", reason=f"the builder reported READY, but not for a new head of {data['branch']}",
                        next_step=f"read {artifact}; {say['inspect']}")
        if any(e.get("role") == "verify" and e.get("commit") == commit for e in workers):
            return Step("blocked", "build", reason=f"the fix builder reported READY without a new commit; {commit} "
                        "was already refused", next_step=f"read {artifact}; {say['inspect']}")
        checked = any(e.get("event") == "run" and e.get("checked") == commit for e in history)
        if checks_command(path.parents[1]) and not checked:
            # Checks cost no tokens, so they run before a verifier is spent on the commit.
            ran = run_checks(path, commit)
            if ran["exit"]:
                return judge(path, ran)
            monitor.note(path, f"checks passed: {ran['command']}", checked=commit, checks=ran)
        return start(path, "verify")
    if role == "verify":
        if environment_only(artifact) or (opening == "PASS" and not claim_problems(folder, data.get("kind"))):
            return start(path, "evidence")
        if opening == "FAIL" and data.get("kind") != "spike":
            return judge(path)
        # An inconclusive verdict or unusable claims get one more verifier; spawn refuses when a person is needed.
        step = start(path, "verify")
        if step.state == "blocked":
            ask = next((text for text in artifact.read_text().splitlines() if text.startswith("Ask:")), "")
            step.reason = f"the verifier's verdict was {opening or 'unusable'} and {step.reason}. {ask}".strip()
            step.next_step = f"do what it asks, then: {say['answer']}"
        return step
    return judge(path)


def drive(path, interval=5.0, announce=None, sleep=time.sleep):
    """Drive the task until it is done, blocked or failed; return its final status record."""
    path = Path(path)
    data = drivable(path)
    with (path / ".driver.lock").open("a") as lock:
        # The lock is held for as long as this process drives the task; `hw status` reads it to tell whether
        # a driver is alive. A status read holds it for an instant, so one refusal is tried again briefly.
        for attempt in range(10):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if attempt == 9:
                    raise ValueError(f"{data['id']} is already being driven; follow it with: hw watch {data['id']}") from None
                time.sleep(0.05)
        return _drive(path, interval, announce, sleep)


def _drive(path, interval, announce, sleep):
    say = commands(path)
    if is_stopped(path):
        append_event(path, {"event": "resumed", "at": time.time()})
    before = monitor.saved(path)
    # Time already spent driving counts; a run that died without saying so is counted up to its last heartbeat.
    banked = before.get("active_seconds", 0) + (max(0.0, before.get("heartbeat_at", 0) - before["run_started_at"])
                                                if before.get("run_started_at") and before.get("pid") != os.getpid() else 0)
    started = before["run_started_at"] if before.get("pid") == os.getpid() else time.time()
    stage = before.get("stage", "queued")
    monitor.write(path, state="running", stage=stage, reason=None, next_step=None, pid=os.getpid(),
                  active_seconds=banked, run_started_at=started, heartbeat_at=time.time(), ended_at=None)

    def finish(step, kind=None):
        now = time.time()
        monitor.note(path, f"{step.state}: {step.reason}")
        monitor.write(path, state=step.state, stage=step.stage, reason=step.reason, next_step=step.next_step, pid=None,
                      active_seconds=banked + now - started, run_started_at=None, heartbeat_at=now, ended_at=now)
        monitor.notify(path, monitor.record(path), kind or step.state)
        current = monitor.record(path)
        if announce:
            announce(current)
        return current

    shown = pending = None
    try:
        while True:
            current = monitor.record(path)
            if announce:
                announce(current)
            spent = monitor.over_budget(path, current)
            if spent:
                stop(path)
                return finish(Step("blocked", stage, reason=spent, next_step="raise the budget and continue: "
                                   f"{say['resume']} --max-minutes N (or --max-tokens N)"), "budget")
            # While a limit holds a start back, only that start is tried again: the gate and the checks
            # that led to it are not run once more on every turn.
            step = start(path, *pending) if pending else advance(path)
            stage, pending = step.stage, step.retry
            if step.state != "running":
                return finish(step)
            if step.action and step.action != shown:
                monitor.note(path, step.action)
            shown = step.action
            monitor.write(path, stage=stage, heartbeat_at=time.time())
            if step.wait:
                sleep(interval)
    except KeyboardInterrupt:
        return finish(Step("blocked", stage, reason="hw run was interrupted; workers it started keep working",
                           next_step=f"continue with: {say['resume']}"))
    except Exception as error:
        return finish(Step("failed", stage, reason=f"{type(error).__name__}: {error}",
                           next_step=f"fix the cause, then continue with: {say['resume']}"))


def detach(path):
    """Start the same loop in its own herdr core terminal, so it outlives this shell."""
    path = Path(path)
    data = read_task(path)
    drivable(path)
    before = monitor.saved(path)
    if monitor.driven(path):
        raise ValueError(f"{data['id']} is already being driven; follow it with: hw watch {data['id']}")
    name = f"hw-{data['project']}-{data['id'].lower()}-run"[:32]
    # The label key differs from the workers' `hw` label, so stopping the task's workers never ends its driver.
    result = hc.call("run", "--bg", "--json", "--no-parent", "--name", name, "--cwd", path,
                     "--label", f"hwrun={task_key(path)}", "--label", "role=driver", "--",
                     "env", f"HW_HOME={path.parents[3]}", str(ROOT / "bin/hw"), "run", "-p", data["project"],
                     "--resume", data["id"])
    # Return once the new process has taken the task over, so a caller can follow it at once.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        now = monitor.saved(path)
        taken = now.get("pid") not in (None, os.getpid(), before.get("pid"))
        ended = now.get("updated_at", 0) > before.get("updated_at", 0) and now.get("state") != "running"
        if taken or ended:
            return result
        time.sleep(0.2)
    raise RuntimeError(f"the background run did not start; read its screen with: hc read {name}")
