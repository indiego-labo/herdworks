import hashlib
import json
import shutil
import time
import uuid
from datetime import datetime, timezone
from . import hc
from .gate import claim_problems, environment_only
from .limits import role_settings, hold_reason
from .memory import brief as memory_brief
from .pickup import remove_worktree
from .probe import progress_time
from . import rules
from .runs import ROOT, answered_since, answers, append_event, built_commit, events, first_line, git, locked, newest_artifact, read_task, coordinator_task, task_key, is_stopped, coordinator, ARTIFACT, artifact_complete, escalation, write_journal


def record_launch(path, result, *, name, role, folder, stuck_after, program=None, **metadata):
    append_event(path, {"event": "session", "name": name, "role": role,
                       "address": result["address"], "parent": result.get("parent"),
                       "folder": folder, "started_at": time.time(),
                       "stuck_after_minutes": stuck_after,
                       "first_message": result.get("first_message", {}), **metadata,
                       "launch_source": "override" if program else "template"})
    if not program and result.get("first_message", {}).get("sent") is not True:
        raise RuntimeError(f"first message was not sent to {name}; inspect hc read {name}")


def spike_brief(path, root=ROOT):
    return (root / "briefs/spike.md").read_text() if read_task(path).get("kind") == "spike" else ""


def saved_answers(path):
    """The answers a brief quotes, oldest first, as (number, text)."""
    if read_task(path).get("driver") == "run":
        # No coordinator vouches for the files in answers/, so the owner's own messages are quoted.
        return [(number, text) for number, _, text in answers(path)]
    files = sorted((coordinator_task(path) / "answers").glob("*.md"), key=lambda p: int(p.stem))
    return [(int(file.stem), file.read_text()) for file in files]


def build_brief(path, root=ROOT):
    sources = [root / "briefs/build.md", path / "brief.md", coordinator_task(path) / "intent.md"]
    parts = [f"--- {source.name} ---\n{source.read_text()}" for source in sources]
    parts += [f"--- {number}.md ---\n{text}" for number, text in saved_answers(path)]
    parts.insert(1, spike_brief(path, root) + rules.text("build", path.parents[1]))
    return "\n\n".join(parts) + "\n"


def conversation_context(path):
    project = path.parents[1]
    return (f"Project conversation records (check decision sequence when required):\n"
            f"Inbox: {project / 'inbox.jsonl'}\n"
            f"Outbox: {project / 'coordinator/outbox'}\n"
            f"Question archives and saved answers: {coordinator_task(path)}\n"
            f"Worker chronology: {path / 'events.jsonl'}\n"
            "The Project user's messages are the authority for product choices in this task.\n")


def build_verify_brief(path, commit, worktree, root=ROOT):
    data = read_task(path)
    skills = sorted((worktree / ".agents/skills").glob("verify-*/SKILL.md"))
    checks = "\n".join(str(p) for p in skills) or "No verify-* skill found; use artifact-appropriate checks."
    return (f"{(root / 'briefs/verify.md').read_text()}{spike_brief(path, root)}\n\n"
            f"{rules.text('verify', path.parents[1])}\n"
            f"Original request:\n{(path / 'brief.md').read_text()}\n\n"
            f"User answers:\n{answer_text(path)}\n\n"
            f"{conversation_context(path)}\n"
            f"Base: {data['base']}\nCommit: {commit}\nDetached worktree: {worktree}\n"
            f"Verification skill paths:\n{checks}\n\n"
            f"Proposed coverage (derive requirements independently):\n{(coordinator_task(path) / 'intent.md').read_text()}\n")


DEFAULT_STUCK = {"build": 60, "verify": 45, "evidence": 20}
VERDICT_OPENINGS = ("PASS", "FAIL", "INCONCLUSIVE")


