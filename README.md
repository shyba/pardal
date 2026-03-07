# Pardal PCB

A command-line PCB Place & Route tool with Python API.

![Pardal PCB example](example.jpg)

## Features

- **Multi-layer Routing**: 2, 4, 6, and 8-layer boards with A* pathfinding and Z3 optimization
- **Python API**: Fluent `BoardBuilder` interface for programmatic board creation
- **Routing Strategies**: Pre-configured strategies for FPGA, mixed-signal, and simple boards
- **20+ Commands**: LOAD, SAVE, MOVE, ROTATE, FLIP, LOCK, UNLOCK, LIST, AUTOROUTE, STATS, CREATE, and more
- **CLI Modes**: Interactive REPL, batch file execution, single command execution
- **File Formats**: Reads KiCad netlist (.net) and PCB (.kicad_pcb), writes KiCad PCB
- **SDK Workflow**: Generate production-quality boards with library footprints, 0 DRC errors
- **Footprint Templates**: Auto-generates pads for common packages (QFP, SOIC, 0603, etc.)

## Dependencies

### Required
- **Python 3.10+**
- **KiCad 9.0+** installed (provides `pcbnew` Python module and `kicad-cli`)

Install on Debian/Ubuntu:
```bash
sudo apt install kicad kicad-packages3d python3-venv
```

### Python Environment Notes

Pardal uses **two Python environments** for different tasks:

| Task | Python | Why |
|------|--------|-----|
| Routing, board creation | venv (`./venv/bin/python`) | Pure Python, isolated dependencies |
| Finalization, KiCad SDK | System (`/usr/bin/python3`) | `pcbnew` module installed with KiCad |

**Most users only need venv** for routing. System Python is only needed for the `finalize` command that adds library footprints and copper zones.

Verify KiCad SDK is available:
```bash
/usr/bin/python3 -c "import pcbnew; print('KiCad', pcbnew.Version())"
```

## Installation

```bash
git clone <repo-url> pardal-pcb
cd pardal-pcb
python3 -m venv venv
./venv/bin/pip install -e .
```

For the `pardal` command shortcut (optional):
```bash
pip install -e .
pardal --help
```

## Python API Quick Start

Create a 4-layer FPGA board in ~20 lines:

```python
from pcb_tool.board_builder import fpga_board
from pcb_tool.routing_strategies import route_board
from pcb_tool.kicad_writer import KicadWriter

board = (fpga_board(layers=4, width=40, height=40)
    .component("U1", "TQFP-32", (20, 20), value="FPGA")
    .component("C1", "0603", (12, 20), value="100nF")
    .net("VCC", "Power", [("U1", "8"), ("C1", "1")])
    .net("GND", "Power", [("U1", "16"), ("C1", "2")])
    .build())

result = route_board(board, "fpga")
print(f"Routed {result.nets_routed}/{result.nets_total} nets")

KicadWriter().write(board, "board.kicad_pcb")
```

See [docs/PYTHON_API_GUIDE.md](docs/PYTHON_API_GUIDE.md) for complete API reference.

## Atopile Users - Quick Start

**If you have an atopile project**, use these commands:

```bash
# Set PARDAL_DIR to where pardal-pcb is located
PARDAL_DIR=/path/to/pardal-pcb

# After `ato build`, your files are at:
# build/builds/default/default/default.kicad_pcb  ← Has placed components
# build/builds/default/default/default.net        ← Netlist only

# Route the existing board (use .kicad_pcb to keep atopile's placement!)
PYTHONPATH=$PARDAL_DIR/venv/lib/python3.*/site-packages \
  /usr/bin/python3 -m pcb_tool.cli route \
  build/builds/default/default/default.kicad_pcb \
  -o board_routed.kicad_pcb

# Finalize for production (library footprints + GND zones)
/usr/bin/python3 -m pcb_tool.finalize \
  board_routed.kicad_pcb board_final.kicad_pcb

# Verify 0 DRC errors
kicad-cli pcb drc board_final.kicad_pcb
```

