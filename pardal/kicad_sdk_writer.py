from __future__ import annotations

"""
KiCad SDK Board Writer

Uses the pcbnew Python SDK to create PCB files with complete footprints
loaded from KiCad's standard libraries. This produces boards that pass
DRC without footprint mismatch warnings.

Requires: System Python 3 with pcbnew module (not virtualenv)
"""

import os
from pathlib import Path
from typing import Optional

from pardal.footprint_normalizer import normalize_footprint_name

# pcbnew is only available in system Python
try:
    import pcbnew
except ImportError:
    class _MissingPcbnew:
        def __getattr__(self, name):
            return 0

    pcbnew = _MissingPcbnew()
    PCBNEW_AVAILABLE = False
else:
    PCBNEW_AVAILABLE = True

from pardal.data_model import Board, Component, Net, TraceSegment, Via, CopperZone


# Map library:footprint to library paths
# This allows discovery without hardcoding paths
LIBRARY_PATHS = {
    # Standard KiCad library locations (in order of preference)
    "default_search_paths": [
        "/usr/share/kicad/footprints",
        "/usr/local/share/kicad/footprints",
        os.path.expanduser("~/.local/share/kicad/footprints"),
    ],
    # Library nickname to .pretty directory name mapping
    "nicknames": {
        "Resistor_SMD": "Resistor_SMD.pretty",
        "Capacitor_SMD": "Capacitor_SMD.pretty",
        "Capacitor_THT": "Capacitor_THT.pretty",
        "Diode_THT": "Diode_THT.pretty",
        "Diode_SMD": "Diode_SMD.pretty",
        "Package_TO_SOT_THT": "Package_TO_SOT_THT.pretty",
        "Package_TO_SOT_SMD": "Package_TO_SOT_SMD.pretty",
        "Package_QFP": "Package_QFP.pretty",
        "LED_SMD": "LED_SMD.pretty",
        "Connector_PinHeader_2.54mm": "Connector_PinHeader_2.54mm.pretty",
        "TerminalBlock_Phoenix": "TerminalBlock_Phoenix.pretty",
        "TestPoint": "TestPoint.pretty",
        "Fiducial": "Fiducial.pretty",
        "MountingHole": "MountingHole.pretty",
    },
}


def find_footprint_library_path(library_nickname: str) -> Optional[str]:
    """Find the path to a footprint library by nickname.

    Args:
        library_nickname: Library nickname (e.g., "Resistor_SMD")

    Returns:
        Full path to the .pretty directory, or None if not found
    """
    pretty_name = LIBRARY_PATHS["nicknames"].get(library_nickname)
    if not pretty_name:
        # Try direct match
        pretty_name = f"{library_nickname}.pretty"

    for search_path in LIBRARY_PATHS["default_search_paths"]:
        full_path = os.path.join(search_path, pretty_name)
        if os.path.isdir(full_path):
            return full_path

    return None


def parse_footprint_name(footprint_full_name: str) -> tuple[str, str]:
    """Parse a full footprint name into library and footprint parts.

    Args:
        footprint_full_name: Full name like "Resistor_SMD:R_0805_2012Metric"

    Returns:
        Tuple of (library_nickname, footprint_name)
    """
    if ":" in footprint_full_name:
        library, fp_name = footprint_full_name.split(":", 1)
        return library, fp_name
    else:
        # No library specified, return empty library
        return "", footprint_full_name


