"""A task's status record: where it is, how long it has run, what it has used and what it did last.

`hw run` saves its state in the task's status.json. Everything else in the record (elapsed time,
tokens, sessions, the last action) is read fresh from the task's records each time, so the same
record also describes a task the coordinator drives."""
import fcntl
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from . import hc, tokens
from .limits import budget, project_setting
from .pr import recorded_pr, redact
from .probe import newest_file
from .runs import (ARTIFACT, append_event, artifact_complete, built_commit, coordinator_task, derive_status,
                   escalation, events, first_line, read_task, write_journal)

DERIVED = {"verified": "done", "for review": "done", "needs manual verification": "done",
           "stopped": "blocked", "escalated": "blocked", "waiting on you": "blocked"}


def saved(path):
    file = Path(path) / "status.json"
    return json.loads(file.read_text()) if file.is_file() else {}


def write(path, **changes):
    """Save the driver's state. Free text is redacted here, so nothing downstream repeats a secret."""
    for name in ("reason", "next_step"):
        if changes.get(name):
            changes[name] = redact(changes[name])
    own = dict(saved(path), **changes, updated_at=time.time())
    write_journal(Path(path) / "status.json", own)
    return own


def note(path, action, **facts):
    """Add a line to the task's timeline for something no other event records."""
    append_event(path, {"event": "run", "at": time.time(), "action": redact(action), **facts})


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def driven(path):
    """True while a `hw run` process holds the task's driver lock. The lock dies with its process, so
    unlike a saved pid it cannot be mistaken for another program after a crash or a restart."""
    try:
        with (Path(path) / ".driver.lock").open() as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False
    except FileNotFoundError:
        return False


def timeline(path):
    """Every timestamped fact about the task, oldest first, as (time, text)."""
    path = Path(path)
    facts = []
    for event in events(path):
        kind, at = event.get("event"), event.get("at") or event.get("started_at")
        if not at:
            continue
        name = event.get("name")
        text = {"session": f"started {event.get('role')} {name}" + (f", replacing {event['replaces']}" if event.get("replaces") else ""),
                "gate": "gate VERIFIED" if event.get("passed") else "gate REFUSED: " + "; ".join(event.get("reasons", [])),
                "run": event.get("action"), "pr": f"opened draft pull request {event.get('url')}",
                "stop": "stopped its workers", "resumed": "resumed", "closed": "closed",
                "escalated": f"escalated: the same refusal on {event.get('failures')} commits",
                "stalled": f"{name} ended without its {ARTIFACT.get(event.get('step', '').split(':')[0], 'artifact')}"}.get(kind)
        if text:
            facts.append((at, text[:300]))
        if kind == "session" and event.get("role") in ARTIFACT:
            artifact = path / event["folder"] / ARTIFACT[event["role"]]
            if artifact_complete(artifact.parent, event["role"]):
                facts.append((artifact.stat().st_mtime, f"{event['role']} {name} reported {first_line(artifact)}"))
    return sorted(facts)


def sessions(path, now):
    """Each worker session: its role, agent, running time and the tokens its agent reports."""
    path = Path(path)
    found, history = [], events(path)
    for index, event in enumerate(history):
        role = event.get("role")
        if event.get("event") != "session" or role not in ARTIFACT:
            continue
        folder = path / event["folder"]
        artifact = folder / ARTIFACT[role]
        live = bool(event.get("address")) and hc.get(event["address"]).get("state") == "live"
        finished = artifact_complete(folder, role)
        # A worker that ended without its artifact ran until the next recorded event: its stop or replacement.
        later = next((e.get("at") or e.get("started_at") for e in history[index + 1:] if e.get("at") or e.get("started_at")),
                     max(newest_file(folder), event["started_at"]))
        end = artifact.stat().st_mtime if finished else now if live else later
        used = tokens.read(event.get("agent"), folder / ("work" if role == "evidence" else "wt"), event["started_at"])
        found.append(dict(name=event["name"], role=role, agent=event.get("agent") or "unknown", model=event.get("model"),
                          state="working" if live and not finished else "finished" if finished else "ended",
                          live=live, started_at=event["started_at"], seconds=round(max(0.0, end - event["started_at"]), 1),
                          tokens=used or "unknown"))
    return found


