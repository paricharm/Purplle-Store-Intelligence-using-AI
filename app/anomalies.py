from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.analytics import compute_anomalies


router = APIRouter()


@router.get("/stores/{id}/anomalies")
def get_anomalies(id: str) -> dict[str, Any]:
    return compute_anomalies(id)
