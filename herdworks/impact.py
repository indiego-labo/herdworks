import json
from .runs import events, locked, read_task


LEVELS = ('green', 'yellow', 'red', 'unknown')
REPRODUCTION = ('reproduced', 'unreproduced', 'unknown', 'not-applicable')
CONFIDENCE = ('high', 'medium', 'low', 'unknown')


def proposal(level, reason, *, reproduction=None, confidence=None):
    if level is None and reason is None and reproduction is None and confidence is None:
        return None
    reason = reason.strip() if reason is not None else ''
    if level not in LEVELS or not reason or not reason.isprintable():
        raise ValueError('impact requires a level and a nonempty, single-line reason')
    result = dict(level=level, reason=reason)
    for field, value, choices in (('reproduction', reproduction, REPRODUCTION),
                                  ('confidence', confidence, CONFIDENCE)):
        if value is not None:
            if value not in choices:
                raise ValueError(f'{field} must be one of {", ".join(choices)}')
            result[field] = value
    return result


def update(path, level, reason, *, corrected=False, reproduction=None, confidence=None):
    impact = proposal(level, reason, reproduction=reproduction, confidence=confidence)
    with locked(path):
        data = read_task(path)
        if any(e.get('event') == 'closed' for e in events(path)):
            raise ValueError('task is closed')
        previous = data.get('impact', {})
        if corrected:
            impact['corrected'] = True
        elif previous.get('corrected'):
            raise ValueError('owner correction is in effect; ask the owner to update it')
        impact = data['impact'] = {**previous, **impact}
        temporary = path / '.task-impact.tmp'
        temporary.write_text(json.dumps(data, indent=2) + '\n')
        temporary.replace(path / 'task.json')
    return impact


def label(impact):
    if impact is None:
        return ''
    source = 'owner correction' if impact.get('corrected') else 'proposed'
    details = ''.join(f' {field}={impact[field]}' for field in ('reproduction', 'confidence')
                      if field in impact)
    return f" [impact={impact['level']} ({source}) {impact['reason']}{details}]"
