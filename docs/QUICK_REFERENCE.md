# Pardal-PCB Quick Reference

## REPL Commands

### Board Setup
```
SET BOARD SIZE <width_mm> <height_mm>    Set board dimensions
SET LAYERS <2|4|6>                       Set layer count
SET WIDTH NET <name> <mm>                Set net trace width
SET WIDTH CLASS <name> <mm>              Set class trace width
SET CLEARANCE CLASS <name> <mm>          Set class clearance
```

### Components
```
CREATE COMPONENT <ref> <footprint> <x> <y> [ROTATION <deg>] [VALUE <val>]
MOVE <ref> <x> <y>                       Move component
ROTATE <ref> <degrees>                   Rotate component
FLIP <ref>                               Flip to other side
WHERE <ref>                              Show component location
LIST COMPONENTS                          List all components
```

### Nets
```
CREATE NET <name> <ref.pin> <ref.pin> [<ref.pin>...]
CREATE NET <name> CLASS <class> <ref.pin> <ref.pin> [<ref.pin>...]
LIST NETS                                List all nets
SHOW NET <name>                          Show net details
```

### Routing
```
AUTOROUTE ALL                            Route all nets
AUTOROUTE ALL UNROUTED                   Route unrouted nets only
AUTOROUTE NET <name>                     Route specific net
AUTOROUTE NET <name> LAYER <layer>       Route on specific layer
AUTOROUTE STRATEGY <name>                Route using strategy
ROUTE <net> <start> <end>                Manual route segment
VIA <net> <x> <y>                        Place via
DELETE_ROUTE <net> <x> <y>               Delete route segment
DELETE_VIA <net> <x> <y>                 Delete via
```

### Inspection
```
STATS                                    Show all statistics
STATS ROUTING                            Show routing stats
STATS NETS                               Show net stats
STATS COMPONENTS                         Show component stats
CHECK DRC                                Run design rule check
CHECK AIRWIRES                           Show unrouted connections
CHECK CLEARANCE                          Check trace clearances
SHOW BOARD                               Show board summary
```

### File Operations
```
LOAD <file.kicad_pcb>                    Load board file
SAVE <file.kicad_pcb>                    Save board file
```

### Undo/Redo
```
UNDO                                     Undo last command
REDO                                     Redo undone command
HISTORY                                  Show command history
```

## Routing Strategies

| Strategy | Alias | Description |
|----------|-------|-------------|
| `simple` | `2layer` | Basic 2-layer balanced |
| `ground_plane` | `2layer_ground` | GND plane on B.Cu |
| `fpga` | `4layer_fpga` | VCC/F.Cu, GND/B.Cu, signals/inner |
| `mixed` | `4layer` | Balanced 4-layer |

## Footprint Shorthands

| Shorthand | Full Name |
|-----------|-----------|
| `0402` | `R_0402_1005Metric` |
| `0603` | `R_0603_1608Metric` |
| `0805` | `R_0805_2012Metric` |
| `1206` | `R_1206_3216Metric` |
| `TQFP-32` | `TQFP-32_7x7mm_P0.8mm` |
| `TQFP-44` | `TQFP-44_10x10mm_P0.8mm` |
| `LQFP-64` | `LQFP-64_10x10mm_P0.5mm` |
| `SOIC-8` | `SOIC-8_3.9x4.9mm_P1.27mm` |
| `SOT-23` | `SOT-23` |

## Python API Quick Start

### Create Board (Builder Pattern)
```python
from pcb_tool.board_builder import fpga_board
from pcb_tool.routing_strategies import route_board
from pcb_tool.kicad_writer import KicadWriter

board = (fpga_board(layers=4, width=40, height=40)
    .component("U1", "TQFP-32", (20, 20))
    .component("C1", "0603", (12, 20), value="100nF")
    .net("VCC", "Power", [("U1", "8"), ("C1", "1")])
    .net("GND", "Power", [("U1", "16"), ("C1", "2")])
    .build())

result = route_board(board, "fpga")
KicadWriter().write(board, "output.kicad_pcb")
```

### Create Board (Direct Data Model)
```python
from pcb_tool.data_model import Board, Component, Net, NetClass, STANDARD_LAYER_STACKS
from pcb_tool.footprint_templates import generate_pads

board = Board(layers=STANDARD_LAYER_STACKS[4])
board.width = 40.0
board.height = 40.0

board.net_classes["Power"] = NetClass(name="Power", track_width=0.5)

pads = generate_pads("TQFP-32")
comp = Component(ref="U1", value="FPGA", footprint="TQFP-32",
                 position=(20, 20), rotation=0, pads=pads)
board.add_component(comp)

net = Net(name="VCC", code="1", track_width=0.5, net_class="Power")
net.add_connection("U1", "8")
board.add_net(net)
```

## Layer Names

| Layers | Names |
|--------|-------|
| 2 | `F.Cu`, `B.Cu` |
| 4 | `F.Cu`, `In1.Cu`, `In2.Cu`, `B.Cu` |
| 6 | `F.Cu`, `In1.Cu`, `In2.Cu`, `In3.Cu`, `In4.Cu`, `B.Cu` |

## Common Patterns

### Power/Ground Routing (4-layer)
```
Power nets: F.Cu (top layer)
Signal nets: In1.Cu, In2.Cu (inner layers)
Ground nets: B.Cu (bottom layer)
```

### Via Costs (encourage layer switching)
```python
via_costs = {
    "through": 2.0,  # Low = more vias
    "blind": 1.5,
    "buried": 1.0
}
```

### Net Class Setup
```python
# Power: Wide traces, larger vias
builder.net_class("Power", track_width=0.5, clearance=0.25, via_size=0.8, via_drill=0.4)

# Signal: Thin traces, smaller vias
builder.net_class("Signal", track_width=0.2, clearance=0.2, via_size=0.6, via_drill=0.3)
```
