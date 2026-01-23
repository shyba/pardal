> Status note (2026-01): This repo no longer includes the Rust router backend that earlier iterations discussed/planned.
> The active routing backend is Mojo (`pardal-pcb/pardal_router_mojo/`). Rust-specific sections in this doc are historical context only.

## Scope

This document captures technical debt in `pardal-pcb/` and proposes a phased refactor plan.

Goals:
- Make the Python API safer and easier to integrate (automation, batch routing, CI).
- Reduce coupling between CLI/REPL, routing core, KiCad SDK integration, and DRC.
- Improve determinism, debuggability, and distribution (pure-Python fallback + optional fastpath).

Non-goals:
- “Rewrite the router” (A*/Z3/iterative approaches stay; refactor is about boundaries and correctness).
- Modifying KiCad itself.

## Current Technical Debt (high value items)

### 1) Two DRC stacks with overlapping responsibilities
- Internal DRC: `pcb_tool/commands/drc.py` (grid-ish geometry checks; simplified; used heavily in tests).
- External DRC: `pcb_tool/drc.py` (invokes `kicad-cli` and/or `pcbnew` SDK; used for “production” verification).

Debt symptoms:
- Callers have to know which DRC they want and what “passed” means in each.
- Rules/assumptions differ (layer handling, via-in-pad expectations, pad ownership).

Suggested direction:
- Introduce a single “DRC API” with multiple engines behind it, and unify result types.

### 2) RoutingGrid construction is hidden inside commands
- `AutoRouteCommand._create_routing_grid` does a lot of policy work (grid size inference, pad obstacles, pad ownership, via marking).

Debt symptoms:
- Hard to reuse routing in a library context without bringing command/CLI structure along.
- Multiple places can end up re-implementing “grid build” logic with subtle differences.

Suggested direction:
- Extract a `GridBuilder` / `GridFromBoard` service in `pcb_tool/routing/` that is the single source of truth.

### 3) Implicit global-ish state in PathFinder
- `PathFinder.find_path` mutates `self.current_net` / `self._current_layer` and stores “last_*” fields.

Debt symptoms:
- Harder to use concurrently; harder to unit test; easy to accidentally rely on previous call state.

Suggested direction:
- Make `find_path` return a rich result object (`PathResult`) containing:
  - points, per-segment layers, vias, backend name, costs, and debug stats.
- Keep “last_*” as optional compatibility, but deprecate in favor of the returned object.

### 4) Inconsistent modeling of pads and layers
Observed issues in real runs/tests:
- Unconnected pads still need to behave like copper obstacles for clearance checks.
- Keepouts must not “punch holes” near dense pinfields due to overlapping-net logic.
- Diagonal movement needs consistent corner-cut rules across Python and fastpath backends.

Suggested direction:
- Define explicit “geometry semantics” for:
  - pad copper vs pad center,
  - which checks are layer-aware vs layer-agnostic,
  - and corner-cut behavior.
- Centralize the rules in `pcb_tool/routing/` and have both A* backends follow them.

### 5) Mixed concerns: library vs CLI/REPL
- Many modules print directly (useful for interactive use, noisy for API consumers).

Suggested direction:
- Introduce structured logging (or a simple `Reporter` interface) so the library can be silent by default and the CLI can opt into verbosity.

### 6) Packaging/build complexity for fastpath
- Fastpath uses a Cython extension (`pcb_tool/fastpath/_astar.pyx`) with a local `setup.py` build path.

Debt symptoms:
- Easy to get into “it works locally but not on CI” situations.
- Users need to know when to rebuild and how to disable fastpath.

Suggested direction:
- Keep pure-Python fallback always working.
- Make fastpath a clearly optional “accelerator” with a stable ABI boundary:
  - `pcb_tool/fastpath/__init__.py` becomes the only entry point and exposes a minimal API.
  - Better docs for env toggles: `PARDAL_FASTPATH`, `PARDAL_FASTPATH_MAX_CELLS_2D`, `PARDAL_FASTPATH_MAX_CELLS_3D`.

## Proposed Refactor Plan (phased)

## Progress (implemented)

- Centralized routing grid construction in `pcb_tool/routing/grid_builder.py` and used it from routing commands.
- Added adaptive grid sizing in `pcb_tool/routing/grid_builder.py` (auto-scales resolution based on board size + pad density to keep routing bounded on large sparse boards).
- Introduced `pcb_tool/api/` for programmatic use:
  - `pcb_tool.api.autoroute()` returns `RouteResult`
  - `pcb_tool.api.check_internal_drc()` and `pcb_tool.api.run_kicad_drc()`
- Added `pcb_tool.api.io` helpers:
  - `pcb_tool.api.load_kicad_pcb()` (pcbnew when available, otherwise text/S-expression loader)
  - `pcb_tool.api.save_kicad_pcb()` (minimal router-focused `.kicad_pcb` writer)
- Added structured routing result types (`pcb_tool/routing/results.py`) and `PathFinder.find_path_result()`.
- Centralized net-to-MST edge expansion in `pcb_tool/routing/net_definitions.py`.
- Added a unified DRC interface shim (`pcb_tool/drc_engine.py`) and wired the API to it.
- Added `AutoRouteCommand.execute_result()` and a `verbose` flag to reduce printing for library use.
- Fixed `.kicad_pcb` output parseability: removed invalid simplified `(property ...)` emission from `pcb_tool/kicad_writer.py`.
- Made pad numbers stringly-typed (supports BGA pads like `"A1"`) and normalized negative rotations to `[0, 360)` in the core data model.
- Added KiCad 9 `.kicad_pcb` text loader (no `pcbnew` needed): `pcb_tool/sexpr.py`, `pcb_tool/kicad_text_loader.py`.
- Text loader also parses existing `(segment ...)` and `(via ...)` so fallback workflows can respect pre-existing copper.
- Made `pardal route` usable without `pcbnew` (text loader + minimal writer fallback).
- Added optional KiCad 9 docker-backed DRC runner (`PARDAL_KICAD_DOCKER=1`) and a gated docker DRC smoke test (`PARDAL_ENABLE_DOCKER_TESTS=1` + run slow tests).
  - Run slow/docker tests: `PARDAL_ENABLE_DOCKER_TESTS=1 pytest -m slow -o addopts= --run-slow`
- Added docker-backed KiCad 9 3D render helper (`kicad-cli pcb render`) and a gated render smoke test (same docker gating).

### Phase 0: Guardrails (low risk)
- Add and keep `black` config + dev extra in `pyproject.toml`.
- Add a single entrypoint command for formatting/tests (e.g. `make fmt`, `make test`) if desired.
- Replace `print()` in library paths with `logging` or a `Reporter` abstraction (CLI keeps printing).

Deliverables:
- Formatting and test workflow is repeatable.
- Library usage is quieter and more composable.

### Phase 1: Public API surface + return types
- Create a small `pcb_tool/api/` package (or `pcb_tool/public_api.py`) that re-exports:
  - `Board`, `Component`, `Pad`, `Net`, `NetClass`
  - `route_board(...)`, `route_net(...)`, `run_drc(...)`
- Introduce `PathResult` and `RouteResult` dataclasses.
- Stop requiring consumers to read `PathFinder.last_*` for vias/layers/backends.

Deliverables:
- A stable, documented API for automation.
- Less internal state leakage.

### Phase 2: Unify DRC under one interface
Create:
- `pcb_tool/drc/engine.py`:
  - `DrcEngine` protocol + `DrcResult` + `DrcViolation` (single canonical types).
- Engines:
  - `InternalDrcEngine` (wraps existing `CheckDrcCommand` logic),
  - `KicadCliDrcEngine` (wraps `kicad-cli`),
  - `PcbnewDrcEngine` (wraps sdk).

Deprecate:
- Direct use of `CheckDrcCommand` for programmatic consumers (still usable via CLI/repl).

Deliverables:
- “Run DRC” is one call for consumers; selecting engine is configuration, not code branching.

### Phase 3: Extract GridBuilder and routing “policy”
Extract from `AutoRouteCommand`:
- Board bounds strategy (outline-aware when present; component-bounds fallback).
- Pad obstacle stamping:
  - pad copper cells, pad centers, per-pad net ownership.
- Existing-route stamping (segments/vias).

Deliverables:
- Routing can be called without going through command execution.
- Correctness fixes land in one place.

### Phase 4: Routing core cleanup
- Normalize the “path representation” across:
  - Python A*, 2D fastpath, and 3D fastpath.
- Move all via-placement and “via-in-pad avoidance” policy to one place (not scattered).
- Introduce a single `RoutingParams` structure:
  - resolution, clearance policy, keepout radius, diagonal rules, via costs.

Deliverables:
- Fewer backend-specific quirks; easier to swap implementations.

### Phase 5: Distribution + CI hardening
- Ensure pip installs build the extension when a compiler is available, but keep a clean fallback.
- Add CI matrix that tests both:
  - `PARDAL_FASTPATH=0` (pure python),
  - `PARDAL_FASTPATH=1` (extension present).

Deliverables:
- Predictable performance and behavior across environments.

## Known Slow Tests (for future work)

Current slowest tests are mostly integration/regression:
- `tests/test_final_regression.py::TestRegressionEdgeCases::test_out_of_bounds_components`
- `tests/test_final_regression.py::TestBoardSizeVariety::test_small_board_50x50mm`
- `tests/test_final_regression.py::TestBoardComplexity::test_moderate_crossing_nets`
- `tests/test_production_routing.py::TestFPGABoardRouting::test_fpga_board_zero_drc_errors`

Before optimizing further, prefer isolating the slow behavior behind dedicated benchmarks and ensuring they exercise realistic workloads rather than repeated setup costs.

---

# High-Performance Routing Backend (Rust, SIMD-first, wgpu-portable)

## Objective

