# BGA-324 (0.1mm, strict) Performance Optimization Plan

Goal: make `pardal rust-route` route `pardal-pcb/bench/bga324/bga324_breakout2.kicad_pcb` at **0.1mm resolution** with:
- **0 unconnected items** (KiCad DRC)
- **0 KiCad DRC violations**
- **≤ 5 minutes wall time** on a modern workstation CPU
- deterministic output given a fixed seed

Non-goals:
- modifying KiCad
- relying on external routing libraries
- changing fixture rules (netclass widths/clearances/via sizes) to “cheat” DRC

This plan is written to be executable by a dev with no prior context.

## 0. Current Blocker (Why It Times Out)

At 0.1mm resolution, the grid is large and the strict router pathfinding becomes expensive primarily due to:
- A* exploring too many nodes (search-space explosion).
- Per-neighbor legality checks being too slow (especially spacing/clearance checks).
- Large per-route working sets (workspace arrays sized to the full grid).

The BGA-100 milestone showed the correctness path:
- conservative obstacle quantization (ceil radii)
- modeling pre-existing microvias as fixed resources

For BGA-324, the next gating factor is performance (not correctness).

## 1. Success Criteria and Metrics

### 1.1 Definition of “strict”

Strict run means:
- `ncr_allow_overlaps = false`
- `enforce_spacing = true`
- extractor uses conservative obstacle stamping (ceil radii)
- pre-existing vias are treated as fixed copper for spacing + occupancy

### 1.2 Performance metrics to track per run

Collect and persist to JSON (see §2):
- `elapsed_s_total`
- `elapsed_s_per_net` (min/median/p95/max)
- `astar_pops_total`, `astar_pushes_total`
- `nodes_relaxed_total` (successful relax operations)
- rejection counters:
  - `rej_base_blocked`
  - `rej_occ_other`
  - `rej_ko_track`
  - `rej_ko_via`
  - `rej_bounds`
  - `rej_forbidden`
- `peak_rss_mb` (optional if easy)
- `failed_nets` (must be 0)
- `kicad_drc_violations` (must be 0)

Acceptance gate (for each phase): do not proceed until metrics improve and BGA-100 remains 0-DRC.

## 2. Phase 0 — Make Performance Measurable (No Logic Changes)

### 2.1 Add stats instrumentation in Rust router

Files:
- `pardal-pcb/pardal_router_cli/src/main.rs`

Tasks:
1. Add a `Stats` struct with counters:
   - A* heap pops/pushes
   - relax attempts/successes
   - rejections by reason
2. Thread a mutable `&mut Stats` through:
   - `astar_3d_bounded` neighbor expansion
   - via transitions
3. Record timing:
   - total elapsed
   - per-net elapsed (start/end around `try_route_net`)
4. Emit to `routes.json` (top-level keys):
   - `stats_total`, `stats_by_net` (by `spec_idx`)

Validation:
- Unit test: stats JSON schema contains expected keys.
- Regression: BGA-100 output routes still routes 0-DRC.

### 2.2 Add a repeatable benchmark harness

Files:
- `pardal-pcb/bench/` (new script)

Tasks:
1. Add `bench/run_bga_bench.py`:
   - runs `pcb_tool.cli rust-route` with specified `--resolution`, `--cfg`, `--inflate`
   - runs `kicad-cli pcb drc --format json`
   - parses routes.json stats and DRC counts
   - appends a row into `bench/results.csv` (timestamped, deterministic)
2. Add a “golden” command for BGA-324 strict attempt:
   - `resolution=0.1`, strict config
   - run timeout 10 minutes (for local dev), but record time to first success.

Validation:
- BGA-100 benchmark completes and reports 0-DRC.

## 3. Phase 1 — Make Strict Checks O(1) (High Impact, Low Risk)

### 3.1 Remove per-step scan loops in strict mode

Today, strict mode uses `track_clear()` / `via_clear()` which scan offset neighborhoods and touch multiple arrays.
This makes each neighbor expansion expensive at 0.1mm.