class KiCadSDKWriter:
    """Writes PCB files using the pcbnew SDK with library footprints."""

    # Layer name to pcbnew constant mapping
    # Supports all copper layers up to 32-layer boards
    LAYER_MAP = {
        "F.Cu": pcbnew.F_Cu,
        "In1.Cu": pcbnew.In1_Cu,
        "In2.Cu": pcbnew.In2_Cu,
        "In3.Cu": pcbnew.In3_Cu,
        "In4.Cu": pcbnew.In4_Cu,
        "In5.Cu": pcbnew.In5_Cu,
        "In6.Cu": pcbnew.In6_Cu,
        "In7.Cu": pcbnew.In7_Cu,
        "In8.Cu": pcbnew.In8_Cu,
        "In9.Cu": pcbnew.In9_Cu,
        "In10.Cu": pcbnew.In10_Cu,
        "In11.Cu": pcbnew.In11_Cu,
        "In12.Cu": pcbnew.In12_Cu,
        "In13.Cu": pcbnew.In13_Cu,
        "In14.Cu": pcbnew.In14_Cu,
        "In15.Cu": pcbnew.In15_Cu,
        "In16.Cu": pcbnew.In16_Cu,
        "In17.Cu": pcbnew.In17_Cu,
        "In18.Cu": pcbnew.In18_Cu,
        "In19.Cu": pcbnew.In19_Cu,
        "In20.Cu": pcbnew.In20_Cu,
        "In21.Cu": pcbnew.In21_Cu,
        "In22.Cu": pcbnew.In22_Cu,
        "In23.Cu": pcbnew.In23_Cu,
        "In24.Cu": pcbnew.In24_Cu,
        "In25.Cu": pcbnew.In25_Cu,
        "In26.Cu": pcbnew.In26_Cu,
        "In27.Cu": pcbnew.In27_Cu,
        "In28.Cu": pcbnew.In28_Cu,
        "In29.Cu": pcbnew.In29_Cu,
        "In30.Cu": pcbnew.In30_Cu,
        "B.Cu": pcbnew.B_Cu,
    }

    def __init__(self):
        if not PCBNEW_AVAILABLE:
            raise RuntimeError(
                "pcbnew module not found. Run this command with system Python 3."
            )
        self.io = pcbnew.PCB_IO_KICAD_SEXPR()
        self._footprint_cache: dict[str, pcbnew.FOOTPRINT] = {}

    def load_footprint(self, footprint_full_name: str) -> Optional[pcbnew.FOOTPRINT]:
        """Load a footprint from KiCad libraries.

        Args:
            footprint_full_name: Full name like "Resistor_SMD:R_0805_2012Metric"

        Returns:
            FOOTPRINT object or None if not found
        """
        footprint_full_name = normalize_footprint_name(footprint_full_name)
        fallback = self._create_fallback_footprint(footprint_full_name)
        if fallback is not None:
            return fallback
        if footprint_full_name in self._footprint_cache:
            # Return a copy to avoid modifying cached footprint
            cached = self._footprint_cache[footprint_full_name]
            # Clone by loading again (pcbnew doesn't have easy clone)
            library, fp_name = parse_footprint_name(footprint_full_name)
            lib_path = find_footprint_library_path(library)
            if lib_path:
                return self.io.FootprintLoad(lib_path, fp_name)
            return None

        library, fp_name = parse_footprint_name(footprint_full_name)
        lib_path = find_footprint_library_path(library)

        if not lib_path:
            print(
                f"Warning: Library '{library}' not found for footprint "
                f"'{footprint_full_name}'"
            )
            return None

        try:
            fp = self.io.FootprintLoad(lib_path, fp_name)
            self._footprint_cache[footprint_full_name] = fp
            return self.io.FootprintLoad(lib_path, fp_name)  # Return fresh copy
        except Exception as e:
            print(
                f"Warning: Failed to load footprint '{fp_name}' from '{lib_path}': {e}"
            )
            return None

    def _create_fallback_footprint(
        self, footprint_full_name: str
    ) -> Optional[pcbnew.FOOTPRINT]:
        _library, footprint_name = parse_footprint_name(footprint_full_name)
        if footprint_name == "TestPoint_Pad_1.0mm":
            fp = pcbnew.FOOTPRINT(None)
            pad = pcbnew.PAD(fp)
            pad.SetNumber("1")
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.0), pcbnew.FromMM(1.0)))
            pad.SetPosition(pcbnew.VECTOR2I(0, 0))
            pad.SetLayerSet(self._front_smd_layers())
            fp.Add(pad)
            return fp
        if footprint_name == "Fiducial_1mm_Mask2mm":
            fp = pcbnew.FOOTPRINT(None)
            pad = pcbnew.PAD(fp)
            pad.SetNumber("1")
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.0), pcbnew.FromMM(1.0)))
            pad.SetPosition(pcbnew.VECTOR2I(0, 0))
            pad.SetLayerSet(self._front_smd_layers())
            fp.Add(pad)
            return fp
        if footprint_name == "MountingHole_3.2mm_M3":
            fp = pcbnew.FOOTPRINT(None)
            pad = pcbnew.PAD(fp)
            pad.SetNumber("1")
            pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            size = pcbnew.VECTOR2I(pcbnew.FromMM(3.2), pcbnew.FromMM(3.2))
            pad.SetSize(size)
            if hasattr(pad, "SetDrillSize"):
                pad.SetDrillSize(size)
            if hasattr(pad, "SetDrill"):
                pad.SetDrill(pcbnew.FromMM(3.2))
            pad.SetPosition(pcbnew.VECTOR2I(0, 0))
            pad.SetLayerSet(pcbnew.LSET.AllCuMask())
            fp.Add(pad)
            return fp
        return None

    def _front_smd_layers(self):
        layers = pcbnew.LSET()
        layers.AddLayer(pcbnew.F_Cu)
        layers.AddLayer(pcbnew.F_Mask)
        return layers

    def write_board(self, board: Board, output_path: str) -> bool:
        """Write a complete PCB file using the SDK.

        Args:
            board: Board data model with components, nets, traces
            output_path: Path to write the .kicad_pcb file

        Returns:
            True if successful, False otherwise
        """
        try:
            pcb = pcbnew.BOARD()
            if board.layer_count >= 2:
                pcb.SetCopperLayerCount(board.layer_count)
            self._apply_design_rules(pcb, board)

            # Create nets first (need them for pad assignments)
            net_map = self._create_nets(pcb, board)

            # Add components with library footprints
            self._add_components(pcb, board, net_map)

            # Add traces
            self._add_traces(pcb, board, net_map)

            # Add vias
            self._add_vias(pcb, board, net_map)

            # Add board outline
            self._add_board_outline(pcb, board)

            # Add zones
            self._add_zones(pcb, board, net_map)

            # Save
            pcb.Save(str(output_path))
            if board.zones:
                self._fill_zones(output_path)
            return True

        except Exception as e:
            print(f"Error writing board: {e}")
            import traceback

            traceback.print_exc()
            return False

    def _apply_design_rules(self, pcb: pcbnew.BOARD, board: Board) -> None:
        settings = pcb.GetDesignSettings()
        clearances = [net_class.clearance for net_class in board.net_classes.values()]
        widths = [net_class.track_width for net_class in board.net_classes.values()]
        via_sizes = [net_class.via_size for net_class in board.net_classes.values()]
        via_drills = [net_class.via_drill for net_class in board.net_classes.values()]

        min_clearance = min(clearances, default=0.2)
        min_width = min(widths, default=0.25)
        min_via_size = min(via_sizes, default=0.5)
        min_via_drill = min(via_drills, default=0.3)

        settings.m_MinClearance = pcbnew.FromMM(min_clearance)
        settings.m_TrackMinWidth = pcbnew.FromMM(min_width)
        settings.SetCustomTrackWidth(pcbnew.FromMM(min_width))
        settings.UseCustomTrackViaSize(True)
        settings.m_ViasMinSize = pcbnew.FromMM(min_via_size)
        settings.m_MicroViasMinSize = pcbnew.FromMM(min_via_size)
        settings.m_MicroViasMinDrill = pcbnew.FromMM(min_via_drill)
        settings.SetCustomViaSize(pcbnew.FromMM(min_via_size))
        settings.SetCustomViaDrill(pcbnew.FromMM(min_via_drill))
        net_settings = settings.m_NetSettings
        default_class = net_settings.GetDefaultNetclass()
        default_class.SetClearance(pcbnew.FromMM(min_clearance))
        default_class.SetTrackWidth(pcbnew.FromMM(min_width))
        default_class.SetViaDiameter(pcbnew.FromMM(min_via_size))
        default_class.SetViaDrill(pcbnew.FromMM(min_via_drill))
        net_settings.SetDefaultNetclass(default_class)
        for name, net_class in board.net_classes.items():
            kicad_class = pcbnew.NETCLASS(name)
            kicad_class.SetClearance(pcbnew.FromMM(net_class.clearance))
            kicad_class.SetTrackWidth(pcbnew.FromMM(net_class.track_width))
            kicad_class.SetViaDiameter(pcbnew.FromMM(net_class.via_size))
            kicad_class.SetViaDrill(pcbnew.FromMM(net_class.via_drill))
            net_settings.SetNetclass(name, kicad_class)
            for net_name in net_class.nets:
                net_settings.SetNetclassPatternAssignment(net_name, name)
        net_settings.RecomputeEffectiveNetclasses()

    def _create_nets(
        self, pcb: pcbnew.BOARD, board: Board
    ) -> dict[str, pcbnew.NETINFO_ITEM]:
        """Create all nets on the board.

        Returns:
            Map of net name to NETINFO_ITEM
        """
        net_map = {}

        # Always create empty net (net 0)
        # Net 0 is implicit

        for net_code, (net_name, net) in enumerate(board.nets.items(), start=1):
            net_info = pcbnew.NETINFO_ITEM(pcb, net_name)
            pcb.Add(net_info)
            net_map[net_name] = net_info

        return net_map

    def _add_components(
        self, pcb: pcbnew.BOARD, board: Board, net_map: dict[str, pcbnew.NETINFO_ITEM]
    ) -> None:
        """Add all components with library footprints."""
        for comp in board.components.values():
            fp = self.load_footprint(comp.footprint)

            if not fp:
                print(f"Warning: Skipping component {comp.ref} - footprint not found")
                continue

            # Set position (KiCad uses nm internally, FromMM converts)
            pos = pcbnew.VECTOR2I(
                pcbnew.FromMM(comp.position[0]), pcbnew.FromMM(comp.position[1])
            )
            fp.SetPosition(pos)

            # Set rotation
            fp.SetOrientationDegrees(comp.rotation)

            # Set reference and value
            fp.SetReference(comp.ref)
            fp.SetValue(comp.value)
            if comp.ref.startswith(("TP", "FID", "MH")):
                fp.Reference().SetVisible(False)
                fp.Value().SetVisible(False)

            # Set layer (front or back)
            if comp.layer == "B.Cu":
                fp.Flip(pos, False)  # Flip to back side

            # Assign nets to pads based on component connections
            self._assign_pad_nets(fp, comp, board, net_map)

            pcb.Add(fp)

    def _assign_pad_nets(
        self,
        fp: pcbnew.FOOTPRINT,
        comp: Component,
        board: Board,
        net_map: dict[str, pcbnew.NETINFO_ITEM],
    ) -> None:
        """Assign nets to footprint pads based on board connections."""
        for pad in fp.Pads():
            pad_num = pad.GetNumber()

            # Find net for this pad
            for net_name, net in board.nets.items():
                for conn_ref, conn_pin in net.connections:
                    if conn_ref == comp.ref and str(conn_pin) == str(pad_num):
                        if net_name in net_map:
                            pad.SetNet(net_map[net_name])
                        break

    def _add_traces(
        self, pcb: pcbnew.BOARD, board: Board, net_map: dict[str, pcbnew.NETINFO_ITEM]
    ) -> None:
        """Add all trace segments.

        Supports traces on any copper layer (F.Cu, In1.Cu, ..., In30.Cu, B.Cu).
        """
        for net_name, net in board.nets.items():
            net_info = net_map.get(net_name)

            for segment in net.segments:
                track = pcbnew.PCB_TRACK(pcb)
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

                if segment.layer not in board.layers:
                    raise ValueError(
                        f"Segment on net {net_name} uses layer {segment.layer}, "
                        f"not in board stack {board.layers}"
                    )
                pcbnew_layer = self.LAYER_MAP[segment.layer]
                track.SetLayer(pcbnew_layer)

                if net_info:
                    track.SetNet(net_info)

                pcb.Add(track)

    def _add_vias(
        self, pcb: pcbnew.BOARD, board: Board, net_map: dict[str, pcbnew.NETINFO_ITEM]
    ) -> None:
        """Add all vias.

        Supports multi-layer vias:
        - Through-hole: VIATYPE_THROUGH
        - Blind: VIATYPE_BLIND_BURIED (outer to inner)
        - Buried: VIATYPE_BLIND_BURIED (inner to inner)
        """
        for net_name, net in board.nets.items():
            net_info = net_map.get(net_name)

            for via_data in net.vias:
                via = pcbnew.PCB_VIA(pcb)
                via.SetPosition(
                    pcbnew.VECTOR2I(
                        pcbnew.FromMM(via_data.position[0]),
                        pcbnew.FromMM(via_data.position[1]),
                    )
                )
                via.SetDrill(pcbnew.FromMM(via_data.drill))

                # Set via type based on via_data.via_type
                if via_data.via_type == "through":
                    via.SetViaType(pcbnew.VIATYPE_THROUGH)
                elif via_data.via_type in ("blind", "buried"):
                    # Both blind and buried use VIATYPE_BLIND_BURIED in KiCad
                    via.SetViaType(pcbnew.VIATYPE_BLIND_BURIED)

                for layer in via_data.layers:
                    if layer not in board.layers:
                        raise ValueError(
                            f"Via on net {net_name} uses layer {layer}, "
                            f"not in board stack {board.layers}"
                        )
                first_layer = self.LAYER_MAP[via_data.layers[0]]
                last_layer = self.LAYER_MAP[via_data.layers[-1]]
                via.SetLayerPair(first_layer, last_layer)
                via_width = pcbnew.FromMM(via_data.size)
                via.SetWidth(first_layer, via_width)
                via.SetWidth(last_layer, via_width)

                if net_info:
                    via.SetNet(net_info)

                pcb.Add(via)

    def _add_board_outline(self, pcb: pcbnew.BOARD, board: Board) -> None:
        """Add board outline on Edge.Cuts layer."""
        source_width = getattr(board, "width", None)
        source_height = getattr(board, "height", None)
        if (
            isinstance(source_width, (int, float))
            and isinstance(source_height, (int, float))
            and source_width > 0
            and source_height > 0
        ):
            min_x, min_y = 0.0, 0.0
            max_x, max_y = float(source_width), float(source_height)
        else:
            # Fallback for legacy ad hoc boards without declared dimensions.
            if not board.components:
                return

            margin = 5.0  # mm
            min_x = float("inf")
            min_y = float("inf")
            max_x = float("-inf")
            max_y = float("-inf")

            for comp in board.components.values():
                x, y = comp.position
                # Approximate footprint size (could be improved with actual bounds)
                min_x = min(min_x, x - 10)
                min_y = min(min_y, y - 10)
                max_x = max(max_x, x + 10)
                max_y = max(max_y, y + 10)

            min_x -= margin
            min_y -= margin
            max_x += margin
            max_y += margin

        # Create rectangle outline
        points = [
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
        ]

        for i in range(4):
            start = points[i]
            end = points[(i + 1) % 4]

            line = pcbnew.PCB_SHAPE(pcb)
            line.SetShape(pcbnew.SHAPE_T_SEGMENT)
            line.SetStart(
                pcbnew.VECTOR2I(pcbnew.FromMM(start[0]), pcbnew.FromMM(start[1]))
            )
            line.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(end[0]), pcbnew.FromMM(end[1])))
            line.SetLayer(pcbnew.Edge_Cuts)
            line.SetWidth(pcbnew.FromMM(0.1))
            pcb.Add(line)

    def _add_zones(
        self, pcb: pcbnew.BOARD, board: Board, net_map: dict[str, pcbnew.NETINFO_ITEM]
    ) -> None:
        for zone_data in board.zones:
            zone = self._zone_to_pcbnew(pcb, zone_data, net_map)
            pcb.Add(zone)

    def _zone_to_pcbnew(
        self,
        pcb: pcbnew.BOARD,
        zone_data: CopperZone,
        net_map: dict[str, pcbnew.NETINFO_ITEM],
    ) -> pcbnew.ZONE:
        board_layers = self.LAYER_MAP
        if zone_data.layer not in board_layers:
            raise ValueError(f"Zone layer {zone_data.layer} is not supported")
        net_info = net_map.get(zone_data.net_name)
        if net_info is None:
            raise ValueError(f"Zone references unknown net {zone_data.net_name}")

        zone = pcbnew.ZONE(pcb)
        zone.SetNet(net_info)
        layer = board_layers[zone_data.layer]
        zone.SetLayer(layer)
        zone.SetFillFlag(layer, True)
        zone.SetAssignedPriority(zone_data.priority)
        zone.SetLocalClearance(pcbnew.FromMM(zone_data.clearance))
        zone.SetMinThickness(pcbnew.FromMM(zone_data.min_thickness))
        zone.SetThermalReliefGap(pcbnew.FromMM(zone_data.thermal_gap))
        zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(zone_data.thermal_bridge))
        if hasattr(zone, "SetPadConnection") and hasattr(
            pcbnew, "ZONE_CONNECTION_THERMAL"
        ):
            zone.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)

        for x, y in zone_data.outline:
            zone.AppendCorner(
                pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)),
                -1,
            )
        return zone

    def _fill_zones(self, output_path: str) -> None:
        pcb = pcbnew.LoadBoard(str(output_path))
        zones = pcb.Zones()
        if len(zones) == 0:
            return
        pcbnew.ZONE_FILLER(pcb).Fill(zones)
        pcbnew.SaveBoard(str(output_path), pcb)


def convert_board_to_sdk(
    input_board: Board,
    output_path: str,
    add_gnd_pour: bool = True,
    fill_zones: bool = True,
) -> bool:
    """Convert a Board data model to a KiCad PCB file using the SDK.

    This function creates a PCB file with:
    - Complete library footprints (with graphics, 3D models, attributes)
    - All traces and vias
    - Board outline
    - Optionally: GND copper pour on both layers

    Args:
        input_board: Board data model
        output_path: Path for output .kicad_pcb file
        add_gnd_pour: Whether to add GND copper pours
        fill_zones: Whether to fill zones after adding pours

    Returns:
        True if successful
    """
    writer = KiCadSDKWriter()

    if not writer.write_board(input_board, output_path):
        return False

    # Post-process for GND pour if requested
    if add_gnd_pour:
        try:
            from pardal.kicad_postprocess import postprocess

            # Reprocess the saved file to add pours
            postprocess(output_path, output_path, add_gnd=True, fill=fill_zones)
        except ImportError:
            print("Warning: kicad_postprocess not available, skipping GND pour")

    return True
