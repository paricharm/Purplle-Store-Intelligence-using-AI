from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


def ingest_jsonl(path: Path, api_url: str, batch_size: int) -> None:
    batch: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            batch.append(json.loads(line))
            if len(batch) >= batch_size:
                _post_batch(batch, api_url)
                batch = []
    if batch:
        _post_batch(batch, api_url)


def _post_batch(batch: list[dict], api_url: str) -> None:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/events/ingest",
        data=json.dumps(batch).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        print(response.read().decode("utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest JSONL events without third-party packages.")
    parser.add_argument("events", type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    ingest_jsonl(args.events, args.api_url, args.batch_size)
