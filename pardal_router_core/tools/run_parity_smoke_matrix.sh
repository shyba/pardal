#!/usr/bin/env bash
set -euo pipefail

# Runs the fixed parity smoke corpus across several Rust routing modes and writes a markdown report.
#
# This is an *extended* smoke intended to exercise:
# - sequential vs basic negotiation
# - ALL vs ALLMST (multi-pin nets)
#
# Usage:
#   run_parity_smoke_matrix.sh [seed_hex] [passes] [net_limit]
#
# Output:
#   pardal-pcb/pardal_router_core/build/parity_smoke_matrix_report.md

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CORE="$ROOT/pardal-pcb/pardal_router_core"
OUT="$CORE/build/parity_smoke_matrix_report.md"

seed="${1:-0xDEADBEEF}"
passes="${2:-1}"
net_limit="${3:-10}"

CORPUS=(
  "freerouting/tests/Issue313-FastTest.dsn"
  "freerouting/tests/Issue270-non-ansi_bracket.dsn"
  "freerouting/tests/Issue103-Board-Routed.dsn"
  "freerouting/tests/Issue209-split05.dsn"
  "freerouting/tests/empty_board.dsn"
)

CONFIGS=(
  "ALL|off"
  "ALL|basic"
  "ALLMST|basic"
)

mkdir -p "$(dirname "$OUT")"

echo "Building rust bins..." >&2
(cd "$CORE" && cargo build -q --bin pardal_parity_extract)

ts_ms() { date +%s%3N; }

json_get() {
  local json_file="$1"
  local key="$2"
  if [[ ! -f "$json_file" ]]; then
    echo "?"
    return 0
  fi
  "$CORE/target/debug/pardal_parity_extract" "$json_file" 2>/dev/null \
    | python3 -c 'import json,sys
try:
  j=json.load(sys.stdin)
except Exception:
  print("?"); sys.exit(0)
v=j.get(sys.argv[1])
print("?" if v is None else v)
' "$key" 2>/dev/null || echo "?"
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

declare -a TIMES=()

{
  echo "# Parity Smoke Matrix Report"
  echo ""
  echo "- seed: \`$seed\`"
  echo "- freerouting_passes: \`$passes\`"
  echo "- rust_net_limit: \`$net_limit\`"
  echo "- date: \`$(date -Is)\`"
  echo ""
  echo "## Results"
  echo ""
  echo "| Case | Mode | Negotiation | Time (ms) | Oracle incomplete | Oracle clr viol | Rust out unconn | Rust out clr viol | Notes |"
  echo "|---|---|---|---:|---:|---:|---:|---:|---|"
} >"$OUT"

for rel in "${CORPUS[@]}"; do
  dsn="$ROOT/$rel"
  if [[ ! -f "$dsn" ]]; then
    echo "Skipping missing: $rel" >&2
    continue
  fi
  base="$(basename "$dsn")"
  base_noext="${base%.*}"

  for cfg in "${CONFIGS[@]}"; do
    mode="${cfg%%|*}"
    nego="${cfg##*|}"
    tag="${mode}.${nego}"

    t0="$(ts_ms)"
    PARDAL_PARITY_ROUTE_MODE="$mode" PARDAL_PARITY_NEGOTIATION="$nego" PARDAL_PARITY_OUT_TAG="$tag" \
      bash "$CORE/tools/run_parity.sh" "$dsn" "$seed" "$passes" "$net_limit" >"$tmp/${base_noext}.${mode}.${nego}.log" 2>&1 || true
    t1="$(ts_ms)"
    dt="$((t1 - t0))"
    TIMES+=("$dt\t$rel\t$mode\t$nego")

    out_dir="$CORE/build/parity/$base_noext/$tag"
    oracle_stats="$out_dir/${base_noext}.oracle.stats.json"
    drc_rust="$out_dir/${base_noext}.rust.route.freerouting.drc.json"

    oracle_incomplete="?"
    oracle_clr="?"
    rust_unconn="?"
    rust_clr="?"
    notes=""

    if [[ -f "$oracle_stats" ]]; then
      oracle_incomplete="$(json_get "$oracle_stats" "connections_incomplete")"
      oracle_clr="$(json_get "$oracle_stats" "clearance_violations_total")"
    fi

    if [[ -f "$drc_rust" ]]; then
      rust_unconn="$(json_get "$drc_rust" "unconnected_items_total")"
      rust_clr="$(json_get "$drc_rust" "clearance_violations_total")"
    else
      notes="no Rust DSN output"
    fi

    printf "| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n" \
      "\`$rel\`" "\`$mode\`" "\`$nego\`" "$dt" "${oracle_incomplete:-?}" "${oracle_clr:-?}" \
      "${rust_unconn:-?}" "${rust_clr:-?}" "${notes:-}" >>"$OUT"
  done
done

{
  echo ""
  echo "## Slowest"
  echo ""
  printf '%b\n' "${TIMES[@]}" | sort -nr | head -n 10 | while IFS=$'\t' read -r ms dsn mode nego; do
    echo "- \`${ms}ms\` \`$dsn\` (\`$mode\` \`$nego\`)"
  done
} >>"$OUT"

echo "wrote: $OUT" >&2