Target behavior:
- In strict mode, treat `ko_track` + `ko_via` as the authoritative clearance constraint (they are already stamped from committed copper).
- Replace scan-based checks with O(1) checks:
  - **track step allowed** iff:
    - `base_allows(...)` AND
    - `occ_other_at_idx(...) == 0` AND
    - `ko_track_other_at_idx(...) == 0` AND
    - `ko_via_other_at_idx(...) == 0`
  - **via step allowed** iff (both involved layers at the via center):
    - `occ_other_at_idx == 0` AND
    - `ko_track_other_at_idx == 0` AND
    - `ko_via_other_at_idx == 0`

Files:
- `pardal-pcb/pardal_router_cli/src/main.rs`

Tasks:
1. Introduce a config toggle:
   - `strict_spacing_mode: "ko_only" | "scan"` (default `ko_only`)
2. Update A* expansion logic:
   - use `ko_only` checks in strict mode
   - keep `scan` mode behind the flag for debugging/verification
3. Add debug-time validation (optional, behind flag):
   - for a sample of steps, assert that `scan` would agree with `ko_only`

Validation gates:
- BGA-100 strict at 0.1mm remains **0 DRC violations**.
- BGA-324 strict attempt runtime decreases significantly (target: >3× faster) even if still incomplete.

### 3.2 Reduce work inside tight loops

Micro-optimizations (do after 3.1 lands so they’re measurable):
- Inline `idx3` computations where profitable (avoid repeated unidx/idx conversions in neighbors).
- Precompute:
  - `w*h` and per-layer base offset
  - neighbor delta indices for manhattan moves
- Avoid repeated bounds checks by hoisting conditions.
- Use `u32` counters and saturating adds only where necessary.

Validation:
- Rust unit tests/build.
- BGA-100 0-DRC preserved.

## 4. Phase 2 — Shrink A* Working Set (Memory + CPU)

### 4.1 Bound-local A* workspace

Current A* workspace (`g`, `parent`, `seen`) is allocated for `layers*width*height` (full board).
At 0.1mm, this is large and makes each route reset expensive (cache misses + memory bandwidth).

Target:
- Allocate workspace per-net for the *current bounds* only:
  - local index: `(layer, x, y) -> local_idx`
  - local arrays sized `layers * bw * bh`

Files:
- `pardal-pcb/pardal_router_cli/src/main.rs` (or extract into a module/crate if needed)

Tasks:
1. Add a `BoundedWorkspace`:
   - owns `g`, `parent`, `seen`, heap
   - carries `bounds` and local dimensions
2. Make `astar_3d_bounded` operate on `BoundedWorkspace`:
   - local idx mapping helpers
3. Add a threshold fallback:
   - if bounds are “too big” (e.g. >70% of full board), use global workspace to avoid repeated allocations

Validation gates:
- BGA-100 strict remains 0-DRC.
- BGA-324 strict attempt shows reduced RSS and better runtime.

### 4.2 Reduce path cost per net (search reduction, not just faster checks)

Add deterministic early exit improvements:
- Prefer exits that reduce Manhattan distance to goal (already present via heuristic; also constrain bounds).
- Use smaller margins first:
  - for BGA breakout, set `margin_init` small and grow adaptively.
- Add net ordering enhancements:
  - keep “deep pads first”
  - tie-break by goal angle (already present)

Validation:
- No regression on BGA-100.
- BGA-324 strict completes more nets before timeout.

## 5. Phase 3 — Coarse-to-Fine Corridor Routing (Search-Space Control)

This is the highest leverage for 0.1mm without rewriting the router to edge-based.

Idea:
1. Solve at **coarser resolution** (0.2mm) to obtain a topological path.
2. Convert coarse path into a **corridor mask** (inflate by N cells).
3. Solve at **0.1mm** restricted to that corridor.
4. If a net fails, expand corridor and retry (bounded number of retries).

### 5.1 Implementation approach

Files:
- Python orchestration:
  - `pardal-pcb/pcb_tool/api/rust_route_kicad_docker.py`
  - `pardal-pcb/pcb_tool/cli.py`
- Rust:
  - `pardal-pcb/pardal_router_cli/src/main.rs`

Tasks:
1. Add CLI mode `--hierarchical` (Python-level):
   - extract + route @0.2
   - extract + route @0.1 with corridor constraints
2. Corridor representation in problem JSON:
   - add optional `allowed_mask` per layer, expressed as rectangles or sparse runs
   - OR: add a list of allowed circles/segments and stamp into `base_occ` as “allowed region”
3. Enforce corridor in A* by:
   - rejecting moves outside the corridor mask (cheap check)
