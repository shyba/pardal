#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
OUT_DIR="$ROOT/pardal-pcb/pardal_router_core/build/corpus"

SES_SMOKE=0
LIMIT=0
DRC_MODE="all"
SLOW_N=20
DSN_TIMEOUT_S=0
ROUTE=0
ROUTE_PITCH="auto"
ROUTE_VIA_COST="5"
ROUTE_NET_LIMIT="10"
ROUTE_BRUSH="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ses-smoke) SES_SMOKE=1; shift ;;
    --limit) LIMIT="${2:-0}"; shift 2 ;;
    --drc) DRC_MODE="${2:-all}"; shift 2 ;;
    --slow) SLOW_N="${2:-20}"; shift 2 ;;
    --dsn-timeout) DSN_TIMEOUT_S="${2:-0}"; shift 2 ;;
    --route) ROUTE=1; shift ;;
    --route-pitch) ROUTE_PITCH="${2:-2.0}"; shift 2 ;;
    --route-via-cost) ROUTE_VIA_COST="${2:-5}"; shift 2 ;;
    --route-net-limit) ROUTE_NET_LIMIT="${2:-10}"; shift 2 ;;
    --route-brush) ROUTE_BRUSH="${2:-0}"; shift 2 ;;
    --help|-h)
      echo "Usage: $0 [--ses-smoke] [--limit N] [glob...]" >&2
      echo "Default glob: freerouting/tests/*.dsn" >&2
      echo "Options:" >&2
      echo "  --drc all|copper|keepout|boundary|areas|none (default: all)" >&2
      echo "  --slow N  Print N slowest DSNs (default: 20)" >&2
      echo "  --dsn-timeout SECONDS  Per-DSN timeout (default: 0 = none)" >&2
      echo "  --route  Also run a routing smoke test (ALL mode)" >&2
      echo "  --route-pitch FLOAT|auto  Route grid pitch in DSN units (default: auto)" >&2
      echo "  --route-via-cost INT  Via transition cost (default: 5)" >&2
      echo "  --route-net-limit INT  Max nets to attempt in ALL mode (default: 10)" >&2
      echo "  --route-brush INT  Commit brush radius in grid cells (default: 0)" >&2
      exit 0
      ;;
    *) break ;;
  esac
done

