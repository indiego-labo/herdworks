import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch
from herdworks.runs import git
from tests.support import RunCase

SOURCE = Path(__file__).resolve().parents[1] / '.agents/skills/verify-herdworks/scripts/journey.py'
spec = importlib.util.spec_from_file_location('factory_journey', SOURCE)
journey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journey)


class RegressionRecipeTests(RunCase):
    def test_selected_parent_and_head_are_exercised_and_checkout_removed(self):
        scripts = self.repo / '.agents/skills/verify-herdworks/scripts'
        scripts.mkdir(parents=True)
        (scripts / 'journey.py').write_text(
            'import pathlib,sys\n'
            'evidence=pathlib.Path(sys.argv[sys.argv.index("--evidence")+1])\n'
            'evidence.mkdir()\n'
            'root=pathlib.Path(__file__).resolve().parents[4]\n'
            '(evidence/"root.txt").write_text(str(root))\n'
            'print("PASS", sys.argv[1])\n')
        programs = self.repo / 'bin'
        programs.mkdir()
        installer = programs / 'hw'
        installer.write_text(f'#!{sys.executable}\nprint("installed")\n')
        installer.chmod(0o755)
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'test: regression command fixture')
        parent = git(self.repo, 'rev-parse', 'HEAD')
        destination = self.root / 'regression'
        with patch.object(journey, 'ROOT', self.repo), patch.object(journey, 'doctor', return_value={}), \
                patch.object(journey, 'snapshot', return_value=set()):
            journey.regression(destination, parent)
        self.assertEqual(json.loads((destination / 'commits.json').read_text())['parent'], parent)
        self.assertEqual((destination / 'parent/root.txt').read_text(), str(destination / 'parent-checkout'))
        self.assertEqual((destination / 'head/root.txt').read_text(), str(self.repo))
        self.assertFalse((destination / 'parent-checkout').exists())
        self.assertNotIn('parent-checkout', git(self.repo, 'worktree', 'list', '--porcelain'))
        self.assertTrue((destination / 'result.txt').read_text().startswith('PASS'))

    def test_initial_acknowledgement_is_not_a_later_answer_or_repeat(self):
        import os
        outbox = self.project / 'coordinator/outbox'
        for filename, number, timestamp in [('000003.md', 2, 70), ('000004.md', 1, 80), ('000001.md', 1, 49)]:
            file = outbox / filename
            file.write_text(f'REPLY\nMessage: {number}\nTask: HE-1\n')
            os.utime(file, (timestamp, timestamp))
        self.assertEqual(journey.initial_reply(self.project).name, '000001.md')

    def test_doctor_requires_scratch_runtime_before_contacting_core(self):
        import os
        with patch.dict(os.environ, HC_SESSION='scratch', XDG_CONFIG_HOME=str(self.root / 'config'),
                        XDG_STATE_HOME=str(self.root / 'state'), XDG_RUNTIME_DIR=''), patch('herdworks.hc.call') as call:
            with self.assertRaisesRegex(RuntimeError, 'XDG_RUNTIME_DIR'):
                journey.doctor()
            call.assert_not_called()

    def test_doctor_refuses_hw_home_inside_checkout_before_core(self):
        import os
        with patch.dict(os.environ, HC_SESSION='scratch', XDG_CONFIG_HOME=str(self.root / 'config'),
                        XDG_STATE_HOME=str(self.root / 'state'), XDG_RUNTIME_DIR=str(self.root / 'runtime')):
            for home in (journey.ROOT, journey.ROOT / 'scratch-home'):
                with self.subTest(home=home), patch.dict(os.environ, HW_HOME=str(home)), patch('herdworks.hc.call') as call:
                    with self.assertRaisesRegex(RuntimeError, 'checkout'):
                        journey.doctor()
                    call.assert_not_called()

    def test_cleanup_never_touches_baseline_when_another_owner_removes_it(self):
        evidence = self.root / 'cleanup-evidence'
        evidence.mkdir()
        def transport(*args):
            if args[0] == 'ls':
                return dict(terminals=[dict(address='owned')])
            if args[0] == 'read':
                return dict(text='last screen')
            return {}
        session = dict(address='owned', state='live', labels=dict(hw='project:unit'))
        with patch('herdworks.hc.get', return_value=session), patch('herdworks.hc.call', side_effect=transport) as call, patch.object(journey, 'snapshot', return_value=set()):
            journey.cleanup(self.project, evidence, {'foreign'})
        mutations = [c.args for c in call.call_args_list if c.args[0] in ('kill', 'rm')]
        self.assertEqual(mutations, [('kill', 'owned'), ('rm', 'owned')])
        cleanup = json.loads((evidence / 'cleanup.json').read_text())
        self.assertEqual(cleanup['foreign_missing'], ['foreign'])
        self.assertTrue(cleanup['foreign_untouched'])
        self.assertEqual(cleanup['owned_remaining'], [])