def evidence_wait_reason(verdict, verifier):
    """Return why no review may start yet, or None when the verdict is settled."""
    if verifier and verifier.get("address") and hc.get(verifier["address"]).get("state") == "live":
        return ("evidence review must wait for the verdict: the verifier session is still live; "
                "wait for the verdict before starting a review")
    if verdict is None:
        return ("evidence review must wait for the verdict: verdict.md is missing; "
                "wait for the verifier to write it")
    if first_line(verdict) not in VERDICT_OPENINGS:
        return ("evidence review must wait for the verdict: verdict.md is still being written; "
                "wait for the verifier to finish")
    return None


def stale_review(previous, verdict):
    """True when the newest review began before its verdict and may be replaced."""
    if not verdict or previous.get("started_at", 0) >= verdict.stat().st_mtime:
        return False
    state = hc.get(previous["address"]).get("state") if previous.get("address") else "missing"
    return state != "live"


def answer_text(path):
    return "\n\n".join(text for _, text in saved_answers(path))


def fix_brief(path, round_number, root):
    commit = built_commit(path)
    failed = []
    for event in reversed(events(path)):
        role = event.get("role")
        if event.get("event") != "session" or role not in ("verify", "evidence"):
            continue
        artifact = path / event["folder"] / ARTIFACT[role]
        if event.get("commit") == commit and first_line(artifact) in ("FAIL", "REJECTED"):
            failed.append(artifact.read_text())
            break
    checks = next((e.get("checks") for e in reversed(events(path)) if e.get("event") == "gate"), None) or {}
    if checks.get("commit") == commit and checks.get("exit"):
        failed.append(f"Checks command `{checks['command']}` exited {checks['exit']}. Its last output:\n{checks['tail']}")
    if not commit or not failed:
        raise ValueError("fix requires a failed verdict, rejected review or failed checks for the current built commit")
    reports = sorted(path.glob("build-*/report.md"), key=lambda p: int(p.parent.name.split("-")[1]))
    return (f"{(root / 'briefs/fix.md').read_text()}\nFix round: {round_number} of 3\n\n"
            f"{build_brief(path, root)}\nFindings:\n" +
            "\n\n".join(failed) + "\nEarlier reports and diagnoses:\n" +
            "\n\n".join(p.read_text() for p in reports) +
            "\nIf a later round repeats a cause, test the underlying assumption and reconsider the design.\n")


def release_claim(data, setup, delete_branch=False):
    claim = setup.get("claim")
    if not claim:
        return
    refs = git(data["repo"], "for-each-ref", "--format=%(refname)", claim).splitlines()
    if claim not in refs:
        return
    if delete_branch:
        # Both refs were created in one transaction, so this attempt owns the branch.
        git(data["repo"], "update-ref", "-d", f"refs/heads/{data['branch']}", data["base"])
    git(data["repo"], "update-ref", "-d", claim, data["base"])


def rollback_setup(path, marker, setup):
    data = read_task(path)
    folder = path / setup["folder"]
    cwd = folder / setup["cwd_name"]
    if setup["role"] != "evidence":
        worktrees = git(data["repo"], "worktree", "list", "--porcelain").splitlines()
        if f"worktree {cwd}" in worktrees:
            git(data["repo"], "worktree", "remove", "--force", cwd)
        elif cwd.is_symlink():
            cwd.unlink()
        elif cwd.exists():
            shutil.rmtree(cwd)
    elif cwd.exists():
        cwd.rmdir()
    release_claim(data, setup, delete_branch=True)
    (folder / "brief.md").unlink(missing_ok=True)
    (folder / "launch-pending.json").unlink(missing_ok=True)
    if not setup["folder_existed"] and folder.exists():
        try:
            folder.rmdir()
        except OSError:
            pass
    marker.unlink()


