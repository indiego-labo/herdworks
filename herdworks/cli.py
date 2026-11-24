import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
from . import hc
from .gate import check_gate, gate, reap
from .probe import format_fact, probe
from .runs import ROOT, derive_status, escalation, locked, read_task, first_line, events
from .projects import add_project, add_github_project, project_path, task_path, task_paths, new_task, read_project
from .talk import up, say, read, latest, wait
from .spawn import spawn
from .pickup import stop, close, tidy
from .pr import open_pr, recorded_pr
from .projects import grant_project
from .limits import config, hold_reason
from . import memory, automations
from .status import tree


def install(root=ROOT, destination=None):
    destination = destination or hc.template_dir()
    destination.mkdir(parents=True, exist_ok=True)
    manifest = destination / ".hw-install.json"
    with locked(destination):
        owned = json.loads(manifest.read_text()) if manifest.exists() else {}
        rendered = {}
        for source in sorted((root / "templates").glob("*.md")):
            target = destination / source.name
            if target.exists():
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                if owned.get(source.name) != digest:
                    raise ValueError(f"refusing to overwrite template not written by install: {target}")
            rendered[target] = source.read_text().replace("{{HW}}", shlex.quote(str(root / "bin/hw"))).replace(
                "{{CODEX}}", shlex.quote(str(root / "bin/hw-codex"))).replace(
                "{{OPENCODE}}", shlex.quote(str(root / "bin/hw-opencode")))
        for target, content in rendered.items():
            target.write_text(content)
            owned[target.name] = hashlib.sha256(content.encode()).hexdigest()
        manifest.write_text(json.dumps(owned, indent=2) + "\n")
    return list(rendered)


def task_lines(project):
    read_project(project)
    for item in task_paths(project):
        path = item.parent
        if any(e.get('event') == 'closed' for e in events(path)):
            continue
        data = read_task(path)
        observed = probe(path)
        facts = [f for f in observed if f["state"] == "live"]
        summary = " ".join(f"{f['name']}({f['status']},quiet {f['quiet_minutes']:.0f}m of {f['stuck_after_minutes']:g}m{',STALLED' if f.get('stalled') else ''})" for f in facts)
        status = derive_status(path)
        pr = recorded_pr(path) if status in ('for review', 'needs manual verification') else None
        commit = pr['commit'] if pr else check_gate(path)[1] if status == 'verified' else ''
        address = pr['url'] if pr else ''
        reason = hold_reason(path, allocating=True) if status == 'queued' else None
        held = f'held by {reason}' if reason else ''
        unsandboxed = 'unsandboxed' if any(e.get('sandboxed') is False for e in events(path)) or ((project / 'coordinator.json').exists() and json.loads((project / 'coordinator.json').read_text()).get('sandboxed') is False) else ''
        roles = set(data.get("roles", {})) | {f["role"] for f in observed if f["launch_source"] == "override"}
        overrides = "overrides=" + ",".join(sorted(roles)) if roles else ""
        yield f"{data['id']} {status} {commit} {address} {first_line(path / 'brief.md')} {summary} {overrides} {held} {unsandboxed}".rstrip()


