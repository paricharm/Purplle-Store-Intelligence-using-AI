from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.schemas import EventIn, EventType
from app.time_utils import to_iso_z


def build_event(
    *,
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: EventType | str,
    timestamp: datetime,
    zone_id: str | None = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 0.75,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = EventIn(
        event_id=str(uuid.uuid4()),
        store_id=store_id,
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type=EventType(event_type),
        timestamp=timestamp,
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=max(0.0, min(1.0, confidence)),
        metadata=metadata or {},
    )
    return event.model_dump(mode="json")


class JsonlEmitter:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.output_path.open("w", encoding="utf-8")

    def emit(self, event: dict[str, Any]) -> None:
        if isinstance(event.get("timestamp"), datetime):
            event = {**event, "timestamp": to_iso_z(event["timestamp"])}
        validated = EventIn.model_validate(event)
        self._handle.write(json.dumps(validated.model_dump(mode="json"), sort_keys=True) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "JsonlEmitter":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