def reconcile(path):
    """The caller holds the task lock so recovery cannot race another launch."""
    recovered = []
    for marker in sorted(path.glob(".setup-*.json")):
        setup = json.loads(marker.read_text())
        recorded = next((e for e in events(path) if e.get("event") == "session"
                         and e.get("name") == setup["name"]), None)
        result = setup.get("result")
        if not recorded and setup.get("launching") and result is None:
            observed = hc.get(setup["name"])
            if observed.get("state") != "missing":
                expected = str(path / setup["folder"] / setup["cwd_name"])
                if (observed.get("cwd") != expected or observed.get("name") != setup["name"]
                        or observed.get("labels", {}).get("hw") != task_key(path)):
                    raise RuntimeError(f"launch identity uncertain for {setup['name']}; inspect before retrying")
                result = observed
        if recorded or result:
            if not recorded:
                record_launch(path, result, **setup["metadata"])
            release_claim(read_task(path), setup)
            (path / setup["folder"] / "launch-pending.json").unlink(missing_ok=True)
            marker.unlink()
            recovered.append(setup["name"])
        else:
            rollback_setup(path, marker, setup)
    return recovered


def replace_session(path, event):
    history = events(path)
    replacements = [e for e in history if e.get("event") == "stalled" and e.get("step") == event["step"]]
    prior = next((e for e in replacements if e.get("name") == event["name"]), None)
    if prior:
        return
    if len(replacements) >= 2:
        raise ValueError("two replacements exhausted for this step; ask with the saved stalled screens")
    if any(e.get("event") == "session" and e.get("replaces") == event["name"] for e in history):
        raise ValueError("that session was already replaced")
    if artifact_complete(path / event["folder"], event["role"]):
        raise ValueError("session already has its artifact; read it instead of replacing")
    folder = path / event["folder"]
    screen = folder / f"stalled-{len(replacements) + 1}.txt"
    last_progress = progress_time(path, event)
    text = hc.call("read", "--json", event["address"])["text"]
    session = hc.get(event["address"])
    captured = time.time()
    status = session.get("status")
    if isinstance(status, dict):
        status = status.get("state")
    screen.write_text(
        f"Session: {event['name']}\nRole: {event['role']}\n"
        f"Commit: {event['commit']}\nStep: {event['step']}\n"
        f"Started: {datetime.fromtimestamp(event['started_at'], timezone.utc).isoformat()}\n"
        f"Last progress: {datetime.fromtimestamp(last_progress, timezone.utc).isoformat()}\n"
        f"Captured: {datetime.fromtimestamp(captured, timezone.utc).isoformat()}\n"
        f"Quiet: {max(0, captured - last_progress) / 60:.2f} minutes; "
        f"stuck-after: {event['stuck_after_minutes']:g} minutes\n"
        f"Herdr core state: {session.get('state')}\nHerdr core status: {status}\n\n"
        "Screen text:\n" + (text if text.strip() else "The session's screen was empty.\n"))
    if session.get("state") == "live":
        hc.call("kill", event["address"])
    append_event(path, {"event": "stalled", "name": event["name"], "step": event["step"],
                        "screen": str(screen), "at": time.time()})


