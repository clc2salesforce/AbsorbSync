"""
Tests to verify that the CSV status column is updated after each successful API call,
not once after all updates complete. No temp files are used; all rows remain in the
original CSV at all times.
"""

import csv
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from absorb_sync import sync_external_ids


def create_test_csv(csv_path, rows):
    """Helper to create a test CSV file with user data rows."""
    fieldnames = ['Status', 'id', 'username', 'externalId', 'current_customFields_decimal1', 'user_data_json']
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_csv_rows(csv_path):
    """Helper to read all rows from a CSV file."""
    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return list(reader)


def make_user_row(user_id, username, external_id, current_value='', status='Retrieved'):
    """Helper to create a user row dict for the test CSV."""
    user_data = {
        'id': user_id,
        'username': username,
        'externalId': external_id,
        'customFields': {'decimal1': float(current_value) if current_value else None}
    }
    return {
        'Status': status,
        'id': user_id,
        'username': username,
        'externalId': external_id,
        'current_customFields_decimal1': current_value,
        'user_data_json': json.dumps(user_data)
    }


class TestCsvStatusUpdateAfterEachCall(unittest.TestCase):
    """Verify that the status column in the CSV is updated after each API call."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.csv_path = os.path.join(self.test_dir, 'test_users.csv')
        self.mock_client = MagicMock()
        self.mock_client.update_user = MagicMock(return_value=True)

    def tearDown(self):
        for f in os.listdir(self.test_dir):
            os.remove(os.path.join(self.test_dir, f))
        os.rmdir(self.test_dir)

    @patch('builtins.input', return_value='yes')
    def test_csv_updated_after_each_call_with_all_rows(self, mock_input):
        """
        Verify the CSV always contains ALL rows and is updated after each API call.
        After each update_user call, the CSV should have all 3 rows on disk.
        """
        rows = [
            make_user_row('id1', 'user1', '100'),
            make_user_row('id2', 'user2', '200'),
            make_user_row('id3', 'user3', '300'),
        ]
        create_test_csv(self.csv_path, rows)

        csv_snapshots = []

        def capture_csv_on_update(user_data, source_value, destination_field):
            """Side effect: read the CSV from disk each time update_user is called."""
            csv_snapshots.append(read_csv_rows(self.csv_path))
            return True

        self.mock_client.update_user.side_effect = capture_csv_on_update

        sync_external_ids(
            self.mock_client,
            dry_run=False,
            csv_file=self.csv_path,
            use_existing_file=True,
            destination_field='customFields.decimal1',
            source_field='externalId',
        )

        # There should be 3 API calls (one per user)
        self.assertEqual(len(csv_snapshots), 3)

        # Each snapshot is taken during update_user, BEFORE _save_csv writes this
        # row's updated status. But the previous rows' statuses have been saved.
        # Critically, ALL 3 rows are always present in the CSV.
        for i, snapshot in enumerate(csv_snapshots):
            self.assertEqual(len(snapshot), 3,
                             f"All 3 rows must always be in the CSV (snapshot {i})")

        # In the snapshot taken during the 2nd API call, the 1st row should
        # already have 'Success' status from the previous _save_csv call.
        self.assertEqual(csv_snapshots[1][0]['Status'], 'Success')

        # In the snapshot taken during the 3rd API call, the first 2 rows
        # should have 'Success' status.
        self.assertEqual(csv_snapshots[2][0]['Status'], 'Success')
        self.assertEqual(csv_snapshots[2][1]['Status'], 'Success')

    @patch('builtins.input', return_value='yes')
    def test_csv_has_all_statuses_after_completion(self, mock_input):
        """Verify all rows have correct status after sync completes."""
        rows = [
            make_user_row('id1', 'user1', '100'),
            make_user_row('id2', 'user2', '200'),
        ]
        create_test_csv(self.csv_path, rows)

        self.mock_client.update_user.return_value = True

        success, errors, skipped = sync_external_ids(
            self.mock_client,
            dry_run=False,
            csv_file=self.csv_path,
            use_existing_file=True,
            destination_field='customFields.decimal1',
            source_field='externalId',
        )

        self.assertEqual(success, 2)
        self.assertEqual(errors, 0)

        final_rows = read_csv_rows(self.csv_path)
        self.assertEqual(len(final_rows), 2)
        self.assertEqual(final_rows[0]['Status'], 'Success')
        self.assertEqual(final_rows[1]['Status'], 'Success')

    @patch('builtins.input', return_value='yes')
    def test_csv_failure_status_written_immediately(self, mock_input):
        """Verify failure status is also written to the CSV immediately."""
        rows = [
            make_user_row('id1', 'user1', '100'),
            make_user_row('id2', 'user2', '200'),
        ]
        create_test_csv(self.csv_path, rows)

        self.mock_client.update_user.side_effect = [True, False]

        success, errors, skipped = sync_external_ids(
            self.mock_client,
            dry_run=False,
            csv_file=self.csv_path,
            use_existing_file=True,
            destination_field='customFields.decimal1',
            source_field='externalId',
        )

        self.assertEqual(success, 1)
        self.assertEqual(errors, 1)

        final_rows = read_csv_rows(self.csv_path)
        self.assertEqual(len(final_rows), 2)
        self.assertEqual(final_rows[0]['Status'], 'Success')
        self.assertEqual(final_rows[1]['Status'], 'Failure')

    @patch('builtins.input', return_value='yes')
    def test_dry_run_does_not_modify_original(self, mock_input):
        """In dry-run mode, the original CSV should not be modified."""
        rows = [
            make_user_row('id1', 'user1', '100'),
        ]
        create_test_csv(self.csv_path, rows)

        original_rows = read_csv_rows(self.csv_path)

        sync_external_ids(
            self.mock_client,
            dry_run=True,
            csv_file=self.csv_path,
            use_existing_file=True,
            destination_field='customFields.decimal1',
            source_field='externalId',
        )

        # Original CSV should be completely unchanged in dry-run mode
        after_rows = read_csv_rows(self.csv_path)
        self.assertEqual(original_rows, after_rows)

    @patch('builtins.input', return_value='yes')
    def test_no_temp_files_created(self, mock_input):
        """No temp files should be created during processing."""
        rows = [
            make_user_row('id1', 'user1', '100'),
        ]
        create_test_csv(self.csv_path, rows)

        self.mock_client.update_user.return_value = True

        sync_external_ids(
            self.mock_client,
            dry_run=False,
            csv_file=self.csv_path,
            use_existing_file=True,
            destination_field='customFields.decimal1',
            source_field='externalId',
        )

        remaining_files = os.listdir(self.test_dir)
        tmp_files = [f for f in remaining_files if f.endswith('.tmp')]
        self.assertEqual(len(tmp_files), 0, f"No temp files should exist, found: {tmp_files}")

    @patch('builtins.input', return_value='yes')
    def test_all_rows_preserved_on_error(self, mock_input):
        """If an API call raises an exception, all rows remain in the CSV."""
        rows = [
            make_user_row('id1', 'user1', '100'),
            make_user_row('id2', 'user2', '200'),
            make_user_row('id3', 'user3', '300'),
        ]
        create_test_csv(self.csv_path, rows)

        # First call succeeds, second raises exception
        self.mock_client.update_user.side_effect = [True, Exception("API connection lost")]

        with self.assertRaises(Exception):
            sync_external_ids(
                self.mock_client,
                dry_run=False,
                csv_file=self.csv_path,
                use_existing_file=True,
                destination_field='customFields.decimal1',
                source_field='externalId',
            )

        # ALL 3 rows must still be in the CSV
        final_rows = read_csv_rows(self.csv_path)
        self.assertEqual(len(final_rows), 3, "All rows must be preserved after a crash")
        # The first row was successfully processed before the crash
        self.assertEqual(final_rows[0]['Status'], 'Success')
        # The remaining rows keep their original status
        self.assertEqual(final_rows[1]['Status'], 'Retrieved')
        self.assertEqual(final_rows[2]['Status'], 'Retrieved')

    @patch('builtins.input', return_value='yes')
    def test_resumability_skips_already_processed(self, mock_input):
        """When resuming with --file, already-processed rows are skipped."""
        rows = [
            make_user_row('id1', 'user1', '100', status='Success'),
            make_user_row('id2', 'user2', '200', status='Failure'),
            make_user_row('id3', 'user3', '300', status='Retrieved'),
        ]
        create_test_csv(self.csv_path, rows)

        self.mock_client.update_user.return_value = True

        success, errors, skipped = sync_external_ids(
            self.mock_client,
            dry_run=False,
            csv_file=self.csv_path,
            use_existing_file=True,
            destination_field='customFields.decimal1',
            source_field='externalId',
        )

        # Only the 3rd row (Retrieved) should have been processed
        self.assertEqual(self.mock_client.update_user.call_count, 1)
        self.assertEqual(success, 1)
        self.assertEqual(errors, 0)

        final_rows = read_csv_rows(self.csv_path)
        self.assertEqual(len(final_rows), 3)
        self.assertEqual(final_rows[0]['Status'], 'Success')   # unchanged
        self.assertEqual(final_rows[1]['Status'], 'Failure')   # unchanged
        self.assertEqual(final_rows[2]['Status'], 'Success')   # newly processed


if __name__ == '__main__':
    unittest.main()