def authorize(project, memory_task=None, memory_command=False):
    caller = os.environ.get("HW_CALLER_TERMINAL")
    if caller is None:
        return
    session = hc.get(caller) if caller else {}
    labels = session.get("labels", {})
    if (memory_command and project and session.get('state') == 'live'
            and labels.get('role') == 'build'
            and labels.get('hw', '').startswith(f'{project}:')
            and (memory_task is None or labels.get('hw') == f'{project}:{memory_task}')):
        task_id = labels['hw'].split(':', 1)[1]
        cwd = Path(session.get('cwd', ''))
        if (cwd.name == 'wt' and cwd.parent.name.startswith('build-')
                and cwd.parent.parent == task_path(project, task_id)):
            return
    if (not project or session.get("state") != "live"
            or labels.get("role") != "coordinator"
            or labels.get("hw") != f"project:{project}"
            or session.get("cwd") != str(project_path(project) / "coordinator")):
        raise ValueError("caller is not the coordinator of this Project")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Message a Project and follow its tasks. Start with: hw help")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install")
    sub.add_parser("config")
    command = sub.add_parser("help", help="guides for people and agents: hw help [agent|models|rules|server|automations|reference]")
    command.add_argument("topic", nargs="?")
    command = sub.add_parser("rules", help="show or copy the house rules workers follow")
    command.add_argument("action", nargs="?", choices=["list", "copy"], default="list")
    command.add_argument("name", nargs="?", choices=["all", "build", "verify", "review"])
    command.add_argument("--project", help="a Project's own rules instead of this machine's")
    command = sub.add_parser("skills",
                             help="skills workers can load, and house rules that name a missing one")
    command.add_argument("--project", help="also search this Project's repository and its rules for skills")
    command = sub.add_parser("setup", help="sign in and add a first Project; safe to run again")
    command.add_argument("--check", action="store_true", help="only report what is missing")
    command = sub.add_parser('status')
    command.add_argument('project', nargs='?')
    command = sub.add_parser('automations')
    command.add_argument('action', nargs='?', choices=['tick'])
    command.add_argument('--at', type=float, help='Unix timestamp for a controlled tick')
    command = sub.add_parser('automation')
    actions = command.add_subparsers(dest='action', required=True)
    command = actions.add_parser('add')
    command.add_argument('name')
    command.add_argument('--project', required=True)
    command.add_argument('--owner', required=True)
    command.add_argument('--trigger', required=True, choices=['schedule', 'github-issue'])
    command.add_argument('--instructions', required=True)
    command.add_argument('--interval', type=float, default=60, help='seconds, at least 60')
    command.add_argument('--daily-cap', type=int, default=1)
    command.add_argument('--author', action='append', default=[])
    for action in ('on', 'off', 'test', 'history'):
        command = actions.add_parser(action)
        if action == 'history':
            command.add_argument('name', nargs='?')
        else:
            command.add_argument('name')
    command = sub.add_parser('memory')
    actions = command.add_subparsers(dest='action', required=True)
    for action in ('add', 'read'):
        command = actions.add_parser(action)
        command.add_argument('project')
        command.add_argument('--task', required=action == 'add')
        if action == 'add':
            command.add_argument('--title', required=True)
            command.add_argument('--text', required=True)
        else:
            command.add_argument('--role', choices=['build', 'verify', 'evidence'], default='build')
    command = sub.add_parser("project")
    actions = command.add_subparsers(dest="action", required=True)
    command = actions.add_parser("add")
    command.add_argument("project")
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", type=Path, help="a clean local checkout")
    source.add_argument("--github", help="owner/repo; clones it under HW_HOME with gh's sign-in")
    command.add_argument("--base", default=None, help="base branch (default: main, or GitHub's default)")
    command.add_argument("--prefix")
    command = actions.add_parser("grant")
    command.add_argument("project")
    command.add_argument("--push", action=argparse.BooleanOptionalAction, default=None)
    command.add_argument("--draft-pr", action=argparse.BooleanOptionalAction, default=None)
    command.add_argument("--unsandboxed", action=argparse.BooleanOptionalAction, default=None)
    command.add_argument("--remote")
    command.add_argument("--gh", help="gh executable (default: gh from PATH)")
    command = sub.add_parser("up")
    command.add_argument("project")
    command = sub.add_parser("say")
    command.add_argument("project")
    command.add_argument("text", nargs="?")
    command.add_argument("--file", type=Path)
    command.add_argument("--number", type=int, help="redeliver an existing message number")
    command.add_argument("--base", help="start this task from another branch instead of the Project base")
    command = sub.add_parser("read")
    command.add_argument("project")
    command.add_argument("--since", type=int, default=0)
    command.add_argument("--latest", action="store_true", help="print only the newest reply number (0 if none)")
    command = sub.add_parser("wait", help="block until the coordinator's next reply, print it and exit")
    command.add_argument("project")
    command.add_argument("--since", type=int, help="wait for replies above this number (default: the newest now)")
    command.add_argument("--timeout", type=float, help="seconds to wait; exit 2 if nothing arrives")
    command = sub.add_parser("tasks")
    command.add_argument("project")
    command = sub.add_parser("tidy", help="reclaim finished workers' clean worktrees and close tasks with ended pull requests")
    command.add_argument("project")
    command = sub.add_parser("task")
    actions = command.add_subparsers(dest="action", required=True)
    command = actions.add_parser("new")
    command.add_argument("project")
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--brief", type=Path)
    source.add_argument("--message", type=int)
    command.add_argument("--role", nargs=2, action="append", default=[])
    command.add_argument("--stuck-after", type=float)
    command.add_argument("--base", help="branch to start from instead of the Project base")
    command.add_argument("--kind", choices=["build", "spike"], default="build",
                         help="spike: the task answers a question, and the gate accepts an evidenced no")
    command = actions.add_parser("close")
    command.add_argument("project")
    command.add_argument("task_id")
    command = sub.add_parser("spawn")
    command.add_argument("project")
    command.add_argument("task_id")
    command.add_argument("role", choices=["build", "fix", "verify", "evidence"])
    command.add_argument("--replaces")
    for name in ("gate", "reap", "stop", "probe", "pr"):
        command = sub.add_parser(name)
        command.add_argument("project")
        command.add_argument("task_id")
        if name == "pr":
            command.add_argument("--manual-verification", action="store_true")
            command.add_argument("--title", help="short pull request title; defaults to the brief first sentence, up to 72 characters")
    if not (sys.argv[1:] if argv is None else list(argv)):
        from .help import text
        print(text(), end="")
        return 0
    args = parser.parse_args(argv)
    try:
        if hc.owner_mutation(list(argv) if argv is not None else sys.argv[1:]):
            hc.require_owner()
        if args.command in ('automation', 'automations') and os.environ.get('HW_CALLER_TERMINAL') is not None:
            raise ValueError('automations are governed by the owner outside Herdworks sessions')
        authorize(getattr(args, "project", None), getattr(args, "task", None), args.command == "memory")
        if args.command == 'status':
            print('\n'.join(tree(args.project)))
        elif args.command == 'automations':
            if args.action == 'tick':
                for entry in automations.tick(args.at):
                    print(f"{entry['name']} {automations.stamp(entry['at'])} {entry['result']}")
            else:
                print('\n'.join(automations.listing()))
        elif args.command == 'automation':
            if args.action == 'add':
                automations.add(args.name, args.project, args.owner, args.trigger, args.instructions,
                                args.interval, args.daily_cap, args.author)
                print(f'added automation {args.name} on')
            elif args.action in ('on', 'off'):
                automations.switch(args.name, args.action == 'on')
                print(f'{args.name} {args.action}')
            elif args.action == 'test':
                print('Preview only; no message sent.\n' + '\n---\n'.join(automations.preview(args.name)))
            else:
                if args.name:
                    automations.load(args.name)
                for entry in automations.history(args.name):
                    print(f"{entry['name']} {automations.stamp(entry['at'])} {entry['result']}")
        elif args.command == "install":
            for path in install():
                print(f"installed {path.stem}")
        elif args.command == 'memory':
            project = project_path(args.project)
            read_project(project)
            if args.task:
                task_path(args.project, args.task)
            if args.action == 'add':
                print(memory.add(project, args.task, args.title, args.text))
            else:
                print(memory.read(project, args.task, args.role))
        elif args.command == "help":
            from .help import text
            print(text(args.topic), end="")
        elif args.command == "rules":
            from . import rules
            project = project_path(args.project) if args.project else None
            if project is not None:
                read_project(project)
            if args.action == "copy":
                if not args.name:
                    raise ValueError("name the rule to copy: all, build, verify or review")
                print(f"copied to {rules.copy(args.name, project)}; edit it there")
            else:
                print("\n".join(rules.listing(project)))
        elif args.command == "skills":
            from . import skills
            project = project_path(args.project) if args.project else None
            if project is not None:
                read_project(project)
            print("\n".join(skills.listing(project)))
        elif args.command == "setup":
            from .setup import setup
            return setup(check_only=args.check)
        elif args.command == "config":
            print(json.dumps(config(), indent=2))
        elif args.command == "project":
            if args.action == "add":
                if args.github:
                    path = add_github_project(args.project, args.github, args.base, args.prefix)
                else:
                    path = add_project(args.project, args.repo, args.base or "main", args.prefix)
                print(f"added Project {path.name}")
            else:
                print(json.dumps(grant_project(project_path(args.project), args.push,
                                               args.draft_pr, args.remote, args.gh, args.unsandboxed)))
        elif args.command == "up":
            result = up(project_path(args.project))
            print(f"started {result['name']}")
        elif args.command == "say":
            if args.file and args.text is not None:
                raise ValueError("use text or --file")
            text = args.file.read_text() if args.file else args.text
            number, repeat = say(project_path(args.project), text, args.number, base=args.base)
            print(f"delivered {number}" + (" repeat" if repeat else ""))
        elif args.command == "read":
            if args.latest:
                print(latest(project_path(args.project)))
            else:
                for number, text in read(project_path(args.project), args.since):
                    print(f"{number}\n{text.rstrip()}")
        elif args.command == "wait":
            replies = wait(project_path(args.project), args.since, args.timeout)
            for number, text in replies:
                print(f"{number}\n{text.rstrip()}")
            if not replies:
                return 2
        elif args.command == "tasks":
            for line in task_lines(project_path(args.project)):
                print(line)
        elif args.command == "tidy":
            for line in tidy(project_path(args.project)):
                print(line)
        elif args.command == "task" and args.action == "close":
            removed = close(task_path(args.project, args.task_id))
            print(f"closed {args.task_id}: removed {len(removed)} worktrees")
        elif args.command == "task":
            path, repeat = new_task(project_path(args.project), args.brief, args.message,
                                    dict(args.role), args.stuck_after, args.base, args.kind)
            reason = hold_reason(path, allocating=True)
            print(f"{path.name}" + (" repeat" if repeat else "") + (f" queued: {reason}" if reason else ""))
        else:
            path = task_path(args.project, args.task_id)
            if args.command == "spawn":
                print(json.dumps(spawn(path, args.role, replaces=args.replaces)))
            elif args.command == "pr":
                print(open_pr(path, manual_verification=args.manual_verification, title=args.title))
            elif args.command == "stop":
                stop(path)
                print(f"stopped {args.task_id}")
            elif args.command == "probe":
                for fact in probe(path):
                    print(format_fact(fact))
            elif args.command == "gate":
                passed, commit, reasons = gate(path)
                print(f"VERIFIED {commit}" if passed else "REFUSED\n" + "\n".join(reasons))
                if not passed and escalation(path):
                    print(f"ESCALATED after {escalation(path)['failures']} refusals for the same reason; "
                          "start no worker and ask the user")
                return 0 if passed else 1
            elif args.command == "reap":
                for name in reap(path):
                    print(f"reaped {name}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"hw: {error}", file=sys.stderr)
        return 1
