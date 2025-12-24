# PCB Tool - Usage Guide (MVP1)

**Version**: 0.1.0 (MVP1)
**Date**: 2025-12-21

An AI-friendly command-line tool for PCB component placement and layout.

---

## Table of Contents

- [One-Shot Board Generation](#one-shot-board-generation)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Command Reference](#command-reference)
- [Example Workflows](#example-workflows)
- [Troubleshooting](#troubleshooting)

---

## One-Shot Board Generation

Generate a production-quality board with 0 DRC errors in a single command:

```bash
pardal build project.net -o board_final.kicad_pcb --route --finalize
```

This command:
1. Loads the netlist
2. Places components (auto-placement or via placement script)
3. Autoroutes all nets
4. Replaces simplified footprints with full KiCad library footprints
5. Adds GND copper zones on F.Cu and B.Cu
6. Runs DRC check

### Example with Placement Script

```bash
# Create placement.txt with component positions
pardal build project.net -p placement.txt -o board.kicad_pcb --route --finalize
```

### Requirements for --finalize

The `--finalize` flag requires:
- **System Python** with pcbnew (KiCad's Python module)
- Not venv Python (pcbnew is only available in system Python)

To run with system Python:

```bash
# Use system Python directly
/usr/bin/python3 -m pcb_tool.cli build project.net -o board.kicad_pcb --route --finalize
```

### What --finalize Does

The finalization process (SDK workflow):
1. **Extract** - Reads routing geometry (tracks, vias, net assignments)
2. **Rebuild** - Replaces footprints with KiCad library versions (full graphics, 3D models)
3. **Zones** - Adds GND copper zones on both layers and fills them

This workflow achieves 0 DRC errors on standard boards.

---

## Installation

### Prerequisites

- Python 3.10 or higher
- KiCad 9.0+ (for validation/DRC)
- atopile (optional, if building from .ato source)

### Install from Source

```bash
# Clone repository
git clone https://github.com/shyba/pardal
cd pardal

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install pcb-tool
pip install -e .
```

### Verify Installation

```bash
$ pcb-tool --version
pcb-tool 0.1.0 (MVP1)

$ pcb-tool --help
usage: pcb-tool [-h] [--load FILE] [--batch FILE] [--exec CMD] [--version]

PCB Place & Route Tool

optional arguments:
  -h, --help      show this help message and exit
  --load FILE     Load netlist or PCB file
  --batch FILE    Execute commands from file
  --exec CMD      Execute single command
  --version       show program's version number and exit
```

---

## CLI Commands

Pardal provides a unified CLI with subcommands:

```bash
pardal --help                    # Show all commands
pardal build --help              # Show build options
pardal drc --help                # Show DRC options
```

### Available Commands

| Command | Description |
|---------|-------------|
| `pardal build` | Build PCB: load netlist → place → route → save → DRC |
| `pardal drc` | Run KiCad DRC check on existing PCB |
| `pardal place` | Place components only (no routing) |
| `pardal route` | Autoroute existing PCB |
| `pardal repl` | Interactive REPL mode |

### Build Command

One-shot build from netlist to validated PCB:

```bash
# Basic build (placement only)
pardal build project.net -o board.kicad_pcb

# With placement script
pardal build project.net -p placement.txt -o board.kicad_pcb

# With autorouting
pardal build project.net -p placement.txt -o board.kicad_pcb --route

# Skip DRC check
pardal build project.net -o board.kicad_pcb --no-drc
```

### DRC Command

Run KiCad Design Rule Check:

```bash
# Basic DRC (text output)
pardal drc board.kicad_pcb

# JSON output for scripting
pardal drc board.kicad_pcb -o report.json --format json
```

### Interactive Mode

```bash
# Start REPL
pardal repl

# Run batch script
pardal repl --batch commands.txt
```

---

## Quick Start

### 1. Interactive Mode

Start the interactive shell:

```bash
$ pcb-tool
PCB Place & Route Tool v0.1.0
Type HELP for commands, EXIT to quit

pcb>
```

### 2. Load a Netlist

Load an atopile-generated netlist:

```bash
pcb> LOAD build/builds/default/default/default.net
OK: Loaded board with 15 components, 8 nets

pcb> LIST COMPONENTS
Components (15 total):
  R1: 10k @ (0.0, 0.0) 0° F.Cu
  R2: 47ohm @ (0.0, 0.0) 0° F.Cu
  C1: 100nF @ (0.0, 0.0) 0° F.Cu
  U1: RP2040 @ (0.0, 0.0) 0° F.Cu
  Q1: BSS84 @ (0.0, 0.0) 0° F.Cu
  ...
```

### 3. Place Components

Move components to desired positions:

```bash
pcb> MOVE U1 TO 50 40
OK: Moved U1 to (50.0, 40.0) rotation 0.0°

pcb> MOVE R1 TO 30 20 ROTATION 90
OK: Moved R1 to (30.0, 20.0) rotation 90.0°

pcb> ROTATE R2 TO 180
OK: Rotated R2 to 180.0°
```

### 4. View the Board

Show the board layout:

```bash
pcb> SHOW BOARD

Board: 100mm × 80mm | Layer: F.Cu | Components: 15
Scale: 1 char = 2mm

    0   10   20   30   40   50   60   70   80   90  100
  0 ┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
    │    │    │    │    │    │    │    │    │    │    │
 10 ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
    │    │    │    │[R1]│    │    │    │    │    │    │
 20 ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
    │    │    │    │ ↑  │    │    │    │    │    │    │
 30 ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
    │    │    │    │    │    │[U1]│    │    │    │    │
 40 ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
    │    │    │    │    │    │    │    │    │    │    │
 50 ├────┼────┼────┼[R2]│    │    │    │    │    │    │
    │    │    │    │ ←  │    │    │    │    │    │    │
 60 ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
    │    │    │    │    │    │    │    │    │    │    │
 70 └────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘

Legend: [Ref] = Component  ↑→↓← = Orientation
```

### 5. Save to KiCad

Export to KiCad PCB file:

```bash
pcb> SAVE output.kicad_pcb
OK: Saved to output.kicad_pcb

pcb> EXIT
Goodbye!
```

### 6. Open in KiCad

```bash
$ kicad output.kicad_pcb
```

The PCB opens in KiCad with all components placed at your specified positions!

---

## Command Reference

### State Management

#### LOAD

Load netlist or PCB file.

**Syntax:**
```
LOAD <filename>
```

**Examples:**
```
LOAD build/default.net
LOAD existing.kicad_pcb
LOAD /path/to/netlist.net
```

**Returns:**
```
OK: Loaded board with 15 components, 8 nets
ERROR: File not found: missing.net
ERROR: Parse error in file.net line 45: unexpected token
```

---

#### SAVE

Save current board to KiCad PCB file.

**Syntax:**
```
SAVE [filename]
```

**Examples:**
```
SAVE                    # Overwrites input file
SAVE output.kicad_pcb   # Save to new file
SAVE /tmp/test.kicad_pcb
```

**Returns:**
```
OK: Saved to output.kicad_pcb
ERROR: Permission denied writing to /path/to/file.kicad_pcb
```

---

#### UNDO

Revert last command(s).

**Syntax:**
```
UNDO [count]
```

**Examples:**
```
UNDO        # Undo last command
UNDO 3      # Undo last 3 commands
```

**Returns:**
```
OK: Undid "MOVE R1 TO 10.0 20.0"
OK: Undid 3 commands
ERROR: Nothing to undo
```

---

#### REDO

Reapply undone command(s).

**Syntax:**
```
REDO [count]
```

**Examples:**
```
REDO        # Redo last undone command
REDO 2      # Redo last 2 undone commands
```

**Returns:**
```
OK: Redid "MOVE R1 TO 10.0 20.0"
OK: Redid 2 commands
ERROR: Nothing to redo
```

---

#### HISTORY

Show command history.

**Syntax:**
```
HISTORY [count]
```

**Examples:**
```
HISTORY      # Show last 10 commands
HISTORY 20   # Show last 20 commands
```

**Returns:**
```
Command History (last 10):
  1: LOAD build/default.net
  2: MOVE R1 TO 10.0 20.0
  3: MOVE R2 TO 15.0 25.0
  4: ROTATE R1 TO 90.0
  5: SAVE output.kicad_pcb
  ...
```

---

### Component Placement

#### MOVE

Move component to new position.

**Syntax:**
```
MOVE <ref> TO <x> <y> [ROTATION <angle>]
```

**Parameters:**
- `ref`: Component reference (R1, U2, etc.)
- `x, y`: Position in millimeters
- `angle`: Rotation in degrees (optional)

**Examples:**
```
MOVE R1 TO 10 20
MOVE U1 TO 50.5 30.25 ROTATION 90
MOVE C1 TO 15 25 ROTATION 180
```

**Returns:**
```
OK: Moved R1 to (10.0, 20.0) rotation 0.0°
OK: Moved U1 to (50.5, 30.25) rotation 90.0°
ERROR: Component R99 not found
```

---

#### ROTATE

Rotate component.

**Syntax:**
```
ROTATE <ref> TO <angle>
ROTATE <ref> BY <delta>
```

**Parameters:**
- `ref`: Component reference
- `angle`: Absolute rotation (degrees)
- `delta`: Relative rotation (degrees)

**Examples:**
```
ROTATE R1 TO 90        # Set to 90°
ROTATE R1 BY 45        # Add 45° to current rotation
ROTATE R1 BY -90       # Subtract 90°
```

**Returns:**
```
OK: Rotated R1 to 90.0°
OK: Rotated R1 by 45.0° (new: 135.0°)
ERROR: Component R99 not found
```

---

#### FLIP

Move component to opposite layer.

**Syntax:**
```
FLIP <ref>
```

**Examples:**
```
FLIP R1     # F.Cu → B.Cu or vice versa
FLIP C2
```

**Returns:**
```
OK: Flipped R1 to B.Cu
OK: Flipped R1 to F.Cu
ERROR: Component R99 not found
```

---

#### LOCK / UNLOCK

Prevent/allow automatic movement.

**Syntax:**
```
LOCK <ref>
UNLOCK <ref>
```

**Examples:**
```
LOCK U1      # Prevent U1 from being moved
UNLOCK U1    # Allow U1 to be moved
```

**Returns:**
```
OK: Locked U1
OK: Unlocked U1
ERROR: Component R99 not found
```

---

### Query Commands

#### SHOW

Display board state.

**Syntax:**
```
SHOW BOARD
SHOW COMPONENT <ref>
SHOW NET <net_name>
```

**Examples:**
```
SHOW BOARD              # Show full board layout
SHOW COMPONENT U1       # Show U1 details
SHOW NET VCC            # Show VCC net routing
```

**Output:**
```
# SHOW BOARD
Board: 100mm × 80mm | Layer: F.Cu | Components: 15
[ASCII board rendering]

# SHOW COMPONENT U1
Component: U1 (RP2040)
Position: (50.0, 40.0) mm
Rotation: 0.0°
Layer: F.Cu
Footprint: Package_QFP:LQFP-56_7x7mm_P0.4mm
Pads: 56
Locked: no

# SHOW NET VCC
Net: VCC (net_id=1)
Class: POWER
Pins: 12 (U1.1, U1.44, C1.1, C2.1, ...)
Routing: Not routed (12 airwires)
```

---

#### LIST

List components or nets.

**Syntax:**
```
LIST COMPONENTS [GROUP <group>]
LIST NETS [CLASS <class>]
LIST GROUPS
```

**Examples:**
```
LIST COMPONENTS                  # All components
LIST COMPONENTS GROUP channels   # Group filter
LIST NETS                        # All nets
LIST NETS CLASS POWER            # Power nets only
LIST GROUPS                      # All groups
```

**Output:**
```
# LIST COMPONENTS
Components (15 total):
  R1: 10k @ (10.0, 20.0) 90° F.Cu
  R2: 47ohm @ (15.0, 25.0) 0° F.Cu
  C1: 100nF @ (20.0, 30.0) 0° F.Cu
  ...

# LIST NETS CLASS POWER
Power Nets (3 total):
  1: VCC (12 pins, unrouted)
  2: VDD_3V3 (8 pins, unrouted)
  3: GND (15 pins, unrouted)
```

---

#### WHERE

Find component or net location.

**Syntax:**
```
WHERE <ref>
WHERE NET <net_name>
```

**Examples:**
```
WHERE R1
WHERE NET VCC
```

**Output:**
```
# WHERE R1
R1: position (10.0, 20.0) rotation 90.0° layer F.Cu
    locked: no
    footprint: Resistor_SMD:R_0402
    value: 10k

# WHERE NET VCC
VCC: net_id=1 class=POWER
     pins: 12 (U1.1, U1.44, C1.1, ...)
     routed: 0 segments, 0 vias
     unrouted: 12 connections
```

---

### Help & Control

#### HELP

Show command help.

**Syntax:**
```
HELP [command]
```

**Examples:**
```
HELP           # Show all commands
HELP MOVE      # Show MOVE syntax
HELP ROTATE    # Show ROTATE syntax
```

---

#### EXIT / QUIT

Exit the REPL.

**Syntax:**
```
EXIT
QUIT
```

**Behavior:**
- Prompts to save if there are unsaved changes
- Exits immediately if no changes

```
pcb> EXIT
Unsaved changes. Save before exit? (y/n): y
OK: Saved to output.kicad_pcb
Goodbye!
```

---

## Example Workflows

### Workflow 1: Place Components for LED Circuit

```bash
$ pcb-tool

# Load netlist
pcb> LOAD /path/to/led_circuit/build/default.net
OK: Loaded board with 3 components, 2 nets

# See what we have
pcb> LIST COMPONENTS
Components (3 total):
  R1: 330ohm @ (0.0, 0.0) 0° F.Cu
  LED1: LED_0805 @ (0.0, 0.0) 0° F.Cu
  J1: Conn_01x02 @ (0.0, 0.0) 0° F.Cu

# Place components in a line
pcb> MOVE J1 TO 10 30          # Connector on left
OK: Moved J1 to (10.0, 30.0) rotation 0.0°

pcb> MOVE R1 TO 25 30          # Resistor in middle
OK: Moved R1 to (25.0, 30.0) rotation 0.0°

pcb> MOVE LED1 TO 35 30        # LED on right
OK: Moved LED1 to (35.0, 30.0) rotation 0.0°

# Rotate resistor vertical
pcb> ROTATE R1 TO 90
OK: Rotated R1 to 90.0°

# View result
pcb> SHOW BOARD

Board: 50mm × 40mm | Components: 3
    0   10   20   30   40   50
  0 ┌────┬────┬────┬────┬────┐
    │    │    │    │    │    │
 20 ├────┼────┼────┼────┼────┤
    │    │[J1]│    │    │    │
 30 ├────┼────┼─R1─┼[LED]    │
    │    │    │ ↑  │    │    │
 40 └────┴────┴────┴────┴────┘

# Save
pcb> SAVE led_circuit.kicad_pcb
OK: Saved to led_circuit.kicad_pcb

pcb> EXIT
```

---

### Workflow 2: Organize by Groups

For designs with atopile groups (e.g., `channels[0]`, `channels[1]`):

```bash
pcb> LOAD build/mosfet_array.net
OK: Loaded board with 48 components, 32 nets

# See groups
pcb> LIST GROUPS
Groups (4 total):
  channels[0]: 12 components
  channels[1]: 12 components
  channels[2]: 12 components
  channels[3]: 12 components

# Place first channel
pcb> LIST COMPONENTS GROUP channels[0]
Components in group 'channels[0]' (12):
  R1: 10k @ (0.0, 0.0) 0° F.Cu
  R2: 47ohm @ (0.0, 0.0) 0° F.Cu
  Q1: BSS84 @ (0.0, 0.0) 0° F.Cu
  ...

# Move components one by one
pcb> MOVE R1 TO 10 10
pcb> MOVE R2 TO 15 10
pcb> MOVE Q1 TO 20 10
# ... etc

# Or use batch file (see next section)
```

---

### Workflow 3: Batch Commands

Create a placement script `placement.txt`:

```
# placement.txt - Automatic placement script
LOAD build/default.net

# Place power components
MOVE U1 TO 50 40
MOVE C1 TO 40 35
MOVE C2 TO 60 35
MOVE C3 TO 50 30

# Place channel 0
MOVE R1 TO 20 20
MOVE R2 TO 25 20
MOVE Q1 TO 30 20

# Place channel 1
MOVE R3 TO 20 40
MOVE R4 TO 25 40
MOVE Q2 TO 30 40

# Save result
SAVE output.kicad_pcb
```

Execute batch:

```bash
$ pcb-tool --batch placement.txt
Executing commands from placement.txt...
OK: Loaded board with 12 components, 8 nets
OK: Moved U1 to (50.0, 40.0) rotation 0.0°
OK: Moved C1 to (40.0, 35.0) rotation 0.0°
...
OK: Saved to output.kicad_pcb
Executed 15 commands successfully
```

---

### Workflow 4: Interactive Undo/Redo

```bash
pcb> MOVE R1 TO 10 20
OK: Moved R1 to (10.0, 20.0) rotation 0.0°

pcb> MOVE R1 TO 15 25
OK: Moved R1 to (15.0, 25.0) rotation 0.0°

pcb> MOVE R1 TO 20 30
OK: Moved R1 to (20.0, 30.0) rotation 0.0°

# Oops, went too far
pcb> UNDO
OK: Undid "MOVE R1 TO 20.0 30.0"

pcb> WHERE R1
R1: position (15.0, 25.0) rotation 0.0° layer F.Cu

# Actually, I liked it at 20,30
pcb> REDO
OK: Redid "MOVE R1 TO 20.0 30.0"

pcb> WHERE R1
R1: position (20.0, 30.0) rotation 0.0° layer F.Cu
```

---

### Workflow 5: Single Command Execution

For scripting or CI/CD:

```bash
# Load and show board info
$ pcb-tool --load build/default.net --exec "LIST COMPONENTS"
Components (15 total):
  R1: 10k @ (0.0, 0.0) 0° F.Cu
  R2: 47ohm @ (0.0, 0.0) 0° F.Cu
  ...

# Move component via script
$ pcb-tool --load input.kicad_pcb --exec "MOVE R1 TO 10 20" --exec "SAVE output.kicad_pcb"
OK: Loaded board with 15 components, 8 nets
OK: Moved R1 to (10.0, 20.0) rotation 0.0°
OK: Saved to output.kicad_pcb
```

---

## Troubleshooting

### Common Issues

#### "File not found" error

```
pcb> LOAD myboard.net
ERROR: File not found: myboard.net
```

**Solution:** Use absolute or relative path:
```
pcb> LOAD ./build/builds/default/default/default.net
pcb> LOAD /path/to/project/build/default.net
```

---

#### "Component not found" error

```
pcb> MOVE R99 TO 10 20
ERROR: Component R99 not found
```

**Solution:** Check component exists:
```
pcb> LIST COMPONENTS
pcb> WHERE R1    # Check exact reference
```

---

#### "Parse error" when loading

```
pcb> LOAD broken.net
ERROR: Parse error in broken.net line 45: unexpected token '}'
```

**Solution:**
- Ensure file is valid KiCad netlist format
- Regenerate from atopile: `ato build`
- Check file isn't corrupted

---

#### Board doesn't render properly

```
pcb> SHOW BOARD
[Garbled or tiny output]
```

**Solution:**
- Ensure terminal is at least 80 columns wide
- Try maximizing terminal window
- Components at (0,0) won't show - move them first

---

#### Changes not saved

```
pcb> MOVE R1 TO 10 20
OK: Moved R1 to (10.0, 20.0) rotation 0.0°

pcb> EXIT
Goodbye!

# Reopening shows R1 at (0,0)!
```

**Solution:** Save before exiting:
```
pcb> SAVE output.kicad_pcb
pcb> EXIT
```

Or respond to the save prompt:
```
pcb> EXIT
Unsaved changes. Save before exit? (y/n): y
```

---

### Debug Mode

Enable verbose logging:

```bash
$ pcb-tool --verbose
```

Or set environment variable:

```bash
$ export PCB_TOOL_DEBUG=1
$ pcb-tool
```

Logs are written to `.pcb_tool.log` in the current directory.

---

## Limitations (MVP1)

### Not Yet Implemented

- ✅ Routing commands (ROUTE, VIA, AUTOROUTE)
- ❌ Auto-placement algorithm
- ✅ Auto-routing algorithm (A* pathfinder + Z3 optimizer)
- ✅ DRC checking integration (via kicad-cli)
- ❌ Net airwire visualization
- ❌ Footprint library resolution
- ❌ Component detail view
- ❌ Multi-layer visualization

### Known Issues

- Board rendering assumes 2-layer boards (F.Cu, B.Cu)
- Large boards (>50 components) may render poorly
- Component rotation arrows only show 4 directions (0°, 90°, 180°, 270°)

---

## What's Next (MVP2)

Planned features for MVP2:

- ✅ Routing commands (ROUTE, VIA, DELETE_ROUTE)
- ✅ Net visualization (SHOW NET, SHOW AIRWIRES)
- ✅ DRC integration (CHECK DRC)
- ✅ Enhanced board rendering (show traces, vias)
- ✅ Footprint library resolution
- ✅ Component detail view with pads
- ✅ Group operations (GROUP_MOVE, ARRANGE)

---

## Getting Help

- **Documentation**: See `docs/` directory
- **Examples**: See the Example Workflows section above
- **Issues**: https://github.com/shyba/pardal/issues
- **In-tool help**: `HELP` command

---

## License

MIT License - See LICENSE file for details

---

**End of Usage Guide**
