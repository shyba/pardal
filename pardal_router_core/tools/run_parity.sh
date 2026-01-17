#!/usr/bin/env bash
set -euo pipefail

# Parity runner (early harness).
#
# Today, `pardal_route_dsn` is a limited router (sequential, net limit) and not FreeRouting-parity.
# This script exists to make it easy to compare *the same inputs/settings* against FreeRouting
# (oracle) while we implement parity phases.
#
# Usage:
#   run_parity.sh <path.dsn> [seed_hex] [max_passes] [net_limit]
#
# Outputs are written under `pardal-pcb/pardal_router_core/build/parity/<base>/`.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CORE="$ROOT/pardal-pcb/pardal_router_core"
OUT_BASE="$CORE/build/parity"

dsn="${1:-}"
seed="${2:-0xDEADBEEF}"
passes="${3:-8}"
net_limit="${4:-10}"

if [[ -z "$dsn" ]]; then
  echo "Usage: $0 <path.dsn> [seed_hex] [max_passes] [net_limit]" >&2
  exit 2
fi

dsn_abs="$(realpath "$dsn")"
base="$(basename "$dsn_abs")"
base_noext="${base%.*}"
tag="${PARDAL_PARITY_OUT_TAG:-}"
if [[ -n "$tag" ]]; then
  out_dir="$OUT_BASE/$base_noext/$tag"
else
  out_dir="$OUT_BASE/$base_noext"
fi
mkdir -p "$out_dir"

rm -f "$out_dir/${base_noext}.oracle."* 2>/dev/null || true
rm -rf "$out_dir/userdata" 2>/dev/null || true

echo "== Build rust bins ==" >&2
(cd "$CORE" && cargo build -q --bin pardal_dsn_check --bin pardal_route_dsn --bin pardal_dsn_to_ses)

echo "== Rust: dsn_check ==" >&2
"$CORE/target/debug/pardal_dsn_check" "$dsn_abs" --json --drc all >"$out_dir/${base_noext}.rust.dsn_check.json"

echo "== Rust: route_smoke (limited) ==" >&2
route_mode="${PARDAL_PARITY_ROUTE_MODE:-ALL}"
negotiation="${PARDAL_PARITY_NEGOTIATION:-off}"
PARDAL_ROUTE_SES_OUT="$out_dir/${base_noext}.rust.route.ses" \
PARDAL_ROUTE_DSN_OUT="$out_dir/${base_noext}.rust.route.dsn" \
  "$CORE/target/debug/pardal_route_dsn" "$dsn_abs" "$route_mode" auto auto "$net_limit" auto auto "$negotiation" \
  >"$out_dir/${base_noext}.rust.route.txt" 2>"$out_dir/${base_noext}.rust.route.err" || true

echo "== FreeRouting (oracle) ==" >&2
bash "$CORE/tools/freerouting_oracle.sh" "$dsn_abs" "$out_dir" "$seed" "$passes" 1 >/dev/null

echo "== FreeRouting: DRC on input DSN ==" >&2
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$out_dir":/mnt/out \
  -v "$dsn_abs":/mnt/in/board.dsn:ro \
  ee-freerouting-oracle:local \
  java -jar /app/freerouting-executable.jar \
    --gui-enabled=false \
    --api_server-enabled=false \
    --feature_flags-logging=0 \
    --usage_and_diagnostic_data-disableAnalytics=1 \
    --user_data_path=/tmp/freerouting_userdata \
    -de /mnt/in/board.dsn \
    -drc "/mnt/out/${base_noext}.oracle.input.freerouting.drc.json" \
  >/dev/null || true

if [[ -s "$out_dir/${base_noext}.rust.route.dsn" ]]; then
  echo "== FreeRouting: DRC on Rust output DSN ==" >&2
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$out_dir":/mnt/out \
    ee-freerouting-oracle:local \
    java -jar /app/freerouting-executable.jar \
      --gui-enabled=false \
      --api_server-enabled=false \
      --feature_flags-logging=0 \
      --usage_and_diagnostic_data-disableAnalytics=1 \
      --user_data_path=/tmp/freerouting_userdata \
      -de "/mnt/out/${base_noext}.rust.route.dsn" \
      -drc "/mnt/out/${base_noext}.rust.route.freerouting.drc.json" \
    >/dev/null || true

  echo "== Rust: dsn_check on Rust output DSN ==" >&2
  "$CORE/target/debug/pardal_dsn_check" "$out_dir/${base_noext}.rust.route.dsn" --json --drc all \
    >"$out_dir/${base_noext}.rust.route.dsn_check.json" 2>"$out_dir/${base_noext}.rust.route.dsn_check.err" || true
fi

echo "== Outputs ==" >&2
ls -1 "$out_dir" >&2

echo "" >&2
echo "== Summary ==" >&2
if [[ -f "$out_dir/${base_noext}.oracle.stats.json" ]]; then
  python3 - <<PY "$out_dir/${base_noext}.oracle.stats.json" >&2
import json, sys
p=sys.argv[1]
with open(p,'r',encoding='utf-8') as f:
    j=json.load(f)
def get(path, default=None):
    cur=j
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur=cur[k]
    return cur
print("oracle.connections.incomplete_count =", get(["connections","incomplete_count"]))
print("oracle.clearance_violations.total_count =", get(["clearance_violations","total_count"]))
print("oracle.layers.total_count =", get(["layers","total_count"]))
PY
fi

if [[ -f "$out_dir/${base_noext}.rust.route.txt" ]]; then
  req="$(rg -o 'requested: [0-9]+' -m 1 "$out_dir/${base_noext}.rust.route.txt" | awk '{print $2}' || true)"
  got="$(rg -o 'routed: [0-9]+' -m 1 "$out_dir/${base_noext}.rust.route.txt" | awk '{print $2}' || true)"
  echo "rust.route_smoke.requested = ${req:-?}" >&2
  echo "rust.route_smoke.routed = ${got:-?}" >&2
fi

if [[ -f "$out_dir/${base_noext}.rust.route.freerouting.drc.json" ]]; then
  python3 - <<PY "$out_dir/${base_noext}.rust.route.freerouting.drc.json" >&2
import json, sys
p=sys.argv[1]
with open(p,'r',encoding='utf-8') as f:
    j=json.load(f)
def n(key):
    v=j.get(key, [])
    return len(v) if isinstance(v, list) else None
print("freerouting_drc.unconnected_items =", n("unconnected_items"))
print("freerouting_drc.clearance_violations =", n("clearance_violations"))
PY
fi

if [[ -f "$out_dir/${base_noext}.oracle.input.freerouting.drc.json" ]]; then
  python3 - <<PY "$out_dir/${base_noext}.oracle.input.freerouting.drc.json" >&2
import json, sys
p=sys.argv[1]
with open(p,'r',encoding='utf-8') as f:
    j=json.load(f)
def n(key):
    v=j.get(key, [])
    return len(v) if isinstance(v, list) else None
print("freerouting_drc_input.unconnected_items =", n("unconnected_items"))
print("freerouting_drc_input.clearance_violations =", n("clearance_violations"))
PY
fi
