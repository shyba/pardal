# Documentation and API Simplification Plan

## Goal
Enable smaller/less capable models to achieve FPGA-quality designs by:
1. Reducing boilerplate code required
2. Adding missing REPL commands
3. Creating comprehensive documentation with examples

## Current State Analysis

### What the FPGA Design Required (356 lines of Python)
- Manual pad positioning for 32-pin IC (~50 lines)
- Net class definitions (not available in REPL)
- Manual net creation with pin connections
- Layer assignment strategy (not available in REPL)
- Via cost tuning (not available in REPL)
- Statistics collection (not available in REPL)

### Key Gaps Identified

| Feature | REPL | Python | Priority |
|---------|------|--------|----------|
| Board dimensions | ❌ | ✅ | High |
| Net classes | ❌ | ✅ | High |
| Layer preferences | ❌ | ✅ | High |
| Via costs | ❌ | ✅ | Medium |
| Footprint templates | ❌ | ❌ | High |
| Routing statistics | ❌ | ✅ | Medium |

---

## Phase 1: Code Simplification (Reduce Boilerplate)

### 1.1 Add Footprint Templates Library

**File:** `pcb_tool/footprint_templates.py`

Create pre-defined footprint templates with correct pad positions:

```python
FOOTPRINT_TEMPLATES = {
    # QFP packages
    "TQFP-32_7x7mm_P0.8mm": {
        "pads": 32,
        "pitch": 0.8,
        "body": (7.0, 7.0),
        "pad_size": (0.5, 1.2),
        "generate": generate_qfp_pads,  # Auto-generates pad positions
    },

    # SMD passives
    "C_0603_1608Metric": {
        "pads": 2,
        "pad_positions": [(-0.8, 0), (0.8, 0)],
        "pad_size": (0.9, 0.9),
    },

    # Headers
    "PinHeader_2x05_P1.27mm": {
        "pads": 10,
        "rows": 2,
        "cols": 5,
        "pitch": 1.27,
        "generate": generate_header_pads,
    },
}

def create_component_with_pads(ref, value, footprint, position, rotation=0):
    """Create component with auto-generated pads from template."""
    template = FOOTPRINT_TEMPLATES.get(footprint)
    if template:
        pads = generate_pads_from_template(template)
        return Component(ref=ref, value=value, footprint=footprint,
                        position=position, rotation=rotation, pads=pads)
    raise ValueError(f"Unknown footprint: {footprint}")
```

**Impact:** Reduces 50+ lines of manual pad positioning to 1 line.

### 1.2 Add Board Builder Helper Class

**File:** `pcb_tool/board_builder.py`

```python
class BoardBuilder:
    """Fluent API for building boards with less boilerplate."""

    def __init__(self, layers=2, width=100, height=100):
        self.board = Board(layers=STANDARD_LAYER_STACKS[layers])
        self.board.width = width
        self.board.height = height

    def add_net_class(self, name, track_width, clearance=0.2):
        """Add a net class with common defaults."""
        self.board.net_classes[name] = NetClass(
            name=name, track_width=track_width, clearance=clearance
        )
        return self

    def add_ic(self, ref, footprint, position, value="IC"):
        """Add IC with auto-generated pads from footprint template."""
        comp = create_component_with_pads(ref, value, footprint, position)
        self.board.add_component(comp)
        return self

    def add_passive(self, ref, footprint, position, value="", rotation=0):
        """Add passive component (R, C, L)."""
        comp = create_component_with_pads(ref, value, footprint, position, rotation)
        self.board.add_component(comp)
        return self

    def add_power_net(self, name, *connections):
        """Add power net with 0.5mm traces."""
        net = Net(name=name, code=str(len(self.board.nets)+1),
                 track_width=0.5, net_class="Power")
        for ref, pin in connections:
            net.add_connection(ref, pin)
        self.board.add_net(net)
        return self

    def add_signal_net(self, name, *connections):
        """Add signal net with 0.2mm traces."""
        net = Net(name=name, code=str(len(self.board.nets)+1),
                 track_width=0.2, net_class="Signal")
        for ref, pin in connections:
            net.add_connection(ref, pin)
        self.board.add_net(net)
        return self

    def route_all(self, strategy="4layer"):
        """Route all nets with sensible defaults for layer count."""
        if strategy == "4layer":
            return route_4layer_board(self.board)
        elif strategy == "2layer":
            return route_2layer_board(self.board)

    def build(self):
        return self.board
```

