from herdworks import rules
from herdworks.spawn import build_brief
from tests.support import RunCase


class RulesTests(RunCase):
    def test_project_then_machine_then_built_in(self):
        self.assertEqual(rules.find('verify', self.project)[0], 'built-in')
        machine = rules.copy('verify')
        self.assertEqual(machine, self.home / 'rules/verify.md')
        self.assertEqual(rules.find('verify', self.project), ('machine', machine))
        project = rules.copy('verify', self.project)
        self.assertEqual(rules.find('verify', self.project), ('Project', project))
        self.assertEqual(rules.find('verify'), ('machine', machine))
        with self.assertRaises(ValueError):
            rules.copy('verify', self.project)
        with self.assertRaises(ValueError):
            rules.find('nonsense')

    def test_edited_project_rule_reaches_the_build_brief(self):
        (self.notes / 'intent.md').write_text('DONE CHECK')
        rules.copy('build', self.project).write_text('Always run make lint.')
        brief = build_brief(self.path)
        self.assertIn('Always run make lint.', brief)
        self.assertIn('house rules: all', brief)
