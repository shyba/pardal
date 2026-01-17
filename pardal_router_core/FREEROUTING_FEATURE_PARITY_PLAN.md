# FreeRouting Feature Parity Plan (Rust) — TDD Roadmap

This is a formal, test-driven plan to bring `pardal_router_core` to *practical batch-autorouter* feature parity with FreeRouting for the DSN/Spectra ecosystem.

**Scope**
- Target parity: FreeRouting’s *batch autorouter* for DSN → routed result (SES or DSN wiring), and the rules/DRC behavior that governs it.
- Non-goals (for parity): FreeRouting GUI, interactive editor UX, and KiCad plugin UX. (We still need the underlying shove/push algorithms because batch routing can depend on them.)

**Current baseline**
- Strong DSN ingestion + nm-level DRC + grid-based IR + fast goal-directed 3D routing for two-pin connections.
- Missing: negotiation/ripup, rule-driven widths/clearances/vias during routing, shove/push, and FreeRouting-like free-space (non-grid) routing fidelity.
- Recent IR/router improvements:
  - `RoutingIr.pad_owner` separates “unpoppable” pad copper from trace occupancy, enabling safer future negotiation (pads are never crossable by other nets).
  - DSN export stitches pin centers to the routed grid endpoints so FreeRouting recognizes connectivity in headless DRC runs.
  - Any layer transition is now committed as a through-hole via occupying all layers, which prevents “via through other net’s pad” clearance errors (at the cost of fewer routed nets).
  - A minimal deterministic ripup loop exists (`route_nets_negotiation_basic_with_brushes`) as a stepping stone (not parity).

**Recent harness work (already landed)**
- FreeRouting “oracle” runner via Docker: `tools/freerouting_oracle.sh`
  - emits `*.oracle.stats.json` (JSON object extracted from CLI stdout)
  - may not emit an output design unless the job completes; treat `BoardStatistics` as the oracle.
- Parity runner + smoke report:
  - `tools/run_parity.sh` runs Rust routing + FreeRouting oracle + FreeRouting DRC on input and Rust output DSNs.
  - `tools/run_parity_smoke.sh` runs a fixed corpus and writes `build/parity_smoke_report.md`.
  - `pardal_parity_extract` normalizes FreeRouting metrics JSON (including the KiCad-schema DRC JSON FreeRouting emits).
- DSN edit utility: `dsn/edit.rs` (`append_wiring_exprs`) so we can generate DSN outputs FreeRouting headless can load.

---

## 1) Define What “Parity” Means (Acceptance Criteria)

We call feature parity reached when all of the following are true:

### 1.1 Functional parity (batch routing)
- For a defined parity corpus (see §2), the Rust autorouter:
  - routes the same “completable” boards to completion (all nets connected), or
  - reaches the same conclusion (“cannot complete under constraints”) within a comparable time budget.

### 1.2 Rules parity (routing consumes rules, not just DRC)
- Routing respects:
  - clearance matrices (netclass + default + item-type)
  - per-net / per-class widths (per layer if present)
  - via rules: allowed padstacks, allowed layer transitions, via cost/penalties, via keepouts
  - layer direction preferences / penalties
  - keepins/keepouts, boundary + holes

### 1.3 Output parity (SES/DSN interoperability)
- Rust can:
  - read DSN → route → write SES (or DSN wiring) that FreeRouting/KiCad can load
  - preserve net identities, layers, and geometry in supported constraints (45°/90°)

### 1.4 DRC parity (post-route verification)
- Rust DRC results are consistent with FreeRouting’s own DRC model for:
  - clearance violations
  - unconnected items
  - keepout violations
  - boundary/cutout violations

**Note:** absolute equality of routes is not required; equality of *validity* and *completion under constraints* is required.

---

## 2) TDD Harness: “FreeRouting Oracle” + Corpus

Parity needs a reliable oracle to compare against. This plan assumes we use the `freerouting/` source already in this repo as the reference implementation.

### 2.1 Add an oracle runner (tooling, not unit tests)
Create `pardal-pcb/pardal_router_core/tools/freerouting_oracle.sh` that:
- runs FreeRouting headlessly on a DSN with deterministic settings:
  - fixed `random_seed`
  - fixed number of passes
  - fixed shove/push mode, angle restriction, via rules
- emits:
  - routed output file(s) (SES preferred)
  - a JSON summary (metrics) including:
    - routed / unrouted connection count
    - DRC violation counts (by type)
    - via count, total trace length, layer usage
    - runtime per phase (if available)

