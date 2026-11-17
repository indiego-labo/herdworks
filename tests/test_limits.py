import json
from unittest.mock import patch
from herdworks.limits import config, hold_reason
from herdworks.projects import new_task, add_project
from herdworks.runs import append_event
from herdworks.spawn import spawn
from tests.support import RunCase


class LimitsTests(RunCase):
    def configure(self, **values):
        (self.home / 'config.json').write_text(json.dumps(values))

    def active(self, path):
        append_event(path, dict(event='session', role='build', name='worker', address='t2'))

    def test_task_limit_releases_and_project_limit_is_clamped(self):
        self.configure(max_tasks_at_once=1)
        self.active(self.path)
        second, _ = new_task(self.project, self.brief)
        self.assertEqual(hold_reason(second, allocating=True), 'max_tasks_at_once')
        append_event(self.path, dict(event='stop'))
        self.assertIsNone(hold_reason(second, allocating=True))
        p = self.project / 'project.json'
        data = json.loads(p.read_text())
        data['max_tasks_at_once'] = 99
        p.write_text(json.dumps(data))
        self.active(self.path)
        self.assertEqual(hold_reason(second, allocating=True), 'max_tasks_at_once')
        self.configure(max_tasks_at_once=3)
        data['max_tasks_at_once'] = 1
        p.write_text(json.dumps(data))
        self.assertEqual(hold_reason(second, allocating=True), 'Project max_tasks_at_once')

    def test_worker_limit_releases_when_session_ends(self):
        self.configure(max_worker_sessions=1)
        self.active(self.path)
        with patch('herdworks.hc.get', return_value={'state': 'live'}):
            self.assertEqual(hold_reason(self.path), 'max_worker_sessions')
        with patch('herdworks.hc.get', return_value={'state': 'exited'}):
            self.assertIsNone(hold_reason(self.path))

    def test_worktree_limit_releases_when_removed(self):
        self.configure(max_worktrees=1)
        wt = self.path / 'build-1/wt'
        wt.mkdir(parents=True)
        self.assertEqual(hold_reason(self.path), 'max_worktrees')
        wt.rmdir()
        self.assertIsNone(hold_reason(self.path))

    def test_worktree_limit_ignores_tasks_waiting_on_a_person(self):
        self.configure(max_worktrees=1)
        (self.path / 'build-1/wt').mkdir(parents=True)
        second, _ = new_task(self.project, self.brief)
        self.assertEqual(hold_reason(second), 'max_worktrees')
        append_event(self.path, dict(event='pr', url='https://github.com/o/r/pull/1', commit='x'))
        self.assertIsNone(hold_reason(second))

    def test_disk_floor_prevents_spawn_and_queues_allocation(self):
        with patch('herdworks.limits.shutil.disk_usage') as usage:
            usage.return_value.free = 1024 ** 3
            second, _ = new_task(self.project, self.brief)
            self.assertEqual(hold_reason(second), 'min_free_disk_gb')
            with patch('herdworks.hc.launch') as launch:
                with self.assertRaisesRegex(ValueError, 'min_free_disk_gb'):
                    spawn(second)
                launch.assert_not_called()
            usage.return_value.free = 10 * 1024 ** 3
            self.assertIsNone(hold_reason(second))

    def test_session_budget_holds_only_that_task(self):
        self.configure(max_sessions_per_task=1)
        self.active(self.path)
        with patch('herdworks.hc.get', return_value={'state': 'exited'}):
            self.assertIn('max_sessions_per_task', hold_reason(self.path))
            second, _ = new_task(self.project, self.brief)
            self.assertIsNone(hold_reason(second))

    def test_config_rejects_unreadable_or_invalid_content(self):
        self.assertEqual(config(self.home)['max_tasks_at_once'], 2)
        for value in ('{', '[]', '{"max_worktrees": true}', '{"max_tasks_at_once": 0}'):
            (self.home / 'config.json').write_text(value)
            with self.assertRaises((ValueError, OSError)):
                config(self.home)

    def test_concurrent_starts_share_one_machine_admission_lock(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from herdworks.runs import events
        self.configure(max_tasks_at_once=1)
        second, _ = new_task(self.project, self.brief)
        for path in (self.path, second):
            (self.project / 'coordinator/tasks' / path.name / 'intent.md').write_text('Done check')
        entered = threading.Event()
        release = threading.Event()
        def launch(**kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return dict(address='started', name=kwargs['name'], first_message={'sent': True})
        def start(path):
            try:
                return spawn(path)
            except ValueError as error:
                return str(error)
        with patch('herdworks.hc.launch', side_effect=launch), patch('herdworks.hc.get', return_value={'state': 'missing'}):
            with ThreadPoolExecutor(2) as pool:
                first = pool.submit(start, self.path)
                self.assertTrue(entered.wait(5))
                other = pool.submit(start, second)
                release.set()
                self.assertIsInstance(first.result(10), dict)
                self.assertIn('max_tasks_at_once', other.result(10))
        self.assertEqual(sum(e.get('event') == 'session' for p in (self.path, second) for e in events(p)), 1)
        self.assertFalse((second / 'build-1').exists())

    def test_uncertain_launch_reserves_capacity_until_reconciled(self):
        self.configure(max_worker_sessions=1)
        second, _ = new_task(self.project, self.brief)
        marker = self.path / '.setup-build-1.json'
        marker.write_text(json.dumps(dict(launching=True, metadata=dict(name='uncertain'))))
        self.assertEqual(hold_reason(second), 'max_worker_sessions')
        marker.unlink()
        self.assertIsNone(hold_reason(second))

    def test_machine_task_limit_spans_projects(self):
        self.configure(max_tasks_at_once=1)
        other = add_project('other', self.repo, prefix='OT')
        self.active(self.path)
        task, _ = new_task(other, self.brief)
        self.assertEqual(hold_reason(task, allocating=True), 'max_tasks_at_once')
        append_event(self.path, dict(event='stop'))
        with patch('herdworks.hc.get', return_value={'state': 'finished'}):
            self.assertIsNone(hold_reason(task, allocating=True))
