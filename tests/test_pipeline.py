# PROMPT:
# Generate tests proving the suggested challenge skeleton files are implemented and
# connected to the production code.
#
# CHANGES MADE:
# Focused the assertions on compatibility entrypoints rather than duplicating the
# existing behavior tests in test_pipeline_events.py and test_runtime_helpers.py.

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

from app import anomalies, funnel, health, ingestion, metrics
from app.config import settings
from app.db import EventDB, get_db
from app.models import IngestRequest, StoreEvent
from app.storage import init_db
from pipeline.emit import build_event
from pipeline.pos_correlator import converted_visitor_ids, correlate_file
from tests.helpers import seed_events, workspace_tempdir


class PipelineSkeletonTests(TestCase):
    def test_expected_pipeline_and_app_entrypoints_exist(self) -> None:
        expected = [
            "pipeline/detect.py",
            "pipeline/tracker.py",
            "pipeline/emit.py",
            "pipeline/pos_correlator.py",
            "pipeline/run.sh",
            "app/main.py",
            "app/models.py",
            "app/db.py",
            "app/ingestion.py",
            "app/metrics.py",
            "app/funnel.py",
            "app/anomalies.py",
            "app/health.py",
            "dashboard/tui.py",
            "docs/DESIGN.md",
            "docs/CHOICES.md",
        ]
        for path in expected:
            self.assertTrue(Path(path).exists(), path)

    def test_models_and_pos_correlation_use_required_schema(self) -> None:
        event = build_event(
            store_id="STORE_BLR_002",
            camera_id="CAM_5",
            visitor_id="VIS_PIPE_001",
            event_type="BILLING_QUEUE_JOIN",
            timestamp=datetime(2026, 4, 10, 11, 24, tzinfo=UTC),
            zone_id="BILLING",
            metadata={"queue_depth": 3, "session_seq": 1},
        )
        request = IngestRequest(events=[StoreEvent.model_validate(event)])
        self.assertEqual(len(request.events), 1)
        self.assertEqual(EventDB().dedup_column, "event_id")

        converted = converted_visitor_ids(
            [json.loads(json.dumps(event))],
            [
                {
                    "store_id": "STORE_BLR_002",
                    "transaction_id": "TXN_1",
                    "timestamp": "2026-04-10T11:25:00Z",
                    "basket_value_inr": 500.0,
                }
            ],
        )
        self.assertEqual(converted, {"VIS_PIPE_001"})

    def test_skeleton_api_modules_delegate_to_real_analytics(self) -> None:
        with workspace_tempdir() as tmp:
            original_db_path = settings.db_path
            object.__setattr__(settings, "db_path", tmp / "skeleton.db")
            try:
                seed_events(settings.db_path)
                self.assertEqual(metrics.get_metrics("ST1008")["unique_visitors"], 3)
                self.assertEqual(funnel.get_funnel("ST1008")["unit"], "session")
                self.assertIn("active_anomalies", anomalies.get_anomalies("ST1008"))
                self.assertEqual(health.get_health().database, "ok")
                self.assertEqual(health.service_health().status, "ok")
                with get_db(settings.db_path) as conn:
                    row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
                    self.assertEqual(row[0], 11)
            finally:
                object.__setattr__(settings, "db_path", original_db_path)

    def test_skeleton_ingestion_and_pos_file_correlation(self) -> None:
        with workspace_tempdir() as tmp:
            original_db_path = settings.db_path
            object.__setattr__(settings, "db_path", tmp / "ingest.db")
            try:
                init_db(settings.db_path)
                event = build_event(
                    store_id="STORE_BLR_002",
                    camera_id="CAM_5",
                    visitor_id="VIS_PIPE_002",
                    event_type="BILLING_QUEUE_JOIN",
                    timestamp=datetime(2026, 4, 10, 11, 24, tzinfo=UTC),
                    zone_id="BILLING",
                    metadata={"queue_depth": 2, "session_seq": 1},
                )
                response = ingestion.ingest(IngestRequest(events=[StoreEvent.model_validate(event)]))
                self.assertEqual(response.accepted, 1)
                payload_response = ingestion.ingest_payload({"events": [event, {"bad": "event"}]})
                self.assertEqual(payload_response.duplicates, 1)
                self.assertEqual(payload_response.rejected, 1)

                events_path = tmp / "events.jsonl"
                output_path = tmp / "correlated.jsonl"
                pos_path = tmp / "pos.csv"
                events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
                pos_path.write_text(
                    "invoice_number,store_id,total_amount,order_date,order_time\n"
                    "INV1,STORE_BLR_002,100,10-04-2026,16:55:00\n",
                    encoding="utf-8",
                )
                result = correlate_file(events_path, pos_path, output_path)
                self.assertEqual(result["converted_visitors"], 1)
                self.assertTrue(output_path.exists())
            finally:
                object.__setattr__(settings, "db_path", original_db_path)
