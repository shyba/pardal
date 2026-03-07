"""Build a `RoomGraph` from a `Grid` occupancy map (coarse free-space rectangles).

This is a pragmatic bridge from the existing grid-based router toward the
FreeRouting rooms/doors maze model:
- derive a set of axis-aligned free-space rectangles ("rooms") from a grid
- connect neighboring rooms via "doors" at shared borders

Notes:
- This is not the exact FreeRouting geometry partitioning; it is intentionally
  conservative and box-only.
- The purpose is to provide a scalable room graph for experimenting with
  maze-style searches on real problem grids.
"""

from collections import List

from ...grid import Grid
from ..geometry.planar.int_box import IntBox
from ..geometry.planar.int_point import IntPoint
from .room_graph import RoomGraph


@fieldwise_init
struct RoomRect(Copyable, Movable):
    var layer: Int
    var x0: Int
    var y0: Int
    var x1: Int  # exclusive
    var y1: Int  # exclusive


fn _is_free(g: Grid, layer: Int, x: Int, y: Int, net_id: UInt32) -> Bool:
    return g.in_bounds(layer, x, y) and g.base_allows(layer, x, y, net_id)

fn _is_free_with_keepouts(
    g: Grid,
    layer: Int,
    x: Int,
    y: Int,
    net_id: UInt32,
    use_touch: Bool,
    use_ko: Bool,
) -> Bool:
    if not _is_free(g, layer, x, y, net_id):
        return False
    var idx = g.idx(layer, x, y)
    if use_touch:
        if g.touch_track_other_at_idx(idx, net_id) != UInt16(0) or g.touch_via_other_at_idx(idx, net_id) != UInt16(0):
            return False
    if use_ko:
        if g.ko_track_other_at_idx(idx, net_id) != UInt16(0) or g.ko_via_other_at_idx(idx, net_id) != UInt16(0):
            return False
    return True


fn build_rooms_from_grid(g: Grid, net_id: UInt32) -> RoomGraph:
    return build_rooms_from_grid_with_keepouts(g, net_id, False, False)


fn build_rooms_from_grid_with_keepouts(
    g: Grid,
    net_id: UInt32,
    use_touch: Bool,
    use_ko: Bool,
) -> RoomGraph:
    # Build per-layer maximal rectangles by merging equal runs vertically.
    # Doors are NOT created here.
    var graph = RoomGraph()
    for layer in range(g.layers):
        # Each active rectangle is keyed by (x0,x1) and carries (y0,y1,current).
        var active = List[RoomRect]()

        for y in range(g.height):
            # Compute free runs on this row.
            var runs = List[RoomRect]()
            var x = 0
            while x < g.width:
                while x < g.width and not _is_free_with_keepouts(g, layer, x, y, net_id, use_touch, use_ko):
                    x += 1
                if x >= g.width:
                    break
                var x0 = x
                while x < g.width and _is_free_with_keepouts(g, layer, x, y, net_id, use_touch, use_ko):
                    x += 1
                var x1 = x
                runs.append(RoomRect(layer, x0, y, x1, y + 1))

            # Merge runs with active rectangles of same x-range.
            var new_active = List[RoomRect]()
            for r in runs:
                var merged = False
                for a in active:
                    if a.x0 == r.x0 and a.x1 == r.x1 and a.y1 == r.y0:
                        new_active.append(RoomRect(layer, a.x0, a.y0, a.x1, r.y1))
                        merged = True
                        break
                if not merged:
                    new_active.append(r.copy())

            # Finalize actives that did not continue.
            for a in active:
                var continued = False
                for na in new_active:
                    if na.x0 == a.x0 and na.x1 == a.x1 and na.y0 == a.y0:
                        continued = True
                        break
                if not continued:
                    _ = graph.add_room(
                        layer,
                        IntBox(IntPoint(a.x0, a.y0), IntPoint(a.x1, a.y1)),
                    )

            active = new_active^

        # Flush remaining active rectangles.
        for a in active:
            _ = graph.add_room(
                layer,
                IntBox(IntPoint(a.x0, a.y0), IntPoint(a.x1, a.y1)),
            )

    graph.finalize_adjacency()
    return graph^


