import datetime
import json
import math
import re
import subprocess
import time
import uuid
from .home import hw_home
from .projects import project_path, read_project, task_paths
from .runs import git, locked, read_task
from .pr import recorded_pr, repository_identity
from .talk import say


def folder():
    return hw_home() / 'automations'


def path_for(name):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,47}', name):
        raise ValueError('automation name must be 1 to 48 lowercase letters, digits, hyphens or underscores')
    return folder() / f'{name}.json'


def write(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def load(name):
    return json.loads(path_for(name).read_text())


def add(name, project, owner, trigger, instructions, interval=60, daily_cap=1, authors=(), now=None):
    now = time.time() if now is None else now
    path = path_for(name)
    read_project(project_path(project))
    if trigger not in ('schedule', 'github-issue'):
        raise ValueError('unknown trigger')
    if not owner.strip() or not instructions.strip():
        raise ValueError('owner and instructions are required')
    if not math.isfinite(interval) or interval < 60:
        raise ValueError('interval must be at least 60 seconds')
    if isinstance(daily_cap, bool) or not isinstance(daily_cap, int) or daily_cap < 1:
        raise ValueError('daily cap must be a positive integer')
    if trigger == 'github-issue' and (not authors or any(not re.fullmatch(r'[A-Za-z0-9-]+', a) for a in authors)):
        raise ValueError('github-issue requires named authors')
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked(path.parent):
        if path.exists():
            raise ValueError('automation already exists')
        data = dict(name=name, enabled=True, owner=owner, project=project, trigger=trigger,
                    instructions=instructions, interval=interval, daily_cap=daily_cap,
                    authors=list(authors), created_at=now, last_tick=now, next_run=now + interval,
                    last_run=None, last_result='never', failures=0, deliveries=[])
        write(path, data)
    return data


def switch(name, enabled, now=None):
    with locked(folder()):
        data = load(name)
        data['enabled'] = enabled
        if enabled:
            now = time.time() if now is None else now
            data.update(failures=0, last_tick=now, next_run=now + data['interval'])
        write(path_for(name), data)
    return data


def history(name=None):
    path = folder() / 'runs.jsonl'
    entries = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [e for e in entries if name is None or e['name'] == name]


def listing():
    for path in sorted(folder().glob('*.json')):
        data = load(path.stem)
        yield (f"{data['name']} {'on' if data['enabled'] else 'off'} owner={data['owner']} "
               f"Project={data['project']} {data['trigger']} last={stamp(data['last_run'])} "
               f"next={stamp(data['next_run']) if data['enabled'] else '-'} {data['last_result']}")


def stamp(value):
    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat() if value is not None else '-'


def gh(project, *args):
    config = read_project(project)
    remote = git(config['repo'], 'remote', 'get-url', config.get('remote', 'origin'))
    repository = repository_identity(remote)
    if not repository.startswith(('github.com/', 'github.invalid/')):
        raise ValueError('github-issue requires a GitHub repository remote')
    result = subprocess.run([config.get('gh', 'gh'), *map(str, args), '--repo', repository],
                            cwd=config['repo'], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('gh failed: ' + result.stderr.strip())
    return result.stdout


def candidates(data):
    if data['trigger'] == 'schedule':
        return [dict(source='schedule', text=data['instructions'])]
    project = project_path(data['project'])
    issues = []
    for author in data['authors']:
        issues.extend(json.loads(gh(project, 'issue', 'list', '--state', 'open', '--label', 'herdworks',
                                    '--author', author, '--limit', '100',
                                    '--json', 'number,title,body,url,author,labels,state')))
    taken = {d['source'] for path in folder().glob('*.json')
             for other in [json.loads(path.read_text())] if other['project'] == data['project']
             for d in other['deliveries']}
    result = []
    for issue in issues:
        number = issue['number']
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ValueError('issue number must be positive')
        source = f'issue:{number}'
        if (source in taken or issue['author']['login'] not in data['authors']
                or issue.get('state', '').upper() != 'OPEN'
                or 'herdworks' not in [label['name'] for label in issue['labels']]):
            continue
        result.append(dict(source=source, issue=number,
                           text=f"{data['instructions']}\n\nGitHub issue #{number}: {issue['title']}\n"
                                f"{issue['url']}\n\n{issue['body']}"))
        taken.add(source)
    return result


def preview(name):
    data = load(name)
    return [item['text'] for item in candidates(data)]


def problem(data, reason):
    project = project_path(data['project'])
    with locked(project):
        outbox = project / 'coordinator/outbox'
        number = max((int(p.stem) for p in outbox.glob('*.md') if p.stem.isdecimal()), default=0) + 1
        target = outbox / f'{number:06}.md'
        temporary = outbox / f'.{number:06}.tmp'
        temporary.write_text(f"PROBLEM\nAutomation: {data['name']}\n{reason}\nSwitched off; inspect automation history before switching on.\n")
        temporary.replace(target)
    data.update(enabled=False, last_result='PROBLEM: ' + reason)


def deliver(data, item, path):
    project = project_path(data['project'])
    if 'message' not in item:
        number, _ = say(project, item['text'], delivery_key=item['key'])
        item['message'] = number
        write(path, data)
    if item.get('issue') and not item.get('labelled'):
        gh(project, 'issue', 'edit', item['issue'], '--add-label', 'herdworks-taken', '--remove-label', 'herdworks')
        item['labelled'] = True
    item['done'] = True
    write(path, data)


def comments(data, path):
    project = project_path(data['project'])
    for item in data['deliveries']:
        if not item.get('issue') or 'message' not in item or item.get('commented'):
            continue
        for metadata in task_paths(project):
            task = metadata.parent
            if read_task(task).get('message') != item['message']:
                continue
            from .runs import derive_status
            pr = recorded_pr(task)
            if pr and derive_status(task) == 'for review':
                marker = f"<!-- herdworks:{data['name']}:{item['key']} -->"
                existing = json.loads(gh(project, 'issue', 'view', item['issue'], '--json', 'comments'))
                if not any(marker in c['body'] for c in existing['comments']):
                    gh(project, 'issue', 'comment', item['issue'], '--body', f"Draft pull request: {pr['url']}\n\n{marker}")
                item['commented'] = pr['url']
                write(path, data)


def tick(now=None):
    now = time.time() if now is None else now
    if not math.isfinite(now) or now < 0:
        raise ValueError('clock must be a finite nonnegative Unix timestamp')
    folder().mkdir(parents=True, exist_ok=True)
    results = []
    with locked(folder()):
        for path in sorted(folder().glob('*.json')):
            data = load(path.stem)
            if not data['enabled']:
                continue
            if now < data['last_tick']:
                raise ValueError('clock moved backwards')
            if now < data['next_run']:
                continue
            result = 'idle'
            try:
                if now - data['last_tick'] > 2 * data['interval']:
                    problem(data, 'idle past twice its interval')
                    result = data['last_result']
                else:
                    comments(data, path)
                    day = stamp(now)[:10]
                    recovered = False
                    for item in data['deliveries']:
                        if not item.get('done'):
                            recovered = True
                            if 'message' not in item and item['day'] != day:
                                if sum(d['day'] == day for d in data['deliveries']) >= data['daily_cap']:
                                    continue
                                item['day'] = day
                                write(path, data)
                            deliver(data, item, path)
                    used = sum(item['day'] == day for item in data['deliveries'])
                    available = data['daily_cap'] - used
                    choices = candidates(data) if available > 0 and not (recovered and data['trigger'] == 'schedule') else []
                    result = 'capped' if available <= 0 else 'idle'
                    for item in choices[:max(0, available)]:
                        item.update(key=uuid.uuid4().hex, day=day, at=now)
                        data['deliveries'].append(item)
                        write(path, data)
                        deliver(data, item, path)
                        result = 'sent'
                    data['failures'] = 0
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
                data['failures'] += 1
                result = f'ERROR: {error}'
                if data['failures'] >= 3:
                    problem(data, 'three consecutive failures: ' + str(error))
                    result = data['last_result']
            data.update(last_tick=now, last_run=now, next_run=now + data['interval'], last_result=result)
            write(path, data)
            entry = dict(name=data['name'], at=now, result=result)
            with (folder() / 'runs.jsonl').open('a') as stream:
                stream.write(json.dumps(entry) + '\n')
            results.append(entry)
    return results
