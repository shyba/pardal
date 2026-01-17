# FreeRouting Parity (Rust) — Status + TODO

This document tracks feature parity between `pardal_router_core` (Rust) and FreeRouting for the DSN/Spectra ecosystem, with an emphasis on being able to route dense 4-layer FPGA/BGA boards programmatically.

## Current Status (What Works)

### DSN ingestion
- Tokenization supports DSN strings, escapes, and FreeRouting’s `"a"-"b"` no-whitespace dash tokenization.
- `extract_model` reconstructs concatenated pin refs from `(pins "J3"-"D+")` into `J3-D+` so nets resolve to pins.
- Board outlines:
  - Extracts all `(boundary ...)` shapes and builds an outer polygon + hole polygons.
  - Boundary DRC enforces both the outer edge and cutout holes.
- Keepouts:
  - Parses and stamps `keepout`, `wire_keepout`, and `via_keepout`.
  - IR supports `via_forbidden` distinct from wire occupancy.
- Pins/pads:
  - Uses padstack copper shapes for accurate pin stamping (not just bounding circles).
- Planes/areas:
  - Parses plane polygons + windows.
  - Area DRC checks copper-to-area clearance/shorts using spatial indexing.

### DRC (nm model)
- Indexed copper clearance DRC for tracks/vias/terminals/areas.
- Keepout DRC with a robust cell-size heuristic (fixes pathological large-AABB explosions).
- Boundary DRC including holes/cutouts.

### IR + routing kernels (grid router)
- `RoutingIr` occupancy (`occ`) + `via_forbidden` + `pad_owner` (unpoppable pads).
- 3D wavefront routing kernels respect `via_forbidden` for via transitions.
- Default two-pin router is now A*-guided (goal-directed) while keeping the same occupancy semantics:
  - `route_dial_3d_for_net` uses `k6_a_star_3d_occ_owner_diag_to_goal_with_scratch` (scratch reuse + admissible heuristic).
  - This significantly reduces exploration on large boards compared to the earlier Dial-style Dijkstra baseline.
  - The A* open set (`BinaryHeap`) is now also kept inside `Dial3dScratch` and reused across calls to avoid per-route heap allocations.
    - On `ring_escape_multi` 600-pin synthetic, Rust(off) went from ~`142s` → ~`115s` with the same routed fraction (`53/600`).
- CLI `pardal_route_dsn` can:
  - Build IR from DSN bbox + boundary masks + keepouts + pin shapes + wiring occupancy.
  - Route multiple two-pin nets sequentially (baseline) or with a minimal ripup loop.
  - Use `via_cost=auto` to consume DSN `(autoroute_settings (via_costs ...) (vias on/off))` when present.
  - Use `brush` stamping to approximate width/clearance in the IR:
    - `brush=auto` uses DSN width/clearance rules (per-net when possible; falls back to default).
  - Pick nearest free endpoint cells if coarse grid rounding lands endpoints in blocked cells.
  - `keepouts=auto|all|none` mode:
    - `auto` (default) retries with keepouts disabled if keepouts eliminate all free cells.
    - `all` is strict keepouts.
    - `none` ignores keepouts (useful for diagnosing broken DSN exports).
  - `pitch=auto` caps total grid nodes to keep memory bounded on multi-layer boards.
  - IR stamping inflates existing pins/wires/vias by approximate width + default clearance (owner-preserving) to reduce FreeRouting DRC clearance regressions on exported DSNs.

## Parity Gaps vs FreeRouting (Major)

### Routing behavior
- No FreeRouting-style negotiation/ripup-and-reroute (a basic grid ripup loop exists, but is not parity).
- No global routing / congestion-driven iterative refinement.
- No shove routing; no topology-preserving push/pull.
- Limited objective model (no length matching, skew, diff pairs, impedance, etc.).
- Class-level parity checklist lives in `pardal-pcb/pardal_router_core/FREEROUTING_CLASS_PARITY_MATRIX.md`.