def spawn(path, role="build", root=ROOT, replaces=None):
    if role not in ("build", "fix", "verify", "evidence"):
        raise ValueError("unknown worker role")
    with locked(path.parents[3]), locked(path):
        reconcile(path)
        data = read_task(path)
        history = events(path)
        if any(e.get("event") == "closed" for e in events(path)):
            raise ValueError("task is closed")
        if is_stopped(path):
            raise ValueError("task is stopped")
        if escalation(path):
            raise ValueError("task is escalated: the gate refused it repeatedly for the same reason; "
                             "ask the user and start nothing until they answer")
        from .monitor import over_budget
        spent = over_budget(path)
        if spent:
            raise ValueError(f"{spent}; start no worker: the owner raises the budget or stops the task")
        from .pr import recorded_pr
        pr = recorded_pr(path)
        if pr and pr.get('manual_verification') and pr['commit'] == built_commit(path):
            raise ValueError('task needs manual verification; do not start another round')
        artifact = newest_artifact(path, 'verify-*/verdict.md' if role == 'verify' else 'evidence-*/review.md')
        artifact_session = next((e for e in reversed(history) if e.get('event') == 'session'
                                 and artifact and e.get('folder') == artifact.parent.name), None)
        builder = next((e for e in reversed(history) if e.get("event") == "session" and e.get("role") == "build"), {})
        # A builder that reported after that verdict or review was written makes it one about earlier work.
        if (role in ('verify', 'evidence') and artifact and artifact_session
                and artifact_session.get('commit') == built_commit(path)
                and artifact_session.get('started_at', 0) >= builder.get('started_at', 0)
                and artifact_session.get('launch_source') == 'template' and environment_only(artifact)):
            raise ValueError('requirement blocked by environment; do not retry; use pr --manual-verification')
        from .limits import config
        if sum(e.get('event') == 'session' and e.get('role') != 'coordinator' for e in history) >= config(path.parents[3])['max_sessions_per_task']:
            raise ValueError('max_sessions_per_task worker session budget exhausted')
        worker_role = 'build' if role == 'fix' else role
        reason = hold_reason(path, worker_role, replacing=replaces)
        if reason:
            raise ValueError(f'queued: {reason}')
        # A task started by `hw run` is driven by that command and has no coordinator above it.
        parent_session = {} if data.get("driver") == "run" else coordinator(path)
        if not parent_session and data.get("driver") != "run":
            raise ValueError("Project has no recorded coordinator")
        worker_role = "build" if role == "fix" else role
        settings = role_settings(path.parents[1], worker_role)
        workers = [e for e in history if e.get("event") == "session" and e.get("role") == worker_role]
        previous = workers[-1] if workers else None
        round_number = max((e.get("round", 0) for e in history if e.get("role") == "build"), default=0)
        commit = built_commit(path) if worker_role != "build" else None
        if worker_role != "build" and not commit:
            raise ValueError("a READY report matching a new branch head is required")
        verdict = newest_artifact(path, "verify-*/verdict.md")
        verifier = next((e for e in reversed(history) if e.get("event") == "session"
                         and e.get("role") == "verify" and verdict
                         and e.get("folder") == verdict.parent.name), None)
        if worker_role == "evidence":
            reason = evidence_wait_reason(verdict, verifier)
            if reason:
                raise ValueError(reason)
        target = None
        if replaces:
            target = next((e for e in workers if e.get("name") == replaces), None)
            if target is None or target != previous:
                raise ValueError("--replaces must name the latest session of the same role")
            step = target.get("step", f"{worker_role}:{target.get('round', 0)}")
            target = dict(target, step=step)
            if worker_role == "build":
                commit = target.get("commit") or data["base"]
                head = git(data["repo"], "rev-parse", f"refs/heads/{data['branch']}")
                if head != commit:
                    if data.get("driver") != "run":
                        raise ValueError("builder branch advanced without a complete report; ask before replacing at a different commit")
                    # `hw run` has nobody to ask: the replacement continues from what the lost builder committed.
                    commit = head
            elif target.get("commit") != commit:
                raise ValueError("replacement must verify the same current commit")
            round_number = target.get("round", 0)
        elif role == "fix":
            refusal = next((e for e in reversed(history) if e.get("event") == "gate"), None)
            if not refusal or refusal.get("passed") or refusal.get("commit") != built_commit(path):
                raise ValueError("fix requires the gate's refusal of the current built commit; run hw gate first")
            round_number += 1
            if round_number > 3:
                raise ValueError("three fix rounds exhausted; ask with diagnoses and a recommendation")
            step = f"build:{round_number}"
        elif worker_role == "build":
            rewind = next((e for e in reversed(history) if e.get("event") == "rewind"), None)
            if previous and (not rewind or rewind["at"] <= previous["started_at"]):
                raise RuntimeError(f"worker already started as {previous['name']}; inspect its artifact")
            step = f"build:rewind:{rewind['at']}" if previous else "build:0"
        else:
            step = f"{worker_role}:{commit}"
            if worker_role == "verify" and str(builder.get("step", "")).startswith("build:rewind"):
                # A builder restarted with the owner's answer may report the commit it found. That commit is
                # then verified against the answer too: a step of its own, not a repeat of an earlier verifier.
                step += f":{builder['folder']}"
            if previous and previous.get("commit") == commit and previous.get("step", step) == step:
                artifact = path / previous["folder"] / ARTIFACT[worker_role]
                if not artifact_complete(artifact.parent, worker_role):
                    raise RuntimeError(f"worker already started as {previous['name']}; inspect its artifact")
                if worker_role == "verify" and (first_line(artifact) == "INCONCLUSIVE"
                                                or claim_problems(artifact.parent, data.get("kind"))):
                    cause = next((line for line in artifact.read_text().splitlines() if line.startswith("Cause:")), "")
                    # For a `hw run` task the files in answers/ are copies; only the owner's own messages count.
                    answered = (answered_since(path, artifact.stat().st_mtime) if data.get("driver") == "run" else any(
                        p.stat().st_mtime > artifact.stat().st_mtime for p in (coordinator_task(path) / "answers").glob("*.md")))
                    if cause == "Cause: external-prerequisite" and not answered:
                        raise ValueError("external prerequisite requires a new answer after this verdict; ask the user")
                    attempts = [e for e in workers if e.get("step") == step and not e.get("replaces")]
                    if len(attempts) >= 2 and cause != "Cause: external-prerequisite":
                        raise ValueError("inconclusive verifier rerun exhausted; ask the user")
                elif worker_role == "evidence" and stale_review(previous, verdict):
                    # The review began before the verdict it inspects; the gate must refuse it.
                    # Start a fresh one in a new folder and keep the old review for the record.
                    pass
                else:
                    raise RuntimeError(f"worker already started as {previous['name']}; inspect its artifact")
        if worker_role == "evidence" and (not verdict or (first_line(verdict) != "PASS" and not environment_only(verdict)) or not verifier
                                           or verifier.get("commit") != commit):
            raise ValueError("evidence review requires the newest recorded verifier's PASS verdict")
        if worker_role == "evidence" and (problems := claim_problems(verdict.parent, data.get("kind"))):
            raise ValueError("evidence review requires usable claims; rerun the verifier: " + "; ".join(problems))
        brief = quoted = None
        if worker_role == "build":
            # Read before the brief is written, so every number recorded here is certainly quoted in it.
            quoted = [number for number, _ in saved_answers(path)]
            if target:
                brief, quoted = (path / target["folder"] / "brief.md").read_text(), target.get("answers", [])
            elif role != "fix" and previous and previous.get("round"):
                # A build restarted by an answer during a fix round keeps that round's brief and its findings.
                brief = ((path / previous["folder"] / "brief.md").read_text()
                         + f"\n--- answers given since ---\n{answer_text(path)}\n")
            else:
                brief = fix_brief(path, round_number, root) if role == "fix" else build_brief(path, root)
            head = built_commit(path)
            if role != "fix" and not target and previous and head:
                # The answer came after a builder had finished: its successor continues that work.
                brief += (f"\n--- continuing ---\nThe branch already holds the work of the builder before you, at commit {head}.\n"
                          "The owner's answers in this brief arrived after it was built; the newest is last.\n"
                          "Change what they call for and keep what still holds. If nothing needs to change,\n"
                          f"make no commit and report READY {head}.\n")
        if target:
            replace_session(path, target)
        if worker_role == "build" and previous:
            for event in workers:
                wt = path / event["folder"] / "wt"
                if not wt.exists():
                    continue
                if event.get("address") and hc.get(event["address"]).get("state") == "live":
                    if git(wt, "branch", "--show-current") != data["branch"]:
                        continue
                    if not artifact_complete(wt.parent, "build"):
                        raise ValueError("previous builder is still alive; replace it explicitly")
                    hc.call("kill", event["address"])
                # Unfinished files are kept as unsaved.patch beside the removed worktree.
                remove_worktree(data["repo"], wt)
        if worker_role == "build" and not target:
            commit = git(data["repo"], "rev-parse", f"refs/heads/{data['branch']}") if workers else data["base"]
        number = len(workers) + 1
        folder = path / f"{worker_role}-{number}"
        name = f"hw-{data['project']}-{data['id'].lower()}-{folder.name}"
        if len(name) > 32:
            name = f"hw-{data['project']}-{data['id'].lower()}-{worker_role[0]}{number}"
        if len(name) > 32:
            digest = hashlib.sha256(data['id'].encode()).hexdigest()[:12]
            name = f"hw-{data['project']}-{digest}-{worker_role[0]}{number}"
        cwd_name = "work" if worker_role == "evidence" else "wt"
        cwd = folder / cwd_name
        if cwd.exists() or cwd.is_symlink() or (folder / "brief.md").exists():
            raise ValueError(f"worker working folder already exists: {folder}")
        marker = path / f".setup-{folder.name}.json"
        program = data.get("roles", {}).get(worker_role)
        metadata = dict(name=name, role=worker_role, folder=folder.name,
                        stuck_after=data.get("stuck_after_minutes", DEFAULT_STUCK[worker_role]),
                        program=program, commit=commit, **settings,
                        round=round_number, step=step, replaces=replaces,
                        verifier=verifier["name"] if worker_role == "evidence" else None,
                        **({"answers": quoted} if worker_role == "build" else {}))
        setup = dict(name=name, role=worker_role, folder=folder.name, cwd_name=cwd_name,
                     folder_existed=folder.exists(), metadata=metadata)
        if worker_role == "build" and not workers:
            setup["claim"] = f"refs/hw-setup/{uuid.uuid4().hex}"
        write_journal(marker, setup)
        try:
            folder.mkdir(exist_ok=True)
            if setup.get("claim"):
                ref = f"refs/heads/{data['branch']}"
                git(data["repo"], "update-ref", "--stdin", input=(
                    f"start\ncreate {ref} {data['base']}\n"
                    f"create {setup['claim']} {data['base']}\nprepare\ncommit\n"))
            if worker_role == "evidence":
                cwd.mkdir()
                brief = (f"{(root / 'briefs/evidence.md').read_text()}{spike_brief(path, root)}\n"
                         f"{rules.text('evidence', path.parents[1])}\n"
                         f"Commit: {commit}\n"
                         f"Target repository: {data['repo']}\nBase: {data['base']}\n"
                         f"Original request:\n{(path / 'brief.md').read_text()}\n"
                         f"{conversation_context(path)}\n"
                         f"Verdict: {verdict}\nEvidence folder: {verdict.parent / 'evidence'}\n")
            else:
                arguments = [cwd, data["branch"]] if worker_role == "build" else ["--detach", cwd, commit]
                git(data["repo"], "worktree", "add", *arguments)
                if worker_role == "verify":
                    brief = build_verify_brief(path, commit, cwd, root)
            (folder / "brief.md").write_text(brief + memory_brief(path, worker_role))
        except Exception:
            rollback_setup(path, marker, setup)
            raise
        setup["launching"] = True
        metadata["started_at"] = time.time()
        write_journal(marker, setup)
        (folder / "launch-pending.json").write_text(json.dumps(setup) + "\n")
        try:
            template = {"build": "hw-builder", "verify": "hw-verifier", "evidence": "hw-evidence-reviewer"}[worker_role]
            if settings["agent"] == "opencode":
                template += "-opencode"
            result = hc.launch(name=name, cwd=cwd, template=template,
                               task=str(folder / "brief.md") if program else f"Read {folder / 'brief.md'} in full and do what it says.",
                               identity=task_key(path), role=worker_role, parent=parent_session.get("address"), program=program)
        except (FileNotFoundError, PermissionError):
            rollback_setup(path, marker, setup)
            raise
        except Exception as error:
            raise RuntimeError(f"launch outcome uncertain for {name}: {error}; retained {marker}; retry to reconcile") from error
        setup["result"] = result
        write_journal(marker, setup)
        record_launch(path, result, **metadata)
        release_claim(data, setup)
        marker.unlink()
        (folder / "launch-pending.json").unlink()
        return result
