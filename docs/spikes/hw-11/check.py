"""Drive the unmodified merge-green CLI after preparing an already-published fixture."""
import importlib.util
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import time

root = Path.cwd()
source = root / "candidate"
evidence = root / "evidence"
repo = root / "repo"
bare = root / "remote.git"
publisher = root / "fixture-publisher.py"
candidate = "610fa3acebe97e050beeba00de11e7f8f43d1903"

sys.path.insert(0, str(source))
from herdworks.impact import update
from herdworks.projects import add_project, grant_project, new_task
from herdworks.runs import append_event, git

spec = importlib.util.spec_from_file_location(
    "journey", source / ".agents/skills/verify-herdworks/scripts/journey.py"
)
journey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journey)


def capture(name, *argv, cwd=root):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    (evidence / f"{name}.txt").write_text(
        f"cwd={cwd}\n$ {shlex.join(map(str, argv))}\n"
        f"stdout:\n{result.stdout}stderr:\n{result.stderr}exit={result.returncode}\n"
    )
    result.check_returncode()
    return result.stdout.strip()


def refs():
    return git(bare, "show-ref").splitlines()


def snapshot(name, project):
    destination = evidence / name
    destination.mkdir()
    journey.collect(project, destination)
    shutil.copyfile(root / "fixture-pr.json", destination / "fixture-pr.json")
    journey.save(destination / "refs.json", refs())
    return destination


assert platform.system() == "Linux"
assert capture("candidate", "git", "-C", source, "rev-parse", "HEAD") == candidate
assert not capture("candidate-status", "git", "-C", source, "status", "--porcelain")
journey.save(evidence / "operator.json", dict(
    host=platform.node(), system=platform.system(), python=platform.python_version(),
    pid=os.getpid(), transport="agent-dev SSH command outside any Herdworks session",
    fixture_only=True,
))
journey.save(evidence / "doctor.json", journey.doctor("opencode"))

journey.fixture(repo)
baseline = git(repo, "rev-parse", "HEAD")
request = root / "request.md"
request.write_text("Make a small change in the hello fixture.\n")
project = add_project("hello", repo, prefix="HE")
task, _ = new_task(project, request)
branch = "hw/HE-1"
git(repo, "checkout", "-b", branch)
(repo / "proof.txt").write_text("Fixture contribution\n")
git(repo, "add", "proof.txt")
git(repo, "commit", "-m", "test: add fixture contribution")
head = git(repo, "rev-parse", "HEAD")
capture("bare-setup", "git", "clone", "--bare", repo, bare)
git(repo, "remote", "add", "origin", str(bare))
git(repo, "remote", "set-url", "--push", "origin", "git@github.invalid:fixture/hello.git")
grant_project(project, gh=str(publisher), green_merge="squash")
update(task, "green", "Small fixture change", reproduction="not-applicable", confidence="high")

# Seed completed fixture records, with the ordering from tests.support.GateCase.
# The actual gate reads them during merge-green. No role session is launched.
now = time.time() - 10
for role, stamp, name, extra in (
    ("build", now + 1, "report.md", {}),
    ("verify", now + 3, "verdict.md", {"commit": head}),
    ("evidence", now + 5, "review.md", {"commit": head, "verifier": "fixture-verify"}),
):
    folder = task / f"{role}-1"
    folder.mkdir()
    artifact = folder / name
    text = {
        "build": f"READY {head}",
        "verify": f"PASS\nCommit: {head}",
        "evidence": "CONFIRMED",
    }[role]
    artifact.write_text(text + "\n")
    os.utime(artifact, (stamp + 1, stamp + 1))
    if role == "verify":
        file = folder / "evidence" / "fixture.txt"
        file.parent.mkdir()
        proof = capture("fixture-content", "git", "-C", repo, "show", f"{head}:proof.txt")
        assert proof == "Fixture contribution"
        file.write_text(proof + "\n")
        journey.save(folder / "claims.json", [dict(
            id="AC-1", grade="PROVED", check=f"git show {head}:proof.txt",
            evidence="evidence/fixture.txt",
        )])
    append_event(task, dict(event="session", role=role, folder=folder.name, name=f"fixture-{role}",
                            address=f"fixture-{role}", started_at=stamp, launch_source="template", **extra))

url = capture("publication", publisher, "pr", "create", "--base", "main", "--head", branch, cwd=repo)
append_event(task, dict(event="pr", commit=head, url=url, branch=branch,
                        remote="origin", manual_verification=False))
before = snapshot("before", project)
publication = json.loads((before / "fixture-pr.json").read_text())
assert publication["state"] == "OPEN" and publication["headRefOid"] == head
assert f"{baseline} refs/heads/main" in refs()

# A separate CLI process operates on the retained pre-state.
try:
    result = capture("merge-green", source / "bin/hw", "merge-green", "hello", "HE-1")
finally:
    after = snapshot("after", project)

entries = [json.loads(line) for line in (evidence / "publisher.jsonl").read_text().splitlines()]
assert len(entries) == 5
lookup = entries[1]["request"]
mutation = entries[3]["request"]
assert "query(" in lookup["query"]
assert "expectedHeadOid: $sha" in mutation["query"] and mutation["variables"]["sha"] == head
pr = json.loads((after / "fixture-pr.json").read_text())
history = [json.loads(line) for line in (after / "events.jsonl").read_text().splitlines()]
assert result == f"Merged verified green HEAD {head}"
assert pr["state"] == "MERGED" and pr["headRefOid"] == head
assert [event["event"] for event in history[-3:]] == ["pr", "green-merge-started", "green-merge"]
assert all(event["commit"] == head for event in history[-3:]) and history[-1]["merged"] is True

target = git(bare, "rev-parse", "refs/heads/main")
assert target != baseline
assert git(bare, "rev-parse", f"{target}^") == baseline
assert git(bare, "rev-parse", f"{target}^{{tree}}") == git(bare, "rev-parse", f"{head}^{{tree}}")
journey.save(evidence / "assertions.json", dict(
    candidate=candidate, verified_head=head, mutation_expected_head=mutation["variables"]["sha"],
    pr_before=publication["state"], pr_after=pr["state"], target_before=baseline, target_after=target,
    target_parent=baseline, target_tree=git(bare, "rev-parse", f"{target}^{{tree}}"),
    final_events=[event["event"] for event in history[-3:]],
))
capture("candidate-tests", "python3", "-m", "unittest", "discover", "-s", "tests", cwd=source)
