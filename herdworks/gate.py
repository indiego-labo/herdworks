import re
import time
from . import hc
from .pickup import remove_worktree
from .runs import append_event, built_commit, events, first_line, git, locked, newest_artifact, read_task, artifact_complete


def has_evidence(folder):
    return any(p.is_file() and not p.is_symlink() for p in (folder / "evidence").rglob("*"))


def blocked_lines(artifact):
    if artifact is None or not artifact.is_file():
        return []
    return [line.split(':', 1)[1].strip() for line in artifact.read_text().splitlines()
            if line.startswith('BLOCKED-BY-ENVIRONMENT:') and line.split(':', 1)[1].strip()]


def environment_only(artifact):
    openings = {'verdict.md': ('PASS', 'INCONCLUSIVE'), 'review.md': ('CONFIRMED', 'INCONCLUSIVE')}
    return (first_line(artifact) in openings.get(artifact.name, ())
            and bool(blocked_lines(artifact))
            and any(line.startswith('PASSED-OTHER-CHECKS:') and line.split(':', 1)[1].strip()
                    for line in artifact.read_text().splitlines()))


def blocked_requirements(path):
    return list(dict.fromkeys(item for pattern in ('verify-*/verdict.md', 'evidence-*/review.md')
                              for item in blocked_lines(newest_artifact(path, pattern))))


def check_gate(path, manual_verification=False):
    reasons = []
    commit = built_commit(path)
    if not commit:
        reasons.append("newest report must open READY with the current branch head, different from base")
    report = newest_artifact(path, "build-*/report.md")
    verdict = newest_artifact(path, "verify-*/verdict.md")
    review = newest_artifact(path, "evidence-*/review.md")
    history = [e for e in events(path) if e.get("event") == "session"]
    build = next((e for e in reversed(history) if report and e.get("role") == "build"
                  and e.get("folder") == report.parent.name), None)
    verifier = next((e for e in reversed(history) if verdict and e.get("role") == "verify"
                     and e.get("folder") == verdict.parent.name), None)
    if verifier and verifier.get("launch_source") != "template":
        reasons.append("verdict session must come from the verifier template, not a --role override or unknown launch source")
    verdict_ok = first_line(verdict) == 'PASS' and not blocked_lines(verdict) if verdict else False
    if manual_verification and verdict and environment_only(verdict):
        verdict_ok = True
    if not verdict_ok:
        reasons.append("newest verdict must open with exactly PASS")
    verified_commits = re.findall(r"^Commit: ([0-9a-f]{40,64})$", verdict.read_text(), re.MULTILINE) if verdict else []
    if not commit or verified_commits != [commit]:
        reasons.append("verdict must name the current built commit")
    if (not verifier or not build or verifier.get("address") == build.get("address")
            or not report or verifier.get("started_at", 0) < report.stat().st_mtime
            or verifier.get("started_at", 0) <= build.get("started_at", 0)
            or verifier.get("commit") != commit
            or verdict.stat().st_mtime < verifier.get("started_at", 0)):
        reasons.append("verdict must belong to a recorded independent verify session started after the build")
    if not verdict or not has_evidence(verdict.parent):
        reasons.append("verifier evidence must contain at least one file")
    reviewer = next((e for e in reversed(history) if review and e.get("role") == "evidence"
                     and e.get("folder") == review.parent.name), None)
    if reviewer and reviewer.get("launch_source") != "template":
        reasons.append("review session must come from the evidence-reviewer template, not a --role override or unknown launch source")
    review_ok = first_line(review) == 'CONFIRMED' and not blocked_lines(review) if review else False
    if manual_verification and review and environment_only(review):
        review_ok = True
    if (not review_ok or not reviewer or not verdict or not verifier
            or reviewer.get("started_at", 0) < verdict.stat().st_mtime
            or review.stat().st_mtime < reviewer.get("started_at", 0)
            or reviewer.get("commit") != commit or reviewer.get("verifier") != verifier.get("name")
            or reviewer.get("address") in {e.get("address") for e in (build, verifier) if e}):
        reasons.append("review must open CONFIRMED and come from an evidence session started after the verdict")
    for artifact in (verdict, review):
        if artifact and any(line.startswith('BLOCKED-BY-ENVIRONMENT:') and not line.split(':', 1)[1].strip()
                            for line in artifact.read_text().splitlines()):
            reasons.append('environment blocker must name the unproven requirement and missing prerequisite')
    blockers = blocked_requirements(path)
    if manual_verification and not blockers:
        reasons.append('manual verification requires an environment-blocked requirement')
    elif not manual_verification and blockers:
        reasons.append('requirements blocked by environment; needs manual verification')
    return not reasons, commit, reasons


def gate(path):
    with locked(path):
        passed, commit, reasons = check_gate(path)
        append_event(path, {"event": "gate", "at": time.time(), "passed": passed,
                            "commit": commit, "reasons": reasons})
    return passed, commit, reasons


def reap(path):
    reaped = []
    with locked(path):
        data = read_task(path)
        history = events(path)
        for event in history:
            role = event.get("role")
            if event.get("event") != "session" or role == "coordinator":
                continue
            folder = path / event["folder"]
            artifact = {"build": "report.md", "verify": "verdict.md", "evidence": "review.md"}[role]
            if not artifact_complete(folder, role):
                continue
            session = hc.get(event["address"])
            if session.get("state") in ("live", "finished") and not (folder / "last-screen.txt").exists():
                screen = hc.call("read", "--json", event["address"])
                (folder / "last-screen.txt").write_text(screen["text"])
            if session.get("state") == "live":
                hc.call("kill", event["address"])
            wt = folder / "wt"
            if role == "verify" and wt.exists():
                remove_worktree(data["repo"], wt)
            if not any(e.get("event") == "reaped" and e.get("name") == event["name"] for e in history):
                append_event(path, {"event": "reaped", "name": event["name"], "at": time.time()})
            reaped.append(event["name"])
    return reaped