### 2.2 Add a Rust comparison harness (integration tests)
Add `pardal-pcb/pardal_router_core/tests/parity_oracle_tests.rs`:
- picks a small set of fixtures (fast) by default
- runs:
  1) Rust router → output
  2) Rust DRC → metrics
  3) FreeRouting oracle → metrics (from JSON)
  4) compare metrics under thresholds (exact match where feasible)

**Keep tests fast**: oracle tests should be `#[ignore]` by default; CI can run them in a nightly/extended job.

### 2.3 Define corpora
Maintain three corpora lists (explicit file lists, not globs):
- **Smoke (fast, per-PR)**: 5–10 DSNs covering corner cases
- **Parity (medium, daily)**: ~30 DSNs representing real boards
- **Stress (slow, manual)**: large boards (FPGA/BGA-class)

Use existing fixtures in `freerouting/tests/*.dsn` plus add minimal synthetic DSNs in:
- `pardal-pcb/pardal_router_core/tests/fixtures/*.dsn`

#### Current stress baseline (grid router, not parity)
- Synthetic `ring_escape_multi` BGA (600 pins) is used as a stress/perf target via `tools/run_bga_bench.py`.
- Best known “Rust(off)” config (Dec 2025):
  - `PARDAL_ROUTE_ORDER=angle`
  - `PARDAL_BRUSH_SHAPE=euclidean`
  - `PARDAL_DYNAMIC_COST_REBUILD_EVERY=16`
  - Results: `53/600` routed with `0` FreeRouting DRC clearance violations, in ~`115s`.
  - Report: `pardal-pcb/pardal_router_core/build/bga_bench_report.bga_ring_escape_multi_p2_angle_dyn16_euc_heapreuse_600_v2.md`
- FreeRouting often times out on this scenario under the same 180s budget at low pass counts; treat it as a “stress signal”, not a strict parity oracle.

### 2.4 Metrics schema (stable)
Define a stable JSON schema for parity comparisons:
- `board_id`, `seed`, `settings_hash`
- `connections_total`, `connections_unrouted`
- `drc`: counts by category + top-N sample locations
- `vias_total`, `trace_length_total`, `segments_total`
- `runtime_ms`: stage breakdown

---

## 2.5 Feature Parity Checklist (What Must Exist)

This checklist is the “definition of done”. Every item below must have:
- a Rust implementation (in `pardal_router_core`)
- at least one unit/integration test
- at least one oracle comparison fixture (unless it’s pure internal refactoring)

| Area | FreeRouting reference (source) | Rust target module(s) | Required tests (TDD) |
|---|---|---|---|
| DSN read | `board/HeadlessBoardManager.loadFromSpecctraDsn` | `dsn/*`, `dsn_to_nm.rs`, `dsn_to_ir.rs` | existing DSN corpus tests + new edge cases as found |
| DRC | `drc/DesignRulesChecker` | `drc_nm.rs`, `clearance_nm.rs`, `connectivity_nm.rs` | compare counts on fixtures; geometry-specific unit tests |
| Rules model | `rules/*` (`ClearanceMatrix`, `NetClasses`, `ViaRule`) | `dsn/net_rules.rs` (+new `rules/` proposed) | DSN→rules extraction unit tests |
| Router pass loop | `autoroute/BatchAutorouter` | `autoroute/batch.rs` | deterministic pass-loop tests, progress/stagnation tests |
| Connection router entry | `autoroute/AutorouteEngine.autoroute_connection` | `autoroute/engine.rs` | 2-pin route tests under constraints; conflict handling tests |
| Maze search | `autoroute/MazeSearchAlgo*` | `autoroute/maze.rs` | corridor + obstacle + via tests (golden routes not required) |
| Insert path | `autoroute/InsertFoundConnectionAlgo` | `autoroute/insert.rs` | insert -> connectivity ok, DRC ok, geometry invariants |
| Locate path | `autoroute/LocateFoundConnectionAlgo*` | `autoroute/locate.rs` | angle restriction tests (45/90) and simplification |
| Ripup selection | `autoroute/*rip*` + `BoardHistory` | `autoroute/ripup.rs` | deadlock fixtures that require ripup to succeed |
| History costs | `autoroute/AutorouteControl` cost factors | `autoroute/costs.rs` | monotonicity tests, determinism tests |
| Shove/push | `autoroute/MazeShoveTraceAlgo` + interactive shove | `autoroute/shove.rs` | “only solvable by shove” fixture |
| Optimization | `autoroute/BatchOptimizer*` | `autoroute/optimize.rs` | “no DRC regression” + via reduction non-increase |
| Output (SES/DSN) | `Specctra*Writer` | `ses.rs` + `dsn/edit.rs` (+ future DSN writer) | roundtrips; FreeRouting load-smokes |

