import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from herdworks import hc
from tests.support import RunCase
from herdworks.runs import git
from herdworks.projects import add_project, new_task

ROOT = Path(__file__).resolve().parents[1]


class LaunchTests(RunCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS sandbox-exec')
    def test_override_cannot_replace_factory_gate(self):
        scratch = self.root / 'hw-copy'
        shutil.copytree(ROOT / 'herdworks', scratch / 'herdworks',
                        ignore=shutil.ignore_patterns('__pycache__'))
        project = add_project('forged', self.repo, prefix='FO', home=scratch / 'home')
        run, _ = new_task(project, self.brief)
        folder = run / 'evidence-1'
        cwd = folder / 'work'
        cwd.mkdir(parents=True)
        source = scratch / 'herdworks/gate.py'
        original = source.read_bytes()
        script = folder / 'attack.py'
        script.write_text(
            'from pathlib import Path\n'
            f'target = Path({str(source)!r})\n'
            'try:\n'
            ' target.write_text("def check_gate(path): return True, \'forged\', []\\n"\n'
            '                   "def gate(path): return check_gate(path)\\n"\n'
            '                   "def reap(path): return []\\n")\n'
            ' print("REPLACED herdworks/gate.py")\n'
            'except PermissionError:\n print("DENIED herdworks/gate.py")\n')

        def direct_launch(*args):
            result = subprocess.run(list(map(str, args[args.index('--') + 1:])),
                                    cwd=cwd, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout, end='')
            return result.stdout

        with patch('herdworks.hc.call', side_effect=direct_launch):
            hc.launch(name='attack', cwd=cwd, template='unused', task=str(script),
                      identity='forged', role='evidence', program=sys.executable)
        status = subprocess.run(
            [sys.executable, '-c', 'from herdworks.cli import main; raise SystemExit(main(["tasks", "forged"]))'],
            cwd=scratch, env=dict(os.environ, HW_HOME=str(scratch / "home")), capture_output=True, text=True, check=True)
        print(status.stdout, end='')
        self.assertNotEqual(status.stdout.split()[1], 'verified', status.stdout)
        self.assertEqual(source.read_bytes(), original)

    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS sandbox-exec')
    def test_override_protects_task_records_and_other_sessions(self):
        self.path = self.path.rename(self.path.parent / 'run with "quotes"')
        (self.path / 'other-1').mkdir()
        for role in ('build', 'verify', 'evidence'):
            with self.subTest(role=role):
                folder = self.path / f'{role}-1'
                cwd = folder / 'wt'
                folder.mkdir()
                git(self.repo, 'worktree', 'add', '--detach', cwd, 'HEAD')
                (folder / 'alias').symlink_to(self.path, target_is_directory=True)
                script = folder / 'probe.py'
                script.write_text(
                    'import json, os, socket, subprocess, tempfile\nfrom pathlib import Path\n'
                    f'run = Path({str(self.path)!r})\nfolder = Path({str(folder)!r})\n'
                    'denied = {}\n'
                    'def attempt(label, action):\n'
                    ' try:\n  action()\n  denied[label] = False\n'
                    ' except PermissionError:\n  denied[label] = True\n'
                    'for target in (run / "events.jsonl", run / "task.json",\n'
                    f'               Path({str(self.notes / "forged")!r}), run / "other-1/forged",\n'
                    '               folder / "alias/events.jsonl"):\n'
                    ' attempt(str(target), lambda: target.write_text("forged"))\n'
                    'attempt("unlink", lambda: (run / "events.jsonl").unlink())\n'
                    'attempt("chmod", lambda: (run / "task.json").chmod(0o777))\n'
                    '(folder / "replacement").write_text("forged")\n'
                    'attempt("replace", lambda: (folder / "replacement").replace(run / "task.json"))\n'
                    'attempt("hardlink", lambda: os.link(run / "events.jsonl", folder / "linked"))\n'
                    'attempt("rename ancestor", lambda: run.parent.rename(run.parent.with_name("moved")))\n'
                    f'for target in (Path({str(ROOT / "herdworks/hc.py")!r}),\n'
                    f'               Path({str(self.repo / "outside.txt")!r}),\n'
                    f'               Path.home() / {self.root.name!r}, Path("/tmp") / {self.root.name!r}):\n'
                    ' attempt(str(target), lambda: target.open("a").close())\n'
                    f'git_probe = Path({str(self.repo / ".git/override-probe")!r})\n'
                    'attempt("git directory", lambda: git_probe.write_text("probe"))\n'
                    'result = subprocess.run(["hc", "ls", "--json"], capture_output=True, text=True, timeout=5)\n'
                    'denied["hc ls"] = result.returncode != 0\n'
                    'print("hc ls:", result.returncode, result.stderr.strip())\n'
                    'core = Path(os.environ["XDG_RUNTIME_DIR"]) / "herdr-core" / (os.environ["HC_SESSION"] + ".sock")\n'
                    'assert core.exists(), core\n'
                    'def connect(family, address):\n'
                    ' with socket.socket(family, socket.SOCK_STREAM) as client:\n'
                    '  client.connect(address)\n'
                    'attempt("core socket", lambda: connect(socket.AF_UNIX, str(core)))\n'
                    'attempt("tcp network", lambda: connect(socket.AF_INET, ("127.0.0.1", 9)))\n'
                    '(folder / "own.txt").write_text("allowed")\n'
                    'Path("work.txt").write_text("allowed")\n'
                    'with tempfile.NamedTemporaryFile() as temporary:\n'
                    ' assert Path(temporary.name).parent == folder / ".tmp"\n'
                    'subprocess.run(["sh", "-c", "printf ordinary > shell.txt"], check=True)\n'
                    'print(json.dumps(denied))\n')

                def direct_launch(*args):
                    result = subprocess.run(list(map(str, args[args.index('--') + 1:])),
                                            cwd=cwd, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    print(role, result.stdout, end='')
                    return json.loads(result.stdout.splitlines()[-1])

                with patch('herdworks.hc.call', side_effect=direct_launch):
                    denied = hc.launch(name='probe', cwd=cwd, template='unused', task=str(script),
                                       identity='unit', role=role, program=sys.executable)
                self.assertEqual(denied.pop('git directory'), role != 'build')
                self.assertTrue(all(denied.values()), denied)
                self.assertEqual((folder / 'own.txt').read_text(), 'allowed')
                self.assertEqual((cwd / 'work.txt').read_text(), 'allowed')
                self.assertFalse((self.repo / 'outside.txt').exists())
                self.assertEqual((cwd / 'shell.txt').read_text(), 'ordinary')

    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS sandbox-exec')
    def test_override_builder_can_commit_on_task_branch(self):
        cwd = self.path / 'build-1/wt'
        cwd.parent.mkdir()
        git(self.repo, 'worktree', 'add', '-b', 'hw/HE-1', cwd, 'HEAD')
        script = cwd.parent / 'commit.sh'
        script.write_text('set -eu\nprintf changed > hello.py\ngit add hello.py\n'
                          'git commit -m "test: planted builder"\n')

        def direct_launch(*args):
            result = subprocess.run(list(map(str, args[args.index('--') + 1:])),
                                    cwd=cwd, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout, end='')
            return result.stdout

        before = git(self.repo, 'rev-parse', 'HEAD')
        with patch('herdworks.hc.call', side_effect=direct_launch):
            hc.launch(name='builder', cwd=cwd, template='unused', task=str(script),
                      identity='unit', role='build', program='/bin/sh')
        self.assertNotEqual(git(self.repo, 'rev-parse', 'hw/HE-1'), before)
        self.assertEqual(git(self.repo, 'show', 'hw/HE-1:hello.py'), 'changed')

    def test_override_fails_closed_without_os_sandbox(self):
        for unavailable in (patch('herdworks.hc.sys.platform', 'linux'),
                            patch('herdworks.hc.os.access', return_value=False)):
            with unavailable, patch('herdworks.hc.call') as call:
                with self.assertRaisesRegex(RuntimeError, 'refusing an unprotected launch'):
                    hc.launch(name='probe', cwd=self.path / 'build-1/wt', template='unused',
                              task='brief', identity='unit', role='build', program='/bin/true')
                call.assert_not_called()

    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS sandbox-exec')
    def test_override_fails_closed_when_sandbox_rejects_profile(self):
        cwd = self.path / 'evidence-1/work'
        cwd.mkdir(parents=True)
        # Force a malformed profile; the real sandbox-exec must reject it.
        with patch('herdworks.hc.json.dumps', return_value='('), patch('herdworks.hc.call') as call:
            with self.assertRaisesRegex(RuntimeError, 'could not be applied; refusing an unprotected launch') as error:
                hc.launch(name='probe', cwd=cwd, template='unused', task='brief',
                          identity='unit', role='evidence', program='/bin/true')
            print(error.exception)
            call.assert_not_called()

    def fake(self, name):
        folder = self.root / "fake-bin"
        folder.mkdir(exist_ok=True)
        script = folder / name
        script.write_text(f"#!{sys.executable}\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
        script.chmod(0o755)
        return dict(os.environ, PATH=str(folder) + os.pathsep + os.environ["PATH"])

    def test_sessions_inherit_only_allowlisted_environment_names(self):
        env = self.fake("codex")
        env.update(SOME_API_KEY="synthetic", HW_SECRET="synthetic", UNRELATED_SETTING="synthetic",
                   HW_HOME=str(self.home), CODEX_HOME=str(self.root / "codex"),
                   HC_SESSION="scratch", XDG_CONFIG_HOME=str(self.root / "config"))
        script = Path(env["PATH"].split(os.pathsep)[0]) / "codex"
        script.write_text(f"#!{sys.executable}\nimport json,os\nprint(json.dumps(sorted(os.environ)))\n")
        for mode in ("coordinator", "worker", "verify"):
            with self.subTest(mode=mode):
                result = subprocess.run([str(ROOT / "bin/hw-codex"), mode], cwd=self.repo,
                                        env=env, capture_output=True, text=True, check=True)
                names = json.loads(result.stdout)
                for required in ("HOME", "PATH", "HC_SESSION", "XDG_CONFIG_HOME", "HW_HOME", "CODEX_HOME", "TMPDIR", "TMPPREFIX"):
                    self.assertIn(required, names)
                for secret in ("SOME_API_KEY", "HW_SECRET", "UNRELATED_SETTING"):
                    self.assertNotIn(secret, names)

    def test_worker_uses_proven_approval_and_trust_contract(self):
        env = self.fake("codex")
        result = subprocess.run([str(ROOT / "bin/hw-codex"), "worker"], cwd=self.repo,
                                env=env, capture_output=True, text=True, check=True)
        args = json.loads(result.stdout)
        self.assertIn("--approve-for-me", args)
        self.assertNotIn("-s", args)
        self.assertNotIn("--sandbox", args)
        self.assertIn("--no-daemon", args)
        self.assertIn("check_for_update_on_startup=false", args)
        self.assertIn(str(self.root), args)
        self.assertIn('projects={' + json.dumps(str(self.repo)) + '={trust_level="trusted"}}', args)

    def test_coordinator_cannot_request_wider_access(self):
        env = self.fake("codex")
        result = subprocess.run([str(ROOT / "bin/hw-codex"), "coordinator"], cwd=self.repo,
                                env=env, capture_output=True, text=True, check=True)
        args = json.loads(result.stdout)
        self.assertEqual(args[args.index("-a") + 1], "never")
        self.assertEqual(args[args.index("-s") + 1], "workspace-write")
        self.assertNotIn("--approve-for-me", args)
        self.assertNotIn(str(self.root), args)
        self.assertIn("sandbox_workspace_write.network_access=true", args)

    def test_both_modes_exclude_shared_temporary_roots_and_supply_private_tmpdir(self):
        env = self.fake("codex")
        script = Path(env["PATH"].split(os.pathsep)[0]) / "codex"
        script.write_text(
            f"#!{sys.executable}\nimport json,os,sys,tempfile\n"
            "with tempfile.NamedTemporaryFile() as temporary:\n"
            " print(json.dumps({'args': sys.argv[1:], 'tmpdir': os.environ['TMPDIR'],\n"
            "                   'tmpprefix': os.environ['TMPPREFIX'], 'file': temporary.name}))\n")
        for mode in ("coordinator", "worker", "verify"):
            with self.subTest(mode=mode):
                result = subprocess.run([str(ROOT / "bin/hw-codex"), mode], cwd=self.repo,
                                        env=env, capture_output=True, text=True, check=True)
                launch = json.loads(result.stdout)
                self.assertIn("sandbox_workspace_write.exclude_slash_tmp=true", launch["args"])
                self.assertIn("sandbox_workspace_write.exclude_tmpdir_env_var=true", launch["args"])
                expected = (self.repo if mode == "coordinator" else self.root) / ".tmp"
                self.assertEqual(Path(launch["tmpdir"]), expected)
                self.assertEqual(Path(launch["tmpprefix"]), expected / "zsh")
                self.assertEqual(Path(launch["file"]).parent, expected)

    def test_all_forwarded_commands_cross_hc_with_caller_identity(self):
        env = self.fake("hc")
        env.update(HW_HC_HOP="1", HC_TERMINAL_ID="t-caller")
        for command in (["install"], ["up", "unit"], ["spawn", "unit", "HE-1", "build"], ["probe", "unit", "HE-1"], ["gate", "unit", "HE-1"], ["reap", "unit", "HE-1"], ["tasks", "unit"], ["pr", "unit", "HE-1"]):
            with self.subTest(command=command):
                result = subprocess.run([str(ROOT / "bin/hw"), *command], env=env,
                                        capture_output=True, text=True, check=True)
                args = json.loads(result.stdout)
                self.assertEqual(args[:5], ["exec", "--", "env", "-u", "HW_HC_HOP"])
                self.assertIn("HW_CALLER_TERMINAL=t-caller", args)
                self.assertIn(f"HW_HOME={self.home}", args)
                self.assertEqual(args[-len(command):], command)

    def test_verifier_has_network_and_only_session_write_access(self):
        env = self.fake("codex")
        result = subprocess.run([str(ROOT / "bin/hw-codex"), "verify"], cwd=self.repo,
                                env=env, capture_output=True, text=True, check=True)
        args = json.loads(result.stdout)
        self.assertEqual(args[args.index("-a") + 1], "never")
        self.assertEqual(args[args.index("-s") + 1], "workspace-write")
        self.assertIn("sandbox_workspace_write.network_access=true", args)
        self.assertEqual(args[args.index("--add-dir") + 1], str(self.root))
        self.assertNotIn("--approve-for-me", args)

    def test_coordinator_trusts_its_folder_outside_git(self):
        env = self.fake("codex")
        cwd = self.root / "outside-project/coordinator"
        cwd.mkdir(parents=True)
        result = subprocess.run([str(ROOT / "bin/hw-codex"), "coordinator"], cwd=cwd,
                                env=env, capture_output=True, text=True, check=True)
        args = json.loads(result.stdout)
        self.assertIn('projects={' + json.dumps(str(cwd)) + '={trust_level="trusted"}}', args)
        self.assertTrue((cwd / ".tmp").is_dir())

    def test_coordinator_adapter_enables_factory_hop(self):
        env = self.fake("codex")
        script = Path(env["PATH"].split(os.pathsep)[0]) / "codex"
        script.write_text(f"#!{sys.executable}\nimport os\nprint(os.environ.get('HW_HC_HOP', ''))\n")
        result = subprocess.run([str(ROOT / "bin/hw-codex"), "coordinator"], cwd=self.repo,
                                env=env, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "1")
