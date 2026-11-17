import json
import shlex
import subprocess
import sys
import unittest
from unittest.mock import patch
from herdworks.runs import append_event, git, read_task
from herdworks.spawn import spawn
from tests.support import RunCase


class HookTests(RunCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS sandbox-exec')
    def test_sandboxed_builder_hook_cannot_run_during_verifier_setup(self):
        marker = self.root / 'hook-ran.txt'
        script = self.root / 'planted-builder.py'
        hook = '#!/bin/sh\nprintf "hook ran" > ' + shlex.quote(str(marker)) + '\n'
        script.write_text(
            'import subprocess\nfrom pathlib import Path\n'
            'common = Path(subprocess.check_output(["git", "rev-parse", "--git-common-dir"], text=True).strip()).resolve()\n'
            'hook = common / "hooks/post-checkout"\n'
            f'hook.write_text({hook!r})\nhook.chmod(0o755)\n'
            'subprocess.run(["git", "config", "core.hooksPath", str(hook.parent)], check=True)\n'
            'Path("hello.py").write_text("print(\'changed\')\\n")\n'
            'subprocess.run(["git", "add", "hello.py"], check=True)\n'
            'subprocess.run(["git", "commit", "-m", "test: plant checkout hook"], check=True)\n'
            'commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()\n'
            'Path("../report.md").write_text("READY " + commit + "\\n")\n'
            'print("Sandboxed builder installed executable post-checkout and committed")\n')
        launcher = self.root / 'planted-builder'
        launcher.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))}\n')
        launcher.chmod(0o755)
        data = read_task(self.path)
        data['roles'] = {'build': str(launcher)}
        (self.path / 'task.json').write_text(json.dumps(data))
        (self.notes / 'intent.md').write_text('Check exact CLI output')
        append_event(self.path, dict(event='session', role='coordinator', name='hw-unit-coord', address='t1'))

        def transport(*args):
            if args[0] == 'get':
                return dict(state='finished')
            name = args[args.index('--name') + 1]
            if '--' in args:
                cwd = args[args.index('--cwd') + 1]
                result = subprocess.run(list(map(str, args[args.index('--') + 1:])),
                                        cwd=cwd, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout, end='')
            return dict(name=name, address=name, first_message={'sent': True})

        with patch('herdworks.hc.call', side_effect=transport):
            spawn(self.path, 'build')
            self.assertTrue((self.repo / '.git/hooks/post-checkout').is_file())
            self.assertFalse(marker.exists())
            control = self.root / 'control-wt'
            subprocess.run(['git', '-C', str(self.repo), 'worktree', 'add', '--detach', str(control), 'hw/HE-1'],
                           check=True, capture_output=True, text=True)
            self.assertEqual(marker.read_text(), 'hook ran')
            marker.unlink()
            subprocess.run(['git', '-C', str(self.repo), 'worktree', 'remove', str(control)],
                           check=True, capture_output=True, text=True)
            print('Raw Git control executed the planted hook; marker cleared before hw setup')
            spawn(self.path, 'verify')
        self.assertTrue((self.path / 'verify-1/wt/.git').exists())
        self.assertFalse(marker.exists(), 'hw verifier preparation executed the planted hook outside its sandbox')
        print('Herdworks verifier setup: planted hook did not run')
