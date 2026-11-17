"""House rules: plain Markdown that every worker brief includes.

Each rule is looked up in the Project, then the machine, then the built-in defaults, so a person
or an agent can change how work is done by editing a copy, and updates never overwrite it.
"""
import shutil
from pathlib import Path

from .home import hw_home
from .runs import ROOT

NAMES = ('all', 'build', 'verify', 'review')
FOR_ROLE = {'build': ('all', 'build'), 'fix': ('all', 'build'), 'verify': ('all', 'verify'),
            'evidence': ('all', 'review')}


def locations(project=None):
    places = []
    if project is not None:
        places.append(('Project', Path(project) / 'rules'))
    places.append(('machine', hw_home() / 'rules'))
    places.append(('built-in', ROOT / 'rules'))
    return places


def find(name, project=None):
    if name not in NAMES:
        raise ValueError(f'rule must be one of {", ".join(NAMES)}')
    for where, folder in locations(project):
        path = folder / f'{name}.md'
        if path.is_file():
            return where, path
    raise ValueError(f'built-in rule {name} is missing from {ROOT / "rules"}')


def text(role, project=None):
    parts = []
    for name in FOR_ROLE[role]:
        _, path = find(name, project)
        parts.append(f'--- house rules: {name} ({path}) ---\n{path.read_text().strip()}\n')
    return '\n'.join(parts)


def listing(project=None):
    return [f'{name:7} {where:9} {path}' for name in NAMES for where, path in [find(name, project)]]


def copy(name, project=None):
    """Copies the rule now in effect one level down, so edits start from what workers see today."""
    where, source = find(name, project)
    folder = (Path(project) / 'rules') if project is not None else hw_home() / 'rules'
    target = folder / f'{name}.md'
    if target.exists():
        raise ValueError(f'{target} already exists; edit it directly')
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target
