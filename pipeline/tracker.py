from __future__ import annotations

from dataclasses import dataclass
from math import hypot


@dataclass
class Detection:
    bbox: tuple[float, float, float, float]
    confidence: float
    class_id: int = 0
    class_name: str | None = None
    track_id: int | None = None

    @property
    def centroid(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def bottom_center(self) -> tuple[float, float]:
        x1, _y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, y2)


@dataclass
class Track:
    track_id: int
    detection: Detection
    missed: int = 0


class CentroidTracker:
    """Small dependency-free tracker used when YOLO tracking IDs are unavailable."""

    def __init__(self, max_distance: float = 80.0, max_missed: int = 12) -> None:
        self.max_distance = max_distance
        self.max_missed = max_missed
        self.next_id = 1
        self.tracks: dict[int, Track] = {}

    def update(self, detections: list[Detection]) -> list[Track]:
        unmatched = detections[:]
        for track in list(self.tracks.values()):
            if not unmatched:
                track.missed += 1
                continue
            best = min(unmatched, key=lambda det: self._distance(track.detection, det))
            distance = self._distance(track.detection, best)
            if distance <= self.max_distance:
                track.detection = best
                track.missed = 0
                unmatched.remove(best)
            else:
                track.missed += 1

        for detection in unmatched:
            track_id = self.next_id
            self.next_id += 1
            self.tracks[track_id] = Track(track_id=track_id, detection=detection)

        for track_id in [tid for tid, track in self.tracks.items() if track.missed > self.max_missed]:
            del self.tracks[track_id]

        return list(self.tracks.values())

    @staticmethod
    def _distance(left: Detection, right: Detection) -> float:
        lx, ly = left.centroid
        rx, ry = right.centroid
        return hypot(lx - rx, ly - ry)
