# Rust Autorouter Feature-Parity Plan (Freerouting → `pardal-pcb` Rust backend)

This document is an **exhaustive, execution-ordered plan** to reach **feature parity with Freerouting’s routing capabilities** in the Rust backend used by `pardal-pcb` (currently `pardal-pcb/pardal_router_cli/src/main.rs`).

It is written as a **formal TODO list** with **acceptance criteria**, **test/bench requirements**, and explicit **implementation order** (no “decide later” gaps).

> Scope note: Freerouting is a full application (GUI, job server, analytics, etc.). This plan targets **routing feature parity** (fanout + autoroute + optimize + DRC + rules), and “parity” means: **for the same inputs and rules, the Rust router can produce routes that pass DRC and are comparable in completion rate/quality to Freerouting on Freerouting’s own test designs**.

---

## Status (repo reality)

This repo already contains a partial “parity groundwork” implementation:

- Rust crates:
  - `pardal-pcb/pardal_router_core/` exists and already contains:
    - a DSN tokenizer + summary + partial model extraction (`pardal-pcb/pardal_router_core/src/dsn/`)
    - DSN → grid IR stamping utilities (`pardal-pcb/pardal_router_core/src/dsn_to_ir.rs`)
    - grid routing kernels and reference routers (`pardal-pcb/pardal_router_core/src/kernels.rs`, `pardal-pcb/pardal_router_core/src/router.rs`)
  - `pardal-pcb/pardal_router_cli/` exists and is used by `pcb_tool.cli rust-route` today.
- Tests:
  - DSN parsing smoke tests already exist under `pardal-pcb/pardal_router_core/tests/`.

Important caveat:
- The current Rust routing is still fundamentally **grid-based**, while Freerouting’s routing is **continuous geometry** + negotiation + shove + optimization. This plan remains the correct path to parity, but several “big re-architecture” steps are still required.

### Current TODO (active, execution-ordered)

- [x] DSN tokenize + summary extraction (smoke corpus coverage)
- [x] DSN model extraction (pins, nets, placements, padstack radii + layer presence)
- [x] DSN boundary polygon extraction
- [x] DSN wiring extraction (wires + vias) for `path` and `polyline_path`
- [x] DSN wiring → grid IR stamping (net-owned occupancy)
- [x] DSN autoroute_settings extraction (via costs, per-layer preferred directions)
- [x] DSN net rules + netclasses extraction (class net lists, use_via, use_layer, width/clearance when present)
- [x] DSN `structure` typed clearances extraction (e.g. `default_smd`, `wire_via`, `pin_pin`)
- [x] DRC hook supports kind-aware clearance selection (wire/via/pin/smd)
- [x] Continuous-geometry primitives: integer-nm points/segments (foundation for DRC)
- [x] Continuous-geometry DRC skeleton (track/via shorts + clearance)
- [x] DSN wiring → nm track/via conversion (deterministic unit scaling)
- [x] DSN → minimal **continuous-geometry** board model (tracks/vias/terminals in nm)
- [x] Minimal Specctra SES writer (smoke-level; routes only)
- [x] Continuous connectivity check (copper overlap, not exact coords)
- [x] DSN check harness CLI (diagnostics from DSN fixtures)
- [x] Freerouting `.rules` file clearance parsing (typed + matrix) + optional `pardal_dsn_check --rules`
- [x] DSN → nm attaches per-item `clearance_class` ids + terminal `pin_ref` (for per-pin rules); `BoardNm` carries id→name table
- [x] Reusable clearance resolver (net + typed + matrix) for DRC
- [x] Spatial hash index + indexed DRC (track↔track, track↔circle accelerated)
- [x] DSN keepout extraction (structure + image) + placement transforms
- [x] Keepouts converted to nm + keepout overlap checks (circle + polygon)
- [ ] Internal DRC on continuous model (full: pads/keepouts/zones, per-netclass, connectivity)
- [ ] RouterSettings parity: preferred directions, via costs, pass schedule, deterministic seeds
- [ ] Negotiation router: ripup/reroute loop with cost escalation
- [ ] Push-and-shove + local repair
- [ ] Fanout (BGA escape) parity
- [ ] Optimizer parity: pull-tight + smoothing + via/segment reduction
- [ ] Parity harness:
  - [x] Freerouting test corpus runner (DSN in → metrics out) via `pardal-pcb/pardal_router_core/tools/run_freerouting_corpus.sh`
  - [ ] KiCad DRC oracle suite for selected KiCad fixtures

