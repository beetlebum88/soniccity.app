#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${1:-"$ROOT/logs/target_places_audio_pipeline.log"}"

cd "$ROOT"
mkdir -p "$ROOT/logs"

{
  echo "[PIPELINE] started $(date)"
  echo "[PIPELINE] collect target places"
  env PYTHONUNBUFFERED=1 .venv/bin/python -u collect_target_city_places.py --sleep 1.0 --save-every 1

  echo "[PIPELINE] prefetch place images"
  env PYTHONUNBUFFERED=1 .venv/bin/python -u prefetch_place_images.py --kind place --lang en --only-missing --sleep 0.08

  echo "[PIPELINE] generate target city/place audio"
  env PYTHONUNBUFFERED=1 .venv/bin/python -u bulk_generate_country_audio.py \
    --mode target-cities \
    --include-places \
    --audio-version v7 \
    --langs en,fr,es,it,ua,de \
    --genders female,male \
    --source-mode linked-local \
    --edge-rate=-6% \
    --edge-pitch=+1Hz \
    --edge-volume=+0% \
    --edge-concurrency 2

  echo "[PIPELINE] finished $(date)"
} >> "$LOG" 2>&1
