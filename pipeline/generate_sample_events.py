from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas import EventType
from pipeline.emit import JsonlEmitter, build_event


def generate_sample_events(output_path: Path, store_id: str = "ST1008") -> int:
    base = datetime(2026, 4, 10, 11, 23, tzinfo=UTC)
    rows = [
        ("VIS_001", EventType.ENTRY, 0, None, 0, False, 0.94, None),
        ("VIS_001", EventType.ZONE_ENTER, 30, "SKINCARE", 0, False, 0.91, None),
        ("VIS_001", EventType.ZONE_DWELL, 65, "SKINCARE", 35000, False, 0.9, None),
        ("VIS_001", EventType.ZONE_EXIT, 80, "SKINCARE", 50000, False, 0.88, None),
        ("VIS_001", EventType.BILLING_QUEUE_JOIN, 100, "BILLING", 0, False, 0.9, 2),
        ("VIS_001", EventType.EXIT, 280, None, 0, False, 0.93, None),
        ("VIS_002", EventType.ENTRY, 8, None, 0, False, 0.89, None),
        ("VIS_002", EventType.ZONE_ENTER, 40, "MAKEUP", 0, False, 0.87, None),
        ("VIS_002", EventType.ZONE_DWELL, 75, "MAKEUP", 35000, False, 0.86, None),
        ("VIS_002", EventType.BILLING_QUEUE_JOIN, 130, "BILLING", 0, False, 0.88, 3),
        ("VIS_002", EventType.BILLING_QUEUE_ABANDON, 180, "BILLING", 50000, False, 0.84, 2),
        ("VIS_003", EventType.ENTRY, 12, None, 0, True, 0.95, None),
        ("VIS_003", EventType.ZONE_ENTER, 50, "SKINCARE", 0, True, 0.93, None),
        ("VIS_004", EventType.ENTRY, 220, None, 0, False, 0.78, None),
        ("VIS_004", EventType.EXIT, 260, None, 0, False, 0.8, None),
        ("VIS_004", EventType.REENTRY, 310, None, 0, False, 0.76, None),
        ("VIS_004", EventType.ZONE_ENTER, 330, "HAIRCARE", 0, False, 0.78, None),
        ("VIS_004", EventType.ZONE_DWELL, 365, "HAIRCARE", 35000, False, 0.77, None),
    ]

    count = 0
    with JsonlEmitter(output_path) as emitter:
        for index, (visitor_id, event_type, offset, zone_id, dwell_ms, is_staff, confidence, queue_depth) in enumerate(rows, start=1):
            emitter.emit(
                build_event(
                    store_id=store_id,
                    camera_id="CAM_1" if event_type in {EventType.ENTRY, EventType.EXIT, EventType.REENTRY} else "CAM_2",
                    visitor_id=visitor_id,
                    event_type=event_type,
                    timestamp=base + timedelta(seconds=offset),
                    zone_id=zone_id,
                    dwell_ms=dwell_ms,
                    is_staff=is_staff,
                    confidence=confidence,
                    metadata={
                        "queue_depth": queue_depth,
                        "sku_zone": zone_id,
                        "session_seq": index,
                    },
                )
            )
            count += 1
    return count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate schema-valid sample events.")
    parser.add_argument("--output", type=Path, default=Path("sample_data/sample_events.jsonl"))
    parser.add_argument("--store-id", default="ST1008")
    args = parser.parse_args()
    count = generate_sample_events(args.output, args.store_id)
    print({"events_written": count, "output": str(args.output)})
