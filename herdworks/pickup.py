import re
import subprocess
import time
from pathlib import Path
from . import hc
from .runs import append_event, artifact_complete, events, first_line, git, is_stopped, locked, read_task, task_key

WORKER_FOLDER = re.compile(r'(build|verify)-[1-9][0-9]*')
FINISHED = ('verified', 'for review', 'needs manual verification', 'stopped')


def has_hidden_tracked_paths(wt):
    # ls-files -v marks skip-worktree with S and assume-unchanged with lowercase.
    entries = git(wt, 'ls-files', '-v', '-z').split('\0')
    return any(entry[0] == 'S' or entry[0].islower() for entry in entries if entry)


def remove_worktree(repo, wt):
    wt = Path(wt)
    if wt.is_symlink() or wt.parent.is_symlink():
        raise ValueError(f'refusing symlinked worktree: {wt}')
    if has_hidden_tracked_paths(wt):
        raise ValueError(f'clear assume-unchanged and skip-worktree flags before removing this worktree: {wt}')
    if git(wt, 'ls-files', '--others', '--ignored', '--exclude-standard', '--directory'):
        raise ValueError(f'move ignored files out of the worktree before removing it: {wt}')
    if git(wt, 'status', '--porcelain'):
        # Keep uncommitted work as a patch beside the worktree, so removal never loses it.
        git(wt, 'add', '-A')
        (wt.parent / 'unsaved.patch').write_text(git(wt, 'diff', '--cached', '--binary', 'HEAD') + '\n')
    git(repo, 'worktree', 'remove', '--force', wt)


def registered_worktrees(repo):
    records = git(repo, 'worktree', 'list', '--porcelain', '-z').split('\0\0')
    entries = [dict(field.partition(' ')[::2] for field in record.split('\0') if field)
               for record in records if record]
    return {entry['worktree']: entry for entry in entries}


def pristine(wt, generated_dirs=()):
    # Both status and non-force worktree removal can miss these tracked edits.
    if has_hidden_tracked_paths(wt):
        return False
    # NUL records keep filenames with whitespace or newlines unambiguous.
    status = git(wt, 'status', '--porcelain=v1', '-z', '--untracked-files=normal',
                 '--ignored=matching', '--ignore-submodules=none')
    ignored_prefixes = tuple(f'!! {name}/' for name in generated_dirs
                             if not (wt / name).is_symlink() and (wt / name).is_dir())
    return all(record.startswith(ignored_prefixes) for record in status.split('\0') if record)


def generated_worktree_dirs(project):
    from .projects import read_project
    names = read_project(project).get('generated_worktree_dirs', [])
    if not isinstance(names, list) or any(
            not isinstance(name, str) or name in ('.', '..') or name.lower() == '.git'
            or not re.fullmatch(r'[a-zA-Z0-9_.-]+', name) for name in names):
        raise ValueError('generated_worktree_dirs must be a list of top-level directory names')
    return names


def save_screen(folder, address):
    screen = folder / 'last-screen.txt'
    if not screen.exists():
        screen.write_text(hc.call('read', '--json', address)['text'])


def reclaim_worktrees(path):
    """Reclaim proven, ended worker checkouts under the caller's task lock."""
    history = events(path)
    ended_task = any(e.get('event') == 'closed' for e in history) or is_stopped(path)
    data = read_task(path)
    candidates = {}
    for event in history:
        role, name = event.get('role'), event.get('folder', '')
        if (event.get('event') != 'session' or role not in ('build', 'verify')
                or not WORKER_FOLDER.fullmatch(name) or not name.startswith(role + '-')
                or not event.get('address')):
            continue
        folder = path / name
        wt = folder / 'wt'
        if (wt.is_dir() and wt.resolve() == wt
                and not (path / f'.setup-{name}.json').exists()
                and not (folder / 'launch-pending.json').exists()):
            candidates[wt] = event
    if not candidates:
        return []
    entries = registered_worktrees(data['repo'])
    generated_dirs = generated_worktree_dirs(path.parents[1])
    removed = []
    for wt, event in candidates.items():
        entry = entries.get(str(wt), {})
        if not entry or 'locked' in entry or 'prunable' in entry:
            continue
        role, folder = event['role'], wt.parent
        if role == 'build':
            if entry.get('branch') != f"refs/heads/{data['branch']}":
                continue
            report = folder / 'report.md'
            complete = (not report.is_symlink()
                        and first_line(report) == f"READY {entry['HEAD']}"
                        and entry['HEAD'] != data['base'])
        else:
            if 'detached' not in entry or entry.get('HEAD') != event.get('commit'):
                continue
            complete = not (folder / 'verdict.md').is_symlink() and artifact_complete(folder, role)
        if not ended_task and not complete:
            continue
        state = hc.get(event['address']).get('state')
        if state not in ('finished', 'missing'):
            continue
        link = wt / '.git'
        if not link.is_file() or link.is_symlink() or not pristine(wt, generated_dirs):
            continue
        if state == 'finished':
            save_screen(folder, event['address'])
        # Git rechecks the checkout on removal. Never force automatic cleanup.
        git(data['repo'], 'worktree', 'remove', wt)
        removed.append(str(wt))
        append_event(path, dict(event='worktree-reclaimed', folder=folder.name, at=time.time()))
    return removed


def remove_task_worktrees(path):
    data = read_task(path)
    registered = registered_worktrees(data['repo'])
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


def close(path, reason=None, *, safe_only=False):
    from .runs import derive_status, events
    with locked(path.parents[3]), locked(path):
        if derive_status(path) not in FINISHED:
            raise ValueError('task close requires a finished task (verified, for review, needs manual verification or stopped)')
        for event in events(path):
            if event.get('event') == 'session' and event.get('address'):
                if hc.get(event['address']).get('state') == 'live':
                    raise ValueError('task still has live workers; reap or stop it before closing')
        if safe_only:
            if list(path.glob('*/wt')) or list(path.glob('.setup-*.json')):
                raise ValueError('worker folders retained; inspect them before closing the task')
            removed = []
        else:
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
    lines = []
    for item in task_paths(project):
        path = item.parent
        try:
            with locked(path):
                removed = reclaim_worktrees(path)
                if removed:
                    lines.append(f'{path.name} reclaimed {len(removed)} worktrees')
                if any(e.get('event') == 'closed' for e in events(path)):
                    continue
                pr = recorded_pr(path)
            if pr:
                state = pr_state(project, pr['url'])
                if state in ('MERGED', 'CLOSED'):
                    close(path, reason=f'pull request {state.lower()}', safe_only=True)
                    lines.append(f'{path.name} closed: pull request {state.lower()}')
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            lines.append(f'{path.name} not tidied: {error}')
    return lines
