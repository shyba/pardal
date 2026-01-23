# AI Integration Guide for Pardal-PCB

This guide helps AI assistants understand how to create and route PCB boards using Pardal-PCB.

## Key Concepts

1. **Board** - The PCB with dimensions and layer count
2. **Component** - IC, resistor, capacitor, etc. placed on the board
3. **Footprint** - Physical package (e.g., TQFP-32, 0603)
4. **Net** - Electrical connection between component pins
5. **Net Class** - Routing rules (trace width, clearance) for a group of nets
6. **Routing Strategy** - Pre-configured layer assignment and via cost settings

## Minimal Working Example

```python
from pcb_tool.board_builder import BoardBuilder
from pcb_tool.routing_strategies import route_board
from pcb_tool.kicad_writer import KicadWriter

# 1. Create board with builder
board = (BoardBuilder(layers=4, width=40, height=40)
    .net_class("Power", track_width=0.5)
    .net_class("Signal", track_width=0.2)
    .component("U1", "TQFP-32", (20, 20))
    .component("C1", "0603", (15, 20))
    .net("VCC", "Power", [("U1", "8"), ("C1", "1")])
    .net("GND", "Power", [("U1", "16"), ("C1", "2")])
    .build())

# 2. Route board
result = route_board(board, "fpga")

# 3. Save output
KicadWriter().write(board, "board.kicad_pcb")
```

## Decision Tree for Board Creation

### Step 1: Choose Layer Count

| Condition | Layer Count |
|-----------|-------------|
| Simple circuit, < 10 nets | 2 layers |
| FPGA/MCU, 10-50 nets | 4 layers |
| Complex, > 50 nets | 6 layers |

### Step 2: Choose Routing Strategy

| Board Type | Strategy |
|------------|----------|
| 2-layer simple | `simple` |
| 2-layer with ground plane | `ground_plane` |
| 4-layer FPGA/MCU | `fpga` |
| 4-layer mixed-signal | `mixed` |

### Step 3: Set Trace Widths

| Net Type | Typical Width |
|----------|---------------|
| Power (VCC, 3V3, 5V) | 0.4-0.8 mm |
| Ground (GND, VSS) | 0.4-0.8 mm |
| Signal (data, clock) | 0.15-0.25 mm |
| High-speed differential | 0.15 mm |

## Common Footprint Names

### SMD Passives (Resistors, Capacitors)
- `0402` - 1.0 x 0.5 mm (small)
- `0603` - 1.6 x 0.8 mm (common)
- `0805` - 2.0 x 1.25 mm (medium)
- `1206` - 3.2 x 1.6 mm (large)

### ICs
- `TQFP-32` - 32-pin quad flat pack
- `TQFP-44` - 44-pin quad flat pack
- `LQFP-64` - 64-pin low-profile QFP
- `SOIC-8` - 8-pin small outline IC
- `SOT-23` - 3-pin small transistor

### Connectors
- `PinHeader_1x02_P2.54mm_Vertical` - 2-pin header
- `PinHeader_2x05_P2.54mm_Vertical` - 10-pin header
- `PinHeader_2x05_P1.27mm_Vertical` - JTAG header

## Template: FPGA Development Board

