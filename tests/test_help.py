import os
from unittest.mock import patch
from herdworks.help import TOPICS, next_step, text
from tests.support import RunCase


class HelpTests(RunCase):
    def test_every_topic_prints_and_agent_guide_has_no_front_matter(self):
        for topic in TOPICS:
            self.assertTrue(text(topic).strip(), topic)
        self.assertTrue(text('agent').startswith('# Herdworks as your Bot'))
        with self.assertRaises(ValueError):
            text('nonsense')

    def test_next_step_follows_the_machine_state(self):
        self.assertIn('Your Projects: unit', next_step())
        self.assertIn('hw run -p unit', text())
        with patch.dict(os.environ, HW_HOME=str(self.root / 'empty')):
            self.assertIn('choose a model', next_step())
            (self.root / 'empty').mkdir()
            (self.root / 'empty/config.json').write_text('{}')
            self.assertIn('choose a model', next_step())
            (self.root / 'empty/config.json').write_text('{"agents": {}}')
            self.assertIn('choose a model', next_step())
            (self.root / 'empty/config.json').write_text(
                '{"agents": {"builder": {"agent": "codex"}}, "max_tasks_at_once": 1}')
            self.assertIn('add your first Project', next_step())
