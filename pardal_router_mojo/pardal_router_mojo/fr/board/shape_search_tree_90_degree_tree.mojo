"""A minimal `ShapeSearchTree90Degree` that can execute `complete_shape` over box obstacles.

This is not yet the full FreeRouting board/search-tree integration. It exists to:
- validate `complete_shape` semantics (room cutting loop)
- provide a stepping stone toward the full port (SearchTreeObject + layers + clearance)
"""

from collections import List

from ..autoroute.incomplete_free_space_expansion_room import IncompleteFreeSpaceExpansionRoom
from ..datastructures.min_area_tree_int_box import MinAreaTreeIntBox
from ..geometry.planar.int_box import IntBox
from ..geometry.planar.int_point import IntPoint
from .shape_search_tree_90_degree import restrain_shape


@fieldwise_init
struct _Obstacle(Copyable, Movable):
    var shape: IntBox
    var layer: Int
    var net_no: Int
    var is_trace_obstacle: Bool


@fieldwise_init
struct ShapeSearchTree90DegreeLite(Movable):
    var tree: MinAreaTreeIntBox
    var obstacles: List[_Obstacle]
    var board_bbox: IntBox

    fn __init__(out self, board_bbox: IntBox):
        self.tree = MinAreaTreeIntBox()
        self.obstacles = List[_Obstacle]()
        self.board_bbox = IntBox(
            IntPoint(board_bbox.ll.x, board_bbox.ll.y),
            IntPoint(board_bbox.ur.x, board_bbox.ur.y),
        )

    fn insert_obstacle(mut self, shape: IntBox, layer: Int, net_no: Int, is_trace_obstacle: Bool) -> Int:
        var obj_id = len(self.obstacles)
        self.obstacles.append(
            _Obstacle(
                IntBox(IntPoint(shape.ll.x, shape.ll.y), IntPoint(shape.ur.x, shape.ur.y)),
                layer,
                net_no,
                is_trace_obstacle,
            )
        )
        _ = self.tree.insert_leaf(obj_id, 0, shape)
        return obj_id

    fn complete_shape(
        self,
        room: IncompleteFreeSpaceExpansionRoom,
        net_no: Int,
        ignore_object_id: Int,
        ignore_shape: IntBox,
    ) -> List[IncompleteFreeSpaceExpansionRoom]:
        # Port intent of Java `ShapeSearchTree90Degree.complete_shape`:
        # Starting from `start_shape`, iteratively cut rooms against overlapping obstacles.
        var contained = room.get_contained_shape()
        if contained.is_empty():
            return List[IncompleteFreeSpaceExpansionRoom]()

        var start_shape = IntBox(
            IntPoint(self.board_bbox.ll.x, self.board_bbox.ll.y),
            IntPoint(self.board_bbox.ur.x, self.board_bbox.ur.y),
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
                IntBox(IntPoint(start_shape.ll.x, start_shape.ll.y), IntPoint(start_shape.ur.x, start_shape.ur.y)),
                layer,
                IntBox(IntPoint(contained.ll.x, contained.ll.y), IntPoint(contained.ur.x, contained.ur.y)),
            )
        )

        # Iterate until stable: scan overlaps vs current bounding_shape, cut rooms.
        var changed = True
        var iter = 0
        while changed and iter < 50:
            changed = False
            iter += 1
            var hits = self.tree.overlaps(bounding_shape)
            var hi = 0
            while hi < len(hits):
                var leaf_idx = hits[hi]
                var obj_id = self.tree.leaf_object_id[leaf_idx]
                if obj_id != ignore_object_id:
                    var ob = self.obstacles[obj_id].copy()
                    if ob.is_trace_obstacle and ob.net_no == net_no and ob.layer == layer:
                        var new_result = List[IncompleteFreeSpaceExpansionRoom]()
                        var new_bounding = IntBox.empty()
                        var ri = 0
                        while ri < len(result):
                            var curr_room = result[ri].copy()
                            var curr_shape = curr_room.get_shape()
                            if curr_shape.overlaps(ob.shape):
                                var pieces = restrain_shape(curr_room, ob.shape)
                                var pi = 0
                                while pi < len(pieces):
                                    new_result.append(pieces[pi].copy())
                                    new_bounding = new_bounding.union(pieces[pi].get_shape())
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
