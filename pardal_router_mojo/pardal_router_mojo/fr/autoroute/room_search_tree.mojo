"""Glue between `RoomGraph` and `ShapeSearchTreeBox` (minimal).

FreeRouting stores expansion rooms in the search tree so it can quickly find
neighbor rooms and compute doors. For the incremental Mojo port, we keep the
interfaces simple:
- store each room as a `SearchTreeObject` with a single box shape
- query overlaps to find candidate neighbor rooms
"""

from collections import List

from ..board.shape_search_tree_box import ShapeSearchTreeBox
from ..board.search_tree_object import SearchTreeObject
from ..geometry.planar.int_box import IntBox
from .room_graph import RoomGraph


@fieldwise_init
struct RoomSearchTree(Movable):
    var tree: ShapeSearchTreeBox
    var room_to_object_id: List[Int]  # index by room_id
    var object_to_room_id: List[Int]  # index by object_id (dense)

    fn __init__(out self):
        self.tree = ShapeSearchTreeBox()
        self.room_to_object_id = List[Int]()
        self.object_to_room_id = List[Int]()

    fn insert_all_rooms(mut self, graph: RoomGraph):
        self.room_to_object_id = List[Int]()
        self.object_to_room_id = List[Int]()
        for room_id in range(graph.room_count()):
            self.room_to_object_id.append(-1)
            var box = graph.room_box(room_id)
            var layer = graph.room_layer[room_id]
            # Expansion rooms are not net obstacles; use net_no=-1 and obstacle flags false.
            var obj = SearchTreeObject(box, layer, -1, 0, False, False, True)
            var oid = self.tree.insert_object(obj)
            self.room_to_object_id[room_id] = oid
            while len(self.object_to_room_id) <= oid:
                self.object_to_room_id.append(-1)
            self.object_to_room_id[oid] = room_id

    fn overlapping_rooms_on_layer(self, shape: IntBox, layer: Int) -> List[Int]:
        # Returns room ids whose boxes overlap the query shape on the given layer.
        var hits = self.tree.overlapping_tree_entries_on_layer(shape, layer)
        var out = List[Int]()
        for h in hits:
            if h.object_id >= 0 and h.object_id < len(self.object_to_room_id):
                var rid = self.object_to_room_id[h.object_id]
                if rid >= 0:
                    out.append(rid)
        return out^
