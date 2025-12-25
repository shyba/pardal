# Pardal-PCB Python API Guide

This guide covers the Python API for creating and routing PCB boards programmatically.

## Quick Start

### Creating a Simple Board

```python
from pcb_tool.board_builder import BoardBuilder

# Create a 4-layer board 40x40mm
board = (BoardBuilder(layers=4, width=40, height=40)
    .net_class("Power", track_width=0.5, clearance=0.25)
    .net_class("Signal", track_width=0.2, clearance=0.2)
    .component("U1", "TQFP-32", (20, 20))
    .component("C1", "0603", (12, 20))
    .component("C2", "0603", (28, 20))
    .net("VCC", "Power", [("U1", "8"), ("C1", "1"), ("C2", "1")])
    .net("GND", "Power", [("U1", "16"), ("C1", "2"), ("C2", "2")])
    .build())

# Route using FPGA strategy
from pcb_tool.routing_strategies import route_board
result = route_board(board, "fpga")
print(f"Routed {result.nets_routed}/{result.nets_total} nets")
```

## BoardBuilder API

The `BoardBuilder` class provides a fluent interface for creating boards:

### Constructor

```python
BoardBuilder(layers=2, width=100.0, height=100.0)
```

- `layers`: Number of copper layers (2, 4, 6, or 8)
- `width`: Board width in mm
- `height`: Board height in mm

### Methods

#### `.net_class(name, track_width, clearance, via_size, via_drill)`

Add a net class for routing rules:

```python
builder.net_class("Power", track_width=0.5, clearance=0.25, via_size=0.8, via_drill=0.4)
builder.net_class("Signal", track_width=0.2, clearance=0.2, via_size=0.6, via_drill=0.3)
```

#### `.component(ref, footprint, position, value, rotation, layer)`

Add a component with automatic pad generation:

```python
# Using shorthand footprint names
builder.component("U1", "TQFP-32", (20, 20))
builder.component("R1", "0603", (10, 15), value="10k")
builder.component("C1", "0805", (12, 20), rotation=90, value="100nF")
```

**Supported footprint shorthands:**
- Passives: `0402`, `0603`, `0805`, `1206` (prefix with R_ or C_ for explicit type)
- QFP: `TQFP-32`, `TQFP-44`, `TQFP-48`, `LQFP-64`, `LQFP-100`
- SOIC: `SOIC-8`, `SOIC-14`, `SOIC-16`
- SOT: `SOT-23`, `SOT-23-5`, `SOT-23-6`
- Headers: `PinHeader_1x02_P2.54mm_Vertical`, etc.

#### `.net(name, net_class, connections, track_width)`

Create a net with connections:

```python
# Net with class-derived width
builder.net("VCC", "Power", [("U1", "8"), ("C1", "1")])

# Net with explicit width
builder.net("SIG1", track_width=0.3, connections=[("U1", "1"), ("J1", "2")])
```

#### `.connect(net_name, ref, pin)`

Add a connection to an existing net:

```python
builder.net("VCC", "Power", [("U1", "8"), ("C1", "1")])
builder.connect("VCC", "C2", "1")  # Add another connection
```

#### `.build()`

Return the constructed Board object:

```python
board = builder.build()
```

### Convenience Functions

```python
from pcb_tool.board_builder import quick_board, fpga_board, simple_board

# Quick 4-layer board
board = quick_board(4, 50, 50).component("U1", "TQFP-32", (25, 25)).build()

# FPGA-optimized board with Power/Signal classes
board = fpga_board().component("U1", "TQFP-32", (20, 20)).build()

# Simple 2-layer board
board = simple_board().component("R1", "0603", (10, 10)).build()
```

## Routing Strategies

### Available Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `simple` / `2layer` | Balanced 2-layer routing | Simple digital circuits |
| `ground_plane` / `2layer_ground` | B.Cu as GND plane | Analog, audio circuits |
| `fpga` / `4layer_fpga` | VCC on F.Cu, signals on inner, GND on B.Cu | FPGA/MCU designs |
| `mixed` / `4layer` | Balanced 4-layer | Mixed-signal boards |

### Using Strategies

```python
from pcb_tool.routing_strategies import route_board, get_strategy, auto_select_strategy

# Route with specific strategy
result = route_board(board, "fpga")

# Auto-select based on board configuration
strategy_name = auto_select_strategy(board)
result = route_board(board, strategy_name)

# Get strategy object for custom use
strategy = get_strategy("fpga")
result = strategy.route(board)
```

### RoutingResult

The `route_board()` function returns a `RoutingResult`:

```python
result = route_board(board, "fpga")

print(f"Success: {result.success}")
print(f"Nets: {result.nets_routed}/{result.nets_total}")
print(f"Length: {result.total_length_mm:.1f}mm")
print(f"Vias: {result.total_vias}")
print(f"Layers used: {result.layers_used}")
```

## Footprint Templates

### Generating Pads

