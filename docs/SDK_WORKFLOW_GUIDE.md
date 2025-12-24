# SDK Workflow Guide

Complete guide for generating production-quality PCB files using KiCad's Python SDK.

## Prerequisites

### System Requirements
- **KiCad 9.0+** with Python bindings
- **System Python 3** (not virtualenv - pcbnew requires system install)
- **kicad-packages3d** package for 3D models

### Installation (Debian/Ubuntu)
```bash
sudo apt install kicad kicad-packages3d python3
```

### Verify Installation
```bash
python3 -c "import pcbnew; print('KiCad', pcbnew.Version())"
```

## Overview

The SDK workflow converts an autorouted board into a production-ready file:

```
Autorouted Board -> Extract Data -> Build with Library FPs -> Add Zones -> DRC-Clean Board
     (pardal)          (JSON)         (SDK footprints)       (copper pour)    (0 errors)
```

**Why separate phases?** KiCad's SWIG Python bindings have memory management issues when combining board loading and creation. Running separate processes avoids segfaults.

## Step-by-Step Workflow

### Step 1: Autoroute with pardal-pcb

```bash
cd pardal-pcb
./venv/bin/python -m pcb_tool
pcb> LOAD ../project/board.net
pcb> AUTOROUTE ALL
pcb> SAVE ../project/board_routed.kicad_pcb
pcb> EXIT
```

### Step 2: Extract Board Data

Create `extract_board_data.py`:

```python
#!/usr/bin/env python3
"""Extract board data to JSON (Phase 1)."""
import json
import pcbnew

def extract_board_data(input_path: str, output_json: str):
    board = pcbnew.LoadBoard(input_path)

    data = {
        'net_names': [],
        'pad_nets': {},      # "REF:PAD" -> net_name
        'footprints': [],
        'tracks': [],
        'edges': [],
    }

    # Extract nets
    net_names = set()
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname():
                net_names.add(pad.GetNetname())
    for track in board.GetTracks():
        if track.GetNetname():
            net_names.add(track.GetNetname())
    data['net_names'] = list(net_names)

    # Extract pad-to-net mapping
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            if pad.GetNetname():
                data['pad_nets'][f"{ref}:{pad.GetNumber()}"] = pad.GetNetname()

    # Extract footprint info with pad 1 position for alignment
    for fp in board.GetFootprints():
        pos = fp.GetPosition()
        pad1_pos = pos
        for pad in fp.Pads():
            if pad.GetNumber() == '1':
                pad1_pos = pad.GetPosition()
                break

        data['footprints'].append({
            'fp_name': str(fp.GetFPID().GetLibItemName()),
            'ref': fp.GetReference(),
            'value': fp.GetValue(),
            'pos_x': pcbnew.ToMM(pos.x),
            'pos_y': pcbnew.ToMM(pos.y),
            'pad1_x': pcbnew.ToMM(pad1_pos.x),
            'pad1_y': pcbnew.ToMM(pad1_pos.y),
            'orientation': fp.GetOrientationDegrees(),
            'layer': fp.GetLayer(),
        })

    # Extract tracks
    for track in board.GetTracks():
        is_via = isinstance(track, pcbnew.PCB_VIA)
        info = {
            'is_via': is_via,
            'net_name': track.GetNetname(),
            'width': track.GetWidth(),
            'layer': track.GetLayer(),
        }
        if is_via:
            pos = track.GetPosition()
            info['pos_x'] = pos.x
            info['pos_y'] = pos.y
            info['drill'] = track.GetDrill()
            info['via_type'] = int(track.GetViaType())
        else:
            info['start_x'] = track.GetStart().x
            info['start_y'] = track.GetStart().y
            info['end_x'] = track.GetEnd().x
            info['end_y'] = track.GetEnd().y
        data['tracks'].append(info)

    # Extract edges
    for drawing in board.GetDrawings():
        if drawing.GetLayer() == pcbnew.Edge_Cuts:
            data['edges'].append({
                'shape': int(drawing.GetShape()),
                'start_x': drawing.GetStart().x,
                'start_y': drawing.GetStart().y,
                'end_x': drawing.GetEnd().x,
                'end_y': drawing.GetEnd().y,
                'width': drawing.GetWidth(),
            })

    with open(output_json, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Extracted {len(data['footprints'])} footprints, {len(data['tracks'])} tracks")

if __name__ == '__main__':
    import sys
    input_file = sys.argv[1] if len(sys.argv) > 1 else 'board_routed.kicad_pcb'
    output_file = sys.argv[2] if len(sys.argv) > 2 else '/tmp/board_data.json'
    extract_board_data(input_file, output_file)
```