**Important**: Use `pardal route` on `.kicad_pcb`, NOT `pardal build` on `.net` - otherwise you lose atopile's placement!

## Quick Start (General)

```bash
# Install
pip install -e .

# Show available commands
pardal --help

# Build PCB from netlist with placement script (when starting from scratch)
pardal build project.net -p placement.txt -o board.kicad_pcb

# Run DRC check
pardal drc board.kicad_pcb

# Interactive mode
pardal repl
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `pardal build` | Load netlist, place components, optionally route, save PCB, run DRC |
| `pardal drc` | Run KiCad DRC check on existing PCB file |
| `pardal place` | Place components from netlist (no routing) |
| `pardal route` | Autoroute existing PCB file |
| `pardal repl` | Interactive REPL mode |

### Examples

```bash
# Full build with autorouting
pardal build project.net -p placement.txt -o board.kicad_pcb --route

# Build without DRC check
pardal build project.net -o board.kicad_pcb --no-drc

# Check DRC and save JSON report
pardal drc board.kicad_pcb -o report.json --format json

# Run batch commands
pardal repl --batch commands.txt
```

### Interactive Mode
```bash
./venv/bin/python -m pcb_tool
pcb> HELP
pcb> LOAD ../manual_temp_test/example.net
pcb> LIST COMPONENTS
pcb> MOVE U1 TO 10 20
pcb> AUTOROUTE ALL
pcb> SHOW BOARD
pcb> SAVE output.kicad_pcb
pcb> EXIT
```

### Batch Mode
```bash
./venv/bin/python -m pcb_tool --batch placement.txt
```

### Command Execution
```bash
./venv/bin/python -m pcb_tool --load example.net --exec "MOVE U1 TO 10 20" --exec "SAVE output.kicad_pcb"
```

## DRC Validation

**Important**: The internal `CHECK DRC` command performs basic connectivity checks only. For full DRC validation matching KiCad's standards, use `kicad-cli`:

```bash
kicad-cli pcb drc --output drc_report.txt board.kicad_pcb
```

This runs KiCad's complete DRC engine including clearance, copper pour, footprint, and electrical rule checks.

## SDK Workflow (Recommended)

For production-quality boards with proper footprints and 0 DRC errors, use the SDK-based workflow:

1. **Route board** using pardal-pcb's autorouter
2. **Regenerate with SDK** to get library footprints with full graphics/3D models
3. **Add zones** for copper pours
4. **Validate** with `kicad-cli pcb drc`

See `docs/SDK_WORKFLOW_GUIDE.md` for complete instructions.

## Documentation

- **[docs/PYTHON_API_GUIDE.md](docs/PYTHON_API_GUIDE.md)**: Complete Python API reference
- **[docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md)**: Command cheat sheet
- **[docs/PRODUCTION_WORKFLOW.md](docs/PRODUCTION_WORKFLOW.md)**: Routing to production guide
- **[docs/AI_INTEGRATION.md](docs/AI_INTEGRATION.md)**: Guide for AI assistants
- **[docs/AUTOROUTING_GUIDE.md](docs/AUTOROUTING_GUIDE.md)**: Autorouting internals
- **[docs/SDK_WORKFLOW_GUIDE.md](docs/SDK_WORKFLOW_GUIDE.md)**: KiCad SDK details
- **USAGE.md**: CLI command reference

## Testing

Run the full test suite:
```bash
./venv/bin/pytest tests/ -v
```

## Architecture

- **Command Pattern**: All operations as reversible command objects
- **Vertical Slices**: End-to-end features over horizontal layers
- **Clean Separation**: Data model, commands, parsers, I/O handlers

## Limitations

- **Linux only**: Footprint library paths assume standard KiCad installation at `/usr/share/kicad/footprints/`
- **KiCad 9+**: Requires KiCad 9.0 or newer for SDK compatibility
- **System Python for finalization**: The `finalize` command requires system Python with pcbnew (see Dependencies)

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

See [LICENSE](LICENSE) for the full license text.
