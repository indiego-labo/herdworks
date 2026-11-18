import json
from unittest.mock import patch
from herdworks.limits import role_settings
from herdworks.talk import up
from tests.support import RunCase


class AgentTests(RunCase):
    def test_defaults_override_and_unsandboxed_grant(self):
        self.assertEqual(role_settings(self.project, 'build')['agent'], 'codex')
        choice = {'agent': 'opencode', 'model': 'deepseek/deepseek-flash'}
        (self.home / 'config.json').write_text(json.dumps({'agents': {'builder': choice}}))
        with self.assertRaisesRegex(ValueError, 'grant unsandboxed'):
            role_settings(self.project, 'build')
        p = self.project / 'project.json'
        data = json.loads(p.read_text())
        data['grants']['unsandboxed'] = True
        data['agents'] = {'builder': {'model': 'other/model'}}
        p.write_text(json.dumps(data))
        self.assertEqual(role_settings(self.project, 'build'),
                         dict(agent='opencode', model='other/model', reasoning=None, sandboxed=False))
        data['agents'] = {'builder': {'model': 'other/model', 'reasoning': 'xhigh'}}
        p.write_text(json.dumps(data))
        self.assertEqual(role_settings(self.project, 'build')['reasoning'], 'xhigh')
        data['agents'] = {'builder': {'model': 'other/model', 'reasoning': 'huge'}}
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'reasoning must be'):
            role_settings(self.project, 'build')

    def test_coordinator_choice_selects_template_and_records_sandbox(self):
        p = self.project / 'project.json'
        data = json.loads(p.read_text())
        data.update(agents={'coordinator': {'agent': 'opencode', 'model': 'deepseek/deepseek-flash'}})
        data['grants']['unsandboxed'] = True
        p.write_text(json.dumps(data))
        with patch('herdworks.hc.get', return_value={'state': 'missing'}), patch('herdworks.hc.launch') as launch:
            launch.return_value = dict(name='hw-unit-coord', address='t1', first_message={'sent': True})
            result = up(self.project)
        self.assertEqual(launch.call_args.kwargs['template'], 'hw-coordinator-opencode')
        self.assertFalse(result['sandboxed'])
        self.assertEqual(result['model'], 'deepseek/deepseek-flash')

    def test_launchers_keep_memory_write_scope_and_opencode_provider_paths(self):
        import os
        import subprocess
        import sys
        from pathlib import Path
        from herdworks.runs import git
        root = Path(__file__).resolve().parents[1]
        cwd = self.path / 'build-1/wt'
        cwd.parent.mkdir()
        git(self.repo, 'worktree', 'add', '-b', 'hw/HE-1', cwd, 'HEAD')
        fake_bin = self.root / 'bin'
        fake_bin.mkdir()
        for program in ('codex', 'opencode'):
            script = fake_bin / program
            script.write_text(f'#!{sys.executable}\nimport os,sys,json\nfrom pathlib import Path\n'
                              'print(json.dumps(dict(args=sys.argv[1:], '
                              'paths={k:os.environ.get(k) for k in ("XDG_CONFIG_HOME","XDG_DATA_HOME","XDG_STATE_HOME","HW_HOME")}, '
                              'config=json.loads(Path(os.environ["OPENCODE_CONFIG"]).read_text()) if "OPENCODE_CONFIG" in os.environ else None)))\n')
            script.chmod(0o755)
        env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ['PATH'])
        env.pop('HW_HOME', None)
        def invoke(launcher, mode):
            output = subprocess.check_output([str(root / 'bin' / launcher), mode], cwd=cwd, env=env, text=True)
            return json.loads(output)
        (cwd / 'project.json').write_text('{"agents": {"builder": {"agent": "opencode"}}}')
        build = invoke('hw-codex', 'worker')
        verify = invoke('hw-codex', 'verify')
        self.assertEqual(build['paths']['HW_HOME'], str(self.home))
        self.assertIn(str(self.project / 'memory'), build['args'])
        self.assertNotIn(str(self.project / 'memory'), verify['args'])
        project_file = self.project / 'project.json'
        data = json.loads(project_file.read_text())
        data['agents'] = {'builder': dict(agent='opencode', model='deepseek/deepseek-flash')}
        data['grants']['unsandboxed'] = True
        project_file.write_text(json.dumps(data))
        launched = invoke('hw-opencode', 'worker')
        self.assertEqual(launched['paths']['HW_HOME'], str(self.home))
        self.assertEqual(launched['args'], ['--standalone', '--auto'])
        self.assertEqual(launched['config']['model'], 'deepseek/deepseek-flash')
        self.assertIs(launched['config']['websearch'], False)
        self.assertEqual(launched['paths']['XDG_CONFIG_HOME'], str(Path.home() / '.config'))
        self.assertEqual(launched['paths']['XDG_DATA_HOME'], str(Path.home() / '.local/share'))
        self.assertEqual(launched['paths']['XDG_STATE_HOME'], str(Path.home() / '.local/state'))
        shim = cwd.parent / '.tools/hc'
        self.assertTrue(shim.stat().st_mode & 0o111)
        # The shim passes on the caller's herdr core location only when the caller set one.
        if 'XDG_CONFIG_HOME' in os.environ:
            self.assertIn(os.environ['XDG_CONFIG_HOME'], shim.read_text())
        self.assertIn('hc "$@"', shim.read_text())
