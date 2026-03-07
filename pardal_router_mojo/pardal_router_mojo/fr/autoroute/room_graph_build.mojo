"""Helpers to build a `RoomGraph` from overlapping room boxes (minimal).

This is *not* FreeRouting's full space-partitioning logic. It's a stepping stone:
- store rooms
- find overlapping rooms via `RoomSearchTree`
- create doors as box intersections

This lets us validate the search-tree→doors pipeline before implementing the
actual "free space expansion rooms" algorithm.
"""

from collections import List

from ..geometry.planar.int_box import IntBox
from .room_graph import RoomGraph
from .room_search_tree import RoomSearchTree


fn build_doors_for_all_overlaps(mut graph: RoomGraph) -> Int:
    # Builds doors for all overlapping room pairs on the same layer.
    # Returns number of doors created.
    var room_count = graph.room_count()
    var search = RoomSearchTree()
    search.insert_all_rooms(graph)

    var created = 0
    for rid in range(room_count):
        var layer = graph.room_layer[rid]
        var box = graph.room_box(rid)
        var neigh = search.overlapping_rooms_on_layer(box, layer)
        for other in neigh:
            if other <= rid:
                continue
            var did = graph.add_intersection_door(rid, other)
            if did >= 0:
                created += 1

    graph.finalize_adjacency()
    return created


fn build_doors_for_all_contacts(mut graph: RoomGraph) -> Int:
    # Builds doors for all rooms that overlap or touch (edge/corner).
    # Returns number of doors created.
    var room_count = graph.room_count()
    if room_count <= 0:
        graph.finalize_adjacency()
        return 0

    var search = RoomSearchTree()
    search.insert_all_rooms(graph)

    var created = 0
    for rid in range(room_count):
        var layer = graph.room_layer[rid]
        var box = graph.room_box(rid)
        # Expand by 1 to catch touching rooms (edges/corners).
        var query = box.offset(Float64(1.0))
        var neigh = search.overlapping_rooms_on_layer(query, layer)
        for other in neigh:
            if other <= rid:
                continue
            var a = graph.room_box(rid)
            var b = graph.room_box(other)
            var inter = a.intersection(b)
            if inter.is_empty():
                continue
            var dim = inter.dimension()
            if dim < 0:
                continue
            _ = graph.add_door(rid, other, dim, inter)
            created += 1

    graph.finalize_adjacency()
    return created


fn build_doors_for_cross_layer_overlaps(mut graph: RoomGraph, layer_step: Int) -> Int:
    # Build doors between rooms on adjacent layers where their boxes overlap.
    # This models via opportunities for maze routing.
    var room_count = graph.room_count()
    if room_count <= 0:
        graph.finalize_adjacency()
        return 0
    var step = layer_step
    if step <= 0:
        step = 1

    var search = RoomSearchTree()
    search.insert_all_rooms(graph)

    var created = 0
    for rid in range(room_count):
        var layer = graph.room_layer[rid]
        var target_layer = layer + step
        var box = graph.room_box(rid)
        var neigh = search.overlapping_rooms_on_layer(box, target_layer)
        for other in neigh:
            if other <= rid:
                continue
            var a = graph.room_box(rid)
            var b = graph.room_box(other)
            var inter = a.intersection(b)
            if inter.is_empty():
                continue
            var dim = inter.dimension()
            if dim < 0:
                continue
            _ = graph.add_door(rid, other, dim, inter)
            created += 1

    graph.finalize_adjacency()
    return created