This table should be kept up-to-date as we implement parity phases.

## 3) Architectural Roadmap (Match FreeRouting’s Core Concepts)

FreeRouting’s batch autorouter (high level) is roughly:
1) choose an unrouted connection
2) run a maze search in free space (not a uniform grid)
3) if needed, rip up conflicting items
4) insert found connection
5) repeat across passes, using history/costs + optimization

In FreeRouting sources, key components are in:
- `app.freerouting.autoroute.*` (BatchAutorouter, AutorouteEngine, MazeSearchAlgo, *FoundConnection* algos)
- `app.freerouting.rules.*` (clearance matrices, netclasses, via rules)
- `app.freerouting.drc.*` (DesignRulesChecker)
- `app.freerouting.geometry.planar.*` (robust planar geometry, 45°/orthogonal primitives)
- `app.freerouting.board.*` (board object model, shape search trees)

### 3.1 Target Rust module map (proposed)
Add/extend modules under `pardal_router_core/src/`:
- `specctra/`:
  - `dsn.rs` (already) + `ses.rs` (add full SES read/write)
- `rules/`:
  - `clearance_matrix.rs`
  - `netclasses.rs`
  - `via_rules.rs`
  - `layer_rules.rs` (preferred directions/penalties)
  - `autoroute_settings.rs` (seed/pass counts/ripup costs)
- `geom/` (already partially present):
  - add robust 45°/orthogonal segment/offset primitives used by routing+DRC
- `board/`:
  - board database of items (traces/vias/areas), connectivity, and incremental updates
  - spatial index abstraction (R-tree / BVH / grid buckets)
- `autoroute/`:
  - `batch.rs` (pass loop, scoring, termination)
  - `engine.rs` (per-connection autoroute entry)
  - `maze.rs` (maze search; orth/45/any-angle variants)
  - `ripup.rs` (conflict selection + removal)
  - `insert.rs` (convert maze result into trace/via items)
  - `optimize.rs` (pull tight, via reduce)

### 3.2 Bridging strategy (keep current grid router)
Keep the current grid IR router as:
- a fallback backend for early milestones, and
- a debugging tool for reachability.

Primary parity routing backend should migrate to **free-space / expansion-graph routing** like FreeRouting (necessary for:
- geometric correctness independent of grid pitch
- 45° rules
- shove/push interactions
- rule-exact clearances without coarse dilation artifacts)

---

## 4) Implementation Phases (TDD First)

Each phase has:
- **Tests to write first**
- **Implementation tasks**
- **Exit criteria**

### Phase 0 — Tooling + Oracles (foundation)
**Tests first**
- Add a failing “oracle contract” test that:
  - runs FreeRouting oracle on a tiny synthetic DSN and parses the metrics JSON.

**Implement**
- `tools/freerouting_oracle.sh` (deterministic run + metrics JSON)
  - uses FreeRouting CLI mode (GUI+API disabled)
  - concrete CLI args (from upstream `GlobalSettings.applyCommandLineArguments`):
    - input: `-de <design.dsn>`
    - output: `-do <out.ses>`
    - passes: `-mp <max_passes>`
    - threads: `-mt <threads>`
    - seed: `-random_seed <hex>`
  - recommend forcing CLI mode: `--gui-enabled=false --api_server-enabled=false`
- `tools/metrics_schema.md` (document schema)
- `tests/parity_oracle_tests.rs` (ignored by default)

**Exit**
- Oracle can run one DSN end-to-end and produce stable metrics.
  - Note: FreeRouting headless `BoardLoader` currently loads **DSN only**; CLI may not write an output design unless the job is `COMPLETED`. The oracle should treat the printed `BoardStatistics` JSON as the primary artifact.

### Phase 1 — SES Interop (output pipeline)
FreeRouting’s “product” is routed items; SES is the primary exchange format.

**Tests first**
- Roundtrip tests:
  - DSN → SES (oracle) → parse SES → item counts stable
  - Rust SES writer produces SES that FreeRouting can load (smoke).

**Implement**
- SES parser/writer in Rust:
  - segments, vias, net names, layers
  - units + coordinate transforms
- `pardal_ses_check` binary analogous to `pardal_dsn_check`

**Exit**
- For a fixture DSN, Rust can emit SES with a small inserted route and FreeRouting loads it.

### Phase 2 — Rules as Data (shared by DRC + routing)
**Tests first**
- Unit tests for parsing rules:
  - clearance matrix extracted correctly
  - netclasses and default rules correct
  - via rules list and allowed stacks correct
  - autoroute settings parsed (seed, passes, costs)