GLOBS=("$@")
if [[ ${#GLOBS[@]} -eq 0 ]]; then
  GLOBS=("freerouting/tests/*.dsn")
fi

mkdir -p "$OUT_DIR"

count=0
fail=0
skip=0
route_fail=0
route_partial=0
route_ok=0

declare -a TIMES=()
declare -a TIMES_ROUTE=()

now_ms() {
  # Linux: milliseconds since epoch
  date +%s%3N
}

BIN_DIR="$ROOT/pardal-pcb/pardal_router_core/target/debug"
DSN_CHECK_BIN="$BIN_DIR/pardal_dsn_check"
ROUTE_BIN="$BIN_DIR/pardal_route_dsn"

run_dsn_check() {
  local dsn_path="$1"
  local json_out="$2"
  local err_out="$3"
  if [[ "$DSN_TIMEOUT_S" -gt 0 ]] && command -v timeout >/dev/null 2>&1; then
    timeout "${DSN_TIMEOUT_S}" "$DSN_CHECK_BIN" "$dsn_path" --json --drc "$DRC_MODE" > "$json_out" 2> "$err_out"
  else
    "$DSN_CHECK_BIN" "$dsn_path" --json --drc "$DRC_MODE" > "$json_out" 2> "$err_out"
  fi
}

run_route_smoke() {
  local dsn_path="$1"
  local out_txt="$2"
  local err_out="$3"
  if [[ "$DSN_TIMEOUT_S" -gt 0 ]] && command -v timeout >/dev/null 2>&1; then
    timeout "${DSN_TIMEOUT_S}" "$ROUTE_BIN" "$dsn_path" ALL "$ROUTE_PITCH" "$ROUTE_VIA_COST" "$ROUTE_NET_LIMIT" "$ROUTE_BRUSH" > "$out_txt" 2> "$err_out"
  else
    "$ROUTE_BIN" "$dsn_path" ALL "$ROUTE_PITCH" "$ROUTE_VIA_COST" "$ROUTE_NET_LIMIT" "$ROUTE_BRUSH" > "$out_txt" 2> "$err_out"
  fi
}

(
  cd "$ROOT/pardal-pcb/pardal_router_core"
  cargo build -q --bin pardal_dsn_check
  if [[ "$ROUTE" -eq 1 ]]; then
    cargo build -q --bin pardal_route_dsn
  fi
)

for g in "${GLOBS[@]}"; do
  for dsn in $g; do
    [[ -f "$ROOT/$dsn" ]] || continue
    # Some corpora contain mislabeled/binary `.dsn` files (e.g. OLE documents).
    # Skip anything that doesn't look like a Specctra DSN header.
    if ! head -c 4096 "$ROOT/$dsn" | tr -d '\000' | grep -qi "(pcb"; then
      echo "SKIP: $dsn (no '(pcb' header)" >&2
      skip=$((skip+1))
      continue
    fi
    base="$(basename "$dsn")"
    json_out="$OUT_DIR/${base}.json"
    echo "dsn_check: $dsn -> $(realpath --relative-to="$ROOT" "$json_out")" >&2
    err_out="$OUT_DIR/${base}.err"
    t0="$(now_ms)"
    if ! run_dsn_check "$ROOT/$dsn" "$json_out" "$err_out"; then
      echo "FAILED: $dsn (see $(realpath --relative-to="$ROOT" "$err_out"))" >&2
      rm -f "$json_out"
      count=$((count+1))
      fail=$((fail+1))
      if [[ "$LIMIT" -gt 0 && "$count" -ge "$LIMIT" ]]; then
        exit 0
      fi
      continue
    fi
    t1="$(now_ms)"
    dt="$((t1 - t0))"
    TIMES+=("$dt\t$dsn")
    rm -f "$err_out"

    if [[ "$ROUTE" -eq 1 ]]; then
      route_out="$OUT_DIR/${base}.route.txt"
      route_err="$OUT_DIR/${base}.route.err"
      echo "route_smoke: $dsn -> $(realpath --relative-to="$ROOT" "$route_out")" >&2
      t0="$(now_ms)"
      if ! run_route_smoke "$ROOT/$dsn" "$route_out" "$route_err"; then
        echo "ROUTE FAILED: $dsn (see $(realpath --relative-to="$ROOT" "$route_err"))" >&2
        route_fail=$((route_fail+1))
      else
        rm -f "$route_err"
        req="$(rg -o 'requested: [0-9]+' -m 1 "$route_out" | awk '{print $2}' || echo 0)"
        got="$(rg -o 'routed: [0-9]+' -m 1 "$route_out" | awk '{print $2}' || echo 0)"
        if [[ "$req" -eq 0 ]]; then
          route_ok=$((route_ok+1))
        elif [[ "$got" -eq 0 ]]; then
          echo "ROUTE WARN: $dsn routed 0/$req (see $(realpath --relative-to="$ROOT" "$route_out"))" >&2
          route_fail=$((route_fail+1))
        elif [[ "$got" -lt "$req" ]]; then
          route_partial=$((route_partial+1))
        else
          route_ok=$((route_ok+1))
        fi
      fi
      t1="$(now_ms)"
      dt="$((t1 - t0))"
      TIMES_ROUTE+=("$dt\t$dsn")
    fi

    if [[ "$SES_SMOKE" -eq 1 ]]; then
      ses_out="$OUT_DIR/${base}.ses"
      echo "ses_smoke: $dsn -> $(realpath --relative-to="$ROOT" "$ses_out")" >&2
      bash "$ROOT/pardal-pcb/pardal_router_core/tools/freerouting_ses_smoke.sh" "$dsn" "$(realpath --relative-to="$ROOT" "$ses_out")" >/dev/null
    fi

    count=$((count+1))
    if [[ "$LIMIT" -gt 0 && "$count" -ge "$LIMIT" ]]; then
      break
    fi
  done
done

total="$count"
{
  echo ""
  echo "Summary:"
  echo "  drc_mode: $DRC_MODE"
  if [[ "$ROUTE" -eq 1 ]]; then
    echo "  route_smoke: enabled (pitch=$ROUTE_PITCH via_cost=$ROUTE_VIA_COST net_limit=$ROUTE_NET_LIMIT brush=$ROUTE_BRUSH)"
    echo "  route_ok: $route_ok"
    echo "  route_partial: $route_partial"
    echo "  route_failed: $route_fail"
  fi
  echo "  ok: $((total - fail))"
  echo "  failed: $fail"
  echo "  skipped: $skip"
  echo ""
  echo "Slowest ${SLOW_N}:"
} >&2

if [[ "${#TIMES[@]}" -gt 0 ]]; then
  printf '%b\n' "${TIMES[@]}" | sort -nr | head -n "$SLOW_N" | while IFS=$'\t' read -r ms dsn; do
    echo "  ${ms}ms  ${dsn}" >&2
  done
fi

if [[ "$ROUTE" -eq 1 ]]; then
  echo "" >&2
  echo "Slowest ${SLOW_N} (route_smoke):" >&2
  if [[ "${#TIMES_ROUTE[@]}" -gt 0 ]]; then
    printf '%b\n' "${TIMES_ROUTE[@]}" | sort -nr | head -n "$SLOW_N" | while IFS=$'\t' read -r ms dsn; do
      echo "  ${ms}ms  ${dsn}" >&2
    done
  fi
fi
