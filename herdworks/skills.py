"""Skills a worker can load, and house rules that name one that is not installed.

Herdworks never installs, fetches or edits a skill. Each agent searches its own folders on
this machine, and the Project repository's ``.agents/skills``, so this module only reports
what is already there.
"""
import re
from pathlib import Path

from . import rules
from .projects import read_project

OPENCODE = "opencode"
CODEX = "Codex"

# A folder is searched by the agents listed for it.
HOME_FOLDERS = (
    ("~/.agents/skills", ".agents/skills", (OPENCODE, CODEX)),
    ("~/.claude/skills", ".claude/skills", (OPENCODE,)),
    ("~/.config/opencode/skills", ".config/opencode/skills", (OPENCODE,)),
    ("~/.codex/skills", ".codex/skills", (CODEX,)),
)

SPAN = re.compile(r"`([^`]+)`")
SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
UNDER_SKILLS = re.compile(r"(?:^|/)skills/([^/]+)")

# A skill folder is named in lowercase with single hyphens, as in .agents/skills/verify-herdworks.
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Plain text names a skill after use, load or follow: "Use the release-notes skill." A single
# lowercase word is ordinary prose too ("Use them rather than ..."), so it counts only when the
# word "skill" follows it; a hyphenated slug is a skill name on its own.
PLAIN_NAME = re.compile(r"(?i:\b(?:use|load|follow)\s+)(?:the\s+)?(" + SKILL_NAME.pattern
                        + r")\s+skill\b")
PLAIN_SLUG = re.compile(r"(?i:\b(?:use|load|follow)\s+)(?:the\s+)?([a-z0-9]+(?:-[a-z0-9]+)+)"
                        r"(?![A-Za-z0-9._/-])")
# A documented file is not a skill: SKILL.md, index.md, README.
FILE_TYPE = re.compile(r"\.[A-Za-z0-9]+$")
DOCUMENTS = frozenset({"readme", "license", "licence", "changelog", "contributing", "notice",
                       "makefile", "dockerfile"})


def show(path):
    """Home-relative folders read better and do not vary with each person's name."""
    path = Path(path)
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def folders(project=None):
    """Every folder a worker's agents search, with the agents that search it."""
    places = [(label, Path.home() / relative, agents)
              for label, relative, agents in HOME_FOLDERS]
    if project is not None:
        repo = Path(read_project(project)["repo"])
        places.append((show(repo) + "/.agents/skills", repo / ".agents/skills",
                       (OPENCODE, CODEX)))
    return places


def inventory(project=None):
    """Each installed skill as a name, its folder and the agents that search that folder."""
    found = []
    for _, folder, agents in folders(project):
        if not folder.is_dir():
            continue
        for item in sorted(folder.iterdir(), key=lambda path: path.name):
            if item.is_dir() and (item / "SKILL.md").is_file():
                found.append({"name": item.name, "folder": item, "agents": agents})
    return found


def is_file_name(name):
    """A documented file such as `SKILL.md` or `README`, not a skill folder."""
    return bool(FILE_TYPE.search(name)) or name.casefold() in DOCUMENTS


def named(line):
    """Skill names a house-rule line refers to: a path under skills/, a backticked name on a
    line that talks about skills, or a plain name after use, load or follow."""
    names = []
    for span in SPAN.findall(line):
        span = span.strip()
        under = UNDER_SKILLS.search(span)
        if under:
            name = under.group(1)
        elif "skill" in line.lower() and SLUG.fullmatch(span):
            name = span
        else:
            continue
        if not is_file_name(name) and "*" not in name and "?" not in name:
            names.append(name)
    for name in PLAIN_NAME.findall(line) + PLAIN_SLUG.findall(line):
        if SKILL_NAME.fullmatch(name) and name not in names:
            names.append(name)
    return names


def in_effect(project=None):
    """The rule files workers see: a Project's copy replaces the machine's for that rule."""
    found = []
    for where, folder in rules.locations(project):
        if where == "built-in":
            continue
        for name in sorted(rules.NAMES):
            path = folder / f"{name}.md"
            if path.is_file() and rules.find(name, project)[1] == path:
                found.append((where, path))
    return found


def missing(project=None):
    """House-rule lines in effect that name a skill no searched folder provides."""
    installed = {skill["name"].casefold() for skill in inventory(project)}
    found = []
    for where, path in in_effect(project):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            for name in named(line):
                if name.casefold() not in installed:
                    found.append({"where": where, "path": path, "line": number,
                                  "name": name})
    return found


def listing(project=None):
    skills = inventory(project)
    name_width = max([4] + [len(skill["name"]) for skill in skills])
    folder_width = max([8] + [len(show(skill["folder"])) for skill in skills])
    lines = ["Skills workers can see:",
             f"{'NAME':{name_width}}  {'FOLDER':{folder_width}}  AGENTS"]
    lines += [f"{skill['name']:{name_width}}  {show(skill['folder']):{folder_width}}  "
              f"{', '.join(skill['agents'])}" for skill in skills]
    if not skills:
        lines.append("(none installed in a searched folder)")
    lines += ["", "Searched folders:"]
    places = folders(project)
    label_width = max([8] + [len(label) for label, _, _ in places])
    for label, folder, agents in places:
        state = "present" if folder.is_dir() else "absent "
        lines.append(f"  {state}  {label:{label_width}}  {', '.join(agents)}")
    if project is None:
        lines.append("  (no Project selected, so its repository's .agents/skills was not searched)")
    lines += ["", "House rules naming a skill that is not installed:"]
    found = missing(project)
    if found:
        lines += [f"  {item['where']:<8}  {show(item['path'])}:{item['line']}  {item['name']}"
                  for item in found]
    else:
        lines.append("  (no house rule names a missing skill)")
    return lines
