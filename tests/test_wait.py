import threading
import time
from herdworks.talk import latest, wait
from tests.support import RunCase


class WaitTests(RunCase):
    def reply(self, number, kind='REPLY'):
        (self.project / f'coordinator/outbox/{number:06d}.md').write_text(f'{kind}\nTask: HE-1\n')

    def test_returns_only_replies_after_the_newest_at_call_time(self):
        self.reply(1)
        self.assertEqual(latest(self.project), 1)
        later = threading.Timer(0.3, self.reply, args=(2, 'QUESTION'))
        later.start()
        self.addCleanup(later.cancel)
        replies = wait(self.project, timeout=5, interval=0.05)
        self.assertEqual([number for number, _ in replies], [2])
        self.assertTrue(replies[0][1].startswith('QUESTION'))

    def test_since_catches_a_reply_written_before_the_call(self):
        self.reply(1)
        self.assertEqual([n for n, _ in wait(self.project, since=0, timeout=1, interval=0.05)], [1])

    def test_timeout_returns_nothing(self):
        started = time.monotonic()
        self.assertEqual(wait(self.project, timeout=0.2, interval=0.05), [])
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(latest(self.project), 0)