Implement a high-performance routing backend in Rust for dense, multi-layer PCB routing workloads (e.g. large BGA breakouts) with the following properties:

- **Performance**: maximize routes-per-second under tight time budgets; support incremental routing loops (route/score/ripup/reroute).
- **Correctness**: preserve electrical correctness (no shorts), respect clearances/widths/via constraints, and support frequent DRC checks.
- **Determinism**: identical inputs + seed produce identical outputs (or identical hashes/metrics under defined tie-break rules).
- **Portability**: design routing computation as a sequence of dense-buffer compute kernels so the implementation can later be migrated to **wgpu compute** with minimal conceptual changes.
- **Optionality**: remain easy to remove later; no mandatory runtime dependency for users who do not want it.

Non-goals (initially):
- Full feature parity with FreeRouting.
- Differential-pair tuning, length matching, impedance rules, or advanced RF constraints.
- Replacing KiCad DRC; KiCad DRC remains the authoritative final validation step.

## Success Criteria (quantitative)

For the `fpga_large` breakout fixture (BGA-324, 4 layers):
- Demonstrate a monotonic reduction curve of `unrouted_count` over time with a fixed compute budget.
- Achieve a substantial improvement over FreeRouting for equivalent budgets (e.g. fewer unrouted nets at 5–20 minutes), or an equivalent result with materially less time/CPU/memory.
- Enforce invariants at every commit:
  - no shorts (owner conflict in occupancy),
  - no clearance violations under configured clearance model,
  - deterministic behavior under a fixed seed.

## Integration Contract (keep optional and removable)

The Rust backend must integrate behind a small, explicit boundary:

- Introduce a `RouterBackend` abstraction with a strict input/output contract.
- Keep conversion from `pcb_tool` datamodel to routing IR in a separate module/crate.
- Keep the Rust backend out of any "default import path" so removal is mechanical.

Proposed interface (conceptual):
- `build_ir(board, params) -> RoutingIr`
- `route(ir, opts) -> RouteResult`
- `apply_routes(board, result) -> board`

## Data Model: Routing IR (buffer-centric)

Routing must operate on dense buffers, not pointer graphs, to enable SIMD and GPU compute.

Required buffers (conceptual):
- `occ[layer][cell] -> u32` occupancy with owner tags (net id or 0 for free) and flags.
- `cost_base[layer][cell] -> u16/u32` static costs (keepouts, preferred direction, edge costs).
- `clearance[layer][cell] -> u16` distance-to-obstacle or "clearance margin".
- `congestion[layer][cell] -> u16` learned penalty map from prior passes.
- `pins[pin] -> cell_idx`, `net_pins[net] -> range`.
- `via_rules` and `layer_pairs` (allowed transitions and per-transition costs).

Multi-resolution requirement:
- Coarse grid for global corridor planning / congestion management.
- Fine grid for detail routing near pinfields and for legal commit checks.

## Kernel-Oriented Decomposition

Design the router as a pipeline of kernels over flat buffers (CPU SIMD now; wgpu later).

The pipeline must avoid:
- complex pointer chasing,
- recursion,
- unbounded dynamic allocations in inner loops.

See the "Kernel Table" section below for the formal decomposition.

## TDD Strategy (formal)

### Principle
Every kernel is unit-tested in isolation and validated against:
1) small synthetic fixtures (fast, exact correctness),
2) a curated subset of FreeRouting DSN fixtures (realistic inputs),
3) end-to-end KiCad DRC on exported routed boards (authoritative validation).

### Golden Artifacts
Store deterministic hashes, not large files, wherever possible:
- `hash(occ)` per layer,
- `hash(paths)` per net,
- scalar metrics (unrouted, total length, vias, conflicts).

## Reuse FreeRouting Regression Corpus (confidence, not dependency)

FreeRouting provides:
- DSN input corpus: `freerouting/tests/*.dsn`
- Rules and expected DRC JSON in some cases: e.g. `freerouting/tests/Issue575-*.json`
- JUnit issue regressions: `freerouting/src/test/java/app/freerouting/tests/Issue*Test.java`
- Determinism reference: `freerouting/src/test/java/app/freerouting/tests/RandomSeedTest.java`

These will be used as *test inputs and invariants* for the Rust backend, not as a runtime dependency.

## CI Test Tiers (time-bounded)

- **Tier A (unit, required)**: synthetic micro-grids; kernel correctness; parser smoke for 1–2 DSNs.
- **Tier B (integration, required)**: curated DSN subset (10–20); determinism checks; DRC-lite invariants.
- **Tier C (perf, optional/nightly)**: larger DSNs; route-until-plateau curves; publish performance metrics; run KiCad DRC on outputs.

All tiers must run with explicit time budgets and produce structured metrics logs.

---

## Phased Implementation Plan (TDD-first)

### Phase R0 — Specifications and Harness

Deliverables:
- `RoutingIr` schema and serialization format for debug snapshots.
- Deterministic hashing strategy for routing outputs.
- `RouterBackend` boundary definition (trait/protocol).
- Test harness skeleton (criterion benches + integration runner).

TODO:
- Define grid resolution policy and scaling rules (coarse vs fine).
- Define deterministic tie-break rules for equal-cost expansions.
- Define canonical cost units (integer weights; avoid floats).
- Define net ordering policies (priority, shortest-first, congestion-aware).

Acceptance gates:
- A minimal end-to-end pipeline can parse a tiny synthetic fixture, route one net, and export a stable hash.

Progress (tracked in-repo):
- [x] Create initial Rust crate `pardal-pcb/pardal_router_core` (Rust-only, no `pcb_tool` coupling yet).
- [x] Port first FreeRouting corpus tests:
  - `freerouting/tests/empty_board.dsn` summary + boundary bbox
  - `freerouting/tests/Issue313-FastTest.dsn` summary smoke
  - `freerouting/tests/Issue110-Паяльная станция.dsn` UTF-8 smoke
  - `freerouting/tests/Issue026-J2_reference.dsn` net-count assertion (24)
  - `freerouting/tests/Issue313-FastTest.dsn` component/pin count assertions (1 component, 108 pins)
- [x] Implement minimal DSN net/pin extraction and validate against `Issue313-FastTest.dsn` (VCC pins + u1-2406 coords).
- [x] Extend DSN extraction with padstack radius approximations (circle/polygon) and validate against `Issue313-FastTest.dsn` (p2391, p17076).
- [x] Track padstack copper layer presence (DSN 1-based numeric layer ids → 0-based indices) and expose it in `DsnModel.padstack_layers`.
- [x] Support KiCad-style DSNs where `placement/component(place <refdes> x y side rot)` maps refdes to footprint images; synthesize absolute pin positions as `<refdes>-<pin>` by applying placement transforms (synthetic test).
- [x] Extract DSN boundary polygon vertices (world coords) and validate against `Issue313-FastTest.dsn`.
- [x] Support DSN boundary forms beyond `path`: parse `(boundary (rect ...))` and `(boundary (polygon ...))` for bbox + boundary masking (synthetic tests).
- [x] Support KiCad DSN layer *names* in padstack shapes by building a `structure` layer-name→index map (e.g. `F.Cu`, `In1.Cu`) and accepting `path` pad shapes in addition to `circle`/`polygon` (synthetic test + CLI smoke on `Issue214-freerouting.dsn`).
- [x] Add criterion micro-benchmarks for DSN summarization (`cargo bench --bench dsn_summary`).
- [x] Add criterion micro-benchmark for DSN→IR pin stamping (`cargo bench --bench dsn_to_ir_stamp`).
- [x] Add criterion benchmark for goal-directed 3D routing on a synthetic grid (`cargo bench --bench dial3d_route`).
- [x] Define minimal `RoutingIr` + stable hashing (`blake3`) and scalar reference router primitives.
- [x] Define `RoutingIr` JSON serialization for debug snapshots (round-trip tested).
- [x] Define a minimal `RouterBackend` trait + scalar reference backend (no `pcb_tool` integration yet).

### Phase R1 — Geometry Rasterization Kernels (scalar first)

Deliverables:
- Pad/keepout/edge rasterization into `occ` and `cost_base`.
- Clearance model precomputation (distance transform or conservative approximation).
- Commit/uncommit for path occupancy.

TODO:
- Implement `K0–K4`, `K9–K10` (see kernel table).
- Write kernel-level unit tests for raster correctness and clearance correctness.
- Add a DRC-lite "no shorts" checker based on occupancy owner conflicts.

Acceptance gates:
- Kernel tests pass on synthetic fixtures.
- Routing commit never produces owner conflicts under tests.

Progress (tracked in-repo):
- [x] Implement scalar reference K0 rectangle stamping kernel (`k0_rasterize_rects_occ`) + unit tests.
- [x] Add circle stamping primitive (`Circle` + `k0_rasterize_circles_occ`) + unit tests.
- [ ] Define via and pad-polygon stamping primitives (needed for real PCB geometry).
- [x] Add DSN→IR scaffold (`dsn_to_ir`): build IR from boundary bbox, stamp pin keepouts from padstack radii, and route between two pins in `Issue313-FastTest.dsn` (integration test).
- [x] Stamp DSN pin keepouts on the layers implied by each pin's padstack (fallback to all layers if unknown), enabling realistic “pads on top only” behavior for BGAs.
- [x] Add polygon fill primitive (`Polygon` + `k0_rasterize_polygon_fill_occ`) + unit tests; wire DSN→IR boundary mask (`apply_boundary_mask_from_world_polygon`) and validate on `Issue313-FastTest.dsn`.
- [x] Define deterministic occupancy owner-tagging semantics for commits (`0`=free, `net_id`=owned; conflicts reported).
- [x] Implement scalar reference K3 Manhattan distance-to-obstacle and tests (`k3_clearance_distance_manhattan`).
- [x] Implement scalar reference K9/K10 commit + conflict reporting and K13 uncommit (unit-tested).
- [x] Add 3D occupancy commit/uncommit for layered point paths (`k9_commit_path_occ_3d`, `k13_uncommit_net_occ_3d`) + unit tests.

