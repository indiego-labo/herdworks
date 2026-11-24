import json
from pathlib import Path
import sys

root = Path(sys.argv[1])

def rows(name):
    return [json.loads(line) for line in (root / name).read_text().splitlines()]

def assessments(name):
    return [row for row in rows(name) if row.get("command", [])[1:3] in
            (["task", "impact"], ["task", "correct-impact"])]

worker = json.loads((root / "worker-terminal.json").read_text())
coord_start = next(row for row in rows("coordinator.jsonl") if row.get("event") == "start")
worker_start = next(row for row in rows("worker.jsonl") if row.get("event") == "start")
assert worker["address"] == worker_start["terminal"] != coord_start["terminal"] == worker["parent"]
assert {row["command"][2] for row in assessments("coordinator.jsonl")} == {"impact", "correct-impact"}
assert not assessments("worker.jsonl")
print("Worker:", worker["address"], worker["name"], worker["labels"], worker["template"])
print("Coordinator:", coord_start["terminal"])
for row in assessments("coordinator.jsonl"):
    print(row["command"], "exit", row["exit"], row["stderr"].strip())
print("Worker assessment commands:", len(assessments("worker.jsonl")))
