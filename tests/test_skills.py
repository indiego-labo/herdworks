import os
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from herdworks import cli, skills
from herdworks.help import text as help_text
from herdworks.spawn import build_brief
from tests.support import RunCase

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ('If a skill or house rule conflicts with the task protocol in this brief '
            '(starting agents, pushing, the READY line, the verdict and review files), '
            'the protocol wins.')


class SkillsTests(RunCase):
    def setUp(self):
        super().setUp()
        self.user = self.root / 'user'
        self.user.mkdir()
        home = patch.dict(os.environ, HOME=str(self.user))
        home.start()
        self.addCleanup(home.stop)
        caller = os.environ.pop('HW_CALLER_TERMINAL', None)
        if caller is not None:
            self.addCleanup(os.environ.__setitem__, 'HW_CALLER_TERMINAL', caller)

    def install(self, name, folder):
        skill = Path(folder) / name
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text(f'---\nname: {name}\n---\n')
        return skill

    def test_agents_folder_skill_is_listed_with_both_agents(self):
        folder = self.user / '.agents/skills'
        skill = self.install('tmp-skill', folder)
        self.install('claude-only', self.user / '.claude/skills')
        self.install('codex-only', self.user / '.codex/skills')
        repo_skill = self.install('repo-skill', self.repo / '.agents/skills')

        found = {entry['name']: entry for entry in skills.inventory(self.project)}
        self.assertEqual(found['tmp-skill']['agents'], ('opencode', 'Codex'))
        self.assertEqual(found['claude-only']['agents'], ('opencode',))
        self.assertEqual(found['codex-only']['agents'], ('Codex',))
        self.assertEqual(found['repo-skill']['agents'], ('opencode', 'Codex'))
        self.assertEqual(found['tmp-skill']['folder'], skill)

        output = '\n'.join(skills.listing(self.project))
        self.assertIn('~/.agents/skills/tmp-skill', output)
        self.assertIn(str(repo_skill), output)
        self.assertIn('opencode, Codex', output)

    def test_missing_house_rule_skill_is_reported_and_installed_one_is_not(self):
        self.install('tmp-skill', self.user / '.agents/skills')
        machine = self.home / 'rules'
        machine.mkdir(parents=True)
        (machine / 'build.md').write_text(
            'Use the `tmp-skill` skill when editing release notes.\n'
            'Use the `missing-skill` skill for screenshots.\n')
        project_rules = self.project / 'rules'
        project_rules.mkdir()
        (project_rules / 'verify.md').write_text(
            'Follow `.agents/skills/never-installed/SKILL.md` for journeys.\n'
            'Also `skills/relative-missing/SKILL.md`.\n')

        found = skills.missing(self.project)
        self.assertEqual([(item['where'], item['name'], item['line']) for item in found],
                         [('Project', 'never-installed', 1),
                          ('Project', 'relative-missing', 2),
                          ('machine', 'missing-skill', 2)])

        output = '\n'.join(skills.listing(self.project))
        missing_section = output.split('House rules naming a skill that is not installed:')[1]
        self.assertIn('missing-skill', missing_section)
        self.assertIn('never-installed', missing_section)
        self.assertNotIn('tmp-skill', missing_section)

    def test_glob_and_plain_folder_are_not_mistaken_for_skills(self):
        machine = self.home / 'rules'
        machine.mkdir(parents=True)
        (machine / 'build.md').write_text(
            'Read `.agents/skills/verify-*` first.\n'
            'Install skills into `~/.agents/skills`.\n')
        self.assertEqual(skills.missing(self.project), [])
        self.assertIn('(no house rule names a missing skill)',
                      '\n'.join(skills.listing(self.project)))

    def test_skills_command_prints_the_same_report(self):
        self.install('tmp-skill', self.user / '.agents/skills')
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = cli.main(['skills', '--project', 'unit'])
        self.assertEqual(code, 0)
        self.assertIn('~/.agents/skills/tmp-skill', buffer.getvalue())
        self.assertIn('opencode, Codex', buffer.getvalue())

    def test_every_worker_brief_carries_the_protocol_line(self):
        for name in ('build', 'fix', 'verify', 'evidence'):
            self.assertIn(PROTOCOL, (ROOT / 'briefs' / f'{name}.md').read_text(), name)
        (self.notes / 'intent.md').write_text('DONE CHECK')
        self.assertIn(PROTOCOL, build_brief(self.path))

    def test_help_rules_explains_the_four_ways(self):
        page = help_text('rules')
        self.assertIn('Using skills', page)
        for heading in ('Per task', 'Per Project', 'Per machine', 'Per role'):
            self.assertIn(heading, page)
        self.assertIn('~/.agents/skills', page)
        self.assertIn('does not install', page)
