from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.analytics import compute_funnel


router = APIRouter()


@router.get("/stores/{id}/funnel")
def get_funnel(id: str) -> dict[str, Any]:
    return compute_funnel(id)
