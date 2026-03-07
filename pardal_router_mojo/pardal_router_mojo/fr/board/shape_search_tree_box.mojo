"""Minimal `ShapeSearchTree` port (IntBox-only).

This is the next step beyond `ShapeSearchTree90DegreeLite`: it introduces a
`SearchTreeObject` store + shape-indexed tree leaves so later ports can mirror
FreeRouting's object/shape separation.

Scope (intentional):
- IntBox shapes only
- MinAreaTreeIntBox backing store
- overlap query returns `(object_id, shape_index)` pairs
"""

from collections import List

from ..datastructures.min_area_tree_int_box import MinAreaTreeIntBox
from ..geometry.planar.int_box import IntBox
from ..geometry.planar.int_point import IntPoint
from ..rules.clearance_matrix import ClearanceMatrix
from .search_tree_object import SearchTreeObject
from .layer_structure import LayerStructure
from .layer import Layer


@fieldwise_init
struct TreeEntryBox(Copyable, Movable):
    var object_id: Int
    var shape_index_in_object: Int


@fieldwise_init
struct ShapeSearchTreeBox(Movable):
    var tree: MinAreaTreeIntBox
    var objects: List[SearchTreeObject]
    var clearance_matrix: ClearanceMatrix
    var compensated_clearance_class_no: Int

    fn __init__(out self):
        self.tree = MinAreaTreeIntBox()
        self.objects = List[SearchTreeObject]()
        var ls = LayerStructure([Layer("L0", True)])
        self.clearance_matrix = ClearanceMatrix(1, ls, ["default"])
        self.compensated_clearance_class_no = 0

    @staticmethod
    fn with_clearance(
        mut clearance_matrix: ClearanceMatrix,
        compensated_clearance_class_no: Int,
    ) -> ShapeSearchTreeBox:
        var out = ShapeSearchTreeBox()
        out.clearance_matrix = clearance_matrix^
        # Reinitialize the moved-from argument to satisfy Mojo's definite init rules.
        var ls = LayerStructure([Layer("L0", True)])
        clearance_matrix = ClearanceMatrix(1, ls, ["default"])
        out.compensated_clearance_class_no = compensated_clearance_class_no
        return out^

    fn insert_object(mut self, obj: SearchTreeObject) -> Int:
        var object_id = len(self.objects)
        self.objects.append(obj.copy())
        var inserted_entries = List[Int]()
        # Insert each shape as a leaf with (object_id, shape_index).
        var i = 0
        while i < self.objects[object_id].tile_shape_count():
            var sh = self.objects[object_id].get_tree_shape_box(i)
            if self.compensated_clearance_class_no > 0 and obj.clearance_class_no > 0:
                var layer = obj.shape_layer(i)
                var v = self.clearance_matrix.get_value(
                    obj.clearance_class_no,
                    self.compensated_clearance_class_no,
                    layer,
                    False,
                ) - self.clearance_matrix.clearance_compensation_value(
                    self.compensated_clearance_class_no, layer
                )
                if v > 0:
                    sh = sh.offset(Float64(v))
            var leaf_id = self.tree.insert_leaf(object_id, i, sh)
            inserted_entries.append(leaf_id)
            i += 1
        var stored = self.objects[object_id].copy()
        stored.set_search_tree_entries(inserted_entries^)
        self.objects[object_id] = stored^
        return object_id

    fn overlapping_tree_entries(self, shape: IntBox) -> List[TreeEntryBox]:
        var hits = self.tree.overlaps(shape)
        var out = List[TreeEntryBox]()
        var i = 0
        while i < len(hits):
            var leaf_idx = hits[i]
            out.append(
                TreeEntryBox(
                    self.tree.leaf_object_id[leaf_idx],
                    self.tree.leaf_shape_index[leaf_idx],
                )
            )
            i += 1
        return out^

    fn overlapping_tree_entries_on_layer(self, shape: IntBox, layer: Int) -> List[TreeEntryBox]:
        var hits = self.tree.overlaps(shape)
        var out = List[TreeEntryBox]()
        var i = 0
        while i < len(hits):
            var leaf_idx = hits[i]
            var obj_id = self.tree.leaf_object_id[leaf_idx]
            var sh_idx = self.tree.leaf_shape_index[leaf_idx]
            if self.objects[obj_id].shape_layer(sh_idx) == layer:
                out.append(TreeEntryBox(obj_id, sh_idx))
            i += 1
        return out^

    fn overlapping_tree_entries_filtered(
        self,
        shape: IntBox,
        layer: Int,
        net_no: Int,
        require_obstacle: Bool,
        require_trace_obstacle: Bool,
    ) -> List[TreeEntryBox]:
        # Generalized overlap query used by incremental FreeRouting ports.
        # `layer < 0` disables layer filtering.
        # `net_no < 0` means "unknown net" for obstacle predicates.
        var hits = self.tree.overlaps(shape)
        var out = List[TreeEntryBox]()
        var i = 0
        while i < len(hits):
            var leaf_idx = hits[i]
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
            out.append(TreeEntryBox(obj_id, sh_idx))
            i += 1
        return out^

    fn overlapping_tree_entries_obstacles(self, shape: IntBox, layer: Int, net_no: Int) -> List[TreeEntryBox]:
        # Returns overlaps on a single layer that are obstacles for `net_no`.
        return self.overlapping_tree_entries_filtered(
            shape,
            layer,
            net_no,
            True,
            False,
        )

    fn overlapping_tree_entries_trace_obstacles(self, shape: IntBox, layer: Int, net_no: Int) -> List[TreeEntryBox]:
        return self.overlapping_tree_entries_filtered(
            shape,
            layer,
            net_no,
            False,
            True,
        )

    fn object_shape_box(self, entry: TreeEntryBox) -> IntBox:
        var obj = self.objects[entry.object_id]
        return obj.get_tree_shape_box(entry.shape_index_in_object)

    fn object_layer(self, entry: TreeEntryBox) -> Int:
        return self.objects[entry.object_id].shape_layer(entry.shape_index_in_object)

    fn tree_shape_count(self) -> Int:
        return self.tree.leaf_count

    fn tree_entry(self, tree_index: Int) -> TreeEntryBox:
        # Maps a tree-leaf index back to (object_id, shape_index).
        return TreeEntryBox(
            self.tree.leaf_object_id[tree_index], self.tree.leaf_shape_index[tree_index]
        )

    fn tree_entry_shape_box(self, tree_index: Int) -> IntBox:
        return self.object_shape_box(self.tree_entry(tree_index))
