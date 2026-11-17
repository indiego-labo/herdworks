import os
import time
from pathlib import Path
from . import hc
from .runs import events, first_line, git, read_task, waiting_on_answer, ARTIFACT, artifact_complete


def newest_file(path):
    newest = 0.0
    if not path.exists():
        return newest
    for directory, folders, files in os.walk(path):
        folders[:] = [name for name in folders if name != ".git"]
        for name in files:
            file = Path(directory) / name
            if file.is_symlink():
                continue
            try:
                newest = max(newest, file.stat().st_mtime)
            except FileNotFoundError:
                pass
    return newest


def progress_time(path, event):
    data = read_task(path)
    folder = path / event["folder"]
    latest = max(event["started_at"], newest_file(folder))
    try:
        commit = git(data["repo"], "log", "-1", "--format=%ct", f"refs/heads/{data['branch']}")
        latest = max(latest, float(commit))
    except RuntimeError:
        pass
    return latest


def probe(path, clock=time.time):
    facts = []
    for event in events(path):
        if event.get("event") != "session" or event.get("role") == "coordinator":
            continue
        session = hc.get(event["address"])
        quiet = max(0.0, (clock() - progress_time(path, event)) / 60)
        artifact = ARTIFACT[event["role"]]
        artifact_path = path / event["folder"] / artifact
        waiting = waiting_on_answer(path)
        stalled = (session.get("state") == "live"
                   and not artifact_complete(artifact_path.parent, event["role"]) and not waiting
                   and quiet > event["stuck_after_minutes"])
        lines = artifact_path.read_text().splitlines() if artifact_path.exists() else []
        facts.append({"name": event["name"], "role": event["role"],
                      "launch_source": event.get("launch_source", "unknown"),
                      "state": session.get("state"),
                      "status": (session.get("status") or {}).get("state")
                      if isinstance(session.get("status"), dict) else session.get("status"),
                      "turn": session.get("turn", 0), "quiet_minutes": quiet,
                      "stuck_after_minutes": event["stuck_after_minutes"],
                      "artifact": first_line(artifact_path), "stalled": stalled,
                      "cause": next((line for line in lines if line.startswith("Cause:")), ""),
                      "ask": next((line for line in lines if line.startswith("Ask:")), "")})
    return facts


def format_fact(fact):
    return (f"{fact['name']} role={fact['role']} launch={fact['launch_source']} status={fact['status']} turn={fact['turn']} "
            f"quiet={fact['quiet_minutes']:.1f}m stuck-after={fact['stuck_after_minutes']}m "
            f"{fact['artifact']} {'STALLED' if fact.get('stalled') else ''} "
            f"{fact.get('cause', '')} {fact.get('ask', '')}").rstrip()
