"""
Footprint Templates Library

Pre-defined footprint templates with automatic pad generation.
Eliminates manual pad positioning for common packages.

Supported packages:
- QFP (TQFP, LQFP) - 32, 44, 48, 64, 100 pins
- SMD passives (0402, 0603, 0805, 1206)
- Pin headers (1xN, 2xN)
- SOT packages (SOT-23, SOT-223)
- SOP/SOIC packages
"""

import math
from typing import List, Tuple, Optional, Dict, Any
from pcb_tool.data_model import Pad


def generate_qfp_pads(
    pin_count: int,
    pitch: float,
    body_size: Tuple[float, float],
    pad_size: Tuple[float, float] = (0.5, 1.2),
) -> List[Pad]:
    """Generate pads for QFP (Quad Flat Package) footprints.

    Pins are numbered counter-clockwise starting from pin 1 at top-left of left side.

    Args:
        pin_count: Total number of pins (must be divisible by 4)
        pitch: Pin pitch in mm
        body_size: (width, height) of package body in mm
        pad_size: (width, height) of each pad in mm

    Returns:
        List of Pad objects with correct positions

    Example:
        >>> pads = generate_qfp_pads(32, pitch=0.8, body_size=(7.0, 7.0))
        >>> len(pads)
        32
    """
    if pin_count % 4 != 0:
        raise ValueError(f"QFP pin count must be divisible by 4, got {pin_count}")

    # Note: For QFPs, users typically specify pad size as (pad_width, pad_length),
    # where pad_length is the dimension extending away from the body.
    pad_width, pad_length = pad_size

    pads = []
    pins_per_side = pin_count // 4
    half_body_w = body_size[0] / 2
    half_body_h = body_size[1] / 2

    # Calculate starting offset for pins (centered on each side)
    start_offset = -((pins_per_side - 1) * pitch) / 2

    # Left side (pins 1 to pins_per_side) - pads are horizontal, pointing left
    for i in range(pins_per_side):
        pin_num = i + 1
        y_offset = start_offset + i * pitch
        x_offset = -half_body_w - pad_length / 2 + 0.3  # Slight inward offset
        pads.append(
            Pad(
                number=pin_num,
                position_offset=(x_offset, y_offset),
                size=(pad_length, pad_width),
                shape="rect",
            )
        )

    # Bottom side (pins pins_per_side+1 to 2*pins_per_side) - pads are vertical
    for i in range(pins_per_side):
        pin_num = pins_per_side + i + 1
        x_offset = start_offset + i * pitch
        y_offset = half_body_h + pad_length / 2 - 0.3
        pads.append(
            Pad(
                number=pin_num,
                position_offset=(x_offset, y_offset),
                size=(pad_width, pad_length),
                shape="rect",
            )
        )

    # Right side (pins 2*pins_per_side+1 to 3*pins_per_side) - pads horizontal, pointing right
    for i in range(pins_per_side):
        pin_num = 2 * pins_per_side + i + 1
        y_offset = start_offset + (pins_per_side - 1 - i) * pitch  # Reverse order
        x_offset = half_body_w + pad_length / 2 - 0.3
        pads.append(
            Pad(
                number=pin_num,
                position_offset=(x_offset, -y_offset),
                size=(pad_length, pad_width),
                shape="rect",
            )
        )

    # Top side (pins 3*pins_per_side+1 to 4*pins_per_side) - pads vertical
    for i in range(pins_per_side):
        pin_num = 3 * pins_per_side + i + 1
        x_offset = start_offset + (pins_per_side - 1 - i) * pitch  # Reverse order
        y_offset = -half_body_h - pad_length / 2 + 0.3
        pads.append(
            Pad(
                number=pin_num,
                position_offset=(-x_offset, y_offset),
                size=(pad_width, pad_length),
                shape="rect",
            )
        )

    return pads