### Next TODO (detailed, no gaps)

**Continuous model**
- [ ] Add `BoardNm` obstacles: keepout polygons, board outline, and plane layers (routing-forbidden layers).
- [x] Add pad geometry beyond circles (rects/polygons/paths/circles w/ offsets) using DSN padstack shapes.
- [ ] Add an `AabbNm` for every primitive and a spatial hash/R-tree index per layer.

**DRC parity**
- [x] Extend DRC to include terminal↔terminal, track↔pad, via↔pad checks with per-layer applicability.
- [ ] Add clearance rules sourced from DSN net classes:
  - [ ] Support per-netclass clearance (when directly specified).
  - [x] Use typed `structure` clearances for object-kind pairs where available (`default_smd`, `via_via`, `smd_smd`, etc).
  - [x] Parse clearance matrix entries from Freerouting `.rules` files (pairwise `"a"-"b"` `type` clearances).
  - [x] DRC clearance callback receives per-item `clearance_class` ids (enables matrix lookup).
  - [ ] Wire clearance matrix model into router rules + route search costs (not just DRC).
- [ ] Add “unconnected items” detection that matches Freerouting semantics (multi-terminal nets).

**SES/DSN interop**
- [ ] Make SES output closer to Freerouting:
  - [x] Emit `library_out` for padstacks (circle + polygon + path + rect-as-polygon).
  - [x] Validate SES lex/parse by running Freerouting headless scanner (`pardal-pcb/pardal_router_core/tools/freerouting_ses_smoke.sh`).
- [ ] Add a small DSN+SES roundtrip test fixture and smoke runner script.

**Routing**
- [ ] Add a continuous-space router skeleton:
  - [ ] Build a coarse routing graph (visibility/corridors) from obstacles expanded by clearance.
  - [ ] Route a single 2-terminal net with costs (length, via, preferred direction).
  - [ ] Gate all placements by DRC before committing.
- [ ] Add negotiation loop (ripup/reroute) around the continuous router.
- [ ] Add fanout primitives for BGA-like terminals.

**Perf / scale**
- [ ] Add per-phase timing JSON (parse, build, route, drc).
- [ ] Replace O(N²) DRC with spatial-indexed sweep and add a perf regression bench.
- [ ] Use the indexed DRC implementation by default in harness tools, and report candidate counts to tune cell sizing.
- [x] Add `pardal_dsn_check --drc {all|copper|keepout|none}` and wire it into corpus runner for fast parse-only passes.

### Sprint Backlog (expanded)

**Correctness / parsing**
- [x] DSN parse: `keepout` shapes beyond `circle/polygon` (`rect`, `path`, `polygon_path`).
- [x] DSN parse: per-pin `clearance_class` overrides inside `placement` → `place` pin scopes.
- [ ] DSN parse: `structure`-level routing rules beyond default `rule` (layer-specific widths, clearances).
- [ ] DSN parse: clearance matrix / class-to-class clearance (Specctra `clearance_matrix` / `clearance_class` patterns).
- [ ] DSN parse: plane/area objects + windows (holes) and map to obstacles.
- [ ] Unit handling: treat `unit` vs `resolution` differences robustly (fixtures where `unit != resolution_unit`).

**Model**
- [x] Represent vias as shapes (not just circles) when padstack shapes exist.
- [ ] Add board outline as an obstacle shape (and its windows/cutouts).
- [ ] Add copper pours/zones as obstacles with toggles per layer.

**DRC**
- [x] Add indexed circle↔circle acceleration (vias/terminals) to remove remaining O(N²) hotspots.
- [x] Add shape-aware via geometry checks (track↔via, via↔terminal, via↔via when via padstacks are non-circles).
- [x] Add “unconnected items” detection closer to Freerouting semantics (copper overlap, not exact center matches).

**Interop**
- [ ] Add DSN→SES roundtrip corpus runner: DSN in → route/DRC → SES out → parse SES for sanity.
- [x] Add a Freerouting headless validation step (local jar) for a small fixture set.

