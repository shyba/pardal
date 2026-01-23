# Rust Router Feature Parity Plan (vs FreeRouting)

This is an exhaustive implementation plan to reach *batch autorouting* feature parity with the FreeRouting KiCad plugin workflow (DSN/SES), **without modifying KiCad**.

Scope: headless “route a placed `.kicad_pcb` and write a routed `.kicad_pcb`” runs suitable for automation pipelines.

## 0. Definitions

- **Parity (for this plan)**: For a given PCB fixture, the Rust router can:
  - Route to **0 unconnected items** (KiCad DRC), or prove impossible under rules.
  - Achieve **0 KiCad DRC errors/warnings** (or a configurable “allowed set” for early milestones).
  - Support the same classes of constraints that FreeRouting can consume from DSN: widths, clearances, net classes, via types, layer counts, keepouts, board outline.
  - Provide ripup/reroute + post-processing (tightening/cleanup) at similar quality, with a deterministic seedable run.

- **Non-goals (explicit)**:
  - Interactive routing / shove routing UI.
  - Manual editing convenience features.
  - Full Specctra DSN/SES fidelity for every obscure construct; we only need parity for KiCad-exported DSNs and pcbnew-extracted geometry.

## 1. Current Baseline (Rust backend prototype)

Already present (as of this repo state):
- KiCad 9 docker integration: extract → route (Rust) → apply → `kicad-cli pcb drc`.
- Grid-based A* + multi-net routing via PathFinder-like negotiated congestion.
- Per-cell net ownership (best-effort) and keepout-stamped clearance fields (track/via).
- Extractor support for fixed “pre-existing vias” (e.g. microvias-in-pad) so they participate in spacing/occupancy checks.
- Bench fixture generator for BGA breakouts: `pardal-pcb/bench/generate_bga_breakout.py`.
- Benchmark report: `pardal-pcb/bench/compare_freeroute_vs_rust.md`.

Known limitations:
- Geometry model is still **cell-based points**, not edge-based segments; this causes many `tracks_crossing`, `shorting_items`, and clearance mismatches vs KiCad’s real geometry DRC.
- Obstacles are approximated (mostly circles) and don’t fully represent pads/holes/zones/edges.
- Via type handling is simplistic (microvia vs through via needs rule-based choice).

Recent milestone:
- BGA-100 breakout reaches **0 unconnected** and **0 KiCad DRC violations** using strict spacing at 0.1mm resolution (see `pardal-pcb/bench/compare_freeroute_vs_rust.md`).

Performance plan:
- BGA-324 strict @0.1mm is currently time-bounded; see `pardal-pcb/docs/BGA324_PERF_OPTIMIZATION_PLAN.md`.

## 2. Parity Gap Map (Feature Inventory)

The table below maps major FreeRouting capabilities to Rust implementation tasks.

| FreeRouting capability (batch) | What it means | Rust status | Work needed |
|---|---|---:|---|
| DSN import of full board geometry | pads, tracks, vias, keepouts, outline, zones | partial (pcbnew extractor) | richer pcbnew extraction; optional DSN parser for cross-check |
| Net classes / rules | widths, clearance, via sizes, layer constraints | partial | full rule graph + per-net overrides |
| Multiple via types | microvia, blind/buried, through; legal layer spans | partial | via-type catalog + legal transitions + costs |
| Fanout / escape routing | BGA escape patterns before global route | rudimentary | dedicated escape router (BGA-aware) |
| Global routing / planning | decide corridors + layer assignments | none | global router phase (coarse grid / channel routing) |
| Detailed maze routing | connect pins while respecting obstacles/rules | partial | edge-based router with clearance-aware expansions |
| Ripup & reroute | resolve conflicts iteratively | partial | capacity model on edges + conflict-driven ripups |
| Cost model | via costs, layer penalties, congestion costs | partial | full cost tuning + rule-dependent penalties |
| Optimizer / “pull tight” | shorten/straighten while preserving legality | minimal | post-route optimization suite |
| Cleanup | remove dangling, merge collinear, minimize vias | partial | deterministic cleanup passes |
| Determinism controls | random seed + stable ordering | partial | deterministic RNG + stable tie-breakers everywhere |
| Reporting | stats, progress, reasons for failure | partial | structured JSON report + per-net failure causes |

## 3. Architecture Target (to enable parity)

To hit parity, the Rust router must move from “point occupancy” to a routing model that matches KiCad’s DRC semantics.

### 3.1 Core data model (authoritative)

- **Board geometry** (continuous):
  - Board outline polygon(s)
  - Copper layer stack (names + ids + count)
  - Obstacles:
    - Pads (shape: circle/oval/rect/roundrect; rotation)
    - Holes (NPTH/PTH) and drills
    - Existing tracks/vias
    - Keepout zones (copper/track/via restrictions)
    - Copper zones (optional, if we decide to route with planes present)