### Phase R2 — Single-Net Pathfinding (algorithm choice compatible with kernels)

Deliverables:
- Coarse-grid wave routing kernel pipeline with integer weights.
- Path extraction + simplification.

TODO:
- Implement bucketed wave expansion (Dial-like) or restricted-cost BFS variants.
- Implement predecessor encoding and backtrace extraction.
- Implement turn/via penalties with small integer weights.

Acceptance gates:
- Synthetic fixtures: guaranteed-find cases succeed; no-route cases fail fast.
- Determinism: same seed => same path hash.

Progress (tracked in-repo):
- [x] Implement scalar reference wavefront (K6 BFS) and predecessor backtrace (K7) with unit tests.
- [x] Add minimal multi-layer wavefront baseline (uniform-cost 3D BFS + predecessor extraction with via transitions) + unit test forcing a via escape.
- [x] Add K8 path simplification (collinear removal) with deterministic rules + tests.
- [x] Extend wavefront to support small integer cost fields (Dial-style reference implementation) + tests.
- [x] Extend wavefront to 3D with small integer costs and explicit via cost (Dial-style 3D), with tests that force/avoid vias via cost field and via penalty.
- [x] Add seeded tie-break hook for deterministic path selection under equal-cost alternatives (test-backed).
- [x] Add a minimal high-level 3D routing API wrapper (`route_dial_3d_from_ir`) to exercise kernels end-to-end.
- [x] Add `occ`-direct Dial-3D kernel (`k6_wavefront_dial_3d_occ`) and use it from `route_dial_3d_from_ir` to avoid allocating a temporary blocked mask (equivalence tested).
- [x] Add goal-directed early-exit variants for Dial-3D kernels (`*_to_goal`) and use them from router wrappers to avoid exploring the entire grid for single-net routes (equivalence tested via extracted paths).

### Phase R3 — Multi-Net Router Loop (negotiation + local ripup)

Deliverables:
- Routing scheduler: net ordering, incremental improvements, plateau detection.
- Congestion learning and hot-tile ripup selection.

TODO:
- Implement congestion accumulation (`K11`, `K14`) and ripup selection (`K12`).
- Define ripup scope rules (tile-local, net-local) to avoid global churn.
- Add budgeted iteration controller (time/pass limits).

Acceptance gates:
- For the BGA breakout fixture, demonstrate an improvement curve under a 1–5 minute budget.
- No shorts at all times; clearance violations remain at zero under DRC-lite constraints.

Progress (tracked in-repo):
- [x] Add owner-aware single-net routing primitive (`route_dial_3d_for_net` + `k6_wavefront_dial_3d_occ_owner`) that treats other nets as blocked (no shorts by construction); unit-tested with a forced crossing failure.
- [x] Add minimal sequential multi-net loop (`route_nets_sequential`) that routes and commits a list of two-pin nets (no ripup/negotiation yet), unit-tested on a 2-net fixture.
- [x] Add a minimal DSN routing CLI (`pardal_route_dsn`) to drive DSN→IR + 3D routing manually on fixtures.
- [x] Extend `pardal_route_dsn` with `ALL` mode to route a 2-pin subset of the first N nets sequentially (smoke harness for large DSNs).
- [x] Extend `pardal_route_dsn` with `MST:<net>` mode to connect multi-pin nets via MST (uses the `limit` arg as a pin cap).
- [x] Add deterministic Manhattan MST helper (`mst_manhattan`) as a building block for routing multi-pin nets.
- [x] Add `route_net_mst` to route a multi-pin net by routing the MST edges sequentially (unit-tested on a 3-pin synthetic net).

### Phase R4 — SIMD CPU Backend

Deliverables:
- SIMD implementations for hot kernels (clearance/cost compose/relax/commit).
- Benchmark suite with regression thresholds.

TODO:
- Implement SoA memory layout and alignment rules (tile-based).
- Vectorize the highest-cost kernels first (profiling-driven).
- Add CI perf guardrails (non-failing warnings initially, later enforce).

Acceptance gates:
- Demonstrate speedups vs scalar (per-kernel and end-to-end).

### Phase R5 — Integration with `pcb_tool` and KiCad DRC Validation

Deliverables:
- Converter: `pcb_tool` board → `RoutingIr`; routes → `pcb_tool` traces/vias.
- End-to-end integration tests that run KiCad DRC on outputs for selected fixtures.

TODO:
- Implement robust unit handling and snapping rules (mm ↔ grid cells).
- Validate via legality against KiCad constraints (min drill/diameter; layer pairs).
- Add "route subset" integration tests to keep CI time reasonable.

Acceptance gates:
- Selected fixtures: zero shorts and zero clearance violations under KiCad DRC; unconnected count decreases under budget.

### Phase R6 — wgpu Portability Harness (design now, implement later)

Deliverables:
- `KernelBackend` abstraction with a CPU reference backend.
- Buffer layout and dispatch plans compatible with wgpu.

TODO:
- Remove any CPU-only assumptions in kernel APIs (e.g., heap-based priority queues).
- Ensure kernels are expressed as pure functions over buffers with explicit staging.
- Define and test cross-backend parity for key kernels (distance labels, predecessor encoding).

Acceptance gates:
- Cross-backend equivalence tests pass for the CPU backends (scalar vs SIMD).

---

## Kernel Table (formal decomposition)

| Kernel ID | Name | Purpose | Inputs | Outputs | Determinism requirements | Portability notes |
|---:|---|---|---|---|---|---|
| K0 | RasterizePads | Stamp pads/pins and terminal regions | pad geometry, layer map | `occ`, `pin_cells` | stable stamping order | tile dispatch; avoid atomics where possible |
| K1 | RasterizeKeepouts | Stamp keepouts/edge constraints | keepout geometry | `occ`, `cost_base` | stable rule precedence | scanline or tile fill |
| K2 | RasterizePreRoutes | Preserve existing routes (optional) | segments/vias | `occ` | stable segment stepping | segment stepping should be integer-only |
| K3 | ClearanceDistance | Clearance margin computation | `occ` | `clearance` | stable transform ordering | multi-pass distance transform (GPU-friendly) |
| K4 | CostCompose | Build final cost field | `cost_base`, `clearance`, `congestion` | `cost_field` | stable integer arithmetic | single-pass buffer kernel |
| K5 | FrontierInit | Seed wavefront | `pin_cells`, net metadata | `dist`, `prev`, frontiers | stable pin ordering | scatter + compaction |
| K6 | WavefrontRelax | Wave expansion (core router) | `dist`, `cost_field`, `occ` | `dist`, `prev`, next frontier | stable bucket order and tie-break | bucketed relax; avoid heap PQ for GPU |
| K7 | PathExtract | Backtrace predecessor field | `prev`, pins | raw path | deterministic tie-break | typically scalar, but GPU possible |
| K8 | PathSimplify | Compress/smooth path | raw path | segments | stable simplification rules | scan/compaction kernel |
| K9 | CommitOccupancy | Write route into occupancy | segments/vias | `occ`, per-net lists | deterministic commit ordering | detect conflicts during commit |
| K10 | ConflictDetect | Detect shorts/overlaps | `occ` | conflict list | stable conflict ordering | atomic append on GPU |
| K11 | CongestionUpdate | Increase penalties in hot regions | committed routes | `congestion` | stable accumulation | per-tile accumulation; atomic add on GPU |
| K12 | RipupSelect | Choose ripup targets | tile stats, net scores | ripup set | stable selection order | reductions + selection |
| K13 | Uncommit | Remove routes for a net/region | per-net lists | `occ` | stable removal | scatter clears |
| K14 | TileStats | Compute heat/utilization | `occ`, `congestion` | tile stats | stable reductions | reduction per tile |
| K15 | LayerTransitionTable | Precompute transition costs | via rules | transition LUT | deterministic | constant buffer |
| K16 | PinEscapePlanner | Local escape routing templates | pin neighborhood | escape plan | deterministic templates | local workgroup search |

---

# FPGA-Large End-to-End Plan (KiCad 9, 4-layer BGA-324)

This section is a **no-forks**, end-to-end implementation plan to make the Rust backend route `pardal-pcb/fpga_large/` boards (especially `fpga_large_csg324_breakout.kicad_pcb`) to **0 KiCad DRC errors** under a fixed time budget, with deterministic and reproducible results.

Primary fixture artifacts:
- Generator (KiCad 9 Python): `pardal-pcb/fpga_large/generate_fpga_large.py`, `pardal-pcb/fpga_large/generate_fpga_large_fanout.py`
- Unrouted/fanout boards: `pardal-pcb/fpga_large/fpga_large_csg324.kicad_pcb`, `pardal-pcb/fpga_large/fpga_large_csg324_fanout.kicad_pcb`
- Target breakout board (unrouted): `pardal-pcb/fpga_large/fpga_large_csg324_breakout.kicad_pcb`
- Existing routed baselines (for comparisons): `pardal-pcb/fpga_large/fpga_large_csg324_breakout_routed_*.kicad_pcb`

## 5-Minute Target (what “conclusion” means)

We consider the run “finished” within 5 minutes if it:
- Produces a fully routed board (`unrouted == 0`) with **0 KiCad DRC errors**, OR
- Produces a deterministic “proof-of-impossibility” report identifying at least one net whose terminals are disconnected **even on the base board** (pads/outline/keepouts only), meaning no router could complete the board without changing constraints.

The 5-minute target assumes a workstation with:
- AVX512-capable CPU (for scalar/SIMD kernels and fast stamping), and/or
- NVIDIA GPU (for wavefront and distance-transform kernels via a compute backend).

