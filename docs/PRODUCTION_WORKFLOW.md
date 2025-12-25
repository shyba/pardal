# Production Workflow Guide

How to go from a routed board to a production-ready KiCad file with 0 DRC errors.

## Quick Version

```bash
# 1. Route board (venv Python)
./venv/bin/python -m pcb_tool.cli route input.kicad_pcb -o routed.kicad_pcb

# 2. Finalize for production (system Python with pcbnew)
/usr/bin/python3 -m pcb_tool.finalize routed.kicad_pcb final.kicad_pcb

# 3. Verify 0 DRC errors
kicad-cli pcb drc final.kicad_pcb
```

## Understanding the Two-Stage Process

### Why Two Stages?

Pardal-PCB uses **two different Python environments**:

| Stage | Python | Purpose |
|-------|--------|---------|
| **Routing** | venv (`./venv/bin/python`) | Pure Python routing algorithms, no KiCad dependency |
| **Finalization** | System (`/usr/bin/python3`) | KiCad SDK for library footprints, zones, 3D models |

**Why not just use system Python for everything?**
- The venv has specific dependencies (z3-solver, numpy) that may conflict with system packages
- Routing code is pure Python and doesn't need pcbnew
- Keeping them separate avoids dependency conflicts

**Why not use venv for finalization?**
- KiCad's `pcbnew` module is installed with KiCad, not pip-installable
- It's compiled against system Python and won't work in a venv

## Detailed Workflow

### Stage 1: Create and Route Board

Use the Python API or REPL to create and route your board:

```python
# Using Python API (runs in venv)
from pcb_tool.board_builder import fpga_board
from pcb_tool.routing_strategies import route_board
from pcb_tool.kicad_writer import KicadWriter

board = (fpga_board(layers=4, width=40, height=40)
    .component("U1", "TQFP-32", (20, 20))
    .component("C1", "0603", (12, 20))
    .net("VCC", "Power", [("U1", "8"), ("C1", "1")])
    .net("GND", "Power", [("U1", "16"), ("C1", "2")])
    .build())

route_board(board, "fpga")
KicadWriter().write(board, "routed.kicad_pcb")
```

Or via CLI:
```bash
./venv/bin/python -m pcb_tool.cli route input.kicad_pcb -o routed.kicad_pcb
```

**Output**: `routed.kicad_pcb` - Board with traces but simplified footprints (no graphics, no 3D models)

### Stage 2: Finalize for Production

The finalization step:
1. **Loads library footprints** - Replaces simplified footprints with full KiCad library versions (includes silkscreen, courtyard, 3D models)
2. **Adds copper zones** - Creates GND pour on bottom layer
3. **Fills zones** - Computes actual copper fill polygons
4. **Validates** - Basic sanity checks

```bash
/usr/bin/python3 -m pcb_tool.finalize routed.kicad_pcb final.kicad_pcb
```

**Output**: `final.kicad_pcb` - Production-ready board

### Stage 3: Validate with DRC

Always run KiCad's DRC to verify the board is manufacturable:

```bash
kicad-cli pcb drc final.kicad_pcb -o drc_report.txt
```

**Target**: 0 errors, 0 warnings

## Common Issues

### "ImportError: No module named 'pcbnew'"

**Problem**: Running finalize with venv Python instead of system Python.

**Solution**: Use `/usr/bin/python3` explicitly:
```bash
/usr/bin/python3 -m pcb_tool.finalize ...
```

### "ModuleNotFoundError: No module named 'pcb_tool'"

**Problem**: System Python can't find pcb_tool module.

**Solution**: Add pardal-pcb to PYTHONPATH:
```bash
PYTHONPATH=/path/to/pardal-pcb /usr/bin/python3 -m pcb_tool.finalize ...
```

### DRC Errors After Finalization

**Clearance violations**: Traces too close to pads
- Solution: Increase clearance in net class settings before routing

**Unconnected items**: Missing connections
- Solution: Check all nets have complete routing before finalizing

**Zone issues**: Copper pour not filling correctly
- Solution: Re-run finalization, check zone outline covers board area

## Simplified Setup Script

Create this script for easier workflow:

```bash
#!/bin/bash
# pardal-workflow.sh - Complete routing and finalization

PARDAL_DIR="$(dirname "$0")"
INPUT="$1"
OUTPUT="${2:-board_final.kicad_pcb}"
TEMP_ROUTED="/tmp/pardal_routed_$$.kicad_pcb"

# Stage 1: Route (venv Python)
echo "Routing..."
"$PARDAL_DIR/venv/bin/python" -m pcb_tool.cli route "$INPUT" -o "$TEMP_ROUTED"

# Stage 2: Finalize (system Python)
echo "Finalizing..."
PYTHONPATH="$PARDAL_DIR" /usr/bin/python3 -m pcb_tool.finalize "$TEMP_ROUTED" "$OUTPUT"

# Stage 3: DRC
echo "Running DRC..."
kicad-cli pcb drc "$OUTPUT"

# Cleanup
rm -f "$TEMP_ROUTED"

echo "Done: $OUTPUT"
```

## Zone Configuration

By default, finalization adds a GND zone on the bottom layer (B.Cu). To customize:

```python
# In your own finalization script
import pcbnew

board = pcbnew.LoadBoard("routed.kicad_pcb")

# Add custom zone
zone = pcbnew.ZONE(board)
zone.SetNet(board.FindNet("GND"))
zone.SetLayer(pcbnew.B_Cu)
zone.SetLocalClearance(pcbnew.FromMM(0.3))

# Define zone outline (board edges)
outline = zone.Outline()
outline.NewOutline()
mm = 1000000  # KiCad internal units
outline.Append(int(0 * mm), int(0 * mm))
outline.Append(int(40 * mm), int(0 * mm))
outline.Append(int(40 * mm), int(40 * mm))
outline.Append(int(0 * mm), int(40 * mm))

board.Add(zone)

# Fill all zones
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())

board.Save("final.kicad_pcb")
```

## Layer Reference

| Board Type | Layers | Zone Recommendations |
|------------|--------|---------------------|
| 2-layer | F.Cu, B.Cu | GND pour on B.Cu |
| 4-layer | F.Cu, In1.Cu, In2.Cu, B.Cu | GND on B.Cu, optionally VCC on In2.Cu |
| 6-layer | F.Cu, In1-4.Cu, B.Cu | GND on B.Cu and In2.Cu, VCC on In3.Cu |

## Troubleshooting Checklist

Before finalizing:
- [ ] All nets routed (check with `STATS` command or `result.nets_routed`)
- [ ] No DRC errors in routed board
- [ ] Board dimensions set correctly

After finalizing:
- [ ] Run `kicad-cli pcb drc` - should show 0 errors
- [ ] Open in KiCad to visually verify
- [ ] Check 3D viewer for correct component models

## See Also

- [SDK_WORKFLOW_GUIDE.md](SDK_WORKFLOW_GUIDE.md) - Detailed SDK internals
- [PYTHON_API_GUIDE.md](PYTHON_API_GUIDE.md) - Python API reference
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Command cheat sheet
