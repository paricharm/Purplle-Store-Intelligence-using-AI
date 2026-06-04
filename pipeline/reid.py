from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ReIDDescriptor:
    vector: list[float]
    method: str


class OSNetReIdentifier:
    """OSNet-compatible Re-ID helper with a deterministic lightweight fallback.

    If `torchreid` is available, this class can be extended to load an OSNet model.
    The fallback keeps the submitted pipeline runnable in CPU-only environments while
    preserving the same descriptor/match contract.
    """

    def __init__(self) -> None:
        self.method = "appearance_histogram_fallback"
        try:
            import torchreid  # noqa: F401
        except Exception:
            self.has_osnet = False
        else:
            self.has_osnet = True
            self.method = "osnet_ready"
        self.gallery: dict[str, tuple[ReIDDescriptor, datetime]] = {}

    def describe(self, frame: Any, bbox: tuple[float, float, float, float]) -> ReIDDescriptor | None:
        if frame is None:
            return None
        try:
            import cv2
            import numpy as np
        except Exception:
            return None

        height, width = frame.shape[:2]
        x1, y1, x2, y2 = [int(round(value)) for value in bbox]
        x1 = max(0, min(width - 1, x1))
        x2 = max(0, min(width, x2))
        y1 = max(0, min(height - 1, y1))
        y2 = max(0, min(height, y2))
        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist_h = cv2.calcHist([hsv], [0], None, [12], [0, 180]).flatten()
        hist_s = cv2.calcHist([hsv], [1], None, [8], [0, 256]).flatten()
        vector = np.concatenate([hist_h, hist_s]).astype("float32")
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector = vector / norm
        return ReIDDescriptor(
            vector=[round(float(value), 5) for value in vector.tolist()],
            method=self.method,
        )

    def remember(self, visitor_id: str, descriptor: ReIDDescriptor | None, timestamp: datetime) -> None:
        if descriptor is not None:
            self.gallery[visitor_id] = (descriptor, timestamp)

    def match(self, descriptor: ReIDDescriptor | None, threshold: float = 0.82) -> str | None:
        if descriptor is None:
            return None
        best_visitor_id: str | None = None
        best_score = threshold
        for visitor_id, (known, _timestamp) in self.gallery.items():
            if len(known.vector) != len(descriptor.vector):
                continue
            score = sum(left * right for left, right in zip(known.vector, descriptor.vector))
            if score > best_score:
                best_score = score
                best_visitor_id = visitor_id
        return best_visitor_id
