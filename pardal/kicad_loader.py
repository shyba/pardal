"""
KiCad pcbnew integration helpers.

Provides bidirectional conversion between:
- pcbnew.BOARD (KiCad's native board representation)
- pardal.data_model.Board (pardal's board representation)
"""

from pardal.data_model import Board, Component, Net, Pad, TraceSegment, Via
from pardal.data_model import NetClass


def _get_layer_map():
    """Build layer name → pcbnew constant mapping (lazy import to avoid import-time pcbnew)."""
    import pcbnew

    layer_map = {
        "F.Cu": pcbnew.F_Cu,
        "B.Cu": pcbnew.B_Cu,
    }
    # Add inner layers In1.Cu through In30.Cu
    for i in range(1, 31):
        layer_name = f"In{i}.Cu"
        layer_map[layer_name] = getattr(pcbnew, f"In{i}_Cu", None)
    return layer_map


def _get_pcbnew_layer(layer_name: str):
    """Get pcbnew layer constant for a layer name. Defaults to F.Cu if unknown."""
    import pcbnew

    layer_map = _get_layer_map()
    return layer_map.get(layer_name, pcbnew.F_Cu)


def load_board_from_kicad(kicad_board) -> Board:
    """
    Convert a pcbnew board to pardal Board.

    Extracts:
    - Components with pads and positions
    - Nets with connections
    - Existing traces and vias

    Args:
        kicad_board: pcbnew.BOARD object

    Returns:
        Board object populated with components and nets
    """
    import pcbnew

    board = Board()

    # Extract net classes (design rules).
    # KiCad exposes net classes on the BOARD; we keep a lightweight mirror so the router
    # can use correct widths/clearances/via sizes for DRC-clean writeback.
    try:
        kicad_net_classes = kicad_board.GetAllNetClasses()
    except Exception:
        kicad_net_classes = {}

    for name, nc in dict(kicad_net_classes).items():
        try:
            board.add_net_class(
                NetClass(
                    name=str(name),
                    track_width=pcbnew.ToMM(nc.GetTrackWidth()),
                    clearance=pcbnew.ToMM(nc.GetClearance()),
                    via_size=pcbnew.ToMM(nc.GetViaDiameter()),
                    via_drill=pcbnew.ToMM(nc.GetViaDrill()),
                )
            )
        except Exception:
            # Keep going; net class API differs slightly across KiCad builds.
            continue

    default_net_class = board.net_classes.get("Default")

    # Extract nets
    for i in range(kicad_board.GetNetCount()):
        net_info = kicad_board.GetNetInfo().GetNetItem(i)
        net_name = net_info.GetNetname()
        if net_name:
            net = Net(name=net_name, code=str(i))
            try:
                class_name = str(net_info.GetNetClassName())
                if class_name:
                    net.net_class = class_name
            except Exception:
                pass
            if net.net_class and net.net_class in board.net_classes:
                nc = board.net_classes[net.net_class]
                net.track_width = nc.track_width
                net.via_size = nc.via_size
                net.via_drill = nc.via_drill
            elif default_net_class is not None:
                net.track_width = default_net_class.track_width
                net.via_size = default_net_class.via_size
                net.via_drill = default_net_class.via_drill
            board.add_net(net)

    # Extract footprints as components
    for fp in kicad_board.GetFootprints():
        ref = fp.GetReference()
        pos = fp.GetPosition()

        comp = Component(
            ref=ref,
            value=fp.GetValue(),
            footprint=str(fp.GetFPID().GetLibItemName()),
            position=(pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)),
            rotation=fp.GetOrientationDegrees(),
            layer="F.Cu" if fp.GetLayer() == pcbnew.F_Cu else "B.Cu",
        )

        # Extract pads
        for kicad_pad in fp.Pads():
            pad_pos = kicad_pad.GetPosition()
            pad = Pad(
                number=kicad_pad.GetNumber(),
                position_offset=(
                    pcbnew.ToMM(pad_pos.x - pos.x),
                    pcbnew.ToMM(pad_pos.y - pos.y),
                ),
                size=(
                    pcbnew.ToMM(kicad_pad.GetSize().x),
                    pcbnew.ToMM(kicad_pad.GetSize().y),
                ),
                shape=(
                    "rect"
                    if kicad_pad.GetShape() == pcbnew.PAD_SHAPE_RECT
                    else "circle"
                ),
            )
            comp.pads.append(pad)

            # Track net connections
            net_name = kicad_pad.GetNetname()
            if net_name and net_name in board.nets:
                board.nets[net_name].add_connection(ref, kicad_pad.GetNumber())

        board.add_component(comp)

    return board


def write_traces_to_kicad(board: Board, kicad_board):
    """
    Write pardal traces and vias back to pcbnew board.

    Args:
        board: Pardal Board object with routing results
        kicad_board: pcbnew.BOARD object to write to
    """
    import pcbnew

    for net_name, net in board.nets.items():
        net_info = kicad_board.FindNet(net_name)

        for segment in net.segments:
            track = pcbnew.PCB_TRACK(kicad_board)
            track.SetStart(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(segment.start[0]), pcbnew.FromMM(segment.start[1])
                )
            )
            track.SetEnd(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(segment.end[0]), pcbnew.FromMM(segment.end[1])
                )
            )
            track.SetWidth(pcbnew.FromMM(segment.width))
            track.SetLayer(_get_pcbnew_layer(segment.layer))
            if net_info:
                track.SetNet(net_info)
            kicad_board.Add(track)

        for via in net.vias:
            pcb_via = pcbnew.PCB_VIA(kicad_board)
            pcb_via.SetPosition(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(via.position[0]), pcbnew.FromMM(via.position[1])
                )
            )
            pcb_via.SetWidth(pcbnew.FromMM(via.size))
            pcb_via.SetDrill(pcbnew.FromMM(via.drill))

            # Set via type and span.
            # - "through": spans outer layers
            # - "blind"/"buried": use layer pairs
            # - "micro": KiCad microvia
            layers = tuple(via.layers)
            if layers:
                try:
                    layer0 = _get_pcbnew_layer(layers[0])
                    layer1 = _get_pcbnew_layer(layers[-1])
                    if via.via_type == "micro":
                        pcb_via.SetViaType(pcbnew.VIATYPE_MICROVIA)
                        pcb_via.SetLayerPair(layer0, layer1)
                    elif via.via_type in ("blind", "buried"):
                        pcb_via.SetViaType(pcbnew.VIATYPE_BLIND_BURIED)
                        pcb_via.SetLayerPair(layer0, layer1)
                    else:
                        pcb_via.SetViaType(pcbnew.VIATYPE_THROUGH)
                except Exception:
                    pass
            if net_info:
                pcb_via.SetNet(net_info)
            kicad_board.Add(pcb_via)
