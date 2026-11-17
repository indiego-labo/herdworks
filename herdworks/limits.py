import json
import math
import shutil
from pathlib import Path
from .home import hw_home, sandbox_setting

DEFAULTS = dict(max_tasks_at_once=2, max_worker_sessions=4, max_worktrees=6,
                min_free_disk_gb=5, max_sessions_per_task=12)
ROLES = ('coordinator', 'builder', 'verifier', 'evidence-reviewer')


def config(home=None):
    home = Path(home) if home is not None else hw_home()
    path = home / 'config.json'
    data = json.loads(path.read_text()) if path.exists() or path.is_symlink() else {}
    if not isinstance(data, dict):
        raise ValueError('config.json must be an object')
    result = dict(DEFAULTS, **data)
    for name in DEFAULTS:
        value = result[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'{name} must be a finite nonnegative number')
        if name != 'min_free_disk_gb' and (not isinstance(value, int) or value < 1):
            raise ValueError(f'{name} must be a positive integer')
    result['sandbox'] = sandbox_setting(result)
    validate_agents(result.get('agents', {}))
    return result


def validate_agents(agents):
    if not isinstance(agents, dict) or set(agents) - set(ROLES):
        raise ValueError('agents must name coordinator, builder, verifier or evidence-reviewer')
    for choice in agents.values():
        if not isinstance(choice, dict) or set(choice) - {'agent', 'model'}:
            raise ValueError('each agent choice accepts agent and model')
        if choice.get('agent', 'codex') not in ('codex', 'opencode'):
            raise ValueError('agent must be codex or opencode')
        if 'model' in choice and (not isinstance(choice['model'], str) or not choice['model'].strip()):
            raise ValueError('model must be a nonempty name')


def role_settings(project, role):
    from .projects import read_project
    role = {'build': 'builder', 'verify': 'verifier', 'evidence': 'evidence-reviewer'}.get(role, role)
    machine = config(project.parents[1])
    data = read_project(project)
    validate_agents(data.get('agents', {}))
    choice = dict(machine.get('agents', {}).get(role, {}))
    choice.update(data.get('agents', {}).get(role, {}))
    agent = choice.get('agent', 'codex')
    model = choice.get('model')
    if agent == 'opencode' and not choice.get('model'):
        raise ValueError('opencode requires a model name')
    if agent == 'opencode' and data.get('grants', {}).get('unsandboxed') is not True:
        raise ValueError('Project must grant unsandboxed sessions before using opencode')
    return dict(agent=agent, model=model, sandboxed=agent != 'opencode' and machine['sandbox'] == 'on')


def launcher_settings(cwd, role):
    cwd = Path(cwd).resolve()
    if role == 'coordinator' and cwd.name == 'coordinator':
        project = cwd.parent
    elif cwd.name in ('wt', 'work') and len(cwd.parents) >= 4 and (cwd.parents[1] / 'task.json').is_file():
        project = cwd.parents[3]
    else:
        return None
    if (project / 'project.json').is_file():
        return role_settings(project, role)
    return None


def hold_reason(path, role='build', *, replacing=None, allocating=False):
    from . import hc
    from .projects import read_project, task_paths
    from .runs import events, derive_status
    project = path.parents[1]
    home = project.parents[1]
    limits = config(home)
    own = read_project(project).get('max_tasks_at_once', limits['max_tasks_at_once'])
    if isinstance(own, bool) or not isinstance(own, int) or own < 1:
        raise ValueError('Project max_tasks_at_once must be a positive integer')
    active = []
    tasks = []
    pending = []
    for other in sorted((home / 'projects').glob('*')):
        if not (other / 'project.json').is_file():
            continue
        for item in task_paths(other):
            task = item.parent
            tasks.append(task)
            journals = []
            for marker in task.glob('.setup-*.json'):
                try:
                    journals.append(json.loads(marker.read_text()))
                except FileNotFoundError:
                    pass
            pending.extend(j['metadata'] for j in journals if j.get('launching'))
            if journals and task not in active:
                active.append(task)
            if task not in active and any(e.get('event') == 'session' and e.get('role') != 'coordinator' for e in events(task)) and derive_status(task) not in ('verified', 'for review', 'needs manual verification', 'stopped'):
                active.append(task)
    if path not in active:
        if len(active) >= limits['max_tasks_at_once']:
            return 'max_tasks_at_once'
        if sum(p.parents[1] == project for p in active) >= min(own, limits['max_tasks_at_once']):
            return 'Project max_tasks_at_once'
    if shutil.disk_usage(home).free / (1024 ** 3) < limits['min_free_disk_gb']:
        return 'min_free_disk_gb'
    workers = [e for task in tasks for e in events(task)
               if e.get('event') == 'session' and e.get('role') != 'coordinator']
    if not allocating:
        count = sum(e.get('event') == 'session' and e.get('role') != 'coordinator' for e in events(path))
        if count >= limits['max_sessions_per_task']:
            return 'max_sessions_per_task (worker session budget exhausted)'
    live = sum(bool(e.get('name') != replacing and e.get('address') and hc.get(e['address']).get('state') == 'live') for e in workers)
    recorded = {e.get('name') for e in workers}
    live += sum(e.get('name') not in recorded for e in pending)
    if live >= limits['max_worker_sessions']:
        return 'max_worker_sessions'
    # A finished task's worktree waits on a person, not on this machine's capacity.
    worktrees = sum(1 for task in tasks if task == path or derive_status(task) not in
                    ('verified', 'for review', 'needs manual verification', 'stopped')
                    for wt in task.glob('*/wt') if wt.exists())
    if role != 'evidence' and worktrees >= limits['max_worktrees']:
        return 'max_worktrees'
    return None