### FreeRouting reference map (what’s still missing in Rust)

| FreeRouting component | Where (Java) | What it does | Rust status (`pardal_router_core`) |
|---|---|---|---|
| Batch routing loop | `autoroute/BatchAutorouter.java` | multi-pass routing, progress/stagnation, ordering | missing |
| Per-connection router | `autoroute/AutorouteEngine.java` | chooses start/target items, costs, calls maze/shove | missing |
| Free-space maze search | `autoroute/MazeSearchAlgo.java` | expansion-graph routing through rooms/doors (not a uniform grid) | missing (Rust uses coarse grid A*) |
| Shove/push | `autoroute/MazeShoveTraceAlgo.java`, `board/ShoveTraceAlgo.java` | push existing copper to make room | missing |
| Ripup/history | `autoroute/BoardHistoryEntry.java`, `autoroute/*Ripup*` | negotiation: rip up conflicting routes and retry | missing |
| Fanout | `autoroute/BatchFanout.java` | BGA/IC escape routing primitives | missing |
| Optimization | `autoroute/BatchOptimizer*.java` | pull-tight, via reduction, cleanup | missing |
| Rule model | `rules/*` | clearance matrix, net classes, via rules, directions | partial (DSN rules parsed; routing only uses defaults) |
| Board DB + spatial index | `board/RoutingBoard.java`, `board/ShapeSearchTree*.java` | incremental geometry db + collision queries | partial (nm DRC has indices; router uses `RoutingIr`) |

### Constraints & rules
- Partial: net rules and clearance matrices exist for DRC, but routing does not yet fully consume:
  - per-net/per-class widths
  - per-layer constraints (preferred layers, layer penalties, routing keepins)
  - via rules (allowed stacks, drill sizes, microvias)
  - neckdowns, clearance overrides, dynamic widening
- Grid routing is resolution-dependent and can miss geometric feasibility in tight clearances.
- `rules::RulesDb` exists as a small wrapper over DSN net rules, but is not yet the single source of truth for DRC/routing rules.
- Via geometry is still approximated as “just another path point” during routing:
  - current brush inflation is track-based, not via-diameter-based
  - drill/via-to-via spacing (including same-net spacing) is not enforced during search, so DRC can still flag via-via clearance errors on dense boards

### Geometry fidelity
- Router operates on a discretized grid, not continuous geometry.
- Track width/clearance is approximated by occupancy dilation rather than exact Minkowski sums.

### Connectivity workflow
- No “prove impossible” mode (connectivity reachability proof) for a full netlist under constraints.
- No incremental “already connected” detection to skip routing of satisfied nets.

## Recent routing-only additions (not parity)
- Transactional commit kernels (`k9_try_commit_path_occ_3d*`) so negotiation attempts don’t destroy already-routed copper.
- `route_nets_negotiation_basic_with_brushes` now supports multiple requests per net ID (needed for multi-pin MST expansions).
- `pardal_route_dsn` adds `ALLMST` (expand each chosen net into Manhattan MST edges) and fixes `brush=auto` to use the real net name.
- `pardal_route_dsn` DSN export now stitches pin centers to the first/last routed grid point (on the routed layer) so FreeRouting recognizes the nets as connected (avoids “Pin and Via unconnected” false negatives).
- Via commits now treat any layer transition as a through-hole via occupying all layers, preventing “via through other net’s pad” DRC violations (reduces FreeRouting clearance errors significantly on dense boards).
- `pardal_route_dsn` respects `(autoroute_settings (layer_rule ... (active off)))` by blocking inactive layers and choosing active layers for pin starts/goals.
- Per-layer preferred-direction trace costs from `autoroute_settings.layer_rule` are consumed as routing penalties (grid router approximation).
- Negotiation loop performance: the “basic” ripup loop now uses a `net_id -> request indices` map for requeue (avoids O(N²) rescans on large netlists), but the algorithm is still far from FreeRouting parity and often needs tighter iteration budgets to finish inside 180s on 600-pin cases.