**Performance**
- [x] `pardal_dsn_check`: add timing output + JSON mode (parse/build/drc phases).
- [x] `SpatialHashNm`: remove per-query `HashSet` allocations (implemented sort+dedup scratch in indexed DRC + keepout checks).

## 0) Definitions & Targets

### 0.1 Feature parity definition (routing)
The Rust backend is “feature-parity” with Freerouting when all of the following hold:

1. **Input parity**
   - Reads and routes **KiCad boards** via the existing pipeline (`pcbnew` extract → route → apply).
   - Reads and routes **Specctra DSN** (Freerouting’s canonical exchange format), and can write **SES** (or DSN+session equivalent) such that Freerouting can load the result.
2. **Rules parity**
   - Respects **net classes**, **per-layer constraints**, **via rules/types**, **preferred directions**, **keepouts**, **planes/pours**, and **neckdown** behavior.
3. **Routing parity**
   - Supports **fanout**, **multi-terminal nets**, **ripup/negotiation**, **push/shove**, and **deterministic multi-pass autoroute** comparable to Freerouting.
4. **Optimization parity**
   - Supports **pull-tight**, **corner smoothing**, **via reduction**, and **length/quality scoring**-driven improvement loops.
5. **DRC parity**
   - Provides an internal DRC equivalent in coverage to Freerouting’s DRC (and must also pass KiCad DRC for KiCad outputs).
6. **Reliability parity**
   - Has a regression suite built from Freerouting “issue” tests and additional KiCad DRC-based end-to-end tests.

### 0.2 Non-goals (explicit)
- GUI, interactive editor states, job server, analytics, or Freerouting’s REST API.
- Perfectly identical routing geometry vs Freerouting; only rule compliance + comparable quality metrics are required.

### 0.3 Performance target (parity milestone)
- For the routing-relevant subset of Freerouting’s test corpus adopted here, the Rust backend must:
  - Complete within **≤ 2× Freerouting runtime** on the same machine for mid-size boards.
  - Complete a “large stress” board (e.g. `bga324_breakout2`-class fixture) within a **configurable timeout**, and provide partial results + diagnostics.

---

## 1) Ground Truth: Freerouting Feature Inventory

### 1.1 Key Freerouting subsystems (reference map)
This is the “source-of-truth” list of subsystems we must match:

- **Rules**: `freerouting/src/main/java/app/freerouting/rules/`
  - Net classes, clearance matrix, via rules, shove-fixed nets, etc.
- **Board model**: `freerouting/src/main/java/app/freerouting/board/`
  - Items (traces, vias, pads), obstacles, planes, layer structure.
- **Geometry**: `freerouting/src/main/java/app/freerouting/geometry/` and `geometry/planar/`
  - Robust polygon/segment operations and spatial queries.
- **Autoroute**: `freerouting/src/main/java/app/freerouting/autoroute/`
  - Expansion rooms/doors, search tree, ripup control, routing passes.
- **Optimizer / pull-tight / smoothing**: mostly under `interactive/` + `autoroute/` (route finalization utilities).
- **DRC**: `freerouting/src/main/java/app/freerouting/drc/`
- **Settings**: `freerouting/src/main/java/app/freerouting/settings/RouterSettings.java` (+ fanout/optimizer/scoring settings).
- **Tests**: `freerouting/src/test/java/app/freerouting/tests/` and design fixtures in `freerouting/tests/`.

### 1.2 Freerouting settings to match (minimum)
From `RouterSettings` and related settings:
- Routing passes, timeout, random seed determinism.
- Layer activation + per-layer preferred direction.
- Via enable/disable + via cost model.
- Automatic neckdown.
- Fanout enable + parameters.
- Optimizer enable + parameters.
- Scoring: trace direction costs, via costs, ripup costs, etc.

---

## 2) Target Rust Architecture (must-do refactor before parity work)

### 2.1 Split the single-file router into crates/modules
**Goal:** enable testability and incremental parity without modifying the Python integration surface.

