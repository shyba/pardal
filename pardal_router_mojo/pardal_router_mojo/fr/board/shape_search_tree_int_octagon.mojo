"""Minimal `ShapeSearchTree` base for IntOctagon bounds.

This is the 45° counterpart to `shape_search_tree_int_box.mojo`.
"""

from collections import List

from ..datastructures.min_area_tree_int_octagon import MinAreaTreeIntOctagon
from ..geometry.planar.int_octagon import IntOctagon
from ..rules.clearance_matrix import ClearanceMatrix
from .search_tree_object import SearchTreeObject
from .layer_structure import LayerStructure
from .layer import Layer


@fieldwise_init
struct SearchTreeHit(Copyable, Movable):
    var object_id: Int
    var shape_index: Int


@fieldwise_init
struct ShapeSearchTreeIntOctagon(Movable):
    var tree: MinAreaTreeIntOctagon
    var objects: List[SearchTreeObject]
    var clearance_matrix: ClearanceMatrix
    var compensated_clearance_class_no: Int

    fn __init__(out self):
        self.tree = MinAreaTreeIntOctagon()
        self.objects = List[SearchTreeObject]()
        # Default: no clearance compensation (class 0) with a minimal 1-layer matrix.
        var ls = LayerStructure([Layer("L0", True)])
        self.clearance_matrix = ClearanceMatrix(1, ls, ["default"])
        self.compensated_clearance_class_no = 0

    fn insert_object(mut self, obj: SearchTreeObject) -> Int:
        var obj_id = len(self.objects)
        self.objects.append(obj.copy())
        self._insert_object_shapes(obj_id)
        return obj_id

    fn _insert_object_shapes(mut self, obj_id: Int):
        var obj = self.objects[obj_id].copy()
        var inserted_entries = List[Int]()
        var si = 0
        while si < obj.tile_shape_count():
            # For 45° trees we require octagon bounds.
            var oct = obj.get_tree_shape_octagon(si)
            if self.compensated_clearance_class_no > 0 and obj.clearance_class_no > 0:
                var layer = obj.shape_layer(si)
                var v = self.clearance_matrix.get_value(
                    obj.clearance_class_no,
                    self.compensated_clearance_class_no,
                    layer,
                    False,
                ) - self.clearance_matrix.clearance_compensation_value(
                    self.compensated_clearance_class_no, layer
                )
                if v > 0:
                    oct = oct.offset(Float64(v))
            var leaf_id = self.tree.insert_leaf(obj_id, si, oct)
            inserted_entries.append(leaf_id)
            si += 1
        obj.set_search_tree_entries(inserted_entries^)
        self.objects[obj_id] = obj^

    fn overlaps(self, shape: IntOctagon) -> List[SearchTreeHit]:
        var hits = List[SearchTreeHit]()
        var leafs = self.tree.overlaps(shape)
        var i = 0
        while i < len(leafs):
            var leaf_idx = leafs[i]
            hits.append(
                SearchTreeHit(
                    self.tree.leaf_object_id[leaf_idx],
                    self.tree.leaf_shape_index[leaf_idx],
                )
            )
            i += 1
        return hits^

    fn overlaps_filtered(
        self,
        shape: IntOctagon,
        layer: Int,
        net_no: Int,
        require_obstacle: Bool,
        require_trace_obstacle: Bool,
    ) -> List[SearchTreeHit]:
        var out = List[SearchTreeHit]()
        var leafs = self.tree.overlaps(shape)
        var i = 0
        while i < len(leafs):
            var leaf_idx = leafs[i]
            var obj_id = self.tree.leaf_object_id[leaf_idx]
            var sh_idx = self.tree.leaf_shape_index[leaf_idx]
            var obj = self.objects[obj_id].copy()
            if layer >= 0 and obj.shape_layer(sh_idx) != layer:
                i += 1
                continue
            if require_trace_obstacle and not obj.is_trace_obstacle(net_no):
                i += 1
                continue
            if require_obstacle and not obj.is_obstacle(net_no):
                i += 1
                continue
            out.append(SearchTreeHit(obj_id, sh_idx))
            i += 1
        return out^

    fn overlaps_on_layer(self, shape: IntOctagon, layer: Int) -> List[SearchTreeHit]:
        return self.overlaps_filtered(shape, layer, -1, False, False)

    fn overlaps_obstacles(self, shape: IntOctagon, layer: Int, net_no: Int) -> List[SearchTreeHit]:
        return self.overlaps_filtered(shape, layer, net_no, True, False)

    fn overlaps_trace_obstacles(self, shape: IntOctagon, layer: Int, net_no: Int) -> List[SearchTreeHit]:
        return self.overlaps_filtered(shape, layer, net_no, False, True)

    fn remove_object(mut self, object_id: Int) -> Int:
        # Remove all leaf entries belonging to `object_id`.
        # Returns number of removed leaves. Leaves are swap-removed.
        var removed = 0
        var i = 0
        while i < len(self.tree.leaf_object_id):
            if self.tree.leaf_object_id[i] == object_id:
                if self.tree.remove_leaf(i):
                    removed += 1
                    # Do not increment i; swapped element needs checking.
                    continue
            i += 1
        return removed
