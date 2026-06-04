# PROMPT:
# Generate tests for the health check's last-event timestamp and stale feed data source.
#
# CHANGES MADE:
# Kept this at the storage layer so it remains stable without depending on wall-clock
# health endpoint behavior.

from pathlib import Path
from unittest import TestCase

from app.storage import latest_event_timestamp_by_store
from tests.helpers import seed_events, workspace_tempdir


class HealthDataTests(TestCase):
    def test_latest_event_timestamp_is_grouped_by_store(self) -> None:
        with workspace_tempdir() as tmp:
            db_path = tmp / "test.db"
            seed_events(db_path)

            latest = latest_event_timestamp_by_store(db_path)

            self.assertEqual(latest["ST1008"], "2026-04-10T11:28:10Z")
