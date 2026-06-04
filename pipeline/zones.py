from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STORE_ALIASES = {
    "STORE_BLR_002": "ST1008",
}


@dataclass(frozen=True)
class Zone:
    zone_id: str
    camera_ids: set[str]
    polygon: list[tuple[float, float]]
    sku_zone: str | None = None


def load_store_layout(path: Path, store_id: str) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        layout = json.load(handle)
    stores = layout["stores"]
    return stores.get(store_id) or stores[STORE_ALIASES.get(store_id, store_id)]


def load_zones(path: Path, store_id: str) -> list[Zone]:
    store = load_store_layout(path, store_id)
    zones = []
    for raw in store.get("zones", []):
        zones.append(
            Zone(
                zone_id=raw["zone_id"],
                camera_ids=set(raw.get("camera_ids", [])),
                polygon=[tuple(point) for point in raw["polygon"]],
                sku_zone=raw.get("sku_zone"),
            )
        )
    return zones


def point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, point in enumerate(polygon):
        xi, yi = point
        xj, yj = polygon[j]
        intersects = (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


class ZoneMapper:
    def __init__(self, layout_path: Path, store_id: str) -> None:
        self.store = load_store_layout(layout_path, store_id)
        self.zones = load_zones(layout_path, store_id)

    def zone_for_point(self, camera_id: str, x_norm: float, y_norm: float) -> Zone | None:
        for zone in self.zones:
            if camera_id in zone.camera_ids and point_in_polygon(x_norm, y_norm, zone.polygon):
                return zone
        return None

    def entry_line(self, camera_id: str) -> dict[str, Any] | None:
        camera = self.store.get("cameras", {}).get(camera_id, {})
        return camera.get("entry_line")

    def detection_filter(self, camera_id: str) -> dict[str, Any]:
        camera = self.store.get("cameras", {}).get(camera_id, {})
        return camera.get("detection_filter", {})

    def is_valid_person_detection(
        self,
        camera_id: str,
        bbox: tuple[float, float, float, float],
        frame_width: float,
        frame_height: float,
    ) -> tuple[bool, str | None]:
        filters = self.detection_filter(camera_id)
        if not filters:
            return True, None

        x1, y1, x2, y2 = bbox
        width_norm = max(0.0, (x2 - x1) / frame_width)
        height_norm = max(0.0, (y2 - y1) / frame_height)
        bottom_y_norm = y2 / frame_height
        center_x_norm = ((x1 + x2) / 2) / frame_width
        center_y_norm = ((y1 + y2) / 2) / frame_height

        min_bottom = filters.get("min_bottom_y_norm")
        if min_bottom is not None and bottom_y_norm < float(min_bottom):
            return False, "bottom_center_above_walkable_floor"

        min_height = filters.get("min_height_norm")
        if min_height is not None and height_norm < float(min_height):
            return False, "box_too_short_for_camera_person"

        max_width = filters.get("max_width_norm")
        if max_width is not None and width_norm > float(max_width):
            return False, "box_too_wide_for_single_person"

        for polygon in filters.get("ignore_polygons", []):
            normalized_polygon = [tuple(point) for point in polygon]
            if point_in_polygon(center_x_norm, center_y_norm, normalized_polygon):
                return False, "center_inside_ignore_polygon"

        return True, None
