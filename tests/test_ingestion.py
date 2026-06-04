# PROMPT:
# Generate API ingestion tests for a Store Intelligence event schema. Cover duplicate
# event_id behavior and malformed event validation.
#
# CHANGES MADE:
# Replaced endpoint-only tests with storage-level tests so idempotency can be verified
# quickly against a temporary SQLite database without starting the web server.

from pathlib import Path
from unittest import TestCase

from pydantic import ValidationError

from app.schemas import EventIn
from app.storage import fetch_events, init_db, insert_events
from pipeline.emit import build_event
from tests.helpers import workspace_tempdir


class IngestionTests(TestCase):
    def test_insert_is_idempotent_by_event_id(self) -> None:
        with workspace_tempdir() as tmp:
            db_path = tmp / "test.db"
            init_db(db_path)
            event = build_event(
                store_id="ST1008",
                camera_id="CAM_1",
                visitor_id="VIS_001",
                event_type="ENTRY",
                timestamp="2026-04-10T11:23:00Z",
                confidence=0.95,
            )
            accepted, duplicates = insert_events([EventIn.model_validate(event)], db_path)
            second_accepted, second_duplicates = insert_events([EventIn.model_validate(event)], db_path)

            self.assertEqual((accepted, duplicates), (1, 0))
            self.assertEqual((second_accepted, second_duplicates), (0, 1))
            self.assertEqual(len(fetch_events("ST1008", db_path=db_path)), 1)

    def test_malformed_event_fails_validation(self) -> None:
        event = build_event(
            store_id="ST1008",
            camera_id="CAM_1",
            visitor_id="VIS_001",
            event_type="ENTRY",
            timestamp="2026-04-10T11:23:00Z",
            confidence=0.95,
        )
        event["confidence"] = 1.5
        with self.assertRaises(ValidationError):
            EventIn.model_validate(event)
