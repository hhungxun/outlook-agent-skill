import json
import unittest
from pathlib import Path
from tests import test_cli as harness


class OrganisationTest(unittest.TestCase):
    setUp = harness.CliTest.setUp
    tearDown = harness.CliTest.tearDown
    call = harness.CliTest.call
    connect = harness.CliTest.connect

    def plan(self):
        self.connect()
        code, result = self.call('organise', 'plan', '--limit', '2')
        self.assertEqual(code, 0, result)
        path = result['plan']
        self.assertEqual(result['count'], 2)
        for mid, topic in [('one', 'Physics'), ('two', 'School Admin')]:
            code, result = self.call('organise', 'assign', path, '--topic', topic, '--message-id', mid)
            self.assertEqual(code, 0, result)
        return path

    def test_round_trip_preserves_messages_and_read_status(self):
        path = self.plan()
        self.assertEqual(self.api.moves, 0)
        code, result = self.call('organise', 'apply', path)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['verified'], 2)
        journal = result['journal']
        # A later user read-state change must survive undo.
        self.api.messages['one-moved']['isRead'] = True
        code, result = self.call('organise', 'undo', journal)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['restored'], 2)
        self.assertTrue(all(m['parentFolderId'] == 'inbox' for m in self.api.messages.values()))
        self.assertTrue(all(m['isRead'] for m in self.api.messages.values()))
        self.assertIn('Physics', self.api.folders.values())  # folders not deleted
        code, result = self.call('organise', 'undo', journal)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.api.moves, 4)

    def test_reconciles_lost_move_response_without_duplicate_move(self):
        path = self.plan()
        self.api.fail_after_move = True
        code, result = self.call('organise', 'apply', path)
        self.assertEqual(code, 2)
        self.assertEqual(self.api.moves, 1)
        code, result = self.call('organise', 'apply', path)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['verified'], 2)
        self.assertEqual(self.api.moves, 2)

    def test_stale_source_preflight_prevents_all_moves(self):
        path = self.plan()
        self.api.messages['two']['parentFolderId'] = 'sentitems'
        code, result = self.call('organise', 'apply', path)
        self.assertEqual(code, 2)
        self.assertEqual(self.api.moves, 0)

    def test_undo_does_not_overwrite_later_user_folder_change(self):
        path = self.plan()
        code, result = self.call('organise', 'apply', path)
        journal = result['journal']
        self.api.messages['one-moved']['parentFolderId'] = 'sentitems'
        code, result = self.call('organise', 'undo', journal)
        self.assertEqual(code, 2)
        self.assertEqual(self.api.moves, 2)
        self.assertEqual(self.api.messages['one-moved']['parentFolderId'], 'sentitems')

    def test_unassigned_plan_and_protected_destination_are_rejected(self):
        self.connect()
        code, result = self.call('organise', 'plan', '--limit', '2')
        path = result['plan']
        code, result = self.call('organise', 'apply', path)
        self.assertEqual(code, 2)
        self.assertEqual(self.api.moves, 0)
        code, result = self.call('organise', 'assign', path, '--topic', 'Deleted Items', '--message-id', 'one')
        self.assertEqual(code, 2)

    def test_duplicate_identity_reconciliation_stops_conservatively(self):
        path = self.plan()
        self.api.fail_after_move = True
        code, result = self.call('organise', 'apply', path)
        duplicate = dict(self.api.messages['one-moved'], id='duplicate')
        self.api.messages['duplicate'] = duplicate
        code, result = self.call('organise', 'apply', path)
        self.assertEqual(code, 2)
        self.assertEqual(self.api.moves, 1)


if __name__ == '__main__':
    unittest.main()
