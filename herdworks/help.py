"""`hw help`: the same guides for people and for agents, printed as Markdown."""
import json
from .home import hw_home
from .runs import ROOT

TOPICS = {
    'agent': ROOT / 'skills/herdworks/SKILL.md',
    'models': ROOT / 'help/models.md',
    'rules': ROOT / 'help/rules.md',
    'server': ROOT / 'docs/server.md',
    'automations': ROOT / 'docs/automations.md',
    'reference': ROOT / 'docs/reference.md',
}


def strip_front_matter(text):
    if text.startswith('---\n'):
        end = text.find('\n---\n', 4)
        if end != -1:
            return text[end + 5:].lstrip('\n')
    return text


def chosen_agents():
    """True when config.json names agents; a file with other settings alone has no chosen model."""
    path = hw_home() / 'config.json'
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    agents = data.get('agents') if isinstance(data, dict) else None
    return isinstance(agents, dict) and bool(agents)


def next_step():
    """One line on what to do next on this machine, read from files only."""
    home = hw_home()
    projects = sorted(p.name for p in (home / 'projects').glob('*') if (p / 'project.json').is_file())
    if projects:
        return (f'Your Projects: {", ".join(projects)}. '
                f'Give one a task with `hw run -p {projects[0]} "..."`.')
    if not chosen_agents():
        return 'Next: run `hw setup` to choose a model and add your first Project.'
    return 'Next: run `hw setup` to add your first Project.'


def text(topic=None):
    if topic is None:
        return (ROOT / 'help/overview.md').read_text().rstrip() + '\n\n' + next_step() + '\n'
    if topic not in TOPICS:
        raise ValueError(f'no help on {topic}; topics: {", ".join(TOPICS)}')
    return strip_front_matter(TOPICS[topic].read_text())
