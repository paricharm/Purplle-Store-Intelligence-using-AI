from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


ENTRY_CAMERAS = {"CAM_3"}
MAIN_FLOOR_CAMERAS = {"CAM_1", "CAM_2"}
BILLING_CAMERAS = {"CAM_5", "CAM_4"}


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso_ts(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@dataclass
class TrackSummary:
    key: tuple[str, str]
    camera_id: str
    local_visitor_id: str
    first_ts: datetime
    last_ts: datetime
    events: list[dict[str, Any]]
    zones: set[str] = field(default_factory=set)
    is_staff: bool = False
    staff_event_count: int = 0
    non_staff_event_count: int = 0
    has_entry: bool = False
    has_exit: bool = False
    start_center: tuple[float, float] | None = None
    end_center: tuple[float, float] | None = None


@dataclass
class Session:
    visitor_id: str
    first_ts: datetime
    last_ts: datetime
    cameras: set[str] = field(default_factory=set)
    zones: set[str] = field(default_factory=set)
    is_staff: bool = False
    has_entry: bool = False
    has_billing: bool = False
    local_track_count: int = 0
    staff_track_count: int = 0
    non_staff_track_count: int = 0
    last_seen_by_camera: dict[str, datetime] = field(default_factory=dict)


def load_events(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in sorted(events, key=lambda row: row["timestamp"]):
            handle.write(json.dumps(event, sort_keys=True) + "\n")


def summarize_tracks(events: list[dict[str, Any]]) -> list[TrackSummary]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for event in events:
        metadata = event.get("metadata") or {}
        local_id = metadata.get("camera_visitor_id") or event["visitor_id"]
        key = (event["camera_id"], local_id)
        grouped.setdefault(key, []).append(event)

    summaries = []
    for key, rows in grouped.items():
        rows.sort(key=lambda row: row["timestamp"])
        first_ts = parse_ts(rows[0]["timestamp"])
        last_ts = parse_ts(rows[-1]["timestamp"])
        start_center = _center(rows[0])
        end_center = _center(rows[-1])
        staff_event_count = sum(1 for row in rows if row.get("is_staff"))
        non_staff_event_count = len(rows) - staff_event_count
        summaries.append(
            TrackSummary(
                key=key,
                camera_id=key[0],
                local_visitor_id=key[1],
                first_ts=first_ts,
                last_ts=last_ts,
                events=rows,
                zones={row["zone_id"] for row in rows if row.get("zone_id")},
                is_staff=staff_event_count > non_staff_event_count,
                staff_event_count=staff_event_count,
                non_staff_event_count=non_staff_event_count,
                has_entry=any(row["event_type"] == "ENTRY" for row in rows),
                has_exit=any(row["event_type"] == "EXIT" for row in rows),
                start_center=start_center,
                end_center=end_center,
            )
        )
    return sorted(summaries, key=lambda summary: summary.first_ts)


def stitch_events(
    events: list[dict[str, Any]],
    max_gap_seconds: int = 150,
    same_camera_fragment_gap_seconds: int = 15,
) -> list[dict[str, Any]]:
    summaries = summarize_tracks(events)
    sessions: list[Session] = []
    assignments: dict[tuple[str, str], str] = {}

    for track in summaries:
        session = _choose_session(
            track,
            sessions,
            max_gap_seconds=max_gap_seconds,
            same_camera_fragment_gap_seconds=same_camera_fragment_gap_seconds,
        )
        if session is None:
            session = _new_session(track)
            sessions.append(session)
        _attach_track(session, track)
        assignments[track.key] = session.visitor_id

    stitched = []
    seq_by_session: dict[str, int] = {}
    staff_by_session = {
        session.visitor_id: session.staff_track_count > session.non_staff_track_count
        for session in sessions
    }
    for event in sorted(events, key=lambda row: row["timestamp"]):
        metadata = event.get("metadata") or {}
        local_id = metadata.get("camera_visitor_id") or event["visitor_id"]
        key = (event["camera_id"], local_id)
        visitor_id = assignments.get(key, event["visitor_id"])
        seq_by_session[visitor_id] = seq_by_session.get(visitor_id, 0) + 1
        session_is_staff = bool(staff_by_session.get(visitor_id, event.get("is_staff", False)))

        updated_metadata = {
            **metadata,
            "camera_visitor_id": local_id,
            "pre_stitch_visitor_id": event["visitor_id"],
            "session_seq": seq_by_session[visitor_id],
            "stitching_method": "time_camera_zone_baseline",
            "local_person_role": metadata.get("person_role"),
            "person_role": "staff" if session_is_staff else "customer",
            "session_role_source": "cross_camera_session_majority",
        }
        stitched.append(
            {
                **event,
                "visitor_id": visitor_id,
                "is_staff": session_is_staff,
                "metadata": updated_metadata,
            }
        )
    return stitched


def stitch_file(input_path: Path, output_path: Path) -> int:
    events = load_events(input_path)
    stitched = stitch_events(events)
    write_events(output_path, stitched)
    return len(stitched)


def _choose_session(
    track: TrackSummary,
    sessions: list[Session],
    *,
    max_gap_seconds: int,
    same_camera_fragment_gap_seconds: int,
) -> Session | None:
    if track.has_entry and track.camera_id in ENTRY_CAMERAS:
        return None

    candidates: list[tuple[float, Session]] = []
    for session in sessions:
        if session.local_track_count >= 12:
            continue
        gap = (track.first_ts - session.last_ts).total_seconds()
        if gap < -10 or gap > max_gap_seconds:
            continue

        if track.camera_id in session.last_seen_by_camera:
            camera_gap = (track.first_ts - session.last_seen_by_camera[track.camera_id]).total_seconds()
            if camera_gap < -5 or camera_gap > same_camera_fragment_gap_seconds:
                continue

        route_score = _route_score(track.camera_id, session)
        if route_score < 0:
            continue

        distance_penalty = _center_penalty(track, session)
        candidates.append((route_score + abs(gap) / 600 + distance_penalty, session))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _route_score(camera_id: str, session: Session) -> float:
    if camera_id in ENTRY_CAMERAS:
        return 0.2 if camera_id in session.cameras else 0.6
    if camera_id in MAIN_FLOOR_CAMERAS:
        return 0.0 if session.has_entry else 0.4
    if camera_id in BILLING_CAMERAS:
        if session.has_entry or session.zones:
            return 0.1
        return 0.7
    return 0.5


def _center_penalty(track: TrackSummary, session: Session) -> float:
    # Keep this intentionally weak: camera transitions do not share coordinates.
    if track.camera_id in session.last_seen_by_camera:
        return 0.05
    return 0.0


def _new_session(track: TrackSummary) -> Session:
    seed = f"{track.camera_id}|{track.local_visitor_id}|{iso_ts(track.first_ts)}"
    suffix = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    return Session(
        visitor_id=f"VIS_{suffix}",
        first_ts=track.first_ts,
        last_ts=track.last_ts,
    )


def _attach_track(session: Session, track: TrackSummary) -> None:
    session.last_ts = max(session.last_ts, track.last_ts)
    session.cameras.add(track.camera_id)
    session.zones.update(track.zones)
    track_staff = track.is_staff or _behavior_staff_signal(session, track)
    session.is_staff = session.is_staff or track_staff
    session.has_entry = session.has_entry or track.has_entry
    session.has_billing = session.has_billing or "BILLING" in track.zones
    session.local_track_count += 1
    if track_staff:
        session.staff_track_count += 1
    else:
        session.non_staff_track_count += 1
    session.last_seen_by_camera[track.camera_id] = track.last_ts


def _behavior_staff_signal(session: Session, track: TrackSummary) -> bool:
    camera_count = len(session.cameras | {track.camera_id})
    duration_seconds = (max(session.last_ts, track.last_ts) - session.first_ts).total_seconds()
    zone_count = len(session.zones | track.zones)
    # Store staff often traverse several cameras/zones and remain visible longer than a
    # short customer shopping path. This is a weak fallback only; visual uniform signals
    # remain the primary staff classifier.
    return (
        "SERVICE_AREA" in (session.zones | track.zones)
        and camera_count >= 4
        and zone_count >= 4
        and duration_seconds >= 300
    ) or (
        camera_count >= 4
        and zone_count >= 4
        and duration_seconds >= 240
    )


def _center(event: dict[str, Any]) -> tuple[float, float] | None:
    center = (event.get("metadata") or {}).get("center_norm")
    if not isinstance(center, list) or len(center) != 2:
        return None
    return float(center[0]), float(center[1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Stitch camera-local visitor IDs into sessions.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count = stitch_file(args.input, args.output)
    print({"stitched_events": count, "output": str(args.output)})


if __name__ == "__main__":
    main()