If GPU is present, the plan mandates using it for the wavefront relax kernel (K6) and for any full-grid transforms (K3), to make the 5-minute target realistic at fpga_large scale.

## Known Fixture Properties (explicit assumptions)

The plan assumes the fpga_large fixtures follow the generator intent:
- 4 copper layers: `F.Cu`, `In1.Cu`, `In2.Cu`, `B.Cu`.
- One BGA footprint (`Xilinx_CSG324`) centered on board.
- 324 2-pin nets: each net connects one BGA pad (`U1_<pad_number>`) to one perimeter testpoint.
- Escape intent: via-in-pad microvia from `F.Cu -> In1.Cu` is present for each BGA pad in the breakout generator outputs.

Grid scaling policy (fixed, to avoid re-decisions later):
- Coarse grid: `grid_step_coarse_nm = 200_000` (0.20mm).
- Fine grid: `grid_step_fine_nm = 100_000` (0.10mm).
- Coarse is used for global corridor finding; fine is used for final routing in a tube around the coarse corridor (see R8).

Memory budget expectations (order-of-magnitude):
- 260mm board @ 0.10mm => ~2600×2600 ≈ 6.8M cells per layer, ~27M cells for 4 layers.
- A single `u32` occupancy buffer for 4 layers is ~108MB; the design must avoid allocating full `dist/prev` per net.

## Determinism Contract (must be implemented up-front)

To make runs reproducible and debuggable:
- One global seed is provided as an explicit parameter; default seed is fixed in tests.
- All ordering is stable:
  - net ordering (see R9),
  - terminal ordering,
  - neighbor expansion ordering,
  - bucket iteration ordering.
- No floating point is used in core routing decisions; all costs are integer.

## Hard Requirements (invariants)

These are enforced by construction or checked after every commit stage:

1) **No shorts by construction**
- Maintain `occ_owner[layer][cell] -> net_id|0`.
- Any commit that would write a non-zero different owner is rejected (conflict) and must trigger reroute/ripup (never “overpaint”).

2) **Clearance by construction**
- Route into a **dilated obstacle field** where blocked cells already include (object copper + required clearance + half width of candidate trace/via).
- This eliminates the need for expensive per-segment geometric clearance checks during routing.

3) **Determinism**
- Inputs + seed => bit-identical outputs (or bit-identical per-net route hashes), with stable tie-breaks:
  - stable net ordering,
  - stable pin ordering,
  - stable neighbor iteration order,
  - stable bucket iteration order.

4) **KiCad is the final oracle**
- Internal “DRC-lite” is used for fast iteration and CI smoke, but the acceptance gates for the fpga_large fixtures are **KiCad DRC reports**.

## Integration Target (no KiCad modifications)

The only supported integration route is:

`pcbnew (KiCad 9 Python API) -> routing IR -> Rust router -> route result -> pcbnew writeback -> kicad-cli DRC`

Notes:
- DSN/Specctra support exists only as a **stress-test harness** and regression corpus (mirrors FreeRouting’s extensive `freerouting/tests/*.dsn` set).
- The production path for `fpga_large` must be **KiCad board in / KiCad board out**.

## “No-Context Dev” Execution Cookbook (one page)

This is the exact workflow a new developer should follow to execute and validate the fpga_large routing pipeline:

1) Generate/refresh fixtures (KiCad 9 python):
   - `docker run --rm -v "$PWD:/work" -w /work kicad/kicad:9.0.6-full python3 /work/pardal-pcb/fpga_large/generate_fpga_large.py /work/pardal-pcb/fpga_large/fpga_large_csg324.kicad_pcb`
   - `docker run --rm -v "$PWD:/work" -w /work kicad/kicad:9.0.6-full python3 /work/pardal-pcb/fpga_large/generate_fpga_large_fanout.py /work/pardal-pcb/fpga_large/fpga_large_csg324_fanout.kicad_pcb`

2) Run the router end-to-end on breakout board:
   - `python -m pcb_tool.api.autoroute_kicad --in pardal-pcb/fpga_large/fpga_large_csg324_breakout.kicad_pcb --out pardal-pcb/fpga_large/fpga_large_csg324_breakout_routed_rust.kicad_pcb --seed 12345 --budget-s 300`
   - (This CLI is a planned deliverable in R7/R8; its contract is fixed by this plan.)

3) Run KiCad DRC in the same docker image (authoritative check):
   - `docker run --rm -v "$PWD:/work" -w /work kicad/kicad:9.0.6-full kicad-cli pcb drc -o /work/pardal-pcb/fpga_large/fpga_large_csg324_breakout_routed_rust-drc.json /work/pardal-pcb/fpga_large/fpga_large_csg324_breakout_routed_rust.kicad_pcb`
   - Acceptance: 0 errors and 0 violations.

4) If not fully routed, demand a “conclusion report”:
   - `python -m pcb_tool.api.autoroute_kicad --prove-impossible --in ... --out ...`
   - Must output `unreachable_nets.json` (see R11) listing disconnected terminal components on the *base board*.

## PR-by-PR Implementation Checklist (no context required)

This is the exact sequence of changes expected to land, each with a concrete “done” test.

PR 1 — KiCad extraction + normalized JSON (`R7.1`):
- Add `pcb_tool/routing/backends/kicad_extract.py` exporting `extract_normalized(board_path) -> input_json`.
- Add `python -m pcb_tool.api.extract_kicad_ir --in ... --out normalized.json`.
- Done when: `normalized.json` round-trips and contains expected nets/layers/pads on `fpga_large_csg324_fanout.kicad_pcb`.

PR 2 — Rust IR builder from normalized JSON (`R7.2`):
- Add `pardal_router_core/src/kicad_ir.rs` and unit tests with a tiny synthetic normalized fixture.
- Done when: `cargo test -p pardal_router_core` passes and prints stable layer/cell counts.

PR 3 — PyO3 bridge (`R7.3`):
- Add `pardal-pcb/pardal_router_py/` with `build_ir/route/free_ir` API exactly as specified in R8.
- Done when: a Python smoke test calls `route()` and gets a route result for a 2-pin synthetic fixture.

PR 4 — pcbnew writeback + KiCad DRC harness (`R8.2`):
- Add `pcb_tool/api/autoroute_kicad.py` (planned CLI in cookbook).
- Done when: routing N=1 produces a `.kicad_pcb` that KiCad opens and DRC runs without crashing.

PR 5 — ROI+coarse→fine tube routing (`R8`):
- Implement ROI and tube constraints in Rust routing calls.
- Done when: `N=10` routes in < 10s and produces 0 KiCad DRC errors for routed nets.

PR 6 — GPU K6 wavefront (deterministic) (`R8`, required for 5 min):
- Implement GPU relax with deterministic `atomicMin(label)` as described.
- Done when: CPU and GPU produce identical per-net route hashes on a fixed-seed small fixture.

PR 7 — Structured router (rings+trunks) (`R8.0`):
- Implement trunk graph build + embed-then-route.
- Done when: `fpga_large_csg324_breakout.kicad_pcb` routes ≥ 90% nets within 300s on AVX512+NVIDIA.

PR 8 — Negotiation + ripup + endgame controller (`R9`):
- Implement deterministic pass loop and endgame schedule.
- Done when: end-to-end run always terminates with `conclusion.kind` set and a DRC report is emitted.

## Component Decomposition (what gets built where)

Python (`pardal-pcb/pcb_tool/`):
- `pcb_tool/kicad_loader.py`: load `.kicad_pcb` into `pcb_tool.data_model` (legacy path; useful for non-SDK flows).
- `pcb_tool/kicad_sdk_writer.py`: write `.kicad_pcb` using `pcbnew` SDK (authoritative for production outputs).
- `pcb_tool/drc_engine.py`: unified DRC interface; must support KiCad DRC invocation for acceptance.
- `pcb_tool/api/*`: programmatic entry points (`autoroute`, `run_kicad_drc`, etc.).
- **New (planned):** `pcb_tool/routing/backends/rust_backend.py`:
  - extracts normalized primitives from `pcbnew.BOARD`,
  - calls the Rust router extension,
  - writes tracks/vias back via `pcbnew`.

Rust (`pardal-pcb/pardal_router_core/`):
- `src/ir.rs`, `src/geom.rs`, `src/kernels.rs`: routing IR + dense-buffer kernels (CPU scalar now; SIMD later).
- `src/router.rs`, `src/mst.rs`: routing policy helpers (single-net, sequential nets, MST, etc.).
- `src/dsn/*`, `src/dsn_to_ir.rs`: DSN harness for regression/perf only.
- **New (planned):** `src/kicad_ir.rs`:
  - consumes normalized primitives (already extracted in Python),
  - produces `RoutingIr` for routing kernels.

Rust/Python FFI (planned, kept minimal and removable):
- **New crate:** `pardal-pcb/pardal_router_py/` (PyO3), exporting a stable function-level API:
  - `build_ir(normalized_input) -> ir_handle`
  - `route(ir_handle, params) -> routes`
  - `free(ir_handle)`
  - No direct dependency on `pcbnew` bindings in Rust.

## Dependency DAG (implementation order, no forks)

This list is ordered so each item has all prerequisites satisfied when started:

1) R7.1: `pcbnew` extraction → normalized primitives (Python)
2) R7.2: normalized primitives → `RoutingIr` (Rust `kicad_ir.rs`)
3) R7.3: pyo3 FFI boundary (`pardal_router_py`) + Python backend shim
4) R8.1: diagonal expansion + preferred-direction costs (Rust kernels)
5) R8.2: pcbnew writeback (Python) + KiCad DRC harness integration
6) R9.1: deterministic multi-net scheduler + bookkeeping (Rust)
7) R9.2: congestion stats + ripup selection + uncommit (Rust)
8) R10: fpga_large-specific escape/topology constraints (Rust+Python config)
9) R11: DRC-lite JSON + CI smoke checks (Rust)
10) R12: hotspot profiling + SIMD backends + parity tests (Rust)

