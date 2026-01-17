# BGA Stress Routing Improvement Plan (Rust grid router)

This plan is based on current `ring_escape_multi` benchmark results:

- Best known config routes `53/600` with `0` FreeRouting DRC clearance violations in ~`115s`:
  - `PARDAL_ROUTE_ORDER=angle`
  - `PARDAL_BRUSH_SHAPE=euclidean`
  - `PARDAL_DYNAMIC_COST_REBUILD_EVERY=16`
  - Report: `build/bga_bench_report.bga_ring_escape_multi_p2_angle_dyn16_euc_heapreuse_600_v2.md`
- “basic” negotiation currently isn’t productive on the 600-pin stress case under 180s (times out or routes only a handful when tightly bounded).

The gap is *routing completeness/strategy*, not raw runtime.

---

## 0) Targets (measurable)

### Primary stress target (synthetic, 600 pins)
- **Completion**: `>= 400/600` routed (minimum), `>= 520/600` (stretch)
- **DRC**: `FR DRC clear == 0` (must hold)
- **Runtime**: `<= 300s` (5 minutes) on a single high-end CPU core class; scale-out later

### Secondary targets (real boards / future)
- Can route BGA escape/fanout robustly on 4 layers (FPGA-class densities) without manual edits.
- Emits DSN/SES that FreeRouting can load without “unconnected items” false negatives.

---

## 1) Measurement + baselines (no algorithm changes)

### 1.1 Standardize a “known good” benchmark invocation
**Definition**
- Use `tools/run_bga_bench.py` with `ring_escape_multi`, fixed geometry, and 180s timeout as the default smoke-stress.

**Action**
- Maintain a single “golden command” in this file and in `FREEROUTING_PARITY_TODO.md`.

**Acceptance**
- One command reproduces the same routed count (+/- 1) and time within ~10% on the same machine.

### 1.2 Add a tuning sweep runner (small, focused)
**Why**
- Hand-tuning env vars doesn’t scale; we need systematic exploration.

**Action**
- Use `tools/run_bga_sweep.py` to run a *small* grid of configs and emit a CSV + “top configs” markdown:
  - `order`: `angle|median`
  - `brush_shape`: `euclidean|chebyshev`
  - `dyn_rebuild_every`: `0|8|16|32`
  - `via_cost`: `1|2|4`
  - `pitch`: `4|6|8`
  - Keep timeouts low and pins to `100,200` for sweeps.

**Acceptance**
- Produces a sortable table of `(routed, drc_clear, time)` and identifies top candidates automatically.

---

## 2) Fix the core strategy gap: BGA escape/fanout phase

The current sequential router starts inside a dense pin field and immediately competes for the same narrow corridors, so early routes “poison” the grid.

### 2.1 Implement escape-point generation per pad
**Idea**
- Don’t route from pad center on the grid.
- Generate candidate “escape points” on the pad boundary / just outside the pad dilation, on the allowed routing layers.

**Work items**
- Extract pad outline/radius in grid cells (from DSN padstack shapes already parsed).
- For each pin terminal:
  - Generate candidates on a ring at `r = pad_r + clearance + track_half_width + margin`.
  - Filter by reachability (`occ==0`, `pad_owner` ok, `via_forbidden` ok).
- Keep candidates per layer (for 4-layer, you’ll want inner-layer candidates too).

**Acceptance tests**
- Unit: a single pad in a blocked field yields candidates only in free space.
- Integration: small synthetic BGA (e.g. 8x8) yields non-zero candidates for most pins.

### 2.2 Add an “escape routing” micro-router
**Idea**
- For each pin, route a very short segment from pad center to the chosen escape point (often 5–20 cells), committing immediately.

**Work items**
- Route short pin→escape using current A* (but with a small expansion cap).
- Add a “no-via” option for top-layer-only escape, and an optional “via early” mode (via-in-pad or via-near-pad) for 4-layer boards.
- Commit with *via-aware stamping* (see 3.x) to avoid massive overblocking.

**Acceptance tests**
- A 2-pin corridor case where only “via early” can escape should succeed.
- Determinism: same seed yields same escape point selection and same committed shapes.

### 2.3 Assign escapes globally (avoid collisions)
**Problem**
- Greedy choice can assign two pins the same choke point, reducing completion.

**Work items**
- Implement assignment as a min-cost matching on a small candidate set:
  - cost = distance + congestion + layer penalty
  - constraints = unique escape sites within a via-spacing radius
  - start with greedy + repair; upgrade to Hungarian/min-cost-flow only if needed

**Acceptance**
- On a synthetic “dense ring” BGA, escape collisions drop vs greedy baseline and routed count increases.

---

## 3) Make occupancy/stamping match physical geometry (unblocks routing)

Right now, the router “brush” approximates both track and via geometry, and vias are treated as through-holes occupying all layers with the same brush. That is conservative (good for DRC) but blocks too aggressively (bad for completion).

### 3.1 Separate track stamp vs via stamp radii
**Work items**
- Compute two radii per net (grid cells):
  - `track_r = f(width, clearance)`
  - `via_r = f(via_diam, clearance)` (from DSN padstack `via0` if present)
- Update commit kernels so:
  - path points stamp with `track_r` on the point’s layer
  - layer transitions stamp via cores with `via_r` across the via’s spanned layers

**Acceptance**
- FreeRouting DRC clearance violations remain `0` on the current best-known routed set (53/600).
- Routed count improves on 100/200-pin stress subsets with the same DRC constraints.

### 3.2 Enforce same-net via spacing properly (not heuristic reject)
**Work items**
- Track via sites committed per net (spatial hash / bitset).
- Reject or penalize paths that add a via too close to an existing same-net via (and optionally too close to foreign vias).
- Integrate this into the search cost (soft constraint) rather than only post-checking.

