import json
import math
import os
import shutil
import tempfile
from pathlib import Path
import re
import time
import sys
from .home import hw_home
from .runs import git, locked
from .limits import hold_reason
from .memory import sync


def project_path(name, home=None):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,11}", name):
        raise ValueError("Project name must be 1 to 12 lowercase letters, digits, hyphens or underscores")
    return (Path(home) if home is not None else hw_home()) / "projects" / name


def read_project(path):
    return json.loads((path / "project.json").read_text())


def add_project(name, repo, base_branch="main", prefix=None, home=None):
    path = project_path(name, home)
    repo = Path(repo).expanduser().resolve(strict=True)
    prefix = prefix or ("".join(c for c in name if c.isalpha()) + "XX")[:2].upper()
    if not re.fullmatch(r"[A-Z]{2}", prefix):
        raise ValueError("task prefix must be two uppercase letters")
    if git(repo, "rev-parse", "--is-bare-repository") != "false":
        raise ValueError("target must be a working repository")
    git(repo, "rev-parse", "--verify", f"refs/heads/{base_branch}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked(path.parent):
        if path.exists():
            raise ValueError(f"Project {name} already exists")
        pending = Path(tempfile.mkdtemp(prefix=f".{name}-pending-", dir=path.parent))
        try:
            for folder in ("memory", "tasks", "coordinator", "coordinator/tasks", "coordinator/outbox"):
                (pending / folder).mkdir()
            (pending / "project.json").write_text(json.dumps(dict(
                name=name, repo=str(repo), base_branch=base_branch, prefix=prefix,
                remote="origin", grants={"push": False, "draft-pr": False}), indent=2) + "\n")
            (pending / "inbox.jsonl").touch()
            pending.rename(path)
        finally:
            if pending.exists():
                shutil.rmtree(pending)
    return path


def grant_project(path, push=None, draft_pr=None, remote=None, gh=None, unsandboxed=None):
    from . import hc
    hc.require_owner()
    if remote is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", remote):
        raise ValueError("remote must be a git remote name")
    if gh is not None and not gh.strip():
        raise ValueError("gh executable must not be empty")
    with locked(path):
        data = read_project(path)
        grants = data.setdefault("grants", {"push": False, "draft-pr": False})
        for name, value in (("push", push), ("draft-pr", draft_pr), ("unsandboxed", unsandboxed)):
            if value is not None:
                grants[name] = value
        if remote is not None:
            data["remote"] = remote
        if gh is not None:
            data["gh"] = gh
        temporary = path / ".project.json.tmp"
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        temporary.replace(path / "project.json")
    return data


def task_path(project, task_id, home=None):
    path = project_path(project, home)
    prefix = read_project(path)["prefix"]
    if not re.fullmatch(re.escape(prefix) + r"-[1-9][0-9]*", task_id):
        raise ValueError("task id must use the Project prefix and a positive number")
    return path / "tasks" / task_id


def task_paths(project):
    return sorted((p for p in (project / "tasks").glob("*/task.json")
                   if re.fullmatch(r"[A-Z]{2}-[1-9][0-9]*", p.parent.name)),
                  key=lambda p: int(p.parent.name.split("-")[-1]))


def new_task(project, brief=None, message=None, roles=None, stuck_after=None):
    data = read_project(project)
    if stuck_after is not None and (stuck_after <= 0 or not math.isfinite(stuck_after)):
        raise ValueError("stuck-after must be a positive number of minutes")
    if roles and sys.platform != "darwin":
        raise ValueError("--role overrides are unavailable on Linux; require macOS sandbox-exec")
    if roles and set(roles) - {"build", "verify", "evidence"}:
        raise ValueError("unknown worker role")
    roles = {role: str(Path(program).resolve(strict=True)) for role, program in (roles or {}).items()}
    with locked(project.parents[1]), locked(project):
        memory_before = sync(project)
        paths = task_paths(project)
        if message is not None:
            inbox = [json.loads(line) for line in (project / "inbox.jsonl").read_text().splitlines()]
            entry = next((m for m in inbox if m["number"] == message), None)
            if entry is None:
                raise ValueError("message number is not in this Project's inbox")
            for item in paths:
                if json.loads(item.read_text()).get("message") == message:
                    (project / "coordinator/tasks" / item.parent.name).mkdir(exist_ok=True)
                    return item.parent, True
            text = entry["text"]
        elif brief is not None:
            text = Path(brief).read_text()
        else:
            raise ValueError("a brief or message number is required")
        repo = data["repo"]
        if git(repo, "status", "--porcelain"):
            raise ValueError("target repository must be clean")
        number = max((int(p.parent.name.split("-")[-1]) for p in paths), default=0) + 1
        task_id = f"{data['prefix']}-{number}"
        path = project / "tasks" / task_id
        metadata = dict(id=task_id, project=data["name"], repo=repo,
                        base=git(repo, "rev-parse", f"refs/heads/{data['base_branch']}"),
                        branch=f"hw/{task_id}", created_at=time.time(), message=message,
                        memory_before=memory_before)
        reason = hold_reason(path, allocating=True)
        if reason:
            metadata["queued_reason"] = reason
        if roles:
            metadata["roles"] = roles
        if stuck_after is not None:
            metadata["stuck_after_minutes"] = stuck_after
        pending = project / "tasks" / f".{task_id}-pending"
        pending.mkdir(exist_ok=True)
        (pending / "brief.md").write_text(text)
        (pending / "events.jsonl").write_text("")
        (pending / "task.json").write_text(json.dumps(metadata, indent=2) + "\n")
        pending.rename(path)
        (project / "coordinator/tasks" / task_id).mkdir(exist_ok=True)
        return path, False