## FreeRouting Parity Mapping (what we replicate, what we don’t)

FreeRouting components relevant to the fpga_large goal:

| FreeRouting concept | Where it lives | What it does | Our plan equivalent |
|---|---|---|---|
| Settings / costs | `settings/RouterSettings.java` | layer activeness, via costs, preferred-direction costs, seed, passes | `RoutingParams` + `CostModel` (pure integer weights) |
| Per-net control | `autoroute/AutorouteControl.java` | netclass-driven widths/clearances, via legality, ripup knobs | `NetRules` + `ViaLut` (precomputed, per-net) |
| Router core | `autoroute/AutorouteEngine.java` + `MazeSearchAlgo.java` | PQ-based maze/A* with obstacle queries | K6 bucketed wavefront (Dial) over dense buffers |
| Fanout | `autoroute/BatchFanout.java` | SMD pin fanout loop, time-limited | K16 escape templates + small local routes |
| Push/shove | `autoroute/MazeShoveTraceAlgo.java` | shove traces around obstacles | Not implemented (grid-only); replaced by negotiation+reroute |
| Optimizer | `autoroute/BatchOptimizer.java` | ripup+reroute to reduce vias/length | deterministic optimization passes over selected nets |
| DRC report | `drc/DesignRulesChecker.java` | clearance + unconnected + KiCad JSON output | DRC-lite (grid) + KiCad DRC as acceptance |
| Determinism test | `tests/RandomSeedTest.java` | hash-based determinism under seed | fixed-seed golden hashes for fpga_large + DSN corpus |

Scope boundary:
- We intentionally avoid FreeRouting’s geometric `ShapeSearchTree` approach; we stick to **dense-buffer kernels** to keep SIMD/wgpu portability.

---

## Phase R7 — KiCad Board → Routing IR (production path)

Goal: Build routing IR directly from `pcbnew.BOARD` with all constraints needed for fpga_large.

### Deliverables
- [ ] Python adapter: load `.kicad_pcb`, extract geometry + rules, call Rust router, write back routes.
- [ ] Rust “IR builder” interface that accepts *already-normalized* primitives (no SWIG types in Rust):
  - layers (ordered), outline boundary polygons, keepouts,
  - pads (per-layer copper shapes), vias (existing), existing segments,
  - per-net constraints (width, clearance, via types allowed).
- [ ] IR memory layout spec (documented, stable) usable by CPU scalar/SIMD and later wgpu.
- [ ] Base-connectivity analyzer (“prove impossible”): given base obstacles only, compute connectivity between terminals for every net.

### Exact extraction rules (KiCad 9 / pcbnew)
- Coordinates:
  - use integer KiCad internal units (`pcbnew` returns nm-scale ints via `VECTOR2I`); convert to `i64 nm`.
  - define `grid_step_nm = 100_000` (0.10 mm) for the initial full-board router for fpga_large.
  - snapping: `cell = floor((coord_nm - origin_nm) / grid_step_nm)`.
- Board bounds:
  - prefer `Edge.Cuts` closed outline; rasterize “inside” as allowed and “outside” as blocked.
  - if outline missing, fall back to bounding box of all copper items + margin.
- Layers:
  - use KiCad copper layers order: `F.Cu`, `In1.Cu`, `In2.Cu`, `B.Cu` (for the fixture).
  - represent layers as indices 0..L-1; store the KiCad layer id mapping in IR metadata.
- Obstacles:
  - Pads: stamp copper on the pad’s owning layer(s); treat all pads (even unconnected) as obstacles for clearance.
  - Vias: stamp on all layers intersecting their span; for microvias, only the layer pair.
  - Existing tracks: stamp as obstacles (already-routed copper).
  - Keepouts / rule areas: stamp as blocked + cost penalties (two channels).
- Terminals:
  - For each net, build terminal sets as “connectable regions”, not single cells:
    - pad copper region (dilated by a small “terminal reach” radius of 1 cell),
    - existing via annulus region (same rule),
    - existing track endpoints if they are already part of that net.

### Base-connectivity “prove impossible” algorithm (fixed)

This is required to guarantee the 5-minute run reaches a conclusion (route or prove impossible).

Inputs:
- Base occupancy `occ_base`: outline mask + pad/via copper + keepouts + existing locked routes.
- Allowed transitions `ViaLut` (layer adjacency).

Algorithm:
1) Build a “free-space graph” implicitly on the chosen grid resolution (coarse grid, 0.20mm):
   - nodes: (layer, cell) where `occ_base == 0`.
   - edges: 8-neighbor moves (with no-corner-cut), plus via edges from `ViaLut` (for the fixture, allow F↔In1, In1↔In2, In2↔B).
2) For each net, pick a canonical start terminal cell (min lexicographic cell) and run a flood-fill in that graph until:
   - all other terminals are found (reachable), or
   - fill completes without reaching a terminal.
3) If any net’s source cannot reach its destination on the base graph, emit it as “impossible”.

Outputs:
- `unreachable_nets.json`: per net: start cell, dest cell(s), and a minimal witness boundary:
  - bounding box of the explored component,
  - frontier cells count,
  - optional sampled boundary points for visualization.

### Validation gates (R7)
- Unit tests (Rust):
  - [ ] IR bounds and layer mapping are stable (fixture-based).
  - [ ] Outline rasterization: point-in-polygon matches expected inside/outside for the fpga_large outline.
  - [ ] Pad/via stamping: golden counts of blocked cells per layer on `fpga_large_csg324_fanout.kicad_pcb`.
- Integration tests (Python + KiCad 9 docker):
  - [ ] Load+save is lossless for non-routing items (hash only excludes timestamps/uuid noise).
  - [ ] KiCad DRC on `fpga_large_csg324_fanout.kicad_pcb` is 0 errors before routing (baseline sanity).
  - [ ] “prove impossible” on `fpga_large_csg324_breakout.kicad_pcb` returns “no impossible nets” (expected for this fixture).

---

## Phase R8 — Single-Net + Two-Pin Routing on KiCad IR (budgeted)

Goal: Prove the end-to-end pipeline on fpga_large by routing **a bounded subset** of nets deterministically.

### Phase R8.0 — Structured Router for fpga_large (mandatory fast path)

This fixture is intentionally regular (BGA → unique perimeter TP). To hit the 5-minute target reliably, routing must start with a deterministic, structure-aware strategy before falling back to general maze routing.

Structured strategy (fixed):
- Use layer roles:
  - `In1.Cu`: primarily horizontal motion.
  - `In2.Cu`: primarily vertical motion.
  - `F.Cu`: only for the final approach into the testpoint pad region.
- Define two rectangular “trunk rings” in board coordinates:
  1) **Inner ring**: `bbox(all BGA pads).expand(8.0mm)`
  2) **Outer ring**: `board_outline_bbox.shrink(10.0mm)`
- Define a trunk grid on `In1/In2`:
  - Trunk lines are axis-aligned, spaced every `trunk_pitch_mm = 0.40mm`, clipped to the area between inner/outer rings.
  - Trunk lines are not pre-routed copper; they are *logical preferred corridors* implemented as low-cost regions in `cost_base`.

Route construction (per net, fixed):
1) **Source escape (In1)**: route from the BGA via landing (terminal) to the nearest point on the inner ring using fine-tube routing (local ROI only).
2) **Trunk traverse (In1/In2)**: route from inner ring point to a selected point on the outer ring using only trunk corridors:
   - represent trunks as a small graph (nodes at intersections, edges along trunks),
   - run Dijkstra on this trunk graph (tiny; deterministic),
   - then embed the trunk path into the grid as a narrow tube and run fine routing inside the tube.
3) **Destination approach (F/In1)**: route from outer ring point to the testpoint pad region:
   - route on `In1` to within 3 cells of the pad center,
   - insert `F.Cu<->In1.Cu` microvia,
   - finish on `F.Cu` into pad region.

Deterministic tie-breaks (required for structured router too):
- Inner ring point: choose the reachable ring cell with minimal `(ManhattanDist, linear_index)`.
- Outer ring point: choose the point with minimal `(HPWL_to_dest, linear_index)`.
- Trunk graph Dijkstra: stable adjacency ordering and `(cost, node_id)` priority.

Acceptance for R8.0:
- Must route at least 90% of nets on `fpga_large_csg324_breakout.kicad_pcb` without invoking general fallback, within 300s on AVX512+NVIDIA.

### Router policy (fixed)
- Movement:
  - 8-neighbor on each layer: orthogonal cost = 10, diagonal cost = 14.
  - diagonal allowed only if both adjacent orthogonal cells are free (“no corner cutting”).
  - layer transitions only via allowed via types from `ViaLut` (K15).
- Cost field:
  - base step cost + preferred-direction penalty per layer (horizontal preferred on odd signal layers, vertical on even).
  - via insertion adds fixed integer via cost + additional penalty if the via is placed within 2 cells of any pad center.
- Path extraction:
  - always backtrace to the **first reached destination cell** using stable predecessor tie-breaks.
- Commit:
  - stamp route geometry into occupancy using dilation radius = (trace_halfwidth + clearance) in cells.

### FFI/API Contract (frozen, implement exactly)

The router backend boundary must be simple enough to swap Python/Cython/Rust/GPU later. The contract is:

Python calls into Rust via `pardal_router_py`:

- `build_ir(input_json_bytes: bytes) -> u64`
  - Returns an opaque IR handle.
- `route(handle: u64, params_json_bytes: bytes) -> bytes`
  - Returns `routes_json_bytes` (compact JSON; msgpack optional later but not now).
- `free_ir(handle: u64) -> None`