fn connect_doors_from_room_map(mut graph: RoomGraph, width: Int, height: Int):
    # Build doors by scanning borders between per-cell room ids (O(width*height)).
    # The room map is reconstructed from room rectangles; this is still linear in
    # the total free area and is far cheaper than O(n^2) pairwise checks.
    #
    # Note: door geometry uses *grid coordinates*. Vertical doors are represented
    # by IntBox(x, y0) to (x, y1) where x is the border coordinate.
    var n_rooms = graph.room_count()
    if n_rooms <= 0:
        graph.finalize_adjacency()
        return

    for layer in range(0, 1 if graph.room_count() == 0 else 32):
        # Determine if this layer exists in the room set quickly.
        var any = False
        for rid in range(n_rooms):
            if graph.room_layer[rid] == layer:
                any = True
                break
        if not any:
            continue

        var map = List[Int](length=width * height, fill=-1)
        for rid in range(n_rooms):
            if graph.room_layer[rid] != layer:
                continue
            var bb = graph.room_box(rid)
            var y = bb.ll.y
            while y < bb.ur.y and y < height:
                var x = bb.ll.x
                while x < bb.ur.x and x < width:
                    map[y * width + x] = rid
                    x += 1
                y += 1

        # Vertical borders between x and x+1
        var y = 0
        while y < height:
            var x = 0
            var advanced = False
            while x < width - 1:
                var a = map[y * width + x]
                var b = map[y * width + (x + 1)]
                if a >= 0 and b >= 0 and a != b:
                    var x_border = x + 1
                    var y0 = y
                    var yy = y + 1
                    while yy < height:
                        var aa = map[yy * width + x]
                        var bb2 = map[yy * width + (x + 1)]
                        if aa != a or bb2 != b:
                            break
                        yy += 1
                    _ = graph.add_door(a, b, 1, IntBox(IntPoint(x_border, y0), IntPoint(x_border, yy)))
                    y = yy
                    advanced = True
                    break
                x += 1
            if not advanced:
                y += 1

        # Horizontal borders between y and y+1
        for x in range(width):
            var y = 0
            while y < height - 1:
                var a = map[y * width + x]
                var b = map[(y + 1) * width + x]
                if a >= 0 and b >= 0 and a != b:
                    var y_border = y + 1
                    var x0 = x
                    var x1 = x + 1
                    var xx = x + 1
                    while xx < width:
                        var aa = map[y * width + xx]
                        var bb2 = map[(y + 1) * width + xx]
                        if aa != a or bb2 != b:
                            break
                        xx += 1
                    x1 = xx
                    _ = graph.add_door(a, b, 1, IntBox(IntPoint(x0, y_border), IntPoint(x1, y_border)))
                    y += 1
                else:
                    y += 1

    graph.finalize_adjacency()


fn connect_doors_naive(mut graph: RoomGraph):
    # Connect rooms on each layer that touch along edges.
    # O(n^2) worst-case; use only for small graphs / tests.
    var n = graph.room_count()
    for i in range(n):
        for j in range(i + 1, n):
            if graph.room_layer[i] != graph.room_layer[j]:
                continue
            var a = graph.room_box(i)
            var b = graph.room_box(j)
            if a.ur.x == b.ll.x or b.ur.x == a.ll.x:
                var y0 = a.ll.y if a.ll.y > b.ll.y else b.ll.y
                var y1 = a.ur.y if a.ur.y < b.ur.y else b.ur.y
                if y1 > y0:
                    var x = a.ur.x if a.ur.x == b.ll.x else b.ur.x
                    _ = graph.add_door(i, j, 1, IntBox(IntPoint(x, y0), IntPoint(x, y1)))
                elif y1 == y0:
                    # Corner-touch: allow a point door (dimension 0). This is important
                    # when free rectangles meet only at a single grid cell corner.
                    var x = a.ur.x if a.ur.x == b.ll.x else b.ur.x
                    _ = graph.add_door(i, j, 0, IntBox(IntPoint(x, y0), IntPoint(x, y0)))
            if a.ur.y == b.ll.y or b.ur.y == a.ll.y:
                var x0 = a.ll.x if a.ll.x > b.ll.x else b.ll.x
                var x1 = a.ur.x if a.ur.x < b.ur.x else b.ur.x
                if x1 > x0:
                    var yb = a.ur.y if a.ur.y == b.ll.y else b.ur.y
                    _ = graph.add_door(i, j, 1, IntBox(IntPoint(x0, yb), IntPoint(x1, yb)))
                elif x1 == x0:
                    var yb = a.ur.y if a.ur.y == b.ll.y else b.ur.y
                    _ = graph.add_door(i, j, 0, IntBox(IntPoint(x0, yb), IntPoint(x0, yb)))
    graph.finalize_adjacency()


fn build_room_graph_from_grid(g: Grid, net_id: UInt32) -> RoomGraph:
    var graph = build_rooms_from_grid(g, net_id)
    # For small test cases use the naive door builder.
    connect_doors_naive(graph)
    return graph^


fn build_room_graph_from_grid_fast(g: Grid, net_id: UInt32) -> RoomGraph:
    var graph = build_rooms_from_grid(g, net_id)
    connect_doors_from_room_map(graph, g.width, g.height)
    return graph^


fn build_room_graph_from_grid_fast_with_keepouts(
    g: Grid,
    net_id: UInt32,
    use_touch: Bool,
    use_ko: Bool,
) -> RoomGraph:
    var graph = build_rooms_from_grid_with_keepouts(g, net_id, use_touch, use_ko)
    connect_doors_from_room_map(graph, g.width, g.height)
    return graph^
