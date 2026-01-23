from collections import List

from python import Python, PythonObject

from .drc_kernels import check_circle_segment_clearance, check_polygon_segment_clearance
from .geometry import AABB, Circle as GeoCircle, Segment as GeoSegment, Vec2, dist_segment_segment2

comptime py = Python


@fieldwise_init
struct MazeObstacleCircle(Copyable, Movable):
    var circle: GeoCircle
    var layers_mask: UInt32
    var net_id: UInt32


@fieldwise_init
struct MazeObstaclePoly(Copyable, Movable):
    var poly: List[Vec2]
    var layers_mask: UInt32
    var net_id: UInt32


@fieldwise_init
struct MazeNode(Copyable, Movable):
    var x_mm: Float64
    var y_mm: Float64
    var layer: Int


fn _rng_next(mut state: UInt64) -> UInt64:
    # LCG (PCG-ish constants); deterministic across platforms.
    state = state * UInt64(6364136223846793005) + UInt64(1442695040888963407)
    return state


fn _rng_f01(mut state: UInt64) -> Tuple[UInt64, Float64]:
    state = _rng_next(state)
    # Use top 53 bits for Float64 mantissa range.
    var v = (state >> UInt64(11)) & UInt64(0x1F_FFFF_FFFF_FFFF)
    return (state, Float64(v) / Float64(0x20_0000_0000_0000))


fn _layer_in_mask(layer: Int, mask: UInt32) -> Bool:
    if layer < 0 or layer >= 32:
        return True
    return (mask & (UInt32(1) << UInt32(layer))) != UInt32(0)


fn _segment_clear_of_static(
    seg: GeoSegment,
    layer: Int,
    net_id: UInt32,
    inflate_mm: Float64,
    circles: List[MazeObstacleCircle],
    polys: List[MazeObstaclePoly],
) -> Bool:
    var i = 0
    while i < len(circles):
        var o = circles[i].copy()
        if o.net_id == net_id:
            i += 1
            continue
        if not _layer_in_mask(layer, o.layers_mask):
            i += 1
            continue
        if check_circle_segment_clearance(seg=seg, circle=o.circle, clearance=inflate_mm):
            return False
        i += 1
    i = 0
    while i < len(polys):
        var p = polys[i].copy()
        if p.net_id == net_id:
            i += 1
            continue
        if not _layer_in_mask(layer, p.layers_mask):
            i += 1
            continue
        if check_polygon_segment_clearance(seg=seg, poly=p.poly, clearance=inflate_mm):
            return False
        i += 1
    return True


fn _segment_clear_of_tracks(
    seg: GeoSegment,
    layer: Int,
    net_id: UInt32,
    inflate_mm: Float64,
    track_db: PythonObject,
) raises -> Bool:
    # Track record schema:
    # [layer_idx:int, net_id:int, width_mm:float, sx,sy,ex,ey,minx,miny,maxx,maxy]
    if not track_db:
        return True
    var bb = seg.aabb()
    bb.min_x = bb.min_x - inflate_mm
    bb.min_y = bb.min_y - inflate_mm
    bb.max_x = bb.max_x + inflate_mm
    bb.max_y = bb.max_y + inflate_mm

    var k0 = PythonObject(Int(0))
    var k1 = PythonObject(Int(1))
    var k2 = PythonObject(Int(2))
    var k3 = PythonObject(Int(3))
    var k4 = PythonObject(Int(4))
    var k5 = PythonObject(Int(5))
    var k6 = PythonObject(Int(6))
    var k7 = PythonObject(Int(7))
    var k8 = PythonObject(Int(8))
    var k9 = PythonObject(Int(9))
    var k10 = PythonObject(Int(10))

    for rec in track_db:
        var r_layer = Int(py=rec[k0])
        if r_layer != layer:
            continue
        var r_net = UInt32(Int(py=rec[k1]))
        if r_net == net_id:
            continue
        var minx = Float64(py=rec[k7])
        var miny = Float64(py=rec[k8])
        var maxx = Float64(py=rec[k9])
        var maxy = Float64(py=rec[k10])
        if maxx < bb.min_x or minx > bb.max_x or maxy < bb.min_y or miny > bb.max_y:
            continue
        var r_w = Float64(py=rec[k2])
        var r_sx = Float64(py=rec[k3])
        var r_sy = Float64(py=rec[k4])
        var r_ex = Float64(py=rec[k5])
        var r_ey = Float64(py=rec[k6])
        var other = GeoSegment(Vec2(r_sx, r_sy), Vec2(r_ex, r_ey))
        var r = inflate_mm + (r_w / Float64(2.0))
        if dist_segment_segment2(seg.a, seg.b, other.a, other.b) < (r * r):
            return False
    return True


