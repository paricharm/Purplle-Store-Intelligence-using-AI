from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests


def replay_events(path: Path, api_url: str, batch_size: int = 50, delay_seconds: float = 0.5) -> None:
    batch = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            batch.append(json.loads(line))
            if len(batch) >= batch_size:
                _post(batch, api_url)
                batch = []
                time.sleep(delay_seconds)
    if batch:
        _post(batch, api_url)


def _post(batch: list[dict], api_url: str) -> None:
    response = requests.post(f"{api_url.rstrip('/')}/events/ingest", json=batch, timeout=30)
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay JSONL events into the API.")
    parser.add_argument("--events", type=Path, default=Path("sample_data/sample_events.jsonl"))
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--delay-seconds", type=float, default=0.5)
    args = parser.parse_args()
    replay_events(args.events, args.api_url, args.batch_size, args.delay_seconds)
