"""Token counts as the agents themselves report them. No count is ever estimated: None means unknown."""
import os
import sqlite3
from pathlib import Path

PARTS = ("input", "output", "reasoning", "cache_read", "cache_write")


def opencode_db():
    # bin/hw-opencode always points opencode's data folder here.
    return Path.home() / ".local/share/opencode/opencode.db"


def codex_db():
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    found = sorted(home.glob("state_*.sqlite"), key=lambda p: int(p.stem.split("_")[1]) if p.stem.split("_")[1].isdecimal() else -1)
    return found[-1] if found else home / "state.sqlite"


SLACK = 60  # seconds a session's own start time may precede the launch Herdworks recorded


def query(database, sql, *values):
    """One row from the agent's own database, opened read-only; None when it cannot answer."""
    if not Path(database).is_file():
        return None
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=1)
        try:
            return connection.execute(sql, values).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None


def opencode(cwd, since):
    row = query(opencode_db(), "select count(*), sum(tokens_input), sum(tokens_output), sum(tokens_reasoning), "
                               "sum(tokens_cache_read), sum(tokens_cache_write) from session_v2 "
                               "where directory = ? and time_created >= ?", str(cwd), int((since - SLACK) * 1000))
    if not row or not row[0]:
        return None
    counts = dict(zip(PARTS, (int(value or 0) for value in row[1:])))
    return dict(counts, total=sum(counts.values()))


def codex(cwd, since):
    row = query(codex_db(), "select count(*), sum(tokens_used) from threads where cwd = ? and created_at >= ?",
                str(cwd), int(since - SLACK))
    if not row or not row[0]:
        return None
    return dict(total=int(row[1] or 0))


READERS = {"opencode": opencode, "codex": codex}


def read(agent, cwd, since=0):
    """What the session started in `cwd` at or after `since` has used, or None when its agent keeps no readable count.

    Each worker runs in its own folder, so the folder identifies the session; the start time keeps out
    an older session from a folder path that was used before. `total` counts every token the agent
    reports, cached input included."""
    reader = READERS.get(agent)
    return reader(cwd, since) if reader else None
