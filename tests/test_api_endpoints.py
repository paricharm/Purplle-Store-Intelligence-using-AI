# PROMPT:
# Generate endpoint-level tests for the Store Intelligence API. Cover ingest partial
# success, idempotency, metrics/funnel/heatmap/anomalies/live responses, health, media,
# dashboard, video metadata, and graceful disabled-pipeline behavior.
#
# CHANGES MADE:
# Used a temporary SQLite database per test and restored global settings so the tests
# exercise the real FastAPI routes without touching the user's demo database.

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

from fastapi import HTTPException
from fastapi.responses import Response

from app.config import settings
from app.logging_config import request_logging_middleware
from app.main import (
    anomalies,
    camera_media,
    camera_video,
    dashboard,
    funnel,
    health,
    heatmap,
    ingest_events,
    live_snapshot,
    metrics,
    process_video,
    recent_events,
    root,
    video_job,
    videos,
)
from app.schemas import VideoProcessRequest
from app.storage import init_db, insert_pos_transactions
from pipeline.emit import build_event
from tests.helpers import workspace_tempdir


class ApiEndpointTests(TestCase):
    def _configure_temp_settings(self, tmp: Path) -> None:
        self._original_db_path = settings.db_path
        self._original_pos_path = settings.pos_csv_path
        self._original_cctv_path = settings.cctv_dir_path
        self._original_pipeline_flag = settings.enable_in_process_pipeline
        object.__setattr__(settings, "db_path", tmp / "api.db")
        object.__setattr__(settings, "pos_csv_path", tmp / "missing_pos.csv")
        object.__setattr__(settings, "cctv_dir_path", tmp / "videos")
        init_db(settings.db_path)
        insert_pos_transactions(
            [
                {
                    "transaction_id": "TXN_API_1",
                    "store_id": "STORE_BLR_002",
                    "timestamp": "2026-04-10T11:25:00Z",
                    "basket_value_inr": 999.0,
                }
            ],
            settings.db_path,
        )

    def tearDown(self) -> None:
        for name in (
            "_original_db_path",
            "_original_pos_path",
            "_original_cctv_path",
            "_original_pipeline_flag",
        ):
            if not hasattr(self, name):
                return
        object.__setattr__(settings, "db_path", self._original_db_path)
        object.__setattr__(settings, "pos_csv_path", self._original_pos_path)
        object.__setattr__(settings, "cctv_dir_path", self._original_cctv_path)
        object.__setattr__(
            settings,
            "enable_in_process_pipeline",
            self._original_pipeline_flag,
        )

    def test_ingest_and_analytics_routes(self) -> None:
        with workspace_tempdir() as tmp:
            self._configure_temp_settings(tmp)
            events = [
                build_event(
                    store_id="STORE_BLR_002",
                    camera_id="CAM_1",
                    visitor_id="VIS_API_001",
                    event_type="ENTRY",
                    timestamp=datetime(2026, 4, 10, 11, 20, tzinfo=UTC),
                    confidence=0.9,
                ),
                build_event(
                    store_id="STORE_BLR_002",
                    camera_id="CAM_5",
                    visitor_id="VIS_API_001",
                    event_type="BILLING_QUEUE_JOIN",
                    timestamp=datetime(2026, 4, 10, 11, 24, tzinfo=UTC),
                    zone_id="BILLING",
                    confidence=0.88,
                    metadata={"queue_depth": 7, "session_seq": 2},
                ),
                {
                    "event_id": "bad-confidence",
                    "store_id": "STORE_BLR_002",
                    "camera_id": "CAM_1",
                    "visitor_id": "VIS_BAD",
                    "event_type": "ENTRY",
                    "timestamp": "2026-04-10T11:20:00Z",
                    "dwell_ms": 0,
                    "confidence": 2.0,
                },
            ]

            request = SimpleNamespace(state=SimpleNamespace())
            response = asyncio.run(ingest_events(request, {"events": events}))
            self.assertEqual(response.accepted, 2)
            self.assertEqual(response.rejected, 1)

            duplicate = asyncio.run(ingest_events(SimpleNamespace(state=SimpleNamespace()), events[:2]))
            self.assertEqual(duplicate.duplicates, 2)

            self.assertEqual(asyncio.run(root())["dashboard"], "/dashboard")
            self.assertIn("Live Dashboard", asyncio.run(dashboard()))
            self.assertEqual(
                asyncio.run(metrics("STORE_BLR_002"))["unique_visitors"],
                1,
            )
            self.assertEqual(asyncio.run(funnel("STORE_BLR_002"))["unit"], "session")
            self.assertIn("zones", asyncio.run(heatmap("STORE_BLR_002")))
            self.assertIn("active_anomalies", asyncio.run(anomalies("STORE_BLR_002")))
            self.assertEqual(asyncio.run(recent_events("STORE_BLR_002", limit=1))["count"], 1)
            self.assertIn("recent_events", asyncio.run(live_snapshot("STORE_BLR_002")))
            self.assertLessEqual(len(asyncio.run(live_snapshot("STORE_BLR_002", limit=1000))["recent_events"]), 1000)
            self.assertEqual(asyncio.run(health()).database, "ok")

            fake_request = SimpleNamespace(
                headers={"x-trace-id": "trace-api-test"},
                state=SimpleNamespace(store_id="STORE_BLR_002", event_count=2),
                path_params={"id": "STORE_BLR_002"},
                url=SimpleNamespace(path="/events/ingest"),
            )

            async def call_next(_request: object) -> Response:
                return Response(status_code=200)

            logged_response = asyncio.run(request_logging_middleware(fake_request, call_next))
            self.assertEqual(logged_response.headers["x-trace-id"], "trace-api-test")

    def test_malformed_payload_video_and_media_errors_are_structured(self) -> None:
        with workspace_tempdir() as tmp:
            self._configure_temp_settings(tmp)
            object.__setattr__(settings, "enable_in_process_pipeline", False)

            with self.assertRaises(HTTPException) as invalid_payload:
                asyncio.run(ingest_events(SimpleNamespace(state=SimpleNamespace()), {"not_events": []}))
            self.assertEqual(invalid_payload.exception.status_code, 400)
            self.assertEqual(invalid_payload.exception.detail["error"], "INVALID_PAYLOAD")

            self.assertEqual(asyncio.run(camera_media())["cameras"][0]["available"], False)
            with self.assertRaises(HTTPException) as media_error:
                asyncio.run(camera_video("NOPE"))
            self.assertEqual(media_error.exception.status_code, 404)
            self.assertEqual(asyncio.run(videos())["exists"], False)
            with self.assertRaises(HTTPException) as disabled_pipeline:
                asyncio.run(
                    process_video(
                        VideoProcessRequest(
                            clip_start="2026-04-10T11:20:00Z",
                            video_path="CAM 1.mp4",
                        )
                    )
                )
            self.assertEqual(disabled_pipeline.exception.status_code, 503)
            with self.assertRaises(HTTPException) as missing_job:
                asyncio.run(video_job("missing"))
            self.assertEqual(missing_job.exception.status_code, 404)