**Impact:** FPGA design reduces from 356 lines to ~50 lines:

```python
board = (BoardBuilder(layers=4, width=40, height=40)
    .add_net_class("Power", track_width=0.5)
    .add_net_class("Signal", track_width=0.2)
    .add_ic("U1", "TQFP-32_7x7mm_P0.8mm", (20, 20), "FPGA")
    .add_passive("C1", "C_0603_1608Metric", (12, 20), "100nF")
    .add_passive("C2", "C_0603_1608Metric", (28, 20), "100nF")
    .add_power_net("VCC", ("U1", "8"), ("U1", "24"), ("C1", "1"), ("C2", "1"))
    .add_power_net("GND", ("U1", "16"), ("U1", "32"), ("C1", "2"), ("C2", "2"))
    .add_signal_net("TMS", ("J1", "2"), ("U1", "1"))
    .route_all("4layer")
    .build())
```

### 1.3 Add Routing Strategy Presets

**File:** `pcb_tool/routing_strategies.py`

```python
def route_4layer_board(board):
    """Standard 4-layer routing strategy.

    Layer assignment:
    - F.Cu: Power (VCC) + short signals
    - In1.Cu: Horizontal signals
    - In2.Cu: Vertical signals
    - B.Cu: Ground plane
    """
    via_costs = {"through": 2.0, "blind": 1.5, "buried": 1.0}

    # Classify nets
    power_nets = [n for n in board.nets if n.upper() in ["VCC", "VDD", "+12V", "+5V", "+3V3"]]
    gnd_nets = [n for n in board.nets if n.upper() in ["GND", "GROUND", "VSS"]]
    signal_nets = [n for n in board.nets if n not in power_nets + gnd_nets]

    # Route power on F.Cu
    for net in power_nets:
        AutoRouteCommand(net_name=net, prefer_layer="F.Cu", via_costs=via_costs).execute(board)

    # Distribute signals across inner layers
    for i, net in enumerate(signal_nets):
        layer = "In1.Cu" if i % 2 == 0 else "In2.Cu"
        AutoRouteCommand(net_name=net, prefer_layer=layer, via_costs=via_costs).execute(board)

    # Route GND on B.Cu (ground plane)
    for net in gnd_nets:
        AutoRouteCommand(net_name=net, prefer_layer="B.Cu", via_costs=via_costs).execute(board)

    return board
```

---

## Phase 2: New REPL Commands

### 2.1 SET BOARD Command

```
SET BOARD WIDTH <mm>
SET BOARD HEIGHT <mm>
SET BOARD LAYERS <2|4|6>
```

### 2.2 SET NETCLASS Command (Enhanced)

```
SET NETCLASS <name> WIDTH <mm> [CLEARANCE <mm>] [VIA <mm>]
ASSIGN NET <net_name> TO CLASS <class_name>
```

### 2.3 AUTOROUTE Enhancement

```
AUTOROUTE ALL STRATEGY <2layer|4layer|dense>
AUTOROUTE NET <name> LAYER <layer> [VIA_COST <cost>]
```

### 2.4 STATS Command

```
STATS                    # Show routing statistics
STATS LAYERS             # Layer utilization
STATS NETS               # Per-net details
```

### 2.5 CREATE Commands

```
CREATE NET <name> CLASS <class_name>
CREATE NET <name> WIDTH <mm>
CONNECT <net_name> <ref>.<pin> [<ref>.<pin> ...]
```

---

## Phase 3: Documentation

### 3.1 New Documentation Files

#### `docs/PYTHON_API_GUIDE.md`
- When to use Python vs REPL
- Import statements and setup
- Data model overview (Board, Component, Net, Pad)
- Complete FPGA example walkthrough
- Common patterns and templates

