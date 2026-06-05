"""Early full `ShapeSearchTree90Degree.complete_shape` port for IntBox-only trees.

This replaces the earlier Lite test-only version by introducing a minimal
`SearchTreeObject` abstraction and the ignore-door logic required by
FreeRouting.

It still uses `MinAreaTreeIntBox.overlaps()` for traversal (not `TreeNode`
stack), but behavior should match the Java loop for IntBox bounds.
"""

from collections import List

from ..autoroute.incomplete_free_space_expansion_room import (
    IncompleteFreeSpaceExpansionRoom,
)
from ..geometry.planar.int_box import IntBox
from ..geometry.planar.int_point import IntPoint
from ..geometry.planar.polyline import Polyline
from ..geometry.planar.tile_shape import TileShapeBox
from .search_tree_object import SearchTreeObject
from .shape_search_tree_int_box import ShapeSearchTreeIntBox
from .shape_search_tree_90_degree import restrain_shape


@fieldwise_init
struct ShapeSearchTree90Degree(Movable):
    var base: ShapeSearchTreeIntBox

    fn __init__(out self, board_bbox: IntBox):
        self.base = ShapeSearchTreeIntBox(board_bbox)

    fn insert_object(mut self, obj: SearchTreeObject) -> Int:
        return self.base.insert_object(obj)

    fn offset_shape_box(
        self, polyline: Polyline, half_width: Int, no: Int
    ) -> TileShapeBox:
        _ = self
        return TileShapeBox(polyline.offset_box(half_width, no))

    fn offset_shapes_boxes(
        self,
        polyline: Polyline,
        half_width: Int,
        from_no: Int,
        to_no: Int,
    ) -> List[TileShapeBox]:
        _ = self
        var from_i = from_no if from_no > 0 else 0
        var max_no = polyline.line_count() - 1
        var to_i = to_no if to_no < max_no else max_no
        var shape_count = to_i - from_i - 1
        if shape_count <= 0:
            return List[TileShapeBox]()
        var out = List[TileShapeBox]()
        var j = from_i
        while j < to_i - 1:
            out.append(TileShapeBox(polyline.offset_box(half_width, j)))
            j += 1
        return out^

    fn complete_shape(
        self,
        room: IncompleteFreeSpaceExpansionRoom,
        net_no: Int,
        ignore_object_id: Int,
        ignore_shape: TileShapeBox,
    ) -> List[IncompleteFreeSpaceExpansionRoom]:
        var contained = room.get_contained_shape()
        if contained.is_empty():
            return List[IncompleteFreeSpaceExpansionRoom]()

        var board_bbox = self.base.board_bbox.copy()
        var start_shape = IntBox(
            IntPoint(board_bbox.ll.x, board_bbox.ll.y),
            IntPoint(board_bbox.ur.x, board_bbox.ur.y),
        )
        var rs = room.get_shape()
        start_shape = rs.intersection(start_shape)
        var bounding_shape = IntBox(
            IntPoint(start_shape.ll.x, start_shape.ll.y),
            IntPoint(start_shape.ur.x, start_shape.ur.y),
        )
        var layer = room.get_layer()

        var result = List[IncompleteFreeSpaceExpansionRoom]()
        result.append(
            IncompleteFreeSpaceExpansionRoom(
                IntBox(
                    IntPoint(start_shape.ll.x, start_shape.ll.y),
                    IntPoint(start_shape.ur.x, start_shape.ur.y),
                ),
                layer,
                IntBox(
                    IntPoint(contained.ll.x, contained.ll.y),
                    IntPoint(contained.ur.x, contained.ur.y),
                ),
            )
        )

        var changed = True
        var iter = 0
        while changed and iter < 100:
            changed = False
            iter += 1
            var hits = self.base.overlaps(bounding_shape)
            var hi = 0
            while hi < len(hits):
                var hit = hits[hi].copy()
                var obj_id = hit.object_id
                if obj_id != ignore_object_id:
                    var obj = self.base.objects[obj_id].copy()
                    if (
                        obj.is_trace_obstacle(net_no)
                        and obj.shape_layer(hit.shape_index) == layer
                    ):
                        var obj_shape = obj.get_tree_shape_box(hit.shape_index)
                        var new_result = List[IncompleteFreeSpaceExpansionRoom]()
                        var new_bounding = IntBox.empty()
                        var ri = 0
                        while ri < len(result):
                            var curr_room = result[ri].copy()
                            var curr_shape = curr_room.get_shape()
                            if curr_shape.overlaps(obj_shape):
                                if (
                                    obj.is_complete_room()
                                    and not ignore_shape.is_empty()
                                ):
                                    var isect = curr_shape.intersection(obj_shape)
                                    if ignore_shape.contains(
                                        TileShapeBox(
                                            IntBox(
                                                IntPoint(isect.ll.x, isect.ll.y),
                                                IntPoint(isect.ur.x, isect.ur.y),
                                            )
                                        )
                                    ):
                                        ri += 1
                                        continue
                                var pieces = restrain_shape(curr_room, obj_shape)
                                var pi = 0
                                while pi < len(pieces):
                                    new_result.append(pieces[pi].copy())
                                    new_bounding = new_bounding.union(
                                        pieces[pi].get_shape()
                                    )
                                    pi += 1
                                changed = True
                            else:
                                new_result.append(curr_room.copy())
                                new_bounding = new_bounding.union(curr_shape)
                            ri += 1
                        result = new_result^
                        bounding_shape = IntBox(
                            IntPoint(new_bounding.ll.x, new_bounding.ll.y),
                            IntPoint(new_bounding.ur.x, new_bounding.ur.y),
                        )
                hi += 1
        return result^
