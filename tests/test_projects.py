import json
import os
from unittest.mock import patch
from herdworks.home import hw_home
from herdworks.projects import add_project, new_task, project_path, read_project, task_path
from herdworks.runs import read_task
from tests.support import RunCase


class ProjectTests(RunCase):
    def test_home_default_and_override(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(hw_home(), __import__('pathlib').Path.home() / '.herdworks')
        self.assertEqual(hw_home(), self.home)

    def test_project_folders_metadata_and_rejections(self):
        project = add_project('hello', self.repo)
        self.assertEqual(read_project(project), dict(name='hello', repo=str(self.repo), base_branch='main', prefix='HE',
                                                  remote='origin', grants={'push': False, 'draft-pr': False}))
        for folder in ('memory', 'tasks', 'coordinator', 'coordinator/outbox'):
            self.assertTrue((project / folder).is_dir())
        with self.assertRaisesRegex(ValueError, 'already exists'):
            add_project('hello', self.repo)
        for name in ('abcdefghijklm', '../escape', '', 'UPPER'):
            with self.assertRaises(ValueError):
                project_path(name)

    def test_task_ids_rise_and_notes_are_inside_coordinator(self):
        second, repeat = new_task(self.project, self.brief)
        self.assertFalse(repeat)
        self.assertEqual([self.path.name, second.name], ['HE-1', 'HE-2'])
        self.assertEqual(read_task(second)['branch'], 'hw/HE-2')
        self.assertTrue((self.project / 'coordinator/tasks/HE-2').is_dir())
        self.assertEqual((second / 'events.jsonl').read_text(), '')
        for value in ('HE-0', 'OTHER-1', '../escape'):
            with self.assertRaises(ValueError):
                task_path('unit', value)
        self.assertFalse((self.root / 'runs').exists())

    def test_replayed_message_reuses_task(self):
        (self.project / 'inbox.jsonl').write_text(json.dumps(dict(number=1, text='do this')) + '\n')
        first, repeat = new_task(self.project, message=1)
        again, repeat = new_task(self.project, message=1)
        self.assertEqual(again, first)
        self.assertTrue(repeat)
        self.assertEqual(first.name, 'HE-2')
        self.assertEqual((first / 'brief.md').read_text(), 'do this')

    def test_dirty_repository_does_not_allocate_task(self):
        (self.repo / 'pending').touch()
        with self.assertRaisesRegex(ValueError, 'clean'):
            new_task(self.project, self.brief)
        self.assertFalse((self.project / 'tasks/HE-2').exists())

    def test_incomplete_task_setup_is_not_counted_as_a_task(self):
        pending = self.project / 'tasks/.HE-2-pending'
        pending.mkdir()
        (pending / 'task.json').write_text('{}')
        second, _ = new_task(self.project, self.brief)
        self.assertEqual(second.name, 'HE-2')
        self.assertFalse(pending.exists())

    def test_task_ids_have_no_added_numeric_cap(self):
        self.assertEqual(task_path('unit', 'HE-1000000').name, 'HE-1000000')

    def test_interrupted_project_creation_is_hidden_and_retryable(self):
        from pathlib import Path
        write = Path.write_text
        seen = []
        def interrupt(path, *args, **kwargs):
            if path.name == 'project.json' and 'hello' in path.parent.name:
                seen.append(project_path('hello').exists())
                raise OSError('interrupted creation')
            return write(path, *args, **kwargs)
        with patch.object(Path, 'write_text', interrupt):
            with self.assertRaisesRegex(OSError, 'interrupted creation'):
                add_project('hello', self.repo)
        self.assertEqual(seen, [False])
        self.assertFalse(project_path('hello').exists())
        project = add_project('hello', self.repo)
        self.assertEqual(read_project(project)['name'], 'hello')
        self.assertTrue((project / 'coordinator/outbox').is_dir())
