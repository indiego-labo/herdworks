import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
from . import hc
from .gate import check_gate, gate, reap
from .probe import format_fact, probe
from .runs import ROOT, derive_status, escalation, locked, read_task, first_line, events
from .projects import add_project, add_github_project, project_path, task_path, task_paths, new_task, read_project
from .talk import up, say, read, latest, wait, route, answer
from .spawn import spawn
from .pickup import stop, close, tidy
from .pr import open_pr, recorded_pr
from .projects import grant_project
from .limits import config, hold_reason
from . import memory, automations, monitor
from .status import tree
from .home import hw_home

TASK_ID = re.compile(r"[A-Z]{2}-[1-9][0-9]*")


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


def find_task(task_id, project=None):
    """The folder of a task named by its id alone; the Project is needed only when two share a prefix."""
    if project:
        found = [task_path(project, task_id)]
    else:
        found = [item.parent / "tasks" / task_id for item in sorted((hw_home() / "projects").glob("*/project.json"))
                 if read_project(item.parent)["prefix"] == task_id[:2]]
    found = [path for path in found if (path / "task.json").is_file()]
    if not found:
        raise ValueError(f"no task {task_id}; hw tasks PROJECT lists a Project's tasks")
    if len(found) > 1:
        raise ValueError(f"{task_id} exists in Projects {', '.join(p.parents[1].name for p in found)}; add -p PROJECT")
    return found[0]


def open_tasks(project=None):
    projects = [project_path(project)] if project else sorted(
        item.parent for item in (hw_home() / "projects").glob("*/project.json"))
    for folder in projects:
        read_project(folder)
        for item in task_paths(folder):
            if not any(e.get("event") == "closed" for e in events(item.parent)):
                yield item.parent


def newest_task(project=None):
    found = max(open_tasks(project), key=lambda path: read_task(path)["created_at"], default=None)
    if found is None:
        raise ValueError('no open task to follow; start one with: hw run -p PROJECT "..."')
    return found