fn _point_clear_of_static(
    p: Vec2,
    layer: Int,
    net_id: UInt32,
    inflate_mm: Float64,
    circles: List[MazeObstacleCircle],
    polys: List[MazeObstaclePoly],
) -> Bool:
    # Point is treated as tiny segment; reuse segment predicates for simplicity.
    var seg = GeoSegment(p.copy(), p.copy())
    return _segment_clear_of_static(seg, layer, net_id, inflate_mm, circles, polys)


fn _point_clear_of_tracks(
    p: Vec2,
    layer: Int,
    net_id: UInt32,
    inflate_mm: Float64,
    track_db: PythonObject,
) raises -> Bool:
    var seg = GeoSegment(p.copy(), p.copy())
    return _segment_clear_of_tracks(seg, layer, net_id, inflate_mm, track_db)


fn _mm_to_cell(x_mm: Float64, origin_mm: Float64, resolution_mm: Float64) -> Int:
    # Round-to-nearest cell.
    var fx = (x_mm - origin_mm) / resolution_mm
    var ix = Int(fx + Float64(0.5))
    return ix


fn _line_cells_2d(
    x0: Int,
    y0: Int,
    x1: Int,
    y1: Int,
) -> List[Tuple[Int, Int]]:
    # Bresenham (inclusive).
    var out = List[Tuple[Int, Int]]()
    var dx = x1 - x0
    var dy = y1 - y0
    var sx = 1
    if dx < 0:
        sx = -1
        dx = -dx
    var sy = 1
    if dy < 0:
        sy = -1
        dy = -dy
    var err = dx - dy
    var x = x0
    var y = y0
    while True:
        out.append((x, y))
        if x == x1 and y == y1:
            break
        var e2 = err + err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return out^


fn _grid_idx(layer: Int, x: Int, y: Int, width: Int, height: Int) -> Int:
    return layer * width * height + y * width + x


fn _polyline_to_grid_path(
    layer: Int,
    pts: List[Vec2],
    *,
    width: Int,
    height: Int,
    origin_x_mm: Float64,
    origin_y_mm: Float64,
    resolution_mm: Float64,
) -> List[Int]:
    var path = List[Int]()
    if len(pts) < 2:
        return path^
    var i = 0
    while i + 1 < len(pts):
        var a = pts[i].copy()
        var b = pts[i + 1].copy()
        var x0 = _mm_to_cell(a.x, origin_x_mm, resolution_mm)
        var y0 = _mm_to_cell(a.y, origin_y_mm, resolution_mm)
        var x1 = _mm_to_cell(b.x, origin_x_mm, resolution_mm)
        var y1 = _mm_to_cell(b.y, origin_y_mm, resolution_mm)
        for (x, y) in _line_cells_2d(x0, y0, x1, y1):
            if len(path) == 0:
                path.append(_grid_idx(layer, x, y, width, height))
            else:
                var idx = _grid_idx(layer, x, y, width, height)
                if idx != path[len(path) - 1]:
                    path.append(idx)
        i += 1
    return path^


fn _dijkstra(
    nodes: List[MazeNode],
    neigh: List[List[Int]],
    start_id: Int,
    goal_id: Int,
    dist_w: List[List[Float64]],
) -> List[Int]:
    # Simple Dijkstra using O(N^2) selection (good enough for small graphs).
    var n = len(nodes)
    var inf = Float64(1e300)
    var dist = List[Float64](length=n, fill=inf)
    var prev = List[Int](length=n, fill=-1)
    var used = List[UInt8](length=n, fill=UInt8(0))
    dist[start_id] = Float64(0.0)
    var it = 0
    while it < n:
        var best = -1
        var best_d = inf
        var i = 0
        while i < n:
            if used[i] == UInt8(0) and dist[i] < best_d:
                best_d = dist[i]
                best = i
            i += 1
        if best < 0:
            break
        if best == goal_id:
            break
        used[best] = UInt8(1)
        var j = 0
        while j < len(neigh[best]):
            var nb = neigh[best][j]
            if used[nb] != UInt8(0):
                j += 1
                continue
            var w = dist_w[best][j]
            var nd = best_d + w
            if nd < dist[nb]:
                dist[nb] = nd
                prev[nb] = best
            j += 1
        it += 1
    if prev[goal_id] < 0 and goal_id != start_id:
        return List[Int]()^
    var out = List[Int]()
    var cur = goal_id
    out.append(cur)
    while cur != start_id:
        cur = prev[cur]
        if cur < 0:
            return List[Int]()^
        out.append(cur)
    # reverse
    var rev = List[Int]()
    var k = len(out) - 1
    while k >= 0:
        rev.append(out[k])
        k -= 1
    return rev^


