# PROMPT:
# Generate tests for runtime helpers used by the live demo and production readiness:
# video job bookkeeping, JSONL ingestion, live replay fresh-run behavior, zone filters,
# POS parsing, and the fallback centroid tracker.
#
# CHANGES MADE:
# Avoided starting background detector threads or requiring OpenCV/Ultralytics. The tests
# use small local files and monkeypatched network calls so they are deterministic.

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.config import settings
from app.pos_import import load_pos_csv
from app.schemas import EventIn
from app.storage import fetch_events, init_db
from app.video_jobs import _ingest_output, _resolve_path, _set_job, _update_job, get_job, list_videos
from pipeline.docker_live import wait_for_api
from pipeline.emit import JsonlEmitter, build_event
from pipeline.live_replay import _freshen_event, _load_events, live_replay
import pipeline.run as run_module
from pipeline.replay import replay_events
from pipeline.run_all import CAMERA_FILES, process_all_cameras
from pipeline.staff import classify_person_role
from pipeline.tracker import CentroidTracker, Detection
from pipeline.zones import ZoneMapper, point_in_polygon
from tests.helpers import workspace_tempdir


class RuntimeHelperTests(TestCase):
    def test_jsonl_emitter_and_video_job_ingest_output(self) -> None:
        with workspace_tempdir() as tmp:
            original_db_path = settings.db_path
            object.__setattr__(settings, "db_path", tmp / "jobs.db")
            try:
                init_db(settings.db_path)
                output = tmp / "events.jsonl"
                with JsonlEmitter(output) as emitter:
                    emitter.emit(
                        build_event(
                            store_id="STORE_BLR_002",
                            camera_id="CAM_1",
                            visitor_id="VIS_JOB_001",
                            event_type="ENTRY",
                            timestamp=datetime(2026, 4, 10, 11, 20, tzinfo=UTC),
                        )
                    )

                accepted, duplicates = _ingest_output(output)
                second_accepted, second_duplicates = _ingest_output(output)

                self.assertEqual((accepted, duplicates), (1, 0))
                self.assertEqual((second_accepted, second_duplicates), (0, 1))
                self.assertEqual(len(fetch_events("STORE_BLR_002", db_path=settings.db_path)), 1)
            finally:
                object.__setattr__(settings, "db_path", original_db_path)

    def test_video_listing_path_resolution_and_job_bookkeeping(self) -> None:
        with workspace_tempdir() as tmp:
            original_cctv = settings.cctv_dir_path
            object.__setattr__(settings, "cctv_dir_path", tmp / "videos")
            try:
                settings.cctv_dir_path.mkdir()
                video = settings.cctv_dir_path / "CAM 1.mp4"
                video.write_bytes(b"fake")

                listing = list_videos()
                self.assertEqual(listing["count"], 1)
                self.assertEqual(_resolve_path("CAM 1.mp4", default=video), video.resolve())

                _set_job(
                    "job-1",
                    {
                        "job_id": "job-1",
                        "status": "queued",
                        "message": "queued",
                        "output_path": None,
                        "events_written": 0,
                        "events_ingested": 0,
                        "duplicates": 0,
                        "error": None,
                    },
                )
                _update_job("job-1", status="completed", events_written=3)
                self.assertEqual(get_job("job-1").status, "completed")
                self.assertEqual(get_job("missing").status, "not_found")
                with self.assertRaises(FileNotFoundError):
                    _resolve_path("missing.mp4", default=video)
            finally:
                object.__setattr__(settings, "cctv_dir_path", original_cctv)

    def test_live_replay_freshens_and_batches_events(self) -> None:
        with workspace_tempdir() as tmp:
            first = build_event(
                store_id="STORE_BLR_002",
                camera_id="CAM_1",
                visitor_id="VIS_LIVE",
                event_type="ENTRY",
                timestamp=datetime(2026, 4, 10, 11, 20, tzinfo=UTC),
            )
            second = build_event(
                store_id="STORE_BLR_002",
                camera_id="CAM_1",
                visitor_id="VIS_LIVE",
                event_type="EXIT",
                timestamp=datetime(2026, 4, 10, 11, 21, tzinfo=UTC),
            )
            events_path = tmp / "events.jsonl"
            events_path.write_text(
                "\n".join(json.dumps(event) for event in [second, first]),
                encoding="utf-8",
            )
            self.assertEqual(_load_events(events_path)[0]["event_type"], "ENTRY")
            fresh = _freshen_event(first, "abc123")
            self.assertNotEqual(fresh["event_id"], first["event_id"])
            self.assertEqual(fresh["metadata"]["original_visitor_id"], "VIS_LIVE")

            posted: list[list[dict[str, object]]] = []

            def fake_post(batch: list[dict[str, object]], api_url: str) -> dict[str, int]:
                posted.append(batch)
                return {"accepted": len(batch), "duplicates": 0}

            with patch("pipeline.live_replay._post", fake_post), patch("time.sleep", lambda _: None):
                live_replay(
                    path=events_path,
                    api_url="http://api",
                    batch_size=1,
                    speed=60,
                    max_sleep=0.01,
                    fresh_run=True,
                )

            self.assertEqual(len(posted), 2)
            self.assertNotEqual(posted[0][0]["visitor_id"], "VIS_LIVE")

    def test_zones_tracker_and_pos_csv_helpers(self) -> None:
        with workspace_tempdir() as tmp:
            layout = tmp / "layout.json"
            layout.write_text(
                json.dumps(
                    {
                        "stores": {
                            "ST1008": {
                                "cameras": {
                                    "CAM_1": {
                                        "entry_line": {
                                            "orientation": "horizontal",
                                            "position": 0.5,
                                        },
                                        "detection_filter": {
                                            "min_bottom_y_norm": 0.4,
                                            "min_height_norm": 0.1,
                                            "max_width_norm": 0.8,
                                            "ignore_polygons": [
                                                [[0.0, 0.0], [0.4, 0.0], [0.4, 0.4], [0.0, 0.4]]
                                            ],
                                        },
                                    }
                                },
                                "zones": [
                                    {
                                        "zone_id": "SKINCARE",
                                        "camera_ids": ["CAM_1"],
                                        "polygon": [[0.4, 0.4], [1.0, 0.4], [1.0, 1.0], [0.4, 1.0]],
                                        "sku_zone": "MOISTURISER",
                                    }
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            mapper = ZoneMapper(layout, "STORE_BLR_002")
            self.assertTrue(point_in_polygon(0.5, 0.5, [(0, 0), (1, 0), (1, 1), (0, 1)]))
            self.assertEqual(mapper.zone_for_point("CAM_1", 0.6, 0.6).zone_id, "SKINCARE")
            self.assertIsNotNone(mapper.entry_line("CAM_1"))
            self.assertEqual(
                mapper.is_valid_person_detection("CAM_1", (10, 10, 20, 20), 100, 100)[1],
                "bottom_center_above_walkable_floor",
            )
            self.assertEqual(
                mapper.is_valid_person_detection("CAM_1", (0, 0, 90, 90), 100, 100)[1],
                "box_too_wide_for_single_person",
            )
            self.assertEqual(
                mapper.is_valid_person_detection("CAM_1", (10, 45, 20, 60), 100, 100)[0],
                True,
            )

            tracker = CentroidTracker(max_distance=20, max_missed=1)
            first_tracks = tracker.update([Detection((0, 0, 10, 10), 0.8)])
            second_tracks = tracker.update([Detection((2, 2, 12, 12), 0.7)])
            self.assertEqual(first_tracks[0].track_id, second_tracks[0].track_id)
            tracker.update([])
            self.assertEqual(tracker.update([]), [])

            csv_path = tmp / "pos.csv"
            csv_path.write_text(
                "invoice_number,store_id,total_amount,order_date,order_time\n"
                "INV1,ST1008,100.50,10-04-2026,11:20:00\n"
                "INV1,ST1008,20.25,10-04-2026,11:20:00\n"
                "INV2,ST1008,bad,10-04-2026,11:25:00\n",
                encoding="utf-8",
            )
            transactions = load_pos_csv(csv_path)
            self.assertEqual(transactions[0]["basket_value_inr"], 120.75)
            self.assertEqual(transactions[1]["basket_value_inr"], 0.0)

    def test_process_all_cameras_combines_and_stitches_outputs(self) -> None:
        with workspace_tempdir() as tmp:
            video_dir = tmp / "videos"
            video_dir.mkdir()
            for filename in (CAMERA_FILES["CAM_1"], CAMERA_FILES["CAM_3"]):
                (video_dir / filename).write_bytes(b"fake")

            class FakeVideoProcessor:
                def __init__(self, **kwargs: object) -> None:
                    self.output_path = kwargs["output_path"]
                    self.camera_id = kwargs["camera_id"]
                    self.store_id = kwargs["store_id"]

                def run(self) -> int:
                    event = build_event(
                        store_id=str(self.store_id),
                        camera_id=str(self.camera_id),
                        visitor_id=f"VIS_{self.camera_id}",
                        event_type="ENTRY",
                        timestamp=datetime(2026, 4, 10, 11, 20, tzinfo=UTC),
                    )
                    Path(self.output_path).write_text(json.dumps(event) + "\n", encoding="utf-8")
                    return 1

            def fake_stitch_file(input_path: Path, output_path: Path) -> int:
                output_path.write_text(input_path.read_text(encoding="utf-8"), encoding="utf-8")
                return 2

            with patch("pipeline.run_all.VideoProcessor", FakeVideoProcessor), patch(
                "pipeline.run_all.stitch_file",
                fake_stitch_file,
            ), patch("pipeline.run_all.enrich_billing_abandonment_file", lambda *_args: 3):
                result = process_all_cameras(
                    video_dir=video_dir,
                    output=tmp / "combined.jsonl",
                    layout=tmp / "layout.json",
                    store_id="STORE_BLR_002",
                    model=Path("model.pt"),
                    clip_start=datetime(2026, 4, 10, 11, 20, tzinfo=UTC),
                    frame_stride=10,
                    confidence_threshold=0.1,
                    inference_imgsz=640,
                    tracking_backend="bytetrack",
                    pos_csv=tmp / "pos.csv",
                    stitch=True,
                )

            self.assertEqual(result["combined_events"], 2)
            self.assertEqual(result["stitched_events"], 2)
            self.assertEqual(result["camera_counts"]["CAM_2"], 0)

    def test_replay_docker_wait_and_staff_default_paths(self) -> None:
        with workspace_tempdir() as tmp:
            event = build_event(
                store_id="STORE_BLR_002",
                camera_id="CAM_1",
                visitor_id="VIS_REPLAY",
                event_type="ENTRY",
                timestamp=datetime(2026, 4, 10, 11, 20, tzinfo=UTC),
            )
            events_path = tmp / "events.jsonl"
            events_path.write_text(json.dumps(event) + "\n\n", encoding="utf-8")
            posted_batches: list[list[dict[str, object]]] = []

            class FakeResponse:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict[str, int]:
                    return {"accepted": 1}

            def fake_post(url: str, json: list[dict[str, object]], timeout: int) -> FakeResponse:
                posted_batches.append(json)
                return FakeResponse()

            with patch("pipeline.replay.requests.post", fake_post), patch("time.sleep", lambda _: None):
                replay_events(events_path, "http://api", batch_size=1, delay_seconds=0.01)

            self.assertEqual(len(posted_batches), 1)

            class FakeUrlOpen:
                def __enter__(self) -> "FakeUrlOpen":
                    return self

                def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                    return None

                def read(self) -> bytes:
                    return b'{"status":"ok"}'

            with patch("urllib.request.urlopen", lambda *_args, **_kwargs: FakeUrlOpen()):
                wait_for_api("http://api", timeout_seconds=1)

            role = classify_person_role(None, (0, 0, 10, 10), camera_id="CAM_1")
            self.assertEqual(role.label, "customer")

    def test_pipeline_run_cli_sample_and_detect_modes(self) -> None:
        with workspace_tempdir() as tmp:
            sample_output = tmp / "sample.jsonl"
            detect_output = tmp / "detect.jsonl"

            with patch(
                "sys.argv",
                ["run.py", "--mode", "sample", "--output", str(sample_output), "--store-id", "ST1008"],
            ), patch("pipeline.run.generate_sample_events", lambda output, store_id: 4):
                run_module.main()

            class FakeVideoProcessor:
                def __init__(self, **kwargs: object) -> None:
                    self.output_path = kwargs["output_path"]

                def run(self) -> int:
                    Path(self.output_path).write_text("", encoding="utf-8")
                    return 2

            with patch(
                "sys.argv",
                [
                    "run.py",
                    "--mode",
                    "detect",
                    "--output",
                    str(detect_output),
                    "--video",
                    str(tmp / "clip.mp4"),
                    "--pos-csv",
                    str(tmp / "missing.csv"),
                ],
            ), patch("pipeline.run.VideoProcessor", FakeVideoProcessor):
                run_module.main()

            self.assertTrue(detect_output.exists())
