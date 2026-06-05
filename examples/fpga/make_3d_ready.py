#!/usr/bin/env python3
"""Make a routed .kicad_pcb "3D-ready" by replacing footprints from libraries.

`pardal.kicad_writer.KicadWriter` emits minimal footprints (pads only), which are
fine for routing and basic visualization but typically lack `(model ...)` entries.
KiCad's 3D viewer needs those model references to render components.

This script:
- Loads an existing routed `.kicad_pcb` via the pcbnew Python API
- Replaces selected footprints with standard KiCad library footprints
- Preserves position/orientation and pad net assignments (by pad number/name)
- Saves a new `.kicad_pcb` suitable for `kicad-cli pcb render`

Run with system python (KiCad's pcbnew module):
  python3 pardal-pcb/examples/fpga/make_3d_ready.py \
    pardal-pcb/examples/fpga/fpga_routed_with_widths.kicad_pcb \
    pardal-pcb/examples/fpga/fpga_routed_with_widths.lib.kicad_pcb
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pcbnew


@dataclass(frozen=True)
class FootprintMapping:
    lib: str
    name: str

    @property
    def pretty_dir(self) -> str:
        return f"{self.lib}.pretty"


LIB_ROOT = Path("/usr/share/kicad/footprints")

MAPPING_BY_FOOTPRINT = {
    # Our generated names -> KiCad library footprints with 3D models.
    "TQFP-32_7x7mm_P0.8mm": FootprintMapping("Package_QFP", "TQFP-32_7x7mm_P0.8mm"),
    "C_0603_1608Metric": FootprintMapping("Capacitor_SMD", "C_0603_1608Metric"),
    "PinHeader_2x05_P1.27mm_Vertical": FootprintMapping(
        "Connector_PinHeader_1.27mm", "PinHeader_2x05_P1.27mm_Vertical"
    ),
    "PinHeader_1x02_P2.54mm_Vertical": FootprintMapping(
        "Connector_PinHeader_2.54mm", "PinHeader_1x02_P2.54mm_Vertical"
    ),
}

def _kicad_str(value: object) -> str:
    get_chars = getattr(value, "GetChars", None)
    if callable(get_chars):
        return str(get_chars())
    return str(value)


def _load_library_footprint(mapping: FootprintMapping) -> pcbnew.FOOTPRINT:
    lib_dir = LIB_ROOT / mapping.pretty_dir
    if not lib_dir.is_dir():
        raise FileNotFoundError(f"Library not found: {lib_dir}")

    # Use pcbnew's footprint loader to avoid version-specific IO classes.
    fp = pcbnew.FootprintLoad(str(lib_dir), mapping.name)
    if fp is None:
        raise FileNotFoundError(f"Footprint not found: {mapping.lib}:{mapping.name}")
    return fp


def _copy_pad_nets(old_fp: pcbnew.FOOTPRINT, new_fp: pcbnew.FOOTPRINT) -> None:
    old_by_name = {pad.GetName(): pad for pad in old_fp.Pads()}
    for pad in new_fp.Pads():
        old = old_by_name.get(pad.GetName())
        if old is None:
            continue
        pad.SetNet(old.GetNet())


def replace_footprints(board: pcbnew.BOARD) -> int:
    replaced = 0
    for fp in list(board.GetFootprints()):
        current = _kicad_str(fp.GetFPID().GetLibItemName())
        mapping = MAPPING_BY_FOOTPRINT.get(current)
        if mapping is None:
            continue

        new_fp = _load_library_footprint(mapping)
        new_fp.SetReference(fp.GetReference())
        new_fp.SetValue(fp.GetValue())
        new_fp.SetPosition(fp.GetPosition())
        new_fp.SetOrientation(fp.GetOrientation())
        new_fp.SetLayer(fp.GetLayer())

        _copy_pad_nets(fp, new_fp)

        board.Remove(fp)
        board.Add(new_fp)
        replaced += 1

    return replaced


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip())
        return 2

    src = Path(argv[1])
    dst = Path(argv[2])
    if not src.exists():
        raise FileNotFoundError(src)

    board = pcbnew.LoadBoard(str(src))
    replaced = replace_footprints(board)
    board.Save(str(dst))

    print(f"Replaced {replaced} footprints -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
