import json
import os
import subprocess
import shlex
import sys
from pathlib import Path
from .runs import git


class HCError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def call(*args):
    result = subprocess.run(["hc", *map(str, args)], capture_output=True, text=True)
    if result.returncode:
        raise HCError(result.returncode, f"hc {args[0]}: {result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout)


def template_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "herdr-core/templates"


def launch(*, name, cwd, template, task, identity, role, parent=None, program=None):
    args = ["run", "--bg", "--json", "--name", name, "--cwd", cwd,
            "--label", f"hw={identity}", "--label", f"role={role}"]
    args += ["--parent", parent] if parent else ["--no-parent"]
    if program:
        if sys.platform != "darwin" or not os.access("/usr/bin/sandbox-exec", os.X_OK):
            raise RuntimeError("--role overrides require macOS sandbox-exec; refusing an unprotected launch")
        # Overrides are untrusted programs: only their session is writable.
        # Builders also need the target's shared git directory to commit.
        folder = Path(cwd).resolve().parent
        writable = [folder]
        if role == "build":
            common = git(cwd, "rev-parse", "--git-common-dir")
            writable.append((Path(cwd) / common).resolve(strict=True))
        profile = ('(version 1)(allow default)(deny file-write*)(deny network*)'
                   # Git opens this nonpersistent sink read/write.
                   '(allow file-write-data (literal "/dev/null"))'
                   '(allow file-write* ' + ' '.join(
                       f'(subpath {json.dumps(str(p), ensure_ascii=False)})'
                       for p in writable) + ')')
        checked = subprocess.run(["/usr/bin/sandbox-exec", "-p", profile, "/usr/bin/true"],
                                 capture_output=True, text=True)
        if checked.returncode:
            raise RuntimeError("--role override sandbox could not be applied; refusing an unprotected launch: "
                               + (checked.stderr.strip() or checked.stdout.strip()))
        temporary = folder / ".tmp"
        temporary.mkdir(exist_ok=True)
        return call(*args, "--", "/usr/bin/sandbox-exec", "-p", profile,
                    "/usr/bin/env", f"TMPDIR={temporary}", f"TMPPREFIX={temporary / 'zsh'}",
                    program, task)
    return call(*args, template, task)


def sessions():
    return call("ls", "--json")["terminals"]


def get(name):
    try:
        return call("get", "--json", name)
    except HCError as error:
        if error.code != 3:
            raise
        return {"state": "missing", "status": "missing", "turn": 0}


def caller_ancestry():
    result = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('cannot verify owner process ancestry')
    processes = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) >= 2:
            processes[int(fields[0])] = (int(fields[1]), fields[2] if len(fields) == 3 else '')
    ancestry = {}
    pid = os.getpid()
    while pid:
        if pid in ancestry or pid not in processes:
            raise RuntimeError('cannot verify complete owner process ancestry')
        parent, command = processes[pid]
        ancestry[pid] = command
        pid = parent
    return ancestry


def require_owner():
    denied = 'operation must be performed by the owner outside Herdworks sessions'
    if os.environ.get('HW_CALLER_TERMINAL') is not None or os.environ.get('HW_HC_HOP'):
        raise ValueError(denied)
    terminal = os.environ.get('HC_TERMINAL_ID')
    if terminal and get(terminal).get('labels', {}).get('hw'):
        raise ValueError(denied)
    ancestry = caller_ancestry()
    for command in ancestry.values():
        try:
            words = shlex.split(command)
        except ValueError:
            words = command.split()
        programs = words[:1]
        if words and Path(words[0]).name.lower().startswith('python'):
            programs = words
        if any(Path(word).name in ('hw-codex', 'hw-opencode') for word in programs):
            raise ValueError(denied)
    for terminal in sessions():
        detail = get(terminal['address'])
        if detail.get('state') == 'live' and detail.get('pid') in ancestry and detail.get('labels', {}).get('hw'):
            raise ValueError(denied)


def owner_mutation(argv):
    return (argv[:2] in (['automation', 'add'], ['automation', 'on'], ['automation', 'off'],
                         ['automations', 'tick'], ['project', 'grant']))


def forward(entrypoint, argv):
    if owner_mutation(argv):
        print("hw: operation must be performed by the owner outside Herdworks sessions", file=sys.stderr)
        return 1
    caller = os.environ.get("HC_TERMINAL_ID")
    if not caller:
        raise RuntimeError("Herdworks hop requires a caller terminal")
    return subprocess.call([
        "hc", "exec", "--", "env", "-u", "HW_HC_HOP",
        f"HW_CALLER_TERMINAL={caller}",
        *([f"HW_HOME={os.environ['HW_HOME']}"] if "HW_HOME" in os.environ else []),
        sys.executable, str(entrypoint), *argv])