**Implement**
- Central `RulesDb` derived from DSN:
  - used by both DRC and autoroute
- Explicit item-type clearance handling (trace/via/pad/area)

**Exit**
- Routing code can query `RulesDb` for (net, layer, item-type) → width/clearance/via-allowance.

### Phase 3 — Board Database + Spatial Index (incremental updates)
FreeRouting maintains a “board database” + search trees updated as routes are inserted/ripped.

**Tests first**
- Insert/remove trace/via updates connectivity and spatial index:
  - queries for nearest obstacles match expected
  - removing a route restores previous state

**Implement**
- `BoardDb`:
  - item store (traces/vias/areas)
  - per-net connectivity graph (union-find + terminals)
  - spatial index (layered R-tree or bucket grid)
- incremental update hooks

**Exit**
- Can insert a route, detect conflicts by geometric clearance, and rip it back out deterministically.

### Phase 4 — Maze Router on Free Space (orthogonal + 45°)
This is the core of FreeRouting’s routing quality.

**Tests first**
- Synthetic fixtures:
  - “corridor” routing: must pick legal path
  - “corner-cut” case: must respect 45° + no corner cutting
  - via transition test: must respect via_forbidden + via rules
- Golden metric tests vs FreeRouting on small fixtures:
  - completion status equal
  - DRC count equal (0)

**Implement**
- Expansion graph (rooms + doors) or equivalent sparse routing graph:
  - represent free space as navigable regions
  - edges carry costs (length, layer penalty, via cost, history)
- Maze search implementation (A*):
  - orth-only and 45° variants (match DSN angle restriction)
- “LocateFoundConnection” equivalent:
  - convert maze path into actual trace/via geometry respecting widths
- “InsertFoundConnection” equivalent:
  - commit into `BoardDb` with conflict checks

**Exit**
- Routes a set of 2-pin connections on medium fixtures with 0 DRC violations.

### Phase 5 — Ripup + Negotiation (batch completion loop)
FreeRouting’s advantage is negotiation: reroute with increasing costs until completion or timeout.

**Tests first**
- Construct fixtures where:
  - naive sequential routing fails (deadlock)
  - negotiation succeeds (requires ripup)
- Determinism tests:
  - same seed/settings → same metrics

**Implement**
- Batch pass loop similar to `BatchAutorouter`:
  - choose unrouted “connections to do”
  - attempt route with current costs
  - on conflict: ripup selected items (strategy: least critical / low cost / local)
  - reinsert and update history cost
- Termination:
  - max passes
  - stagnation detection
  - time budget
- Scoring:
  - connections unrouted (primary)
  - violations (secondary)
  - via count / length (tertiary)

**Exit**
- Completes parity corpus “Parity (medium)” to the same completion status as FreeRouting.

### Phase 6 — Shove/Push (needed for dense boards)
Even in batch routing, shove can be necessary to escape dense pin fields without excessive ripup.

**Tests first**
- A “blocked channel” fixture:
  - only solvable if a foreign trace is shifted within constraints
- Keepout + clearance invariants:
  - shove must not introduce violations

**Implement**
- Shove router primitives:
  - detect movable segments
  - compute legal displacement corridor
  - reroute/repair affected nets locally
- Integrate with negotiation:
  - shove allowed based on settings
  - fallback to ripup if shove fails

**Exit**
- Passes shove-specific fixtures; improves completion rate on dense corpus boards.

### Phase 7 — Optimization passes (pull-tight, via reduce, smoothing)
**Tests first**
- Optimization must preserve:
  - connectivity
  - 0 DRC violations
- Metric improvement checks:
  - via count non-increasing (via reduce mode)
  - length non-increasing (pull tight)

**Implement**
- Pull tight accuracy controls (like FreeRouting’s)
- Via optimizer:
  - attempt via elimination by rerouting locally on preferred layers

**Exit**
- Produces routes closer in quality metrics to FreeRouting on medium boards.

### Phase 8 — Full-parity validation + regression gating
**Tests first**
- Golden oracle tests for:
  - completion status on full parity corpus
  - DRC == 0 for already-routed fixtures

**Implement**
- CI targets:
  - quick unit suite
  - “smoke parity” (ignored by default locally; enabled in scheduled CI)
- Regression guardrails:
  - `PARDAL_TIMING` stage budgets per fixture
  - `--seed` / settings hash stored with outputs

**Exit**
- Documented, reproducible parity across the corpus, with stable performance.

---

## 5) Execution Backlog (Ordered, No Mid-Flight Decisions)

