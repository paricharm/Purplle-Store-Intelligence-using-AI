from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean


def load_events(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def summarize(path: Path) -> dict:
    events = load_events(path)
    confidences = [float(event["confidence"]) for event in events]
    metadata = [event.get("metadata") or {} for event in events]
    return {
        "file": str(path),
        "events": len(events),
        "visitors": len({event["visitor_id"] for event in events}),
        "event_types": dict(Counter(event["event_type"] for event in events)),
        "cameras": dict(Counter(event["camera_id"] for event in events)),
        "zones": dict(Counter(str(event.get("zone_id")) for event in events)),
        "staff": dict(Counter(str(event["is_staff"]) for event in events)),
        "person_roles": dict(
            Counter(str(meta.get("person_role", "unknown")) for meta in metadata)
        ),
        "detector_models": dict(
            Counter(str(meta.get("detector_model", "unknown")) for meta in metadata)
        ),
        "avg_confidence": round(mean(confidences), 4) if confidences else 0,
        "low_confidence_events": sum(1 for value in confidences if value < 0.35),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare two generated event JSONL files.")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.files:
        print(json.dumps(summarize(path), indent=2, sort_keys=True))
