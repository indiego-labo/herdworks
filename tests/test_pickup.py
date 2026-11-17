from unittest.mock import patch
from herdworks.pickup import stop
from herdworks.runs import derive_status
from tests.support import RunCase


class StopTests(RunCase):
    def test_stop_only_ends_this_tasks_workers(self):
        sessions = [dict(address=n) for n in ('worker', 'coordinator', 'foreign')]
        def get(address):
            labels = {'worker': 'unit:HE-1', 'coordinator': 'project:unit', 'foreign': 'other:HE-1'}
            return dict(address=address, name=address, state='live', labels=dict(hw=labels[address]))
        with patch('herdworks.hc.sessions', return_value=sessions), patch('herdworks.hc.get', side_effect=get), patch('herdworks.hc.call') as call:
            self.assertEqual(stop(self.path), ['worker'])
            call.assert_called_once_with('kill', 'worker')
        self.assertEqual(derive_status(self.path), 'stopped')
