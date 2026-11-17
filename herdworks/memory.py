import hashlib
import json
import shlex
import re
import time
import uuid
from .runs import locked, read_task


def sync(project):
    folder = project / 'memory'
    folder.mkdir(exist_ok=True)
    with locked(folder):
        index = folder / 'index.json'
        entries = json.loads(index.read_text()) if index.exists() else {}
        for file in sorted(folder.glob('*.md')):
            if file.name == 'MEMORY.md':
                continue
            if file.is_symlink() or file.stat().st_size > 16384:
                raise ValueError('memory entries must be regular files of at most 16 KiB')
            content = file.read_text()
            digest = hashlib.sha256(content.encode()).hexdigest()
            previous = entries.get(file.name, {})
            if previous.get('sha256') != digest:
                declared = re.search(r'^Task: ([A-Z]{2}-[1-9][0-9]*)$', content, re.MULTILINE)
                if declared is None or not (project / 'tasks' / declared[1] / 'task.json').is_file():
                    raise ValueError('direct memory entries require Task: TASK_ID for an existing task')
                entries[file.name] = dict(added_at=time.time(), task=declared[1],
                                          sha256=digest, content=content)
        entries = {name: entry for name, entry in entries.items() if (folder / name).is_file()}
        temporary = folder / '.index.tmp'
        temporary.write_text(json.dumps(entries, indent=2) + '\n')
        temporary.replace(index)
        (folder / 'MEMORY.md').write_text(render(entries))
        return entries


def render(entries):
    return '# Project memory\n\n' + ''.join(f'## {name}\n{entry["content"]}\n\n' for name, entry in sorted(entries.items()))


def add(project, task, title, text):
    path = project / 'tasks' / task
    data = read_task(path)
    if data['id'] != task or not title.strip() or not text.strip():
        raise ValueError('memory needs a task, title and text')
    folder = project / 'memory'
    name = f'{uuid.uuid4().hex}.md'
    content = f'# {title}\nTask: {task}\n\n{text}\n'
    if len(content.encode()) > 16384:
        raise ValueError('memory entries must be at most 16 KiB')
    temporary = folder / f'.{name}.tmp'
    temporary.write_text(content)
    temporary.replace(folder / name)
    sync(project)
    return folder / name


def read(project, task=None, role='build'):
    if task is not None and role in ('verify', 'evidence'):
        data = read_task(project / 'tasks' / task)
        entries = {name: entry for name, entry in data.get('memory_before', {}).items()
                   if entry['task'] != task and entry['added_at'] < data['created_at']}
    else:
        entries = sync(project)
    return render(entries)


def brief(path, role):
    project = path.parents[1]
    from .runs import ROOT
    command = f'env HW_HOME={shlex.quote(str(project.parents[1]))} {shlex.quote(str(ROOT / "bin/hw"))}'
    context = f'\nProject: {project.name}\nTask: {path.name}\n'
    if role == 'build':
        context += f'Memory folder: {project / "memory"}\nMemory command: {command} memory add {project.name} --task {path.name} --title TITLE --text TEXT\n'
    return context + read(project, path.name, role)