`input_json` schema (versioned):
- `version: 1`
- `units: "nm"`
- `grid_step_nm_coarse: 200000`
- `grid_step_nm_fine: 100000`
- `layers: [{ name: "F.Cu", kicad_id: int }, ...]`
- `outline_polygons: { layer: "Edge.Cuts", polys: [[[x_nm,y_nm], ...], ...] }`
- `keepouts: [{ layer: "F.Cu"|..., poly: [[x_nm,y_nm],...], kind: "hard"|"cost", cost: int }, ...]`
- `pads: [{ net: str|null, layers: [layer_name,...], poly: [[x_nm,y_nm],...], is_terminal: bool, terminal_id: str }, ...]`
- `vias: [{ net: str|null, from_layer: str, to_layer: str, center: [x_nm,y_nm], diameter_nm: int }, ...]`
- `tracks: [{ net: str|null, layer: str, width_nm: int, a: [x_nm,y_nm], b: [x_nm,y_nm] }, ...]`
- `net_rules: { net_name: { width_nm, clearance_nm, via_kind: "microvia"|"through", allowed_layer_pairs: [[from,to],...] }, ... }`
- `nets: [{ name: str, terminals: [terminal_id,...] }, ...]`

`params_json` schema:
- `version: 1`
- `seed: u64`
- `budget_ms: u32`
- `passes_max: u32` (fixed to 10 by this plan)
- `backend: "cpu"|"gpu"` (auto-select allowed, but must be deterministic)

`routes_json` schema:
- `version: 1`
- `routes: [{ net: str, items: [ { kind:"track", layer, width_nm, a:[x_nm,y_nm], b:[x_nm,y_nm] } | { kind:"via", from_layer, to_layer, center:[x_nm,y_nm], diameter_nm, drill_nm } ] }]`
- `stats: { routed: u32, unrouted: u32, ms_total: u32, passes: u32 }`
- `conclusion: { kind: "routed"|"impossible", details_path: str }`

### Performance-critical implementation rules (mandatory)

To make the 5-minute target achievable, the routing loop must obey these constraints:

1) No full-grid per-net allocations:
- Use reusable buffers with epoch tagging:
  - `dist[u32]`, `prev[u32]`, `seen_epoch[u32]`.
- A cell is “unset” for the current search if `seen_epoch[cell] != epoch`.

2) Always search in a region-of-interest (ROI), not full board:
- Compute net ROI on coarse grid:
  - ROI = bbox(terminals) expanded by `roi_margin_cells = 64` (coarse cells).
- Run coarse routing only inside ROI.

3) Always refine via “tube routing” on fine grid:
- Convert the coarse path to world points.
- Define a tube region on fine grid: all fine cells within `tube_radius_mm = 3.0` of any coarse segment.
- Route again on fine grid, but only within the tube region (plus terminal blobs).

4) Backend selection is not optional:
- If NVIDIA GPU is present, K6 must run on GPU (wavefront relax dominates).
- CPU AVX512 is used for stamping (K0/K1/K9) and for path extraction (K7/K8).

### GPU Determinism Strategy (mandatory if GPU used)

GPU parallelism must not break determinism. Use a single label buffer per search:

- `label[u64]` per cell, initialized to `INF`.
- Pack `(dist, pred)` into a monotone-comparable 64-bit integer:
  - `label = (dist_u32 as u64) << 32 | (pred_linear_u32 as u64)`
  - Use `pred_linear_u32 = current_cell_linear_index` for the predecessor candidate.
  - Use `pred_linear_u32 = 0xFFFF_FFFF` for “unset”.
- Relaxation uses `atomicMin(label[next], candidate_label)`.
  - This enforces deterministic tie-break: minimum distance first, then minimum predecessor index.

Frontier scheduling:
- Process cost buckets in increasing `dist` order (Dial).
- Bucket insertion order may be nondeterministic; this is acceptable because `atomicMin` determines the final label deterministically.

Path extraction:
- After the distance field is finalized (or goal is reached), extract on CPU by greedy descent:
  - at each step, select the neighbor with strictly smaller `(dist, pred)` label using the same deterministic neighbor order.

### Work items
- [ ] Add diagonal expansion kernels for 2D/3D Dial wavefront (K6 variant) with stable tie-breaks.
- [ ] Add per-layer preferred direction costs in the cost composer (K4).
- [ ] Add “terminal reach regions” so routes can hit pads/vias robustly at 0.10mm grid.
- [ ] Implement pcbnew writeback for:
  - tracks on the chosen layers with correct width,
  - vias with correct type and layer pair.
- [ ] Implement ROI + tube routing exactly as described above (coarse→fine, no alternatives).
- [ ] Implement the structured router exactly as described in R8.0 (rings + trunk graph + embed-then-route).

### Validation gates (R8)
- Unit tests (Rust):
  - [ ] diagonal/no-corner-cut correctness on synthetic obstacles.
  - [ ] cost field determinism: given the same inputs, identical `cost_field` bytes.
- Integration tests:
  - [ ] Route exactly N nets on `fpga_large_csg324_breakout.kicad_pcb` (start with N=10), save output board.
  - [ ] Run KiCad DRC on the output and require: 0 errors, 0 shorts, 0 clearance errors (warnings allowed only for unconnected nets).
  - [ ] Time budget: N=10 completes in < 10 seconds on a developer workstation (CPU-only acceptable here).

---

## Phase R9 — Full 324-Net Routing Loop (negotiation + ripup, deterministic)

Goal: Route all nets on `fpga_large_csg324_breakout.kicad_pcb` under a fixed wall-clock budget with a monotonic “unrouted decreases” curve.

### Deterministic multi-net schedule (fixed)

Net ordering (stable):
1) sort nets descending by HPWL (half-perimeter wire length) of terminals,
2) tie-break by net name lexicographically.

Per-pass schedule:
- Pass 1: route all nets sequentially once, no ripup.
- Pass 2..P (P=10): negotiation loop:
  - compute tile congestion stats (K14) on a fixed tile size of 64x64 cells.
  - update congestion penalties (K11) by adding +`penalty = min(500, 5 * util_percent)` to cells in the top 10% hottest tiles.
  - select ripup targets (K12) as the set of nets whose routes intersect the top 5% hottest tiles, capped at 64 nets/pass.
  - uncommit those nets (K13) and reroute them sequentially with the updated cost field.

Stop conditions:
- stop early if `unrouted == 0` and KiCad DRC is 0 errors for the intermediate output.
- otherwise stop after 10 passes or after budget is exceeded (whichever first), keeping the best-known solution by (unrouted, violations, total_cost).

### “Conclusion within budget” controller (mandatory)

This controller makes the 5-minute requirement enforceable:
- Global budget: 300s wall-clock.
- Per-pass budget: 25s (10 passes max).
- Per-net budget: dynamic, but capped at 250ms average:
  - if average > 250ms over the last 32 nets, the system must reduce work by shrinking ROIs to the terminal bbox + 32 cells, and disable ripup for that pass.

Mandatory endgame schedule (no alternatives):

- At `t = 240s` (60s remaining): enter **Endgame Mode**:
  1) Save a checkpoint board (`*_checkpoint_before_endgame.kicad_pcb`).
  2) Uncommit all non-locked routes (return to base-only occupancy).
  3) Run the **structured router** (R8.0) for all nets once, in deterministic order, with no ripup.
  4) If fully routed, stop and run KiCad DRC.

- At `t = 295s` (5s remaining): if still not fully routed, enter **Impossibility Proof Mode**:
  1) Uncommit all non-locked routes (base-only occupancy).
  2) Run base-connectivity analysis at **fine grid** (0.10mm) once to precompute connected components of free space.
  3) For each remaining unrouted net, check whether all terminals lie in the same component:
     - If any net is base-disconnected, emit `unreachable_nets.json` and mark the run as `impossible` (this is the required proof).
  4) If all remaining nets are base-connected (so no impossibility proof exists under this model), emit:
     - `failure_bundle/` (deterministic) containing the final IR snapshot, remaining nets list, and per-net stats,
     - `conclusion.json` with `kind = "failed_within_budget"` and an explicit statement that impossibility was *not* proven.
     - This is treated as a routing-engine deficiency and is prioritized as a perf/correctness bug.

### Work items
- [ ] Add tile stats kernel and deterministic selection.
- [ ] Add per-net route bookkeeping needed for fast uncommit (store stamped cell lists per net).
- [ ] Add pass controller and scoring accumulator.
- [ ] Add periodic “checkpoint save” of intermediate boards (debug artifacts) with a stable naming scheme.
 - [ ] Add “time-to-first-route” metric and fail-fast if no net routes in the first 5 seconds (indicates extraction or obstacle dilation is wrong).
 - [ ] Add deterministic run log (JSONL) emitting:
   - pass number, net name, ROI size, expansions, path cost, time ms, committed cells,
   - unrouted count after each pass,
   - and final conclusion reason.

### Validation gates (R9)
- Determinism:
  - [ ] fixed seed produces identical per-net hashes for 3 consecutive runs.
- Quality:
  - [ ] after each pass, `unrouted_count` is non-increasing (allow temporary increases only if a pass is rolled back; rollback must be deterministic).
- KiCad validation:
  - [ ] final output: 0 KiCad DRC errors and 0 violations.
 - Performance validation:
   - [ ] end-to-end run completes (route or conclude) within 5 minutes on AVX512+NVIDIA, for a fixed seed.

---

## Phase R10 — BGA-First Escape and Topology Constraints (fpga_large specific)

Goal: Make the fpga_large breakout reliably routable by seeding correct escape topology around the BGA before global routing.

### Fixed escape strategy for `fpga_large_csg324_breakout.kicad_pcb`

Assumption (matches generator intent):
- Each BGA pad already has a microvia `F.Cu -> In1.Cu` at the pad center (via-in-pad).

