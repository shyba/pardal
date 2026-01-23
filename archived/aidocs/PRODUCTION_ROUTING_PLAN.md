# Production-Grade Autorouter Plan

## Current State

The autorouter is functional but produces boards with DRC errors:
- 4 net shorts (traces crossing pads)
- 5 clearance violations (0.197mm vs 0.2mm)
- 12 unconnected items (incomplete routing)
- 5 solder mask bridges

## Gap Analysis

### 1. **Pad Obstacle Marking** (Critical - causes shorts)

**Problem:** Routes pass through pads of other nets, creating shorts.

**Current code** (`routing.py:882-892`):
```python
# Only marks 3x3 area around component CENTER
for dx in [-1, 0, 1]:
    for dy in [-1, 0, 1]:
        grid.mark_obstacle(gx, gy, "F.Cu")  # BUG: passes grid coords as mm
```

**Fix needed:**
- Mark each pad as obstacle with proper clearance
- Use actual pad positions (component.get_pad_position)
- Apply pad size + clearance radius
- Exclude pads belonging to the net being routed

**Files:** `pcb_tool/commands/routing.py`

---

### 2. **Grid Resolution vs Clearance** (Critical - causes DRC violations)

**Problem:** 0.2mm grid can't maintain 0.2mm clearance (diagonal moves = 0.283mm step).

**Current code** (`routing.py:874-879`):
```python
grid = RoutingGrid(
    resolution_mm=0.2,
    default_clearance_mm=0.2,  # Same as resolution!
)
```

**Fix needed:**
- Reduce resolution to 0.1mm (finer grid)
- Or increase trace clearance to 0.25mm
- Consider adaptive resolution near obstacles

**Files:** `pcb_tool/commands/routing.py`, `pcb_tool/routing/grid.py`

---

### 3. **Coordinate Type Bug** (Critical - obstacles not marked)

**Problem:** `mark_obstacle()` expects mm coords but receives grid coords.

**Current code** (`routing.py:891`):
```python
grid.mark_obstacle(gx, gy, "F.Cu")  # gx,gy are grid coords!
```

**Fix needed:**
```python
# Option A: Convert back to mm
x_mm, y_mm = grid.to_mm_coords(gx, gy)
grid.mark_obstacle(x_mm, y_mm, "F.Cu")

# Option B: Add mark_obstacle_grid() method
grid.mark_obstacle_grid(gx, gy, "F.Cu")
```

**Files:** `pcb_tool/commands/routing.py`

---

### 4. **MST Edge Verification** (Critical - causes incomplete routing)

**Problem:** MST creates edges, but if an edge fails to route, the net is incomplete.

**Current behavior:**
- Creates MST with N-1 edges for N pads
- Routes each edge independently
- If edge fails, that connection is lost

**Fix needed:**
- Track which edges successfully routed
- Retry failed edges with alternative paths
- Use fallback: direct routing to nearest connected pad
- Report truly unroutable connections

**Files:** `pcb_tool/commands/routing.py`, `pcb_tool/routing/multi_net_router.py`

---

### 5. **Zone Filling** (Important - GND appears unconnected)

**Problem:** pcbnew `ZONE_FILLER.Fill()` segfaults, so zones are saved unfilled.

**Current workaround:**
```python
# Zone filling disabled due to crash
# Zones saved unfilled - KiCad will refill on open
```

**Options:**
1. Use `kicad-cli pcb drc --fill-zones` post-processing
2. Investigate pcbnew crash (memory/threading issue?)
3. Accept unfilled zones (KiCad auto-fills on open)
4. Generate filled_polygon manually (complex)

**Files:** `pcb_tool/finalize.py`

---

### 6. **Trace Segment Collision Detection** (Important)

**Problem:** `mark_trace_segment` only marks endpoints, not full trace path.

**Current code** (`routing.py:900-901`):
```python
grid.mark_obstacle(start_gx, start_gy, segment.layer)
grid.mark_obstacle(end_gx, end_gy, segment.layer)  # Only endpoints!
```

**Fix needed:**
- Use `grid.mark_trace_segment()` properly (it exists!)
- Or use Bresenham line to mark all cells along trace

**Files:** `pcb_tool/commands/routing.py`

---

### 7. **THT Pad Multi-Layer Blocking** (Important)

**Problem:** Through-hole pads should block ALL layers, not just F.Cu/B.Cu.

**Current:** Only marks component center on outer layers.

**Fix needed:**
- Detect THT pads (pad.drill is not None)
- Mark THT pads as obstacles on all copper layers
- SMD pads only block their layer

**Files:** `pcb_tool/commands/routing.py`

---

### 8. **Clearance-Aware Routing** (Enhancement)

**Problem:** Pathfinder doesn't consider trace width when checking clearance.

**Current:** Checks single grid cell validity.

**Fix needed:**
- Expand obstacle check by trace_width/2 + clearance
- Or pre-inflate obstacles by this amount

**Files:** `pcb_tool/routing/pathfinder.py`, `pcb_tool/routing/grid.py`

---

## Implementation Priority

### Phase 1: Critical Fixes (Eliminates DRC Errors)
1. [ ] Fix coordinate type bug in obstacle marking
2. [ ] Add pad obstacle marking with clearance
3. [ ] Reduce grid resolution to 0.1mm
4. [ ] Fix trace segment marking (use full line, not endpoints)

### Phase 2: Completeness (All Nets Fully Routed)
5. [ ] Add MST edge verification and retry logic
6. [ ] Handle THT pads blocking all layers
7. [ ] Track routing success per net edge

### Phase 3: Robustness (Production Quality)
8. [ ] Add clearance-aware routing (trace width consideration)
9. [ ] Implement rip-up and reroute for failed nets
10. [ ] Add DRC pre-check before saving

### Phase 4: Polish
11. [ ] Zone filling workaround (kicad-cli post-process)
12. [ ] Routing progress reporting
13. [ ] Estimated completion time

---

## Estimated Effort

| Phase | Tasks | Complexity | Est. Time |
|-------|-------|------------|-----------|
| Phase 1 | 4 | Medium | 2-3 hours |
| Phase 2 | 3 | Medium | 2 hours |
| Phase 3 | 3 | High | 3-4 hours |
| Phase 4 | 3 | Low | 1 hour |

**Total:** ~8-10 hours of focused work

---

## Success Criteria

A production-grade autorouter should:
- [ ] 0 DRC errors on routed boards
- [ ] 0 unconnected items (or clear "unroutable" report)
- [ ] Handle 4+ layer boards correctly
- [ ] Support THT and SMD components
- [ ] Maintain specified clearances
- [ ] Complete VCC/GND power distribution