## High-Value Next Work (Parity-Critical, Dependency-Ordered)

This list is the prioritized reordering of the “Missing today” checklist in `FREEROUTING_PARITY_TEST_MATRIX.md`, optimized for getting to *practical FreeRouting parity* on dense BGA/FPGA boards.

### 1) Rules parity (routing-time behavior, not just parsing/DRC)
- **Implement**: `rules/*` (clearance matrix, netclasses, via rules, layer rules, angle restrictions, per-layer prefs)
- **Why now**: every router/BoardDb decision needs “what is legal + what is preferred”
- **Unblocks**: fanout, maze routing costs, ripup priorities, shove legality
- **Status**: `RulesDb` can now merge typed + pairwise clearances from external `(rules ...)` (see `pardal-pcb/pardal_router_core/src/rules/rules_db.rs:1`)

### 2) Board database + search trees + undo (authoritative geometry model)
- **Implement**: `board/board_db.rs`, `board/search_trees.rs`, plus transactional undo (file placement TBD)
- **Why now**: FreeRouting’s autorouter operates on a geometry DB with incremental collision queries; without this, “maze/insert/shove” can’t be parity
- **Unblocks**: maze rooms/doors graph, insert/remove, shove/forced insertion, history restore
- **Status**: added a minimal `BoardDbNm` + `SearchTreesNm` (tracks/vias/terminals; insert + AABB queries), no undo yet (see `pardal-pcb/pardal_router_core/src/board/board_db.rs:1`)

### 3) Fanout / escape routing (BGA/FPGA completion unlock)
- **Implement**: `autoroute/fanout.rs` (escape point generation, via-in-pad/near-pad modes, layer assignment heuristics)
- **Why now**: dense padfields are the practical bottleneck; this is the phase that prevents early poisoning
- **Depends on**: rules parity (clearances/vias/layers), BoardDb collision queries
- **Status**: added `pad_boundary_escape_points` (pad_owner boundary candidates on the grid IR) as a first primitive (see `pardal-pcb/pardal_router_core/src/autoroute/fanout.rs:1`)

### 4) Maze router (rooms/doors, not uniform grid)
- **Implement**: `autoroute/maze.rs` + supporting graph/rooms/drills modules (see `FREEROUTING_CLASS_PARITY_MATRIX.md`)
- **Why now**: this is the core FreeRouting “find a legal path in free space” algorithm
- **Depends on**: BoardDb + search trees; rules parity for costs/legality

### 5) Locate + Insert pipeline (convert search result to geometry)
- **Implement**:
  - `autoroute/locate.rs` (45/90 restriction, polyline simplification)
  - `autoroute/insert.rs` (insert into BoardDb with rollback safety)
- **Why now**: “path found” is meaningless until it’s inserted legally into the board model
- **Depends on**: BoardDb + undo; rules parity for angle + clearance behavior

### 6) Per-connection autoroute entry (one connection at a time)
- **Implement**: `autoroute/engine.rs` (choose start/target items, call fanout/maze/insert/shove as needed)
- **Why now**: establishes the unit of work the batch router iterates over
- **Depends on**: fanout + maze + locate/insert

### 7) Batch pass loop (turn it into a batch autorouter)
- **Implement**: `autoroute/batch.rs` (pass loop, termination, best-of-N restore; later `autoroute/batch_mt.rs`)
- **Why now**: FreeRouting’s convergence behavior is “pass-based” with progress/stagnation and history restore
- **Depends on**: autoroute engine + board history (next)

### 8) Negotiation parity (ripup + history costs)
- **Implement**: `autoroute/ripup.rs` + `autoroute/history.rs` (plus cost model glue)
- **Why now**: dense designs require conflict resolution beyond greedy routing
- **Depends on**: BoardDb undo + insert/remove; rules parity for “what is ripup-able”