def generate_header_pads(
    rows: int,
    cols: int,
    pitch: float,
    pad_size: Tuple[float, float] = (1.0, 1.0),
    drill: Optional[float] = 0.8,
) -> List[Pad]:
    """Generate pads for pin header footprints.

    Pins are numbered by row then column (standard header numbering).

    Args:
        rows: Number of rows (1 for single-row, 2 for dual-row)
        cols: Number of columns
        pitch: Pin pitch in mm
        pad_size: (width, height) of each pad in mm
        drill: Drill diameter for through-hole pads (None for SMD)

    Returns:
        List of Pad objects

    Example:
        >>> pads = generate_header_pads(rows=2, cols=5, pitch=1.27)
        >>> len(pads)
        10
    """
    pads = []
    pin_num = 1

    # Calculate center offset
    center_x = (rows - 1) * pitch / 2
    center_y = (cols - 1) * pitch / 2

    for col in range(cols):
        for row in range(rows):
            x_offset = row * pitch - center_x
            y_offset = col * pitch - center_y
            pads.append(
                Pad(
                    number=pin_num,
                    position_offset=(x_offset, y_offset),
                    size=pad_size,
                    shape="circle" if drill else "rect",
                    drill=drill,
                )
            )
            pin_num += 1

    return pads


def generate_two_pin_smd_pads(
    pad_spacing: float, pad_size: Tuple[float, float]
) -> List[Pad]:
    """Generate pads for 2-pin SMD components (resistors, capacitors).

    Args:
        pad_spacing: Center-to-center distance between pads in mm
        pad_size: (width, height) of each pad in mm

    Returns:
        List of 2 Pad objects
    """
    half_spacing = pad_spacing / 2
    return [
        Pad(number=1, position_offset=(-half_spacing, 0), size=pad_size, shape="rect"),
        Pad(number=2, position_offset=(half_spacing, 0), size=pad_size, shape="rect"),
    ]


