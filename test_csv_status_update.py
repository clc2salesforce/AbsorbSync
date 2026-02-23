"""
Tests to verify that the CSV status column is updated after each successful API call,
not once after all updates complete.
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
        # Clean up test files
        for f in os.listdir(self.test_dir):
            os.remove(os.path.join(self.test_dir, f))
        os.rmdir(self.test_dir)

    @patch('builtins.input', return_value='yes')
    def test_csv_updated_incrementally_not_at_end(self, mock_input):
        """
        Verify the original CSV file is updated after each API call.
        We do this by having update_user check the CSV on disk after each call.
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

        # After 1st API call: CSV should already have the header written
        # (the 1st user's row hasn't been written yet when update_user is called,
        # but previous rows should be visible after their writes)
        # After the 2nd call, the 1st user's status should be in the CSV
        snapshot_after_2nd = csv_snapshots[1]
        self.assertTrue(len(snapshot_after_2nd) >= 1, "After 2nd API call, at least 1 row should be in CSV")
        self.assertEqual(snapshot_after_2nd[0]['Status'], 'Success',
                         "First user's status should be 'Success' after the 2nd API call")

        # After the 3rd call, both 1st and 2nd users should be in the CSV
        snapshot_after_3rd = csv_snapshots[2]
        self.assertTrue(len(snapshot_after_3rd) >= 2, "After 3rd API call, at least 2 rows should be in CSV")
        self.assertEqual(snapshot_after_3rd[0]['Status'], 'Success')
        self.assertEqual(snapshot_after_3rd[1]['Status'], 'Success')

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

        # Read final CSV
        final_rows = read_csv_rows(self.csv_path)
        self.assertEqual(len(final_rows), 2)
        self.assertEqual(final_rows[0]['Status'], 'Success')
        self.assertEqual(final_rows[1]['Status'], 'Success')

    @patch('builtins.input', return_value='yes')
    def test_csv_failure_status_written_immediately(self, mock_input):
        """Verify failure status is also written to the original CSV immediately."""
        rows = [
            make_user_row('id1', 'user1', '100'),
            make_user_row('id2', 'user2', '200'),
        ]
        create_test_csv(self.csv_path, rows)

        # First call succeeds, second fails
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

        # Read original content
        original_rows = read_csv_rows(self.csv_path)

        sync_external_ids(
            self.mock_client,
            dry_run=True,
            csv_file=self.csv_path,
            use_existing_file=True,
            destination_field='customFields.decimal1',
            source_field='externalId',
        )

        # Original CSV should be unchanged
        after_rows = read_csv_rows(self.csv_path)
        self.assertEqual(original_rows, after_rows)

    @patch('builtins.input', return_value='yes')
    def test_temp_file_cleaned_up_on_success(self, mock_input):
        """Temp file should be removed after successful completion."""
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

        # Only the CSV file should remain (no .tmp files)
        remaining_files = os.listdir(self.test_dir)
        tmp_files = [f for f in remaining_files if f.endswith('.tmp')]
        self.assertEqual(len(tmp_files), 0, f"Temp files should be cleaned up, found: {tmp_files}")

    @patch('builtins.input', return_value='yes')
    def test_temp_file_preserved_on_error(self, mock_input):
        """In non-dry-run mode, temp file should be preserved on error for recovery."""
        rows = [
            make_user_row('id1', 'user1', '100'),
        ]
        create_test_csv(self.csv_path, rows)

        # Make update_user raise an exception
        self.mock_client.update_user.side_effect = Exception("API connection lost")

        with self.assertRaises(Exception):
            sync_external_ids(
                self.mock_client,
                dry_run=False,
                csv_file=self.csv_path,
                use_existing_file=True,
                destination_field='customFields.decimal1',
                source_field='externalId',
            )

        # Temp file should be preserved as backup
        remaining_files = os.listdir(self.test_dir)
        tmp_files = [f for f in remaining_files if f.endswith('.tmp')]
        self.assertEqual(len(tmp_files), 1, "Temp backup file should be preserved on error")


if __name__ == '__main__':
    unittest.main()
