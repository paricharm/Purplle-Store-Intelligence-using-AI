#!/usr/bin/env bash
set -euo pipefail

MODE="${MODE:-sample}"
OUTPUT="${OUTPUT:-data/output/generated_events.jsonl}"
STORE_ID="${STORE_ID:-STORE_BLR_002}"
CLIP_START="${CLIP_START:-2026-04-10T11:20:00Z}"
VIDEO_DIR="${VIDEO_DIR:-sample_data/store-intelligence-videos}"
POS_CSV="${POS_CSV:-POS - sample transactionsb1e826f.csv}"

mkdir -p "$(dirname "$OUTPUT")"

if [[ "$MODE" == "detect-all" ]]; then
  python -m pipeline.run_all \
    --video-dir "$VIDEO_DIR" \
    --store-id "$STORE_ID" \
    --clip-start "$CLIP_START" \
    --pos-csv "$POS_CSV" \
    --output "$OUTPUT"
else
  python -m pipeline.run \
    --mode "$MODE" \
    --store-id "$STORE_ID" \
    --clip-start "$CLIP_START" \
    --pos-csv "$POS_CSV" \
    --output "$OUTPUT"
fi
