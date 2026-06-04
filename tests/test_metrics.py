# PROMPT:
# Create tests for retail store metrics. Include staff exclusion, conversion rate,
# average dwell by zone, queue depth, abandonment, empty stores, and zero purchases.
#
# CHANGES MADE:
# Added an explicit POS transaction inside the 5-minute billing window and separate
# empty-store assertions to protect the zero/null edge cases from the problem statement.

from pathlib import Path
from unittest import TestCase

from app.analytics import compute_metrics
from app.storage import init_db
from tests.helpers import seed_events, workspace_tempdir


class MetricsTests(TestCase):
    def test_metrics_exclude_staff_and_compute_conversion(self) -> None:
        with workspace_tempdir() as tmp:
            db_path = tmp / "test.db"
            seed_events(db_path)

            metrics = compute_metrics("ST1008", db_path)

            self.assertEqual(metrics["unique_visitors"], 3)
            self.assertEqual(metrics["converted_visitors"], 1)
            self.assertEqual(metrics["conversion_rate"], 0.3333)
            self.assertEqual(metrics["queue_depth"], 6)
            self.assertEqual(metrics["abandonment_rate"], 0.5)
            self.assertEqual(metrics["avg_dwell_per_zone"][0]["zone_id"], "SKINCARE")

    def test_empty_store_returns_zero_values(self) -> None:
        with workspace_tempdir() as tmp:
            db_path = tmp / "test.db"
            init_db(db_path)

            metrics = compute_metrics("UNKNOWN", db_path)

            self.assertEqual(metrics["unique_visitors"], 0)
            self.assertEqual(metrics["conversion_rate"], 0)
            self.assertEqual(metrics["avg_dwell_per_zone"], [])