fn maze_route_prm_single_layer(
    *,
    layer: Int,
    start_mm: Vec2,
    goal_mm: Vec2,
    net_id: UInt32,
    track_width_mm: Float64,
    clearance_mm: Float64,
    circles: List[MazeObstacleCircle],
    polys: List[MazeObstaclePoly],
    track_db: PythonObject,
    origin_x_mm: Float64,
    origin_y_mm: Float64,
    board_w_mm: Float64,
    board_h_mm: Float64,
    resolution_mm: Float64,
    width: Int,
    height: Int,
    seed: UInt64,
    samples: Int,
    k_neigh: Int,
) raises -> List[Int]:
    var inflate = (track_width_mm / Float64(2.0)) + clearance_mm
    var bbox = AABB(origin_x_mm + Float64(0.0), origin_y_mm + Float64(0.0), origin_x_mm + board_w_mm, origin_y_mm + board_h_mm)

    var nodes = List[MazeNode]()
    nodes.append(MazeNode(start_mm.x, start_mm.y, layer))
    nodes.append(MazeNode(goal_mm.x, goal_mm.y, layer))

    # Seed points along straight line to help narrow corridors.
    var s = start_mm.copy()
    var g = goal_mm.copy()
    var t = 1
    while t < 8:
        var u = Float64(t) / Float64(8.0)
        var px = s.x + (g.x - s.x) * u
        var pyv = s.y + (g.y - s.y) * u
        nodes.append(MazeNode(px, pyv, layer))
        t += 1

    var rng = seed
    var i = 0
    while i < samples:
        var r = Float64(0.0)
        (rng, r) = _rng_f01(rng)
        var rr = Float64(0.0)
        (rng, rr) = _rng_f01(rng)
        var x = bbox.min_x + (bbox.max_x - bbox.min_x) * r
        var y = bbox.min_y + (bbox.max_y - bbox.min_y) * rr
        var p = Vec2(x, y)
        if _point_clear_of_static(p, layer, net_id, inflate, circles, polys) and _point_clear_of_tracks(p, layer, net_id, inflate, track_db):
            nodes.append(MazeNode(x, y, layer))
        i += 1

    var n = len(nodes)
    if n < 2:
        return List[Int]()^

    # Build adjacency (k-nearest).
    var neigh = List[List[Int]](length=n, fill=List[Int]())
    var dist_w = List[List[Float64]](length=n, fill=List[Float64]())

    var a = 0
    while a < n:
        # Collect candidate distances.
        var cand_ids = List[Int]()
        var cand_d = List[Float64]()
        var ax = nodes[a].x_mm
        var ay = nodes[a].y_mm
        var b = 0
        while b < n:
            if b == a:
                b += 1
                continue
            var dx = nodes[b].x_mm - ax
            var dy = nodes[b].y_mm - ay
            var d2 = dx * dx + dy * dy
            cand_ids.append(b)
            cand_d.append(d2)
            b += 1
        # Partial select k smallest (O(N*k)).
        var kk = k_neigh
        if kk > len(cand_ids):
            kk = len(cand_ids)
        var sel = 0
        while sel < kk:
            var best_i = sel
            var best_d = cand_d[sel]
            var j = sel + 1
            while j < len(cand_d):
                if cand_d[j] < best_d:
                    best_d = cand_d[j]
                    best_i = j
                j += 1
            # swap
            var tmp_id = cand_ids[sel]
            cand_ids[sel] = cand_ids[best_i]
            cand_ids[best_i] = tmp_id
            var tmp_d = cand_d[sel]
            cand_d[sel] = cand_d[best_i]
            cand_d[best_i] = tmp_d

            # Edge validity
            var nb = cand_ids[sel]
            var seg = GeoSegment(Vec2(ax, ay), Vec2(nodes[nb].x_mm, nodes[nb].y_mm))
            if _segment_clear_of_static(seg, layer, net_id, inflate, circles, polys) and _segment_clear_of_tracks(seg, layer, net_id, inflate, track_db):
                neigh[a].append(nb)
                # Use squared distance to avoid sqrt (monotonic and adequate for shortest-path selection).
                dist_w[a].append(cand_d[sel])
                # Add reverse edge to improve connectivity (PRM as undirected graph).
                neigh[nb].append(a)
                dist_w[nb].append(cand_d[sel])
            sel += 1
        a += 1

    var path_nodes = _dijkstra(nodes, neigh, 0, 1, dist_w)
    if len(path_nodes) == 0:
        return List[Int]()^

    var pts = List[Vec2]()
    for nid in path_nodes:
        pts.append(Vec2(nodes[nid].x_mm, nodes[nid].y_mm))

    return _polyline_to_grid_path(
        layer,
        pts,
        width=width,
        height=height,
        origin_x_mm=origin_x_mm,
        origin_y_mm=origin_y_mm,
        resolution_mm=resolution_mm,
    )
