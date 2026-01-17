# FreeRouting Parity — Test Matrix (TDD Contract)

This document makes the parity plan auditable: every parity-relevant feature must map to (1) code, (2) tests, and (3) at least one oracle fixture.

It is intentionally redundant with `FREEROUTING_FEATURE_PARITY_PLAN.md` but organized for execution and review.

## What counts as “done”

A parity item is **done** only when all are true:
1) **Implementation exists** (Rust module + APIs).
2) **Unit/integration test exists** (fast, runs in `cargo test -q`).
3) **Oracle exercise exists** (a DSN fixture + an ignored oracle run that touches it).
4) **Metrics captured** (normalized JSON schema) and recorded in a report.

## Test layers

### A) Fast unit tests (default)
- Must run in `cargo test -q` without Docker.
- Cover: parsers, rules extraction, geometry primitives, BoardDb invariants, routing kernels determinism, commit/rollback safety.

### B) Fast integration tests (default)
- Still run in `cargo test -q`.
- Use `env!("CARGO_BIN_EXE_*")` to test CLIs when needed.
- Cover: end-to-end DSN → route → output artifacts existence, mode parsing, determinism.

### C) Oracle tests (ignored by default)
- Run Dockerized FreeRouting to compare:
  - completion status
  - DRC (counts)
  - selected secondary metrics (vias/length) once stable
- Entry point: `tests/parity_oracle_tests.rs` (`#[ignore]`).

### D) Tooling reports (manual / CI nightly)
- `tools/run_parity_smoke.sh` (baseline smoke report).
- `tools/run_parity_smoke_matrix.sh` (multiple Rust routing configs).

## Fixtures

### Smoke (fast, always available)
- `freerouting/tests/Issue313-FastTest.dsn`
- `freerouting/tests/Issue270-non-ansi_bracket.dsn`
- `freerouting/tests/Issue103-Board-Routed.dsn`
- `freerouting/tests/Issue209-split05.dsn`
- `freerouting/tests/empty_board.dsn`

### Additions required for parity (medium)
The parity plan requires a curated list (~30) that intentionally exercises:
- 45° restriction, 90° restriction, any-angle (if supported)
- via_keepout, wire_keepout, general keepout
- layer_rule preferred directions and active off/on
- via_rule selection and netclass width/clearance overrides
- planes/areas interactions
- tie-pin and multi-terminal nets

## Matrix (high-level)

| Area | Must implement | Must test (fast) | Must oracle (ignored) |
|---|---|---|---|
| DSN parsing | `dsn/*` complete coverage | existing DSN tests + regression corpus | N/A |
| Rules extraction | full `RulesDb` parity (classes, clearance matrix, vias, layer rules) | unit tests per DSN construct | medium corpus subset |
| BoardDb | insert/remove, spatial index, collision queries | synthetic geometry tests | medium corpus subset |
| Maze router | rooms/doors graph + A* search | corridor + obstacle + via fixtures | “route completion” parity |
| Locate/Insert | geometry extraction + insertion semantics | invariants: connectivity preserved, DRC clean | DRC parity on output |
| Negotiation | pass loop, ripup selection, history costs | deadlock fixtures: sequential fails, negotiation succeeds | completion parity |
| Shove | forced insertion + shove primitives | shove-only fixtures + rollback safety | completion parity on dense cases |
| Optimizers | pull-tight, via reduction | metric non-increasing + DRC preserved | quality parity (secondary metrics) |
| Determinism | same seed → same output hash | repeated-run hash tests | repeated-run oracle consistency |
| Performance | budgets + profiling hooks | optional perf tests ignored | nightly perf report |

## “Missing today” checklist (must be driven to zero for parity)

This list mirrors `FREEROUTING_CLASS_PARITY_MATRIX.md`. Each checkbox must eventually link to:
- Rust module path
- test file path
- one or more oracle DSNs

- [ ] `autoroute/batch.rs`: Batch pass loop + termination + best-of-N restore
- [ ] `autoroute/engine.rs`: per-connection router entry
- [ ] `autoroute/maze.rs`: free-space maze search (rooms/doors)
- [ ] `autoroute/locate.rs`: locate found connection into 45/90 polylines
- [ ] `autoroute/insert.rs`: insert geometry into BoardDb
- [ ] `autoroute/ripup.rs` + `autoroute/history.rs`: negotiation + board history
- [ ] `autoroute/shove.rs` + `autoroute/forced_insert.rs`: shove + forced insertion
- [ ] `board/board_db.rs` + `board/search_trees.rs`: BoardDb + search trees
- [ ] `rules/*`: full parity RulesDb (clearance matrix, netclasses, via rules, layer rules)
- [ ] SES full read/write parity (beyond minimal writer)

## Recently locked-in fast tests (examples)

These tests are intentionally small but protect parity-relevant semantics.

- CLI layer-rule activation: `tests/route_dsn_cli_tests.rs` (`cli_respects_inactive_layer_rules`)
- CLI multi-pin expansion: `tests/route_dsn_cli_tests.rs` (`cli_allmst_expands_multi_pin_net`)
- Direction-cost routing bias: `tests/ir_router_tests.rs` (`dial_3d_for_net_can_use_direction_costs_to_pick_layers`)

## Commands (source of truth)

- Fast suite: `cd pardal-pcb/pardal_router_core && cargo test -q`
- Smoke report: `bash pardal-pcb/pardal_router_core/tools/run_parity_smoke.sh 0xDEADBEEF 1 10`
- Smoke matrix: `bash pardal-pcb/pardal_router_core/tools/run_parity_smoke_matrix.sh 0xDEADBEEF 1 10`
- Oracle tests: `cd pardal-pcb/pardal_router_core && cargo test -q --test parity_oracle_tests -- --ignored`
