from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.schemas import EventType
from pipeline.emit import JsonlEmitter, build_event
from pipeline.reid import OSNetReIdentifier
from pipeline.tracker import CentroidTracker, Detection, Track
from pipeline.zones import ZoneMapper

DEFAULT_DETECTOR_MODEL = "models/best.pt"


@dataclass
class TrackState:
    visitor_id: str
    last_zone_id: str | None = None
    zone_entered_at: datetime | None = None
    last_dwell_emit_at: datetime | None = None
    last_bbox: tuple[float, float, float, float] | None = None
    last_center_norm: tuple[float, float] | None = None
    last_x_norm: float | None = None
    last_y_norm: float | None = None
    has_entered: bool = False
    has_exited: bool = False
    session_seq: int = 0
    is_staff: bool = False
    role_label: str = "customer"
    role_confidence: float = 0.62
    role_source: str = "default_customer_when_no_staff_signal"
    role_signals: dict[str, float | bool | str] = field(default_factory=dict)
    reid_method: str = "not_computed"


@dataclass
class VideoProcessor:
    video_path: Path
    output_path: Path
    layout_path: Path
    store_id: str
    camera_id: str
    model_path: Path
    clip_start: datetime
    frame_stride: int = 5
    confidence_threshold: float = 0.05
    inference_imgsz: int = 960
    tracking_backend: str = "bytetrack"
    clip_set: str = "sample"
    states: dict[int, TrackState] = field(default_factory=dict)
    model_source_name: str = DEFAULT_DETECTOR_MODEL
    uses_open_vocab_detector: bool = False
    class_names: dict[int, str] = field(default_factory=dict)
    reid: OSNetReIdentifier = field(default_factory=OSNetReIdentifier)

    def run(self) -> int:
        try:
            import cv2
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "Detection requires requirements-pipeline.txt. Install it with "
                "`pip install -r requirements-pipeline.txt`. In Docker, also ensure "
                "Dockerfile.pipeline installs the OpenCV runtime libraries such as libxcb1."
            ) from exc

        model_source = self._resolve_model_source(self.model_path)
        self.model_source_name = model_source
        model = self._load_model(model_source, YOLO)
        self.class_names = self._model_class_names(model)
        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {self.video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 15
        width = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920
        height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080
        self._last_frame_width = width
        self._last_frame_height = height
        tracker = CentroidTracker()
        zones = ZoneMapper(self.layout_path, self.store_id)
        emitted = 0

        with JsonlEmitter(self.output_path) as emitter:
            frame_index = -1
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frame_index += 1
                if frame_index % self.frame_stride != 0:
                    continue

                timestamp = self.clip_start + timedelta(seconds=frame_index / fps)
                self._last_frame_index = frame_index
                self._last_frame_time_sec = frame_index / fps
                self._last_fps = fps
                detections = [
                    detection
                    for detection in self._detect_people(model, frame)
                    if zones.is_valid_person_detection(
                        self.camera_id,
                        detection.bbox,
                        width,
                        height,
                    )[0]
                ]
                queue_depth = 0
                if self.tracking_backend != "centroid" and all(
                    detection.track_id is not None for detection in detections
                ):
                    tracks = [
                        Track(track_id=int(detection.track_id), detection=detection)
                        for detection in detections
                        if detection.track_id is not None
                    ]
                else:
                    tracks = tracker.update(detections)

                for track in tracks:
                    x, y = track.detection.bottom_center
                    x_norm = x / width
                    y_norm = y / height
                    zone = zones.zone_for_point(self.camera_id, x_norm, y_norm)
                    if zone and "BILL" in zone.zone_id.upper():
                        queue_depth += 1

                for track in tracks:
                    for event in self._events_for_track(
                        frame=frame,
                        track_id=track.track_id,
                        detection=track.detection,
                        timestamp=timestamp,
                        width=width,
                        height=height,
                        zones=zones,
                        queue_depth=queue_depth,
                    ):
                        emitter.emit(event)
                        emitted += 1

        cap.release()
        return emitted

    def _detect_people(self, model: Any, frame: Any) -> list[Detection]:
        predict_args: dict[str, Any] = {
            "conf": self.confidence_threshold,
            "verbose": False,
            "imgsz": self.inference_imgsz,
            "agnostic_nms": True,
        }
        if self.tracking_backend != "centroid" and hasattr(model, "track"):
            tracker_name = (
                "bytetrack.yaml" if self.tracking_backend == "bytetrack" else "botsort.yaml"
            )
            results = model.track(
                frame,
                persist=True,
                tracker=tracker_name,
                **predict_args,
            )
        else:
            predict = getattr(model, "predict", model)
            results = predict(frame, **predict_args)
        detections: list[Detection] = []
        for result in results:
            result_names = self._result_class_names(result)
            for box in result.boxes:
                conf = float(box.conf[0])
                x1, y1, x2, y2 = [float(value) for value in box.xyxy[0].tolist()]
                class_id = int(box.cls[0]) if getattr(box, "cls", None) is not None else 0
                track_id = None
                if getattr(box, "id", None) is not None:
                    track_id = int(box.id[0])
                detections.append(
                    Detection(
                        bbox=(x1, y1, x2, y2),
                        confidence=conf,
                        class_id=class_id,
                        class_name=result_names.get(class_id) or self.class_names.get(class_id),
                        track_id=track_id,
                    )
                )
        return detections

    @staticmethod
    def _load_model(model_source: str, yolo_cls: Any) -> Any:
        return yolo_cls(model_source)

    @staticmethod
    def _resolve_model_source(model_path: Path) -> str:
        if model_path.exists():
            return str(model_path)
        default_path = Path(DEFAULT_DETECTOR_MODEL)
        if default_path.exists():
            return str(default_path)
        raise FileNotFoundError(
            f"Custom YOLOv8 detector not found: {model_path}. "
            f"Place your trained staff/customer weights at {DEFAULT_DETECTOR_MODEL}."
        )

    @staticmethod
    def _model_class_names(model: Any) -> dict[int, str]:
        names = getattr(model, "names", {}) or {}
        if isinstance(names, dict):
            return {int(key): str(value) for key, value in names.items()}
        return {index: str(value) for index, value in enumerate(names)}

    @staticmethod
    def _result_class_names(result: Any) -> dict[int, str]:
        names = getattr(result, "names", {}) or {}
        if isinstance(names, dict):
            return {int(key): str(value) for key, value in names.items()}
        return {index: str(value) for index, value in enumerate(names)}

    def _events_for_track(
        self,
        *,
        frame: Any,
        track_id: int,
        detection: Detection,
        timestamp: datetime,
        width: float,
        height: float,
        zones: ZoneMapper,
        queue_depth: int,
    ) -> list[dict[str, Any]]:
        state = self.states.setdefault(
            track_id,
            TrackState(visitor_id=f"VIS_{self.camera_id}_{track_id:05d}"),
        )
        x, y = detection.bottom_center
        x_norm = x / width
        y_norm = y / height
        state.last_bbox = detection.bbox
        state.last_center_norm = (x_norm, y_norm)
        role_label = (detection.class_name or "").strip().lower()
        state.is_staff = role_label == "staff"
        state.role_label = "staff" if state.is_staff else "customer"
        state.role_confidence = detection.confidence
        state.role_source = "custom_yolov8_class"
        state.role_signals = {
            "custom_class_id": detection.class_id,
            "custom_class_name": detection.class_name or "unknown",
        }
        descriptor = self.reid.describe(frame, detection.bbox)
        self.reid.remember(state.visitor_id, descriptor, timestamp)
        state.reid_method = descriptor.method if descriptor is not None else self.reid.method
        zone = zones.zone_for_point(self.camera_id, x_norm, y_norm)
        zone_id = zone.zone_id if zone else None
        events: list[dict[str, Any]] = []
        confidence = detection.confidence
        events.append(
            self._event(
                state,
                EventType.DETECTION,
                timestamp,
                zone_id,
                0,
                confidence,
                queue_depth=queue_depth if zone_id and "BILL" in zone_id.upper() else None,
                sku_zone=zone.sku_zone if zone else None,
                increment_session=False,
            )
        )

        entry_line = zones.entry_line(self.camera_id)
        if entry_line:
            orientation = entry_line.get("orientation", "horizontal")
            line = float(entry_line.get("position", 0.5))
            inbound_direction = entry_line.get("inbound_direction", "down")
            previous = state.last_x_norm if orientation == "vertical" else state.last_y_norm
            current = x_norm if orientation == "vertical" else y_norm
            if previous is None and zone_id == "ENTRY":
                state.has_entered = True
                events.append(self._event(state, EventType.ENTRY, timestamp, None, 0, confidence))
            elif previous is not None:
                crossed_positive = previous < line <= current
                crossed_negative = previous > line >= current
                inbound_positive = inbound_direction in {"down", "right"}
                if (inbound_positive and crossed_positive) or (
                    not inbound_positive and crossed_negative
                ):
                    event_type = EventType.REENTRY if state.has_entered and state.has_exited else EventType.ENTRY
                    state.has_entered = True
                    state.has_exited = False
                    events.append(self._event(state, event_type, timestamp, None, 0, confidence))
                elif (inbound_positive and crossed_negative) or (
                    not inbound_positive and crossed_positive
                ):
                    state.has_exited = True
                    events.append(self._event(state, EventType.EXIT, timestamp, None, 0, confidence))

        if zone_id != state.last_zone_id:
            if state.last_zone_id is not None:
                dwell_ms = self._dwell_ms(state, timestamp)
                events.append(
                    self._event(
                        state,
                        EventType.ZONE_EXIT,
                        timestamp,
                        state.last_zone_id,
                        dwell_ms,
                        confidence,
                    )
                )
            if zone_id is not None:
                event_type = (
                    EventType.BILLING_QUEUE_JOIN
                    if "BILL" in zone_id.upper() and queue_depth > 0
                    else EventType.ZONE_ENTER
                )
                state.zone_entered_at = timestamp
                state.last_dwell_emit_at = timestamp
                events.append(
                    self._event(
                        state,
                        event_type,
                        timestamp,
                        zone_id,
                        0,
                        confidence,
                        queue_depth=queue_depth if event_type == EventType.BILLING_QUEUE_JOIN else None,
                        sku_zone=zone.sku_zone if zone else None,
                    )
                )
            state.last_zone_id = zone_id

        if zone_id is not None and state.zone_entered_at and state.last_dwell_emit_at:
            if (timestamp - state.last_dwell_emit_at).total_seconds() >= 30:
                dwell_ms = self._dwell_ms(state, timestamp)
                state.last_dwell_emit_at = timestamp
                events.append(
                    self._event(
                        state,
                        EventType.ZONE_DWELL,
                        timestamp,
                        zone_id,
                        dwell_ms,
                        confidence,
                        sku_zone=zone.sku_zone if zone else None,
                    )
                )

        state.last_x_norm = x_norm
        state.last_y_norm = y_norm
        return events

    def _event(
        self,
        state: TrackState,
        event_type: EventType,
        timestamp: datetime,
        zone_id: str | None,
        dwell_ms: int,
        confidence: float,
        queue_depth: int | None = None,
        sku_zone: str | None = None,
        increment_session: bool = True,
    ) -> dict[str, Any]:
        if increment_session:
            state.session_seq += 1
        return build_event(
            store_id=self.store_id,
            camera_id=self.camera_id,
            visitor_id=state.visitor_id,
            event_type=event_type,
            timestamp=timestamp,
            zone_id=zone_id,
            dwell_ms=dwell_ms,
            is_staff=state.is_staff,
            confidence=confidence,
            metadata={
                "queue_depth": queue_depth,
                "sku_zone": sku_zone,
                "session_seq": state.session_seq,
                "camera_visitor_id": state.visitor_id,
                "bbox_xyxy": [round(value, 2) for value in state.last_bbox]
                if state.last_bbox
                else None,
                "center_norm": [round(value, 4) for value in state.last_center_norm]
                if state.last_center_norm
                else None,
                "frame_width": round(float(self._last_frame_width), 2)
                if hasattr(self, "_last_frame_width")
                else None,
                "frame_height": round(float(self._last_frame_height), 2)
                if hasattr(self, "_last_frame_height")
                else None,
                "frame_index": int(self._last_frame_index)
                if hasattr(self, "_last_frame_index")
                else None,
                "frame_time_sec": round(float(self._last_frame_time_sec), 4)
                if hasattr(self, "_last_frame_time_sec")
                else None,
                "fps": round(float(self._last_fps), 4)
                if hasattr(self, "_last_fps")
                else None,
                "person_role": state.role_label,
                "role_confidence": round(state.role_confidence, 4),
                "role_source": state.role_source,
                "role_signals": state.role_signals,
                "detector_model": self.model_source_name,
                "detector_family": "YOLOv8-custom-staff-customer",
                "detector_classes": list(self.class_names.values()) or ["customer", "person", "staff"],
                "custom_class_id": state.role_signals.get("custom_class_id"),
                "custom_class_name": state.role_signals.get("custom_class_name"),
                "inference_imgsz": self.inference_imgsz,
                "tracking_backend": self.tracking_backend,
                "reid_method": state.reid_method,
                "session_stitching_method": "cross_camera_time_route_zone",
                "clip_set": self.clip_set,
            },
        )

    @staticmethod
    def _dwell_ms(state: TrackState, timestamp: datetime) -> int:
        if not state.zone_entered_at:
            return 0
        return int((timestamp - state.zone_entered_at).total_seconds() * 1000)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YOLO-based CCTV event detection.")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("generated_events.jsonl"))
    parser.add_argument("--layout", type=Path, default=Path("config/store_layout.json"))
    parser.add_argument("--store-id", default="STORE_BLR_002")
    parser.add_argument("--camera-id", default="CAM_1")
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(DEFAULT_DETECTOR_MODEL),
        help=f"Local .pt file or Ultralytics weight name. Default: {DEFAULT_DETECTOR_MODEL}.",
    )
    parser.add_argument("--clip-start", default="2026-04-10T11:30:00Z")
    parser.add_argument("--frame-stride", type=int, default=5)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--tracker", choices=["botsort", "bytetrack", "centroid"], default="bytetrack")
    args = parser.parse_args()

    clip_start = datetime.fromisoformat(args.clip_start.replace("Z", "+00:00")).astimezone(UTC)
    count = VideoProcessor(
        video_path=args.video,
        output_path=args.output,
        layout_path=args.layout,
        store_id=args.store_id,
        camera_id=args.camera_id,
        model_path=args.model,
        clip_start=clip_start,
        frame_stride=args.frame_stride,
        confidence_threshold=args.conf,
        inference_imgsz=args.imgsz,
        tracking_backend=args.tracker,
    ).run()
    print({"events_written": count, "output": str(args.output)})


if __name__ == "__main__":
    main()
