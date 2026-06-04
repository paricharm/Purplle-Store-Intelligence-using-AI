from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.analytics import compute_metrics


router = APIRouter()


@router.get("/stores/{id}/metrics")
def get_metrics(id: str) -> dict[str, Any]:
    return compute_metrics(id)
