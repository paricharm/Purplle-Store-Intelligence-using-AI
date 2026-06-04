# PROMPT:
# Switch the production detection path to a custom YOLOv8 best.pt model with
# staff/customer classes and ByteTrack tracking.
#
# CHANGES MADE:
# Updated the old detector default assertions to protect the custom-model default while
# keeping a small anonymous role-classification fallback test.

from pathlib import Path
from datetime import UTC, datetime
from unittest import TestCase

from pipeline.detect import DEFAULT_DETECTOR_MODEL, VideoProcessor
from pipeline.staff import classify_person_role


class CustomYoloDefaultTests(TestCase):
    def test_missing_requested_model_uses_custom_best_pt_default(self) -> None:
        source = VideoProcessor._resolve_model_source(Path("models/does-not-exist.pt"))

        self.assertEqual(Path(source), Path(DEFAULT_DETECTOR_MODEL))
        self.assertEqual(Path(source), Path("models/best.pt"))

    def test_role_classifier_returns_anonymous_customer_without_face_identity(self) -> None:
        role = classify_person_role(None, (0, 0, 10, 10), camera_id="CAM_1")

        self.assertEqual(role.label, "customer")
        self.assertFalse(role.is_staff)
        self.assertGreater(role.confidence, 0)
        self.assertNotIn("face_id", role.signals)

    def test_detector_defaults_to_bytetrack_tracking(self) -> None:
        processor = VideoProcessor(
            video_path=Path("unused.mp4"),
            output_path=Path("unused.jsonl"),
            layout_path=Path("config/store_layout.json"),
            store_id="STORE_BLR_002",
            camera_id="CAM_1",
            model_path=Path(DEFAULT_DETECTOR_MODEL),
            clip_start=datetime.now(UTC),
        )

        self.assertEqual(processor.tracking_backend, "bytetrack")
