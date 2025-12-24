"""
KiCad PCB File Writer

Converts Board objects to KiCad PCB (.kicad_pcb) format using S-expressions.
"""

from pathlib import Path
from typing import TextIO, Tuple, Optional, List
import uuid
from pcb_tool.data_model import Board, Component, Net, CopperZone


class KicadWriter:
    """Writer that converts Board objects to KiCad PCB format."""

    def __init__(self):
        """Initialize the KiCad writer."""
        pass

    def write(self, board: Board, path: Path) -> None:
        """Write a Board to a KiCad PCB file.

        Args:
            board: The Board object to write
            path: Path where the .kicad_pcb file should be created

        The output file will be in KiCad S-expression format and can be
        opened directly in KiCad's pcbnew editor.

        Raises:
            PermissionError: If the file cannot be written due to permissions
            IOError: If there's an error writing the file
        """
        # Ensure parent directory exists
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(f"Permission denied creating directory {path.parent}: {e}")
        except Exception as e:
            raise IOError(f"Error creating directory {path.parent}: {e}")

        # Write the file
        try:
            with open(path, 'w', encoding='utf-8') as f:
                self._write_header(f)
                self._write_general(f)
                self._write_paper(f)
                self._write_layers(f, board)
                self._write_nets(f, board)
                self._write_footprints(f, board)
                self._write_routing(f, board)
                self._write_board_outline(f, board)
                # Note: Zones are added via kicad_postprocess.py using pcbnew SDK
                # This ensures proper zone filling and valid file format
                f.write(")\n")  # Close kicad_pcb
        except PermissionError as e:
            raise PermissionError(f"Permission denied writing to {path}: {e}")
        except IOError as e:
            raise IOError(f"Error writing to {path}: {e}")
        except Exception as e:
            raise IOError(f"Unexpected error writing to {path}: {e}")

    def _write_header(self, f: TextIO) -> None:
        """Write the KiCad PCB file header."""
        f.write("(kicad_pcb (version 20221018) (generator pcb-tool)\n")

    def _write_general(self, f: TextIO) -> None:
        """Write the general section with board properties."""
        f.write("\n  (general\n")
        f.write("    (thickness 1.6))\n")

    def _write_paper(self, f: TextIO) -> None:
        """Write the paper size."""
        f.write("\n  (paper \"A4\")\n")

    # KiCad layer indices for copper layers
    KICAD_LAYER_INDICES = {
        "F.Cu": 0,
        "In1.Cu": 1,
        "In2.Cu": 2,
        "In3.Cu": 3,
        "In4.Cu": 4,
        "In5.Cu": 5,
        "In6.Cu": 6,
        "In7.Cu": 7,
        "In8.Cu": 8,
        "In9.Cu": 9,
        "In10.Cu": 10,
        "In11.Cu": 11,
        "In12.Cu": 12,
        "In13.Cu": 13,
        "In14.Cu": 14,
        "In15.Cu": 15,
        "In16.Cu": 16,
        "In17.Cu": 17,
        "In18.Cu": 18,
        "In19.Cu": 19,
        "In20.Cu": 20,
        "In21.Cu": 21,
        "In22.Cu": 22,
        "In23.Cu": 23,
        "In24.Cu": 24,
        "In25.Cu": 25,
        "In26.Cu": 26,
        "In27.Cu": 27,
        "In28.Cu": 28,
        "In29.Cu": 29,
        "In30.Cu": 30,
        "B.Cu": 31,
    }

    def _write_layers(self, f: TextIO, board: Board) -> None:
        """Write the layer stack definition.

        Supports multi-layer boards (2, 4, 6, 8+ layers).
        Dynamically generates copper layer definitions based on board.layers.

        Args:
            f: File object to write to
            board: Board object with layer configuration
        """
        f.write("\n  (layers\n")

        # Write copper layers from board configuration
        for layer_name in board.layers:
            kicad_idx = self.KICAD_LAYER_INDICES.get(layer_name, 0)
            f.write(f"    ({kicad_idx} \"{layer_name}\" signal)\n")

        # Write standard non-copper layers
        f.write("    (32 \"B.Adhes\" user \"B.Adhesive\")\n")
        f.write("    (33 \"F.Adhes\" user \"F.Adhesive\")\n")
        f.write("    (34 \"B.Paste\" user)\n")
        f.write("    (35 \"F.Paste\" user)\n")
        f.write("    (36 \"B.SilkS\" user \"B.Silkscreen\")\n")
        f.write("    (37 \"F.SilkS\" user \"F.Silkscreen\")\n")
        f.write("    (38 \"B.Mask\" user)\n")
        f.write("    (39 \"F.Mask\" user)\n")
        f.write("    (40 \"Dwgs.User\" user \"User.Drawings\")\n")
        f.write("    (41 \"Cmts.User\" user \"User.Comments\")\n")
        f.write("    (42 \"Eco1.User\" user \"User.Eco1\")\n")
        f.write("    (43 \"Eco2.User\" user \"User.Eco2\")\n")
        f.write("    (44 \"Edge.Cuts\" user)\n")
        f.write("    (45 \"Margin\" user)\n")
        f.write("    (46 \"B.CrtYd\" user \"B.Courtyard\")\n")
        f.write("    (47 \"F.CrtYd\" user \"F.Courtyard\")\n")
        f.write("    (48 \"B.Fab\" user)\n")
        f.write("    (49 \"F.Fab\" user)\n")
        f.write("  )\n")

    def _write_nets(self, f: TextIO, board: Board) -> None:
        """Write the net definitions.

        Args:
            f: File object to write to
            board: Board containing the nets
        """
        f.write("\n")
        # Net 0 is always the unconnected net
        f.write("  (net 0 \"\")\n")

        # Write each net from the board
        for net in board.nets.values():
            f.write(f"  (net {net.code} \"{net.name}\")\n")

    def _write_footprints(self, f: TextIO, board: Board) -> None:
        """Write all component footprints.

        Args:
            f: File object to write to
            board: Board containing the components
        """
        for comp in board.components.values():
            self._write_footprint(f, comp, board)

    def _write_footprint(self, f: TextIO, comp: Component, board: Board) -> None:
        """Write a single component footprint.

        Args:
            f: File object to write to
            comp: Component to write
            board: Board for net lookups
        """
        f.write(f"\n  (footprint \"{comp.footprint}\" (layer \"F.Cu\")\n")
        f.write("    (tedit 0) (tstamp 00000000-0000-0000-0000-000000000000)\n")
        f.write(f"    (at {comp.position[0]} {comp.position[1]} {comp.rotation})\n")

        # Write properties
        f.write(f"    (property \"Reference\" \"{comp.ref}\" (at 0 0 0) (layer \"F.SilkS\")\n")
        f.write("      (effects (font (size 1 1) (thickness 0.15))))\n")

        f.write(f"    (property \"Value\" \"{comp.value}\" (at 0 0 0) (layer \"F.Fab\")\n")
        f.write("      (effects (font (size 1 1) (thickness 0.15))))\n")

        f.write(f"    (property \"Footprint\" \"{comp.footprint}\" (at 0 0 0) (layer \"F.Fab\") hide\n")
        f.write("      (effects (font (size 1 1) (thickness 0.15))))\n")

        # UUID path
        f.write("    (path \"/00000000-0000-0000-0000-000000000000\")\n")

        # Reference text
        f.write(f"    (fp_text reference \"{comp.ref}\" (at 0 0 {comp.rotation}) (layer \"F.SilkS\")\n")
        f.write("      (effects (font (size 1 1) (thickness 0.15))))\n")

        # Value text
        f.write(f"    (fp_text value \"{comp.value}\" (at 0 0 {comp.rotation}) (layer \"F.Fab\")\n")
        f.write("      (effects (font (size 1 1) (thickness 0.15))))\n")

        # Generate complete pads for production-ready board
        self._write_complete_pads(f, comp, board)

        f.write("  )\n")

    def _get_pad_net(self, comp: Component, pin_num: int, board: Board) -> tuple[str, str]:
        """Get the net code and name for a component pin.

        Args:
            comp: Component
            pin_num: Pin number
            board: Board to search for net

        Returns:
            Tuple of (net_code, net_name)
        """
        # Look for this pin in all net connections
        for net in board.nets.values():
            for ref, pin in net.connections:
                if ref == comp.ref and str(pin) == str(pin_num):
                    return (net.code, net.name)
        return ("0", "")  # Unconnected

    def _write_complete_pads(self, f: TextIO, comp: Component, board: Board) -> None:
        """Write production-ready pad definitions from component's pad list.

        Uses the pads populated from the footprint library to ensure
        accurate pad positions that match routing.

        Args:
            f: File object to write to
            comp: Component to write pads for
            board: Board object for net lookups
        """
        # Write pads from component's pad list
        for pad in comp.pads:
            # Get net assignment for this pad
            net_code, net_name = self._get_pad_net(comp, pad.number, board)

            # Determine pad type and layers
            if pad.is_tht:
                # Through-hole pad
                pad_type = "thru_hole"
                layers = "\"*.Cu\" \"*.Mask\""
                drill_spec = f"(drill {pad.drill})"
            else:
                # SMD pad
                pad_type = "smd"
                layers = "\"F.Cu\" \"F.Paste\" \"F.Mask\""
                drill_spec = ""

            # Get pad position offset
            x_offset, y_offset = pad.position_offset
            width, height = pad.size

            # Write pad S-expression
            f.write(
                f"    (pad \"{pad.number}\" {pad_type} {pad.shape} "
                f"(at {x_offset} {y_offset}) "
                f"(size {width} {height}) "
                f"{drill_spec} "
                f"(layers {layers}) "
                f"(net {net_code} \"{net_name}\"))\n"
            )

    def _write_routing(self, f: TextIO, board: Board) -> None:
        """Write all routing data (traces and vias).

        Args:
            f: File object to write to
            board: Board containing the routing data
        """
        # Write trace segments
        for net in board.nets.values():
            for segment in net.segments:
                self._write_segment(f, segment, net.code)

        # Write vias
        for net in board.nets.values():
            for via in net.vias:
                self._write_via(f, via, net.code)

    def _write_segment(self, f: TextIO, segment, net_code: str) -> None:
        """Write a single trace segment.

        Args:
            f: File object to write to
            segment: TraceSegment to write
            net_code: Net code for this segment
        """
        start_x, start_y = segment.start
        end_x, end_y = segment.end

        f.write(f"\n  (segment (start {start_x} {start_y}) (end {end_x} {end_y}) "
                f"(width {segment.width}) (layer \"{segment.layer}\") (net {net_code}))\n")

    def _write_via(self, f: TextIO, via, net_code: str) -> None:
        """Write a single via.

        Supports multi-layer vias (through, blind, buried).
        KiCad format specifies the first and last layer the via spans.

        Args:
            f: File object to write to
            via: Via to write
            net_code: Net code for this via
        """
        x, y = via.position

        # For KiCad, specify first and last layer of the via span
        first_layer = via.layers[0]
        last_layer = via.layers[-1]

        # Determine via type for KiCad (if not through-hole, add type attribute)
        via_type_str = ""
        if via.via_type == "blind":
            via_type_str = " (type blind)"
        elif via.via_type == "buried":
            via_type_str = " (type micro)"  # KiCad uses "micro" for buried vias

        f.write(f"\n  (via{via_type_str} (at {x} {y}) (size {via.size}) (drill {via.drill}) "
                f"(layers \"{first_layer}\" \"{last_layer}\") (net {net_code}))\n")

    def _calculate_board_bounds(self, board: Board, margin: float = 5.0) -> Tuple[float, float, float, float]:
        """Calculate board bounding box from component positions.

        Args:
            board: Board containing components
            margin: Margin to add around components (mm)

        Returns:
            Tuple of (min_x, min_y, max_x, max_y) with margin applied
        """
        if not board.components:
            # Default board size if no components
            return (0, 0, 100, 100)

        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')

        for comp in board.components.values():
            x, y = comp.position

            # Account for pad positions to get actual footprint extent
            for pad in comp.pads:
                pad_x = x + pad.position_offset[0]
                pad_y = y + pad.position_offset[1]
                pad_w, pad_h = pad.size

                # Expand bounds to include this pad
                min_x = min(min_x, pad_x - pad_w / 2)
                min_y = min(min_y, pad_y - pad_h / 2)
                max_x = max(max_x, pad_x + pad_w / 2)
                max_y = max(max_y, pad_y + pad_h / 2)

        # If no pads found, use component positions
        if min_x == float('inf'):
            for comp in board.components.values():
                x, y = comp.position
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

        # Apply margin
        min_x -= margin
        min_y -= margin
        max_x += margin
        max_y += margin

        # Round to nice values (0.5mm grid)
        min_x = round(min_x * 2) / 2
        min_y = round(min_y * 2) / 2
        max_x = round(max_x * 2) / 2
        max_y = round(max_y * 2) / 2

        return (min_x, min_y, max_x, max_y)

    def _write_board_outline(self, f: TextIO, board: Board) -> None:
        """Write board outline on Edge.Cuts layer.

        Creates a closed rectangular outline around the board.

        Args:
            f: File object to write to
            board: Board to calculate outline for
        """
        min_x, min_y, max_x, max_y = self._calculate_board_bounds(board)

        f.write("\n")

        # Write four lines forming a closed rectangle (KiCad 8/9 format with stroke)
        # Bottom edge
        f.write(f"  (gr_line (start {min_x} {min_y}) (end {max_x} {min_y}) "
                f"(stroke (width 0.1) (type solid)) (layer \"Edge.Cuts\") "
                f"(uuid \"{uuid.uuid4()}\"))\n")
        # Right edge
        f.write(f"  (gr_line (start {max_x} {min_y}) (end {max_x} {max_y}) "
                f"(stroke (width 0.1) (type solid)) (layer \"Edge.Cuts\") "
                f"(uuid \"{uuid.uuid4()}\"))\n")
        # Top edge
        f.write(f"  (gr_line (start {max_x} {max_y}) (end {min_x} {max_y}) "
                f"(stroke (width 0.1) (type solid)) (layer \"Edge.Cuts\") "
                f"(uuid \"{uuid.uuid4()}\"))\n")
        # Left edge
        f.write(f"  (gr_line (start {min_x} {max_y}) (end {min_x} {min_y}) "
                f"(stroke (width 0.1) (type solid)) (layer \"Edge.Cuts\") "
                f"(uuid \"{uuid.uuid4()}\"))\n")

    def _write_zones(self, f: TextIO, board: Board) -> None:
        """Write copper zones (pours) to the KiCad file.

        Auto-generates a GND pour on B.Cu layer if:
        - Board has a GND net
        - No zones are already defined

        Args:
            f: File object to write to
            board: Board containing zones and nets
        """
        # Auto-generate GND pour if not already defined
        if not board.zones:
            gnd_net = board.nets.get('GND')
            if gnd_net:
                min_x, min_y, max_x, max_y = self._calculate_board_bounds(board)
                # Create GND pour on bottom layer covering the board area
                gnd_zone = CopperZone(
                    net_name='GND',
                    net_code=gnd_net.code,
                    layer='B.Cu',
                    outline=[
                        (min_x, min_y),
                        (max_x, min_y),
                        (max_x, max_y),
                        (min_x, max_y),
                    ],
                    priority=0,
                    clearance=0.3,
                    min_thickness=0.25,
                    thermal_gap=0.5,
                    thermal_bridge=0.5,
                )
                board.zones.append(gnd_zone)

        # Write all zones
        for zone in board.zones:
            self._write_zone(f, zone)

    def _write_zone(self, f: TextIO, zone: CopperZone) -> None:
        """Write a single copper zone to the KiCad file.

        Args:
            f: File object to write to
            zone: CopperZone to write
        """
        zone_uuid = str(uuid.uuid4())

        # Zone header with net name (not code) and layer
        f.write(f"\n  (zone (net \"{zone.net_name}\") (layer \"{zone.layer}\") (uuid \"{zone_uuid}\")\n")
        f.write(f"    (name \"{zone.net_name}_pour\")\n")
        f.write(f"    (hatch edge 0.5)\n")

        if zone.priority > 0:
            f.write(f"    (priority {zone.priority})\n")

        # Thermal relief connection for pads
        f.write(f"    (connect_pads (clearance {zone.clearance}))\n")
        f.write(f"    (min_thickness {zone.min_thickness})\n")

        # Fill settings with island removal mode (required by KiCad)
        f.write(f"    (fill yes (thermal_gap {zone.thermal_gap}) (thermal_bridge_width {zone.thermal_bridge}) (island_removal_mode 1) (island_area_min 10))\n")

        # Write polygon outline
        f.write("    (polygon\n")
        f.write("      (pts\n")
        for x, y in zone.outline:
            f.write(f"        (xy {x} {y})\n")
        f.write("      )\n")
        f.write("    )\n")

        f.write("  )\n")
