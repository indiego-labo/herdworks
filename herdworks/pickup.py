import re
import subprocess
import time
from pathlib import Path
from . import hc
from .runs import append_event, locked, task_key

WORKER_FOLDER = re.compile(r'(build|verify)-[1-9][0-9]*')
FINISHED = ('verified', 'for review', 'needs manual verification', 'stopped')


def remove_worktree(repo, wt):
    from .runs import git
    wt = Path(wt)
    if wt.is_symlink() or wt.parent.is_symlink():
        raise ValueError(f'refusing symlinked worktree: {wt}')
    if git(wt, 'status', '--porcelain'):
        # Keep uncommitted work as a patch beside the worktree, so removal never loses it.
        git(wt, 'add', '-A')
        (wt.parent / 'unsaved.patch').write_text(git(wt, 'diff', '--cached', '--binary', 'HEAD') + '\n')
    git(repo, 'worktree', 'remove', '--force', wt)


def remove_task_worktrees(path):
    from .runs import git, read_task
    data = read_task(path)
    registered = {line[9:] for line in git(data['repo'], 'worktree', 'list', '--porcelain').splitlines()
                  if line.startswith('worktree ')}
    found = []
    for folder in sorted(path.iterdir()):
        if not WORKER_FOLDER.fullmatch(folder.name):
            continue
        wt = folder / 'wt'
        if folder.is_symlink() or wt.is_symlink():
            raise ValueError(f'refusing symlinked worktree: {wt}')
        if str(wt) in registered:
            found.append(wt)
        elif wt.exists():
            raise ValueError(f'refusing unregistered folder: {wt}')
    for wt in found:
        remove_worktree(data['repo'], wt)
    return [str(wt) for wt in found]


def stop(path):
    with locked(path):
        stopped = []
        for item in reversed(hc.sessions()):
            session = hc.get(item["address"])
            if session.get("labels", {}).get("hw") == task_key(path) and session.get("state") == "live":
                hc.call("kill", session["address"])
                stopped.append(session.get("name", session["address"]))
        record = {"event": "stop", "at": time.time(), "sessions": stopped}
        try:
            record["worktrees"] = remove_task_worktrees(path)
        except (RuntimeError, ValueError) as error:
            # The stop itself must always be recorded; a folder that cannot be removed is reported instead.
            record["worktree_error"] = str(error)
        append_event(path, record)
        return stopped


def close(path, reason=None):
    from .runs import derive_status, events
    with locked(path.parents[3]), locked(path):
        if derive_status(path) not in FINISHED:
            raise ValueError('task close requires a finished task (verified, for review, needs manual verification or stopped)')
        for event in events(path):
            if event.get('event') == 'session' and event.get('address'):
                if hc.get(event['address']).get('state') == 'live':
                    raise ValueError('task still has live workers; reap or stop it before closing')
        removed = remove_task_worktrees(path)
        if not any(e.get('event') == 'closed' for e in events(path)):
            append_event(path, dict(event='closed', at=time.time(), worktrees=removed,
                                    **({'reason': reason} if reason else {})))
        return removed


def pr_state(project, url):
    from .projects import read_project
    result = subprocess.run([read_project(project).get('gh', 'gh'), 'pr', 'view', url,
                             '--json', 'state', '--jq', '.state'],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'gh pr view failed')
    return result.stdout.strip()


def tidy(project):
    from .pr import recorded_pr
    from .projects import task_paths
    from .runs import events, is_stopped
    lines = []
    for item in task_paths(project):
        path = item.parent
        if any(e.get('event') == 'closed' for e in events(path)):
            continue
        pr = recorded_pr(path)
        try:
            if pr:
                state = pr_state(project, pr['url'])
                if state in ('MERGED', 'CLOSED'):
                    removed = close(path, reason=f'pull request {state.lower()}')
                    lines.append(f'{path.name} closed: pull request {state.lower()}, removed {len(removed)} worktrees')
            elif is_stopped(path):
                with locked(path):
                    removed = remove_task_worktrees(path)
                if removed:
                    lines.append(f'{path.name} stopped: removed {len(removed)} worktrees')
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            lines.append(f'{path.name} not tidied: {error}')
    return lines
