# Pardal PCB

A command-line PCB Place & Route tool.

## Features

- **17 Commands**: LOAD, SAVE, MOVE, ROTATE, FLIP, LOCK, UNLOCK, LIST (components/nets), SHOW BOARD, WHERE, UNDO, REDO, HISTORY, HELP, EXIT
- **Autorouting**: A* pathfinding with Z3 layer optimization for 2-layer boards, largely based on some of freerouting project features.
- **CLI Modes**: Interactive REPL, batch file execution (`--batch`), single command execution (`--exec`)
- **File Formats**: Reads KiCad netlist (.net), writes KiCad PCB (.kicad_pcb)
- **SDK Workflow**: Generate production-quality boards with library footprints, aiming at 0 DRC errors
- **Grid Visualization**: ASCII art board display with component positions and orientations
- **Undo/Redo**: Full command history with state management

## Dependencies

### Required
- **Python 3.10+** with virtual environment
- **KiCad 9.0+** installed (provides `pcbnew` Python module and `kicad-cli`)
- **kicad-packages3d** package for 3D model rendering in KiCad viewer

Install on Debian/Ubuntu:
```bash
sudo apt install kicad kicad-packages3d
```

### For SDK Workflow (Recommended)
The SDK workflow uses KiCad's Python API directly (system Python, not venv):
```bash
python3 -c "import pcbnew; print(pcbnew.Version())"
```

## Installation

No installation needed - uses virtual environment:

```bash
cd pardal-pcb
./venv/bin/python -m pcb_tool --help
```

## Quick Start

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

- **USAGE.md**: Complete command reference with examples
- **docs/AUTOROUTING_GUIDE.md**: Autorouting system guide
- **docs/SDK_WORKFLOW_GUIDE.md**: SDK workflow for production boards

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

- **2-layer boards only**: F.Cu and B.Cu layers supported
- **Linux paths**: Footprint library paths assume standard KiCad installation at `/usr/share/kicad/footprints/`
- **KiCad 9+**: Requires KiCad 9.0 or newer for SDK compatibility

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

See [LICENSE](LICENSE) for the full license text.
