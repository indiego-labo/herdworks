"""`hw setup`: get a new machine from installed to a first Project, one plain question at a time.

Every step checks first and only acts when something is missing, so it is safe to run again.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .home import hw_home
from .limits import ROLES, config
from .projects import add_project, grant_project, project_path

PREFERRED_MODELS = ('deepseek/deepseek-flash', 'opencode/deepseek-v4.1-flash-free', 'opencode/big-pickle')


def tool(name):
    found = shutil.which(name)
    if not found and name == 'opencode':
        candidate = Path.home() / '.opencode/bin/opencode'
        found = str(candidate) if os.access(candidate, os.X_OK) else None
    return found


def run(*args, interactive=False):
    if interactive:
        return subprocess.run(args).returncode
    return subprocess.run(args, capture_output=True, text=True)


def say(text=''):
    print(text, flush=True)


def done(text):
    say(f'  \033[32m✓\033[0m {text}')


def todo(text):
    say(f'  \033[33m•\033[0m {text}')


def ask(question, default=None):
    suffix = f' [{default}]' if default else ''
    try:
        answer = input(f'  {question}{suffix}: ').strip()
    except EOFError:
        answer = ''
    return answer or (default or '')


def heading(text):
    say(f'\n\033[1m{text}\033[0m')


def check_tools():
    heading('Tools')
    missing = [name for name in ('git', 'hc', 'opencode', 'gh') if not tool(name)]
    for name in ('git', 'hc', 'opencode', 'gh'):
        if name not in missing:
            done(f'{name}: {tool(name)}')
    if 'opencode' not in missing:
        version = run(tool('opencode'), '--version').stdout.strip()
        major = re.search(r'(\d+)\.', version)
        if not major or int(major[1]) < 2:
            todo(f'opencode {version or "(unknown version)"} is too old; Herdworks needs opencode 2')
            missing.append('opencode 2')
    if missing:
        todo('missing: ' + ', '.join(missing))
        say('  Run the installer again:\n'
            '    curl -fsSL https://raw.githubusercontent.com/indiego-labo/herdworks/main/install.sh | bash')
        return False
    return True


def check_core(fix):
    heading('herdr core (keeps agents running)')
    # `hc server status` starts the core when it is not running.
    status = run('hc', 'server', 'status')
    try:
        data = json.loads(status.stdout)
    except ValueError:
        todo('herdr core did not answer: ' + (status.stderr or status.stdout).strip())
        return False
    done(f"running, version {data.get('version')}")
    if data.get('keeps_running_after_logout') is False:
        todo('agents stop when you log out of this machine. To keep them running, run once:\n'
             f'      sudo loginctl enable-linger {os.environ.get("USER", "$USER")}')
    return True


def check_git_identity(fix):
    heading('Git name and email (used on the agents\' commits)')
    ok = True
    for key, question in (('user.name', 'Your name'), ('user.email', 'Your email')):
        value = run('git', 'config', '--global', key).stdout.strip()
        if value:
            done(f'{key}: {value}')
            continue
        if not fix:
            todo(f'{key} is not set')
            ok = False
            continue
        value = ask(question)
        if not value:
            todo(f'{key} skipped')
            ok = False
            continue
        run('git', 'config', '--global', key, value)
        done(f'{key}: {value}')
    return ok


def check_github(fix):
    heading('GitHub (to open pull requests)')
    if run('gh', 'auth', 'status').returncode == 0:
        done('signed in')
    elif not fix:
        todo('not signed in')
        return False
    elif not sys.stdin.isatty():
        todo('not signed in; GitHub sign-in needs a terminal, so run hw setup in one')
        return False
    else:
        say('  A code will appear. Open the link, sign in to GitHub and paste the code.')
        if run('gh', 'auth', 'login', '--web', '--git-protocol', 'https', interactive=True):
            todo('GitHub sign-in did not finish; run hw setup again')
            return False
        done('signed in')
    if fix:
        # Lets git push over HTTPS with the same sign-in; no SSH keys needed.
        run('gh', 'auth', 'setup-git')
    return True


def models():
    listed = run(tool('opencode'), 'models')
    return [line.strip() for line in listed.stdout.splitlines() if re.fullmatch(r'[\w.-]+/[\w.:/-]+', line.strip())]


def check_model(fix):
    heading('Model (what the agents think with)')
    current = config().get('agents', {})
    chosen = {current.get(role, {}).get('model') for role in ROLES if current.get(role, {}).get('agent') == 'opencode'}
    if len(chosen) == 1 and None not in chosen and set(current) == set(ROLES):
        model = chosen.pop()
        if model in models():
            done(f'all roles use opencode with {model}')
            return True
        todo(f'{model} is set but opencode does not list it; check your provider sign-in')
    if not fix:
        todo('no model chosen')
        return False
    available = models()
    if not any(not name.startswith('opencode/') for name in available):
        say('  Free models need no account but run out quickly, often within one task.')
        say('  For real use, sign in to a provider such as DeepSeek (cents per task).')
        if ask('Sign in to a model provider now? (y/N)', 'n').lower().startswith('y'):
            run(tool('opencode'), 'auth', 'login', interactive=True)
            available = models()
    if not available:
        todo('opencode lists no models; run: opencode auth login, then hw setup again')
        return False
    default = next((name for name in PREFERRED_MODELS if name in available), available[0])
    say(f'  {len(available)} models available, for example: ' + ', '.join(available[:6]))
    if default.startswith('opencode/') and default.endswith('-free'):
        say('  Free models have a small usage limit. How they handle your code: https://opencode.ai/docs/zen')
    model = ask('Model to use', default)
    if model not in available:
        todo(f'{model} is not in opencode\'s list; run hw setup again')
        return False
    path = hw_home() / 'config.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else {}
    data['agents'] = {role: {'agent': 'opencode', 'model': model} for role in ROLES}
    path.write_text(json.dumps(data, indent=2) + '\n')
    done(f'all roles use opencode with {model} ({path})')
    return True


def project_name(repository):
    name = re.sub(r'[^a-z0-9_-]', '-', repository.split('/')[-1].lower().removesuffix('.git')).strip('-_')
    return name[:12].rstrip('-_') or 'project'


def existing_projects():
    folder = hw_home() / 'projects'
    return sorted(p.name for p in folder.iterdir() if (p / 'project.json').exists()) if folder.is_dir() else []


def check_project(fix):
    heading('Your first Project (one GitHub repository)')
    projects = existing_projects()
    if projects:
        done('Projects: ' + ', '.join(projects))
        return projects[0]
    if not fix:
        todo('no Project yet')
        return None
    repository = ask('GitHub repository, as owner/name (Enter to skip for now)')
    if not repository:
        todo('skipped; run hw setup again to add one')
        return None
    repository = re.sub(r'^(https://github\.com/|git@github\.com:)', '', repository).removesuffix('.git').strip('/')
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
        todo(f'{repository} is not owner/name')
        return None
    info = run('gh', 'repo', 'view', repository, '--json', 'defaultBranchRef')
    if info.returncode:
        todo(f'GitHub cannot find {repository} with your sign-in: ' + info.stderr.strip())
        return None
    base = json.loads(info.stdout)['defaultBranchRef']['name']
    name = project_name(repository)
    folder = Path(ask('Where to keep its code', str(Path.home() / 'code' / repository.split('/')[-1]))).expanduser()
    if not folder.exists():
        folder.parent.mkdir(parents=True, exist_ok=True)
        cloned = run('gh', 'repo', 'clone', repository, str(folder), '--', '--quiet')
        if cloned.returncode:
            todo('clone failed: ' + cloned.stderr.strip())
            return None
        done(f'cloned to {folder}')
    else:
        done(f'using {folder}')
    if project_path(name).exists():
        name = ask('A Project with that name exists; another name (12 letters at most)')
    add_project(name, folder, base)
    grant_project(project_path(name), push=True, draft_pr=True, unsandboxed=True)
    done(f'Project {name}: tasks branch from {base} and end as draft pull requests on {repository}')
    return name


def check_skill(fix):
    heading('Claude Code skill (lets Claude hand tasks to your Projects)')
    from .runs import ROOT
    source = ROOT / 'skills/herdworks'
    folder = Path.home() / '.claude/skills'
    target = folder / 'herdworks'
    if target.resolve() == source.resolve():
        done(f'installed: {target}')
        return True
    if target.exists() or target.is_symlink():
        done(f'{target} exists and is yours; left as it is')
        return True
    if not (Path.home() / '.claude').is_dir():
        done('Claude Code not found; skipped (run hw setup again after installing it)')
        return True
    if not fix:
        todo('not installed')
        return True
    folder.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source)
    done(f'installed: {target} (updates with Herdworks)')
    return True


def setup(check_only=False):
    fix = not check_only
    say('\033[1mHerdworks setup\033[0m' + (' (checking only)' if check_only else ''))
    if not check_tools():
        return 1
    results = [check_core(fix), check_git_identity(fix), check_github(fix), check_model(fix)]
    check_skill(fix)
    project = check_project(fix) if all(results) else None
    heading('Next')
    if not all(results) or not project:
        say('  Some steps are not done yet. Run hw setup again when ready.')
        return 1
    say(f'  Give it a task:        hw say {project} "Fix the typo in the README. Done when it reads correctly."')
    say(f'  Read its replies:      hw read {project}')
    say(f'  See its tasks:         hw tasks {project}')
    say('  Each task ends as a draft pull request for you to review and merge.')
    return 0