Escape plan:
- Treat the **In1.Cu landing point** as the primary source terminal for each net.
- For each net, reserve a local keepout ring of radius 2 cells around the BGA via landing to prevent other nets from crowding the escape throat.
- If a destination terminal is on `F.Cu` (testpoint pads), force the final approach to:
  - route on `In1.Cu` until within 3 cells of the destination pad center,
  - insert a `F.Cu <-> In1.Cu` microvia,
  - finish on `F.Cu` (short segment into pad region).

### Work items
- [ ] Implement terminal layer preferences (“start on In1, finish on F” for this fixture).
- [ ] Implement “approach constraints” as additional costs near destination to drive a via + final layer.
- [ ] Implement and test pad-center proximity penalties to reduce via-in-pad and crowding.

### Validation gates (R10)
- [ ] fpga_large routes achieve 0 KiCad DRC errors without requiring manual via seeding beyond what the generator provides.

---

## Phase R11 — DRC-Lite + Report Plumbing (fast feedback loops)

Goal: Make the routing loop self-checking and CI-friendly without depending on KiCad for every iteration.

### DRC-lite checks (grid-based, fast)
- Shorts: owner conflicts in `occ_owner` (must always be 0).
- Clearance: ensure routed stamps never overlap foreign obstacles (must always be 0 by construction).
- Unconnected: approximate via terminal reachability by running a connectivity flood-fill on the net’s stamped region (warning-level until final).

Report format:
- Emit KiCad-like JSON compatible structure (modeled on FreeRouting `DesignRulesChecker.generateReportJson`) for:
  - clearance violations (should be empty in our design),
  - unconnected items (used as progress metric).

### Work items
- [ ] Add DRC-lite report JSON schema and minimal renderer.
- [ ] Add CI smoke that runs DRC-lite on a routed output and checks invariants in < 10 seconds.

---

## Phase R12 — Performance Program (scalar → SIMD → wgpu-ready kernels)

Goal: Make fpga_large routing fast enough to be practical, using kernel-by-kernel optimization with TDD parity checks.

### Fixed benchmarking strategy
- Micro-benches per kernel (Criterion), always reporting:
  - throughput (cells/sec),
  - working-set size (bytes),
  - variance and regression thresholds.
- End-to-end bench:
  - route fpga_large for a fixed 60s budget, report routed count and steps/sec.

### Optimization order (hotspot-first, deterministic)
1) K6 WavefrontRelax (3D, owner-aware, to-goal)
2) K9 CommitOccupancy (stamping + conflict checks)
3) K0/K1 rasterizers (pads/keepouts) + K3 clearance distance/dilation
4) K11/K14 congestion stats

### SIMD rules (fixed)
- Tile size: 128x64 cells for CPU cache locality; SoA layout per field (`occ`, `cost`, `dist`, `prev`).
- Use `u16` for distances with saturating behavior; switch to `u32` only when overflow is observed in tests.
- Vectorize stamping and relax loops first; keep predecessor writes scalar if it complicates vectorization.

### Validation gates (R12)
- [ ] scalar vs SIMD parity tests (byte-identical outputs for the same seed/input).
- [ ] performance threshold: fpga_large “route 324 nets” completes within the configured budget on reference hardware (tracked as CI warning first).

---

## Kernel Reuse Matrix (what runs where)

This matrix is the intended “kernel reuse contract” across routing, scoring, and DRC-lite:

| Kernel | IR build | Route (single-net) | Route (multi-net) | Ripup/negotiation | DRC-lite/report | Notes |
|---|---:|---:|---:|---:|---:|---|
| K0 RasterizePads | ✅ |  |  |  | ✅ | pads are terminals + obstacles |
| K1 RasterizeKeepouts | ✅ |  |  |  | ✅ | keepouts also feed cost penalties |
| K2 RasterizePreRoutes | ✅ | ✅ | ✅ | ✅ | ✅ | used to preserve “do-not-touch” routes |
| K3 ClearanceDistance | ✅ | ✅ | ✅ | ✅ | ✅ | also used for “how tight is this?” metrics |
| K4 CostCompose |  | ✅ | ✅ | ✅ |  | composes base + preferred-dir + congestion |
| K5 FrontierInit |  | ✅ | ✅ | ✅ |  | terminal regions seeding |
| K6 WavefrontRelax |  | ✅ | ✅ | ✅ |  | core compute hotspot |
| K7 PathExtract |  | ✅ | ✅ | ✅ |  | must stay deterministic |
| K8 PathSimplify |  | ✅ | ✅ | ✅ |  | produces pcbnew-friendly segments |
| K9 CommitOccupancy |  | ✅ | ✅ | ✅ | ✅ | commit and “no-shorts” enforcement |
| K10 ConflictDetect |  | ✅ | ✅ | ✅ | ✅ | conflict listing for debug artifacts |
| K11 CongestionUpdate |  |  | ✅ | ✅ |  | only after commits |
| K12 RipupSelect |  |  |  | ✅ |  | deterministic selection is required |
| K13 Uncommit |  |  | ✅ | ✅ |  | requires per-net stamping lists |
| K14 TileStats |  |  | ✅ | ✅ |  | powers selection + progress logging |
| K15 LayerTransitionTable | ✅ | ✅ | ✅ | ✅ |  | via legality + costs LUT |
| K16 PinEscapePlanner | ✅ | ✅ | ✅ |  |  | used only for BGA-like pinfields |

## Validation Matrix (what to assert, when)

| Phase | Primary artifact | Must be true | How it is checked |
|---|---|---|---|
| R7 | `RoutingIr` from `fpga_large_csg324_fanout.kicad_pcb` | layers, outline, pads, vias stamped | Rust unit tests + golden counts |
| R8 | routed subset output board | no KiCad DRC errors on routed subset | `kicad-cli pcb drc` in KiCad 9 docker |
| R9 | full routed output board | unrouted=0 and KiCad DRC errors=0 | KiCad DRC + progress logs per pass |
| R10 | full routed output board | BGA escape stays unclogged and deterministic | per-net hash stability + via count sanity |
| R11 | DRC-lite JSON | schema stable + invariants enforced | Rust unit tests + snapshot tests |
| R12 | benches | parity + speedup | Criterion + parity tests |

## Test & Fixture Port Plan (FreeRouting corpus → Rust regression suite)

FreeRouting includes an extensive DSN fixture set in `freerouting/tests/`. We use it as a regression corpus for the Rust router *independent of KiCad*.

### CI-fast DSN set (must finish < 30s total)
- [ ] `freerouting/tests/Issue313-FastTest.dsn` (small, multi-pin power net)
- [ ] `freerouting/tests/Issue214-freerouting.dsn` (medium, varied)
- [ ] `freerouting/tests/Issue187-processor.Z80.dsn` (medium, dense)
- [ ] `freerouting/tests/empty_board.dsn` (sanity)

Assertions (for CI-fast):
- deterministic route hashes under fixed seed,
- no shorts by construction,
- `routed_edges > 0` and progress monotonicity under a small budget.

### Nightly DSN set (bigger coverage)
- [ ] Add the 20 largest DSNs by (layer_count, pin_count, boundary area) and enforce:
  - no crashes,
  - stable determinism,
  - routed count improves over baseline.

---

## fpga_large Acceptance Checklist (definition of “works”)

For `pardal-pcb/fpga_large/fpga_large_csg324_breakout.kicad_pcb`:
- [ ] End-to-end run produces `fpga_large_csg324_breakout_routed_rust.kicad_pcb`.
- [ ] `kicad-cli pcb drc` on that output reports 0 errors and 0 violations.
- [ ] Repeatability: identical seed produces identical output board hash (ignoring UUID/time noise) 3/3 runs.
- [ ] Performance: within budget (recorded), with a routed-count curve logged per pass.

---

# General Large-Board Compatibility (beyond fpga_large)

This plan is fpga_large-first, but the intent is to produce code that can route *real* large boards that FreeRouting can already route. Today, that confidence depends on whether the input falls within a clearly defined “supported subset”, and whether we have equivalence regression coverage.

## What “Feature Parity with FreeRouting” means (concrete)

We claim “feature parity” only when, for a representative set of DSN fixtures that FreeRouting routes today:
- Our router reaches `unrouted == 0` under the same time budget class (default 5 minutes),
- DRC-lite invariants hold (no shorts; no clearance violations under the same rules),
- and the output passes the same “Issue” acceptance checks that FreeRouting’s own tests assert (incomplete count, violations count, determinism where required).

This does **not** mean the exact same algorithms (FreeRouting uses geometry + `ShapeSearchTree` + shove/pull-tight); it means comparable capabilities and outcomes.

## Feature Parity Roadmap (explicit, no missing bullets)

Until each parity item is implemented, the extractor must produce `unsupported_features.json` and fail fast (never “best effort” silently).

### Parity Level 1 — “Routes common boards” (45°/90°, no shove, no any-angle)

Must support:
- Netclasses with per-layer widths (`NetClass.trace_half_width_arr`), per-net assignment.
- Full clearance matrix by class and layer (`ClearanceMatrix.get_value(i,j,layer)`).
- Via rules (ordered preference) and via legality by layer range (`ViaRule`).
- Layer activeness and preferred-direction costs (`RouterSettings` / `AutorouteControl`).
- Automatic neckdown at pins (like `InsertFoundConnectionAlgo.try_neck_down`) for both start and end segments.
- Conduction areas treated as obstacles with correct clearance classes.
- Deterministic multi-pass ripup/negotiation (our R9 controller) with stable seeds.

### Parity Level 2 — “Routes tight boards” (adds shove-like capability + via optimization)

Must add:
- A shove-equivalent insertion mode for traces/vias (FreeRouting: `ShoveTraceAlgo`, `MazeShoveTraceAlgo`, `ForcedViaAlgo`).
- Via optimization pass (FreeRouting: `OptViaAlgo`) and trace pull-tight in changed areas (FreeRouting: `PullTightAlgo*` restricted to 45°/90°).

### Parity Level 3 — “Any-angle parity” (as FreeRouting supports)

