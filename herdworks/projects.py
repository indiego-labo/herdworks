import json
import math
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
import re
import time
import sys
from .home import hw_home
from .runs import git, locked
from .limits import hold_reason
from .memory import sync

GITHUB_CLONE = "https://github.com/{}.git"


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


def repository_slug(value):
    """owner/repo from what a person types: a slug, an HTTPS URL or an SSH address."""
    text = value.strip()
    text = re.sub(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)", "", text)
    text = text.removesuffix(".git").strip("/")
    parts = text.split("/")
    if (len(parts) != 2
            or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in (".", "..") for part in parts)):
        raise ValueError("--github needs a GitHub repository as owner/repo")
    return text


def gh_executable(gh=None):
    found = gh or shutil.which("gh")
    if not found:
        raise ValueError("GitHub needs gh; install it and run: gh auth login")
    return found


def github_push_access(repository, gh):
    """Ask GitHub, with the signed-in account, whether it may push to the repository."""
    result = subprocess.run([gh, "api", f"repos/{repository}", "--jq", ".permissions.push"],
                            capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise ValueError(f"GitHub cannot read {repository} with the signed-in account: "
                         + (detail[0] if detail else "gh auth login"))
    if result.stdout.strip() != "true":
        raise ValueError(f"the signed-in GitHub account cannot push to {repository}; "
                         "ask for write access, or add a checkout you already have with --repo")


def github_default_branch(repository, gh):
    result = subprocess.run([gh, "repo", "view", repository, "--json", "defaultBranchRef",
                             "--jq", ".defaultBranchRef.name"], capture_output=True, text=True)
    if result.returncode or not result.stdout.strip():
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise ValueError(f"GitHub cannot name the base branch of {repository}: "
                         + (detail[0] if detail else "no answer"))
    return result.stdout.strip()


def clone_github(repository, destination, gh):
    """Clone over HTTPS with gh's sign-in; no SSH keys and no personal clone needed."""
    url = GITHUB_CLONE.format(repository)
    result = subprocess.run(
        ["git", "-c", "credential.helper=",
         "-c", f"credential.helper=!{shlex.quote(gh)} auth git-credential",
         "clone", "--quiet", url, str(destination)],
        capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise ValueError(f"clone of {url} failed: " + (detail[-1] if detail else "git gave no reason"))


def add_github_project(name, repository, base=None, prefix=None, home=None, gh=None):
    """Add a Project for a GitHub repository, cloning it into a folder Herdworks manages."""
    from . import hc
    hc.require_owner()
    home = Path(home) if home is not None else hw_home()
    path = project_path(name, home)
    if path.exists():
        raise ValueError(f"Project {name} already exists")
    slug = repository_slug(repository)
    executable = gh_executable(gh)
    github_push_access(slug, executable)
    base_branch = base or github_default_branch(slug, executable)
    url = GITHUB_CLONE.format(slug)
    destination = home / "repos" / slug
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        # A clone from an interrupted run is reused only when it is the same remote.
        try:
            origin = git(destination, "config", "--get", "remote.origin.url")
        except RuntimeError:
            origin = None
        if not (destination / ".git").is_dir() or origin != url:
            raise ValueError(f"{destination} exists and is not a clone of {slug}; move it aside and retry")
        built = add_project(name, destination, base_branch, prefix, home)
        grant_project(built, push=True, draft_pr=True, unsandboxed=True)
        return built
    staging = Path(tempfile.mkdtemp(prefix=f".{name}-clone-", dir=destination.parent))
    created = built = None
    try:
        clone_github(slug, staging, executable)
        tracking = f"refs/remotes/origin/{base_branch}"
        if tracking not in git(staging, "for-each-ref", "--format=%(refname)", tracking).splitlines():
            raise ValueError(f"branch {base_branch} is not on {slug}")
        if f"refs/heads/{base_branch}" not in git(staging, "for-each-ref", "--format=%(refname)",
                                                  f"refs/heads/{base_branch}").splitlines():
            git(staging, "branch", base_branch, tracking)
        staging.rename(destination)
        created = destination
        built = add_project(name, destination, base_branch, prefix, home)
        grant_project(built, push=True, draft_pr=True, unsandboxed=True)
        return built
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        for folder in (created, built):
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
        raise


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


def valid_branch(repo, name):
    try:
        git(repo, "check-ref-format", "--branch", name)
    except RuntimeError:
        raise ValueError(f"base branch is not a valid branch name: {name}") from None
    return name


def remote_base(repo, remote, base_branch):
    """Fetch the remote and return the newest commit of base_branch, preferring its copy."""
    valid_branch(repo, base_branch)
    if remote in git(repo, "remote").splitlines():
        try:
            git(repo, "fetch", "--quiet", remote)
        except RuntimeError as error:
            raise ValueError(f"could not fetch {remote}: {error}") from error
        tracking = f"refs/remotes/{remote}/{base_branch}"
        if tracking in git(repo, "for-each-ref", "--format=%(refname)", tracking).splitlines():
            return git(repo, "rev-parse", tracking)
        raise ValueError(f"branch {base_branch} is not on {remote}; push it first or choose another base")
    local = f"refs/heads/{base_branch}"
    if local not in git(repo, "for-each-ref", "--format=%(refname)", local).splitlines():
        raise ValueError(f"branch {base_branch} is not in this repository")
    return git(repo, "rev-parse", local)


def new_task(project, brief=None, message=None, roles=None, stuck_after=None, base=None, kind="build", extra=None):
    data = read_project(project)
    if kind not in ("build", "spike"):
        raise ValueError("task kind must be build or spike")
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
            base = base or entry.get("base")
        elif brief is not None:
            text = Path(brief).read_text()
        else:
            raise ValueError("a brief or message number is required")
        repo = data["repo"]
        if git(repo, "status", "--porcelain"):
            raise ValueError("target repository must be clean")
        base_branch = base or data["base_branch"]
        base_commit = remote_base(repo, data.get("remote", "origin"), base_branch)
        number = max((int(p.parent.name.split("-")[-1]) for p in paths), default=0) + 1
        task_id = f"{data['prefix']}-{number}"
        path = project / "tasks" / task_id
        metadata = dict(id=task_id, project=data["name"], repo=repo,
                        base=base_commit, base_branch=base_branch,
                        branch=f"hw/{task_id}", created_at=time.time(), message=message,
                        memory_before=memory_before)
        reason = hold_reason(path, allocating=True)
        if reason:
            metadata["queued_reason"] = reason
        if roles:
            metadata["roles"] = roles
        if stuck_after is not None:
            metadata["stuck_after_minutes"] = stuck_after
        if kind != "build":
            metadata["kind"] = kind
        metadata.update(extra or {})
        pending = project / "tasks" / f".{task_id}-pending"
        pending.mkdir(exist_ok=True)
        (pending / "brief.md").write_text(text)
        (pending / "events.jsonl").write_text("")
        (pending / "task.json").write_text(json.dumps(metadata, indent=2) + "\n")
        pending.rename(path)
        (project / "coordinator/tasks" / task_id).mkdir(exist_ok=True)
        return path, False