- **Rules**:
  - Clearance matrix (netclass-to-netclass, and special cases)
  - Track width per netclass
  - Via catalogs:
    - type, drill/diameter, annulus, allowed layer spans
  - Layer preferences (per layer direction, penalties)
  - Diff-pair constraints (optional parity tier; see §9)

### 3.2 Routing representation (grid, but edge-based)

- Choose a routing resolution (e.g. 0.1–0.25mm) per region (adaptive later).
- Represent resources as **edges**, not cells:
  - Horizontal edges: `(layer, x, y, dir=E)`
  - Vertical edges: `(layer, x, y, dir=N)`
  - Via nodes: `(x, y, via-type, span)`
- Obstacles/keepouts are stamped into blocked edges/nodes, not just points.
- Clearance is enforced by stamping “inflated” blocked regions per resource type, using net ownership to ignore same-net.

This directly targets the DRC-heavy violations seen today:
- `tracks_crossing` → prevented structurally (no crossing edges at same coordinates).
- Many `shorting_items`/`clearance` → reduced by proper clearance stamping vs real shapes.

## 4. Implementation Phases (TDD-first)

Each phase has *acceptance criteria* and *tests*. Do not advance phases without the tests.

### Phase 1 — Extraction correctness (pcbnew → routing problem)

Deliverables:
- A new extractor mode that exports:
  - exact pad shapes (not only circles), including layer set, rotation, and soldermask/paste info (for later)
  - board outline polygon
  - keepout areas (from KiCad keepout zones + drawings)
  - holes (drill, NPTH vs PTH)
  - layer stack + rules (netclass widths/clearances/via sizes)
  - allowed via types (including microvia/blind/buried spans)

Tests:
- Golden JSON schema tests (stable keys + types).
- Round-trip “extracted endpoints count == KiCad pads of interest”.
- For benchmark fixtures, extractor must be deterministic and include all copper obstacles.

Acceptance:
- For a known fixture, the extractor can explain every KiCad DRC obstacle it later flags.

### Phase 2 — Edge-based routing core (single-net)

Deliverables:
- Edge graph indexing (fast neighbor expansion).
- Edge occupancy + ownership (per-net).
- Clearance stamping from obstacles into blocked edges (static) and from routes into keepout edges (dynamic).
- Single-net A* that produces:
  - list of edges + vias
  - then converts to KiCad segments/vias without self-intersections

Tests:
- Unit tests: edge neighbors, via transitions, occupancy/rollback correctness.
- “Impossible” cases: blocked corridor yields no route.
- Small deterministic fixtures (generated) where the optimal path is known.

Acceptance:
- KiCad DRC on single-net fixtures shows 0 clearance/short/crossing violations for that net.

### Phase 3 — Multi-net negotiated routing (PathFinder on edges)

Deliverables:
- Capacities on edges (usually 1; may be >1 for “channels” later).
- Present cost + history cost per edge, updated per iteration.
- Ripup/reroute policy:
  - full reroute sweep per iteration (classic PathFinder)
  - or conflict-driven ripup set (faster)
- Deterministic ordering policy (stable, seedable tie-breaks).

Tests:
- “Two nets share corridor” fixture: converges to 2 disjoint routes.
- Regression tests: same seed → identical output routes.json.

Acceptance:
- For BGA-100 breakout: 0 unconnected items, and DRC violations reduced to “known missing features only” (target: zero `tracks_crossing`, zero `shorting_items`).

### Phase 4 — Escape / fanout routing (BGA-aware)

Deliverables:
- Fanout strategies:
  - 1-via escape to inner layers for dense BGAs
  - ring-based breakout (inner balls route first)
  - preferred direction assignment per row/column
- Constraint-driven fanout:
  - honor via span legality and keepout
  - avoid via drill co-location rules (KiCad `holes_co_located`)
- Produce “escape anchors” that become terminals for the global/detailed router.

Tests:
- BGA escape microvia field fixtures:
  - minimum clearances satisfied
  - no via stacking unless explicitly allowed

Acceptance:
- For BGA-324 breakout: escape completes for all pins with no DRC errors inside the BGA field.

### Phase 5 — Global routing / planning (coarse)

Deliverables:
- Coarse planner to reduce search explosion on big boards:
  - route region decomposition (channels between obstacles)
  - layer assignment hints (e.g., outer layers near pads, inner layers for trunks)
  - congestion forecasts (heatmaps)
- Output constraints for the detailed router (preferred corridors).

Tests:
- Global routes are consistent: every net has at least one corridor plan unless impossible.

Acceptance:
- For BGA-676 breakout: router reaches full completion under time budget (target ≤ 5 minutes on a modern workstation) with a fixed seed.

### Phase 6 — Post-processing / optimization (parity tier)

Deliverables:
- Pull-tight / smoothing:
  - replace stair-steps with longer Manhattan runs (or 45° where allowed)
  - reduce length while respecting clearance
- Via minimization:
  - remove redundant vias
  - merge segments
