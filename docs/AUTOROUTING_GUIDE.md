# Autorouting Guide

## Table of Contents
1. [System Overview](#system-overview)
2. [Quick Start](#quick-start)
3. [Command Reference](#command-reference)
4. [Troubleshooting](#troubleshooting)
5. [Performance Tips](#performance-tips)
6. [Example Workflow](#example-workflow)

## System Overview

The PCB autorouting system provides automated trace routing using advanced pathfinding algorithms. It features:

- **Multi-layer routing**: Automatic routing on F.Cu (front copper) and B.Cu (back copper) layers
- **Via insertion**: Intelligent via placement for layer transitions
- **Priority-based routing**: Power nets (GND, VCC, +12V, etc.) routed first
- **Conflict detection**: Automatic DRC checking for clearances and crossings
- **Grid-based pathfinding**: A* algorithm with 0.2mm resolution
- **Layer optimization**: Z3 SMT solver for optimal via minimization

### Architecture

```
Board → RoutingGrid → PathFinder → MultiNetRouter → RoutedNets
                          ↓
                    LayerOptimizer
```

- **RoutingGrid**: Discretized representation of the PCB (0.2mm cells)
- **PathFinder**: A* pathfinding for single net routing
- **MultiNetRouter**: Coordinates routing of multiple nets with conflict avoidance
- **LayerOptimizer**: Minimizes vias using constraint solving

## Quick Start

### Using the CLI (Recommended)

The easiest way to build and route a board:

```bash
# Build with autorouting and DRC
pardal build project.net -p placement.txt -o board.kicad_pcb --route

# Build with full finalization (production-ready, 0 DRC errors)
pardal build project.net -p placement.txt -o board.kicad_pcb --route --finalize

# Check DRC on existing board
pardal drc board.kicad_pcb
```

**Note**: The `--finalize` flag requires system Python with pcbnew (not venv).

### Using the REPL

For interactive work, use `pardal repl` or follow the steps below:

### Basic Autorouting

1. Load your board:
   ```
   LOAD myboard.kicad_pcb
   ```

2. Place components:
   ```
   MOVE R1 TO 10 20
   MOVE C1 TO 30 20
   ```

3. Route all nets:
   ```
   AUTOROUTE ALL
   ```

4. Save the result:
   ```
   SAVE myboard_routed.kicad_pcb
   ```

### Route Specific Net

```
AUTOROUTE NET GND
```

### Route Only Unrouted Nets

```
AUTOROUTE UNROUTED
```

### Route with Layer Preference

```
AUTOROUTE NET VCC PREFER F.Cu
```

## Command Reference

### AUTOROUTE Command

Automatically routes nets using the pathfinding engine.

**Syntax:**
```
AUTOROUTE ALL [PREFER <layer>] [NOOPTIMIZE]
AUTOROUTE UNROUTED [PREFER <layer>] [NOOPTIMIZE]
AUTOROUTE NET <net_name> [PREFER <layer>] [NOOPTIMIZE]
```

**Parameters:**
- `ALL`: Route all nets on the board
- `UNROUTED`: Route only nets with no existing traces
- `NET <net_name>`: Route a specific net (e.g., "GND", "VCC", "SIGNAL1")
- `PREFER <layer>`: Optional layer preference (F.Cu or B.Cu)
- `NOOPTIMIZE`: Disable Z3 layer optimization (faster but more vias)

**Examples:**
```
AUTOROUTE ALL
AUTOROUTE NET GND PREFER B.Cu
AUTOROUTE UNROUTED
AUTOROUTE NET +5V NOOPTIMIZE
```

**Output:**
```
Successfully routed 12/15 nets:
  GND: 45.2mm, 2 vias [POWER]
  VCC: 38.7mm, 1 via [POWER]
  SIGNAL1: 12.3mm, 0 vias
  ...

Failed to route (3):
  SIGNAL_DENSE: No path found
  ...

Total: 234.5mm traces, 8 vias
```

### OPTIMIZE Command

Optimizes layer assignments for existing routing to minimize vias.

**Syntax:**
```
OPTIMIZE ALL
OPTIMIZE NET <net_name>
```

**Parameters:**
- `ALL`: Optimize all routed nets
- `NET <net_name>`: Optimize a specific net

**Examples:**
```
OPTIMIZE ALL
OPTIMIZE NET GND
```

**Output:**
```
Optimized 12 nets:
  Vias before: 15
  Vias after: 8
  Reduction: 47%
```

### Supporting Commands

**Check DRC:**
```
CHECK DRC
```

**View board state:**
```
SHOW BOARD
```

**List nets:**
```
LIST NETS
```

**Delete routing:**
```
DELETE ROUTE NET GND
```

## Troubleshooting

### "No path found" Errors

**Problem:** Autorouter cannot find a path between net endpoints.

**Causes & Solutions:**

1. **Board too congested**
   - Rearrange components with more spacing
   - Use `ARRANGE GRID` to spread components:
     ```
     ARRANGE GRID SPACING 15
     ```

2. **Obstacles blocking path**
   - Check component placement with `SHOW BOARD`
   - Move components that block critical paths
   - Consider manual routing for difficult nets

3. **Insufficient clearance**
   - Default clearance is 0.2mm
   - Ensure pads have adequate spacing

4. **Wrong layer preference**
   - Try opposite layer:
     ```
     AUTOROUTE NET SIGNAL1 PREFER B.Cu
     ```

### Routing Quality Issues

**Problem:** Routes are suboptimal (too long, excessive vias).

**Solutions:**

1. **Route power nets first**
   - Power nets are automatically prioritized
   - Verify with: `LIST NETS`
   - Ensure nets are named: GND, VCC, VDD, VSS, +12V, +5V, +3V3

2. **Use optimization**
   - Run after autorouting:
     ```
     AUTOROUTE ALL
     OPTIMIZE ALL
     ```

3. **Better component placement**
   - Group related components
   - Minimize trace lengths
   - Use `ARRANGE CLUSTER` for functional grouping

4. **Manual pre-routing**
   - Route critical nets manually first:
     ```
     ROUTE NET GND FROM J1.1 VIA (50, 50) TO C1.1 LAYER B.Cu WIDTH 1.0
     ```
   - Then autoroute remaining:
     ```
     AUTOROUTE UNROUTED
     ```

### DRC Violations

**Problem:** `CHECK DRC` reports errors after autorouting.

**Causes & Solutions:**

1. **Clearance violations**
   - Default grid resolution: 0.2mm
   - Default clearance: 0.2mm
   - For tighter routing, review component spacing

2. **Same-layer crossings**
   - Re-run with optimization:
     ```
     OPTIMIZE ALL
     ```
   - May require manual intervention for complex cases

3. **Via conflicts**
   - Delete problematic routing:
     ```
     DELETE ROUTE NET PROBLEM_NET
     ```
   - Re-route with different layer preference

### Performance Issues

**Problem:** Autorouting is slow (>60 seconds).

**Solutions:**

1. **Route in stages**
   - Route power nets first:
     ```
     AUTOROUTE NET GND
     AUTOROUTE NET VCC
     ```
   - Then route remaining:
     ```
     AUTOROUTE UNROUTED
     ```

2. **Disable optimization for testing**
   ```
   AUTOROUTE ALL NOOPTIMIZE
   ```

3. **Reduce board complexity**
   - Split dense areas across layers
   - Simplify component placement

4. **Expected performance**
   - Simple boards (10-20 nets): <5 seconds
   - Medium boards (50-100 nets): 10-30 seconds
   - Complex boards (100+ nets): 30-60 seconds

## Performance Tips

### Component Placement Strategy

Good placement is critical for autorouting success:

1. **Power distribution**
   - Place decoupling capacitors near power pins
   - Keep power traces on dedicated layer when possible

2. **Signal flow**
   - Arrange components in signal flow order
   - Minimize signal path lengths

3. **Grouping**
   - Group by function (power, analog, digital, I/O)
   - Use `ARRANGE CLUSTER` to help:
     ```
     ARRANGE CLUSTER NETS GND,VCC,SIGNAL1,SIGNAL2
     ```

4. **Grid layout**
   - For simple boards, use grid arrangement:
     ```
     ARRANGE GRID SPACING 10 ORIGIN 10 10
     ```

### Net Routing Order

The autorouter prioritizes nets in this order:

1. **Power nets** (GND, VCC, VDD, VSS, +12V, +5V, +3V3)
2. **High-priority nets** (set with priority parameter)
3. **Shorter nets** (easier to route)
4. **Alphabetical** (for determinism)

To influence routing:
- Name power nets correctly (e.g., "GND", not "Ground")
- Route critical nets manually first
- Use UNROUTED mode to fill in remaining nets

### Layer Usage

**Best Practices:**

1. **Two-layer strategy**
   - B.Cu: Ground plane + power distribution
   - F.Cu: Signal routing + power

2. **When to prefer layers**
   - Horizontal signals: F.Cu
   - Vertical signals: B.Cu
   - (Reduces crossings)

3. **Via minimization**
   - Each via adds ~0.3mm to path length
   - Optimize after routing to reduce vias:
     ```
     AUTOROUTE ALL
     OPTIMIZE ALL
     ```

### Grid Resolution

Default: 0.2mm (suitable for most designs)

**Trade-offs:**
- Higher resolution (0.1mm): More accurate, slower, larger memory
- Lower resolution (0.5mm): Faster, less accurate, may miss tight spaces

Currently fixed at 0.2mm. Contact developers if you need customization.

## Example Workflow

### Complete Board Routing from Scratch

This example shows routing a 2-channel injector board with 25 nets.

#### Step 1: Load and Inspect

```
LOAD injector_2ch.kicad_pcb
LIST COMPONENTS
LIST NETS
```

Output shows 14 components, 25 nets including power nets (GND, +12V, +5V).

#### Step 2: Place Components

```
# Power connector
MOVE J1 TO 15 70 ROTATION 0

# Decoupling capacitors
MOVE C1 TO 35 70 ROTATION 0
MOVE C2 TO 50 70 ROTATION 0

# Channel 1 components
MOVE R1 TO 65 48 ROTATION 0
MOVE Q1 TO 75 44 ROTATION 0
MOVE D1 TO 75 28 ROTATION 90

# Channel 2 components
MOVE R2 TO 95 48 ROTATION 0
MOVE Q2 TO 105 44 ROTATION 0
MOVE D2 TO 105 28 ROTATION 90

# Output connector
MOVE J3 TO 130 44 ROTATION 0

# Verify placement
SHOW BOARD
```

#### Step 3: Manual Critical Routing (Optional)

For best results, manually route power nets on dedicated layers:

```
# GND on B.Cu (ground plane)
ROUTE NET GND FROM J1.3 TO C1.2 LAYER B.Cu WIDTH 1.0
ROUTE NET GND FROM C1.2 TO C2.2 LAYER B.Cu WIDTH 0.8

# +12V on F.Cu
ROUTE NET +12V FROM J1.1 TO C1.1 LAYER F.Cu WIDTH 1.2
```

#### Step 4: Autoroute Remaining Nets

```
AUTOROUTE UNROUTED
```

Output:
```
Successfully routed 22/23 nets:
  GND: 45.2mm, 2 vias [POWER] [MANUAL]
  +12V: 38.7mm, 1 via [POWER] [MANUAL]
  +5V: 12.3mm, 1 via [POWER]
  IN1: 15.6mm, 0 vias
  IN2: 16.1mm, 0 vias
  ...

Failed to route (1):
  DENSE_SIGNAL: No path found

Total: 234.5mm traces, 8 vias
```

#### Step 5: Optimize Layer Assignments

```
OPTIMIZE ALL
```

Output:
```
Optimized 22 nets:
  Vias before: 8
  Vias after: 5
  Reduction: 37%
```

#### Step 6: Validate Design

```
CHECK DRC
```

Output:
```
DRC Check Results:
  Clearance violations: 0
  Same-layer crossings: 0
  Trace width violations: 0

All checks passed!
```

#### Step 7: Save Result

```
SAVE injector_2ch_autorouted.kicad_pcb
```

### Incremental Routing Workflow

For complex boards, route incrementally:

```
# 1. Load board
LOAD complex_board.kicad_pcb

# 2. Route power nets first
AUTOROUTE NET GND PREFER B.Cu
AUTOROUTE NET VCC PREFER B.Cu
AUTOROUTE NET +12V
AUTOROUTE NET +5V

# 3. Route high-speed signals manually
ROUTE NET CLK FROM U1.1 TO U2.5 LAYER F.Cu WIDTH 0.3
ROUTE NET DATA0 FROM U1.2 TO U2.6 LAYER F.Cu WIDTH 0.3

# 4. Autoroute remaining signals
AUTOROUTE UNROUTED

# 5. Optimize
OPTIMIZE ALL

# 6. Check and fix issues
CHECK DRC
# (manually fix any reported violations)

# 7. Save
SAVE complex_board_routed.kicad_pcb
```

### Fixing Failed Routes

If autorouting fails for some nets:

```
# 1. Identify problem nets
AUTOROUTE ALL
# Note which nets failed

# 2. Check component placement
SHOW BOARD
# Look for congested areas

# 3. Rearrange if needed
MOVE R5 TO 80 45
MOVE R6 TO 85 45

# 4. Try different layer
AUTOROUTE NET PROBLEM_NET PREFER B.Cu

# 5. Manual routing as fallback
ROUTE NET PROBLEM_NET FROM R5.1 VIA (82, 50) TO R6.2 LAYER F.Cu WIDTH 0.3

# 6. Complete remaining
AUTOROUTE UNROUTED
```

### CLI Workflow

For scripted/automated builds:

```bash
# 1. Build with autorouting
pardal build injector_2ch.net \
    -p placement.txt \
    -o injector_routed.kicad_pcb \
    --route

# 2. Check DRC
pardal drc injector_routed.kicad_pcb

# Output:
# ✓ DRC PASSED: 0 errors, 0 warnings
```

This is equivalent to the REPL workflow but runs in a single command.

## Advanced Topics

### Understanding the Routing Grid

The autorouter discretizes the board into a grid:

- **Resolution**: 0.2mm (5 cells per mm)
- **Cell types**:
  - Free: Available for routing (cost = 1.0)
  - Clearance: Within clearance zone (cost = 2.0, higher cost)
  - Obstacle: Blocked by component/pad (cost = infinity)

View grid statistics:
```
SHOW BOARD
```

Output includes:
```
Routing Grid: 600x400 cells (120.0mm x 80.0mm)
F.Cu: 45234 free, 12456 obstacles, 3210 clearance
B.Cu: 47821 free, 10123 obstacles, 2890 clearance
```

### Via Placement Strategy

Vias are automatically inserted when:
1. Pathfinding determines layer change is beneficial
2. Via cost < continuing on same layer with detour

Via parameters:
- Diameter: 0.8mm (default)
- Clearance: 0.2mm
- Cost penalty: ~3mm equivalent path length

### Power Net Detection

The router automatically detects power nets by name pattern:
- GND (ground)
- VCC, VDD (positive supply)
- VSS (negative supply)
- +12V, +5V, +3V3 (voltage rails)

These nets are:
1. Routed first (before signal nets)
2. Typically assigned wider traces
3. Prioritized for direct paths

### Z3 Optimization

The `OPTIMIZE` command uses Microsoft's Z3 SMT solver to:
1. Analyze all routing paths
2. Find optimal layer assignments
3. Minimize via count
4. Respect DRC constraints

Constraint types:
- Same-layer segments must not cross
- Each segment assigned to exactly one layer
- Via inserted at layer transitions

Timeout: 10 seconds (then returns best solution found)

## FAQ

**Q: Can I route without optimization?**
A: Yes, add `NOOPTIMIZE` flag:
```
AUTOROUTE ALL NOOPTIMIZE
```
Faster but produces more vias.

**Q: How do I route only specific nets?**
A: Route them individually:
```
AUTOROUTE NET GND
AUTOROUTE NET VCC
AUTOROUTE NET SIGNAL1
```

**Q: Can I change grid resolution?**
A: Currently fixed at 0.2mm. Contact developers for custom builds.

**Q: What if autorouting fails completely?**
A: Check:
1. Component placement (too dense?)
2. Board size (too small?)
3. Use `ARRANGE GRID` to spread components
4. Route power nets manually first

**Q: How do I undo autorouting?**
A: Delete routes for specific nets:
```
DELETE ROUTE NET GND
DELETE ROUTE NET VCC
```
Or reload the board file:
```
LOAD myboard.kicad_pcb
```

**Q: Can I customize trace widths?**
A: Yes, with manual routing:
```
ROUTE NET GND FROM J1.1 TO C1.1 LAYER B.Cu WIDTH 1.5
```
Autorouted traces use default widths (0.3-0.5mm for signals, wider for power).

**Q: Does the autorouter respect locked components?**
A: Yes, locked components are treated as fixed obstacles:
```
LOCK U1
AUTOROUTE ALL
```

**Q: How do I report issues or request features?**
A: Contact the development team with:
- Board file (if possible)
- Command sequence
- Expected vs actual behavior
- Error messages

## Best Practices Summary

1. **Place components thoughtfully** - Good placement = successful routing
2. **Route power first** - Manually or let autorouter prioritize
3. **Use incremental approach** - Critical nets first, then autoroute rest
4. **Optimize after routing** - Reduces vias and improves quality
5. **Check DRC regularly** - Catch issues early
6. **Save frequently** - Before major routing operations
7. **Name nets correctly** - Helps autorouter recognize power nets
8. **Spread components** - Avoid congestion that blocks routing
9. **Layer strategy** - Use B.Cu for GND plane when possible
10. **Iterate** - Autorouting may require multiple attempts with adjusted placement

## Glossary

- **DRC**: Design Rule Check - validates electrical clearances and trace widths
- **Via**: Plated hole connecting traces between layers
- **Clearance**: Minimum distance between traces/pads (default 0.2mm)
- **Grid resolution**: Size of routing cells (0.2mm = 5 cells per mm)
- **Net**: Electrical connection between multiple pads
- **Layer**: Copper plane (F.Cu = front, B.Cu = back)
- **Pathfinding**: A* algorithm for finding optimal trace routes
- **Optimization**: Z3 solver for minimizing vias
- **Obstacle**: Grid cell blocked by component or existing trace
- **Priority**: Routing order (power nets > high priority > shorter nets)

## SDK-Based Board Generation

After autorouting, regenerate the board using KiCad's SDK for production-quality output.

### One-Shot Finalization (Easiest)

Use the `--finalize` flag to automatically run the SDK workflow:

```bash
pardal build project.net -o board.kicad_pcb --route --finalize
```

This automates the entire 3-phase workflow described below. Requires system Python with pcbnew.

### Why Use SDK Workflow?

The autorouter generates simplified footprints for routing. For production boards you need:
- **Library footprints** with complete graphics (silkscreen, courtyard, fab layers)
- **3D models** for visual verification
- **Proper zone fills** computed by KiCad's zone filler
- **0 DRC warnings** including footprint mismatch checks

### Three-Phase Workflow

Due to KiCad's SWIG bindings, run each phase as a separate Python process:

**Phase 1: Extract Data**
```python
# extract_board_data.py - Run with system Python
import pcbnew
board = pcbnew.LoadBoard("routed_board.kicad_pcb")
# Extract positions, nets, tracks to JSON
```

**Phase 2: Build with Library Footprints**
```python
# build_board_from_json.py - Run with system Python
import pcbnew
io = pcbnew.PCB_IO_KICAD_SEXPR()
# Load footprints from KiCad library
fp = io.FootprintLoad('/usr/share/kicad/footprints/Resistor_SMD.pretty', 'R_0805_2012Metric')
# Position by pad 1 alignment (library footprints have pad 1 at origin)
```

**Phase 3: Add Zones**
```python
# add_zones.py - Run with system Python
import pcbnew
board = pcbnew.LoadBoard("board_with_footprints.kicad_pcb")
# Add GND zones, fill them
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
```

### Pad Alignment

Library footprints have their reference point at pad 1, while routed boards may have footprints centered. Align by pad 1 position:

```python
# Find pad 1 offset in library footprint
for pad in fp.Pads():
    if pad.GetNumber() == '1':
        lib_pad1_offset = pad.GetPosition()
        break

# Position so pad 1 matches original
new_pos = original_pad1_pos - lib_pad1_offset
fp.SetPosition(new_pos)
```

### Validation

After all phases, validate with KiCad's DRC:
```bash
kicad-cli pcb drc --output drc_report.txt final_board.kicad_pcb
```

Target: **0 violations, 0 unconnected items, 0 footprint errors**

See `docs/SDK_WORKFLOW_GUIDE.md` for complete step-by-step instructions with full script examples.

## Conclusion

The PCB autorouting system provides powerful automated routing while maintaining full manual control when needed. The key to success is:

1. Good component placement
2. Understanding net priorities
3. Incremental approach (critical nets first)
4. Post-routing optimization
5. DRC validation

For complex designs, combine manual and automatic routing to achieve optimal results.

Happy routing!
