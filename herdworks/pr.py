import json
import re
import subprocess
import time
from urllib.parse import urlsplit
from .gate import check_gate, blocked_requirements, read_claims
from .projects import read_project
from .runs import append_event, events, first_line, git, is_stopped, locked, newest_artifact, read_task, unheard


def recorded_pr(path):
    return next((e for e in reversed(events(path)) if e.get("event") == "pr"), None)


def fenced(text):
    runs = re.findall(r"`+", text)
    fence = "`" * max(3, max(map(len, runs), default=0) + 1)
    return f"{fence}\n{text.rstrip()}\n{fence}"


def redact(text):
    text = re.sub(r"(https?://)[^/\s@]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)([\w-]*(?:api[_-]?key|token|secret|password)[\w-]*\s*[:=]\s*)"
                  r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1[REDACTED]", text)
    return re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", text)


def excerpt(text):
    lines = redact(text).strip().splitlines()
    short = "\n".join(lines[:3])[:400]
    return short + ("\n[Full output retained in Project evidence.]" if short != "\n".join(lines) else "")


def repository_identity(address):
    if "://" not in address:
        scp = re.fullmatch(r"(?:[^/@:]+@)?([^/:]+):(.+)", address)
        if scp:
            address = f"ssh://{scp[1]}/{scp[2]}"
        else:
            return address
    parsed = urlsplit(address)
    if parsed.scheme == "file":
        return parsed.path
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if (not parsed.hostname or len(parts) != 2
            or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in (".", "..") for part in parts)):
        raise ValueError("push address must identify a host, owner and repository")
    return "/".join((parsed.hostname, *parts))


def build_body(path, commit, manual_verification=False):
    data = read_task(path)
    base_branch = data.get('base_branch') or read_project(path.parents[1])['base_branch']
    verdict = newest_artifact(path, "verify-*/verdict.md")
    review = newest_artifact(path, "evidence-*/review.md")
    commands = verdict.parent / "evidence/commands.json"
    if commands.is_symlink() or not commands.is_file():
        raise ValueError("verifier must record evidence/commands.json before opening a pull request")
    records = json.loads(commands.read_text())
    if (not isinstance(records, list) or not records
            or any(not isinstance(record, dict)
                   or not isinstance(record.get("command"), str) or not record["command"].strip()
                   or not isinstance(record.get("output"), str) for record in records)):
        raise ValueError("verifier command records must contain command and output strings")
    changed = git(data["repo"], "diff", "--stat", data["base"], commit)
    commit_label = 'Built commit' if manual_verification else 'Verified commit'
    proof = [f"Verdict: {first_line(verdict)}", f"{commit_label}: {commit}",
             "Claims: " + ", ".join(f"{c['id']} {c['grade']}" for c in read_claims(verdict.parent) or []),
             f"Evidence review: {first_line(review)}",
             f"Project evidence: {verdict}, {review}, {commands}"]
    for record in records:
        proof.append(fenced(f"$ {redact(record['command'])}\n{excerpt(record['output'])}"))
    why = " ".join((path / 'brief.md').read_text().strip().split("\n\n", 1)[0].split())[:600]
    handoff = ('## Needs manual verification\n\n' +
               '\n'.join(f'- {item}' for item in blocked_requirements(path)) + '\n\n') if manual_verification else ''
    summary = ('Independent checks passed except the environment-blocked requirements below.'
               if manual_verification else
               'The independent verifier checked this commit; the evidence reviewer confirmed its proof.')
    scope = 'built commit' if manual_verification else 'verified commit'
    return redact(f"## Why\n\n{why}\n\n"
                  f"## Scope\n\nTask {data['id']}, branch {data['branch']}, based on {base_branch} "
                  f"at {data['base']}. "
                  f"Covers the original request and its {scope}. Follow-up work is outside this draft.\n\n"
                  f"## Blast Radius\n\nChanged files:\n\n{fenced(changed)}\n\n"
                  f"{summary}\n\n"
                  "## Verification\n\n" + "\n\n".join(proof) + "\n\n" + handoff +
                  "Agents must not merge this pull request.\n")


def open_pr(path, manual_verification=False, title=None):
    project = path.parents[1]
    with locked(project), locked(path):
        config = read_project(project)
        data = read_task(path)
        if (data["project"] != config["name"] or data["id"] != path.name
                or data["repo"] != config["repo"] or data["branch"] != f"hw/{path.name}"):
            raise ValueError("task identity does not match its Project")
        missing = [name for name in ("push", "draft-pr") if config.get("grants", {}).get(name) is not True]
        if missing:
            raise ValueError("pull request not opened: Project has not granted " + ", ".join(missing))
        if any(e.get("event") in ("pr", "pr-started") for e in events(path)):
            raise ValueError("pull request already opened or creation outcome uncertain; inspect task events")
        if is_stopped(path):
            raise ValueError("task is stopped")
        if data.get("driver") == "run" and unheard(path):
            # `hw say --task` saves an answer under the locks held here, so this look cannot miss one.
            raise ValueError(f"the owner's answer has not reached a builder yet; continue the task with: "
                             f"hw run -p {data['project']} --resume {data['id']}")
        passed, commit, reasons = check_gate(path, manual_verification=manual_verification)
        if not passed:
            raise ValueError("gate refused: " + "; ".join(reasons))
        remote = config.get("remote", "origin")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", remote):
            raise ValueError("remote must be a git remote name")
        urls = git(config["repo"], "remote", "get-url", "--push", "--all", remote).splitlines()
        if len(urls) != 1:
            raise ValueError("Project remote must have exactly one push address")
        repository = repository_identity(urls[0])
        if title is None:
            brief = ' '.join((path / 'brief.md').read_text().split())
            title = re.split(r'(?<=[.!?])\s+', brief, maxsplit=1)[0][:72].rstrip()
        else:
            title = ' '.join(title.split())
        if not title:
            raise ValueError('pull request title must not be empty')
        if manual_verification:
            title = '[Needs manual verification] ' + title
        base_branch = data.get('base_branch') or config['base_branch']
        body = path / "pr-body.md"
        body.write_text(build_body(path, commit, manual_verification))
        git(config["repo"], "push", remote, f"{commit}:refs/heads/{data['branch']}")
        if check_gate(path, manual_verification=manual_verification)[:2] != (True, commit):
            raise ValueError("gate changed after push; pull request not opened")
        append_event(path, dict(event="pr-started", at=time.time(), commit=commit,
                                branch=data["branch"], remote=remote, manual_verification=manual_verification))
        result = subprocess.run([config.get("gh", "gh"), "pr", "create", "--draft",
                                 "--repo", repository,
                                 "--base", base_branch, "--head", data["branch"],
                                 "--title", title,
                                 "--body-file", str(body),
                                 *(["--label", "needs-manual-verification"] if manual_verification else [])],
                                cwd=config["repo"], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("draft creation failed; inspect before retrying: " + result.stderr.strip())
        url = result.stdout.strip()
        if not re.fullmatch(r"https://[^\s]+/pull/[0-9]+", url):
            raise RuntimeError("draft creation returned no pull request address; inspect before retrying")
        append_event(path, dict(event="pr", at=time.time(), url=url, commit=commit,
                                branch=data["branch"], remote=remote, manual_verification=manual_verification))
        return url
