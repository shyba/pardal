"""Room/door storage for FreeRouting-style maze routing (minimal).

Mojo's `List[T]` requires `T` to be Copyable, which makes it awkward to store
nested structures (rooms containing lists of doors). FreeRouting models routing
space as a graph of expansion rooms connected by expansion doors.

This module provides a storage layer similar in spirit, implemented with flat
arrays + offsets (CSR-style adjacency).

Scope:
- Box-only shapes (`IntBox` bounds for room/door shapes)
- Room → door adjacency stored as (door_ids_flat, door_offsets)
"""

from collections import List

from ..geometry.planar.int_box import IntBox
from ..geometry.planar.int_point import IntPoint
from ..geometry.planar.tile_shape import TileShapeBox


@fieldwise_init
struct RoomId(Copyable, Movable):
    var value: Int


@fieldwise_init
struct DoorId(Copyable, Movable):
    var value: Int


@fieldwise_init
struct RoomGraph(Movable):
    # Rooms
    var room_layer: List[Int]
    var room_llx: List[Int]
    var room_lly: List[Int]
    var room_urx: List[Int]
    var room_ury: List[Int]

    # Doors (global list)
    var door_room_a: List[Int]
    var door_room_b: List[Int]
    var door_dimension: List[Int]
    var door_llx: List[Int]
    var door_lly: List[Int]
    var door_urx: List[Int]
    var door_ury: List[Int]

    # Adjacency (built in two phases to avoid Copyable constraints and ordering issues):
    # - during construction we append (room_id, door_id) pairs
    # - finalize builds CSR arrays
    var adj_room_id: List[Int]
    var adj_door_id: List[Int]

    var room_door_start: List[Int]
    var room_door_len: List[Int]
    var room_door_ids: List[Int]

    fn __init__(out self):
        self.room_layer = List[Int]()
        self.room_llx = List[Int]()
        self.room_lly = List[Int]()
        self.room_urx = List[Int]()
        self.room_ury = List[Int]()

        self.door_room_a = List[Int]()
        self.door_room_b = List[Int]()
        self.door_dimension = List[Int]()
        self.door_llx = List[Int]()
        self.door_lly = List[Int]()
        self.door_urx = List[Int]()
        self.door_ury = List[Int]()

        self.adj_room_id = List[Int]()
        self.adj_door_id = List[Int]()
        self.room_door_start = List[Int]()
        self.room_door_len = List[Int]()
        self.room_door_ids = List[Int]()

    fn room_count(self) -> Int:
        return len(self.room_layer)

    fn door_count(self) -> Int:
        return len(self.door_room_a)

    fn add_room(mut self, layer: Int, box: IntBox) -> Int:
        var id = len(self.room_layer)
        self.room_layer.append(layer)
        self.room_llx.append(box.ll.x)
        self.room_lly.append(box.ll.y)
        self.room_urx.append(box.ur.x)
        self.room_ury.append(box.ur.y)
        self.room_door_start.append(0)
        self.room_door_len.append(0)
        return id

    fn room_box(self, room_id: Int) -> IntBox:
        return IntBox(
            IntPoint(self.room_llx[room_id], self.room_lly[room_id]),
            IntPoint(self.room_urx[room_id], self.room_ury[room_id]),
        )

    fn room_shape(self, room_id: Int) -> TileShapeBox:
        return TileShapeBox(self.room_box(room_id))

    fn add_door(mut self, room_a: Int, room_b: Int, dimension: Int, box: IntBox) -> Int:
        var id = len(self.door_room_a)
        self.door_room_a.append(room_a)
        self.door_room_b.append(room_b)
        self.door_dimension.append(dimension)
        self.door_llx.append(box.ll.x)
        self.door_lly.append(box.ll.y)
        self.door_urx.append(box.ur.x)
        self.door_ury.append(box.ur.y)
        self.adj_room_id.append(room_a)
        self.adj_door_id.append(id)
        self.adj_room_id.append(room_b)
        self.adj_door_id.append(id)
        return id

    fn add_intersection_door(mut self, room_a: Int, room_b: Int) -> Int:
        # Convenience helper: create a door whose shape is the intersection of the
        # two room boxes. Returns -1 if no intersection.
        if room_a < 0 or room_b < 0 or room_a >= self.room_count() or room_b >= self.room_count():
            return -1
        var a = self.room_box(room_a)
        var b = self.room_box(room_b)
        var inter = a.intersection(b)
        if inter.is_empty():
            return -1
        var dim = inter.dimension()
        if dim < 0:
            return -1
        return self.add_door(room_a, room_b, dim, inter)

    fn door_box(self, door_id: Int) -> IntBox:
        return IntBox(
            IntPoint(self.door_llx[door_id], self.door_lly[door_id]),
            IntPoint(self.door_urx[door_id], self.door_ury[door_id]),
        )

    fn door_shape(self, door_id: Int) -> TileShapeBox:
        return TileShapeBox(self.door_box(door_id))

    fn other_room_id(self, door_id: Int, room_id: Int) -> Int:
        var a = self.door_room_a[door_id]
        var b = self.door_room_b[door_id]
        if room_id == a:
            return b
        if room_id == b:
            return a
        return -1

    fn room_doors_begin(self, room_id: Int) -> Int:
        return self.room_door_start[room_id]

    fn room_doors_len(self, room_id: Int) -> Int:
        return self.room_door_len[room_id]

    fn room_door_id_at(self, room_id: Int, i: Int) -> Int:
        return self.room_door_ids[self.room_door_start[room_id] + i]

    fn finalize_adjacency(mut self):
        # Build CSR arrays from the appended adjacency pairs.
        var n = self.room_count()
        self.room_door_start = List[Int]()
        self.room_door_len = List[Int]()
        for _ in range(n):
            self.room_door_start.append(0)
            self.room_door_len.append(0)

        # Count degrees.
        for r in self.adj_room_id:
            if r >= 0 and r < n:
                self.room_door_len[r] = self.room_door_len[r] + 1

        # Prefix sum to starts.
        var acc = 0
        for i in range(n):
            var ln = self.room_door_len[i]
            self.room_door_start[i] = acc
            acc += ln

        # Allocate ids and reset lens to use as write cursors.
        self.room_door_ids = List[Int]()
        for _ in range(acc):
            self.room_door_ids.append(-1)
        var curs = List[Int]()
        for i in range(n):
            curs.append(0)

        # Fill.
        for i in range(len(self.adj_room_id)):
            var r = self.adj_room_id[i]
            if r < 0 or r >= n:
                continue
            var dst = self.room_door_start[r] + curs[r]
            self.room_door_ids[dst] = self.adj_door_id[i]
            curs[r] = curs[r] + 1