def reporter(as_json=False):
    """A function that prints a status record when it changed, and every half minute while it runs."""
    shown = []

    def report(current):
        key = (current["state"], current["stage"], current["last_action"], int(current["elapsed_seconds"] // 30))
        if [key] != shown:
            shown[:] = [key]
            print(json.dumps(current) if as_json else time.strftime("%H:%M:%S ") + monitor.line(current), flush=True)
    return report


def follow(path, as_json=False, interval=2.0, sleep=time.sleep):
    """Print the task's status as it changes until it is done, blocked or failed."""
    report = reporter(as_json)
    while True:
        current = monitor.record(path)
        report(current)
        if current["state"] != "running":
            if not as_json:
                print("\n".join(monitor.render(current)), flush=True)
            return {"done": 0, "blocked": 2}.get(current["state"], 1)
        sleep(interval)


def masked(settings):
    """Settings for printing: a webhook URL can carry a secret, so its value is never shown."""
    return {name: "(set)" if name == "webhook" and value else value for name, value in settings.items()}


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
    command = sub.add_parser('run', help='one command: build, check and verify a task, ending with a draft pull '
                                         'request or a verified branch')
    command.add_argument('-p', '--project', required=True)
    command.add_argument('text', nargs='?', help='what you want, with a done check')
    command.add_argument('--file', type=Path, help='read the request from a file')
    command.add_argument('--resume', metavar='TASK_ID', help='continue a blocked, failed or interrupted task')
    command.add_argument('--base', help='branch to start from instead of the Project base')
    command.add_argument('--kind', choices=['build', 'spike'], default='build')
    command.add_argument('--max-minutes', type=float, help='stop the task after this much running time')
    command.add_argument('--max-tokens', type=int, help='stop the task once its agents report this many input, output '
                                                         'and reasoning tokens (cached input is not counted)')
    command.add_argument('--detach', action='store_true', help='run in the background; follow with hw watch')
    command.add_argument('--json', action='store_true', help='print each status change as a JSON line')
    command = sub.add_parser('status', help='what is running; with a task id, that task\'s stage, elapsed time, '
                                            'tokens and last action')
    command.add_argument('project', nargs='?', metavar='PROJECT|TASK_ID')
    command.add_argument('-p', dest='within', metavar='PROJECT', help='the Project, when two share a task prefix')
    command.add_argument('--json', action='store_true')
    command = sub.add_parser('watch', help='follow a task until it is done, blocked or failed')
    command.add_argument('project', nargs='?', metavar='TASK_ID', help='default: the newest open task')
    command.add_argument('-p', dest='within', metavar='PROJECT')
    command.add_argument('--json', action='store_true', help='print each status change as a JSON line')
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
    command.add_argument("--task", metavar="TASK_ID", help="send it to this task; a hw run task gives it to a builder "
                                                           "and, if it was blocked, resumes")
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
    command = sub.add_parser("tidy", help="close tasks whose pull request was merged or closed, and clear stopped tasks' worktrees")
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
    words = list(sys.argv[1:] if argv is None else argv)
    # Python 3.12+ drops a leading "--" before the command; 3.11 rejects it. Treat both alike.
    args, extra = parser.parse_known_args(words[1:] if words[:1] == ["--"] else words)
    # Python 3.11 argparse leaves an optional positional unfilled when an option sits before it
    # (hw say P --task HE-2 "text"); 3.12+ fills it. Fill it the same way on every version.
    # parse_intermixed_args would do this, but it raises TypeError on a parser with subcommands (3.11 and 3.13).
    slot = {"say": "text", "run": "text", "status": "project", "watch": "project"}.get(args.command)
    if extra and slot and getattr(args, slot) is None and len(extra) == 1 and not extra[0].startswith("-"):
        setattr(args, slot, extra.pop())
    if extra:
        parser.error("unrecognized arguments: " + " ".join(extra))
    try:
        # Starting a run and answering one are the owner's decisions, never an agent's. This is decided
        # from the parsed command, so no abbreviation or `--` spelling of the command line can skip it.
        if (hc.owner_mutation(list(argv) if argv is not None else sys.argv[1:])
                or args.command == 'run' or (args.command == 'say' and args.task)):
            hc.require_owner()
        if args.command in ('automation', 'automations') and os.environ.get('HW_CALLER_TERMINAL') is not None:
            raise ValueError('automations are governed by the owner outside Herdworks sessions')
        target = None
        if args.command in ('status', 'watch'):
            # A task id names its own Project, so the caller is checked against that Project.
            if args.project and TASK_ID.fullmatch(args.project):
                target = find_task(args.project, args.within)
            elif args.command == 'watch':
                if args.project:
                    raise ValueError('watch follows a task id such as HE-1')
                target = newest_task(args.within)
            args.project = target.parents[1].name if target else args.project or args.within
        authorize(getattr(args, "project", None), getattr(args, "task", None) if args.command == "memory" else None,
                  args.command == "memory")
        if args.command == 'watch':
            return follow(target, args.json)
        elif args.command == 'status':
            if target:
                current = monitor.record(target)
                print(json.dumps(current, indent=2) if args.json else '\n'.join(monitor.render(current)))
            elif args.json:
                print(json.dumps([monitor.record(path) for path in open_tasks(args.project)], indent=2))
            else:
                print('\n'.join(tree(args.project)))
        elif args.command == 'run':
            from . import drive
            project = project_path(args.project)
            if args.resume:
                if args.text is not None or args.file or args.base:
                    raise ValueError('--resume continues an existing task; it takes no request or base')
                path = task_path(args.project, args.resume)
                if not (path / 'task.json').is_file():
                    raise ValueError(f'no task {args.resume} in Project {args.project}')
                drive.set_budget(path, args.max_minutes, args.max_tokens)  # refuses a task hw run does not drive
            else:
                if args.file and args.text is not None:
                    raise ValueError('use text or --file')
                path = drive.create(project, args.file.read_text() if args.file else args.text, args.base, args.kind,
                                    args.max_minutes, args.max_tokens)
            if args.detach:
                drive.detach(path)
                print(f'{path.name} is running in the background. Follow it with: hw watch {path.name}')
                return 0
            if not args.json:
                print(f'{path.name} on branch hw/{path.name}. From another terminal: hw status {path.name}', flush=True)
            final = drive.drive(path, announce=reporter(args.json))
            if not args.json:
                print('\n'.join(monitor.render(final)), flush=True)
            return drive.EXIT.get(final['state'], 1)
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
            print(json.dumps(masked(config()), indent=2))
        elif args.command == "project":
            if args.action == "add":
                if args.github:
                    path = add_github_project(args.project, args.github, args.base, args.prefix)
                else:
                    path = add_project(args.project, args.repo, args.base or "main", args.prefix)
                print(f"added Project {path.name}")
            else:
                print(json.dumps(masked(grant_project(project_path(args.project), args.push,
                                                      args.draft_pr, args.remote, args.gh, args.unsandboxed))))
        elif args.command == "up":
            result = up(project_path(args.project))
            print(f"started {result['name']}")
        elif args.command == "say":
            if args.file and args.text is not None:
                raise ValueError("use text or --file")
            text = args.file.read_text() if args.file else args.text
            project = project_path(args.project)
            # Only --task routes a message to a task. A redelivery was routed when it was first sent.
            target = route(project, args.task) if args.task and args.number is None else None
            if target:
                from . import drive
                number = answer(project, target, text)
                watch = f"Follow it with: hw watch {target.name}"
                if monitor.record(target)["state"] == "running":
                    print(f"delivered {number} to {target.name}: it is running and will not be done before a builder "
                          f"has read this. {watch}")
                else:
                    try:
                        drive.detach(target)
                    except (OSError, ValueError, RuntimeError) as error:
                        # The answer is saved; sending it again would save a second copy.
                        raise RuntimeError(f"answer {number} is saved for {target.name}, but the task was not resumed: "
                                           f"{error}. Do not send it again; continue with: "
                                           f"{drive.commands(target)['resume']}") from None
                    print(f"delivered {number} to {target.name} and resumed it. {watch}")
            else:
                number, repeat = say(project, text, args.number, base=args.base, about=args.task)
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
            if (args.command in ("spawn", "gate", "reap", "pr") and os.environ.get("HW_CALLER_TERMINAL") is not None
                    and (path / "task.json").is_file() and read_task(path).get("driver") == "run"):
                raise ValueError(f"{args.task_id} is driven by hw run, not by the coordinator; "
                                 f"report its state from: hw status {args.task_id}")
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
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"hw: {error}", file=sys.stderr)
        return 1
