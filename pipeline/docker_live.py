from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from pipeline.detect import DEFAULT_DETECTOR_MODEL
from pipeline.live_replay import live_replay
from pipeline.run_all import process_all_cameras


def wait_for_api(api_url: str, timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{api_url.rstrip('/')}/health"
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("status") in {"ok", "degraded"}:
                    return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(2)

    raise RuntimeError(f"API did not become ready at {health_url}: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Docker helper: run custom YOLOv8 staff/customer detection and stream events into the API."
    )
    parser.add_argument("--video-dir", type=Path, default=Path("/app/sample_data/store-intelligence-videos"))
    parser.add_argument("--events", type=Path, default=Path("/data/generated_events_custom_yolov8.jsonl"))
    parser.add_argument("--layout", type=Path, default=Path("/app/config/store_layout.json"))
    parser.add_argument("--store-id", default="STORE_BLR_002")
    parser.add_argument("--model", type=Path, default=Path(DEFAULT_DETECTOR_MODEL))
    parser.add_argument("--clip-start", default="2026-04-10T11:20:00Z")
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--tracker", choices=["botsort", "bytetrack", "centroid"], default="bytetrack")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--pos-csv", type=Path, default=Path("/app/POS - sample transactionsb1e826f.csv"))
    parser.add_argument("--clip-set", default="sample")
    parser.add_argument("--api-url", default="http://api:8000")
    parser.add_argument("--speed", type=float, default=12.0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--fresh-run", action="store_true", default=True)
    parser.add_argument("--stream-after-camera", action="store_true", default=True)
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument("--wait-timeout", type=int, default=90)
    args = parser.parse_args()

    wait_for_api(args.api_url, args.wait_timeout)

    if not args.skip_generate:
        if args.events.exists() and args.events.stat().st_size > 0:
            print(
                {
                    "using_existing_events": str(args.events),
                    "bytes": args.events.stat().st_size,
                    "api_url": args.api_url,
                }
            )
            live_replay(
                path=args.events,
                api_url=args.api_url,
                batch_size=args.batch_size,
                speed=args.speed,
                max_sleep=0.2,
                fresh_run=args.fresh_run,
            )
            return

        clip_start = datetime.fromisoformat(args.clip_start.replace("Z", "+00:00")).astimezone(
            UTC
        )

        def stream_camera_events(path: Path) -> None:
            print({"streaming_camera_events": str(path), "api_url": args.api_url})
            live_replay(
                path=path,
                api_url=args.api_url,
                batch_size=args.batch_size,
                speed=args.speed,
                max_sleep=0.2,
                fresh_run=args.fresh_run,
            )

        process_all_cameras(
            video_dir=args.video_dir,
            output=args.events,
            layout=args.layout,
            store_id=args.store_id,
            model=args.model,
            clip_start=clip_start,
            frame_stride=args.frame_stride,
            confidence_threshold=args.conf,
            inference_imgsz=args.imgsz,
            tracking_backend=args.tracker,
            pos_csv=args.pos_csv,
            stitch=True,
            after_camera=stream_camera_events if args.stream_after_camera else None,
            clip_set=args.clip_set,
        )
        if args.stream_after_camera:
            return

    live_replay(
        path=args.events,
        api_url=args.api_url,
        batch_size=args.batch_size,
        speed=args.speed,
        max_sleep=1.5,
        fresh_run=args.fresh_run,
    )


if __name__ == "__main__":
    main()