4. Retry policy:
   - corridor radius = 3 cells, then 6, then 12 (example)
   - if still fails, fall back to global (unmasked) routing for that net

Validation gates:
- BGA-100 0-DRC preserved (hierarchical mode should be optional initially).
- BGA-324 strict @0.1 completes (all nets) under target time or shows clear improvement.

## 6. Phase 4 — Dedicated BGA Escape (Domain-Specific, Big Win)

BGA breakout is dominated by the “escape” step. A general maze router wastes time repeatedly navigating within the dense via-in-pad field.

Target:
- deterministically route each ball to an “escape anchor” outside the BGA field using a constrained pattern router (not full A*).
- then route anchors to TPs using the general router in a less congested space.

Tasks:
1. Detect BGA bbox from starts (already computed):
   - define an inner forbidden region and a 1–2 cell “ring” as the escape target.
2. Implement escape strategies (in order):
   - “drop via and step out” patterns using manhattan steps
   - prioritize inner balls first
   - choose preferred escape direction based on goal TP quadrant
3. Only use A* for escape as a fallback if pattern fails.
4. Emit anchors as terminals and route in two stages:
   - stage A: start -> anchor (inside BGA region)
   - stage B: anchor -> goal (outside region)

Validation gates:
- BGA-100 unchanged.
- BGA-324 strict @0.1 runtime decreases materially (target: >2×) and completion improves.

## 7. Phase 5 — Priority Queue and Heuristic Upgrades (If Still Needed)

If phases 1–4 are insufficient, proceed with algorithmic upgrades.

### 7.1 Weighted A*

Trade optimality for speed:
- use `f = g + ε*h` with `ε ∈ [1.2, 2.0]` (configurable)

Validation:
- BGA-100 still 0-DRC (route quality changes are acceptable as long as legality holds).
- BGA-324 strict completes faster.

### 7.2 Jump Point Search (Manhattan)

Only for `diagonal=false`, uniform-ish costs:
- jump along straight runs until a “forced neighbor” appears or blocked.
- massively reduces node expansions on open boards.

Validation:
- same as above, plus deterministic output with seed.

### 7.3 Bidirectional A*

Use forward/backward frontiers meeting in the middle.
More complex with multi-layer + constraints, but can reduce expansions in long-distance nets.

## 8. Phase 6 — Performance Regression Tests

Add a “slow test” target that runs locally (not necessarily in CI):
- `pytest -m perf` runs BGA-100 strict @0.1 and asserts:
  - elapsed < X seconds
  - DRC == 0

Optional:
- a nightly perf job (if CI exists) that records trend lines.

## 9. Execution Checklist (No Decisions Required)

Run these steps in order and do not proceed until each gate passes.

1. Phase 0 instrumentation + bench harness
   - Gate: metrics are emitted and stable; BGA-100 remains 0-DRC.
2. Phase 1 O(1) strict spacing checks (`ko_only`)
   - Gate: BGA-100 0-DRC; BGA-324 strict run materially faster.
3. Phase 2 bounded workspace
   - Gate: BGA-324 strict run materially faster and uses less memory.
4. Phase 3 hierarchical corridor routing
   - Gate: BGA-324 strict reaches completion with far fewer expansions.
5. Phase 4 dedicated BGA escape anchors
   - Gate: BGA-324 strict completes within target time.
6. Phase 5 heuristic upgrades (weighted A*, then JPS)
   - Gate: only if phases 1–4 still miss time budget.
7. Phase 6 perf regression harness
   - Gate: prevent regressions going forward.

## 10. Risks / Failure Modes

- **Corridor too tight**: fine route fails even though global route exists.
  - Mitigation: bounded retries with expanding corridor; global fallback per-net.
- **`ko_only` correctness gap**: keepout stamping incomplete leads to missed spacing rules.
  - Mitigation: keep `scan` mode for verification; validate via KiCad DRC on BGA-100/BGA-324.
- **Memory blow-up**: bounded workspace still too large for far-away nets.
  - Mitigation: dynamic bounds strategy + hierarchical mode.
- **BGA-324 strict may be impossible with current rules** (width/clearance vs pitch).
  - Mitigation: treat “prove impossible” as acceptable only if validated via an external router; otherwise assume it should be routable and keep optimizing.

