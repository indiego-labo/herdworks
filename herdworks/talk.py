import json
import shlex
import time
from . import hc
from .limits import role_settings
from .monitor import saved
from .pr import recorded_pr
from .projects import read_project, task_paths
from .runs import ROOT, coordinator_task, derive_status, events, locked, read_task, write_journal
from .spawn import reconcile


def status_word(session):
    status = session.get("status")
    return status.get("state") if isinstance(status, dict) else status


def coordinator_name(project):
    return f"hw-{project.name}-coord"


def _up(project, root):
    name = coordinator_name(project)
    observed = hc.get(name)
    if observed.get("state") != "missing":
        if (observed.get("cwd") != str(project / "coordinator")
                or observed.get("labels", {}).get("hw") != f"project:{project.name}"):
            raise ValueError(f"session {name} belongs to another folder; refusing to touch it")
        if observed.get("state") == "live":
            marker = project / ".coordinator-pending.json"
            if marker.exists():
                pending = json.loads(marker.read_text())
                if pending.get("result", {}).get("first_message", {}).get("sent") is False:
                    hc.call("kill", observed["address"])
                else:
                    write_journal(project / "coordinator.json", observed)
                    marker.unlink()
                    return observed, False
            else:
                raise ValueError(f"coordinator {name} is alive ({status_word(observed)})")
        hc.call("rm", observed["address"])
    for item in task_paths(project):
        with locked(item.parent):
            reconcile(item.parent)
    data = read_project(project)
    settings = role_settings(project, "coordinator")
    home = project.parents[1]
    command = f"env HW_HOME={shlex.quote(str(home))} {shlex.quote(str(root / 'bin/hw'))}"
    task = (f"Project: {data['name']}. Project folder: {project}. Herdworks home: {home}. "
            f"Herdworks command (use this exact prefix on every call): {command}. "
            f"Read {root / 'playbooks/coordinator.md'} in full and follow every numbered rule. "
            "You stay for message after message; an idle turn is not the end of the Project. "
            "Read inbox.jsonl in the Project folder for pending numbered messages. "
            "Respond only through your outbox. If there is no task or pending message, end your turn ready for messages. ")
    if task_paths(project):
        task += ("Pick up under rule 18: read all task.json, events.jsonl, artifacts and your tasks/*/decisions.tsv, "
                 "answers/ and catchup.md. Redo nothing with its artifact. Probe every unfinished task; "
                 "workers may die with the old parent. Use spawn PROJECT TASK ROLE --replaces NAME for an incomplete dead worker. ")
    marker = project / ".coordinator-pending.json"
    write_journal(marker, {"name": name})
    result = hc.launch(name=name, cwd=project / "coordinator", template="hw-coordinator" + ("-opencode" if settings["agent"] == "opencode" else ""),
                       task=task, identity=f"project:{project.name}", role="coordinator")
    result.update(settings)
    write_journal(marker, {"name": name, "result": result})
    write_journal(project / "coordinator.json", result)
    with (project / "coordinator-sessions.jsonl").open("a") as stream:
        stream.write(json.dumps(result) + "\n")
    if result.get("first_message", {}).get("sent") is not True:
        raise RuntimeError(f"first message was not sent to {name}; inspect hc read {name}")
    marker.unlink()
    return result, True


def up(project, root=ROOT):
    read_project(project)
    with locked(project):
        return _up(project, root)[0]


def inbox(project):
    return [json.loads(line) for line in (project / "inbox.jsonl").read_text().splitlines() if line]


def route(project, task):
    """Where an owner's `--task` message goes: the folder of a task `hw run` drives, or None for the coordinator.

    Called before anything is recorded. A message nothing would act on is refused with the next
    step, so it is never saved and then ignored. Only `--task` routes: a message that merely
    mentions a task id in its text goes to the coordinator as written."""
    name = read_project(project)["name"]
    known = {item.parent.name: item.parent for item in task_paths(project)}
    if task not in known:
        raise ValueError(f"{task} is not a task of Project {name}, so this message was not delivered. "
                         f"Next step: list its tasks with: hw tasks {name}")
    closed = next((e for e in events(known[task]) if e.get("event") == "closed"), None)
    if closed:
        why = f" ({closed['reason']})" if closed.get("reason") else ""
        raise ValueError(f"{task} is closed{why}, so nothing would act on this message and it was not "
                         f'delivered. Next step: start a follow-up task with: hw run -p {name} "..."')
    return known[task] if read_task(known[task]).get("driver") == "run" else None


