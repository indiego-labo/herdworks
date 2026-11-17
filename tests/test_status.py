import contextlib
import io
from unittest.mock import patch
from herdworks.cli import main
from herdworks.projects import add_project
from herdworks.runs import append_event
from tests.support import RunCase


class StatusTests(RunCase):
    def test_tree_single_and_all_shows_live_roles_agent_quiet_attach(self):
        add_project('other', self.repo, prefix='OT')
        append_event(self.path, dict(event='session', address='t2', name='hw-unit-he-1-build-1',
                                     role='build', agent='opencode', folder='build-1', started_at=1000,
                                     stuck_after_minutes=60))
        append_event(self.path, dict(event='session', address='t3', name='old-worker',
                                     role='verify', agent='codex', folder='verify-1', started_at=1000,
                                     stuck_after_minutes=60))
        def get(name):
            return dict(state='exited' if name == 't3' else 'live', status=dict(state='idle'), status_ms=1000000)
        with patch('herdworks.hc.get', side_effect=get), patch('herdworks.status.time.time', return_value=1120), patch('herdworks.status.newest_file', return_value=0):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['status', 'unit']), 0)
            text = output.getvalue()
            self.assertIn('Project unit\n|-- coordinator', text)
            self.assertIn('HE-1 in progress', text)
            self.assertIn('build agent=opencode idle quiet=2.0m hc attach hw-unit-he-1-build-1', text)
            self.assertIn('hc attach hw-unit-coord', text)
            self.assertNotIn('old-worker', text)
            self.assertNotIn('Project other', text)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['status']), 0)
            self.assertIn('Project other', output.getvalue())
            append_event(self.path, dict(event='closed'))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['status']), 0)
            self.assertNotIn('HE-1', output.getvalue())
