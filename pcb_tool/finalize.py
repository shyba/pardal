#!/usr/bin/env python3
"""
SDK finalization workflow - converts routed board to production-quality.

This module implements the 3-phase workflow that achieves 0 DRC errors:
1. Extract board data (footprints, tracks, nets, edges) to in-memory dict
2. Rebuild board using KiCad library footprints (full graphics, 3D models)
3. Add GND copper zones on F.Cu and B.Cu

Usage:
    from pcb_tool.finalize import finalize_board
    success, msg = finalize_board(Path("input.kicad_pcb"), Path("output.kicad_pcb"))
"""
from pathlib import Path
from typing import Any


# FOOTPRINT_LIBS maps pardal footprint names to KiCad library paths
FOOTPRINT_LIBS = {
    # Resistors SMD
    'R_0805_2012Metric': '/usr/share/kicad/footprints/Resistor_SMD.pretty',
    'R_0603_1608Metric': '/usr/share/kicad/footprints/Resistor_SMD.pretty',
    'R_0805': '/usr/share/kicad/footprints/Resistor_SMD.pretty',
    'R_0603': '/usr/share/kicad/footprints/Resistor_SMD.pretty',

    # Capacitors SMD
    'C_0805_2012Metric': '/usr/share/kicad/footprints/Capacitor_SMD.pretty',
    'C_0603_1608Metric': '/usr/share/kicad/footprints/Capacitor_SMD.pretty',
    'C_0805': '/usr/share/kicad/footprints/Capacitor_SMD.pretty',
    'C_0603': '/usr/share/kicad/footprints/Capacitor_SMD.pretty',

    # Capacitors THT
    'CP_Radial_D6.3mm_P2.50mm': '/usr/share/kicad/footprints/Capacitor_THT.pretty',

    # MOSFETs/Transistors
    'TO-220-3_Vertical': '/usr/share/kicad/footprints/Package_TO_SOT_THT.pretty',

    # Diodes
    'D_DO-41_SOD81_P10.16mm_Horizontal': '/usr/share/kicad/footprints/Diode_THT.pretty',

    # Connectors
    'PinHeader_1x03_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',
    'PinHeader_1x04_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',
    'PinHeader_1x05_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',
    'PinHeader_1x06_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',
    'PinHeader_1x07_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',
    'PinHeader_1x08_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',
    'PinHeader_1x10_P2.54mm_Vertical': '/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty',

    # Voltage regulators
    'SOT-223-3': '/usr/share/kicad/footprints/Package_TO_SOT_SMD.pretty',
    'SOT-223-3_TabPin2': '/usr/share/kicad/footprints/Package_TO_SOT_SMD.pretty',

    # ICs
    'DIP-8_W7.62mm': '/usr/share/kicad/footprints/Package_DIP.pretty',
    'SSOP-20_W5.3mm': '/usr/share/kicad/footprints/Package_SO.pretty',

    # Test points
    'TestPoint_Pad_1.0mm': '/usr/share/kicad/footprints/TestPoint.pretty',

    # Resistors THT
    'R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal': '/usr/share/kicad/footprints/Resistor_THT.pretty',
}


