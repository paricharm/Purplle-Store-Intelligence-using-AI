from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RoleClassification:
    label: str
    is_staff: bool
    confidence: float
    source: str
    signals: dict[str, float | bool | str]


def classify_person_role(
    frame: Any,
    bbox: tuple[float, float, float, float],
    camera_id: str | None = None,
    center_norm: tuple[float, float] | None = None,
) -> RoleClassification:
    """Classify a detected person as anonymous staff/customer.

    This is role identity, not face identity. The detector emits one person box per
    person; this function adds the challenge-required staff/customer flag using
    transparent CCTV cues that can be explained during review.
    """

    default = RoleClassification(
        label="customer",
        is_staff=False,
        confidence=0.62,
        source="default_customer_when_no_staff_signal",
        signals={},
    )
    if frame is None:
        return default

    try:
        import cv2
        import numpy as np
    except ImportError:
        return default

    height, width = frame.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in bbox]
    x1 = max(0, min(width - 1, x1))
    x2 = max(0, min(width, x2))
    y1 = max(0, min(height - 1, y1))
    y2 = max(0, min(height, y2))
    if x2 <= x1 or y2 <= y1:
        return default

    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return default

    crop_h = crop.shape[0]
    torso = crop[int(crop_h * 0.25) : int(crop_h * 0.75), :]
    if torso.size == 0:
        torso = crop
    torso_w = torso.shape[1]
    if torso_w > 4:
        torso = torso[:, int(torso_w * 0.25) : int(torso_w * 0.75)]

    hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
    # OpenCV hue range is 0-179. This catches purple/magenta uniform-like clothing
    # while avoiding white shelves and common skin tones.
    purple_mask = cv2.inRange(hsv, np.array([120, 45, 35]), np.array([165, 255, 255]))
    purple_ratio = float((purple_mask > 0).mean())
    dark_mask = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([179, 95, 70]))
    dark_ratio = float((dark_mask > 0).mean())

    head = crop[: max(1, int(crop_h * 0.35)), :]
    gray_head = cv2.cvtColor(head, cv2.COLOR_BGR2GRAY)
    head_sharpness = float(cv2.Laplacian(gray_head, cv2.CV_64F).var())

    camera_hint = False
    service_area_hint = camera_id == "CAM_4"
    billing_counter_hint = False
    if camera_id == "CAM_5" and center_norm is not None:
        x_norm, y_norm = center_norm
        billing_counter_hint = 0.18 <= x_norm <= 0.48 and 0.20 <= y_norm <= 0.80
        camera_hint = billing_counter_hint
    if service_area_hint:
        camera_hint = True

    score = 0.0
    if purple_ratio >= 0.32:
        score += 0.75
    elif purple_ratio >= 0.18:
        score += 0.45
    if dark_ratio >= 0.58 and (service_area_hint or billing_counter_hint):
        score += 0.45
    elif dark_ratio >= 0.42 and (service_area_hint or billing_counter_hint):
        score += 0.28

    if head_sharpness >= 160 and purple_ratio >= 0.12:
        score += 0.2
    if billing_counter_hint and purple_ratio >= 0.12:
        score += 0.12
    if service_area_hint and purple_ratio >= 0.08:
        score += 0.16
    if head_sharpness >= 140 and dark_ratio >= 0.45 and (service_area_hint or billing_counter_hint):
        score += 0.12

    signals: dict[str, float | bool | str] = {
        "purple_ratio": round(purple_ratio, 4),
        "dark_uniform_ratio": round(dark_ratio, 4),
        "head_sharpness": round(head_sharpness, 2),
        "camera_hint": camera_hint,
        "service_area_hint": service_area_hint,
        "billing_counter_hint": billing_counter_hint,
    }
    if score >= 0.65:
        return RoleClassification(
            label="staff",
            is_staff=True,
            confidence=min(0.95, 0.55 + score),
            source="uniform_color_position_heuristic",
            signals=signals,
        )

    customer_confidence = 0.72 if purple_ratio < 0.08 else 0.62
    return RoleClassification(
        label="customer",
        is_staff=False,
        confidence=customer_confidence,
        source="no_staff_signal",
        signals=signals,
    )


def classify_staff(
    frame: Any,
    bbox: tuple[float, float, float, float],
    camera_id: str | None = None,
    center_norm: tuple[float, float] | None = None,
) -> tuple[bool, float]:
    """Backwards-compatible staff classifier.

    The challenge footage is anonymised for customers, and the business requirement only
    needs an `is_staff` flag. This baseline does not identify faces. It uses transparent
    visual/positional cues that can be defended in CHOICES.md:

    - purple/magenta uniform-like torso color, common for this store context
    - sharper unblurred head region only as a weak supporting signal, not identity
    - optional camera-position hints for service/billing areas
    """
    role = classify_person_role(frame, bbox, camera_id, center_norm)
    return role.is_staff, role.confidence
