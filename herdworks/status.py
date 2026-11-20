import json
import time
from . import hc, monitor
from .home import hw_home
from .projects import project_path, read_project, task_paths
from .runs import events
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
            current = monitor.record(task, now)
            if current['driver'] == 'run':
                # `hw run` keeps the task's state itself: blocked on a question, a budget or a stop, it waits
                # on the owner, so it is shown with the reason and the command that continues it.
                yield '|-- ' + monitor.headline(current)
                for name, text in (('result' if current['state'] == 'done' else 'reason', current['reason']),
                                   ('next', current['next_step'])):
                    if text:
                        yield f'|   |-- {name}: {text}'
            elif current['status'] == 'stopped':
                continue
            else:
                yield (f"|-- {task.name} {current['status']} stage={current['stage']} "
                       f"elapsed={monitor.clock(current['elapsed_seconds'])} {monitor.spent(current['tokens'])}")
            for event in events(task):
                if event.get('event') != 'session' or event.get('role') == 'coordinator':
                    continue
                current = hc.get(event['address'])
                if current.get('state') == 'live':
                    yield '|   |-- ' + session_line(current, event['name'], event['role'],
                                                    event.get('agent', 'unknown'),
                                                    newest_file(task / event['folder']), now)
