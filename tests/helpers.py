from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil
import uuid

from app.schemas import EventIn, EventType
from app.storage import init_db, insert_events, insert_pos_transactions
from pipeline.emit import build_event


@contextmanager
def workspace_tempdir():
    root = Path.cwd() / ".test_tmp"
    root.mkdir(exist_ok=True)
    tmp = root / f"case_{uuid.uuid4().hex}"
    tmp.mkdir()
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def seed_events(db_path: Path) -> None:
    init_db(db_path)
    base = datetime(2026, 4, 10, 11, 23, tzinfo=UTC)
    raw = [
        ("VIS_001", EventType.ENTRY, 0, None, 0, False, 0.95, None),
        ("VIS_001", EventType.ZONE_ENTER, 30, "SKINCARE", 0, False, 0.93, None),
        ("VIS_001", EventType.ZONE_DWELL, 65, "SKINCARE", 35000, False, 0.92, None),
        ("VIS_001", EventType.BILLING_QUEUE_JOIN, 100, "BILLING", 0, False, 0.91, 6),
        ("VIS_002", EventType.ENTRY, 10, None, 0, False, 0.91, None),
        ("VIS_002", EventType.ZONE_ENTER, 40, "MAKEUP", 0, False, 0.89, None),
        ("VIS_002", EventType.BILLING_QUEUE_ABANDON, 180, "BILLING", 40000, False, 0.84, 2),
        ("STAFF_001", EventType.ENTRY, 15, None, 0, True, 0.96, None),
        ("VIS_003", EventType.ENTRY, 220, None, 0, False, 0.78, None),
        ("VIS_003", EventType.EXIT, 260, None, 0, False, 0.8, None),
        ("VIS_003", EventType.REENTRY, 310, None, 0, False, 0.76, None),
    ]
    events = [
        build_event(
            store_id="ST1008",
            camera_id="CAM_1",
            visitor_id=visitor_id,
            event_type=event_type,
            timestamp=base + timedelta(seconds=offset),
            zone_id=zone_id,
            dwell_ms=dwell_ms,
            is_staff=is_staff,
            confidence=confidence,
            metadata={"queue_depth": queue_depth, "session_seq": index, "sku_zone": zone_id},
        )
        for index, (visitor_id, event_type, offset, zone_id, dwell_ms, is_staff, confidence, queue_depth)
        in enumerate(raw, start=1)
    ]
    insert_events([EventIn.model_validate(event) for event in events], db_path)
    insert_pos_transactions(
        [
            {
                "transaction_id": "TXN_MATCHES_VIS_001",
                "store_id": "ST1008",
                "timestamp": "2026-04-10T11:25:36Z",
                "basket_value_inr": 1240.0,
            }
        ],
        db_path,
    )
