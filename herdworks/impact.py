import json
from .runs import events, locked, read_task


LEVELS = ('green', 'yellow', 'red', 'unknown')


def proposal(level, reason):
    if level is None and reason is None:
        return None
    reason = reason.strip() if reason is not None else ''
    if level not in LEVELS or not reason or not reason.isprintable():
        raise ValueError('impact requires a level and a nonempty, single-line reason')
    return dict(level=level, reason=reason)


def update(path, level, reason, *, corrected=False):
    impact = proposal(level, reason)
    with locked(path):
        data = read_task(path)
        if any(e.get('event') == 'closed' for e in events(path)):
            raise ValueError('task is closed')
        if corrected:
            impact['corrected'] = True
        elif data.get('impact', {}).get('corrected'):
            raise ValueError('owner correction is in effect; ask the owner to update it')
        data['impact'] = impact
        temporary = path / '.task-impact.tmp'
        temporary.write_text(json.dumps(data, indent=2) + '\n')
        temporary.replace(path / 'task.json')
    return impact


def label(impact):
    if impact is None:
        return ''
    source = 'owner correction' if impact.get('corrected') else 'proposed'
    return f" [impact={impact['level']} ({source}) {impact['reason']}]"
