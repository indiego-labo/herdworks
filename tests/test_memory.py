from herdworks import memory
from herdworks.projects import new_task
from herdworks.spawn import build_brief, build_verify_brief
from tests.support import RunCase


class MemoryTests(RunCase):
    def test_add_indexes_and_next_task_carries_but_own_verifier_is_blind(self):
        file = memory.add(self.project, 'HE-1', 'Tests', 'python3 -m unittest')
        self.assertIn(file.name, (self.project / 'memory/MEMORY.md').read_text())
        self.assertIn('python3 -m unittest', memory.brief(self.path, 'build'))
        self.assertNotIn('python3 -m unittest', memory.brief(self.path, 'verify'))
        self.assertNotIn('python3 -m unittest', memory.brief(self.path, 'evidence'))
        second, _ = new_task(self.project, self.brief)
        self.assertIn('python3 -m unittest', memory.brief(second, 'build'))
        self.assertIn('python3 -m unittest', memory.brief(second, 'verify'))

    def test_direct_writes_and_edits_do_not_leak_into_own_verifier(self):
        file = self.project / 'memory/direct.md'
        file.write_text('Task: HE-1\nBUILDER-SAYS-IT-WORKS')
        self.assertNotIn('BUILDER-SAYS-IT-WORKS', memory.brief(self.path, 'verify'))
        self.assertIn('BUILDER-SAYS-IT-WORKS', memory.brief(self.path, 'build'))
        second, _ = new_task(self.project, self.brief)
        file.write_text('Task: HE-2\nNEW-CLAIM')
        self.assertNotIn('NEW-CLAIM', memory.brief(second, 'verify'))

    def test_verifier_cutoff_excludes_other_concurrent_task_memory(self):
        second, _ = new_task(self.project, self.brief)
        memory.add(self.project, second.name, 'Concurrent', 'OTHER TASK CLAIM')
        self.assertNotIn('OTHER TASK CLAIM', memory.brief(self.path, 'verify'))

    def test_direct_memory_requires_task_provenance(self):
        file = self.project / 'memory/direct.md'
        file.write_text('unattributed')
        with self.assertRaisesRegex(ValueError, 'Task: TASK_ID'):
            memory.read(self.project)
        file.write_text('Task: HE-1\nReusable command')
        self.assertIn('Reusable command', memory.read(self.project))

    def test_spawn_writes_index_into_actual_builder_packet(self):
        from unittest.mock import patch
        from herdworks.spawn import spawn
        memory.add(self.project, 'HE-1', 'Test command', 'python3 -m unittest')
        (self.notes / 'intent.md').write_text('CLI done check')
        with patch('herdworks.hc.launch', return_value=dict(address='t2', first_message=dict(sent=True))):
            spawn(self.path)
        packet = (self.path / 'build-1/brief.md').read_text()
        self.assertIn('# Project memory', packet)
        self.assertIn('python3 -m unittest', packet)

    def test_builder_writable_index_cannot_backdate_same_task_memory(self):
        import json
        from herdworks.runs import read_task
        memory.add(self.project, 'HE-1', 'Marker', 'BUILDER-SAYS-IT-WORKS')
        index = self.project / 'memory/index.json'
        entries = json.loads(index.read_text())
        for entry in entries.values():
            entry['added_at'] = read_task(self.path)['created_at'] - 100
            entry['task'] = 'HE-999'
        index.write_text(json.dumps(entries))
        self.assertNotIn('BUILDER-SAYS-IT-WORKS', memory.brief(self.path, 'verify'))
        self.assertNotIn('BUILDER-SAYS-IT-WORKS', memory.brief(self.path, 'evidence'))
