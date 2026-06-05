"""Minimal RoutingBoard port for DSN-first ingestion.

This is a scaffold to carry DSN-derived board data into the FreeRouting
ports. It intentionally keeps fields simple (Python dict/list where needed)
so later ports can replace them with richer item/shape models.
"""

from collections import List

from python import Python, PythonObject

from .layer import Layer
from .layer_structure import LayerStructure
from ...dsn import (
    parse_dsn_boundary_bbox_mm,
    parse_dsn_layers,
    parse_dsn_net_names,
    parse_dsn_net_pins,
    parse_dsn_pin_positions_mm,
    parse_dsn_wiring_mm,
)

comptime py = Python


fn _py_is_none(o: PythonObject) raises -> Bool:
    var operator = py.import_module("operator")
    return Bool(py=operator.is_(o, py.none()))


fn _layers_sorted_by_index(layer_recs: PythonObject) raises -> List[String]:
    var names = List[String]()
    var idxs = List[Int]()
    for rec in layer_recs:
        var name = String(py=rec[PythonObject(String("name"))])
        var idx_obj = rec[PythonObject(String("index"))]
        var idx = 0
        if _py_is_none(idx_obj):
            idx = len(names)
        else:
            idx = Int(py=idx_obj)
        names.append(name)
        idxs.append(idx)

    var out = List[String]()
    var used = List[Bool](length=len(names), fill=False)
    var k = 0
    while k < len(names):
        var best = -1
        var best_idx = 1_000_000_000
        var i = 0
        while i < len(names):
            if not used[i] and idxs[i] < best_idx:
                best_idx = idxs[i]
                best = i
            i += 1
        if best < 0:
            break
        used[best] = True
        out.append(names[best])
        k += 1
    return out^


@fieldwise_init
struct RoutingBoard(Movable):
    var layer_structure: LayerStructure
    var board_bbox_mm: PythonObject
    var net_names: PythonObject
    var net_pins: PythonObject
    var pin_positions_mm: PythonObject
    var wiring_mm: PythonObject

    fn net_count(self) raises -> Int:
        return Int(py=self.net_names.__len__())

    fn pin_count(self) raises -> Int:
        return Int(py=self.pin_positions_mm.__len__())

    fn wire_count(self) raises -> Int:
        var wires = self.wiring_mm[PythonObject(String("wires"))]
        return Int(py=wires.__len__())

    fn via_count(self) raises -> Int:
        var vias = self.wiring_mm[PythonObject(String("vias"))]
        return Int(py=vias.__len__())


fn routing_board_from_dsn_src(src: String) raises -> RoutingBoard:
    var layer_recs = parse_dsn_layers(src)
    var names = _layers_sorted_by_index(layer_recs)
    var layers = List[Layer]()
    for rec in layer_recs:
        var name = String(py=rec[PythonObject(String("name"))])
        var kind_obj = rec[PythonObject(String("type"))]
        var kind = String("")
        if not _py_is_none(kind_obj):
            kind = String(py=kind_obj)
        var is_signal = True
        if kind != String(""):
            is_signal = kind == String("signal")
        layers.append(Layer(name, is_signal))

    # Ensure LayerStructure order matches sorted names.
    var sorted_layers = List[Layer]()
    for n in names:
        var found = False
        for l in layers:
            if l.name == n:
                sorted_layers.append(l.copy())
                found = True
                break
        if not found:
            sorted_layers.append(Layer(n, True))

    var ls = LayerStructure(sorted_layers^)
    var bb = parse_dsn_boundary_bbox_mm(src)
    var net_names = parse_dsn_net_names(src)
    var net_pins = parse_dsn_net_pins(src)
    var pin_pos = parse_dsn_pin_positions_mm(src)
    var wiring = parse_dsn_wiring_mm(src)
    return RoutingBoard(ls^, bb, net_names, net_pins, pin_pos, wiring)


fn routing_board_from_dsn_path(path: String) raises -> RoutingBoard:
    var pathlib = py.import_module("pathlib")
    var txt = pathlib.Path(PythonObject(path)).read_text()
    return routing_board_from_dsn_src(String(py=txt))
