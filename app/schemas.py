from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.time_utils import parse_timestamp, to_iso_z


class EventType(StrEnum):
    DETECTION = "DETECTION"
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    camera_id: str = Field(min_length=1)
    visitor_id: str = Field(min_length=1)
    event_type: EventType
    timestamp: datetime
    zone_id: str | None = None
    dwell_ms: int = Field(ge=0)
    is_staff: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: str | datetime) -> datetime:
        return parse_timestamp(value)

    @field_serializer("timestamp")
    def _serialize_timestamp(self, value: datetime) -> str:
        return to_iso_z(value) or ""


class IngestError(BaseModel):
    index: int
    event_id: str | None = None
    code: str
    message: str


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    errors: list[IngestError] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    database: str
    last_event_timestamp_per_store: dict[str, str | None]
    warnings: list[dict[str, Any]]


class VideoProcessRequest(BaseModel):
    video_path: str | None = None
    store_id: str = "STORE_BLR_002"
    camera_id: str = "CAM_1"
    model: str = "models/best.pt"
    clip_set: str = "sample"
    clip_start: datetime
    frame_stride: int = Field(default=10, ge=1, le=300)
    confidence_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    imgsz: int = Field(default=960, ge=320, le=1920)
    tracker: str = Field(default="bytetrack", pattern="^(botsort|bytetrack|centroid)$")
    ingest: bool = True

    @field_validator("clip_start", mode="before")
    @classmethod
    def _parse_clip_start(cls, value: str | datetime) -> datetime:
        return parse_timestamp(value)

    @field_serializer("clip_start")
    def _serialize_clip_start(self, value: datetime) -> str:
        return to_iso_z(value) or ""


class VideoProcessAllRequest(BaseModel):
    video_dir: str | None = None
    store_id: str = "STORE_BLR_002"
    model: str = "models/best.pt"
    clip_set: str = "sample"
    clip_start: datetime
    frame_stride: int = Field(default=10, ge=1, le=300)
    confidence_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    imgsz: int = Field(default=960, ge=320, le=1920)
    tracker: str = Field(default="bytetrack", pattern="^(botsort|bytetrack|centroid)$")
    stitch: bool = True
    ingest: bool = True

    @field_validator("clip_start", mode="before")
    @classmethod
    def _parse_clip_start(cls, value: str | datetime) -> datetime:
        return parse_timestamp(value)

    @field_serializer("clip_start")
    def _serialize_clip_start(self, value: datetime) -> str:
        return to_iso_z(value) or ""


class VideoJobResponse(BaseModel):
    job_id: str
    status: str
    message: str
    output_path: str | None = None
    events_written: int = 0
    events_ingested: int = 0
    duplicates: int = 0
    error: str | None = None
