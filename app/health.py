from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter

from app.config import settings
from app.schemas import HealthResponse
from app.storage import check_database, latest_event_timestamp_by_store
from app.time_utils import parse_timestamp


router = APIRouter()


def service_health() -> HealthResponse:
    db_ok = check_database()
    latest_by_store = latest_event_timestamp_by_store() if db_ok else {}
    warnings: list[dict[str, Any]] = []
    stale_cutoff = datetime.now(UTC) - timedelta(minutes=settings.stale_feed_minutes)
    for store_id, timestamp in latest_by_store.items():
        if timestamp and parse_timestamp(timestamp) < stale_cutoff:
            warnings.append(
                {
                    "store_id": store_id,
                    "code": "STALE_FEED",
                    "message": f"No events received in the last {settings.stale_feed_minutes} minutes.",
                    "last_event_timestamp": timestamp,
                }
            )
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        database="ok" if db_ok else "unavailable",
        last_event_timestamp_per_store=latest_by_store,
        warnings=warnings,
    )


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return service_health()
