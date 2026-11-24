#!/usr/bin/env python3
"""Stand in for the publisher on github.invalid. All writes are to the fixture."""
import json
from pathlib import Path
import subprocess
import sys

root = Path.cwd().parent
bare = root / "remote.git"
state_file = root / "fixture-pr.json"
log = root / "evidence" / "publisher.jsonl"
branch = "hw/HE-1"
url = "https://github.invalid/fixture/hello/pull/1"


def git(*args, **kwargs):
    return subprocess.check_output(
        ["git", "--git-dir", str(bare), *args], text=True, **kwargs
    ).strip()


def record(**fields):
    with log.open("a") as stream:
        stream.write(json.dumps(fields) + "\n")


args = sys.argv[1:]
if args == ["pr", "create", "--base", "main", "--head", branch]:
    assert not state_file.exists()
    pr = dict(id="fixture-pr", state="OPEN", isDraft=False,
              headRefOid=git("rev-parse", f"refs/heads/{branch}"),
              headRefName=branch, baseRefName="main", mergeStateStatus="CLEAN",
              headRepository={"nameWithOwner": "fixture/hello"},
              viewerCanMergeAsAdmin=False, isMergeQueueEnabled=False,
              isInMergeQueue=False, autoMergeRequest=None)
    state_file.write_text(json.dumps(pr) + "\n")
    record(args=args, url=url, response=pr)
    print(url)
else:
    assert args == ["api", "graphql", "--hostname", "github.invalid",
                    "--method", "POST", "--input", "-"]
    request = json.load(sys.stdin)
    query = request["query"]
    variables = request["variables"]
    pr = json.loads(state_file.read_text())
    record(args=args, request=request)
    if "query(" in query:
        assert variables == dict(owner="fixture", name="hello", number=1)
        response = dict(repository=dict(nameWithOwner="fixture/hello", autoMergeAllowed=True,
                                        squashMergeAllowed=True, pullRequest=pr))
    else:
        assert "mergePullRequest(" in query and "expectedHeadOid: $sha" in query
        assert pr["state"] == "OPEN"
        head = git("rev-parse", f"refs/heads/{branch}")
        assert variables == dict(id=pr["id"], sha=pr["headRefOid"], method="SQUASH")
        assert variables["sha"] == head
        base = git("rev-parse", "refs/heads/main")
        tree = git("rev-parse", f"{head}^{{tree}}")
        merged = git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                     "commit-tree", tree, "-p", base, input="Fixture pull request 1\n")
        git("update-ref", "refs/heads/main", merged, base)
        pr["state"] = "MERGED"
        state_file.write_text(json.dumps(pr) + "\n")
        response = dict(mergePullRequest=dict(pullRequest=dict(state="MERGED", headRefOid=head)))
    record(response=response)
    print(json.dumps(dict(data=response)))