Must add:
- Any-angle route representation and pull-tight (`PullTightAlgoAnyAngle`) and any-angle insertion (`LocateFoundConnectionAlgoAnyAngle` + `InsertFoundConnectionAlgo`).
- Deterministic results under seed for fixtures that are deterministic in FreeRouting.

### Feature checklist (FreeRouting → our deliverable)

| Feature | FreeRouting reference | Status in this plan | Implement in phase |
|---|---|---|---|
| Clearance matrix (class×class×layer) | `rules/ClearanceMatrix.java` | missing | R13 |
| Per-layer netclass widths | `rules/NetClass.java` | partial (single width assumed) | R13 |
| Via rules and layer-range vias | `rules/ViaRule.java`, `autoroute/AutorouteControl.java` | partial | R13 |
| Net ties / tie pins | `autoroute/MazeSearchAlgo.reduce_trace_shapes_at_tie_pins` | missing | R16 |
| Automatic neckdown | `autoroute/InsertFoundConnectionAlgo.try_neck_down` | missing | R14 |
| Conduction areas (zones) handling | `board/ConductionArea` usage across routing/DRC | partial (obstacle only) | R17 |
| Pull-tight (45/90) | `board/PullTightAlgo45/90` | missing | R15 |
| Any-angle pull-tight | `board/PullTightAlgoAnyAngle` | missing | R18 |
| Shove / spring-over | `board/ShoveTraceAlgo`, `autoroute/MazeShoveTraceAlgo` | missing | R16 |
| Forced via legality + attach SMD | `board/ForcedViaAlgo` | missing | R14 |
| Via optimization | `board/OptViaAlgo` | missing | R15 |
| DRC JSON report parity | `drc/DesignRulesChecker.java`, `tests/DesignRulesCheckerTest.java` | partial | R17 |

## Equivalence Gates vs FreeRouting (to justify “also works”)

To be confident that “if FreeRouting can route it, we can too”, we need a shared corpus and comparable metrics. Use the existing FreeRouting issue tests as the initial equivalence set because they encode “works today” expectations.

### Equivalence Corpus (must be tracked in CI)

Tier-1 equivalence (required):
- `freerouting/tests/Issue026-J2_reference.dsn` (FreeRouting expects incomplete=0 and violations=0)
- `freerouting/tests/Issue558-dev-board.dsn` (known large-ish demo)
- `freerouting/tests/Issue159-setonix_2hp-pcb.dsn` (stress)

Tier-2 equivalence (nightly):
- Add the top-20 DSNs by size from `freerouting/tests/` (precomputed list checked into repo).

### Metrics and acceptance (fixed)

For each DSN in Tier-1:
- Under a fixed seed and a fixed 5-minute budget:
  - `unrouted == 0` OR emit `unreachable_nets.json` proving base-disconnect (same definition as fpga_large).
  - DRC-lite “no shorts” invariant holds at all times.
  - DRC-lite clearance violations remain 0 by construction (dilated obstacles).

Additionally, to validate “competitive with FreeRouting”:
- Compute comparable stats after routing:
  - vias count,
  - weighted trace length,
  - incomplete count (ratsnest approximation is acceptable in DSN harness).
- Gate: we must not regress catastrophically:
  - `unrouted` must be <= FreeRouting’s `incompleteCount` for Tier-1 fixtures (captured as golden numbers from FreeRouting tests).

### Implementation notes for equivalence

To achieve parity, DSN harness must parse rules/structure enough to honor:
- layer count and active layers,
- per-layer widths,
- clearance matrix,
- via rules (layer ranges) and via costs,
- and tie-pin semantics (at least detection + correct handling once R16 lands).

Determinism checks must be enabled on this corpus (fixed seeds, route hashes).

---

## Phase R13 — Rules Parity (netclasses, clearance matrix, via rules)

Goal: Make routing decisions use the same *rules model* that FreeRouting uses, not a scalar simplification.

Deliverables:
- Per-net rules: `{ trace_half_width[layer], clearance_class, via_rule }` extracted from KiCad and DSN.
- Clearance matrix support: `clearance(i, j, layer)` with safety margin behavior aligned to FreeRouting (`ClearanceMatrix.clearance_safety_margin`).
- Via rules: ordered via list with allowed layer ranges and attach-SMD flag.

Implementation (fixed):
- Add `class_id` for every obstacle (pads, vias, tracks, zones) in IR.
- Add `net_class_id` for every net, and map to `trace_clearance_class`.
- Replace “dilated obstacles by one scalar” with a two-stage check:
  1) conservative grid blocking by `min_clearance_for_net` (fast reject),
  2) exact local clearance validation at commit time using `clearance_matrix` and obstacle class labels (accept/reject).

Validation gates:
- DSN fixtures: must parse and expose `ClearanceMatrix` values and netclass widths; golden snapshot tests.
- Routing must not produce clearance violations under DRC-lite (commit-time validation).

## Phase R14 — Via/Neckdown Parity (forced vias, attach-SMD, width transitions)

Goal: Match FreeRouting’s ability to finish connections even when pins are small, via types are constrained, and vias must be legal on specific layers.

Deliverables:
- Width-state routing (discrete widths):
  - `W0 = net default width`, `W1 = pin neckdown width`.
- Forced via legality checks matching `ForcedViaAlgo.check` behavior at a minimum:
  - layer range,
  - attach-SMD allowed,
  - clearance class constraints.
- Emit variable-width track segments to KiCad.

Implementation (fixed):
- Extend router state to `(layer, x, y, width_state)` for the last K steps near terminals only:
  - width transitions allowed only within `neckdown_radius_cells = 20` (fine grid).
- Commit-time exact check uses clearance matrix and the chosen width.

Validation gates:
- Unit: synthetic “pin smaller than net width” test must succeed only with neckdown enabled.
- DSN: add a fixture-based test that validates a neckdown-like behavior (does not have to match FreeRouting geometry exactly, but must satisfy rules).

## Phase R15 — Pull-Tight + Via Optimization (45/90 parity)

Goal: Close the gap where FreeRouting relies on “route then optimize” to resolve tight clearances and reduce vias.

Deliverables:
- Pull-tight pass for 45° and 90° boards (FreeRouting: `PullTightAlgo45`, `PullTightAlgo90`), operating on our polyline representation.
- Via optimization pass analogous to `OptViaAlgo` for vias with ≤2 trace contacts.

Implementation (fixed):
- Pull-tight operates only within “changed area” boxes to bound cost:
  - keep per-net changed-region bbox during commit/uncommit,
  - iterate until no improvements or iteration cap.
- Via optimization uses a deterministic candidate set:
  - attempt reposition along incident trace directions,
  - accept move if it strictly decreases weighted length and passes clearance checks.

Validation gates:
- Determinism: same seed produces identical optimized routes.
- Quality: vias count and trace length must not increase on Tier-1 DSNs where FreeRouting completes.

## Phase R16 — Tie Pins + Shove-Equivalent Insertion

Goal: Support boards that rely on tie pins and shove/push behavior.

Deliverables:
- Tie-pin semantics:
  - pads may carry multiple nets; routing must be able to connect a net to the tie pad without being blocked by other-net copper inside the pad shape (FreeRouting reduces trace shapes at tie pins).
- Shove-equivalent insertion:
  - insert a candidate segment by locally displacing/rerouting a small set of interfering items.

Implementation (fixed):
- Tie pins:
  - represent “pad interior” as a special region where foreign-net occupancy is ignored *only if* the pad declares multi-net membership and only inside the pad copper polygon.
  - outside the pad polygon, normal “other nets are blocked” applies.
- Shove-equivalent insertion (kernel-friendly, deterministic):
  - define a local window = bbox(candidate_segment).expand(`shove_window_mm = 5.0`),
  - identify interfering foreign-net segments/vias whose geometry intersects the candidate’s clearance envelope,
  - uncommit only those items inside the window (keep outside fixed),
  - route the candidate,
  - reroute the displaced nets inside the same window using the same budgeted wavefront,
  - commit all or rollback deterministically (transactional window routing).

Validation gates:
- Add a DSN fixture that requires tie-pin handling to complete (or synthesize one).
- Add a synthetic test where insertion is impossible without a shove window but becomes possible with it.

## Phase R17 — Zone/Plane Parity + DRC Report Parity

Goal: Correctly model conduction areas and match FreeRouting’s DRC report output expectations.

Deliverables:
- Zones/conduction areas:
  - treated as obstacles with correct clearance class and layer coverage,
  - optional “allow via into plane” rules when the net matches (plane connect).
- DRC JSON parity:
  - generate KiCad-style JSON with the same shape of fields FreeRouting emits (`DesignRulesChecker.generateReportJson`),
  - include unconnected items and clearance violations (should be empty if routing respects rules).

Validation gates:
- Port FreeRouting’s `DesignRulesCheckerTest` expectations to our DRC JSON emitter for at least one fixture.
- Run Tier-1 DSN set and require zero clearance violations.

## Phase R18 — Any-Angle Parity (feature parity completion)

Goal: Support boards that FreeRouting routes in any-angle mode.

Deliverables:
- Any-angle polyline representation and smoothing/pull-tight equivalent to `PullTightAlgoAnyAngle`.
- Any-angle routing option when angle restriction is “none”.

Implementation (fixed, deterministic, portable enough):
- Routing remains grid-based but allows a higher direction set on fine grid:
  - 16-direction moves (multiples of 22.5°) with integer costs approximating Euclidean length.
- After routing, produce any-angle segments by fitting and validating:
  - merge collinear-ish segments,
  - run pull-tight using an exact local clearance checker (same as R13 commit-time validator),
  - accept changes only if they reduce weighted length and preserve clearance.

Validation gates:
- Add a Tier-1 “any-angle required” DSN fixture and require completion within budget.
- Ensure determinism under fixed seed.
