"""Minimal `SearchTreeObject` port for early ShapeSearchTree parity.

FreeRouting's `SearchTreeObject` is a polymorphic base for board items (traces,
vias, rooms, keepouts, ...). For the incremental Mojo port we start with a
single concrete object carrying the bits needed by `ShapeSearchTree90Degree`.
"""

from collections import List

from ..geometry.planar.int_box import IntBox
from ..geometry.planar.int_octagon import IntOctagon
from ..geometry.planar.int_point import IntPoint


struct SearchTreeObject(Copyable, Movable):
    # Multi-shape storage (mirrors Java's per-object shape list).
    var shapes: List[IntBox]
    var octagon_shapes: List[IntOctagon]
    var shape_layers: List[Int]
    var net_no: Int
    var clearance_class_no: Int
    var is_trace_obstacle_flag: Bool
    var is_obstacle_flag: Bool
    # Used to emulate `instanceof CompleteFreeSpaceExpansionRoom` in the early port.
    var is_complete_room_flag: Bool
    # Incremental port hook for Java `set_search_tree_entries(...)`.
    var tree_entries: List[Int]

    fn __init__(
            out self,
            shape: IntBox,
            layer: Int,
            net_no: Int,
            clearance_class_no: Int,
            is_trace_obstacle: Bool,
            is_obstacle: Bool,
            is_complete_room: Bool,
        ):
            self.shapes = List[IntBox]()
            self.octagon_shapes = List[IntOctagon]()
            self.shape_layers = List[Int]()
            self.shapes.append(
                IntBox(IntPoint(shape.ll.x, shape.ll.y), IntPoint(shape.ur.x, shape.ur.y))
            )
            self.octagon_shapes.append(
                IntOctagon.from_box(shape.ll.x, shape.ll.y, shape.ur.x, shape.ur.y)
            )
            self.shape_layers.append(layer)
            self.net_no = net_no
            self.clearance_class_no = clearance_class_no
            self.is_trace_obstacle_flag = is_trace_obstacle
            self.is_obstacle_flag = is_obstacle
            self.is_complete_room_flag = is_complete_room
            self.tree_entries = List[Int]()

    fn add_shape_box(mut self, shape: IntBox, layer: Int):
        # Convenience for ports that build a single object with multiple shapes.
        self.shapes.append(
            IntBox(IntPoint(shape.ll.x, shape.ll.y), IntPoint(shape.ur.x, shape.ur.y))
        )
        self.octagon_shapes.append(
            IntOctagon.from_box(shape.ll.x, shape.ll.y, shape.ur.x, shape.ur.y)
        )
        self.shape_layers.append(layer)

    fn is_trace_obstacle(self, net_no: Int) -> Bool:
        # Treat trace obstacles as blocking only for the routed net itself.
        # This matches the lane semantics in the full/lite complete-shape ports
        # where only the active net should be cut against own trace obstacles.
        if not self.is_trace_obstacle_flag:
            return False
        if net_no < 0:
            return True
        return self.net_no == net_no

    fn is_obstacle(self, net_no: Int) -> Bool:
        # FreeRouting semantics are type-dependent. For the incremental port we
        # provide a controllable flag plus a sensible default for "trace-like"
        # obstacles: do not block the net that owns the object.
        if not self.is_obstacle_flag:
            return False
        if self.is_trace_obstacle_flag:
            return self.net_no != net_no
        return True

    fn shape_layer(self, shape_index: Int) -> Int:
        return self.shape_layers[shape_index]

    fn tree_shape_count(self) -> Int:
        return len(self.shapes)

    fn tile_shape_count(self) -> Int:
        return self.tree_shape_count()

    fn get_tree_shape(self, shape_index: Int) -> IntBox:
        # IntBox-first accessor used by early tree ports.
        return self.get_tree_shape_box(shape_index)

    fn set_search_tree_entries(mut self, entries: List[Int]):
        self.tree_entries = entries.copy()

    fn search_tree_entry_count(self) -> Int:
        return len(self.tree_entries)

    fn search_tree_entry(self, index: Int) -> Int:
        return self.tree_entries[index]

    fn get_tree_shape_box(self, shape_index: Int) -> IntBox:
        var s = self.shapes[shape_index].copy()
        return IntBox(IntPoint(s.ll.x, s.ll.y), IntPoint(s.ur.x, s.ur.y))

    fn get_tree_shape_octagon(self, shape_index: Int) -> IntOctagon:
        return self.octagon_shapes[shape_index].copy()

    fn is_complete_room(self) -> Bool:
        return self.is_complete_room_flag
