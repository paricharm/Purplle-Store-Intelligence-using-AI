# PROMPT:
# Generate tests for the sample detection pipeline output. Validate that JSONL events
# follow the required schema and include the challenge's re-entry/staff examples.
#
# CHANGES MADE:
# Added checks for REENTRY and staff flags so the sample pipeline demonstrates key edge
# cases even before a trained CV model is uploaded.

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

from app.schemas import EventIn
from pipeline.detect import TrackState, VideoProcessor
from pipeline.enrich_events import add_billing_abandonment_events
from pipeline.emit import build_event
from pipeline.generate_sample_events import generate_sample_events
from pipeline.tracker import Detection
from tests.helpers import workspace_tempdir


class PipelineEventTests(TestCase):
    def test_sample_pipeline_writes_schema_valid_events(self) -> None:
        with workspace_tempdir() as tmp:
            output = tmp / "events.jsonl"
            count = generate_sample_events(output)
            events = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(count, len(events))
            validated = [EventIn.model_validate(event) for event in events]
            self.assertTrue(any(event.event_type == "REENTRY" for event in validated))
            self.assertTrue(any(event.is_staff for event in validated))

    def test_entry_line_reentry_emits_reentry_not_second_entry(self) -> None:
        processor = VideoProcessor(
            video_path=Path("unused.mp4"),
            output_path=Path("unused.jsonl"),
            layout_path=Path("config/store_layout.json"),
            store_id="ST1008",
            camera_id="CAM_3",
            model_path=Path("models/best.pt"),
            clip_start=datetime(2026, 4, 10, 11, 20, tzinfo=UTC),
        )
        processor.states[1] = TrackState(
            visitor_id="VIS_CAM_3_00001",
            has_entered=True,
            has_exited=True,
            last_x_norm=0.4,
            last_y_norm=0.5,
        )

        events = processor._events_for_track(
            frame=None,
            track_id=1,
            detection=Detection(bbox=(50, 10, 70, 80), confidence=0.67),
            timestamp=datetime(2026, 4, 10, 11, 25, tzinfo=UTC),
            width=100,
            height=100,
            zones=_FakeZones(),
            queue_depth=0,
        )

        self.assertEqual(events[0]["event_type"], "REENTRY")
        self.assertEqual(events[0]["visitor_id"], "VIS_CAM_3_00001")

    def test_billing_exit_without_pos_generates_abandonment_event(self) -> None:
        join = build_event(
            store_id="ST1008",
            camera_id="CAM_5",
            visitor_id="VIS_001",
            event_type="BILLING_QUEUE_JOIN",
            timestamp="2026-04-10T11:25:00Z",
            zone_id="BILLING",
            metadata={"queue_depth": 4, "sku_zone": "CHECKOUT", "session_seq": 1},
        )
        exit_event = build_event(
            store_id="ST1008",
            camera_id="CAM_5",
            visitor_id="VIS_001",
            event_type="ZONE_EXIT",
            timestamp="2026-04-10T11:26:00Z",
            zone_id="BILLING",
            dwell_ms=60000,
            metadata={"session_seq": 2},
        )

        enriched = add_billing_abandonment_events([join, exit_event], transactions=[])

        abandon = [event for event in enriched if event["event_type"] == "BILLING_QUEUE_ABANDON"]
        self.assertEqual(len(abandon), 1)
        self.assertEqual(abandon[0]["metadata"]["queue_depth"], 4)

    def test_custom_model_staff_class_sets_staff_flag(self) -> None:
        processor = VideoProcessor(
            video_path=Path("unused.mp4"),
            output_path=Path("unused.jsonl"),
            layout_path=Path("config/store_layout.json"),
            store_id="ST1008",
            camera_id="CAM_1",
            model_path=Path("models/best.pt"),
            clip_start=datetime(2026, 4, 10, 11, 20, tzinfo=UTC),
        )

        events = processor._events_for_track(
            frame=None,
            track_id=5,
            detection=Detection(
                bbox=(50, 10, 70, 80),
                confidence=0.88,
                class_id=0,
                class_name="staff",
            ),
            timestamp=datetime(2026, 4, 10, 11, 20, tzinfo=UTC),
            width=100,
            height=100,
            zones=_ZoneOnlyFakeZones(),
            queue_depth=0,
        )

        self.assertTrue(events[0]["is_staff"])
        self.assertEqual(events[0]["metadata"]["person_role"], "staff")
        self.assertEqual(events[0]["metadata"]["role_source"], "custom_yolov8_class")
        self.assertEqual(events[0]["metadata"]["detector_family"], "YOLOv8-custom-staff-customer")


class _FakeZones:
    def entry_line(self, camera_id: str) -> dict[str, object]:
        return {"orientation": "vertical", "position": 0.5, "inbound_direction": "right"}

    def zone_for_point(self, camera_id: str, x_norm: float, y_norm: float) -> None:
        return None


class _ZoneOnlyFakeZones:
    def entry_line(self, camera_id: str) -> None:
        return None

    def zone_for_point(self, camera_id: str, x_norm: float, y_norm: float) -> object:
        return type("Zone", (), {"zone_id": "SKINCARE", "sku_zone": "MOISTURISER"})()