```python
from pcb_tool.footprint_templates import generate_pads, list_templates, list_aliases

# Generate pads for a footprint
pads = generate_pads("TQFP-32")  # Returns list of Pad objects
pads = generate_pads("0603")     # Shorthand works too

# List all available templates
templates = list_templates()  # ['C_0402_1005Metric', 'C_0603_1608Metric', ...]

# List aliases
aliases = list_aliases()  # {'0603': 'R_0603_1608Metric', ...}
```

### Custom Pad Generation

For footprints not in the template library:

```python
from pcb_tool.footprint_templates import (
    generate_qfp_pads,
    generate_header_pads,
    generate_two_pin_smd_pads,
    generate_soic_pads
)

# Custom QFP
pads = generate_qfp_pads(pin_count=64, pitch=0.5, body_size=(10.0, 10.0))

# Custom header
pads = generate_header_pads(rows=2, cols=8, pitch=2.54, drill=1.0)

# Custom SMD passive
pads = generate_two_pin_smd_pads(pad_spacing=2.0, pad_size=(1.0, 0.8))
```

## Complete Example: FPGA Board

```python
#!/usr/bin/env python3
"""Create and route an FPGA development board."""

from pcb_tool.board_builder import fpga_board
from pcb_tool.routing_strategies import route_board
from pcb_tool.kicad_writer import KicadWriter

# Create 4-layer FPGA board
board = (fpga_board(layers=4, width=40, height=40)
    # Central IC
    .component("U1", "TQFP-32", (20, 20), value="FPGA")

    # Decoupling capacitors
    .component("C1", "0603", (12, 20), value="100nF")
    .component("C2", "0603", (28, 20), value="100nF")
    .component("C3", "0603", (20, 12), rotation=90, value="100nF")
    .component("C4", "0603", (20, 28), rotation=90, value="100nF")

    # JTAG header
    .component("J1", "PinHeader_2x05_P1.27mm_Vertical", (5, 20), value="JTAG")

    # Power connector
    .component("J2", "PinHeader_1x02_P2.54mm_Vertical", (35, 20), value="PWR")

    # Power nets (0.5mm traces)
    .net("VCC", "Power", [
        ("J2", "1"), ("U1", "8"), ("U1", "24"),
        ("C1", "1"), ("C2", "1"), ("C3", "1"), ("C4", "1")
    ])
    .net("GND", "Power", [
        ("J2", "2"), ("U1", "16"), ("U1", "32"),
        ("C1", "2"), ("C2", "2"), ("C3", "2"), ("C4", "2")
    ])

    # JTAG signals (0.2mm traces)
    .net("TMS", "Signal", [("J1", "2"), ("U1", "1")])
    .net("TCK", "Signal", [("J1", "4"), ("U1", "2")])
    .net("TDI", "Signal", [("J1", "8"), ("U1", "3")])
    .net("TDO", "Signal", [("J1", "6"), ("U1", "4")])

    .build()
)

# Route using FPGA strategy
result = route_board(board, "fpga")

print(f"Routed {result.nets_routed}/{result.nets_total} nets")
print(f"Total length: {result.total_length_mm:.1f}mm")
print(f"Vias: {result.total_vias}")
print(f"Layers: {result.layers_used}")

# Save to KiCad format
KicadWriter().write(board, "fpga_board.kicad_pcb")
```

## Data Model Reference

### Board

```python
from pcb_tool.data_model import Board, STANDARD_LAYER_STACKS

board = Board(layers=STANDARD_LAYER_STACKS[4])
board.width = 100.0
board.height = 80.0

# Access components and nets
board.components["U1"]  # Component object
board.nets["VCC"]       # Net object
board.net_classes["Power"]  # NetClass object

# Layer info
board.layer_count       # 4
board.layers           # ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']
```

### Component

```python
from pcb_tool.data_model import Component, Pad

comp = Component(
    ref="U1",
    value="FPGA",
    footprint="TQFP-32_7x7mm_P0.8mm",
    position=(20.0, 20.0),
    rotation=0,
    layer="F.Cu",
    pads=[...]  # List of Pad objects
)

# Get absolute pad position
x, y = comp.get_pad_position(1)  # Pin 1 position in board coordinates
```

### Net

```python
from pcb_tool.data_model import Net

net = Net(name="VCC", code="1", track_width=0.5, net_class="Power")
net.add_connection("U1", "8")
net.add_connection("C1", "1")

# After routing
for segment in net.segments:
    print(f"{segment.start} -> {segment.end} on {segment.layer}")
for via in net.vias:
    print(f"Via at {via.position}")
```

### NetClass

```python
from pcb_tool.data_model import NetClass

power_class = NetClass(
    name="Power",
    track_width=0.5,
    clearance=0.25,
    via_size=0.8,
    via_drill=0.4
)
```

## DRC and Validation

```python
from pcb_tool.commands.drc import CheckDrcCommand

# Run DRC
cmd = CheckDrcCommand()
result = cmd.execute(board)
print(result)  # Shows any clearance or connectivity errors
```

## Saving Boards

```python
from pcb_tool.kicad_writer import KicadWriter

# Write to KiCad format
KicadWriter().write(board, "output.kicad_pcb")
```