def token_summary(workers):
    """Tokens per role and in total. A number is a sum of what agents reported; nothing is estimated."""
    summary, partial = {}, False
    for worker in workers:
        role, used = worker["role"], worker["tokens"]
        if used == "unknown":
            partial = True
            summary.setdefault(role, "unknown")
        else:
            summary[role] = used["total"] + (summary[role] if isinstance(summary.get(role), int) else 0)
    known = [value for value in summary.values() if isinstance(value, int)]
    return dict(summary, total=sum(known) if known else "unknown", partial=partial)


def record(path, now=None):
    """The task's status record as a plain dict; see docs/reference.md for the fields."""
    path = Path(path)
    now = time.time() if now is None else now
    data, own, history = read_task(path), saved(path), events(path)
    name, task = data["project"], data["id"]
    status = "closed" if any(e.get("event") == "closed" for e in history) else derive_status(path)
    workers = sessions(path, now)
    facts = timeline(path)
    pr = recorded_pr(path)
    run = data.get("driver") == "run"
    resume = f"hw run -p {name} --resume {task}"
    if run and own:
        state, stage, reason, next_step = own["state"], own["stage"], own.get("reason"), own.get("next_step")
        until = now
        # A run that was just created has not taken its lock yet; for that moment its saved pid stands in.
        starting = now - own.get("updated_at", 0) < 30 and alive(own.get("pid"))
        if state == "running" and not driven(path) and not starting:
            # The driver died without saying so: its time counts up to its last heartbeat.
            state, until = "blocked", own.get("heartbeat_at", now)
            reason = "hw run is no longer running for this task; any worker it started may still be working"
            next_step = f"continue with: {resume}"
        elapsed = own.get("active_seconds", 0) + (max(0.0, until - own["run_started_at"])
                                                  if own.get("run_started_at") else 0)
        ended = own.get("ended_at")
    else:
        state = "done" if status == "closed" else DERIVED.get(status, "running")
        stage = "done" if state == "done" else workers[-1]["role"] if workers else "queued"
        reason = next_step = None
        if status == "waiting on you":
            reason = "the coordinator asked: " + first_line(coordinator_task(path) / "ask.md")
            next_step = f'answer with: hw say {name} "YOUR DECISION"'
        elif status == "escalated":
            raised = escalation(path)
            reason = f"the gate refused {raised['failures']} commits for the same reasons: " + "; ".join(raised["reasons"])
            next_step = f'read the question (hw read {name}) and answer with: hw say {name} "YOUR DECISION"'
        elif status == "stopped":
            reason = "stopped"
        elif run:
            reason, next_step = "hw run has not started driving this task", f"start it with: {resume}"
            state = "blocked"
        ended = facts[-1][0] if state != "running" and facts else None
        elapsed = (ended or now) - data["created_at"]
    if pr and state != "done":
        state, stage, reason, next_step = "done", "done", None, None
    try:
        limits = budget(path)
    except ValueError as error:
        # A bad setting must not hide every task's status; spawn and hw run still refuse it loudly.
        limits = dict(max_minutes=None, max_tokens=None, error=str(error))
    current = dict(
        task=task, project=name, driver="run" if run else "coordinator", state=state, stage=stage, status=status,
        reason=reason, next_step=next_step, request=first_line(path / "brief.md")[:160],
        started_at=data["created_at"], ended_at=ended, elapsed_seconds=round(max(0.0, elapsed), 1),
        last_action=facts[-1][1] if facts else None, last_action_at=facts[-1][0] if facts else None,
        tokens=token_summary(workers), budget=limits, branch=data["branch"],
        commit=pr["commit"] if pr else built_commit(path), pr_url=pr["url"] if pr else None, sessions=workers,
        webhook=next(({k: e.get(k) for k in ("at", "kind", "ok", "detail")}
                      for e in reversed(history) if e.get("event") == "webhook"), None))
    if not run and state == "running" and "error" not in limits:
        spent = over_budget(path, current)
        if spent:
            current.update(state="blocked", reason=spent,
                           next_step=f"raise the budget in project.json, or end it with: hw stop {name} {task}")
    return current


