import json
import unittest
from unittest.mock import patch
from automation import cron_tools


class CronToolsTests(unittest.TestCase):
    def test_setup_cannot_dispatch_or_merge(self):
        state = cron_tools.status()
        self.assertFalse(state['dispatch_available'])
        self.assertFalse(state['auto_merge'])
        self.assertEqual(state['mode'], 'paused-setup')

    def test_monitor_has_stable_order_and_no_clock(self):
        responses = [
            [{'number': 8, 'title': 'later'}, {'number': 2, 'title': 'first'}],
            [{'number': 3, 'headRefOid': 'abc'}],
            {'sha': 'current-main'},
        ]
        with patch.object(cron_tools, 'gh_json', side_effect=responses):
            data = cron_tools.monitor()
        self.assertEqual([x['number'] for x in data['issues']], [2, 8])
        self.assertNotIn('timestamp', json.dumps(data))
        self.assertEqual(data['repo'], 'Sukhraj1000/closegraph')
        self.assertFalse(data['dispatch_available'])
        self.assertEqual(data['base_sha'], 'current-main')

    def test_github_failure_is_not_empty_success(self):
        with patch.object(cron_tools, 'gh_json', side_effect=RuntimeError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                cron_tools.monitor()


if __name__ == '__main__':
    unittest.main()
