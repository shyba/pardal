#!/usr/bin/env bash
set -euo pipefail

# Run FreeRouting headlessly (via Docker) as an "oracle" for DSN/SES parity checks.
#
# Outputs:
# - <out_dir>/<base>.oracle.routed.dsn  (routed design; DSN so FreeRouting DRC can load it)
# - <out_dir>/<base>.oracle.stats.json  (BoardStatistics JSON printed by FreeRouting)
# - <out_dir>/<base>.oracle.drc.json    (optional; DRC JSON on the routed output)
#
# Usage:
#   freerouting_oracle.sh <path.dsn> <out_dir> [seed_hex] [max_passes] [threads]
#
# Notes:
# - We use the local FreeRouting Dockerfile in `freerouting/` (Java 25 required).
# - CLI mode requires both GUI and API disabled.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FR_DIR="$ROOT/freerouting"
IMG_TAG="${FREEROUTING_ORACLE_IMAGE:-ee-freerouting-oracle:local}"

dsn="${1:-}"
out_dir="${2:-}"
seed="${3:-0xDEADBEEF}"
max_passes="${4:-8}"
threads="${5:-1}"

if [[ -z "$dsn" || -z "$out_dir" ]]; then
  echo "Usage: $0 <path.dsn> <out_dir> [seed_hex] [max_passes] [threads]" >&2
  exit 2
fi

if [[ ! -f "$dsn" ]]; then
  echo "Input DSN not found: $dsn" >&2
  exit 2
fi

mkdir -p "$out_dir"

base="$(basename "$dsn")"
base_noext="${base%.*}"

dsn_abs="$(realpath "$dsn")"
out_abs="$(realpath "$out_dir")"

routed_out="$out_abs/${base_noext}.oracle.routed.dsn"
stats_out="$out_abs/${base_noext}.oracle.stats.json"
drc_out="$out_abs/${base_noext}.oracle.drc.json"
raw_out="$out_abs/${base_noext}.oracle.raw.txt"

if ! docker image inspect "$IMG_TAG" >/dev/null 2>&1; then
  echo "Building FreeRouting oracle image: $IMG_TAG" >&2
  docker build -t "$IMG_TAG" "$FR_DIR" >/dev/null
fi

work_in="/mnt/in"
work_out="/mnt/out"
user_data="/tmp/freerouting_userdata"

# Route DSN -> routed DSN (so DRC can load it), capture BoardStatistics JSON from stdout.
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$dsn_abs":"$work_in/board.dsn":ro \
  -v "$out_abs":"$work_out" \
  "$IMG_TAG" \
  java -jar /app/freerouting-executable.jar \
    --gui-enabled=false \
    --api_server-enabled=false \
    --feature_flags-logging=0 \
    --usage_and_diagnostic_data-disableAnalytics=1 \
    --user_data_path="$user_data" \
    -de "$work_in/board.dsn" \
    -do "$work_out/board.routed.dsn" \
    -mp "$max_passes" \
    -mt "$threads" \
    -random_seed "$seed" \
  >"$raw_out"

# Extract the JSON stats object from FreeRouting output (it prints logs before JSON).
awk 'BEGIN{inside=0} /^[[:space:]]*{/ {inside=1} {if(inside) print}' "$raw_out" >"$stats_out"
if [[ ! -s "$stats_out" ]]; then
  echo "error: failed to extract JSON stats from $raw_out" >&2
  exit 1
fi

if [[ -f "$out_abs/board.routed.dsn" ]]; then
  mv -f "$out_abs/board.routed.dsn" "$routed_out"
fi

if [[ ! -s "$routed_out" ]]; then
  rm -f "$routed_out" 2>/dev/null || true
  echo "warn: FreeRouting did not produce a routed DSN (likely not COMPLETED); keeping stats only" >&2
fi

# DRC on the routed design (best-effort; only if the routed DSN exists).
if [[ -s "$routed_out" ]]; then
  set +e
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$out_abs":"$work_out" \
    "$IMG_TAG" \
    java -jar /app/freerouting-executable.jar \
      --gui-enabled=false \
      --api_server-enabled=false \
      --feature_flags-logging=0 \
      --usage_and_diagnostic_data-disableAnalytics=1 \
      --user_data_path="$user_data" \
      -de "$work_out/$(basename "$routed_out")" \
      -drc "$work_out/board.drc.json" \
    >/dev/null
  rc=$?
  set -e

  if [[ $rc -eq 0 && -f "$out_abs/board.drc.json" ]]; then
    mv -f "$out_abs/board.drc.json" "$drc_out"
  else
    rm -f "$out_abs/board.drc.json" 2>/dev/null || true
    echo "warn: FreeRouting DRC step failed (rc=$rc) for $routed_out" >&2
  fi
fi

if [[ -s "$routed_out" ]]; then
  echo "$routed_out"
fi