#### `docs/QUICK_REFERENCE.md`
- One-page cheat sheet
- All commands with syntax
- All Python classes with constructors
- Common footprint templates

#### `docs/EXAMPLES/`
- `simple_2layer.py` - Basic 2-layer board
- `fpga_4layer.py` - Documented FPGA example
- `power_board.py` - High-current design
- `mixed_signal.py` - Analog + digital

### 3.2 Inline Documentation

Add comprehensive docstrings to all classes:

```python
class BoardBuilder:
    """Fluent API for building PCB boards with minimal boilerplate.

    This class simplifies board creation for AI/automation workflows
    by providing sensible defaults and template-based component creation.

    Example - 4-Layer FPGA Board:
        >>> board = (BoardBuilder(layers=4, width=40, height=40)
        ...     .add_net_class("Power", track_width=0.5)
        ...     .add_net_class("Signal", track_width=0.2)
        ...     .add_ic("U1", "TQFP-32_7x7mm_P0.8mm", (20, 20))
        ...     .add_power_net("VCC", ("U1", "8"), ("C1", "1"))
        ...     .route_all("4layer")
        ...     .build())

    Example - Simple 2-Layer Board:
        >>> board = (BoardBuilder(layers=2)
        ...     .add_passive("R1", "R_0805", (10, 10))
        ...     .add_passive("R2", "R_0805", (20, 10))
        ...     .add_signal_net("SIG", ("R1", "1"), ("R2", "1"))
        ...     .route_all("2layer")
        ...     .build())
    """
```

### 3.3 AI-Focused Documentation Section

**File:** `docs/AI_INTEGRATION.md`

```markdown
# Using Pardal-PCB with AI Models

## Quick Start for AI Agents

### Minimum Viable Board (10 lines)
```python
from pcb_tool import BoardBuilder

board = (BoardBuilder(layers=2)
    .add_passive("R1", "R_0805", (10, 10), "10k")
    .add_passive("R2", "R_0805", (20, 10), "10k")
    .add_signal_net("SIG", ("R1", "1"), ("R2", "1"))
    .route_all()
    .save("board.kicad_pcb"))
```

### Common Patterns

1. **Power Distribution**
   - Use `add_power_net()` for VCC, +12V, etc.
   - Power nets get 0.5mm traces automatically

2. **Signal Routing**
   - Use `add_signal_net()` for data signals
   - Signal nets get 0.2mm traces automatically

3. **4-Layer Strategy**
   - F.Cu: Power rails
   - In1.Cu/In2.Cu: Signals (alternating)
   - B.Cu: Ground plane

### Footprint Quick Reference
| Package | Template Name | Pads |
|---------|--------------|------|
| 0603 SMD | C_0603_1608Metric | 2 |
| 0805 SMD | R_0805_2012Metric | 2 |
| TQFP-32 | TQFP-32_7x7mm_P0.8mm | 32 |
| 2x5 Header | PinHeader_2x05_P1.27mm | 10 |
```

---

## Phase 4: Implementation Priority

### High Priority (Week 1)
1. [ ] Create `footprint_templates.py` with common packages
2. [ ] Create `BoardBuilder` class
3. [ ] Add `route_4layer_board()` strategy
4. [ ] Write `docs/PYTHON_API_GUIDE.md`
5. [ ] Write `docs/QUICK_REFERENCE.md`

### Medium Priority (Week 2)
1. [ ] Add `SET BOARD` REPL commands
2. [ ] Add `STATS` REPL command
3. [ ] Add `CREATE NET` / `CONNECT` commands
4. [ ] Enhance `AUTOROUTE` with strategy parameter
5. [ ] Write `docs/AI_INTEGRATION.md`

### Lower Priority (Week 3)
1. [ ] Add more footprint templates (QFN, BGA, SOT-23, etc.)
2. [ ] Add `route_2layer_board()` strategy
3. [ ] Create example files in `docs/EXAMPLES/`
4. [ ] Add interactive tutorial mode

---

## Success Metrics

