"""Load KiCad `.kicad_pcb` files without `pcbnew` (text/S-expression).

This loader is intentionally partial: it extracts the data needed for routing
and analysis (layers, outline bounds, footprints/pads, and net connectivity).

It is useful when:
- `.kicad_pcb` was produced by KiCad 9 (system `pcbnew` may be older)
- routing is executed in a virtualenv without the KiCad Python bindings
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pcb_tool.data_model import (
    Board,
    Component,
    Net,
    Pad,
    TraceSegment,
    Via,
    VALID_COPPER_LAYERS,
)
from pcb_tool.sexpr import load as load_sexpr


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _first(sexpr: list, tag: str) -> list | None:
    for item in sexpr:
        if isinstance(item, list) and item and item[0] == tag:
            return item
    return None


def _all(sexpr: list, tag: str) -> list[list]:
    return [item for item in sexpr if isinstance(item, list) and item and item[0] == tag]


def _layer_stack_from_layers_block(layers_block: list) -> list[str]:
    copper: set[str] = set()
    for entry in layers_block[1:]:
        if not (isinstance(entry, list) and len(entry) >= 2):
            continue
        name = entry[1]
        if isinstance(name, str) and name in VALID_COPPER_LAYERS:
            copper.add(name)

    def _key(layer: str) -> tuple[int, int]:
        if layer == "F.Cu":
            return (0, 0)
        if layer == "B.Cu":
            return (2, 0)
        if layer.startswith("In") and layer.endswith(".Cu"):
            try:
                n = int(layer[2:-3])
            except ValueError:
                n = 0
            return (1, n)
        return (3, 0)

    return sorted(copper, key=_key)


@dataclass(frozen=True)
class KicadTextLoadResult:
    board: Board
    warnings: list[str]


def load_board_kicad_pcb(path: str | Path) -> KicadTextLoadResult:
    """Load a `.kicad_pcb` file into the internal `Board` model."""
    path = Path(path)
    tree = load_sexpr(path)
    if not (isinstance(tree, list) and tree and tree[0] == "kicad_pcb"):
        raise ValueError(f"Not a kicad_pcb file: {path}")

    warnings: list[str] = []
    board = Board()
    board.source_file = path

    # Layers
    layers_block = _first(tree, "layers")
    if layers_block:
        board.layers = _layer_stack_from_layers_block(layers_block)

    # Nets (code -> name)
    net_by_code: dict[str, str] = {}
    for net_def in _all(tree, "net"):
        if len(net_def) >= 3:
            net_by_code[str(net_def[1])] = str(net_def[2])

    # Outline bounds (Edge.Cuts)
    xs: list[float] = []
    ys: list[float] = []
    for gr_line in _all(tree, "gr_line"):
        layer = _first(gr_line, "layer")
        if not (layer and len(layer) >= 2 and layer[1] == "Edge.Cuts"):
            continue
        start = _first(gr_line, "start")
        end = _first(gr_line, "end")
        if not (start and end and len(start) >= 3 and len(end) >= 3):
            continue
        xs.extend([_as_float(start[1]), _as_float(end[1])])
        ys.extend([_as_float(start[2]), _as_float(end[2])])

    if xs and ys:
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        board.width = max_x - min_x
        board.height = max_y - min_y

    # Footprints and pads -> connectivity
    for fp in _all(tree, "footprint"):
        if len(fp) < 2:
            continue

        fp_name = str(fp[1])
        layer = _first(fp, "layer")
        at = _first(fp, "at")

        if not (layer and len(layer) >= 2 and isinstance(layer[1], str)):
            fp_layer = "F.Cu"
        else:
            fp_layer = str(layer[1])

        x = _as_float(at[1]) if at and len(at) >= 3 else 0.0
        y = _as_float(at[2]) if at and len(at) >= 3 else 0.0
        rot = _as_float(at[3]) if at and len(at) >= 4 else 0.0

        ref = None
        value = None
        for prop in _all(fp, "property"):
            if len(prop) >= 3 and prop[1] == "Reference":
                ref = str(prop[2])
            if len(prop) >= 3 and prop[1] == "Value":
                value = str(prop[2])

        if ref is None:
            fp_text_ref = next(
                (t for t in _all(fp, "fp_text") if len(t) >= 3 and t[1] == "reference"),
                None,
            )
            if fp_text_ref and len(fp_text_ref) >= 3:
                ref = str(fp_text_ref[2])

        if value is None:
            fp_text_val = next(
                (t for t in _all(fp, "fp_text") if len(t) >= 3 and t[1] == "value"),
                None,
            )
            if fp_text_val and len(fp_text_val) >= 3:
                value = str(fp_text_val[2])

        if ref is None:
            warnings.append(f"footprint without Reference property: {fp_name}")
            continue

        comp = Component(
            ref=ref,
            value=value or "",
            footprint=fp_name,
            position=(x, y),
            rotation=rot,
            layer=fp_layer,
        )

        for pad in _all(fp, "pad"):
            if len(pad) < 2:
                continue

            pad_num = str(pad[1])
            pad_at = _first(pad, "at")
            pad_size = _first(pad, "size")
            pad_drill = _first(pad, "drill")
            pad_net = _first(pad, "net")

            ox = _as_float(pad_at[1]) if pad_at and len(pad_at) >= 3 else 0.0
            oy = _as_float(pad_at[2]) if pad_at and len(pad_at) >= 3 else 0.0
            w = _as_float(pad_size[1]) if pad_size and len(pad_size) >= 3 else 0.0
            h = _as_float(pad_size[2]) if pad_size and len(pad_size) >= 3 else w
            drill = _as_float(pad_drill[1]) if pad_drill and len(pad_drill) >= 2 else None

            net_name = ""
            if pad_net and len(pad_net) >= 2:
                # Prefer explicit net name; fall back to code lookup.
                if len(pad_net) >= 3 and str(pad_net[2]):
                    net_name = str(pad_net[2])
                else:
                    net_name = net_by_code.get(str(pad_net[1]), "")

            comp.pads.append(
                Pad(
                    number=pad_num,
                    position_offset=(ox, oy),
                    size=(w, h),
                    drill=drill,
                    net_name=net_name,
                )
            )

            if net_name:
                net = board.nets.get(net_name)
                if net is None:
                    # Use the KiCad net code if known, else derive a stable one.
                    code = next((k for k, v in net_by_code.items() if v == net_name), None)
                    net = Net(name=net_name, code=str(code or (len(board.nets) + 1)))
                    board.add_net(net)
                net.add_connection(ref, pad_num)

        board.add_component(comp)

    # Segments/vias (existing routing) -> board nets.
    for seg in _all(tree, "segment"):
        start = _first(seg, "start")
        end = _first(seg, "end")
        width = _first(seg, "width")
        layer = _first(seg, "layer")
        net = _first(seg, "net")
        if not (start and end and width and layer and net):
            continue
        if len(start) < 3 or len(end) < 3 or len(width) < 2 or len(layer) < 2 or len(net) < 2:
            continue

        net_name = net_by_code.get(str(net[1]), "")
        if not net_name:
            continue

        if net_name not in board.nets:
            board.add_net(Net(name=net_name, code=str(net[1])))

        try:
            segment = TraceSegment(
                net_name=net_name,
                start=(_as_float(start[1]), _as_float(start[2])),
                end=(_as_float(end[1]), _as_float(end[2])),
                layer=str(layer[1]),
                width=_as_float(width[1], 0.0),
            )
        except Exception:
            continue

        board.nets[net_name].add_segment(segment)

    for via in _all(tree, "via"):
        # KiCad may include a via type atom: `(via micro ...)`
        offset = 1
        via_kind = None
        if len(via) >= 2 and isinstance(via[1], str) and via[1] not in {"at", "size", "drill", "layers", "net"}:
            via_kind = via[1]
            offset = 2

        at = _first(via[offset:], "at")
        size = _first(via[offset:], "size")
        drill = _first(via[offset:], "drill")
        layers = _first(via[offset:], "layers")
        net = _first(via[offset:], "net")
        if not (at and size and drill and layers and net):
            continue
        if len(at) < 3 or len(size) < 2 or len(drill) < 2 or len(layers) < 3 or len(net) < 2:
            continue

        net_name = net_by_code.get(str(net[1]), "")
        if not net_name:
            continue

        if net_name not in board.nets:
            board.add_net(Net(name=net_name, code=str(net[1])))

        layer_names = tuple(str(l) for l in layers[1:] if isinstance(l, str))
        if len(layer_names) < 2:
            continue

        # Map KiCad via kind to our coarse via_type categories.
        if "F.Cu" in layer_names and "B.Cu" in layer_names:
            via_type = "through"
        elif "F.Cu" in layer_names or "B.Cu" in layer_names:
            via_type = "blind"
        else:
            via_type = "buried"
        if via_kind in {"blind", "buried"}:
            via_type = via_kind

        try:
            via_obj = Via(
                net_name=net_name,
                position=(_as_float(at[1]), _as_float(at[2])),
                size=_as_float(size[1], 0.0),
                drill=_as_float(drill[1], 0.0),
                layers=layer_names,
                via_type=via_type,
            )
        except Exception:
            continue

        board.nets[net_name].add_via(via_obj)

    return KicadTextLoadResult(board=board, warnings=warnings)