def finalize_board(input_pcb: Path, output_pcb: Path, gnd_net: str = "GND") -> tuple[bool, str]:
    """
    Run full SDK finalization workflow.

    Args:
        input_pcb: Path to routed board with simplified footprints
        output_pcb: Path to save finalized board
        gnd_net: Net name for copper zones (default: "GND")

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        import pcbnew
    except ImportError:
        return False, "pcbnew not available. Run with system Python, not venv."

    # Phase 1: Extract board data
    print(f"Phase 1: Extracting data from {input_pcb}...")
    board_data = _extract_board_data(input_pcb)
    print(f"  Extracted {len(board_data['footprints'])} footprints, {len(board_data['tracks'])} tracks")

    # Check for unmapped footprints
    unmapped = []
    for fp in board_data['footprints']:
        if fp['fp_name'] not in FOOTPRINT_LIBS:
            unmapped.append(f"  {fp['ref']} ({fp['fp_name']})")
    if unmapped:
        return False, f"Cannot finalize - unmapped footprints:\n" + "\n".join(unmapped[:10])

    # Phase 2: Build with library footprints
    print("Phase 2: Building with KiCad library footprints...")
    final_board = _build_with_library_footprints(board_data)
    print(f"  Created board with {final_board.GetFootprintCount()} footprints")

    # Phase 3: Add zones
    print("Phase 3: Adding GND zones...")
    _add_gnd_zones(final_board, gnd_net)

    # Save
    final_board.Save(str(output_pcb))
    return True, f"Finalized board saved to {output_pcb}"


def _extract_board_data(input_pcb: Path) -> dict[str, Any]:
    """Phase 1: Extract all board data to in-memory dict."""
    import pcbnew

    board = pcbnew.LoadBoard(str(input_pcb))

    data = {
        'net_names': [],
        'pad_nets': {},      # "REF:PAD" -> net_name
        'footprints': [],
        'tracks': [],
        'edges': [],
    }

    # Extract nets from pads and tracks
    net_names = set()
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname():
                net_names.add(pad.GetNetname())
    for track in board.GetTracks():
        if track.GetNetname():
            net_names.add(track.GetNetname())
    data['net_names'] = list(net_names)

    # Extract pad-to-net mapping (critical for reconnection)
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

    # Extract tracks and vias
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

    # Extract board outline
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

    return data


def _build_with_library_footprints(data: dict[str, Any]) -> 'pcbnew.BOARD':
    """Phase 2: Create new board with library footprints."""
    import pcbnew

    board = pcbnew.BOARD()
    io = pcbnew.PCB_IO_KICAD_SEXPR()

    # Create nets
    for net_name in data['net_names']:
        board.Add(pcbnew.NETINFO_ITEM(board, net_name))

    # Add footprints from library
    for info in data['footprints']:
        lib_path = FOOTPRINT_LIBS.get(info['fp_name'])
        if not lib_path:
            print(f"  Warning: No library for {info['fp_name']} ({info['ref']})")
            continue

        try:
            fp = io.FootprintLoad(lib_path, info['fp_name'])
        except Exception as e:
            print(f"  Error loading {info['fp_name']}: {e}")
            continue

        # Find pad 1 offset in library footprint for alignment
        lib_pad1_x, lib_pad1_y = 0, 0
        for pad in fp.Pads():
            if pad.GetNumber() == '1':
                lib_pad1_x = pcbnew.ToMM(pad.GetPosition().x)
                lib_pad1_y = pcbnew.ToMM(pad.GetPosition().y)
                break

        # Position by pad 1 alignment (critical for routing to work)
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

        # Reconnect nets to pads
        for pad in fp.Pads():
            key = f"{info['ref']}:{pad.GetNumber()}"
            net_name = data['pad_nets'].get(key)
            if net_name:
                net_info = board.FindNet(net_name)
                if net_info:
                    pad.SetNet(net_info)

        board.Add(fp)

    # Add tracks and vias
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

    # Add board outline
    for info in data['edges']:
        shape = pcbnew.PCB_SHAPE(board)
        shape.SetShape(info['shape'])
        shape.SetStart(pcbnew.VECTOR2I(info['start_x'], info['start_y']))
        shape.SetEnd(pcbnew.VECTOR2I(info['end_x'], info['end_y']))
        shape.SetLayer(pcbnew.Edge_Cuts)
        shape.SetWidth(info['width'])
        board.Add(shape)

    return board


def _add_gnd_zones(board: 'pcbnew.BOARD', gnd_net: str = "GND"):
    """Phase 3: Add GND copper zones on both layers."""
    import pcbnew

    gnd_net_info = board.FindNet(gnd_net)
    if not gnd_net_info:
        print(f"  Warning: Net '{gnd_net}' not found, skipping zones")
        return

    # Get board bounding box for zone outline
    bbox = board.GetBoardEdgesBoundingBox()
    if bbox.GetWidth() == 0:
        bbox = board.ComputeBoundingBox()

    # Create zones on both layers
    for layer in [pcbnew.F_Cu, pcbnew.B_Cu]:
        zone = pcbnew.ZONE(board)
        zone.SetNet(gnd_net_info)
        zone.SetLayer(layer)
        zone.SetIsFilled(False)

        # Create outline slightly inside board edges (0.5mm inset)
        outline = zone.Outline()
        outline.NewOutline()
        inset = pcbnew.FromMM(0.5)
        outline.Append(bbox.GetLeft() + inset, bbox.GetTop() + inset)
        outline.Append(bbox.GetRight() - inset, bbox.GetTop() + inset)
        outline.Append(bbox.GetRight() - inset, bbox.GetBottom() - inset)
        outline.Append(bbox.GetLeft() + inset, bbox.GetBottom() - inset)

        # Zone settings
        zone.SetLocalClearance(pcbnew.FromMM(0.3))
        zone.SetMinThickness(pcbnew.FromMM(0.25))
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        zone.SetThermalReliefGap(pcbnew.FromMM(0.5))
        zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.5))

        board.Add(zone)

    # Fill all zones
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())

    print(f"  Added GND zones on F.Cu and B.Cu")