- Cleanup:
  - delete dangling stubs
  - enforce min segment length if needed

Tests:
- “Optimize preserves connectivity and legality” checks.
- KiCad DRC remains clean after each pass.

Acceptance:
- Quality metrics (total length, via count) approach FreeRouting results for the same fixture class.

### Phase 7 — Design-rule parity and advanced constraints

Deliverables:
- Differential pairs:
  - recognize diff pairs from KiCad netclass rules (not just name heuristics)
  - gap constraints, length matching (optional), phase alignment
- Net priorities / classes:
  - explicit priority ordering and cost weighting
- Copper zones:
  - route with zones present or strip/rebuild workflow parity

Tests:
- Targeted diff-pair fixtures with known acceptable DRC outcomes.

Acceptance:
- “Real board” fixtures (non-synthetic) route to 0 DRC under production rules for supported constraint subsets.

## 5. Kernel / Primitive Decomposition (for performance parity)

This is how to structure the Rust implementation so hotspots are swappable (SIMD / GPU later).

| Primitive | Inputs | Outputs | Used by | Notes |
|---|---|---|---|---|
| `rasterize_obstacles()` | pad/hole/keepout geometry | static blocked edges/nodes | all | should support batching + SIMD |
| `stamp_route_keepout()` | route edges/nodes | dynamic keepout arrays | NCR | must be incremental + rollback |
| `neighbors(node)` | node id | neighbor ids + base costs | A* | tight inner loop |
| `edge_cost(edge)` | edge id + rule context | scalar cost | A* | includes congestion/history |
| `via_transition_cost()` | from-layer/to-layer/via-type | scalar cost | A* | encodes via catalogs |
| `detect_conflicts()` | route set | conflict list | NCR | enables conflict-driven ripups |
| `ripup(routes)` | subset | uncommit deltas | NCR | incremental |
| `pull_tight(route)` | route geometry | simplified geometry | post | must be DRC-safe |
| `merge_collinear()` | route geometry | reduced segments | post | deterministic |

## 6. Acceptance Gates (what “parity” means in CI)

Introduce progressive CI gates; do not aim for “all at once”.

Gate A (core correctness):
- No panics, deterministic output for fixed seed.
- 0 `tracks_crossing` and 0 `shorting_items` on BGA-100 breakout.

Gate B (scaling):
- BGA-324 completes to 0 unconnected within ≤ 5 minutes.
- DRC violations limited to a documented, shrinking allowlist.

Gate C (parity-ish):
- BGA-676 completes to 0 unconnected within ≤ 5 minutes.
- 0 KiCad DRC errors/warnings on synthetic breakouts under the chosen rule set.

Gate D (production):
- At least one real “placed board” fixture routes to 0 DRC under production settings.

## 7. What to Compare Against FreeRouting (metrics)

Per run, record:
- Completion: failed nets, KiCad unconnected count
- DRC: violations by type
- Topology: vias count (by type), layer usage, total track length
- Runtime: wall time + iterations until convergence
- Stability: seed-to-seed variance (should be low or controllable)

Use `pardal-pcb/bench/compare_freeroute_vs_rust.md` as the living scoreboard.

## 8. Implementation Order (no decisions mid-flight)

1. Extraction: exact pad shapes + outline + keepouts + holes + rules.
2. Edge-based graph + single-net router + KiCad DRC validation.
3. Multi-net PathFinder on edges (capacity=1).
4. BGA escape router that emits inner-layer terminals.
5. Global planner for large boards (coarse grid).
6. Post-processing (pull-tight + cleanup).
7. Advanced rules (diff pairs, priorities, zones).
8. Performance engineering (SIMD kernels, parallel routing where safe).

## 9. Notes on Diff Pairs (avoid false positives)

KiCad can infer diff pairs from naming (`*_P`/`*_N`) and/or explicit diff-pair rules.
Parity requires:
- Extract explicit diff-pair constraints from the board/netclass rules if present.
- Avoid name-based inference in the router; follow KiCad’s explicit rules so we don’t “route into” a diff-pair DRC trap.

## 10. Work Items (checklist)

- [ ] Extract pad shapes (rect/oval/roundrect) + rotation
- [ ] Extract keepout zones + drawings affecting copper
- [ ] Extract board outline polygon
- [ ] Extract holes (NPTH/PTH) + hole clearances
- [ ] Define via catalog + legal spans + costs
- [ ] Implement edge graph indexing + neighbor generation
- [ ] Implement static obstacle rasterization to edges
- [ ] Implement dynamic keepout stamping (incremental + rollback)
- [ ] Implement single-net DRC-safe router (edge-based)
- [ ] Implement multi-net PathFinder (edge-based)
- [ ] Implement BGA escape router (patterns)
- [ ] Implement coarse planner (optional, for scaling)
- [ ] Implement post-route cleanup + pull-tight
- [ ] Implement DRC-driven repair loop (optional but high leverage)
- [ ] Add benchmark scripts + CI gate targets
