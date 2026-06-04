from __future__ import annotations

from typing import TypeAlias

from pydantic import BaseModel, Field, field_validator

from app.schemas import (
    EventIn,
    EventType,
    HealthResponse,
    IngestError,
    IngestResponse,
    VideoJobResponse,
    VideoProcessAllRequest,
    VideoProcessRequest,
)


StoreEvent: TypeAlias = EventIn


class IngestRequest(BaseModel):
    """Batch wrapper for the challenge ingest contract.

    The public event schema is implemented in `app.schemas.EventIn`; this module exists
    as the explicit `app/models.py` entrypoint from the suggested repository layout.
    """

    events: list[StoreEvent] = Field(default_factory=list)

    @field_validator("events")
    @classmethod
    def _max_500(cls, value: list[StoreEvent]) -> list[StoreEvent]:
        if len(value) > 500:
            raise ValueError("Batch max 500 events")
        return value


__all__ = [
    "EventIn",
    "EventType",
    "HealthResponse",
    "IngestError",
    "IngestRequest",
    "IngestResponse",
    "StoreEvent",
    "VideoJobResponse",
    "VideoProcessAllRequest",
    "VideoProcessRequest",
]
