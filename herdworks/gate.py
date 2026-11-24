import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from . import hc
from .limits import project_setting
from .pickup import reclaim_worktrees, save_screen
from .runs import append_event, built_commit, events, first_line, git, locked, newest_artifact, read_task, artifact_complete

GRADES = ("PROVED", "DISPROVED", "NOT_PROVED")


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


def read_claims(folder):
    try:
        claims = json.loads((folder / "claims.json").read_text())
    except (OSError, ValueError):
        return None
    return claims if isinstance(claims, list) and claims and all(isinstance(c, dict) for c in claims) else None


def stated(value):
    return isinstance(value, str) and bool(value.strip())


def evidence_file(folder, value):
    """True for a saved evidence file, named from the verdict's folder or the verifier's worktree."""
    for base in (folder, folder / "wt") if stated(value) else ():
        proof = Path(os.path.normpath(base / value))
        if (proof.is_file() and not proof.is_symlink()
                and (folder / "evidence").resolve() in proof.resolve().parents):
            return True
    return False


def claim_problems(folder, kind=None):
    """Why claims.json cannot stand behind the verdict beside it; empty when it can."""
    claims = read_claims(folder)
    if claims is None:
        return ["verifier must write claims.json: a list with one graded entry per acceptance criterion"]
    names = [c.get("id") for c in claims]
    if not all(map(stated, names)) or len(set(names)) != len(names):
        return ["every claim in claims.json needs its own id"]
    problems = []
    for claim in claims:
        name, grade = claim["id"], claim.get("grade")
        if grade not in GRADES:
            problems.append(f"claim {name} must be graded PROVED, DISPROVED or NOT_PROVED")
        elif grade == "NOT_PROVED":
            if not stated(claim.get("reason")):
                problems.append(f"claim {name} is NOT_PROVED without a reason")
        elif not stated(claim.get("check")) or not evidence_file(folder, claim.get("evidence")):
            problems.append(f"claim {name} is {grade} without a check and an existing evidence file")
    if problems:
        return problems
    # The verdict is a function of the grades. A spike reports findings, so DISPROVED is an answer.
    grades = {c["grade"] for c in claims}
    if kind == "spike":
        derived = ("PASS", "INCONCLUSIVE") if "NOT_PROVED" in grades else ("PASS",)
    else:
        derived = ("FAIL",) if "DISPROVED" in grades else ("INCONCLUSIVE",) if "NOT_PROVED" in grades else ("PASS",)
    if first_line(folder / "verdict.md") not in derived:
        return [f"verdict.md must open {' or '.join(derived)}, as claims.json grades it"]
    return []


def checks_command(project):
    command = project_setting(project, "checks")
    if command is not None and not stated(command):
        raise ValueError("checks must be a command")
    return command


def run_checks(path, commit):
    """Run the Project's checks command in a fresh checkout of the built commit."""
    command = checks_command(path.parents[1])
    if not command or not commit:
        return None
    repo = read_task(path)["repo"]
    # The result must not depend on who runs the gate, so the coordinator's session identity is left out.
    environment = {k: v for k, v in os.environ.items() if k not in ("HW_CALLER_TERMINAL", "HW_HC_HOP")}
    wt = path / "checks"

    def discard():
        try:
            git(repo, "worktree", "remove", "--force", wt)
        except RuntimeError:
            shutil.rmtree(wt, ignore_errors=True)
    if wt.exists():
        discard()  # left by an interrupted run
    try:
        git(repo, "worktree", "add", "--force", "--detach", wt, commit)
        result = subprocess.run(command, shell=True, cwd=wt, env=environment, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    finally:
        discard()
    return {"command": command, "commit": commit, "exit": result.returncode, "tail": result.stdout[-2000:]}


def check_gate(path, manual_verification=False, checks=None):
    """Judge the task from its records. Only `gate` runs the checks command; here its last record is read."""
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
    if verdict:
        kind = read_task(path).get("kind")
        problems = claim_problems(verdict.parent, kind)
        reasons.extend(problems or [
            f"claim {c['id']} is {c['grade']}" for c in read_claims(verdict.parent) if kind != "spike"
            and (c["grade"] == "DISPROVED" or (c["grade"] == "NOT_PROVED" and not manual_verification))])
    command = checks_command(path.parents[1])
    if command and commit:
        ran = checks or next((e["checks"] for e in reversed(events(path))
                              if e.get("event") == "gate" and e.get("checks")), None)
        if not ran or ran["command"] != command or ran["commit"] != commit:
            reasons.append("checks command has not run on the built commit; run hw gate")
        elif ran["exit"]:
            reasons.append(f"checks command exited {ran['exit']}")
    return not reasons, commit, reasons


def gate(path):
    cap = project_setting(path.parents[1], "max_same_reason_failures")
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        raise ValueError("max_same_reason_failures must be a positive integer")
    with locked(path):
        checks = run_checks(path, built_commit(path))
        passed, commit, reasons = check_gate(path, checks=checks)
        history = events(path)
        append_event(path, {"event": "gate", "at": time.time(), "passed": passed,
                            "commit": commit, "reasons": reasons, **({"checks": checks} if checks else {})})
        if not passed:
            # The same refusal on another commit means one more build will not help; a person decides.
            last = max((i for i, e in enumerate(history) if e.get("event") == "escalated"), default=-1)
            repeats = {e.get("commit") for e in history[last + 1:] if e.get("event") == "gate"
                       and not e.get("passed") and e.get("reasons") == reasons} | {commit}
            if len(repeats) >= cap:
                append_event(path, {"event": "escalated", "at": time.time(), "commit": commit,
                                    "failures": len(repeats), "reasons": reasons})
    return passed, commit, reasons


def reap(path):
    reaped = []
    with locked(path):
        history = events(path)
        for event in history:
            role = event.get("role")
            if event.get("event") != "session" or role == "coordinator":
                continue
            folder = path / event["folder"]
            if not artifact_complete(folder, role):
                continue
            session = hc.get(event["address"])
            if session.get("state") in ("live", "finished"):
                save_screen(folder, event["address"])
            if session.get("state") == "live":
                hc.call("kill", event["address"])
            if not any(e.get("event") == "reaped" and e.get("name") == event["name"] for e in history):
                append_event(path, {"event": "reaped", "name": event["name"], "at": time.time()})
            reaped.append(event["name"])
        reclaim_worktrees(path)
    return reaped