This section expands the TODO list into PR-sized tasks with explicit tests and exit criteria. It is intentionally long and explicit so a dev can execute it without “what next?” decisions.

### Conventions used in this backlog
- **PR size**: aim for 1–3 days of work per item.
- **TDD**: every item starts by adding a failing test (or an ignored oracle test) that becomes green.
- **Exit**: each item has a concrete command to run and expected outcome.

### 5.0 Parity harness hardening (do before routing parity work)
- [x] Add `tests/parity_oracle_tests.rs` cases for a *fixed smoke list* (5 DSNs), all `#[ignore]`.
  - **Tests**: oracle produces parseable JSON, and required fields exist.
  - **Exit**: `cargo test -q --test parity_oracle_tests -- --ignored` passes locally.
- [x] Add `tools/run_parity_smoke.sh` that runs the fixed smoke list and produces a single markdown report.
  - **Tests**: none (tooling), but run it in CI nightly later.
  - **Exit**: report lists per-case: FreeRouting stats, Rust stats, and FreeRouting DRC on Rust DSN.
- [x] Define a *stable field extraction layer* for FreeRouting JSON (don’t depend on full schema).
  - **Tests**: unit tests on stored JSON snippets (fixtures).
  - **Exit**: changes to unrelated FreeRouting JSON fields don’t break parsing.

### 5.1 Output parity scaffolding (so we can compare like-for-like)
- [ ] DSN output: implement a dedicated DSN writer for wiring (not just “append exprs”).
  - **Tests**: roundtrip “parse tokens -> write -> tokenize” + “(pcb ...) still valid”.
  - **Exit**: `pardal_route_dsn` can output a DSN whose `(wiring ...)` is canonicalized and deterministic.
- [ ] SES input: implement SES parser for `network_out` wires/vias (minimal).
  - **Tests**: parse FreeRouting-produced SES from a fixture; count wires/vias per net.
  - **Exit**: a Rust tool can read SES and produce the same nm tracks/vias as expected (within rounding tolerance).
- [ ] “Route artifact pack”: define a directory layout and manifest JSON for a single run.
  - **Tests**: manifest schema unit test.
  - **Exit**: both oracle and Rust runs write artifacts in identical layout for comparison tooling.

### 5.2 RulesDb v1 (routing consumes rules, not only DRC)
- [ ] Create `src/rules/` module with:
  - `RulesDb` (default + per-net + per-class)
  - `ClearanceDb` (clearance matrix, typed clearances)
  - `WidthDb` (track widths per net/class/layer)
  - `ViaDb` (via rules, allowed padstacks, layer spans)
  - `LayerPrefs` (preferred direction/penalty, active layers)
  - **Tests**: DSN fixtures where each rule kind is present; assert extracted values.
  - **Exit**: `RulesDb` can answer queries: `(net, layer, item_kind) -> (width, clearance, via_allowed?)`.
- [ ] Wire RulesDb into DRC uniformly (single source of truth).
  - **Tests**: DRC tests stay green + add one fixture where a per-net override changes DRC outcome.
  - **Exit**: DRC no longer uses “default fallbacks” outside RulesDb.
- [ ] Implement FreeRouting-equivalent `AutorouteControl` inputs (same semantics, Rust-side):
  - layer activation sources:
    - global active layers (KiCad/DSN structure)
    - per-netclass routing layers (`class (circuit (use_layer ...))`)
    - DSN `autoroute_settings.layer_rule.active`
  - preferred direction + direction penalties:
    - DSN `autoroute_settings.layer_rule.preferred_direction`
    - `preferred_direction_trace_costs` / `against_preferred_direction_trace_costs`
  - via availability:
    - global `autoroute_settings.vias`
    - `autoroute_settings.plane_via_costs` (if present, model as additional penalties near planes/areas)
    - class `via_rule` + `via_rule` mapping to padstacks
    - layer span legality and attach_smd permission
  - effective half-widths:
    - per-net/per-layer half-width (width_db)
    - clearance compensation values (to match FreeRouting’s compensated search trees)
  - via cost scaling:
    - FreeRouting uses `min_normal_via_cost = via_costs * max_via_radius` (max_via_radius includes trace half-width)
    - implement the same scaling so history/maze costs are comparable
  - pass controls:
    - `autoroute_settings.start_pass_no` (seed initial pass index)
    - `autoroute_settings.fanout` / `postroute` / router enabled flag (control which phases execute)
    - “remove unconnected vias” policy (affects what gets ripped/kept during negotiation)
  - shove/pull-tight recursion limits + accuracy knobs (wire into settings, used later)
  - **Tests**:
    - DSN fixture containing `autoroute_settings` + `layer_rule` fields → assert extracted values
    - DSN fixture with via rules + layer spans → assert allowed transitions
  - **Exit**: for a given DSN+net, we can build an `AutorouteControlLike` struct covering every field FreeRouting’s autorouter reads.