def answer(project, path, text):
    """Record the owner's message as an answer for a task `hw run` drives; a builder's brief will carry it.

    The task's lock is held while it is saved. `hw run` saves a task's end state under the same lock,
    after looking for answers no builder has read, so an answer is either seen by the running task
    or saved after its end state, where the caller sees that state and resumes the task."""
    if not text or not text.strip():
        raise ValueError("message must not be empty")
    with locked(project), locked(path):
        if saved(path).get("state") == "done" or recorded_pr(path):
            raise ValueError(f"{path.name} is finished ({derive_status(path)}), so this message was not delivered. "
                             f'Next step: start a follow-up task with: hw run -p {project.name} "..."')
        number = max((m["number"] for m in inbox(project)), default=0) + 1
        with (project / "inbox.jsonl").open("a") as stream:
            stream.write(json.dumps(dict(number=number, text=text, at=time.time(), task=path.name)) + "\n")
        # A copy for people and for the workers that read the task's notes; the inbox entry is the answer.
        folder = coordinator_task(path) / "answers"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{number}.md").write_text(text)
    return number


def say(project, text=None, number=None, root=ROOT, delivery_key=None, base=None, about=None):
    data = read_project(project)
    if text is not None and not text.strip():
        raise ValueError("message must not be empty")
    if base is not None:
        from .projects import valid_branch
        valid_branch(data["repo"], base)
    with locked(project):
        current = hc.get(coordinator_name(project))
        if current.get("state") == "live" and status_word(current) == "blocked":
            raise ValueError(f"coordinator {coordinator_name(project)} is blocked; inspect its screen; message was not delivered")
        messages = inbox(project)
        if delivery_key is not None:
            previous = next((m for m in messages if m.get("delivery_key") == delivery_key), None)
            if previous:
                number = previous["number"]
        repeat = number is not None
        if repeat:
            entry = next((m for m in messages if m["number"] == number), None)
            if entry is None:
                raise ValueError("unknown message number")
            answered = project / "tasks" / str(entry.get("task"))
            if entry.get("task") and (answered / "task.json").is_file() and read_task(answered).get("driver") == "run":
                raise ValueError(f"message {number} was an answer to {entry['task']}, a hw run task, and is already "
                                 f"saved for it; nothing to redeliver. See: hw status {entry['task']}")
            if text is not None and text != entry["text"]:
                raise ValueError("repeat must use the original text")
            if base is not None and base != entry.get("base"):
                raise ValueError("repeat must use the original base branch")
        else:
            if text is None:
                raise ValueError("message text is required")
            number = max((m["number"] for m in messages), default=0) + 1
            entry = dict(number=number, text=text, at=time.time())
            if about is not None:
                entry["task"] = about
            if base is not None:
                entry["base"] = base
            if delivery_key is not None:
                entry["delivery_key"] = delivery_key
            with (project / "inbox.jsonl").open("a") as stream:
                stream.write(json.dumps(entry) + "\n")
        if current.get("state") != "live" or (project / ".coordinator-pending.json").exists():
            current, launched = _up(project, root)
            if launched:
                return number, repeat
        elif (current.get("cwd") != str(project / "coordinator")
              or current.get("labels", {}).get("hw") != f"project:{project.name}"):
            raise ValueError("coordinator identity does not match this Project")
        for attempt in range(4):
            try:
                heading = f"MESSAGE {number}" + (f" about {entry['task']}" if entry.get("task") else "")
                hc.call("send", current["address"], f"{heading}\n{entry['text']}")
                break
            except hc.HCError as error:
                if attempt == 3 or "still starting" not in str(error) or "nothing was typed" not in str(error):
                    raise RuntimeError(f"message {number} saved; retry say --number {number}: {error}") from error
                hc.call("wait", current["address"], "--timeout", "2", "--json")
        return number, repeat


def read(project, since=0):
    if since < 0:
        raise ValueError("since must be nonnegative")
    read_project(project)
    replies = []
    numbers = set()
    for file in (project / "coordinator/outbox").iterdir():
        if file.name.startswith(".") or file.suffix != ".md":
            continue
        if not file.is_file() or file.suffix != ".md" or not file.stem.isdecimal():
            raise ValueError(f"outbox file must have a numbered .md name: {file.name}")
        number = int(file.stem)
        if number < 1 or number in numbers:
            raise ValueError("outbox numbers must be unique positive integers")
        numbers.add(number)
        text = file.read_text()
        if not text.splitlines() or text.splitlines()[0] not in ("REPLY", "QUESTION", "DONE", "PROBLEM"):
            raise ValueError(f"invalid outbox opening in {file.name}")
        if number > since:
            replies.append((number, text))
    return sorted(replies)


def latest(project):
    return max((number for number, _ in read(project)), default=0)


def wait(project, since=None, timeout=None, interval=5.0):
    """Blocks until the coordinator writes a reply numbered above `since`; [] when `timeout` passes.

    Reads only the Project's outbox folder, so callers (a person, Claude Code, a script) can wait
    without a service running; `since` defaults to the latest reply at the moment of calling."""
    import time
    since = latest(project) if since is None else since
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        replies = read(project, since)
        if replies:
            return replies
        if deadline is not None and time.monotonic() >= deadline:
            return []
        time.sleep(interval if deadline is None else max(0.0, min(interval, deadline - time.monotonic())))
