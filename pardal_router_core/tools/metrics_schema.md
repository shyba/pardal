# Parity Metrics Schema (WIP)

This repo uses a “metrics-first” parity approach: every routing run (Rust or FreeRouting oracle) produces a machine-readable JSON summary. The parity harness compares these summaries.

## Files (convention)

For an input `X.dsn`, outputs live under a run directory (e.g. `pardal-pcb/pardal_router_core/build/parity/X/`):

- `X.oracle.stats.json`: FreeRouting `BoardStatistics` JSON (printed by FreeRouting CLI mode).
- `X.oracle.drc.json`: FreeRouting DRC report JSON (optional/best-effort).
- `X.oracle.routed.dsn`: FreeRouting routed design (DSN; chosen so FreeRouting DRC can load it).
- `X.rust.route.txt`: Rust router textual summary (today’s router is still “smoke”, not parity).
- `X.rust.route.ses`: Rust-exported SES (existing wiring + any newly routed nets attempted).

## Minimal required fields (parity harness v0)

The v0 parity harness focuses on completion and obvious DRC correctness:

### Routing completion
- `connections.totalCount` (or equivalent)
- `connections.incompleteCount` (or equivalent)

### DRC
- `clearanceViolations.totalCount` (or equivalent)
- `unconnectedItems.totalCount` (or equivalent)

### Runtime
Captured externally by the harness (wall-clock) and stored alongside results.

## Notes

- FreeRouting’s exact JSON structure is defined by its `BoardStatistics` serializer; treat unknown fields as opaque and only depend on a small, stable subset for gating.
- Rust-side metrics should converge toward the same schema over time (Phase 0 → Phase 8 in `FREEROUTING_FEATURE_PARITY_PLAN.md`).