### 5.3 Board database v1 (incremental, rule-aware collisions)
- [ ] Implement `BoardDb` that stores:
  - terminals (pads/pins), tracks, vias, areas
  - per-net connectivity (union-find + terminal sets)
  - spatial index per layer (start with bucket grid; later swap to R-tree if needed)
  - **Tests**: insert/remove roundtrip, connectivity updates, collision queries.
  - **Exit**: can detect “would violate clearance?” for a candidate segment/via under RulesDb.
- [ ] Add “candidate evaluator” API:
  - `can_place_trace_segment(net, layer, seg, width) -> bool + violations`
  - `can_place_via(net, x,y, via_padstack) -> bool + violations`
  - **Tests**: golden “should fail on keepout”, “should fail on clearance”.
  - **Exit**: evaluator matches nm-DRC decisions on small synthetic cases.
- [ ] Add FreeRouting-style “search trees” abstraction (needed for rooms/doors routing):
  - default tree (“all objects” collisions)
  - autoroute tree variants keyed by:
    - angle restriction family (90° vs 45°)
    - compensated clearance class (0 = none; >0 = compensated)
    - trace width tolerance grouping (FreeRouting uses `TRACE_WIDTH_TOLERANCE` when selecting trees for performance)
  - required ops:
    - `overlapping_objects(shape, layer)`
    - `overlapping_tree_entries_with_clearance(shape, layer, net_ids, clearance_class)` (net-aware)
    - `reduce_trace_shape_at_tie_pin(pin, foreign_trace)` (tie-pin handling)
  - incremental invalidation hooks:
    - when an item changes, invalidate rooms touching its shapes (parity with `RoutingBoard.additional_update_after_change`)
  - **Tests**:
    - overlap query golden tests (track/track, track/via, track/area)
    - tie-pin synthetic: pin center stays connectable for multiple nets
  - **Exit**: the maze router can depend on `BoardDb+SearchTree` without any uniform grid.

### 5.4 Maze router v1 (free-space routing, not grid)
Goal: implement FreeRouting-style *sparse* search (rooms/doors / expansion graph) sufficient to route dense boards.

- [ ] Implement a “free space graph” representation:
  - rooms: maximal free-space regions under clearance
  - doors: adjacency edges between rooms (plus via transitions)
  - **Tests**: build graph on synthetic obstacles; assert reachability sets.
  - **Exit**: graph build is deterministic and bounded (no combinatorial blow-ups on fixtures).
- [ ] Implement A* maze search on that graph with:
  - cost: length + via cost + layer penalty + history
  - heuristic: admissible lower bound on remaining cost
  - **Tests**: corridor, maze, via-only escape, keepout-only escape.
  - **Exit**: routes those fixtures with 0 DRC violations.
- [ ] Implement “locate path → geometry”:
  - enforce angle restriction (45°/90°) by construction
  - simplify segments deterministically (no jitter)
  - **Tests**: angle restriction tests; “no corner cutting” tests.
  - **Exit**: produced geometry passes DRC for fixtures.
- [ ] Implement `LocateFoundConnectionAlgo` parity (turn backtracked doors into concrete wires/vias):
  - compute start/target connection points from item “connection shapes”
  - handle conduction-area targets by shrinking target shapes by trace half-width (FreeRouting does this for safety)
  - support 45°/90° angle restriction by selecting the appropriate locator variant
  - stitch into existing copper (connect-to-trace) deterministically
  - **Tests**:
    - fixture: connect pin→pin (simple), pin→trace, pin→area
    - fixture: 45° only board must produce only 45°-legal segments
  - **Exit**: FreeRouting loads the SES/DSN output and reports identical `unconnected_items_total` for those fixtures.
- [ ] Implement “insert path”:
  - insert into BoardDb; update connectivity and spatial index
  - **Tests**: insert then query collisions -> none, connectivity -> connected.
  - **Exit**: repeated insertions do not leak state; remove works.
- [ ] Implement minimal `InsertFoundConnectionAlgo` parity without shove (Phase 5.6 adds shove):
  - create vias between layers using per-net `via_rule` selection
  - insert trace polylines if `can_place_*` says it’s clear (no shoving yet)
  - normalize traces after insert (merge collinear segments, collapse zero-length)
  - remove “trace tails” created by partial inserts (when appropriate)
  - **Tests**:
    - insert a located path and verify BoardDb connectivity and DRC is clean
    - roundtrip: FreeRouting DRC on Rust-exported DSN/SES is not worse than baseline
  - **Exit**: Maze route + locate + insert can complete at least one small fixture end-to-end without any shove/ripup.