TODO:
- [ ] Create a Rust workspace under `pardal-pcb/` (or `pardal_router/`) with:
  - `pardal_router_core` (routing engine, rules, geometry, DRC)
  - `pardal_router_formats` (KiCad-problem JSON, Specctra DSN/SES)
  - `pardal_router_cli` (current binary; thin wrapper)
- [ ] Move current implementation from `pardal-pcb/pardal_router_cli/src/main.rs` into:
  - `core::{grid_router, negotiate, legalize, stats}`
  - `formats::{problem_json}`
  - `cli::{args, logging, json_io}`

Acceptance criteria:
- `pcb_tool.cli rust-route` continues working unchanged.
- Existing `pytest` suite still passes (run `pardal-pcb` tests).

---

## 3) Parity Track A: File Formats & Interop (DSN/SES)

### 3.1 Specctra DSN reader (minimum viable)
TODO:
- [ ] Implement a Specctra DSN parser that supports the subset used by Freerouting tests:
  - Board outline
  - Layers + stackup
  - Components + pins (as obstacles/terminals)
  - Nets + terminals
  - Rules: widths, clearances, via definitions
  - Keepouts / restricted areas
- [ ] Convert DSN → internal board model (see section 4).

Tests (TDD):
- [ ] Add Rust tests that parse DSNs from `freerouting/tests/*.dsn` (start with `empty_board.dsn`, then `Issue026-J2_reference.dsn`).
- [ ] Snapshot/roundtrip tests: DSN → internal → DSN (semantic equality, not byte equality).

Acceptance criteria:
- Can parse at least 10 diverse DSN fixtures from `freerouting/tests/` without panics.

### 3.2 SES/session writer (minimum viable)
TODO:
- [ ] Write SES with routed traces/vias such that Freerouting can load the routed session on the original DSN.
- [ ] Preserve net naming and layer indices.

Tests:
- [ ] Golden test: DSN + SES produced by Rust loads in Freerouting (headless validation step; see section 9.3).

Acceptance criteria:
- At least 3 DSN fixtures can be routed by Rust and verified by Freerouting accepting the SES.

---

## 4) Parity Track B: Core Board Model (continuous geometry, not grid-first)

Freerouting fundamentally routes in continuous space with shape obstacles; the Rust backend must adopt the same model for parity.

### 4.1 Canonical coordinate system
Decision (fixed for this plan):
- Use **integer nanometers** (`i64 nm`) as canonical units across geometry, rules, and serialization.
- Convert KiCad mm inputs into nm at ingest, and convert back on export.

TODO:
- [ ] Implement `UnitNm(i64)` wrappers for safety or enforce via type aliases.
- [ ] Define rounding/quantization rules for conversions (always round outward for keepouts/clearance).

Acceptance criteria:
- Round-trip mm ↔ nm is deterministic; no “shrink” of obstacles after conversion.

### 4.2 Shapes & items
TODO:
- [ ] Implement shapes:
  - `Segment` (centerline + width)
  - `Arc` (optional, but required for parity on some boards)
  - `Circle` (vias/pads)
  - `Polygon` (zones/keepouts)
- [ ] Implement board “items”:
  - `Trace` (polyline segments; arcs allowed)
  - `Via` (type + drill + diameter + layers spanned)
  - `Pad`/terminal (geometry + allowed layers)
  - `Keepout` and `Obstacle` (geometry + layer mask + net ownership if applicable)

Tests:
- [ ] Unit tests for shape intersection and distance/clearance computation.
- [ ] Regression tests for known corner cases (touching, collinear overlap, arc-segment tangency).

Acceptance criteria:
- Internal DRC (section 8) can check all item types for clearance and shorts.

### 4.3 Spatial index / query engine
Decision:
- Use an R-tree-like index (custom or crate) with per-layer partitioning for speed.

TODO:
- [ ] Implement per-layer spatial index for obstacles + routed items.
- [ ] Support:
  - “find all items within radius”
  - “nearest clearance violation candidate”
  - fast collision checks for tentative route placement

Tests:
- [ ] Property tests: inserting/removing items doesn’t corrupt queries.

Acceptance criteria:
- Collision query time grows sublinearly with number of items on typical boards.

---

## 5) Parity Track C: Rules Engine (net classes, layers, vias, keepouts)

