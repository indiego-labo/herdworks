import json
import time
from . import hc, impact
from .home import hw_home
from .projects import project_path, read_project, task_paths
from .runs import derive_status, events, read_task
from .talk import coordinator_name, status_word
from .probe import newest_file


def session_line(session, name, role, agent, activity, now):
    changed = session.get('status_ms') or session.get('created_ms')
    activity = max(activity, changed / 1000 if changed else 0)
    quiet = f'{max(0, now - activity) / 60:.1f}m' if activity else 'unknown'
    state = status_word(session) or session.get('state', 'missing')
    return f'{role} agent={agent} {state} quiet={quiet} hc attach {name}'


def tree(project=None, now=None):
    now = time.time() if now is None else now
    projects = [project_path(project)] if project else sorted(
        p.parent for p in (hw_home() / 'projects').glob('*/project.json'))
    for path in projects:
        read_project(path)
        yield f'Project {path.name}'
        metadata = path / 'coordinator.json'
        data = json.loads(metadata.read_text()) if metadata.exists() else {}
        name = coordinator_name(path)
        current = hc.get(data.get('address', name))
        yield '|-- ' + session_line(current, name, 'coordinator', data.get('agent', 'unknown'),
                                    newest_file(path / 'coordinator'), now)
        for metadata in task_paths(path):
            task = metadata.parent
            if any(e.get('event') == 'closed' for e in events(task)):
                continue
            state = derive_status(task)
            if state == 'stopped':
                continue
            yield f'|-- {task.name} {state}' + impact.label(read_task(task).get('impact'))
            for event in events(task):
                if event.get('event') != 'session' or event.get('role') == 'coordinator':
                    continue
                current = hc.get(event['address'])
                if current.get('state') == 'live':
                    yield '|   |-- ' + session_line(current, event['name'], event['role'],
                                                    event.get('agent', 'unknown'),
                                                    newest_file(task / event['folder']), now)