- [ ] Match FreeRouting’s maze primitives explicitly (avoid hidden missing pieces):
  - `MazeSearchElement` parity:
    - `is_occupied`
    - backtrack pointers (`backtrack_door`, `section_no_of_backtrack_door`)
    - `room_ripped`
    - `adjustment` (placeholder until shove is implemented)
  - `MazeListElement` parity:
    - door + section index
    - g-cost, f-cost/sorting_value
    - next_room pointer
  - door types:
    - `TargetItemExpansionDoor` (start/target item door, “is destination?”)
    - `ExpansionDrill` (via transitions, multi-section over layers)
    - `DrillPage` + `DrillPageArray` (paging optimization for drills/vias)
  - room types:
    - `CompleteFreeSpaceExpansionRoom` / `IncompleteFreeSpaceExpansionRoom`
    - `ObstacleExpansionRoom` (for ripup bookkeeping)
  - **Tests**:
    - backtracking reconstructs a valid door chain (no cycles, indices in range)
    - determinism with fixed seed (stable expansions order and result)
  - **Exit**: a two-pin connection can be found and “located” into a 45°/90° polyline using these primitives (still without shove/ripup).

### 5.5 Negotiation router v1 (ripup + reroute loop)
Goal: reach FreeRouting’s completion behavior on medium boards.

- [ ] Define a “connection” representation identical to FreeRouting’s goal:
  - net terminals partitioned into connected components
  - next target: connect components until one component remains
  - **Tests**: synthetic multi-pin nets, already-connected detection.
  - **Exit**: connection planner yields same “remaining connections” count as nm connectivity.
- [ ] Implement pass loop:
  - choose next unrouted connection (prioritized strategy)
  - attempt route with current history costs
  - if conflicts: pick ripup set, rip, retry
  - update history and/or ripup costs
  - **Tests**: deadlock fixture: sequential routing fails, negotiation succeeds.
  - **Exit**: oracle parity on a small negotiation fixture: FreeRouting completes, Rust completes.
- [ ] Add stagnation detection + termination:
  - stop if no progress after N passes
  - stop if time budget exceeded
  - **Tests**: fixture that cannot be completed; ensure termination reason is stable.
  - **Exit**: router returns a structured `Conclusion` (COMPLETED / INCOMPLETE / IMPOSSIBLE / TIMEOUT).
- [ ] Add FreeRouting-like scoring + board history:
  - implement a `BoardStatistics`-like snapshot in Rust (connections incomplete, DRC violations, via count, length, etc.)
  - implement `BoardHistory`:
    - keep best boards by score
    - restore the best board after a pass (parity with `BatchAutorouter`)
  - optional multi-thread best-of-N pass attempt (parity with `BatchAutorouter.autoroute_pass_multi_thread`):
    - clone board, shuffle autoroute item list, run N attempts, keep best
  - **Tests**:
    - deterministic score for a fixed board state
    - restore picks best board among candidates
  - **Exit**: on at least one fixture where order matters, best-of-N improves completion within the same time budget.

### 5.6 Shove/push v1 (dense escape)
Goal: solve cases where pure ripup negotiation is too expensive or fails.

- [ ] Implement minimal shove primitive:
  - when new segment intersects clearance region of an existing segment:
    - attempt to locally reroute the existing segment within a bounded corridor
  - **Tests**: “blocked channel solvable only by shove”.
  - **Exit**: shove resolves that fixture with 0 DRC violations.
- [ ] Integrate shove into negotiation loop with strict safety:
  - shove must be reversible; if it fails, revert and fall back to ripup.
  - **Tests**: shove attempt that fails must not change final state.
  - **Exit**: determinism and state integrity tests remain green.
- [ ] Implement FreeRouting-style “forced insertion” APIs (these are the shove engine surface area):
  - `check_trace_segment` equivalent:
    - compute “max insertable length” before collision, honoring clearance compensation settings
  - `insert_forced_trace_polyline` equivalent:
    - insert the polyline incrementally, shoving aside obstacles up to recursion limits
    - support “spring over” behavior (retry with more distant corners) to resolve local violations
  - neckdown support (optional for parity, but needed for production boards):
    - detect pin endpoints and use pin neckdown widths when required
  - **Tests**:
    - synthetic shove: insert trace must push movable obstacle trace out of the way
    - negative case: shove-fixed obstacle must prevent insertion (and revert cleanly)
  - **Exit**: `InsertFoundConnectionAlgo` can complete traces that require shove without leaving DRC violations.