**Acceptance**
- Eliminates the need for coarse “drop route if violates” behavior while keeping DRC clear `0`.

---

## 4) Multi-pass completion loop (without full FreeRouting parity)

Sequential one-pass routing is expected to cap out early on dense problems. We need a bounded, deterministic completion loop.

### 4.1 Add a “batch passes” driver for Rust(off)
**Idea**
- Repeat `K` passes:
  - Route remaining unrouted nets with updated congestion/history costs
  - Optionally rip up a small set of “blocking” routes near the current unrouted net

**Work items**
- Add a pass loop with:
  - time budget
  - stagnation detector (no improvement in `N` attempts)
  - a bounded ripup policy (see 4.2)

**Acceptance**
- On 100/200-pin stress subsets, routed count strictly increases vs single-pass for the same DRC constraints.

### 4.2 Replace “soft-cross then ripup all conflicts” with local ripup selection
**Problem**
- Current “basic” negotiation either thrashes or does almost nothing under tight iteration budgets.

**Work items**
- For a failing net, identify a small “conflict region” around the attempted path or around the endpoints:
  - collect foreign net IDs within `R` cells of that region (already partially implemented in `collect_ripup_net_ids_for_path`)
  - select up to `M` nets to rip up using a score:
    - low “value” (short, few vias, recently added)
    - high “blocking” (overlaps region heavily)
- Re-route ripped nets later in the queue (don’t immediately retry them).

**Acceptance**
- `rust_basic` no longer spends 180s routing only ~5 nets on 600-pin stress.
- On 300-pin stress, `rust_basic` produces *more routed nets than rust_off* within the same time budget while keeping `DRC clear == 0`.

---

## 5) Performance work (only after completion improves)

Once completion logic is better, performance becomes critical for the 5-minute goal.

### 5.1 Reduce per-route work in A*
- Already done: reuse `BinaryHeap` in `Dial3dScratch`.
- Next:
  - add an expansion cap for “escape routing” micro-routes
  - add per-route early-exit if heuristic lower bound exceeds best-known (when routing multiple targets)

### 5.2 Jump Point Search (JPS) for uniform-cost segments
**Idea**
- Most expansions are along straight corridors; JPS reduces node expansions dramatically on grids.

**Acceptance**
- For open-grid routes at 600-pin sizes, reduces explored nodes and wall time without changing route legality.

---

## 6) Validation + gates (TDD)

### 6.1 New unit tests (fast)
- Escape candidate generation invariants.
- Track/via stamping correctness on a tiny board (2–3 layers).
- Ripup selection determinism (same seed, same candidate nets).

### 6.2 New integration tests (still fast)
- Small synthetic BGA escape (e.g. 64 pins) routed >= X% within a small timeout.
- FreeRouting DRC oracle on that output with `clearance_violations_total == 0`.

### 6.3 Stress bench gates (manual / nightly)
- 600-pin `ring_escape_multi`:
  - track `(routed, drc_clear, time)`
  - regressions fail the gate

---

## 7) Prioritized implementation order (no ambiguity)

1) 2.1 escape-point generation (tests + tool output)
2) 3.1 separate track/via stamp radii (tests + DRC check)
3) 2.2 escape routing micro-router (tests + small BGA bench)
4) 2.3 global assignment (greedy+repair first)
5) 4.1 batch passes for rust_off (no ripup initially)
6) 4.2 local ripup selection (turn rust_basic into something useful)
7) 5.x JPS / further perf once routed fraction is high

---

## 8) New findings (Dec 2025) — what’s still missing

### 8.1 Pad clearance was being double-counted by the brush model
- Pins are stamped into `pad_owner` with `inflate_world = default_clearance_world` in `pardal_route_dsn` (pad copper + clearance halo).
- The routing brush also included clearance (`width/2 + clearance`), so pad-vs-wire spacing effectively enforced `2*clearance + width/2`.
- Fix implemented: clip the **wire** brush halo against foreign pads (keep the core point strict).
  - Code: `pardal-pcb/pardal_router_core/src/kernels.rs` (`k9_commit_path_occ_3d_brush` and `k9_try_commit_path_occ_3d_brush`).
  - Verified by unit tests: `pardal-pcb/pardal_router_core/tests/kernels_tests.rs`.

**Impact @ pitch=6**
- `ring_escape_multi` 600 pins:
  - `54/600` routed, `0` FreeRouting DRC clearance violations (up from `53/600`).
  - Still far from complete: this confirms the next bottleneck is multi-net strategy (fanout/negotiation), not just commit strictness.

### 8.2 Via↔pin clearance needs a net-aware model (grid pitch limitations)
- If we also clip the via halo against pads, routed count increased (e.g. `~62/600` at pitch=6),
  but FreeRouting DRC reported **via↔pin clearance violations** (dozens-scale).
- Keeping vias strict vs pads preserves `DRC clear == 0` but reduces completion.

This indicates we need at least one of:
- A finer or adaptive grid near dense padfields (so `pad_radius + clearance + via_radius` is representable), or
- A continuous-space clearance check for candidate vias during routing (net-aware and padstack-aware), instead of relying only on cell dilation.

### 8.3 Resolution/brush tradeoff is real (pitch=4 experiments)
- With `pitch=4` and `brush=auto` (radius becomes larger in cells), routing got **more conservative** and completion dropped (`~36/600`, `DRC clear == 0`).
- With `pitch=4` and `brush=1`, completion improved (`~69/600`) but `DRC clear` regressed (tens of violations).

**Conclusion**
- “More resolution” only helps if we simultaneously improve the clearance representation beyond a single integer brush radius (separate wire/via radii; or geometry-based clearance checks).
