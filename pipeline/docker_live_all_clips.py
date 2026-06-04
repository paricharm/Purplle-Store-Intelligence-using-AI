from __future__ import annotations

import argparse
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from pipeline.docker_live import wait_for_api
from pipeline.live_replay import live_replay
from pipeline.run_all import process_all_cameras


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "clip_set"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process every /data/clips store folder and stream custom YOLOv8 events into the API."
    )
    parser.add_argument("--clips-root", type=Path, default=Path("/data/clips"))
    parser.add_argument("--output-dir", type=Path, default=Path("/data"))
    parser.add_argument("--layout", type=Path, default=Path("/app/config/store_layout.json"))
    parser.add_argument("--store-id", default="STORE_BLR_002")
    parser.add_argument("--model", type=Path, default=Path("/app/models/best.pt"))
    parser.add_argument("--clip-start", default="2026-04-10T11:20:00Z")
    parser.add_argument("--frame-stride", type=int, default=5)
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--tracker", choices=["botsort", "bytetrack", "centroid"], default="bytetrack")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--pos-csv", type=Path, default=Path("/app/POS - sample transactionsb1e826f.csv"))
    parser.add_argument("--api-url", default="http://api:8000")
    parser.add_argument("--speed", type=float, default=12.0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--wait-timeout", type=int, default=90)
    parser.add_argument("--fresh-run", action="store_true", default=True)
    args = parser.parse_args()

    wait_for_api(args.api_url, args.wait_timeout)
    clip_start = datetime.fromisoformat(args.clip_start.replace("Z", "+00:00")).astimezone(UTC)
    folders = sorted(path for path in args.clips_root.iterdir() if path.is_dir())
    if not folders:
        raise RuntimeError(f"No clip folders found in {args.clips_root}")

    for folder in folders:
        clip_set = folder.name
        output = args.output_dir / f"generated_events_{_safe_name(clip_set)}.jsonl"
        if not output.exists() or output.stat().st_size == 0:
            def stream_camera_events(path: Path) -> None:
                print(
                    {
                        "streaming_partial_clip_set": clip_set,
                        "camera_events": str(path),
                        "api_url": args.api_url,
                    }
                )
                live_replay(
                    path=path,
                    api_url=args.api_url,
                    batch_size=args.batch_size,
                    speed=args.speed,
                    max_sleep=0.2,
                    fresh_run=args.fresh_run,
                )

            process_all_cameras(
                video_dir=folder,
                output=output,
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
                clip_set=clip_set,
                after_camera=stream_camera_events,
            )
        print({"streaming_clip_set": clip_set, "events": str(output), "api_url": args.api_url})
        live_replay(
            path=output,
            api_url=args.api_url,
            batch_size=args.batch_size,
            speed=args.speed,
            max_sleep=0.2,
            fresh_run=args.fresh_run,
        )
        time.sleep(0.5)


if __name__ == "__main__":
    main()