def generate_sot23_pads(pins: int = 3) -> List[Pad]:
    """Generate pads for SOT-23 packages.

    Args:
        pins: Number of pins (3, 5, or 6)

    Returns:
        List of Pad objects
    """
    if pins == 3:
        return [
            Pad(number=1, position_offset=(-0.95, 1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=2, position_offset=(0.95, 1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=3, position_offset=(0, -1.1), size=(0.6, 0.7), shape="rect"),
        ]
    elif pins == 5:
        return [
            Pad(number=1, position_offset=(-0.95, 1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=2, position_offset=(0, 1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=3, position_offset=(0.95, 1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=4, position_offset=(0.95, -1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=5, position_offset=(-0.95, -1.1), size=(0.6, 0.7), shape="rect"),
        ]
    elif pins == 6:
        return [
            Pad(number=1, position_offset=(-0.95, 1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=2, position_offset=(0, 1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=3, position_offset=(0.95, 1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=4, position_offset=(0.95, -1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=5, position_offset=(0, -1.1), size=(0.6, 0.7), shape="rect"),
            Pad(number=6, position_offset=(-0.95, -1.1), size=(0.6, 0.7), shape="rect"),
        ]
    else:
        raise ValueError(f"SOT-23 supports 3, 5, or 6 pins, got {pins}")


def generate_soic_pads(
    pins: int, pitch: float = 1.27, body_width: float = 3.9
) -> List[Pad]:
    """Generate pads for SOIC packages.

    Args:
        pins: Number of pins (must be even, typically 8, 14, 16)
        pitch: Pin pitch in mm (default 1.27mm)
        body_width: Body width in mm

    Returns:
        List of Pad objects
    """
    if pins % 2 != 0:
        raise ValueError(f"SOIC pin count must be even, got {pins}")

    pads = []
    pins_per_side = pins // 2
    start_offset = -((pins_per_side - 1) * pitch) / 2
    pad_center_x = body_width / 2 + 0.5  # Pad extends beyond body

    # Left side (pins 1 to pins_per_side)
    for i in range(pins_per_side):
        pin_num = i + 1
        y_offset = start_offset + i * pitch
        pads.append(
            Pad(
                number=pin_num,
                position_offset=(-pad_center_x, y_offset),
                size=(0.6, 1.5),
                shape="rect",
            )
        )

    # Right side (pins pins_per_side+1 to pins) - numbered in reverse
    for i in range(pins_per_side):
        pin_num = pins - i
        y_offset = start_offset + i * pitch
        pads.append(
            Pad(
                number=pin_num,
                position_offset=(pad_center_x, y_offset),
                size=(0.6, 1.5),
                shape="rect",
            )
        )

    return sorted(pads, key=lambda p: p.number)


# Footprint template registry
FOOTPRINT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    # QFP packages
    "TQFP-32_7x7mm_P0.8mm": {
        "generator": "qfp",
        "pin_count": 32,
        "pitch": 0.8,
        "body_size": (7.0, 7.0),
        "pad_size": (0.5, 1.2),
    },
    "TQFP-44_10x10mm_P0.8mm": {
        "generator": "qfp",
        "pin_count": 44,
        "pitch": 0.8,
        "body_size": (10.0, 10.0),
        "pad_size": (0.5, 1.2),
    },
    "TQFP-48_7x7mm_P0.5mm": {
        "generator": "qfp",
        "pin_count": 48,
        "pitch": 0.5,
        "body_size": (7.0, 7.0),
        "pad_size": (0.3, 1.0),
    },
    "LQFP-64_10x10mm_P0.5mm": {
        "generator": "qfp",
        "pin_count": 64,
        "pitch": 0.5,
        "body_size": (10.0, 10.0),
        "pad_size": (0.3, 1.0),
    },
    "LQFP-100_14x14mm_P0.5mm": {
        "generator": "qfp",
        "pin_count": 100,
        "pitch": 0.5,
        "body_size": (14.0, 14.0),
        "pad_size": (0.3, 1.0),
    },
    # SMD Passives (Resistors, Capacitors)
    "R_0402_1005Metric": {
        "generator": "two_pin_smd",
        "pad_spacing": 0.9,
        "pad_size": (0.5, 0.5),
    },
    "R_0603_1608Metric": {
        "generator": "two_pin_smd",
        "pad_spacing": 1.5,
        "pad_size": (0.8, 0.8),
    },
    "R_0805_2012Metric": {
        "generator": "two_pin_smd",
        "pad_spacing": 1.9,
        "pad_size": (1.0, 1.0),
    },
    "R_1206_3216Metric": {
        "generator": "two_pin_smd",
        "pad_spacing": 3.0,
        "pad_size": (1.0, 1.5),
    },
    "C_0402_1005Metric": {
        "generator": "two_pin_smd",
        "pad_spacing": 0.9,
        "pad_size": (0.5, 0.5),
    },
    "C_0603_1608Metric": {
        "generator": "two_pin_smd",
        "pad_spacing": 1.6,
        "pad_size": (0.9, 0.9),
    },
    "C_0805_2012Metric": {
        "generator": "two_pin_smd",
        "pad_spacing": 1.9,
        "pad_size": (1.0, 1.0),
    },
    "C_1206_3216Metric": {
        "generator": "two_pin_smd",
        "pad_spacing": 3.0,
        "pad_size": (1.0, 1.5),
    },
    # Pin Headers
    "PinHeader_1x02_P2.54mm_Vertical": {
        "generator": "header",
        "rows": 1,
        "cols": 2,
        "pitch": 2.54,
        "pad_size": (1.7, 1.7),
        "drill": 1.0,
    },
    "PinHeader_1x03_P2.54mm_Vertical": {
        "generator": "header",
        "rows": 1,
        "cols": 3,
        "pitch": 2.54,
        "pad_size": (1.7, 1.7),
        "drill": 1.0,
    },
    "PinHeader_1x04_P2.54mm_Vertical": {
        "generator": "header",
        "rows": 1,
        "cols": 4,
        "pitch": 2.54,
        "pad_size": (1.7, 1.7),
        "drill": 1.0,
    },
    "PinHeader_1x06_P2.54mm_Vertical": {
        "generator": "header",
        "rows": 1,
        "cols": 6,
        "pitch": 2.54,
        "pad_size": (1.7, 1.7),
        "drill": 1.0,
    },
    "PinHeader_2x03_P2.54mm_Vertical": {
        "generator": "header",
        "rows": 2,
        "cols": 3,
        "pitch": 2.54,
        "pad_size": (1.7, 1.7),
        "drill": 1.0,
    },
    "PinHeader_2x05_P2.54mm_Vertical": {
        "generator": "header",
        "rows": 2,
        "cols": 5,
        "pitch": 2.54,
        "pad_size": (1.7, 1.7),
        "drill": 1.0,
    },
    "PinHeader_2x05_P1.27mm_Vertical": {
        "generator": "header",
        "rows": 2,
        "cols": 5,
        "pitch": 1.27,
        "pad_size": (0.7, 0.7),
        "drill": 0.5,
    },
    # SOT packages
    "SOT-23": {
        "generator": "sot23",
        "pins": 3,
    },
    "SOT-23-5": {
        "generator": "sot23",
        "pins": 5,
    },
    "SOT-23-6": {
        "generator": "sot23",
        "pins": 6,
    },
    # SOIC packages
    "SOIC-8_3.9x4.9mm_P1.27mm": {
        "generator": "soic",
        "pins": 8,
        "pitch": 1.27,
        "body_width": 3.9,
    },
    "SOIC-14_3.9x8.7mm_P1.27mm": {
        "generator": "soic",
        "pins": 14,
        "pitch": 1.27,
        "body_width": 3.9,
    },
    "SOIC-16_3.9x9.9mm_P1.27mm": {
        "generator": "soic",
        "pins": 16,
        "pitch": 1.27,
        "body_width": 3.9,
    },
}

# Aliases for common shorthand names
FOOTPRINT_ALIASES = {
    "R_0402": "R_0402_1005Metric",
    "R_0603": "R_0603_1608Metric",
    "R_0805": "R_0805_2012Metric",
    "R_1206": "R_1206_3216Metric",
    "C_0402": "C_0402_1005Metric",
    "C_0603": "C_0603_1608Metric",
    "C_0805": "C_0805_2012Metric",
    "C_1206": "C_1206_3216Metric",
    "TQFP-32": "TQFP-32_7x7mm_P0.8mm",
    "TQFP-44": "TQFP-44_10x10mm_P0.8mm",
    "TQFP-48": "TQFP-48_7x7mm_P0.5mm",
    "LQFP-64": "LQFP-64_10x10mm_P0.5mm",
    "LQFP-100": "LQFP-100_14x14mm_P0.5mm",
    "SOIC-8": "SOIC-8_3.9x4.9mm_P1.27mm",
    "SOIC-14": "SOIC-14_3.9x8.7mm_P1.27mm",
    "SOIC-16": "SOIC-16_3.9x9.9mm_P1.27mm",
}


def get_template(footprint_name: str) -> Optional[Dict[str, Any]]:
    """Get footprint template by name or alias.

    Args:
        footprint_name: Full footprint name or shorthand alias

    Returns:
        Template dictionary or None if not found
    """
    # Check aliases first
    if footprint_name in FOOTPRINT_ALIASES:
        footprint_name = FOOTPRINT_ALIASES[footprint_name]

    return FOOTPRINT_TEMPLATES.get(footprint_name)


def generate_pads(footprint_name: str) -> List[Pad]:
    """Generate pads for a footprint by name.

    Args:
        footprint_name: Footprint name (full or alias)

    Returns:
        List of Pad objects

    Raises:
        ValueError: If footprint not found in templates

    Example:
        >>> pads = generate_pads("TQFP-32")
        >>> len(pads)
        32
        >>> pads = generate_pads("R_0805")
        >>> len(pads)
        2
    """
    template = get_template(footprint_name)
    if template is None:
        raise ValueError(
            f"Unknown footprint: {footprint_name}. "
            f"Available: {', '.join(list(FOOTPRINT_TEMPLATES.keys())[:10])}..."
        )

    generator = template["generator"]

    if generator == "qfp":
        return generate_qfp_pads(
            pin_count=template["pin_count"],
            pitch=template["pitch"],
            body_size=template["body_size"],
            pad_size=template.get("pad_size", (0.5, 1.2)),
        )
    elif generator == "header":
        return generate_header_pads(
            rows=template["rows"],
            cols=template["cols"],
            pitch=template["pitch"],
            pad_size=template.get("pad_size", (1.0, 1.0)),
            drill=template.get("drill"),
        )
    elif generator == "two_pin_smd":
        return generate_two_pin_smd_pads(
            pad_spacing=template["pad_spacing"], pad_size=template["pad_size"]
        )
    elif generator == "sot23":
        return generate_sot23_pads(pins=template["pins"])
    elif generator == "soic":
        return generate_soic_pads(
            pins=template["pins"],
            pitch=template.get("pitch", 1.27),
            body_width=template.get("body_width", 3.9),
        )
    else:
        raise ValueError(f"Unknown generator type: {generator}")


def list_templates() -> List[str]:
    """List all available footprint templates.

    Returns:
        Sorted list of template names
    """
    return sorted(FOOTPRINT_TEMPLATES.keys())


def list_aliases() -> Dict[str, str]:
    """List all footprint aliases.

    Returns:
        Dictionary mapping alias to full name
    """
    return FOOTPRINT_ALIASES.copy()