def over_budget(path, current=None):
    """Why the task may spend no more, or None. Unknown token counts cannot be held to a token budget."""
    limits = budget(path)
    if not any(limits.values()):
        return None
    current = current or record(path)
    minutes = current["elapsed_seconds"] / 60
    if limits["max_minutes"] and minutes >= limits["max_minutes"]:
        return f"max_minutes budget reached: {minutes:.1f} of {limits['max_minutes']:g} minutes"
    total = current["tokens"]["total"]
    if limits["max_tokens"] and isinstance(total, int) and total >= limits["max_tokens"]:
        return f"max_tokens budget reached: {total:,} of {limits['max_tokens']:,} tokens"
    return None


PAYLOAD = ("project", "task", "state", "stage", "status", "reason", "next_step", "started_at", "ended_at",
           "elapsed_seconds", "last_action", "last_action_at", "tokens", "budget", "branch", "commit", "pr_url")


def notify(path, current, kind):
    """POST the record to the Project's webhook, if it has one. A failure is recorded and never raised.

    The URL can carry a secret, so it is never written anywhere: only the outcome is kept."""
    try:
        url = project_setting(Path(path).parents[1], "webhook")
        if not url:
            return None
        if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https"):
            raise ValueError("webhook must be an http or https URL")
        body = json.dumps(dict({name: current[name] for name in PAYLOAD}, event=kind, at=time.time())).encode()
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": "herdworks"})
        with urllib.request.urlopen(request, timeout=10) as response:
            result = dict(ok=200 <= response.status < 300, detail=f"HTTP {response.status}")
    except urllib.error.HTTPError as error:
        result = dict(ok=False, detail=f"HTTP {error.code}")
        error.close()
    except Exception as error:
        result = dict(ok=False, detail=type(error).__name__)
    append_event(path, dict(event="webhook", at=time.time(), kind=kind, **result))
    return result


def clock(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}h{minutes:02}m" if hours else f"{minutes}m{seconds:02}s"


def count(value):
    return f"{value:,}" if isinstance(value, int) else "unknown"


def headline(current):
    used = current["tokens"]
    some = " (some unknown)" if used["partial"] and isinstance(used["total"], int) else ""
    return (f"{current['task']} {current['state']} stage={current['stage']} "
            f"elapsed={clock(current['elapsed_seconds'])} tokens={count(used['total'])}{some}")


def line(current):
    """One line for `hw watch`: the headline and the last action."""
    return headline(current) + (f" | {current['last_action']}" if current["last_action"] else "")


def render(current, now=None):
    """The record as text for a person."""
    now = time.time() if now is None else now
    lines = [headline(current), f"  request: {current['request']}"]
    if current["last_action"] and not current["last_action"].startswith(current["state"] + ":"):
        # A finished run's last action is its own result, which the result or reason line already gives.
        lines.append(f"  last: {current['last_action']} ({clock(max(0, now - current['last_action_at']))} ago)")
    lines.append(f"  branch: {current['branch']}" + (f" at {current['commit']}" if current["commit"] else ""))
    if current["pr_url"]:
        lines.append(f"  pull request: {current['pr_url']}")
    limits = [f"invalid ({value})" if name == "error" else f"{name} {value:g}"
              for name, value in current["budget"].items() if value]
    if limits:
        lines.append("  budget: " + ", ".join(limits))
    for worker in current["sessions"]:
        used = worker["tokens"]
        model = f" {worker['model']}" if worker.get("model") else ""
        lines.append(f"  {worker['role']:<8} {worker['agent']}{model} {clock(worker['seconds'])} "
                     f"tokens={count(used['total'] if isinstance(used, dict) else None)} {worker['state']}"
                     + (f"  hc attach {worker['name']}" if worker["live"] else ""))
    if current["reason"]:
        lines.append(f"  {'result' if current['state'] == 'done' else 'reason'}: {current['reason']}")
    if current["next_step"]:
        lines.append(f"  next: {current['next_step']}")
    if current["webhook"]:
        sent = current["webhook"]
        lines.append(f"  webhook: {sent['kind']} {'delivered' if sent['ok'] else 'not delivered'} ({sent['detail']})")
    return lines