### 5.1 Net classes & clearance matrix
TODO:
- [ ] Implement a clearance matrix equivalent to Freerouting’s `ClearanceMatrix`:
  - class-to-class clearance
  - per-layer overrides (if present)
  - default fallback rules
- [ ] Implement per-netclass:
  - width
  - via diameter/drill
  - allowed via types
  - shove-fixed / pull-tight toggles

Tests:
- [ ] Port logic equivalents of `freerouting/src/test/.../ClearanceMatrixTest.java`.

Acceptance criteria:
- Rule evaluation matches Freerouting semantics for DSN fixtures that encode netclasses.

### 5.2 Via rules/types (through, blind, buried, microvia)
TODO:
- [ ] Represent via types with explicit layer spans:
  - through: (top..bottom)
  - blind/buried: (Lx..Ly)
  - microvia: (adjacent only)
- [ ] Implement rule checking for allowed span and cost model.
- [ ] Implement “plane via costs” (higher penalty when crossing plane layers or keepouts).

Tests:
- [ ] Unit tests for span legality and selection.

Acceptance criteria:
- Router can restrict vias to match DSN rules and still route on sample fixtures.

### 5.3 Keepouts, restricted areas, plane layers
TODO:
- [ ] Support keepout polygons per layer and “all layers” keepouts.
- [ ] Support power plane layers (routing forbidden except allowed via behaviors if configured).
- [ ] Support component courtyards as obstacles (KiCad) and DSN placement outlines.

Tests:
- [ ] DSN fixtures with restricted areas route without violating keepouts.

Acceptance criteria:
- No routed copper appears inside restricted areas in exports; DRC flags none.

---

## 6) Parity Track D: Routing Engine (autoroute + negotiation)

Freerouting is fundamentally a negotiation router with iterative ripup, costs, and optimization.

### 6.1 Single-net router (maze router) on continuous geometry
Decision:
- Implement maze routing on a **visibility graph / channel graph** backed by spatial index, not on a uniform grid.
- Use rectilinear and 45° segments; arcs only in post-processing (unless necessary for constraints).

TODO:
- [ ] Implement node generation:
  - terminals + via candidates
  - obstacle corners (expanded by clearance)
  - “escape points” around pads/vias (fanout seeds)
- [ ] Implement edge legality checks using clearance queries.
- [ ] Implement cost model:
  - length
  - via cost
  - direction cost vs preferred direction
  - obstacle proximity penalty (to encourage routability)
- [ ] Implement multi-terminal net routing using:
  - incremental Steiner-like growth: route terminal-to-tree repeatedly
  - or minimum spanning tree of terminals then route edges with merging

Tests (TDD):
- [ ] Small synthetic boards: route a few terminals with obstacles, assert no collisions.

Acceptance criteria:
- Produces legal routes (internal DRC clean) on synthetic tests.

### 6.2 Negotiation (ripup and reroute) framework
TODO:
- [ ] Implement pass-based routing comparable to Freerouting’s `AutorouteControl`:
  - choose unrouted nets
  - attempt route; if fails, rip up conflicting items based on cost thresholds
  - increment ripup costs per pass
- [ ] Conflict selection policy:
  - minimal set of obstacles that unblock the route
  - prefer ripping low-cost / short / low-priority nets
- [ ] Deterministic behavior with `random_seed`.

Tests:
- [ ] Port Freerouting issue tests that validate determinism (`RandomSeedTest` analog).

Acceptance criteria:
- Same seed produces identical output routes (modulo serialization ordering).

### 6.3 Push-and-shove (interactive-grade legality)
Freerouting supports pushing obstacles aside (for shove-enabled nets).

TODO:
- [ ] Implement shove routing for traces/vias:
  - Given a new segment placement, compute displaced segments (local reroute)
  - Maintain minimum clearance invariants during shove
  - Respect shove-fixed nets (cannot be moved)
- [ ] Add a bounded “local repair” solver:
  - expand region around conflict
  - attempt to re-route displaced items within the region

Tests:
- [ ] Synthetic shove tests: place segment through another, assert that shove moves the movable net and preserves DRC.

Acceptance criteria:
- Shove-enabled configurations route denser problems than ripup-only at same rule settings.

---