```python
from pcb_tool.board_builder import fpga_board
from pcb_tool.routing_strategies import route_board
from pcb_tool.kicad_writer import KicadWriter

# Create board with FPGA preset (4-layer, Power/Signal classes)
board = (fpga_board(layers=4, width=40, height=40)
    # Central IC
    .component("U1", "TQFP-32", (20, 20), value="FPGA")

    # Decoupling capacitors around IC
    .component("C1", "0603", (12, 20), value="100nF")
    .component("C2", "0603", (28, 20), value="100nF")
    .component("C3", "0603", (20, 12), rotation=90, value="100nF")
    .component("C4", "0603", (20, 28), rotation=90, value="100nF")

    # Connectors
    .component("J1", "PinHeader_2x05_P1.27mm_Vertical", (5, 20), value="JTAG")
    .component("J2", "PinHeader_1x02_P2.54mm_Vertical", (35, 20), value="PWR")

    # Power nets - connect to all VCC pins and capacitor positive
    .net("VCC", "Power", [
        ("J2", "1"), ("U1", "8"), ("U1", "24"),
        ("C1", "1"), ("C2", "1"), ("C3", "1"), ("C4", "1")
    ])

    # Ground nets - connect to all GND pins and capacitor negative
    .net("GND", "Power", [
        ("J2", "2"), ("U1", "16"), ("U1", "32"),
        ("C1", "2"), ("C2", "2"), ("C3", "2"), ("C4", "2")
    ])

    # Signal nets - JTAG
    .net("TMS", "Signal", [("J1", "2"), ("U1", "1")])
    .net("TCK", "Signal", [("J1", "4"), ("U1", "2")])
    .net("TDI", "Signal", [("J1", "8"), ("U1", "3")])
    .net("TDO", "Signal", [("J1", "6"), ("U1", "4")])

    .build()
)

# Route using FPGA strategy (VCC→F.Cu, GND→B.Cu, signals→inner)
result = route_board(board, "fpga")

# Check result
if result.success:
    print(f"Success! Routed {result.nets_routed} nets, {result.total_vias} vias")
else:
    print(f"Warning: {result.nets_total - result.nets_routed} nets failed")

# Save to KiCad
KicadWriter().write(board, "fpga_board.kicad_pcb")
```

## Template: Simple 2-Layer Board

```python
from pcb_tool.board_builder import simple_board
from pcb_tool.routing_strategies import route_board
from pcb_tool.kicad_writer import KicadWriter

board = (simple_board(layers=2, width=30, height=20)
    .component("R1", "0603", (10, 10), value="10k")
    .component("R2", "0603", (20, 10), value="10k")
    .component("C1", "0805", (15, 15), value="100nF")
    .net("SIG1", connections=[("R1", "2"), ("R2", "1")])
    .net("SIG2", connections=[("R2", "2"), ("C1", "1")])
    .build())

result = route_board(board, "simple")
KicadWriter().write(board, "simple_board.kicad_pcb")
```

## Error Handling

### Common Issues and Solutions

1. **"Net not found"** - Net name typo or net not created
   ```python
   # Check net exists before routing
   if "VCC" in board.nets:
       # proceed
   ```

2. **"Component not found"** - Component ref typo
   ```python
   # Check component exists
   if "U1" in board.components:
       # proceed
   ```

3. **"Pin not found"** - Wrong pin number for footprint
   - TQFP-32: pins 1-32
   - 0603: pins 1, 2
   - Headers: pin count depends on size

4. **Routing fails** - Try different strategy or check clearances
   ```python
   # Try with lower via cost to encourage layer switching
   from pcb_tool.commands.routing import AutoRouteCommand
   cmd = AutoRouteCommand(net_name="ALL", via_costs={"through": 1.0})
   cmd.execute(board)
   ```

## Quick Checklist for AI Assistants

Before routing:
- [ ] Board dimensions set (width, height)
- [ ] Layer count appropriate for complexity (2/4/6)
- [ ] Net classes defined (Power, Signal)
- [ ] All components have valid footprints
- [ ] All nets have >= 2 connections
- [ ] Power/GND nets use Power class
- [ ] Signal nets use Signal class

After routing:
- [ ] Check `result.success`
- [ ] Check `result.nets_routed == result.nets_total`
- [ ] Run DRC if available

## API Reference Summary

```python
# Board Builder
BoardBuilder(layers, width, height)
    .net_class(name, track_width, clearance, via_size, via_drill)
    .component(ref, footprint, position, value, rotation)
    .net(name, net_class, connections)
    .build()

# Convenience builders
fpga_board(layers=4, width=40, height=40)  # Pre-configured for FPGA
simple_board(layers=2, width=50, height=50)  # Basic 2-layer

# Routing
route_board(board, strategy)  # Returns RoutingResult
# Strategies: "simple", "ground_plane", "fpga", "mixed"

# Output
KicadWriter().write(board, "file.kicad_pcb")
```