### Before (Current State)
- FPGA design: **356 lines** of Python
- Manual pad positioning: **50+ lines**
- No REPL support for net classes, layer preferences
- Documentation: REPL-focused only

### After (Target State)
- FPGA design: **~50 lines** with BoardBuilder
- Pad positioning: **0 lines** (auto-generated)
- Full REPL support for all features
- Documentation: Complete Python API guide + AI integration docs

### Validation
A smaller model should be able to:
1. Create a 4-layer board with power/signal routing
2. Use appropriate trace widths for power vs signals
3. Achieve 0 DRC errors on first attempt
4. Do so with <100 lines of code or <20 REPL commands

---

## Files to Create/Modify

### New Files
- `pcb_tool/footprint_templates.py`
- `pcb_tool/board_builder.py`
- `pcb_tool/routing_strategies.py`
- `pcb_tool/commands/board_config.py` (SET BOARD, STATS)
- `pcb_tool/commands/net_creation.py` (CREATE NET, CONNECT)
- `docs/PYTHON_API_GUIDE.md`
- `docs/QUICK_REFERENCE.md`
- `docs/AI_INTEGRATION.md`
- `docs/EXAMPLES/simple_2layer.py`
- `docs/EXAMPLES/fpga_4layer.py`

### Modified Files
- `pcb_tool/commands/__init__.py` - Export new commands
- `pcb_tool/command_parser.py` - Register new commands
- `pcb_tool/__init__.py` - Export BoardBuilder
- `README.md` - Add Python SDK section
- `USAGE.md` - Add new commands

---

## Appendix: FPGA Design Before/After

### Before (Current - 356 lines)
```python
# 50+ lines of manual pad positioning
pad_positions = [
    ("1", (-3.5, -2.8)), ("2", (-3.5, -2.0)), ...
]
for pad_num, offset in pad_positions:
    ic.pads.append(Pad(number=int(pad_num), position_offset=offset, ...))

# Manual net creation
vcc = Net(name="VCC", code="1", track_width=0.5, net_class="Power")
vcc.add_connection("J2", "1")
vcc.add_connection("U1", "8")
# ... 50 more lines
```

### After (Target - ~50 lines)
```python
from pcb_tool import BoardBuilder

board = (BoardBuilder(layers=4, width=40, height=40)
    .add_net_class("Power", 0.5)
    .add_net_class("Signal", 0.2)

    # Components (pads auto-generated)
    .add_ic("U1", "TQFP-32_7x7mm_P0.8mm", (20, 20), "FPGA")
    .add_passive("C1", "C_0603", (12, 20), "100nF")
    .add_passive("C2", "C_0603", (28, 20), "100nF")
    .add_passive("C3", "C_0603", (20, 12), "100nF", rotation=90)
    .add_passive("C4", "C_0603", (20, 28), "100nF", rotation=90)
    .add_header("J1", "PinHeader_2x05_P1.27mm", (5, 20), "JTAG")
    .add_header("J2", "PinHeader_1x02_P2.54mm", (35, 20), "PWR")

    # Nets (connections as tuples)
    .add_power_net("VCC", ("J2","1"), ("U1","8"), ("U1","24"),
                   ("C1","1"), ("C2","1"), ("C3","1"), ("C4","1"))
    .add_power_net("GND", ("J2","2"), ("U1","16"), ("U1","32"),
                   ("C1","2"), ("C2","2"), ("C3","2"), ("C4","2"))
    .add_signal_net("TMS", ("J1","2"), ("U1","1"))
    .add_signal_net("TCK", ("J1","4"), ("U1","2"))
    .add_signal_net("TDI", ("J1","8"), ("U1","3"))
    .add_signal_net("TDO", ("J1","6"), ("U1","4"))
    .add_signal_net("SIG1", ("U1","17"), ("U1","5"))
    .add_signal_net("GPIO1", ("U1","9"), ("U1","25"))
    .add_signal_net("GPIO2", ("U1","10"), ("U1","26"))

    # Route and build
    .route_all("4layer")
    .build())

# Save
from pcb_tool import KicadWriter
KicadWriter().write(board, "fpga_board.kicad_pcb")
```