## 7) Parity Track E: Fanout / Escape Routing (BGA and dense parts)

### 7.1 Fanout engine
TODO:
- [ ] Implement fanout generation similar to Freerouting `RouterFanoutSettings`:
  - BGA via-in-pad to escape via
  - escape direction patterns (orthogonal + diagonal)
  - layer assignment for escape
  - spacing enforcement and via legality
- [ ] Provide “fanout-only” mode to seed vias/traces before global autoroute.

Tests:
- [ ] Add a BGA fixture in Rust tests (synthetic or reuse `pardal-pcb/bench/bga100`).
- [ ] Assert:
  - all pads receive an escape to allowed layer(s)
  - no DRC violations (internal) in the fanout stage

Acceptance criteria:
- Fanout stage never introduces shorts/clearance violations in isolation.

---

## 8) Parity Track F: Internal DRC (Freerouting-equivalent coverage)

### 8.1 DRC rules to implement
TODO:
- [ ] Clearance violations:
  - track↔track
  - track↔via
  - via↔via
  - copper↔pad
  - copper↔keepout/obstacle
- [ ] Shorting violations (different net copper overlap)
- [ ] Unconnected items detection (net connectivity graph)
- [ ] Annular ring + drill constraints (if rules specify)
- [ ] Hole clearance (via drill vs copper and NPTH)

Tests:
- [ ] Port conceptual equivalents of `freerouting/src/test/.../DesignRulesCheckerTest.java`.
- [ ] Integrate KiCad DRC as an external oracle for KiCad boards:
  - for selected fixtures, require `kicad-cli pcb drc --format json` to be clean.

Acceptance criteria:
- Internal DRC results are stable and correlate with KiCad DRC on exported KiCad boards.

---

## 9) Parity Track G: Optimizer (pull-tight, smoothing, via reduction)

### 9.1 Pull-tight algorithm
TODO:
- [ ] Implement pull-tight with a tunable accuracy parameter (Freerouting has `trace_pull_tight_accuracy`):
  - reduce unnecessary detours
  - maintain clearance constraints

Tests:
- [ ] Optimization should strictly reduce length/cost on known routed fixtures without introducing DRC violations.

Acceptance criteria:
- On a set of routed fixtures, pull-tight reduces total wirelength by ≥ X% (choose X per fixture baseline) while preserving DRC.

### 9.2 Corner smoothing / glossing
TODO:
- [ ] Implement corner smoothing:
  - replace right-angle corners with 45° or arcs where allowed
  - keep within clearance envelope

Tests:
- [ ] Verify that smoothing doesn’t change connectivity and passes DRC.

### 9.3 Item reduction (vias, segments)
TODO:
- [ ] Remove redundant vias (if same-layer path exists).
- [ ] Merge collinear segments.
- [ ] Optional: “via swapping” / layer reassignment improvements.

Acceptance criteria:
- Segment count decreases without increasing DRC or unrouted nets.

---

## 10) Validation Harness (Freerouting parity suite + KiCad DRC suite)

### 10.1 Freerouting parity suite (DSN-based)
TODO:
- [ ] Add a `pardal-pcb/bench/freerouting_parity/` harness:
  - Input: DSN from `freerouting/tests/`
  - Output: SES + metrics JSON
  - Baseline: route with Freerouting (headless) to capture completion + DRC stats (where available)
- [ ] Add “smoke” tier (fast) and “full” tier (slow).

Acceptance criteria:
- CI-style run completes the smoke tier in reasonable time (target ≤ 2 minutes).

### 10.2 KiCad parity suite (KiCad board based)
TODO:
- [ ] Maintain a curated set of `.kicad_pcb` fixtures:
  - the existing BGA fixtures
  - at least one non-BGA mixed-signal board
- [ ] For each fixture:
  - extract routing problem
  - route
  - apply to KiCad
  - run `kicad-cli pcb drc --format json`
  - record violations + unconnected

Acceptance criteria:
- For each fixture in the smoke set, output has:
  - `unconnected == 0`
  - `violations == 0` (or explicitly allowed violations list for the fixture with justification)

### 10.3 Headless Freerouting runner (for baseline comparisons)
Decision:
- Use the local `freerouting/` checkout and run `./gradlew test` and/or a headless route command.

