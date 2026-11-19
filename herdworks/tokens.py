"""Token counts as the agents themselves report them. No count is ever estimated: None means unknown.

`total` is what a session spent: input, output and reasoning tokens. Cached input is kept beside it
and never added in: an agent re-reads its whole context from the cache on every turn, so cache reads
run to many times the fresh input and say little about what a task cost."""
import os
import sqlite3
from pathlib import Path

SPENT = ("input", "output", "reasoning")
CACHED = ("cache_read", "cache_write")


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
    counts = dict(zip(SPENT + CACHED, (int(value or 0) for value in row[1:])))
    return dict(counts, total=sum(counts[name] for name in SPENT))


def codex(cwd, since):
    row = query(codex_db(), "select count(*), sum(tokens_used) from threads where cwd = ? and created_at >= ?",
                str(cwd), int(since - SLACK))
    if not row or not row[0]:
        return None
    # Codex's database keeps one figure per thread, tokens_used: its running total of input and output
    # tokens, in which input counts the cached context again on every turn. It cannot be split here,
    # so the figure is passed on as Codex gives it and marked.
    return dict(total=int(row[1] or 0), includes_cached=True)


READERS = {"opencode": opencode, "codex": codex}


def read(agent, cwd, since=0):
    """What the session started in `cwd` at or after `since` has used, or None when its agent keeps no readable count.

    Each worker runs in its own folder, so the folder identifies the session; the start time keeps out
    an older session from a folder path that was used before. opencode reports each kind of token, so
    its `total` is input + output + reasoning with `cache_read` and `cache_write` beside it. Codex
    reports only `tokens_used`, which includes cached input: its result carries `includes_cached`."""
    reader = READERS.get(agent)
    return reader(cwd, since) if reader else None
