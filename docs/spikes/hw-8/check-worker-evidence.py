#!/usr/bin/env python3
"""Check the legacy worker boundaries in the retained HW-8 Linux evidence."""
import argparse
import json
from pathlib import Path


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("evidence", type=Path, help="Independent verifier's evidence directory")
args = parser.parse_args()
linux = args.evidence / "agent-dev"
task = linux / "tasks/IV-2"
session = json.loads((linux / "worker-session.txt").read_text())
event, = (entry for entry in records(task / "events.jsonl") if entry["event"] == "session")
assert event["launch_source"] == "template" and event["role"] == "build"
assert session["template"] == "hw-builder" and session["state"] == "live"
assert event["address"] == session["address"] and event["parent"] == session["parent"]
assert (linux / "legacy-task.json").is_file()
legacy = json.loads((linux / "legacy-task.json").read_text())
assert legacy["message"] == 2 and "impact" not in legacy
print("Legacy template launch: PROVED (live herdr child and task worktree)")

worker, = (entry for entry in records(linux / "processes.jsonl") if entry["role"] == "builder")
cli, = records(linux / "builder-cli.jsonl")
assert worker["terminal"] == session["address"] and worker["cwd"] == session["cwd"]
assert session["argv"][-1].endswith("/bin/hw-codex worker")
assert legacy["id"] in Path(worker["cwd"]).parts and Path(worker["cwd"]).name == "wt"
assert Path(cli["command"][0]).name == "codex"
assert cli["command"][1:] == ["--help", *worker["argv"]]
assert cli["exit_code"] == 0 and "Usage: codex" in cli["output"]
print("Legacy adapter and installed CLI argument parsing: PROVED (codex --help)")

spawn = json.loads((linux / "legacy-spawn.txt").read_text())
assert spawn["address"] == event["address"]
assert spawn["first_message"] == event["first_message"] and event["first_message"]["sent"]
prompt, = records(linux / "builder-pty.jsonl")
brief = Path(session["cwd"]).parent / "brief.md"
assert f"Read {brief} in full" in prompt["text"]
assert "Legacy request without assessment" in (task / "build-1/brief.md").read_text()
print("Legacy automatic prompt delivery: PROVED (real transport to a fixture)")

commands = json.loads((args.evidence / "commands.json").read_text())
codex = Path(cli["command"][0])
calls = [entry for entry in commands if entry["command"].startswith(f"{codex} ")]
assert calls and all(entry["command"].startswith(f"{codex} --help ")
                     and entry["exit_code"] == 0 for entry in calls)
assert not (task / "build-1/report.md").exists()
print(f"Model-backed Codex startup: NOT_PROVED ({len(calls)} recorded direct calls, all help only)")
print("Model-backed Codex prompt handling: NOT_PROVED (fixture consumed the prompt)")
