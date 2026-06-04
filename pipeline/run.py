from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from pipeline.detect import DEFAULT_DETECTOR_MODEL, VideoProcessor
from pipeline.enrich_events import enrich_billing_abandonment_file
from pipeline.generate_sample_events import generate_sample_events


def main() -> None:
    parser = argparse.ArgumentParser(description="Store intelligence detection pipeline entrypoint.")
    parser.add_argument("--mode", choices=["sample", "detect"], default="sample")
    parser.add_argument("--output", type=Path, default=Path("generated_events.jsonl"))
    parser.add_argument("--video", type=Path, default=Path("sample_data/store-intelligence-videos/CAM 1.mp4"))
    parser.add_argument("--layout", type=Path, default=Path("config/store_layout.json"))
    parser.add_argument("--store-id", default="STORE_BLR_002")
    parser.add_argument("--camera-id", default="CAM_1")
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(DEFAULT_DETECTOR_MODEL),
        help=f"Local .pt file or Ultralytics weight name. Default: {DEFAULT_DETECTOR_MODEL}.",
    )
    parser.add_argument("--clip-start", default="2026-04-10T11:30:00Z")
    parser.add_argument("--frame-stride", type=int, default=5)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--tracker", choices=["botsort", "bytetrack", "centroid"], default="bytetrack")
    parser.add_argument("--pos-csv", type=Path, default=Path("POS - sample transactionsb1e826f.csv"))
    args = parser.parse_args()

    if args.mode == "sample":
        count = generate_sample_events(args.output, args.store_id)
    else:
        clip_start = datetime.fromisoformat(args.clip_start.replace("Z", "+00:00")).astimezone(UTC)
        count = VideoProcessor(
            video_path=args.video,
            output_path=args.output,
            layout_path=args.layout,
            store_id=args.store_id,
            camera_id=args.camera_id,
            model_path=args.model,
            clip_start=clip_start,
            frame_stride=args.frame_stride,
            confidence_threshold=args.conf,
            inference_imgsz=args.imgsz,
            tracking_backend=args.tracker,
        ).run()
        if args.pos_csv.exists():
            count = enrich_billing_abandonment_file(args.output, args.output, args.pos_csv)
    print({"mode": args.mode, "events_written": count, "output": str(args.output)})


if __name__ == "__main__":
    main()
