"""Build a `RoomGraph` using FreeRouting-style free-space expansion (box-only).

This is a bridge between the grid router and the FreeRouting room/door model:
- Convert grid obstacles into box obstacles.
- Use `ShapeSearchTree90Degree.complete_shape` to carve free-space rooms.
- Connect rooms with doors at overlaps/touching edges.
"""

from collections import List

from ...grid import Grid, u32_max
from ..board.search_tree_object import SearchTreeObject
from ..board.shape_search_tree_90_degree_full import ShapeSearchTree90Degree
from ..geometry.planar.int_box import IntBox
from ..geometry.planar.int_point import IntPoint
from ..geometry.planar.tile_shape import TileShapeBox
from .complete_free_space_expansion_room import CompleteFreeSpaceExpansionRoomBox
from .incomplete_free_space_expansion_room import IncompleteFreeSpaceExpansionRoom
from .room_graph import RoomGraph
from .room_graph_build import build_doors_for_all_contacts


@fieldwise_init
struct ObstacleRect(Copyable, Movable):
    var layer: Int
    var x0: Int
    var y0: Int
    var x1: Int
    var y1: Int
    var owner: Int


fn _owner_from_u32(v: UInt32) -> Int:
    if v == UInt32(0) or v == u32_max():
        return -1
    return Int(v)


fn _cell_obstacle_owner(
    g: Grid,
    layer: Int,
    x: Int,
    y: Int,
    net_id: UInt32,
    use_touch: Bool,
    use_ko: Bool,
    use_occ: Bool,
) -> Int:
    var idx = g.idx(layer, x, y)
    if not g.base_allows(layer, x, y, net_id):
        var v = g.base_get(idx)
        if v == g.blocked_value:
            return -1
        return _owner_from_u32(v)

    if use_touch:
        if g.touch_track_other_at_idx(idx, net_id) != UInt16(0):
            return _owner_from_u32(g.touch_track_owner[idx])
        if g.touch_via_other_at_idx(idx, net_id) != UInt16(0):
            return _owner_from_u32(g.touch_via_owner[idx])

    if use_ko:
        if g.ko_track_other_at_idx(idx, net_id) != UInt16(0):
            return _owner_from_u32(g.ko_track_owner[idx])
        if g.ko_via_other_at_idx(idx, net_id) != UInt16(0):
            return _owner_from_u32(g.ko_via_owner[idx])

    if use_occ:
        if g.occ_other_at_idx(idx, net_id) != UInt16(0):
            var o = g.track_owner[idx]
            if o == UInt32(0) or o == u32_max():
                o = g.via_owner[idx]
            return _owner_from_u32(o)

    return 0


fn build_obstacle_rects_from_grid(
    g: Grid,
    net_id: UInt32,
    use_touch: Bool,
    use_ko: Bool,
    use_occ: Bool,
) -> List[ObstacleRect]:
    var out = List[ObstacleRect]()
    for layer in range(g.layers):
        var active = List[ObstacleRect]()
        for y in range(g.height):
            var runs = List[ObstacleRect]()
            var x = 0
            while x < g.width:
                var owner = _cell_obstacle_owner(g, layer, x, y, net_id, use_touch, use_ko, use_occ)
                if owner == 0:
                    x += 1
                    continue
                var x0 = x
                var o = owner
                x += 1
                while x < g.width:
                    var owner2 = _cell_obstacle_owner(g, layer, x, y, net_id, use_touch, use_ko, use_occ)
                    if owner2 != o or owner2 == 0:
                        break
                    x += 1
                var x1 = x
                runs.append(ObstacleRect(layer, x0, y, x1, y + 1, o))

            var new_active = List[ObstacleRect]()
            for r in runs:
                var merged = False
                for a in active:
                    if a.x0 == r.x0 and a.x1 == r.x1 and a.y1 == r.y0 and a.owner == r.owner:
                        new_active.append(ObstacleRect(layer, a.x0, a.y0, a.x1, r.y1, a.owner))
                        merged = True
                        break
                if not merged:
                    new_active.append(r.copy())

            for a in active:
                var continued = False
                for na in new_active:
                    if na.x0 == a.x0 and na.x1 == a.x1 and na.y0 == a.y0 and na.owner == a.owner:
                        continued = True
                        break
                if not continued:
                    out.append(a.copy())

            active = new_active^

        for a in active:
            out.append(a.copy())

    return out^


fn build_room_graph_from_grid_free_space(
    g: Grid,
    net_id: UInt32,
    use_touch: Bool,
    use_ko: Bool,
    use_occ: Bool,
) -> RoomGraph:
    var bbox = IntBox(IntPoint(0, 0), IntPoint(g.width, g.height))
    var tree = ShapeSearchTree90Degree(bbox)

    var obstacles = build_obstacle_rects_from_grid(g, net_id, use_touch, use_ko, use_occ)
    for r in obstacles:
        var box = IntBox(IntPoint(r.x0, r.y0), IntPoint(r.x1, r.y1))
        var obj = SearchTreeObject(box, r.layer, r.owner, 0, True, True, False)
        _ = tree.insert_object(obj)

    var graph = RoomGraph()
    var complete_rooms = List[CompleteFreeSpaceExpansionRoomBox]()
    var room_id = 0
    for layer in range(g.layers):
        var seed_shape = IntBox(IntPoint(bbox.ll.x, bbox.ll.y), IntPoint(bbox.ur.x, bbox.ur.y))
        var seed_contained = IntBox(IntPoint(bbox.ll.x, bbox.ll.y), IntPoint(bbox.ur.x, bbox.ur.y))
        var seed = IncompleteFreeSpaceExpansionRoom(seed_shape^, layer, seed_contained^)
        var rooms = tree.complete_shape(
            seed,
            Int(net_id),
            -1,
            TileShapeBox(IntBox.empty()),
        )
        for r in rooms:
            var box = r.get_shape()
            if box.is_empty() or box.dimension() <= 0:
                continue
            var room_box = IntBox(IntPoint(box.ll.x, box.ll.y), IntPoint(box.ur.x, box.ur.y))
            var room_shape = TileShapeBox(room_box^)
            complete_rooms.append(CompleteFreeSpaceExpansionRoomBox(room_shape, layer, room_id))
            _ = graph.add_room(layer, box)
            room_id += 1

    _ = build_doors_for_all_contacts(graph)
    return graph^