### 9) Shove + forced insertion (only-solvable-by-shove cases)
- **Implement**: `autoroute/shove.rs` + `autoroute/forced_insert.rs`
- **Why now**: FreeRouting can complete boards that require local pushing; parity corpus will include these
- **Depends on**: BoardDb + undo; insert/locate; rules parity

### 10) Optimizers (quality + via reduction + cleanup)
- **Implement**: `autoroute/optimize.rs`
- **Why now**: improves completion in later passes and matches FreeRouting “post-route cleanup”
- **Depends on**: stable BoardDb operations + DRC/legality checks

### 11) SES full read/write parity (interop completeness)
- **Implement**: full SES support (beyond minimal writer)
- **Why now**: not required to route, but required for full tooling parity and interoperability workflows

### Checklist (same items, reordered)
- [ ] `rules/*`: full parity RulesDb (clearance matrix, netclasses, via rules, layer rules)
- [ ] `board/board_db.rs` + `board/search_trees.rs`: BoardDb + search trees
- [ ] `autoroute/fanout.rs`: BGA/IC escape/fanout primitives
- [ ] `autoroute/maze.rs`: free-space maze search (rooms/doors)
- [ ] `autoroute/locate.rs`: locate found connection into 45/90 polylines
- [ ] `autoroute/insert.rs`: insert geometry into BoardDb
- [ ] `autoroute/engine.rs`: per-connection router entry
- [ ] `autoroute/batch.rs`: Batch pass loop + termination + best-of restore
- [ ] `autoroute/ripup.rs` + `autoroute/history.rs`: negotiation + board history
- [ ] `autoroute/shove.rs` + `autoroute/forced_insert.rs`: shove + forced insertion
- [ ] `autoroute/optimize.rs`: pull-tight, via reduction, cleanup
- [ ] SES full read/write parity (beyond minimal writer)

## How To Validate Locally
- Rust unit tests: `cargo test -q` (in `pardal-pcb/pardal_router_core`)
- Corpus DRC (requires docker): `bash pardal-pcb/pardal_router_core/tools/run_freerouting_corpus.sh --drc all --dsn-timeout 10 --slow 10`
- Internal DRC (no docker): `cargo run -q --bin pardal_dsn_check -- <path.dsn> --drc all --json`
- Quick routing smoke: `cargo run -q --bin pardal_route_dsn -- ../../freerouting/tests/Issue270-non-ansi_bracket.dsn ALL auto auto 10 auto`
- Smoke matrix (routing configs): `bash pardal-pcb/pardal_router_core/tools/run_parity_smoke_matrix.sh 0xDEADBEEF 1 10`
- Stage timings: `PARDAL_TIMING=1 cargo run -q --bin pardal_route_dsn -- ../../freerouting/tests/Issue289-Autorouter_PCB_FHT-VGA_2024-03-25.dsn ALL auto auto 10 auto`

## BGA Synthetic Bench Snapshot (ring_escape_multi)

These are stress-style synthetic DSNs (dense + adversarial) used to track Rust-vs-FreeRouting progress and to surface failure modes quickly.

- FreeRouting (2 passes) does not fully complete even at 100 pins (unrouted connections remain); see `pardal-pcb/pardal_router_core/build/bga_bench_report.bga_ring_escape_multi_p2_via1_rustoff_p6_stitch_100_200_v1.md`.
- FreeRouting (10 passes, 180s budget) improves but still leaves unrouted connections (example: 100 pins leaves 35); see `pardal-pcb/pardal_router_core/build/bga_bench_report.fr_only_ring_escape_multi_p10_100.md`.
- Rust sequential baseline currently routes a minority of nets on large cases, but recent correctness fixes significantly reduced DRC violations on exported DSNs:
  - Pin→route stitching fixed FreeRouting “unconnected” false negatives (unconnected count now tracks `pins - routed`).
  - Through-via commit semantics reduced “via through other net’s pad” clearance errors dramatically (example: 600 pins dropped from dozens to ~tens).
