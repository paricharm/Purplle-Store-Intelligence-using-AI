from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models import IngestRequest
from app.schemas import EventIn, IngestError, IngestResponse
from app.storage import insert_events


router = APIRouter()


def ingest_batch(events: list[EventIn]) -> IngestResponse:
    accepted, duplicates = insert_events(events)
    return IngestResponse(accepted=accepted, duplicates=duplicates, rejected=0, errors=[])


@router.post("/events/ingest", response_model=IngestResponse)
def ingest(request: IngestRequest) -> IngestResponse:
    if len(request.events) > settings.ingest_batch_limit:
        raise HTTPException(status_code=400, detail="Batch max 500 events")
    return ingest_batch(request.events)


def ingest_payload(payload: list[dict] | dict) -> IngestResponse:
    raw_events = payload.get("events", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_events, list):
        raise ValueError("Expected a JSON array or an object with an events array.")

    valid: list[EventIn] = []
    errors: list[IngestError] = []
    for index, raw_event in enumerate(raw_events):
        try:
            valid.append(EventIn.model_validate(raw_event))
        except Exception as exc:
            errors.append(
                IngestError(
                    index=index,
                    event_id=raw_event.get("event_id") if isinstance(raw_event, dict) else None,
                    code="INVALID_EVENT",
                    message=str(exc),
                )
            )
    accepted, duplicates = insert_events(valid)
    return IngestResponse(
        accepted=accepted,
        duplicates=duplicates,
        rejected=len(errors),
        errors=errors,
    )
