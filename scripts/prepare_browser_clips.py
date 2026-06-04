from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def camera_id_from_filename(path: Path, fallback_index: int) -> str:
    stem = path.stem.lower()
    match = re.search(r"cam\s*[_ -]?(\d+)", stem)
    if match:
        return f"CAM_{match.group(1)}"
    if "billing" in stem:
        return "CAM_5"
    if "entry 1" in stem or "entry_1" in stem:
        return "CAM_3"
    if "entry 2" in stem or "entry_2" in stem:
        return "CAM_4"
    if "entry" in stem:
        return "CAM_3"
    if "zone" in stem:
        return "CAM_1"
    return f"CAM_{fallback_index}"


def remux_clip(source: Path, target: Path, overwrite: bool) -> None:
    if target.exists() and target.stat().st_size > 0 and not overwrite:
        print({"skipped": str(target)})
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    codec = video_codec(source)
    if codec == "h264":
        video_args = ["-c:v", "copy"]
    else:
        video_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
    command = ["ffmpeg", "-y" if overwrite else "-n", "-i", str(source), "-an", *video_args, "-movflags", "+faststart", str(target)]
    subprocess.run(command, check=True)
    print({"prepared": str(target), "source": str(source), "source_codec": codec})


def video_codec(source: Path) -> str:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "json",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    return str(streams[0].get("codec_name") or "unknown") if streams else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare browser-friendly faststart MP4 clips.")
    parser.add_argument("--clips-root", type=Path, default=Path("data/clips"))
    parser.add_argument("--output-root", type=Path, default=Path("data/browser_clips"))
    parser.add_argument("--clip-set", default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    folders = sorted(path for path in args.clips_root.iterdir() if path.is_dir())
    if args.clip_set:
        folders = [path for path in folders if path.name == args.clip_set]
    if not folders:
        raise SystemExit(f"No clip folders found under {args.clips_root}")

    for folder in folders:
        used: set[str] = set()
        for index, source in enumerate(sorted(folder.glob("*.mp4")), start=1):
            camera_id = camera_id_from_filename(source, index)
            if camera_id in used:
                continue
            used.add(camera_id)
            target = args.output_root / folder.name / f"{camera_id}.mp4"
            remux_clip(source, target, args.overwrite)


if __name__ == "__main__":
    main()