### 5.7 Optimization passes (quality parity)
- [ ] Pull-tight:
  - shorten within free space while preserving DRC
  - **Tests**: length non-increasing; DRC unchanged; connectivity unchanged.
  - **Exit**: improves metrics on at least one medium fixture.
- [ ] Via reduction:
  - try via elimination by layer reassignment / local reroute
  - **Tests**: via count non-increasing; DRC unchanged.
  - **Exit**: improves via count on at least one medium fixture.

### 5.8 Determinism + performance gates (must-have for parity)
- [ ] Deterministic tie-break policy everywhere (routing, ripup selection, shove choice).
  - **Tests**: “same seed/settings → same output hash” on small fixtures.
  - **Exit**: stable output hashes across 10 runs.
- [ ] Budgeted routing:
  - enforce per-connection and per-pass time budgets
  - **Tests**: timeouts return a stable conclusion and do not corrupt board state.
  - **Exit**: stress fixtures stop cleanly and reproducibly.
- [ ] Performance regression guard:
  - stage timing budget file with per-fixture maxima
  - **Tests**: optional/ignored “perf guard” tests for local profiling.
  - **Exit**: performance doesn’t regress >X% without explicit update to budgets.

---

## 6) Validation Commands (as the project evolves)

Current repo tooling that should remain usable throughout:
- Rust: `cd pardal-pcb/pardal_router_core && cargo test -q`
- Corpus: `bash pardal-pcb/pardal_router_core/tools/run_freerouting_corpus.sh --drc all --dsn-timeout 10 --slow 10`
- Routing smoke: `bash pardal-pcb/pardal_router_core/tools/run_freerouting_corpus.sh --drc none --route --route-pitch auto --route-net-limit 10 --slow 10`
- Timing: `PARDAL_TIMING=1 cargo run -q --bin pardal_route_dsn -- ../../freerouting/tests/Issue289-Autorouter_PCB_FHT-VGA_2024-03-25.dsn ALL auto auto 10 auto`
- Export routed artifacts:
  - `PARDAL_ROUTE_SES_OUT=/tmp/out.ses cargo run -q --bin pardal_route_dsn -- <dsn> ALL auto auto 10 auto`
  - `PARDAL_ROUTE_DSN_OUT=/tmp/out.dsn cargo run -q --bin pardal_route_dsn -- <dsn> ALL auto auto 10 auto`

Parity tooling (Phase 0):
- `bash pardal-pcb/pardal_router_core/tools/run_parity.sh freerouting/tests/Issue313-FastTest.dsn 0xDEADBEEF 1 10`
- `bash pardal-pcb/pardal_router_core/tools/run_parity_smoke.sh 0xDEADBEEF 1 10`
- `bash pardal-pcb/pardal_router_core/tools/run_parity_smoke_matrix.sh 0xDEADBEEF 1 10`
- `cd pardal-pcb/pardal_router_core && cargo test -q --test parity_oracle_tests -- --ignored`

---

## 7) Reality Check: What Requires Leaving the Grid

If “feature parity” is literal (not “good enough”), the following require non-grid routing:
- exact 45°/90° constraint routing with robust clearance
- shove/push interactions
- FreeRouting’s free-space “expansion room” style maze search

Therefore this plan intentionally migrates the *primary* autorouting backend from the grid IR to a free-space/graph representation, while keeping the grid router as a debugging fallback.

---

## 8) “Parity Confidence” Work Products (to avoid hidden missing pieces)

To be “sure it will reach parity”, the plan must produce the following *auditable artifacts* along the way:

1) **Feature checklist completion log**
- A markdown table (like §2.5) where every row has:
  - a link to the Rust module
  - a link to the tests that cover it
  - at least one oracle fixture that exercises it
  - (recommended) keep a class-level parity matrix up to date: `FREEROUTING_CLASS_PARITY_MATRIX.md`
  - (required) keep the test mapping auditable: `FREEROUTING_PARITY_TEST_MATRIX.md`

2) **Oracle parity report**
- A generated report that, for each parity fixture:
  - prints FreeRouting stats (connections incomplete, clearance violations, via count)
  - prints Rust stats in the same schema
  - shows diffs and whether they’re within tolerance

3) **Reproducibility report**
- For 5 representative fixtures:
  - run 10 times with same seed
  - show stable output hash + stable metrics

4) **Performance report**
- For stress fixtures:
  - include routing time budget and achieved time
  - show worst-case time and memory consumption

If any of these reports cannot be produced, it indicates a missing parity component (or missing observability).
