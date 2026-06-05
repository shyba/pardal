"""Incremental `ShapeSearchTree45Degree.complete_shape` port (IntOctagon-only).

This uses the minimal `ShapeSearchTreeIntOctagon` base (overlaps via MinAreaTree)
and the IntOctagon-only `restrain_shape` implementation.

It is not yet wired into a full board/search-tree manager; its purpose is to
validate 45° room-cut semantics as building blocks for maze routing.
"""

from collections import List

from ..autoroute.incomplete_free_space_expansion_room_octagon import (
    IncompleteFreeSpaceExpansionRoomOctagon,
)
from ..geometry.planar.int_octagon import IntOctagon
from .search_tree_object import SearchTreeObject
from .shape_search_tree_45_degree import restrain_shape
from .shape_search_tree_int_octagon import ShapeSearchTreeIntOctagon


@fieldwise_init
struct ShapeSearchTree45Degree(Movable):
    var base: ShapeSearchTreeIntOctagon
    var board_bbox: IntOctagon

    fn __init__(out self, board_bbox_oct: IntOctagon):
        self.base = ShapeSearchTreeIntOctagon()
        self.board_bbox = board_bbox_oct.copy()

    fn insert_object(mut self, obj: SearchTreeObject) -> Int:
        return self.base.insert_object(obj)

    fn complete_shape(
        self,
        room: IncompleteFreeSpaceExpansionRoomOctagon,
        net_no: Int,
        ignore_object_id: Int,
        ignore_shape: IntOctagon,
    ) -> List[IncompleteFreeSpaceExpansionRoomOctagon]:
        var contained = room.get_contained_shape()
        if contained.is_empty():
            return List[IncompleteFreeSpaceExpansionRoomOctagon]()

        var start_shape = self.board_bbox.copy()
        var rs = room.get_shape()
        start_shape = rs.intersection(start_shape)

        var bounding_shape = start_shape.copy()
        var layer = room.get_layer()

        var result = List[IncompleteFreeSpaceExpansionRoomOctagon]()
        result.append(
            IncompleteFreeSpaceExpansionRoomOctagon(
                start_shape.copy(), layer, contained.copy()
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
                        var obj_box = obj.get_tree_shape_box(hit.shape_index)
                        var obj_shape = obj_box.to_octagon()
                        var new_result = List[IncompleteFreeSpaceExpansionRoomOctagon]()
                        var new_bounding = IntOctagon.empty()

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
                                    if isect.is_contained_in(ignore_shape):
                                        if not curr_shape.is_contained_in(ignore_shape):
                                            new_result.append(curr_room.copy())
                                            new_bounding = new_bounding.union(
                                                curr_shape.bounding_box().to_octagon()
                                            )
                                        ri += 1
                                        continue
                                var pieces = restrain_shape(curr_room, obj_shape)
                                for p in pieces:
                                    new_result.append(p.copy())
                                    new_bounding = new_bounding.union(
                                        p.get_shape().bounding_box().to_octagon()
                                    )
                                changed = True
                            else:
                                new_result.append(curr_room.copy())
                                new_bounding = new_bounding.union(
                                    curr_shape.bounding_box().to_octagon()
                                )
                            ri += 1
                        result = new_result^
                        bounding_shape = new_bounding.copy()
                hi += 1

        result = self._divide_large_room(result)

        # Match Java: remove rooms with shapes equal to the contained shape to
        # prevent endless loops in higher-level expansion.
        var filtered = List[IncompleteFreeSpaceExpansionRoomOctagon]()
        for r in result:
            var s = r.get_shape()
            var c = r.get_contained_shape()
            if s.is_contained_in(c):
                # If the contained shape fully covers the room, drop it.
                continue
            filtered.append(r.copy())
        return filtered^

    fn _divide_large_room(
        self, rooms: List[IncompleteFreeSpaceExpansionRoomOctagon]
    ) -> List[IncompleteFreeSpaceExpansionRoomOctagon]:
        # FreeRouting calls `divide_large_room(result, board_bbox)` to ensure that
        # there is more than one room per layer even when the layer has no items,
        # otherwise via handling in maze expansion can get stuck.
        #
        # We implement a minimal variant:
        # - if a layer has exactly 1 room and it equals the full board bbox, split
        #   it into two rooms along the board's X midpoint.
        var out = List[IncompleteFreeSpaceExpansionRoomOctagon]()
        # group by layer (small n: linear scans)
        var i = 0
        while i < len(rooms):
            var r = rooms[i].copy()
            out.append(r.copy())
            i += 1

        # Find layers present.
        var li = 0
        while li < len(out):
            var layer = out[li].get_layer()
            # count rooms on layer and find if any equals board bbox
            var count = 0
            var bbox_idx = -1
            var j = 0
            while j < len(out):
                if out[j].get_layer() == layer:
                    count += 1
                    if out[j].get_shape().is_contained_in(
                        self.board_bbox
                    ) and self.board_bbox.is_contained_in(out[j].get_shape()):
                        bbox_idx = j
                j += 1
            if count == 1 and bbox_idx >= 0:
                var bb = self.board_bbox.copy()
                var midx = (bb.leftX + bb.rightX) // 2
                # Left half
                var left_room = IntOctagon.from_freerouting(
                    bb.leftX,
                    bb.bottomY,
                    midx,
                    bb.topY,
                    bb.upperLeftDiagonalX,
                    bb.lowerRightDiagonalX,
                    bb.lowerLeftDiagonalX,
                    bb.upperRightDiagonalX,
                ).normalize()
                # Right half
                var right_room = IntOctagon.from_freerouting(
                    midx,
                    bb.bottomY,
                    bb.rightX,
                    bb.topY,
                    bb.upperLeftDiagonalX,
                    bb.lowerRightDiagonalX,
                    bb.lowerLeftDiagonalX,
                    bb.upperRightDiagonalX,
                ).normalize()
                var old = out[bbox_idx].copy()
                # Replace old with left and append right.
                out[bbox_idx] = IncompleteFreeSpaceExpansionRoomOctagon(
                    left_room.copy(),
                    layer,
                    old.get_contained_shape().intersection(left_room),
                )
                out.append(
                    IncompleteFreeSpaceExpansionRoomOctagon(
                        right_room.copy(),
                        layer,
                        old.get_contained_shape().intersection(right_room),
                    )
                )
            li += 1
        return out^
