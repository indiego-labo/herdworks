"""Check the coordinator's HW-7 attachment against the retained HW-11 run."""

import csv
import json
from pathlib import Path
import re
import sys


def require(condition, description):
    if not condition:
        raise SystemExit(f"LINK-BACK FAIL {description}")
    print(f"LINK-BACK PASS {description}", flush=True)


project = Path(sys.argv[1])
hw7 = project / "tasks/HW-7"
hw11 = project / "tasks/HW-11"
notes = project / "coordinator/tasks/HW-7"
trace_path = "verify-1/evidence/agent-dev-verifier"
trace = hw11 / trace_path
candidate = "610fa3acebe97e050beeba00de11e7f8f43d1903"
transcript = (trace / "merge-green.txt").read_text()
merge = re.search(r"^Merged verified green HEAD ([0-9a-f]{40})$", transcript, re.M)
require(merge and transcript.endswith("exit=0\n"), "independent command succeeded")
head = merge[1]
after = json.loads((trace / "after/fixture-pr.json").read_text())
require(after["state"] == "MERGED" and after["headRefOid"] == head,
        f"independent fixture PR merged verified HEAD {head}")

catchup = (notes / "catchup.md").read_text()
_, _, attachment = catchup.partition("### HW-11 direct-command evidence")
require(candidate in catchup and all(value in attachment for value in (
    "independent Linux", "hw merge-green", "fixture PR", "Exit was 0", head,
    "MERGED", f"tasks/HW-11/{trace_path}/", "verify-1/verdict.md",
    "evidence-1/review.md", "Live GitHub protections remain untested",
)), "HW-7 catchup carries the scoped result and points to independent proof")

with (notes / "decisions.tsv").open(newline="") as decisions:
    require(any(
        len(row) == 6 and row[1] == "evidence-link"
        and "HW-11" in row[2] and "HW-7" in row[2]
        and "direct-command" in row[3]
        and all(link in row[4] for link in (
            "HW-11", trace_path, "verify-1/verdict.md", "evidence-1/review.md",
        ))
        and "HW-7 gate unchanged" in row[5]
        for row in csv.reader(decisions, delimiter="\t")
    ), "HW-7 decisions record the attachment and point to the same proof")

verdict = (hw11 / "verify-1/verdict.md").read_text()
review = (hw11 / "evidence-1/review.md").read_text()
require(candidate in verdict and verdict.startswith("PASS\n") and head in verdict
        and "Live GitHub branch protection and required-check enforcement remain untested" in verdict
        and review.startswith("REJECTED\n") and head in review,
        "references resolve to the scoped independent verdict and its evidence review")

events = [json.loads(line) for line in (hw7 / "events.jsonl").read_text().splitlines()]
gates = [event for event in events if event["event"] == "gate"]
require(gates and gates[-1]["commit"] == candidate and gates[-1]["passed"] is False
        and "requirements blocked by environment; needs manual verification" in gates[-1]["reasons"]
        and (hw7 / "verify-4/verdict.md").read_text().startswith(f"INCONCLUSIVE\nCommit: {candidate}\n")
        and (hw7 / "evidence-3/review.md").read_text().startswith(f"REJECTED\n\nCommit: {candidate}\n"),
        "original HW-7 gate refusal, verdict and review still apply to the candidate")