Run: `python3 extract_board_data.py [input.kicad_pcb] [output.json]`

**Verify extraction:**
```bash
python3 -c "import json; d=json.load(open('/tmp/board_data.json')); print(f'Extracted: {len(d[\"footprints\"])} footprints, {len(d[\"tracks\"])} tracks, {len(d[\"net_names\"])} nets')"
```

### Step 2.5: Inspect Footprints (Important!)

Before proceeding, check which footprints your board uses:

```bash
python3 -c "import json; print('\n'.join(sorted(set(fp['fp_name'] for fp in json.load(open('/tmp/board_data.json'))['footprints']))))"
```

Example output:
```
C_0805_2012Metric
CP_Radial_D6.3mm_P2.50mm
D_DO-41_SOD81_P10.16mm_Horizontal
PinHeader_1x03_P2.54mm_Vertical
R_0805_2012Metric
TO-220-3_Vertical
```

**Each footprint must have a mapping in `FOOTPRINT_LIBS` in Step 3.** If any are missing, add them before proceeding. See [Finding Footprint Libraries](#finding-footprint-libraries) below.

### Step 3: Build with Library Footprints

Create `build_board_from_json.py`:

```python
#!/usr/bin/env python3
"""Build board with library footprints (Phase 2)."""
import json
import pcbnew

# Map footprint names to library paths
# Add your footprints here
FOOTPRINT_LIBS = {
    'R_0805_2012Metric': '/usr/share/kicad/footprints/Resistor_SMD.pretty',
    'C_0805_2012Metric': '/usr/share/kicad/footprints/Capacitor_SMD.pretty',
    'TO-220-3_Vertical': '/usr/share/kicad/footprints/Package_TO_SOT_THT.pretty',
    'D_DO-41_SOD81_P10.16mm_Horizontal': '/usr/share/kicad/footprints/Diode_THT.pretty',
    'CP_Radial_D6.3mm_P2.50mm': '/usr/share/kicad/footprints/Capacitor_THT.pretty',
    'PinHeader_1x03_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',
    'PinHeader_1x07_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',
}

def build_board(input_json: str, output_path: str):
    with open(input_json) as f:
        data = json.load(f)

    board = pcbnew.BOARD()
    io = pcbnew.PCB_IO_KICAD_SEXPR()

    # Create nets
    for net_name in data['net_names']:
        board.Add(pcbnew.NETINFO_ITEM(board, net_name))

    # Add footprints from library
    for info in data['footprints']:
        lib_path = FOOTPRINT_LIBS.get(info['fp_name'])
        if not lib_path:
            print(f"Warning: No library for {info['fp_name']} ({info['ref']})")
            continue

        try:
            fp = io.FootprintLoad(lib_path, info['fp_name'])
        except Exception as e:
            print(f"Error loading {info['fp_name']}: {e}")
            continue

        # Find pad 1 offset in library footprint
        lib_pad1_x, lib_pad1_y = 0, 0
        for pad in fp.Pads():
            if pad.GetNumber() == '1':
                lib_pad1_x = pcbnew.ToMM(pad.GetPosition().x)
                lib_pad1_y = pcbnew.ToMM(pad.GetPosition().y)
                break

        # Position by pad 1 alignment
        new_x = info.get('pad1_x', info['pos_x']) - lib_pad1_x
        new_y = info.get('pad1_y', info['pos_y']) - lib_pad1_y

        pos = pcbnew.VECTOR2I(pcbnew.FromMM(new_x), pcbnew.FromMM(new_y))
        fp.SetPosition(pos)
        fp.SetOrientationDegrees(info['orientation'])
        fp.SetReference(info['ref'])
        fp.SetValue(info['value'])

        # Flip if on back layer
        if info['layer'] == pcbnew.B_Cu:
            fp.Flip(pos, False)

        # Assign nets to pads
        for pad in fp.Pads():
            key = f"{info['ref']}:{pad.GetNumber()}"
            net_name = data['pad_nets'].get(key)
            if net_name:
                net_info = board.FindNet(net_name)
                if net_info:
                    pad.SetNet(net_info)

        board.Add(fp)

    # Add tracks
    for info in data['tracks']:
        net_info = board.FindNet(info['net_name']) if info['net_name'] else None

        if info['is_via']:
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(info['pos_x'], info['pos_y']))
            via.SetWidth(info['width'])
            via.SetDrill(info['drill'])
            via.SetViaType(pcbnew.VIATYPE(info['via_type']))
            if net_info:
                via.SetNet(net_info)
            board.Add(via)
        else:
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(info['start_x'], info['start_y']))
            track.SetEnd(pcbnew.VECTOR2I(info['end_x'], info['end_y']))
            track.SetWidth(info['width'])
            track.SetLayer(info['layer'])
            if net_info:
                track.SetNet(net_info)
            board.Add(track)

    # Add edges
    for info in data['edges']:
        shape = pcbnew.PCB_SHAPE(board)
        shape.SetShape(info['shape'])
        shape.SetStart(pcbnew.VECTOR2I(info['start_x'], info['start_y']))
        shape.SetEnd(pcbnew.VECTOR2I(info['end_x'], info['end_y']))
        shape.SetLayer(pcbnew.Edge_Cuts)
        shape.SetWidth(info['width'])
        board.Add(shape)

    board.Save(output_path)
    print(f"Saved to {output_path}")

if __name__ == '__main__':
    import sys
    input_json = sys.argv[1] if len(sys.argv) > 1 else '/tmp/board_data.json'
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'board_sdk.kicad_pcb'
    strict = '--strict' in sys.argv
    build_board(input_json, output_file)
```

Run: `python3 build_board_from_json.py [input.json] [output.kicad_pcb]`

**Verify build (expect unconnected pads - zones not added yet):**
```bash
kicad-cli pcb drc --output /tmp/phase2_check.txt board_sdk.kicad_pcb 2>&1 | head -3
```

### Step 4: Add Zones

Create `add_zones.py`:

```python
#!/usr/bin/env python3
"""Add GND zones and fill (Phase 3)."""
import pcbnew

def add_zones(input_path: str, output_path: str):
    board = pcbnew.LoadBoard(input_path)

    gnd_net = board.FindNet('GND')
    if not gnd_net:
        print("Error: GND net not found")
        return

    bbox = board.GetBoardEdgesBoundingBox()
    if bbox.GetWidth() == 0:
        bbox = board.ComputeBoundingBox()

    margin = pcbnew.FromMM(0.5)
    x1, y1 = bbox.GetLeft() + margin, bbox.GetTop() + margin
    x2, y2 = bbox.GetRight() - margin, bbox.GetBottom() - margin

    for layer in [pcbnew.B_Cu, pcbnew.F_Cu]:
        zone = pcbnew.ZONE(board)
        zone.SetNet(gnd_net)
        zone.SetLayer(layer)

        outline = zone.Outline()
        outline.NewOutline()
        outline.Append(x1, y1)
        outline.Append(x2, y1)
        outline.Append(x2, y2)
        outline.Append(x1, y2)

        zone.SetLocalClearance(pcbnew.FromMM(0.3))
        zone.SetMinThickness(pcbnew.FromMM(0.25))
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)

        board.Add(zone)
        print(f"Added GND zone on {pcbnew.LayerName(layer)}")

    # Fill zones
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())

    board.Save(output_path)
    print(f"Saved to {output_path}")

if __name__ == '__main__':
    import sys
    input_file = sys.argv[1] if len(sys.argv) > 1 else 'board_sdk.kicad_pcb'
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'board_final.kicad_pcb'
    add_zones(input_file, output_file)
```

Run: `python3 add_zones.py [input.kicad_pcb] [output.kicad_pcb]`

### Step 5: Validate

```bash
kicad-cli pcb drc --output drc_report.txt board_final.kicad_pcb
cat drc_report.txt
```

Expected output:
```
** Found 0 DRC violations **
** Found 0 unconnected pads **
** Found 0 Footprint errors **
```

## Finding Footprint Libraries

Use this table to map footprint names to KiCad library paths:

| Footprint Pattern | Library |
|-------------------|---------|
| `R_*Metric` | `Resistor_SMD.pretty` |
| `R_Axial_*` | `Resistor_THT.pretty` |
| `C_*Metric` | `Capacitor_SMD.pretty` |
| `CP_Radial_*` | `Capacitor_THT.pretty` |
| `L_*` | `Inductor_SMD.pretty` |
| `D_*` (SMD) | `Diode_SMD.pretty` |
| `D_DO-*`, `D_SOD*` | `Diode_THT.pretty` |
| `TO-*` | `Package_TO_SOT_THT.pretty` |
| `SOT-*`, `SOT23*` | `Package_TO_SOT_SMD.pretty` |
| `QFP-*`, `TQFP-*`, `LQFP-*` | `Package_QFP.pretty` |
| `QFN-*`, `DFN-*` | `Package_DFN_QFN.pretty` |
| `DIP-*` | `Package_DIP.pretty` |
| `SOIC-*`, `SOP-*` | `Package_SO.pretty` |
| `BGA-*` | `Package_BGA.pretty` |
| `PinHeader_*` | `Connector_PinHeader_2.54mm.pretty` |
| `PinSocket_*` | `Connector_PinSocket_2.54mm.pretty` |
| `USB_*` | `Connector_USB.pretty` |
| `LED_*` | `LED_SMD.pretty` or `LED_THT.pretty` |
| `Crystal_*` | `Crystal.pretty` |
| `SW_*` | `Button_Switch_SMD.pretty` or `Button_Switch_THT.pretty` |

**Search for a footprint:**
```bash
# Find which library contains a footprint
find /usr/share/kicad/footprints -name "*.kicad_mod" | xargs grep -l "YOUR_FOOTPRINT" 2>/dev/null

# List all footprints in a library
ls /usr/share/kicad/footprints/Resistor_SMD.pretty/
```

## Troubleshooting

### Segmentation Faults
**Cause**: SWIG memory issues when mixing board operations
**Solution**: Run each phase as a separate Python process

### Footprint Not Found
**Cause**: Footprint name not in FOOTPRINT_LIBS mapping
**Solution**: Add the mapping with correct library path:
```python
FOOTPRINT_LIBS['YourFootprint'] = '/usr/share/kicad/footprints/Library.pretty'
```

Find library path:
```bash
ls /usr/share/kicad/footprints/ | grep -i resistor
```

### Strict Mode (Fail on Missing Footprints)
Add `--strict` flag to fail instead of skipping missing footprints:
```python
# In build_board_from_json.py, modify the footprint loop:
if not lib_path:
    msg = f"No library mapping for {info['fp_name']} ({info['ref']})"
    if '--strict' in sys.argv:
        raise ValueError(msg)
    print(f"Warning: {msg}")
    continue
```
Run: `python3 build_board_from_json.py /tmp/board_data.json board_sdk.kicad_pcb --strict`

### Pad Misalignment / Shorts
**Cause**: Library footprint has different reference point than routed board
**Solution**: Align by pad 1 position (see Step 3 code)

### Unconnected GND Pads
**Cause**: Missing copper pour
**Solution**: Run Phase 3 (add_zones.py) to add GND zones

### Starved Thermal Errors
**Cause**: Thermal relief spokes blocked by nearby traces
**Solution**: Use `ZONE_CONNECTION_FULL` instead of `ZONE_CONNECTION_THERMAL`

### 3D Models Not Showing
**Cause**: kicad-packages3d not installed
**Solution**: `sudo apt install kicad-packages3d`

## Adding New Footprints

To support additional footprints, add entries to FOOTPRINT_LIBS:

```python
FOOTPRINT_LIBS = {
    # SMD Resistors
    'R_0402_1005Metric': '/usr/share/kicad/footprints/Resistor_SMD.pretty',
    'R_0603_1608Metric': '/usr/share/kicad/footprints/Resistor_SMD.pretty',
    'R_0805_2012Metric': '/usr/share/kicad/footprints/Resistor_SMD.pretty',
    'R_1206_3216Metric': '/usr/share/kicad/footprints/Resistor_SMD.pretty',

    # SMD Capacitors
    'C_0402_1005Metric': '/usr/share/kicad/footprints/Capacitor_SMD.pretty',
    'C_0603_1608Metric': '/usr/share/kicad/footprints/Capacitor_SMD.pretty',
    'C_0805_2012Metric': '/usr/share/kicad/footprints/Capacitor_SMD.pretty',

    # THT Components
    'TO-220-3_Vertical': '/usr/share/kicad/footprints/Package_TO_SOT_THT.pretty',
    'DIP-8_W7.62mm': '/usr/share/kicad/footprints/Package_DIP.pretty',

    # Connectors
    'PinHeader_1x02_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',
    'PinHeader_1x03_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',
    # ... add more as needed
}
```

## Advanced: Multiple Zone Types

### Adding VCC/Power Zones

To add zones for other nets (e.g., VCC on top layer only):

```python
# In add_zones.py, after GND zones:
vcc_net = board.FindNet('VCC') or board.FindNet('+5V') or board.FindNet('+12V')
if vcc_net:
    zone = pcbnew.ZONE(board)
    zone.SetNet(vcc_net)
    zone.SetLayer(pcbnew.F_Cu)  # Top layer only
    zone.SetAssignedPriority(1)  # Lower priority than GND

    # Define zone outline (smaller area, e.g., around power section)
    outline = zone.Outline()
    outline.NewOutline()
    # Use specific coordinates for power area
    outline.Append(pcbnew.FromMM(10), pcbnew.FromMM(10))
    outline.Append(pcbnew.FromMM(50), pcbnew.FromMM(10))
    outline.Append(pcbnew.FromMM(50), pcbnew.FromMM(30))
    outline.Append(pcbnew.FromMM(10), pcbnew.FromMM(30))

    zone.SetLocalClearance(pcbnew.FromMM(0.3))
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    board.Add(zone)
```

### Zone Priority

Lower number = filled first (higher priority in copper):
- GND: priority 0 (fills most area)
- VCC: priority 1 (fills remaining area)

## Reference Implementation

Complete working example at:
```
/home/user/repos/ee/manual_temp_test/injector_6ch_project/
```

Files:
- `extract_board_data.py` - Phase 1 script
- `build_board_from_json.py` - Phase 2 script
- `add_zones.py` - Phase 3 script
- `injector_6ch_routed.kicad_pcb` - Input (autorouted board)
- `injector_6ch_final.kicad_pcb` - Output (0 DRC errors)

## Quick Reference

```bash
# Full workflow
python3 extract_board_data.py        # Phase 1: Extract
python3 build_board_from_json.py     # Phase 2: Build with library FPs
python3 add_zones.py                 # Phase 3: Add zones
kicad-cli pcb drc -o drc.txt board_final.kicad_pcb  # Validate
```
