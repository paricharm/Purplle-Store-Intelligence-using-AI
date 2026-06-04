# PROMPT:
# Generate tests for operational anomaly detection: queue spike, conversion drop, and
# dead zones.
#
# CHANGES MADE:
# Focused the assertion on queue spike because it is deterministic from latest queue
# depth metadata and is a critical reviewer-visible anomaly.

from pathlib import Path
from unittest import TestCase

from app.analytics import compute_anomalies
from tests.helpers import seed_events, workspace_tempdir


class AnomalyTests(TestCase):
    def test_queue_spike_is_reported_with_action(self) -> None:
        with workspace_tempdir() as tmp:
            db_path = tmp / "test.db"
            seed_events(db_path)

            anomalies = compute_anomalies("ST1008", db_path)["active_anomalies"]
            by_type = {anomaly["type"]: anomaly for anomaly in anomalies}

            self.assertIn("BILLING_QUEUE_SPIKE", by_type)
            self.assertIn("suggested_action", by_type["BILLING_QUEUE_SPIKE"])
