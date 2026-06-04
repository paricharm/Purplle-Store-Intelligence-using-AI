# PROMPT:
# Generate tests for cross-camera visitor stitching. Verify that an entry-camera track
# and a main-floor track close in time become one anonymous visitor session.
#
# CHANGES MADE:
# Kept the fixture minimal and asserted metadata preservation so follow-up questions can
# explain how camera-local IDs are retained after global visitor_id stitching.

from unittest import TestCase

from pipeline.stitch_sessions import stitch_events


class StitchSessionTests(TestCase):
    def test_entry_and_floor_tracks_share_global_visitor_id(self) -> None:
        events = [
            {
                "event_id": "evt-entry",
                "store_id": "ST1008",
                "camera_id": "CAM_3",
                "visitor_id": "VIS_CAM_3_00001",
                "event_type": "ENTRY",
                "timestamp": "2026-04-10T11:20:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.8,
                "metadata": {"camera_visitor_id": "VIS_CAM_3_00001", "session_seq": 1},
            },
            {
                "event_id": "evt-zone",
                "store_id": "ST1008",
                "camera_id": "CAM_1",
                "visitor_id": "VIS_CAM_1_00009",
                "event_type": "ZONE_ENTER",
                "timestamp": "2026-04-10T11:20:45Z",
                "zone_id": "SKINCARE",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.76,
                "metadata": {"camera_visitor_id": "VIS_CAM_1_00009", "session_seq": 1},
            },
        ]

        stitched = stitch_events(events)

        self.assertEqual(stitched[0]["visitor_id"], stitched[1]["visitor_id"])
        self.assertEqual(stitched[1]["metadata"]["pre_stitch_visitor_id"], "VIS_CAM_1_00009")
        self.assertEqual(stitched[1]["metadata"]["session_seq"], 2)