TODO:
- [ ] Add a script to build/run Freerouting headless routing for DSN inputs and emit:
  - routed SES
  - runtime
  - completion metrics (if Freerouting exposes)

Acceptance criteria:
- Script works without manual GUI interaction.

---

## 11) Performance Plan (after correctness parity is established)

Parity is correctness-first. Performance work is staged after parity milestones to avoid invalid fast code.

### 11.1 Profiling + instrumentation
TODO:
- [ ] Add structured timing spans around:
  - obstacle query
  - edge legality checks
  - maze node expansion
  - shove local repair
  - DRC sweeps
- [ ] Add CPU profiles (e.g., `perf` / `pprof-rs`) behind feature flags.

Acceptance criteria:
- Bench harness emits per-stage timing in JSON.

### 11.2 Algorithmic accelerations
TODO:
- [ ] Replace O(N) clearance checks with spatial-index queries.
- [ ] Cache expanded obstacles per clearance class (avoid recompute).
- [ ] Multi-thread independent net routing passes when safe.
- [ ] Use incremental connectivity updates, not full recompute per change.

Acceptance criteria:
- “Smoke” parity suite runtime improves by ≥ 2× from baseline parity implementation.

---

## 12) Feature Parity Checklist (Freerouting → Rust) — Master Table

Use this table as the authoritative tracking list. A feature is “done” only when its tests + harness acceptance criteria are met.

| Feature | Freerouting Ref | Rust Target | Tests | Acceptance |
|---|---|---|---|---|
| DSN parse | `designforms/specctra` | `formats::dsn` | parse + roundtrip | parses ≥10 fixtures |
| SES write | `designforms/specctra` | `formats::ses` | load in FR | FR accepts output |
| Clearance matrix | `rules/ClearanceMatrix` | `rules::clearance` | port `ClearanceMatrixTest` | identical eval |
| Via types/spans | `rules` + board layers | `rules::via` | unit tests | obey spans |
| Preferred direction | `RouterSettings` | `cost::direction` | DSN fixture compare | cost bias works |
| Neckdown | `automatic_neckdown` | `route::neckdown` | synthetic pad tests | connect narrow pins |
| Fanout | `RouterFanoutSettings` | `fanout::*` | BGA fixture | fanout DRC clean |
| Negotiation router | `autoroute/*` | `negotiate::*` | determinism tests | stable + completes |
| Ripup policies | `AutorouteControl` | `ripup::*` | parity harness | improves completion |
| Push/shove | `interactive/*` | `shove::*` | shove unit tests | preserves DRC |
| Pull-tight | `trace_pull_tight_accuracy` | `opt::pull_tight` | optimize tests | reduces length |
| Smoothing | `smoothen_*` | `opt::smooth` | geometry tests | DRC preserved |
| Internal DRC | `drc/*` | `drc::*` | DRC unit tests | correlates w/ KiCad |
| Scoring | `core/scoring` | `score::*` | metric snapshot | stable metrics |

---

## 13) Implementation Order (hard order; do not reorder)

1. **Refactor** into crates/modules without behavior change (section 2).
2. Implement **units + geometry primitives** (sections 4.1–4.2) + spatial index (4.3).
3. Implement **rules engine** (section 5) + internal DRC skeleton (section 8).
4. Implement **DSN parser/writer** (section 3) sufficient to load Freerouting fixtures.
5. Implement **continuous-space single-net router** (6.1) + internal DRC gating for route placement.
6. Implement **negotiation ripup/reroute** (6.2) with determinism.
7. Implement **fanout** (7.1).
8. Implement **push-and-shove** (6.3).
9. Implement **optimizer** features (9.1–9.3).
10. Build **parity harnesses** (section 10) and lock in acceptance baselines.
11. Only then do **performance optimization** (section 11).

---

## 14) Current State (as of last known baseline)

- Rust router is currently **grid-based A\*** with optional diagonal moves and NCR-like reroute loops.
- It does not implement continuous geometry, DSN/SES, push/shove, pull-tight, smoothing, full netclass rules, or Freerouting-equivalent internal DRC.

This gap is why “Freerouting parity” is currently **not achieved**.
