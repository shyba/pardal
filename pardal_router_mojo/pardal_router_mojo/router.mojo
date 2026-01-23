from collections import List

from python import Python, PythonObject

from .astar import AStarWorkspace, abs_i, idx_to_coords, route_a_star, route_a_star_bounded
from .drc_kernels import check_circle_segment_clearance, check_polygon_segment_clearance
from .geometry import AABB, Circle as GeoCircle, Segment as GeoSegment, Vec2, circle_intersects_circle, dist_segment_segment2
from .grid import Grid, SpacingBundle
from .maze import MazeObstacleCircle, MazeObstaclePoly, maze_route_prm_single_layer
from .spatial_index import SpatialSegmentIndex

comptime py = Python

fn _now_s() raises -> Float64:
    var time = py.import_module("time")
    return Float64(py=time.perf_counter())

fn _py_set() raises -> PythonObject:
    var builtins = py.import_module("builtins")
    return builtins.set()

fn _via_is_micro(span_layers: PythonObject) raises -> Bool:
    # Heuristic: if a via spans exactly 2 adjacent layers, treat as microvia.
    # The extractor currently doesn't provide explicit via type.
    var n = Int(py=span_layers.__len__())
    if n != 2:
        return False
    var lo = Int(py=span_layers[PythonObject(Int(0))])
    var hi = Int(py=span_layers[PythonObject(Int(1))])
    if lo > hi:
        var t = lo
        lo = hi
        hi = t
    return (hi - lo) == 1


struct RouteConfig:
    var margin_init: Int
    var margin_step: Int
    var margin_max: Int
    var via_penalty: UInt32
    var layer_penalty_outer: UInt32
    var layer_penalty_in1: UInt32
    var layer_penalty_inner: UInt32
    var diagonal: Bool
    var attempts: Int
    var seed: UInt64
    var heuristic_weight_pct: UInt32
    var astar_max_expansions: UInt32
    var max_time_ms: UInt32
    var per_net_time_ms: UInt32
    var precommit_drc_enable: Bool
    var precommit_shorts_enable: Bool
    var pull_tight_enable: Bool
    var commit_routes: Bool
    var ripup_k: Int
    var ripup_passes: Int
    var ripup_progressive: Bool
    var ripup_extra_candidates: Int
    var ripup_extra_dist_cells: Int
    var ncr_iters: Int
    var ncr_present_cost: UInt32
    var ncr_history_cost: UInt32
    var ncr_history_inc: UInt16
    var ncr_allow_overlaps: Bool
    var legalize_passes: Int
    var escape_enable: Bool
    var escape_margin: Int
    var escape_margin_step: Int
    var escape_margin_max: Int
    var escape_unique_exit: Bool
    var escape_commit_early: Bool
    var batch_fanout_enable: Bool
    var batch_fanout_max_candidates: Int
    var enforce_spacing: Bool
    var keepout_track_cells: Int
    var keepout_via_cells: Int
    var keepout_safety_mm: Float64
    var keepout_clearance_scale: Float64
    var enforce_touch: Bool
    var spacing_present_cost: UInt32
    var spacing_present_cap: UInt16
    var forbid_stacked_vias: Bool
    var route_power_last: Bool
    var seed_circle_keepouts: Bool
    var net_layer_allow: PythonObject
    var precommit_index_existing_vias: Bool
    var precommit_fast_index_enable: Bool
    var precommit_fast_index_cell_mm: Float64
    var shove_enable: Bool
    var shove_max_rips: Int
    var static_obstacle_keepouts: Bool
    var legalize_use_grid_keepouts: Bool
    var maze_fallback_enable: Bool
    var maze_samples: Int
    var maze_k_neigh: Int
    var maze_track_index_cell_mm: Float64
    var debug: Bool

    fn __init__(out self):
        self.margin_init = 128
        self.margin_step = 128
        self.margin_max = 0
        self.via_penalty = UInt32(40)
        self.layer_penalty_outer = UInt32(0)
        self.layer_penalty_in1 = UInt32(0)
        self.layer_penalty_inner = UInt32(0)
        self.diagonal = True
        self.attempts = 6
        self.seed = UInt64(0)
        self.heuristic_weight_pct = UInt32(100)
        self.astar_max_expansions = UInt32(0)
        self.max_time_ms = UInt32(0)
        self.per_net_time_ms = UInt32(0)
        self.precommit_drc_enable = False
        self.precommit_shorts_enable = False
        self.pull_tight_enable = False
        self.commit_routes = True
        self.ripup_passes = 2
        self.ripup_k = 8
        self.ripup_progressive = False
        self.ripup_extra_candidates = 0
        self.ripup_extra_dist_cells = 0
        self.ncr_iters = 0
        self.ncr_present_cost = UInt32(60)
        self.ncr_history_cost = UInt32(10)
        self.ncr_history_inc = UInt16(1)
        self.ncr_allow_overlaps = True
        self.legalize_passes = 2
        self.enforce_spacing = False
        self.keepout_track_cells = 0
        self.keepout_via_cells = 0
        self.keepout_safety_mm = Float64(0.0)
        self.keepout_clearance_scale = Float64(1.0)
        self.enforce_touch = True
        self.spacing_present_cost = UInt32(12000)
        self.spacing_present_cap = UInt16(200)
        self.forbid_stacked_vias = False
        self.route_power_last = False
        self.seed_circle_keepouts = False
        self.net_layer_allow = py.none()
        self.escape_enable = False
        self.escape_margin = 50
        self.escape_margin_step = 20
        self.escape_margin_max = 250
        self.escape_unique_exit = True
        self.escape_commit_early = False
        self.batch_fanout_enable = False
        self.batch_fanout_max_candidates = 16
        self.precommit_index_existing_vias = False
        self.precommit_fast_index_enable = False
        self.precommit_fast_index_cell_mm = Float64(2.0)
        self.shove_enable = False
        self.shove_max_rips = 4
        self.static_obstacle_keepouts = True
        self.legalize_use_grid_keepouts = False
        self.maze_fallback_enable = False
        self.maze_samples = 1200
        self.maze_k_neigh = 14
        self.maze_track_index_cell_mm = Float64(2.0)
        self.debug = False


fn _pick_escape_exit(candidates: List[Int], start_i: Int, used_exits: PythonObject, unique: Bool) raises -> Int:
    if not unique:
        if len(candidates) <= start_i:
            return -1
        return candidates[start_i]
    var i = start_i
    while i < len(candidates):
        var idx = candidates[i]
        if not used_exits.__contains__(PythonObject(idx)):
            return idx
        i += 1
    return -1


fn _plan_escape_path(
    mut ws: AStarWorkspace,
    g: Grid,
    start_idx: Int,
    net_id: UInt32,
    escape_bb: BBox,
    candidates: List[Int],
    used_exits: PythonObject,
    unique_exit: Bool,
    attempts: Int,
    cfg: RouteConfig,
    spacing: SpacingBundle,
    existing_via_any: List[UInt32],
    existing_via_seg: List[UInt32],
    allowed_mask: UInt32,
    iter: UInt32,
    seed_tag: UInt64,
    deadline_s: Float64,
) raises -> List[Int]:
    if len(candidates) == 0:
        return List[Int]()
    var ci = 0
    while ci < len(candidates):
        var exit_idx = _pick_escape_exit(candidates, ci, used_exits, unique_exit)
        if exit_idx < 0:
            break
        var esc_attempt = 0
        while esc_attempt < attempts:
            var esc_seed = cfg.seed ^ (UInt64(iter) << UInt64(32)) ^ (UInt64(net_id) << UInt64(1)) ^ UInt64(esc_attempt) ^ (UInt64(ci) << UInt64(16)) ^ seed_tag
            var ep = route_a_star_bounded(
                ws,
                g,
                start_idx,
                exit_idx,
                net_id,
                esc_seed,
                cfg.diagonal,
                cfg.via_penalty,
                cfg.layer_penalty_outer,
                cfg.layer_penalty_in1,
                cfg.layer_penalty_inner,
                escape_bb.x0,
                escape_bb.y0,
                escape_bb.x1,
                escape_bb.y1,
                cfg.astar_max_expansions,
                cfg.heuristic_weight_pct,
                deadline_s,
                cfg.enforce_spacing,
                cfg.enforce_touch,
                False,
                cfg.spacing_present_cost,
                cfg.spacing_present_cap,
                UInt32(0),
                UInt32(0),
                False,
                existing_via_any,
                existing_via_seg,
                cfg.forbid_stacked_vias,
                allowed_mask,
            )
            if len(ep) > 0:
                used_exits.add(PythonObject(exit_idx))
                return ep^
            esc_attempt += 1
        ci += 1
    return List[Int]()


fn _plan_escape_path_adaptive(
    mut ws: AStarWorkspace,
    g: Grid,
    start_idx: Int,
    net_id: UInt32,
    used_exits: PythonObject,
    attempts: Int,
    cfg: RouteConfig,
    spacing: SpacingBundle,
    existing_via_any: List[UInt32],
    existing_via_seg: List[UInt32],
    allowed_mask: UInt32,
    iter: UInt32,
    seed_tag: UInt64,
    max_candidates: Int,
    deadline_s: Float64,
) raises -> List[Int]:
    var margin = cfg.escape_margin
    var step = cfg.escape_margin_step
    if step <= 0:
        step = 10
    var max_m = cfg.escape_margin_max
    if max_m < margin:
        max_m = margin
    while margin <= max_m:
        var escape_bb = _bbox_expand(_bbox_from_point(start_idx, g.width, g.height, margin), 0, g.width, g.height)
        var candidates = _exit_candidates_from_start(g, start_idx, net_id, escape_bb, max_candidates)
        if g.layers > 2:
            candidates = _exit_candidates_from_start_3d(g, start_idx, net_id, escape_bb, max_candidates)
        if len(candidates) > 0:
            var ep = _plan_escape_path(
                ws,
                g,
                start_idx,
                net_id,
                escape_bb,
                candidates,
                used_exits,
                cfg.escape_unique_exit,
                attempts,
                cfg,
                spacing,
                existing_via_any,
                existing_via_seg,
                allowed_mask,
                iter,
                seed_tag,
                deadline_s,
            )
            if len(ep) > 0:
                return ep^
        margin += step
    return List[Int]()


fn _int_from_py(v: PythonObject) raises -> Int:
    return Int(py=v)


fn _u32_from_py(v: PythonObject) raises -> UInt32:
    return UInt32(Int(py=v))


fn _f64_from_py(v: PythonObject) raises -> Float64:
    return Float64(py=v)


fn _bool_from_py(v: PythonObject) raises -> Bool:
    # Mojo Bool does not accept a PythonObject directly; Python bools convert to Int.
    return Int(py=v) != 0

fn _ceil_div(a: Float64, b: Float64) -> Int:
    if b <= 0.0:
        return 0
    var q = a / b
    var qi = Int(q)
    if Float64(qi) == q:
        return qi
    return qi + 1


fn _get(d: PythonObject, key: String) raises -> PythonObject:
    return d[PythonObject(key)]

fn _clamp_i(v: Int, lo: Int, hi: Int) -> Int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v

fn _angle_less(ax: Int, ay: Int, bx: Int, by: Int) -> Bool:
    # Polar-angle ordering around the origin (counter-clockwise), starting at +X.
    # This avoids float atan2; stable for routing heuristics.
    var ha = ay > 0 or (ay == 0 and ax >= 0)
    var hb = by > 0 or (by == 0 and bx >= 0)
    if ha != hb:
        return ha and not hb
    var cross = Int64(ax) * Int64(by) - Int64(ay) * Int64(bx)
    if cross != Int64(0):
        return cross > Int64(0)
    var da = Int64(ax) * Int64(ax) + Int64(ay) * Int64(ay)
    var db = Int64(bx) * Int64(bx) + Int64(by) * Int64(by)
    return da < db

struct BBox:
    var x0: Int
    var y0: Int
    var x1: Int
    var y1: Int

    fn __init__(out self, x0: Int, y0: Int, x1: Int, y1: Int):
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1


fn _bbox_from_starts(start_idxs: List[Int], width: Int, height: Int) -> BBox:
    if len(start_idxs) == 0:
        return BBox(0, 0, -1, -1)
    var x0 = width
    var y0 = height
    var x1 = 0
    var y1 = 0
    var i = 0
    while i < len(start_idxs):
        var p = idx_to_coords(start_idxs[i], width, height)
        if p.x < x0:
            x0 = p.x
        if p.y < y0:
            y0 = p.y
        if p.x > x1:
            x1 = p.x
        if p.y > y1:
            y1 = p.y
        i += 1
    if x0 >= width or y0 >= height:
        return BBox(0, 0, -1, -1)
    return BBox(x0, y0, x1, y1)


fn _bbox_expand(bb: BBox, margin: Int, width: Int, height: Int) -> BBox:
    if bb.x1 < bb.x0 or bb.y1 < bb.y0:
        return BBox(bb.x0, bb.y0, bb.x1, bb.y1)
    var x0 = bb.x0 - margin
    var y0 = bb.y0 - margin
    var x1 = bb.x1 + margin
    var y1 = bb.y1 + margin
    x0 = _clamp_i(x0, 0, width - 1)
    y0 = _clamp_i(y0, 0, height - 1)
    x1 = _clamp_i(x1, 0, width - 1)
    y1 = _clamp_i(y1, 0, height - 1)
    return BBox(x0, y0, x1, y1)

struct RerouteResult(Movable):
    var path: List[Int]
    var tracks: PythonObject
    var vias: PythonObject
    var ok: Bool

    fn __init__(out self):
        self.path = List[Int]()
        self.tracks = py.none()
        self.vias = py.none()
        self.ok = False


fn _try_reroute_path_bounded(
    mut ws: AStarWorkspace,
    mut g: Grid,
    spec_idx: Int,
    net_clearance_mm: Float64,
    net_names: List[String],
    net_ids: List[UInt32],
    start_idxs: List[Int],
    goal_idxs: List[Int],
    track_width_mm: List[Float64],
    via_diameter_mm: List[Float64],
    via_drill_mm: List[Float64],
    uvia_diameter_mm: List[Float64],
    uvia_drill_mm: List[Float64],
    layers: List[String],
    resolution_mm: Float64,
    origin_x_mm: Float64,
    origin_y_mm: Float64,
    width: Int,
    height: Int,
    existing_vias_py: PythonObject,
    pad_stacks_py: PythonObject,
    allowed_mask: UInt32,
    spacing: SpacingBundle,
    cfg: RouteConfig,
    *,
    bound: BBox,
    iter_tag: UInt64,
    seed_tag: UInt64,
    deadline_s: Float64,
    pre_db: PrecommitDB,
    keepout_circles: List[GeoCircle],
    keepout_circle_net: List[UInt32],
    keepout_polygons: List[List[Vec2]],
    keepout_poly_net: List[UInt32],
    keepout_circle_mask: List[UInt32],
    keepout_poly_mask: List[UInt32],
    clearance_mm: Float64,
    existing_via_any: List[UInt32],
    existing_via_seg: List[UInt32],
) raises -> RerouteResult:
    var res = RerouteResult()
    if spec_idx < 0 or spec_idx >= len(net_ids):
        return res^
    var net_id = net_ids[spec_idx]
    var net_name = net_names[spec_idx]
    var attempt = 0
    while attempt < cfg.attempts:
        var seed = cfg.seed ^ (UInt64(net_id) << UInt64(1)) ^ (UInt64(iter_tag) << UInt64(32)) ^ UInt64(attempt) ^ seed_tag
        var path = route_a_star_bounded(
            ws,
            g,
            start_idxs[spec_idx],
            goal_idxs[spec_idx],
            net_id,
            seed,
            cfg.diagonal,
            cfg.via_penalty,
            cfg.layer_penalty_outer,
            cfg.layer_penalty_in1,
            cfg.layer_penalty_inner,
            bound.x0,
            bound.y0,
            bound.x1,
            bound.y1,
            cfg.astar_max_expansions,
            cfg.heuristic_weight_pct,
            deadline_s,
            cfg.enforce_spacing,
            cfg.enforce_touch,
            cfg.ncr_allow_overlaps,
            cfg.spacing_present_cost,
            cfg.spacing_present_cap,
            cfg.ncr_present_cost,
            cfg.ncr_history_cost,
            False,
            existing_via_any,
            existing_via_seg,
            cfg.forbid_stacked_vias,
            allowed_mask,
        )
        if len(path) == 0:
            attempt += 1
            continue
        if cfg.pull_tight_enable:
            path = _pull_tight_path(g, net_id, path, cfg.diagonal, cfg.enforce_touch, cfg.enforce_spacing)
        var tv = _path_to_tracks_and_vias(
            net_name,
            track_width_mm[spec_idx],
            via_diameter_mm[spec_idx],
            via_drill_mm[spec_idx],
            uvia_diameter_mm[spec_idx],
            uvia_drill_mm[spec_idx],
            layers,
            resolution_mm,
            origin_x_mm,
            origin_y_mm,
            width,
            height,
            path,
            existing_vias_py,
            pad_stacks_py,
        )
        if cfg.precommit_drc_enable and _tracks_violate_keepouts(
            tv.tracks,
            keepout_circles,
            keepout_circle_net,
            keepout_polygons,
            keepout_poly_net,
            keepout_circle_mask,
            keepout_poly_mask,
            layers,
            clearance_mm,
            net_id,
        ):
            attempt += 1
            continue
        if cfg.precommit_shorts_enable:
            var culprit = _tracks_first_conflict_net(
                tv.tracks,
                net_id,
                layers,
                pre_db.tracks,
                pre_db.vias,
                clearance_mm,
                track_index_enabled=pre_db.track_index_enabled,
                track_index=pre_db.track_index,
            )
            if culprit == UInt32(0):
                culprit = _vias_first_conflict_net(tv.vias, net_id, layers, pre_db.tracks, pre_db.vias, clearance_mm)
            if culprit != UInt32(0):
                if cfg.ncr_history_inc != UInt16(0):
                    _ = g.update_history_for_path(net_id, path.copy(), cfg.ncr_history_inc)
                attempt += 1
                continue
        res.path = path^
        res.tracks = tv.tracks
        res.vias = tv.vias
        res.ok = True
        return res^
    return res^


fn _exit_side(
    goal_idx: Int,
    bb: BBox,
    width: Int,
    height: Int,
) -> Int:
    # 0=left,1=right,2=top,3=bottom
    var g = idx_to_coords(goal_idx, width, height)
    var cx = (bb.x0 + bb.x1) // 2
    var cy = (bb.y0 + bb.y1) // 2
    var dx = g.x - cx
    var dy = g.y - cy
    if abs_i(dx) >= abs_i(dy):
        return 0 if dx < 0 else 1
    return 2 if dy < 0 else 3

fn _exit_side_from_start(
    start_idx: Int,
    bb: BBox,
    width: Int,
    height: Int,
) -> Int:
    # 0=left,1=right,2=top,3=bottom
    var s = idx_to_coords(start_idx, width, height)
    var dl = s.x - bb.x0
    var dr = bb.x1 - s.x
    var dt = s.y - bb.y0
    var db = bb.y1 - s.y
    var best = dl
    var side = 0
    if dr < best:
        best = dr
        side = 1
    if dt < best:
        best = dt
        side = 2
    if db < best:
        side = 3
    return side


fn _exit_candidates(
    grid: Grid,
    start_idx: Int,
    goal_idx: Int,
    net_id: UInt32,
    bb: BBox,
    max_candidates: Int,
) -> List[Int]:
    var out = List[Int]()
    if bb.x1 < bb.x0 or bb.y1 < bb.y0:
        return out^
    var start = idx_to_coords(start_idx, grid.width, grid.height)
    var side = _exit_side(goal_idx, bb, grid.width, grid.height)

    var layer = start.layer
    var limit = max_candidates
    if limit <= 0:
        limit = 1
    if side == 0 or side == 1:
        var x = bb.x0 if side == 0 else bb.x1
        var y_seed = _clamp_i(start.y, bb.y0, bb.y1)
        if x >= bb.x0 and x <= bb.x1 and y_seed >= bb.y0 and y_seed <= bb.y1 and grid.in_bounds(layer, x, y_seed) and grid.base_allows(layer, x, y_seed, net_id):
            var idx0 = grid.idx(layer, x, y_seed)
            if grid.occ_other_at_idx(idx0, net_id) == UInt16(0):
                out.append(idx0)
        var d = 1
        while d <= (bb.y1 - bb.y0) and len(out) < limit:
            if y_seed - d >= bb.y0:
                var yy = y_seed - d
                if x >= bb.x0 and x <= bb.x1 and yy >= bb.y0 and yy <= bb.y1 and grid.in_bounds(layer, x, yy) and grid.base_allows(layer, x, yy, net_id):
                    var idx1 = grid.idx(layer, x, yy)
                    if grid.occ_other_at_idx(idx1, net_id) == UInt16(0):
                        out.append(idx1)
            if len(out) >= limit:
                break
            if y_seed + d <= bb.y1:
                var yy2 = y_seed + d
                if x >= bb.x0 and x <= bb.x1 and yy2 >= bb.y0 and yy2 <= bb.y1 and grid.in_bounds(layer, x, yy2) and grid.base_allows(layer, x, yy2, net_id):
                    var idx2 = grid.idx(layer, x, yy2)
                    if grid.occ_other_at_idx(idx2, net_id) == UInt16(0):
                        out.append(idx2)
            d += 1
    else:
        var y = bb.y0 if side == 2 else bb.y1
        var x_seed = _clamp_i(start.x, bb.x0, bb.x1)
        if x_seed >= bb.x0 and x_seed <= bb.x1 and y >= bb.y0 and y <= bb.y1 and grid.in_bounds(layer, x_seed, y) and grid.base_allows(layer, x_seed, y, net_id):
            var idx3 = grid.idx(layer, x_seed, y)
            if grid.occ_other_at_idx(idx3, net_id) == UInt16(0):
                out.append(idx3)
        var d = 1
        while d <= (bb.x1 - bb.x0) and len(out) < limit:
            if x_seed - d >= bb.x0:
                var xx = x_seed - d
                if xx >= bb.x0 and xx <= bb.x1 and y >= bb.y0 and y <= bb.y1 and grid.in_bounds(layer, xx, y) and grid.base_allows(layer, xx, y, net_id):
                    var idx4 = grid.idx(layer, xx, y)
                    if grid.occ_other_at_idx(idx4, net_id) == UInt16(0):
                        out.append(idx4)
            if len(out) >= limit:
                break
            if x_seed + d <= bb.x1:
                var xx2 = x_seed + d
                if xx2 >= bb.x0 and xx2 <= bb.x1 and y >= bb.y0 and y <= bb.y1 and grid.in_bounds(layer, xx2, y) and grid.base_allows(layer, xx2, y, net_id):
                    var idx5 = grid.idx(layer, xx2, y)
                    if grid.occ_other_at_idx(idx5, net_id) == UInt16(0):
                        out.append(idx5)
            d += 1
    return out^

fn _exit_candidates_from_start(
    grid: Grid,
    start_idx: Int,
    net_id: UInt32,
    bb: BBox,
    max_candidates: Int,
) -> List[Int]:
    # Like _exit_candidates, but chooses the escape side based on the start pad's
    # proximity to the bounding box edge (BGA-style fanout), rather than the goal.
    #
    # If the preferred side is fully blocked, we fall back to other sides so the
    # router can still escape crowded BGAs.
    var out = List[Int]()
    if bb.x1 < bb.x0 or bb.y1 < bb.y0:
        return out^

    var start = idx_to_coords(start_idx, grid.width, grid.height)
    var layer = start.layer
    var limit = max_candidates
    if limit <= 0:
        limit = 1
    var side0 = _exit_side_from_start(start_idx, bb, grid.width, grid.height)
    var sides = List[Int]()
    sides.append(side0)
    var s = 0
    while s < 4:
        if s != side0:
            sides.append(s)
        s += 1

    var si = 0
    while si < len(sides) and len(out) < limit:
        var side = sides[si]
        if side == 0 or side == 1:
            var x = bb.x0 if side == 0 else bb.x1
            var y_seed = _clamp_i(start.y, bb.y0, bb.y1)
            if x >= bb.x0 and x <= bb.x1 and y_seed >= bb.y0 and y_seed <= bb.y1 and grid.in_bounds(layer, x, y_seed) and grid.base_allows(layer, x, y_seed, net_id):
                var idx0 = grid.idx(layer, x, y_seed)
                if grid.occ_other_at_idx(idx0, net_id) == UInt16(0):
                    out.append(idx0)
            var d = 1
            while d <= (bb.y1 - bb.y0) and len(out) < limit:
                if y_seed - d >= bb.y0:
                    var yy = y_seed - d
                    if x >= bb.x0 and x <= bb.x1 and yy >= bb.y0 and yy <= bb.y1 and grid.in_bounds(layer, x, yy) and grid.base_allows(layer, x, yy, net_id):
                        var idx1 = grid.idx(layer, x, yy)
                        if grid.occ_other_at_idx(idx1, net_id) == UInt16(0):
                            out.append(idx1)
                if len(out) >= limit:
                    break
                if y_seed + d <= bb.y1:
                    var yy2 = y_seed + d
                    if x >= bb.x0 and x <= bb.x1 and yy2 >= bb.y0 and yy2 <= bb.y1 and grid.in_bounds(layer, x, yy2) and grid.base_allows(layer, x, yy2, net_id):
                        var idx2 = grid.idx(layer, x, yy2)
                        if grid.occ_other_at_idx(idx2, net_id) == UInt16(0):
                            out.append(idx2)
                d += 1
        else:
            var y = bb.y0 if side == 2 else bb.y1
            var x_seed = _clamp_i(start.x, bb.x0, bb.x1)
            if x_seed >= bb.x0 and x_seed <= bb.x1 and y >= bb.y0 and y <= bb.y1 and grid.in_bounds(layer, x_seed, y) and grid.base_allows(layer, x_seed, y, net_id):
                var idx3 = grid.idx(layer, x_seed, y)
                if grid.occ_other_at_idx(idx3, net_id) == UInt16(0):
                    out.append(idx3)
            var d = 1
            while d <= (bb.x1 - bb.x0) and len(out) < limit:
                if x_seed - d >= bb.x0:
                    var xx = x_seed - d
                    if xx >= bb.x0 and xx <= bb.x1 and y >= bb.y0 and y <= bb.y1 and grid.in_bounds(layer, xx, y) and grid.base_allows(layer, xx, y, net_id):
                        var idx4 = grid.idx(layer, xx, y)
                        if grid.occ_other_at_idx(idx4, net_id) == UInt16(0):
                            out.append(idx4)
                if len(out) >= limit:
                    break
                if x_seed + d <= bb.x1:
                    var xx2 = x_seed + d
                    if xx2 >= bb.x0 and xx2 <= bb.x1 and y >= bb.y0 and y <= bb.y1 and grid.in_bounds(layer, xx2, y) and grid.base_allows(layer, xx2, y, net_id):
                        var idx5 = grid.idx(layer, xx2, y)
                        if grid.occ_other_at_idx(idx5, net_id) == UInt16(0):
                            out.append(idx5)
                d += 1
        si += 1
    return out^

fn _exit_candidates_from_start_3d(
    grid: Grid,
    start_idx: Int,
    net_id: UInt32,
    bb: BBox,
    max_candidates: Int,
) -> List[Int]:
    # Like _exit_candidates_from_start, but proposes exits on *any* layer by
    # projecting candidates across layers. This is important for dense fanout:
    # a pad may need to immediately drop to an inner layer before escaping.
    var out = List[Int]()
    if bb.x1 < bb.x0 or bb.y1 < bb.y0:
        return out^

    var start = idx_to_coords(start_idx, grid.width, grid.height)
    var limit = max_candidates
    if limit <= 0:
        limit = 1

    var side0 = _exit_side_from_start(start_idx, bb, grid.width, grid.height)
    var sides = List[Int]()
    sides.append(side0)
    var s = 0
    while s < 4:
        if s != side0:
            sides.append(s)
        s += 1

    # Layer order: prefer the start layer, then the rest.
    var layers = List[Int]()
    layers.append(start.layer)
    var li = 0
    while li < grid.layers:
        if li != start.layer:
            layers.append(li)
        li += 1

    var si = 0
    while si < len(sides) and len(out) < limit:
        var side = sides[si]
        if side == 0 or side == 1:
            var x = bb.x0 if side == 0 else bb.x1
            var y_seed = _clamp_i(start.y, bb.y0, bb.y1)
            var d = 0
            while d <= (bb.y1 - bb.y0) and len(out) < limit:
                # d=0 is the seed, then alternate -1,+1,-2,+2...
                var yy = y_seed
                if d != 0:
                    var step = (d + 1) // 2
                    var sign = -1 if (d % 2) == 1 else 1
                    yy = y_seed + sign * step
                if yy >= bb.y0 and yy <= bb.y1:
                    for l in layers:
                        if len(out) >= limit:
                            break
                        if grid.in_bounds(l, x, yy) and grid.base_allows(l, x, yy, net_id):
                            var idx0 = grid.idx(l, x, yy)
                            if grid.occ_other_at_idx(idx0, net_id) == UInt16(0):
                                out.append(idx0)
                d += 1
        else:
            var y = bb.y0 if side == 2 else bb.y1
            var x_seed = _clamp_i(start.x, bb.x0, bb.x1)
            var d = 0
            while d <= (bb.x1 - bb.x0) and len(out) < limit:
                var xx = x_seed
                if d != 0:
                    var step = (d + 1) // 2
                    var sign = -1 if (d % 2) == 1 else 1
                    xx = x_seed + sign * step
                if xx >= bb.x0 and xx <= bb.x1:
                    for l in layers:
                        if len(out) >= limit:
                            break
                        if grid.in_bounds(l, xx, y) and grid.base_allows(l, xx, y, net_id):
                            var idx1 = grid.idx(l, xx, y)
                            if grid.occ_other_at_idx(idx1, net_id) == UInt16(0):
                                out.append(idx1)
                d += 1
        si += 1
    return out^


fn _bbox_from_start_goal(
    start_idx: Int,
    goal_idx: Int,
    width: Int,
    height: Int,
    margin: Int,
) -> BBox:
    var s = idx_to_coords(start_idx, width, height)
    var g = idx_to_coords(goal_idx, width, height)
    var x0 = min(s.x, g.x) - margin
    var y0 = min(s.y, g.y) - margin
    var x1 = max(s.x, g.x) + margin
    var y1 = max(s.y, g.y) + margin
    x0 = _clamp_i(x0, 0, width - 1)
    y0 = _clamp_i(y0, 0, height - 1)
    x1 = _clamp_i(x1, 0, width - 1)
    y1 = _clamp_i(y1, 0, height - 1)
    return BBox(x0, y0, x1, y1)

fn _bbox_from_point(
    idx: Int,
    width: Int,
    height: Int,
    margin: Int,
) -> BBox:
    var p = idx_to_coords(idx, width, height)
    var x0 = _clamp_i(p.x - margin, 0, width - 1)
    var y0 = _clamp_i(p.y - margin, 0, height - 1)
    var x1 = _clamp_i(p.x + margin, 0, width - 1)
    var y1 = _clamp_i(p.y + margin, 0, height - 1)
    return BBox(x0, y0, x1, y1)


fn _bbox_from_path(path: List[Int], width: Int, height: Int) -> BBox:
    if len(path) == 0:
        return BBox(0, 0, -1, -1)
    var p0 = idx_to_coords(path[0], width, height)
    var x0 = p0.x
    var y0 = p0.y
    var x1 = p0.x
    var y1 = p0.y
    var i = 1
    while i < len(path):
        var p = idx_to_coords(path[i], width, height)
        if p.x < x0:
            x0 = p.x
        if p.y < y0:
            y0 = p.y
        if p.x > x1:
            x1 = p.x
        if p.y > y1:
            y1 = p.y
        i += 1
    return BBox(x0, y0, x1, y1)


fn _bbox_intersects(a: BBox, b: BBox) -> Bool:
    if a.x1 < a.x0 or b.x1 < b.x0:
        return False
    return not (a.x1 < b.x0 or b.x1 < a.x0 or a.y1 < b.y0 or b.y1 < a.y0)

fn _point_in_poly(px: Int, py: Int, pts_x: List[Int], pts_y: List[Int]) -> Bool:
    # Even-odd rule. pts are in grid coords.
    if len(pts_x) < 3 or len(pts_x) != len(pts_y):
        return False
    var inside = False
    var j = len(pts_x) - 1
    var i = 0
    while i < len(pts_x):
        var xi = pts_x[i]
        var yi = pts_y[i]
        var xj = pts_x[j]
        var yj = pts_y[j]
        var cond = (yi > py) != (yj > py)
        if cond:
            # Compare x < x_intersect without floats by cross-multiplying.
            var lhs = (px - xi) * (yj - yi)
            var rhs = (py - yi) * (xj - xi)
            if (yj - yi) > 0:
                if lhs < rhs:
                    inside = not inside
            else:
                if lhs > rhs:
                    inside = not inside
        j = i
        i += 1
    return inside


fn _stamp_polygon_base(
    mut g: Grid,
    layer: Int,
    pts_x: List[Int],
    pts_y: List[Int],
    net_id: UInt32,
):
    if len(pts_x) < 3 or len(pts_x) != len(pts_y):
        return
    var min_x = pts_x[0]
    var max_x = pts_x[0]
    var min_y = pts_y[0]
    var max_y = pts_y[0]
    var i = 1
    while i < len(pts_x):
        var x = pts_x[i]
        var y = pts_y[i]
        if x < min_x:
            min_x = x
        if x > max_x:
            max_x = x
        if y < min_y:
            min_y = y
        if y > max_y:
            max_y = y
        i += 1
    min_x = _clamp_i(min_x, 0, g.width - 1)
    max_x = _clamp_i(max_x, 0, g.width - 1)
    min_y = _clamp_i(min_y, 0, g.height - 1)
    max_y = _clamp_i(max_y, 0, g.height - 1)
    var y = min_y
    while y <= max_y:
        var x = min_x
        while x <= max_x:
            if _point_in_poly(x, y, pts_x, pts_y):
                g.base_set(g.idx(layer, x, y), net_id)
            x += 1
        y += 1

fn _stamp_polygon_base_collect(
    mut g: Grid,
    layer: Int,
    pts_x: List[Int],
    pts_y: List[Int],
    net_id: UInt32,
) -> List[Int]:
    var out = List[Int]()
    if len(pts_x) < 3 or len(pts_x) != len(pts_y):
        return out^
    var min_x = pts_x[0]
    var max_x = pts_x[0]
    var min_y = pts_y[0]
    var max_y = pts_y[0]
    var i = 1
    while i < len(pts_x):
        var x = pts_x[i]
        var y = pts_y[i]
        if x < min_x:
            min_x = x
        if x > max_x:
            max_x = x
        if y < min_y:
            min_y = y
        if y > max_y:
            max_y = y
        i += 1
    min_x = _clamp_i(min_x, 0, g.width - 1)
    max_x = _clamp_i(max_x, 0, g.width - 1)
    min_y = _clamp_i(min_y, 0, g.height - 1)
    max_y = _clamp_i(max_y, 0, g.height - 1)
    var y = min_y
    while y <= max_y:
        var x = min_x
        while x <= max_x:
            if _point_in_poly(x, y, pts_x, pts_y):
                var idx = g.idx(layer, x, y)
                g.base_set(idx, net_id)
                out.append(idx)
            x += 1
        y += 1
    return out^

fn _merge_paths(a: List[Int], b: List[Int]) -> List[Int]:
    var out = List[Int]()
    for x in a:
        out.append(x)
    var i = 0
    if len(out) > 0 and len(b) > 0 and out[len(out) - 1] == b[0]:
        i = 1
    while i < len(b):
        out.append(b[i])
        i += 1
    return out^

fn build_offsets_for_min_dist_mm(min_dist_mm: Float64, res_mm: Float64) -> List[Int]:
    # Packed offsets as [dx0, dy0, dx1, dy1, ...].
    var out = List[Int]()
    if not (min_dist_mm > 0.0 and res_mm > 0.0):
        return out^
    # If the minimum distance is <= one cell, only the same cell could violate it, which is
    # handled separately by direct occupancy checks.
    if min_dist_mm <= res_mm:
        return out^
    var r = _ceil_div(min_dist_mm, res_mm)
    var min2 = min_dist_mm * min_dist_mm
    var eps = Float64(1e-12)
    var dy = -r
    while dy <= r:
        var dx = -r
        while dx <= r:
            if dx == 0 and dy == 0:
                dx += 1
                continue
            var fx = Float64(dx) * res_mm
            var fy = Float64(dy) * res_mm
            var d2 = fx * fx + fy * fy
            if d2 + eps < min2:
                out.append(dx)
                out.append(dy)
            dx += 1
        dy += 1
    return out^

fn _pull_tight_path(
    grid: Grid,
    net_id: UInt32,
    path: List[Int],
    diagonal: Bool,
    enforce_touch: Bool,
    enforce_spacing: Bool,
) -> List[Int]:
    # Grid-based "pull-tight" MVP:
    # 1) remove immediate duplicates
    # 2) remove collinear intermediate points (including diagonals if enabled)
    # 3) greedily shortcut with line-of-sight checks in grid space
    if len(path) < 3:
        return path.copy()
    var cleaned = List[Int]()
    cleaned.append(path[0])
    var i = 1
    while i < len(path):
        if path[i] != cleaned[len(cleaned) - 1]:
            cleaned.append(path[i])
        i += 1
    if len(cleaned) < 3:
        return cleaned^

    # Collinear removal.
    var col = List[Int]()
    col.append(cleaned[0])
    i = 1
    while i + 1 < len(cleaned):
        var a = idx_to_coords(col[len(col) - 1], grid.width, grid.height)
        var b = idx_to_coords(cleaned[i], grid.width, grid.height)
        var c = idx_to_coords(cleaned[i + 1], grid.width, grid.height)
        if a.layer == b.layer and b.layer == c.layer:
            var dx1 = b.x - a.x
            var dy1 = b.y - a.y
            var dx2 = c.x - b.x
            var dy2 = c.y - b.y
            var ndx1 = 0
            var ndy1 = 0
            if dx1 > 0:
                ndx1 = 1
            elif dx1 < 0:
                ndx1 = -1
            if dy1 > 0:
                ndy1 = 1
            elif dy1 < 0:
                ndy1 = -1
            var ndx2 = 0
            var ndy2 = 0
            if dx2 > 0:
                ndx2 = 1
            elif dx2 < 0:
                ndx2 = -1
            if dy2 > 0:
                ndy2 = 1
            elif dy2 < 0:
                ndy2 = -1
            if ndx1 == ndx2 and ndy1 == ndy2:
                # drop b
                i += 1
                continue
        col.append(cleaned[i])
        i += 1
    col.append(cleaned[len(cleaned) - 1])

    if len(col) < 3:
        return col^

    fn _cell_ok(grid: Grid, layer: Int, x: Int, y: Int) -> Bool:
        if not grid.in_bounds(layer, x, y):
            return False
        if not grid.base_allows(layer, x, y, net_id):
            return False
        var idx = grid.idx(layer, x, y)
        if grid.occ_other_at_idx(idx, net_id) != UInt16(0):
            return False
        if enforce_touch and (
            grid.touch_track_other_at_idx(idx, net_id) != UInt16(0)
            or grid.touch_via_other_at_idx(idx, net_id) != UInt16(0)
        ):
            return False
        if enforce_spacing and (
            grid.ko_track_other_at_idx(idx, net_id) != UInt16(0)
            or grid.ko_via_other_at_idx(idx, net_id) != UInt16(0)
        ):
            return False
        return True

    fn _los(grid: Grid, a_idx: Int, b_idx: Int) -> Bool:
        var a = idx_to_coords(a_idx, grid.width, grid.height)
        var b = idx_to_coords(b_idx, grid.width, grid.height)
        if a.layer != b.layer:
            return False
        var dx = b.x - a.x
        var dy = b.y - a.y
        # only axis-aligned or 45-degree if diagonal allowed
        if dx != 0 and dy != 0:
            if not diagonal:
                return False
            if abs_i(dx) != abs_i(dy):
                return False
        var sx = 0
        var sy = 0
        if dx > 0:
            sx = 1
        elif dx < 0:
            sx = -1
        if dy > 0:
            sy = 1
        elif dy < 0:
            sy = -1
        var x = a.x
        var y = a.y
        while x != b.x or y != b.y:
            x += sx
            y += sy
            if not _cell_ok(grid, a.layer, x, y):
                return False
        return True

    # Greedy shortcut.
    var out = List[Int]()
    var j = 0
    while j < len(col):
        out.append(col[j])
        if j == len(col) - 1:
            break
        var k = len(col) - 1
        while k > j + 1:
            if _los(grid, col[j], col[k]):
                break
            k -= 1
        j = k
    return out^


fn _apply_config(cfg_path: String, mut cfg: RouteConfig) raises:
    if cfg_path == "":
        return
    var pathlib = py.import_module("pathlib")
    var json = py.import_module("json")
    var txt = pathlib.Path(PythonObject(cfg_path)).read_text()
    var d = json.loads(txt)

    var k_margin_init = PythonObject(String("margin_init"))
    var k_margin_step = PythonObject(String("margin_step"))
    var k_margin_max = PythonObject(String("margin_max"))
    var k_via_penalty = PythonObject(String("via_penalty"))
    var k_layer_penalty_outer = PythonObject(String("layer_penalty_outer"))
    var k_layer_penalty_in1 = PythonObject(String("layer_penalty_in1"))
    var k_layer_penalty_inner = PythonObject(String("layer_penalty_inner"))
    var k_diagonal = PythonObject(String("diagonal"))
    var k_attempts = PythonObject(String("attempts"))
    var k_seed = PythonObject(String("seed"))
    var k_heuristic_weight_pct = PythonObject(String("heuristic_weight_pct"))
    var k_astar_max_expansions = PythonObject(String("astar_max_expansions"))
    var k_max_time_ms = PythonObject(String("max_time_ms"))
    var k_per_net_time_ms = PythonObject(String("per_net_time_ms"))
    var k_precommit_drc_enable = PythonObject(String("precommit_drc_enable"))
    var k_precommit_shorts_enable = PythonObject(String("precommit_shorts_enable"))
    var k_pull_tight_enable = PythonObject(String("pull_tight_enable"))
    var k_commit_routes = PythonObject(String("commit_routes"))
    var k_ripup_k = PythonObject(String("ripup_k"))
    var k_ripup_passes = PythonObject(String("ripup_passes"))
    var k_ripup_progressive = PythonObject(String("ripup_progressive"))
    var k_ripup_extra_candidates = PythonObject(String("ripup_extra_candidates"))
    var k_ripup_extra_dist_cells = PythonObject(String("ripup_extra_dist_cells"))
    var k_ncr_iters = PythonObject(String("ncr_iters"))
    var k_ncr_present_cost = PythonObject(String("ncr_present_cost"))
    var k_ncr_history_cost = PythonObject(String("ncr_history_cost"))
    var k_ncr_history_inc = PythonObject(String("ncr_history_inc"))
    var k_ncr_allow_overlaps = PythonObject(String("ncr_allow_overlaps"))
    var k_legalize_passes = PythonObject(String("legalize_passes"))
    var k_enforce_spacing = PythonObject(String("enforce_spacing"))
    var k_keepout_track_cells = PythonObject(String("keepout_track_cells"))
    var k_keepout_via_cells = PythonObject(String("keepout_via_cells"))
    var k_keepout_safety_mm = PythonObject(String("keepout_safety_mm"))
    var k_keepout_clearance_scale = PythonObject(String("keepout_clearance_scale"))
    var k_enforce_touch = PythonObject(String("enforce_touch"))
    var k_spacing_present_cost = PythonObject(String("spacing_present_cost"))
    var k_spacing_present_cap = PythonObject(String("spacing_present_cap"))
    var k_forbid_stacked_vias = PythonObject(String("forbid_stacked_vias"))
    var k_route_power_last = PythonObject(String("route_power_last"))
    var k_seed_circle_keepouts = PythonObject(String("seed_circle_keepouts"))
    var k_net_layer_allow = PythonObject(String("net_layer_allow"))
    var k_escape_enable = PythonObject(String("escape_enable"))
    var k_escape_margin = PythonObject(String("escape_margin"))
    var k_escape_margin_step = PythonObject(String("escape_margin_step"))
    var k_escape_margin_max = PythonObject(String("escape_margin_max"))
    var k_escape_unique_exit = PythonObject(String("escape_unique_exit"))
    var k_escape_commit_early = PythonObject(String("escape_commit_early"))
    var k_batch_fanout_enable = PythonObject(String("batch_fanout_enable"))
    var k_batch_fanout_max_candidates = PythonObject(String("batch_fanout_max_candidates"))
    var k_precommit_index_existing_vias = PythonObject(String("precommit_index_existing_vias"))
    var k_precommit_fast_index_enable = PythonObject(String("precommit_fast_index_enable"))
    var k_precommit_fast_index_cell_mm = PythonObject(String("precommit_fast_index_cell_mm"))
    var k_shove_enable = PythonObject(String("shove_enable"))
    var k_shove_max_rips = PythonObject(String("shove_max_rips"))
    var k_static_obstacle_keepouts = PythonObject(String("static_obstacle_keepouts"))
    var k_legalize_use_grid_keepouts = PythonObject(String("legalize_use_grid_keepouts"))
    var k_maze_fallback_enable = PythonObject(String("maze_fallback_enable"))
    var k_maze_samples = PythonObject(String("maze_samples"))
    var k_maze_k_neigh = PythonObject(String("maze_k_neigh"))
    var k_maze_track_index_cell_mm = PythonObject(String("maze_track_index_cell_mm"))
    var k_debug = PythonObject(String("debug"))

    # Only consume a small stable subset for now; ignore unknown keys.
    if d.__contains__(k_margin_init):
        cfg.margin_init = _int_from_py(d[k_margin_init])
    if d.__contains__(k_margin_step):
        cfg.margin_step = _int_from_py(d[k_margin_step])
    if d.__contains__(k_margin_max):
        cfg.margin_max = _int_from_py(d[k_margin_max])
    if d.__contains__(k_via_penalty):
        cfg.via_penalty = _u32_from_py(d[k_via_penalty])
    if d.__contains__(k_layer_penalty_outer):
        cfg.layer_penalty_outer = _u32_from_py(d[k_layer_penalty_outer])
    if d.__contains__(k_layer_penalty_in1):
        cfg.layer_penalty_in1 = _u32_from_py(d[k_layer_penalty_in1])
    if d.__contains__(k_layer_penalty_inner):
        cfg.layer_penalty_inner = _u32_from_py(d[k_layer_penalty_inner])
    if d.__contains__(k_diagonal):
        cfg.diagonal = _bool_from_py(d[k_diagonal])
    if d.__contains__(k_attempts):
        cfg.attempts = _int_from_py(d[k_attempts])
    if d.__contains__(k_seed):
        cfg.seed = UInt64(_int_from_py(d[k_seed]))
    if d.__contains__(k_heuristic_weight_pct):
        cfg.heuristic_weight_pct = _u32_from_py(d[k_heuristic_weight_pct])
    if d.__contains__(k_astar_max_expansions):
        cfg.astar_max_expansions = _u32_from_py(d[k_astar_max_expansions])
    if d.__contains__(k_max_time_ms):
        cfg.max_time_ms = _u32_from_py(d[k_max_time_ms])
    if d.__contains__(k_per_net_time_ms):
        cfg.per_net_time_ms = _u32_from_py(d[k_per_net_time_ms])
    if d.__contains__(k_precommit_drc_enable):
        cfg.precommit_drc_enable = _bool_from_py(d[k_precommit_drc_enable])
    if d.__contains__(k_precommit_shorts_enable):
        cfg.precommit_shorts_enable = _bool_from_py(d[k_precommit_shorts_enable])
    if d.__contains__(k_pull_tight_enable):
        cfg.pull_tight_enable = _bool_from_py(d[k_pull_tight_enable])
    if d.__contains__(k_commit_routes):
        cfg.commit_routes = _bool_from_py(d[k_commit_routes])
    if d.__contains__(k_ripup_passes):
        cfg.ripup_passes = _int_from_py(d[k_ripup_passes])
    if d.__contains__(k_ripup_k):
        cfg.ripup_k = _int_from_py(d[k_ripup_k])
    if d.__contains__(k_ripup_progressive):
        cfg.ripup_progressive = _bool_from_py(d[k_ripup_progressive])
    if d.__contains__(k_ripup_extra_candidates):
        cfg.ripup_extra_candidates = _int_from_py(d[k_ripup_extra_candidates])
    if d.__contains__(k_ripup_extra_dist_cells):
        cfg.ripup_extra_dist_cells = _int_from_py(d[k_ripup_extra_dist_cells])
    if d.__contains__(k_ncr_iters):
        cfg.ncr_iters = _int_from_py(d[k_ncr_iters])
    if d.__contains__(k_ncr_present_cost):
        cfg.ncr_present_cost = _u32_from_py(d[k_ncr_present_cost])
    if d.__contains__(k_ncr_history_cost):
        cfg.ncr_history_cost = _u32_from_py(d[k_ncr_history_cost])
    if d.__contains__(k_ncr_history_inc):
        cfg.ncr_history_inc = UInt16(_int_from_py(d[k_ncr_history_inc]))
    if d.__contains__(k_ncr_allow_overlaps):
        cfg.ncr_allow_overlaps = _bool_from_py(d[k_ncr_allow_overlaps])
    if d.__contains__(k_legalize_passes):
        cfg.legalize_passes = _int_from_py(d[k_legalize_passes])
    if d.__contains__(k_enforce_spacing):
        cfg.enforce_spacing = _bool_from_py(d[k_enforce_spacing])
    if d.__contains__(k_keepout_track_cells) and d[k_keepout_track_cells] != py.none():
        cfg.keepout_track_cells = _int_from_py(d[k_keepout_track_cells])
    if d.__contains__(k_keepout_via_cells) and d[k_keepout_via_cells] != py.none():
        cfg.keepout_via_cells = _int_from_py(d[k_keepout_via_cells])
    if d.__contains__(k_keepout_safety_mm):
        cfg.keepout_safety_mm = _f64_from_py(d[k_keepout_safety_mm])
    if d.__contains__(k_keepout_clearance_scale):
        cfg.keepout_clearance_scale = _f64_from_py(d[k_keepout_clearance_scale])
    if d.__contains__(k_enforce_touch):
        cfg.enforce_touch = _bool_from_py(d[k_enforce_touch])
    if d.__contains__(k_spacing_present_cost):
        cfg.spacing_present_cost = _u32_from_py(d[k_spacing_present_cost])
    if d.__contains__(k_spacing_present_cap):
        cfg.spacing_present_cap = UInt16(_int_from_py(d[k_spacing_present_cap]))
    if d.__contains__(k_forbid_stacked_vias):
        cfg.forbid_stacked_vias = _bool_from_py(d[k_forbid_stacked_vias])
    if d.__contains__(k_route_power_last):
        cfg.route_power_last = _bool_from_py(d[k_route_power_last])
    if d.__contains__(k_seed_circle_keepouts):
        cfg.seed_circle_keepouts = _bool_from_py(d[k_seed_circle_keepouts])
    if d.__contains__(k_net_layer_allow):
        cfg.net_layer_allow = d[k_net_layer_allow]
    if d.__contains__(k_escape_enable):
        cfg.escape_enable = _bool_from_py(d[k_escape_enable])
    if d.__contains__(k_escape_margin):
        cfg.escape_margin = _int_from_py(d[k_escape_margin])
    if d.__contains__(k_escape_margin_step):
        cfg.escape_margin_step = _int_from_py(d[k_escape_margin_step])
    if d.__contains__(k_escape_margin_max):
        cfg.escape_margin_max = _int_from_py(d[k_escape_margin_max])
    if d.__contains__(k_escape_unique_exit):
        cfg.escape_unique_exit = _bool_from_py(d[k_escape_unique_exit])
    if d.__contains__(k_escape_commit_early):
        cfg.escape_commit_early = _bool_from_py(d[k_escape_commit_early])
    if d.__contains__(k_batch_fanout_enable):
        cfg.batch_fanout_enable = _bool_from_py(d[k_batch_fanout_enable])
    if d.__contains__(k_batch_fanout_max_candidates):
        cfg.batch_fanout_max_candidates = _int_from_py(d[k_batch_fanout_max_candidates])
    if d.__contains__(k_precommit_index_existing_vias):
        cfg.precommit_index_existing_vias = _bool_from_py(d[k_precommit_index_existing_vias])
    if d.__contains__(k_precommit_fast_index_enable):
        cfg.precommit_fast_index_enable = _bool_from_py(d[k_precommit_fast_index_enable])
    if d.__contains__(k_precommit_fast_index_cell_mm):
        cfg.precommit_fast_index_cell_mm = _f64_from_py(d[k_precommit_fast_index_cell_mm])
    if d.__contains__(k_shove_enable):
        cfg.shove_enable = _bool_from_py(d[k_shove_enable])
    if d.__contains__(k_shove_max_rips):
        cfg.shove_max_rips = _int_from_py(d[k_shove_max_rips])
    if d.__contains__(k_static_obstacle_keepouts):
        cfg.static_obstacle_keepouts = _bool_from_py(d[k_static_obstacle_keepouts])
    if d.__contains__(k_legalize_use_grid_keepouts):
        cfg.legalize_use_grid_keepouts = _bool_from_py(d[k_legalize_use_grid_keepouts])
    if d.__contains__(k_maze_fallback_enable):
        cfg.maze_fallback_enable = _bool_from_py(d[k_maze_fallback_enable])
    if d.__contains__(k_maze_samples):
        cfg.maze_samples = _int_from_py(d[k_maze_samples])
    if d.__contains__(k_maze_k_neigh):
        cfg.maze_k_neigh = _int_from_py(d[k_maze_k_neigh])
    if d.__contains__(k_maze_track_index_cell_mm):
        cfg.maze_track_index_cell_mm = _f64_from_py(d[k_maze_track_index_cell_mm])
    if d.__contains__(k_debug):
        cfg.debug = _bool_from_py(d[k_debug])
    return


fn _load_problem(problem_path: String) raises -> PythonObject:
    var pathlib = py.import_module("pathlib")
    var json = py.import_module("json")
    var txt = pathlib.Path(PythonObject(problem_path)).read_text()
    return json.loads(txt)

struct TracksVias:
    var tracks: PythonObject
    var vias: PythonObject

    fn __init__(out self, tracks: PythonObject, vias: PythonObject):
        self.tracks = tracks
        self.vias = vias


struct PrecommitDB:
    var tracks: PythonObject
    var vias: PythonObject
    var track_index_enabled: Bool
    var track_index: SpatialSegmentIndex

    fn __init__(
        out self,
        tracks: PythonObject,
        vias: PythonObject,
        track_index_enabled: Bool = False,
        track_index_cell_mm: Float64 = Float64(2.0),
    ):
        self.tracks = tracks
        self.vias = vias
        self.track_index_enabled = track_index_enabled
        self.track_index = SpatialSegmentIndex(
            origin_x=Float64(0.0),
            origin_y=Float64(0.0),
            cols=1,
            rows=1,
            cell_size=track_index_cell_mm,
        )


fn _build_track_index_from_track_db(
    track_db: PythonObject,
    *,
    origin_x_mm: Float64,
    origin_y_mm: Float64,
    board_w_mm: Float64,
    board_h_mm: Float64,
    cell_size_mm: Float64,
) raises -> SpatialSegmentIndex:
    var cell = cell_size_mm
    if cell <= Float64(0.0):
        cell = Float64(2.0)
    var bw = board_w_mm
    var bh = board_h_mm
    if bw <= Float64(0.0):
        bw = Float64(1.0)
    if bh <= Float64(0.0):
        bh = Float64(1.0)
    var cols = Int((bw / cell) + Float64(1.0))
    var rows = Int((bh / cell) + Float64(1.0))
    if cols < 1:
        cols = 1
    if rows < 1:
        rows = 1
    var idx = SpatialSegmentIndex(
        origin_x=origin_x_mm,
        origin_y=origin_y_mm,
        cols=cols,
        rows=rows,
        cell_size=cell,
    )
    for rec in track_db:
        var r_layer = Int(py=rec[PythonObject(Int(0))])
        var r_net = UInt32(Int(py=rec[PythonObject(Int(1))]))
        var r_w = Float64(py=rec[PythonObject(Int(2))])
        var r_sx = Float64(py=rec[PythonObject(Int(3))])
        var r_sy = Float64(py=rec[PythonObject(Int(4))])
        var r_ex = Float64(py=rec[PythonObject(Int(5))])
        var r_ey = Float64(py=rec[PythonObject(Int(6))])
        idx.add_segment(GeoSegment(Vec2(r_sx, r_sy), Vec2(r_ex, r_ey)), r_layer, r_net, r_w)
    return idx




fn _rebuild_precommit_db_inplace(
    mut db: PrecommitDB,
    tracks_by_spec: List[PythonObject],
    vias_by_spec: List[PythonObject],
    routed_state: List[Int],
    net_ids: List[UInt32],
    layers: List[String],
    clearance_mm: Float64,
    *,
    origin_x_mm: Float64,
    origin_y_mm: Float64,
    board_w_mm: Float64,
    board_h_mm: Float64,
    fast_index_enable: Bool,
    fast_index_cell_mm: Float64,
) raises:
    # Reuse the same Python list objects to reduce GC pressure on large boards.
    db.tracks.clear()
    db.vias.clear()
    var i = 0
    while i < len(net_ids):
        if routed_state[i] == 1:
            _index_commit_tracks(tracks_by_spec[i], net_ids[i], layers, db.tracks)
            _index_commit_vias(vias_by_spec[i], net_ids[i], layers, db.vias, clearance_mm)
        i += 1
    db.track_index_enabled = False


fn _path_to_tracks_and_vias(
    net_name: String,
    track_width_mm: Float64,
    via_diameter_mm: Float64,
    via_drill_mm: Float64,
    uvia_diameter_mm: Float64,
    uvia_drill_mm: Float64,
    layers: List[String],
    resolution_mm: Float64,
    origin_x_mm: Float64,
    origin_y_mm: Float64,
    width: Int,
    height: Int,
    path: List[Int],
    existing_vias: PythonObject,
    pad_stacks: PythonObject,
) raises -> TracksVias:
    var tracks = py.list()
    var vias = py.list()
    if len(path) < 2:
        return TracksVias(tracks, vias)

    var k_net = PythonObject(String("net"))
    var k_pos_mm = PythonObject(String("pos_mm"))
    var k_size_mm = PythonObject(String("size_mm"))
    var k_drill_mm = PythonObject(String("drill_mm"))
    var k_via_type = PythonObject(String("via_type"))
    var k_layers = PythonObject(String("layers"))
    var k_layer = PythonObject(String("layer"))
    var k_width_mm = PythonObject(String("width_mm"))
    var k_start_mm = PythonObject(String("start_mm"))
    var k_end_mm = PythonObject(String("end_mm"))

    var k_ev_net = PythonObject(String("net"))
    var k_ev_layers = PythonObject(String("layers"))
    var k_ev_center = PythonObject(String("center"))
    var k_ev_x = PythonObject(String("x"))
    var k_ev_y = PythonObject(String("y"))

    var k_ps_net = PythonObject(String("net"))
    var k_ps_layers = PythonObject(String("layers"))
    var k_ps_center = PythonObject(String("center"))
    var k_ps_x = PythonObject(String("x"))
    var k_ps_y = PythonObject(String("y"))

    var p0 = idx_to_coords(path[0], width, height)
    var prev_layer = p0.layer
    var prev_x = p0.x
    var prev_y = p0.y

    var run_active = False
    var run_dx = 0
    var run_dy = 0
    var run_layer = prev_layer
    var run_start_x = prev_x
    var run_start_y = prev_y

    var i = 1
    while i < len(path):
        var c = idx_to_coords(path[i], width, height)
        var cur_layer = c.layer
        var cur_x = c.x
        var cur_y = c.y

        if cur_x == prev_x and cur_y == prev_y and cur_layer != prev_layer:
            # Via chain: flush current track run then coalesce all consecutive layer changes.
            if run_active and (run_start_x != prev_x or run_start_y != prev_y):
                var sx = origin_x_mm + Float64(run_start_x) * resolution_mm
                var sy = origin_y_mm + Float64(run_start_y) * resolution_mm
                var ex = origin_x_mm + Float64(prev_x) * resolution_mm
                var ey = origin_y_mm + Float64(prev_y) * resolution_mm
                var t = py.dict()
                t[k_net] = PythonObject(net_name)
                t[k_layer] = PythonObject(layers[run_layer])
                t[k_width_mm] = PythonObject(track_width_mm)
                var start = py.list()
                start.append(PythonObject(sx))
                start.append(PythonObject(sy))
                t[k_start_mm] = start
                var end = py.list()
                end.append(PythonObject(ex))
                end.append(PythonObject(ey))
                t[k_end_mm] = end
                tracks.append(t)
            run_active = False

            var vx = prev_x
            var vy = prev_y
            var l0 = prev_layer
            var l1 = cur_layer
            var j = i + 1
            while j < len(path):
                var n = idx_to_coords(path[j], width, height)
                if n.x != vx or n.y != vy:
                    break
                l1 = n.layer
                j += 1

            var lo = l0 if l0 <= l1 else l1
            var hi = l1 if l0 <= l1 else l0
            var dl = abs_i(l1 - l0)
            var via_type = "through"
            var size = via_diameter_mm
            var drill = via_drill_mm
            if dl == 1:
                via_type = "micro"
                size = uvia_diameter_mm
                drill = uvia_drill_mm
            else:
                # If the via doesn't span the full stack, it must be blind/buried; a KiCad
                # "through" via always spans F.Cu-B.Cu regardless of the provided layer pair.
                if not (lo == 0 and hi == (len(layers) - 1)):
                    via_type = "blind"
            var has_existing = False
            for ev in existing_vias:
                if String(py=ev[k_ev_net]) != net_name:
                    continue
                var c = ev[k_ev_center]
                if Int(py=c[k_ev_x]) != vx or Int(py=c[k_ev_y]) != vy:
                    continue
                var ok_lo = False
                var ok_hi = False
                for li in ev[k_ev_layers]:
                    var lli = Int(py=li)
                    if lli == lo:
                        ok_lo = True
                    if lli == hi:
                        ok_hi = True
                    if ok_lo and ok_hi:
                        break
                if ok_lo and ok_hi:
                    has_existing = True
                    break
            var has_pth_stack = False
            if not has_existing:
                for ps in pad_stacks:
                    var c = ps[k_ps_center]
                    if Int(py=c[k_ps_x]) != vx or Int(py=c[k_ps_y]) != vy:
                        continue
                    var ok_lo = False
                    var ok_hi = False
                    for li in ps[k_ps_layers]:
                        var lli = Int(py=li)
                        if lli == lo:
                            ok_lo = True
                        if lli == hi:
                            ok_hi = True
                        if ok_lo and ok_hi:
                            break
                    if ok_lo and ok_hi:
                        has_pth_stack = True
                        break
            if not has_existing and not has_pth_stack:
                var v = py.dict()
                v[k_net] = PythonObject(net_name)
                var pos = py.list()
                pos.append(PythonObject(origin_x_mm + Float64(vx) * resolution_mm))
                pos.append(PythonObject(origin_y_mm + Float64(vy) * resolution_mm))
                v[k_pos_mm] = pos
                v[k_size_mm] = PythonObject(size)
                v[k_drill_mm] = PythonObject(drill)
                v[k_via_type] = PythonObject(String(via_type))
                var span = py.list()
                span.append(PythonObject(layers[lo]))
                span.append(PythonObject(layers[hi]))
                v[k_layers] = span
                vias.append(v)

            prev_layer = l1
            prev_x = vx
            prev_y = vy
            run_layer = prev_layer
            run_start_x = prev_x
            run_start_y = prev_y
            i = j
            continue

        var dx = cur_x - prev_x
        var dy = cur_y - prev_y
        var ndx = 0
        if dx > 0:
            ndx = 1
        elif dx < 0:
            ndx = -1
        var ndy = 0
        if dy > 0:
            ndy = 1
        elif dy < 0:
            ndy = -1

        if not run_active:
            run_active = True
            run_dx = ndx
            run_dy = ndy
            run_layer = prev_layer
            run_start_x = prev_x
            run_start_y = prev_y
        elif ndx != run_dx or ndy != run_dy or prev_layer != run_layer:
            if run_start_x != prev_x or run_start_y != prev_y:
                var sx = origin_x_mm + Float64(run_start_x) * resolution_mm
                var sy = origin_y_mm + Float64(run_start_y) * resolution_mm
                var ex = origin_x_mm + Float64(prev_x) * resolution_mm
                var ey = origin_y_mm + Float64(prev_y) * resolution_mm
                var t = py.dict()
                t[k_net] = PythonObject(net_name)
                t[k_layer] = PythonObject(layers[run_layer])
                t[k_width_mm] = PythonObject(track_width_mm)
                var start = py.list()
                start.append(PythonObject(sx))
                start.append(PythonObject(sy))
                t[k_start_mm] = start
                var end = py.list()
                end.append(PythonObject(ex))
                end.append(PythonObject(ey))
                t[k_end_mm] = end
                tracks.append(t)
            run_dx = ndx
            run_dy = ndy
            run_layer = prev_layer
            run_start_x = prev_x
            run_start_y = prev_y

        prev_layer = cur_layer
        prev_x = cur_x
        prev_y = cur_y
        i += 1

    if run_active and (run_start_x != prev_x or run_start_y != prev_y):
        var sx = origin_x_mm + Float64(run_start_x) * resolution_mm
        var sy = origin_y_mm + Float64(run_start_y) * resolution_mm
        var ex = origin_x_mm + Float64(prev_x) * resolution_mm
        var ey = origin_y_mm + Float64(prev_y) * resolution_mm
        var t = py.dict()
        t[k_net] = PythonObject(net_name)
        t[k_layer] = PythonObject(layers[run_layer])
        t[k_width_mm] = PythonObject(track_width_mm)
        var start = py.list()
        start.append(PythonObject(sx))
        start.append(PythonObject(sy))
        t[k_start_mm] = start
        var end = py.list()
        end.append(PythonObject(ex))
        end.append(PythonObject(ey))
        t[k_end_mm] = end
        tracks.append(t)
    return TracksVias(tracks, vias)


fn _tracks_violate_keepouts(
    tracks: PythonObject,
    keepout_circles: List[GeoCircle],
    keepout_circle_net: List[UInt32],
    keepout_polygons: List[List[Vec2]],
    keepout_poly_net: List[UInt32],
    keepout_circle_mask: List[UInt32],
    keepout_poly_mask: List[UInt32],
    layers: List[String],
    clearance_mm: Float64,
    net_id: UInt32,
) raises -> Bool:
    # Tracks are python dicts emitted by _path_to_tracks_and_vias.
    # Keepouts are hard obstacles; any intersection is a violation.
    if not tracks:
        return False
    var k_layer = PythonObject(String("layer"))
    var k_start_mm = PythonObject(String("start_mm"))
    var k_end_mm = PythonObject(String("end_mm"))
    var k_width_mm = PythonObject(String("width_mm"))
    for t in tracks:
        var layer_name = String(py=t[k_layer])
        var layer_idx = -1
        var li = 0
        while li < len(layers):
            if layers[li] == layer_name:
                layer_idx = li
                break
            li += 1
        var s = t[k_start_mm]
        var e = t[k_end_mm]
        var sx = Float64(py=s[PythonObject(Int(0))])
        var sy = Float64(py=s[PythonObject(Int(1))])
        var ex = Float64(py=e[PythonObject(Int(0))])
        var ey = Float64(py=e[PythonObject(Int(1))])
        var seg = GeoSegment(Vec2(sx, sy), Vec2(ex, ey))
        var w = Float64(py=t[k_width_mm])
        var inflate = (w / Float64(2.0)) + clearance_mm
        var i = 0
        while i < len(keepout_circles):
            if len(keepout_circle_net) == len(keepout_circles) and keepout_circle_net[i] == net_id:
                i += 1
                continue
            if layer_idx >= 0 and layer_idx < 32:
                if (keepout_circle_mask[i] & (UInt32(1) << UInt32(layer_idx))) == UInt32(0):
                    i += 1
                    continue
            if check_circle_segment_clearance(seg=seg, circle=keepout_circles[i], clearance=inflate):
                return True
            i += 1
        i = 0
        while i < len(keepout_polygons):
            if len(keepout_poly_net) == len(keepout_polygons) and keepout_poly_net[i] == net_id:
                i += 1
                continue
            if layer_idx >= 0 and layer_idx < 32:
                if (keepout_poly_mask[i] & (UInt32(1) << UInt32(layer_idx))) == UInt32(0):
                    i += 1
                    continue
            if check_polygon_segment_clearance(seg=seg, poly=keepout_polygons[i], clearance=inflate):
                return True
            i += 1
    return False


fn _tracks_first_conflict_net(
    tracks: PythonObject,
    net_id: UInt32,
    layers: List[String],
    track_db: PythonObject,
    via_db: PythonObject,
    clearance_mm: Float64,
    *,
    track_index_enabled: Bool = False,
    track_index: SpatialSegmentIndex = SpatialSegmentIndex(
        origin_x=Float64(0.0),
        origin_y=Float64(0.0),
        cols=1,
        rows=1,
        cell_size=Float64(2.0),
    ),
) raises -> UInt32:
    if not tracks:
        return UInt32(0)
    var k_layer = PythonObject(String("layer"))
    var k_width_mm = PythonObject(String("width_mm"))
    var k_start_mm = PythonObject(String("start_mm"))
    var k_end_mm = PythonObject(String("end_mm"))

    for t in tracks:
        var layer_name = String(py=t[k_layer])
        var layer_idx = -1
        var li = 0
        while li < len(layers):
            if layers[li] == layer_name:
                layer_idx = li
                break
            li += 1
        if layer_idx < 0:
            continue

        var w = Float64(py=t[k_width_mm])
        var s = t[k_start_mm]
        var e = t[k_end_mm]
        var sx = Float64(py=s[PythonObject(Int(0))])
        var sy = Float64(py=s[PythonObject(Int(1))])
        var ex = Float64(py=e[PythonObject(Int(0))])
        var ey = Float64(py=e[PythonObject(Int(1))])
        var seg = GeoSegment(Vec2(sx, sy), Vec2(ex, ey))

        var inflate0 = (w / Float64(2.0)) + clearance_mm
        var bb = seg.aabb()
        var minx = bb.min_x - inflate0
        var miny = bb.min_y - inflate0
        var maxx = bb.max_x + inflate0
        var maxy = bb.max_y + inflate0

        if track_index_enabled:
            var cand = track_index.query_aabb(AABB(minx, miny, maxx, maxy))
            for sid in cand:
                if sid < 0 or sid >= len(track_index.segs):
                    continue
                if track_index.layer_ids[sid] != layer_idx:
                    continue
                var r_net = track_index.net_ids[sid]
                if r_net == net_id:
                    continue
                var r_w = track_index.widths_mm[sid]
                var other = track_index.segs[sid].copy()
                var inflate = inflate0 + (r_w / Float64(2.0))
                var d2 = dist_segment_segment2(seg.a, seg.b, other.a, other.b)
                if d2 <= inflate * inflate:
                    return r_net
        else:
            for rec in track_db:
                var r_layer = Int(py=rec[PythonObject(Int(0))])
                if r_layer != layer_idx:
                    continue
                var r_net = UInt32(Int(py=rec[PythonObject(Int(1))]))
                if r_net == net_id:
                    continue
                var r_w = Float64(py=rec[PythonObject(Int(2))])
                var r_sx = Float64(py=rec[PythonObject(Int(3))])
                var r_sy = Float64(py=rec[PythonObject(Int(4))])
                var r_ex = Float64(py=rec[PythonObject(Int(5))])
                var r_ey = Float64(py=rec[PythonObject(Int(6))])
                var r_minx = Float64(py=rec[PythonObject(Int(7))])
                var r_miny = Float64(py=rec[PythonObject(Int(8))])
                var r_maxx = Float64(py=rec[PythonObject(Int(9))])
                var r_maxy = Float64(py=rec[PythonObject(Int(10))])
                # Fast BB reject.
                if maxx < r_minx or minx > r_maxx or maxy < r_miny or miny > r_maxy:
                    continue
                var other = GeoSegment(Vec2(r_sx, r_sy), Vec2(r_ex, r_ey))
                var inflate = inflate0 + (r_w / Float64(2.0))
                var d2 = dist_segment_segment2(seg.a, seg.b, other.a, other.b)
                if d2 <= inflate * inflate:
                    return r_net

        # Track vs existing vias (other nets).
        for vrec in via_db:
            var v_layer = Int(py=vrec[PythonObject(Int(0))])
            if v_layer != layer_idx:
                continue
            var v_net = UInt32(Int(py=vrec[PythonObject(Int(1))]))
            if v_net == net_id:
                continue
            var vr = Float64(py=vrec[PythonObject(Int(2))])
            var vcx = Float64(py=vrec[PythonObject(Int(3))])
            var vcy = Float64(py=vrec[PythonObject(Int(4))])
            var v_minx = Float64(py=vrec[PythonObject(Int(5))])
            var v_miny = Float64(py=vrec[PythonObject(Int(6))])
            var v_maxx = Float64(py=vrec[PythonObject(Int(7))])
            var v_maxy = Float64(py=vrec[PythonObject(Int(8))])
            if maxx < v_minx or minx > v_maxx or maxy < v_miny or miny > v_maxy:
                continue
            var circle = GeoCircle(Vec2(vcx, vcy), vr)
            var inflate = inflate0 + vr
            if check_circle_segment_clearance(seg=seg, circle=circle, clearance=inflate):
                return v_net
    # NOTE: committing to index happens in caller after passing checks.
    return UInt32(0)


fn _tracks_violate_shorts_or_clearance(
    tracks: PythonObject,
    net_id: UInt32,
    layers: List[String],
    track_db: PythonObject,
    via_db: PythonObject,
    clearance_mm: Float64,
) raises -> Bool:
    return (
        _tracks_first_conflict_net(
            tracks,
            net_id,
            layers,
            track_db,
            via_db,
            clearance_mm,
        )
        != UInt32(0)
    )


fn _index_commit_tracks(
    tracks: PythonObject,
    net_id: UInt32,
    layers: List[String],
    track_db: PythonObject,
) raises:
    if not tracks:
        return
    var k_layer = PythonObject(String("layer"))
    var k_width_mm = PythonObject(String("width_mm"))
    var k_start_mm = PythonObject(String("start_mm"))
    var k_end_mm = PythonObject(String("end_mm"))
    for t in tracks:
        var layer_name = String(py=t[k_layer])
        var layer_idx = -1
        var li = 0
        while li < len(layers):
            if layers[li] == layer_name:
                layer_idx = li
                break
            li += 1
        if layer_idx < 0:
            continue
        var s = t[k_start_mm]
        var e = t[k_end_mm]
        var sx = Float64(py=s[PythonObject(Int(0))])
        var sy = Float64(py=s[PythonObject(Int(1))])
        var ex = Float64(py=e[PythonObject(Int(0))])
        var ey = Float64(py=e[PythonObject(Int(1))])
        var w = Float64(py=t[k_width_mm])
        var minx = sx if sx < ex else ex
        var maxx = sx if sx > ex else ex
        var miny = sy if sy < ey else ey
        var maxy = sy if sy > ey else ey
        var rec = py.list()
        rec.append(PythonObject(Int(layer_idx)))
        rec.append(PythonObject(Int(net_id)))
        rec.append(PythonObject(w))
        rec.append(PythonObject(sx))
        rec.append(PythonObject(sy))
        rec.append(PythonObject(ex))
        rec.append(PythonObject(ey))
        rec.append(PythonObject(minx))
        rec.append(PythonObject(miny))
        rec.append(PythonObject(maxx))
        rec.append(PythonObject(maxy))
        track_db.append(rec)


fn _index_commit_tracks_spatial(
    tracks: PythonObject,
    net_id: UInt32,
    layers: List[String],
    mut track_index: SpatialSegmentIndex,
) raises:
    if not tracks:
        return
    var k_layer = PythonObject(String("layer"))
    var k_width_mm = PythonObject(String("width_mm"))
    var k_start_mm = PythonObject(String("start_mm"))
    var k_end_mm = PythonObject(String("end_mm"))
    for t in tracks:
        var layer_name = String(py=t[k_layer])
        var layer_idx = -1
        var li = 0
        while li < len(layers):
            if layers[li] == layer_name:
                layer_idx = li
                break
            li += 1
        if layer_idx < 0:
            continue
        var s = t[k_start_mm]
        var e = t[k_end_mm]
        var sx = Float64(py=s[PythonObject(Int(0))])
        var sy = Float64(py=s[PythonObject(Int(1))])
        var ex = Float64(py=e[PythonObject(Int(0))])
        var ey = Float64(py=e[PythonObject(Int(1))])
        var w = Float64(py=t[k_width_mm])
        track_index.add_segment(GeoSegment(Vec2(sx, sy), Vec2(ex, ey)), layer_idx, net_id, w)


fn _vias_first_conflict_net(
    vias: PythonObject,
    net_id: UInt32,
    layers: List[String],
    track_db: PythonObject,
    via_db: PythonObject,
    clearance_mm: Float64,
) raises -> UInt32:
    if not vias:
        return UInt32(0)
    var k_pos_mm = PythonObject(String("pos_mm"))
    var k_size_mm = PythonObject(String("size_mm"))
    var k_drill_mm = PythonObject(String("drill_mm"))
    var k_layers = PythonObject(String("layers"))
    for v in vias:
        var pos = v[k_pos_mm]
        var cx = Float64(py=pos[PythonObject(Int(0))])
        var cy = Float64(py=pos[PythonObject(Int(1))])
        var r = Float64(py=v[k_size_mm]) / Float64(2.0)
        var drill_r = Float64(py=v[k_drill_mm]) / Float64(2.0)
        var span = v[k_layers]
        var lo_name = String(py=span[PythonObject(Int(0))])
        var hi_name = String(py=span[PythonObject(Int(1))])
        var lo = -1
        var hi = -1
        var li = 0
        while li < len(layers):
            if layers[li] == lo_name:
                lo = li
            if layers[li] == hi_name:
                hi = li
            li += 1
        if lo < 0 or hi < 0:
            continue
        if lo > hi:
            var t = lo
            lo = hi
            hi = t
        var layer_idx = lo
        while layer_idx <= hi:
            var minx = cx - (r + clearance_mm)
            var miny = cy - (r + clearance_mm)
            var maxx = cx + (r + clearance_mm)
            var maxy = cy + (r + clearance_mm)

            # Via vs existing tracks.
            for rec in track_db:
                var r_layer = Int(py=rec[PythonObject(Int(0))])
                if r_layer != layer_idx:
                    continue
                var r_net = UInt32(Int(py=rec[PythonObject(Int(1))]))
                if r_net == net_id:
                    continue
                var r_w = Float64(py=rec[PythonObject(Int(2))])
                var r_sx = Float64(py=rec[PythonObject(Int(3))])
                var r_sy = Float64(py=rec[PythonObject(Int(4))])
                var r_ex = Float64(py=rec[PythonObject(Int(5))])
                var r_ey = Float64(py=rec[PythonObject(Int(6))])
                var r_minx = Float64(py=rec[PythonObject(Int(7))])
                var r_miny = Float64(py=rec[PythonObject(Int(8))])
                var r_maxx = Float64(py=rec[PythonObject(Int(9))])
                var r_maxy = Float64(py=rec[PythonObject(Int(10))])
                if maxx < r_minx or minx > r_maxx or maxy < r_miny or miny > r_maxy:
                    continue
                var seg = GeoSegment(Vec2(r_sx, r_sy), Vec2(r_ex, r_ey))
                var circle = GeoCircle(Vec2(cx, cy), r)
                var inflate = (r_w / Float64(2.0)) + clearance_mm
                if check_circle_segment_clearance(seg=seg, circle=circle, clearance=inflate):
                    return r_net
                # Hole (drill) vs copper track: KiCad `hole_clearance`.
                var hole_circle = GeoCircle(Vec2(cx, cy), drill_r)
                if check_circle_segment_clearance(seg=seg, circle=hole_circle, clearance=inflate):
                    return r_net

            # Via vs existing vias.
            for vrec in via_db:
                var v_layer = Int(py=vrec[PythonObject(Int(0))])
                if v_layer != layer_idx:
                    continue
                var v_net = UInt32(Int(py=vrec[PythonObject(Int(1))]))
                if v_net == net_id:
                    continue
                var vr = Float64(py=vrec[PythonObject(Int(2))])
                var vcx = Float64(py=vrec[PythonObject(Int(3))])
                var vcy = Float64(py=vrec[PythonObject(Int(4))])
                var v_drill_r = Float64(py=vrec[PythonObject(Int(5))])
                var v_minx = Float64(py=vrec[PythonObject(Int(6))])
                var v_miny = Float64(py=vrec[PythonObject(Int(7))])
                var v_maxx = Float64(py=vrec[PythonObject(Int(8))])
                var v_maxy = Float64(py=vrec[PythonObject(Int(9))])
                if maxx < v_minx or minx > v_maxx or maxy < v_miny or miny > v_maxy:
                    continue
                var c0 = GeoCircle(Vec2(cx, cy), r + clearance_mm)
                var c1 = GeoCircle(Vec2(vcx, vcy), vr + clearance_mm)
                if circle_intersects_circle(c0, c1):
                    return v_net
                # Hole to other-net copper annulus: KiCad `hole_clearance`.
                var hc0 = GeoCircle(Vec2(cx, cy), drill_r + clearance_mm)
                var hc1 = GeoCircle(Vec2(vcx, vcy), vr + clearance_mm)
                if circle_intersects_circle(hc0, hc1):
                    return v_net
                # Hole-to-hole (drill) clearance: model drills as circles and ensure they do not overlap.
                var h0 = GeoCircle(Vec2(cx, cy), drill_r + clearance_mm)
                var h1 = GeoCircle(Vec2(vcx, vcy), v_drill_r + clearance_mm)
                if circle_intersects_circle(h0, h1):
                    return v_net

            layer_idx += 1
    return UInt32(0)


fn _vias_violate_shorts_or_clearance(
    vias: PythonObject,
    net_id: UInt32,
    layers: List[String],
    track_db: PythonObject,
    via_db: PythonObject,
    clearance_mm: Float64,
) raises -> Bool:
    return _vias_first_conflict_net(vias, net_id, layers, track_db, via_db, clearance_mm) != UInt32(0)


fn _index_commit_vias(
    vias: PythonObject,
    net_id: UInt32,
    layers: List[String],
    via_db: PythonObject,
    clearance_mm: Float64,
) raises:
    if not vias:
        return
    var k_pos_mm = PythonObject(String("pos_mm"))
    var k_size_mm = PythonObject(String("size_mm"))
    var k_drill_mm = PythonObject(String("drill_mm"))
    var k_layers = PythonObject(String("layers"))
    for v in vias:
        var pos = v[k_pos_mm]
        var cx = Float64(py=pos[PythonObject(Int(0))])
        var cy = Float64(py=pos[PythonObject(Int(1))])
        var r = Float64(py=v[k_size_mm]) / Float64(2.0)
        var drill_r = Float64(py=v[k_drill_mm]) / Float64(2.0)
        var span = v[k_layers]
        var lo_name = String(py=span[PythonObject(Int(0))])
        var hi_name = String(py=span[PythonObject(Int(1))])
        var lo = -1
        var hi = -1
        var li = 0
        while li < len(layers):
            if layers[li] == lo_name:
                lo = li
            if layers[li] == hi_name:
                hi = li
            li += 1
        if lo < 0 or hi < 0:
            continue
        if lo > hi:
            var t = lo
            lo = hi
            hi = t
        var layer_idx = lo
        while layer_idx <= hi:
            var minx = cx - (r + clearance_mm)
            var miny = cy - (r + clearance_mm)
            var maxx = cx + (r + clearance_mm)
            var maxy = cy + (r + clearance_mm)
            var rec = py.list()
            rec.append(PythonObject(Int(layer_idx)))
            rec.append(PythonObject(Int(net_id)))
            rec.append(PythonObject(r))
            rec.append(PythonObject(cx))
            rec.append(PythonObject(cy))
            rec.append(PythonObject(drill_r))
            rec.append(PythonObject(minx))
            rec.append(PythonObject(miny))
            rec.append(PythonObject(maxx))
            rec.append(PythonObject(maxy))
            via_db.append(rec)
            layer_idx += 1



fn route_problem(problem_path: String, routes_path: String, cfg_path: String) raises:
    var cfg = RouteConfig()
    _apply_config(cfg_path, cfg)
    if cfg.debug:
        print("cfg maze_fallback_enable", cfg.maze_fallback_enable, "maze_samples", cfg.maze_samples, "maze_k", cfg.maze_k_neigh)
    var d = _load_problem(problem_path)
    var builtins = py.import_module("builtins")

    # Optional origin (board bbox min) for mapping compact grid coordinates back to
    # KiCad board coordinates. Older problem files omit this and implicitly use 0.
    var origin_x_mm = Float64(0.0)
    var origin_y_mm = Float64(0.0)
    var k_origin_mm = PythonObject(String("origin_mm"))
    if d.__contains__(k_origin_mm):
        var o = d[k_origin_mm]
        origin_x_mm = _f64_from_py(_get(o, "x"))
        origin_y_mm = _f64_from_py(_get(o, "y"))

    # Optional copper-to-edge clearance; used to block a safety band near the board
    # outline so the router doesn't "escape" outside the PCB.
    var edge_clearance_mm = Float64(0.0)
    var k_edge_clearance_mm = PythonObject(String("edge_clearance_mm"))
    if d.__contains__(k_edge_clearance_mm):
        edge_clearance_mm = _f64_from_py(d[k_edge_clearance_mm])

    var resolution_mm = _f64_from_py(_get(d, "resolution_mm"))

    # Optional net defaults (older/minimal fixtures may omit these).
    var defaults = py.dict()
    var k_net_defaults = PythonObject(String("net_defaults"))
    if d.__contains__(k_net_defaults):
        defaults = d[k_net_defaults]
    else:
        # Derive from first net if present, otherwise use conservative small defaults.
        var tw = Float64(0.2)
        var cl = Float64(0.2)
        var k_nets = PythonObject(String("nets"))
        if d.__contains__(k_nets):
            var nets_tmp = d[k_nets]
            if nets_tmp and Int(py=nets_tmp.__len__()) > 0:
                var n0 = nets_tmp[PythonObject(Int(0))]
                tw = _f64_from_py(_get(n0, "track_width_mm"))
                cl = tw
        defaults[PythonObject(String("track_width_mm"))] = PythonObject(tw)
        defaults[PythonObject(String("clearance_mm"))] = PythonObject(cl)
        defaults[PythonObject(String("via_diameter_mm"))] = PythonObject(Float64(0.6))
        defaults[PythonObject(String("via_drill_mm"))] = PythonObject(Float64(0.3))
        defaults[PythonObject(String("uvia_diameter_mm"))] = PythonObject(Float64(0.4))
        defaults[PythonObject(String("uvia_drill_mm"))] = PythonObject(Float64(0.2))

    var clearance_mm = _f64_from_py(_get(defaults, "clearance_mm"))
    var layers = List[String]()
    for s in _get(d, "layers"):
        layers.append(String(py=s))

    var width = _int_from_py(_get(d, "width"))
    var height = _int_from_py(_get(d, "height"))
    var g = Grid(len(layers), width, height)
    var ws = AStarWorkspace(g.layers * g.width * g.height)

    # Geometry keepouts for optional precommit DRC (in mm coordinates).
    var keepout_circles = List[GeoCircle]()
    var keepout_circle_mask = List[UInt32]()
    var keepout_polygons = List[List[Vec2]]()
    var keepout_poly_mask = List[UInt32]()
    var keepout_circle_net = List[UInt32]()
    var keepout_poly_net = List[UInt32]()

    # Geometry obstacles for maze/PRM fallback routing (always collected).
    var maze_circles = List[MazeObstacleCircle]()
    var maze_polys = List[MazeObstaclePoly]()

    # Geometry track/via DB for optional precommit shorts/clearance checking.
    # NOTE: Mojo's List[T] requires Copyable elements; a rich index struct isn't
    # storable there yet, so we keep Python lists of records.
    #
    # Track record schema:
    # [layer_idx:int, net_id:int, width_mm:float, sx,sy,ex,ey,minx,miny,maxx,maxy]
    # Via record schema (one record per layer the via spans):
    # [layer_idx:int, net_id:int, r_mm:float, cx,cy, drill_r_mm:float, minx,miny,maxx,maxy]
    var pre_db = PrecommitDB(
        py.list(),
        py.list(),
        cfg.precommit_fast_index_enable,
        cfg.precommit_fast_index_cell_mm,
    )

    # Parse nets into packed arrays (faster + allows ordering/rip-up).
    var nets_py = _get(d, "nets")
    var net_names = List[String]()
    var net_ids = List[UInt32]()
    var start_idxs = List[Int]()
    var goal_idxs = List[Int]()
    var track_width_mm = List[Float64]()
    var via_diameter_mm = List[Float64]()
    var via_drill_mm = List[Float64]()
    var uvia_diameter_mm = List[Float64]()
    var uvia_drill_mm = List[Float64]()

    for net in nets_py:
        net_names.append(String(py=_get(net, "net")))
        net_ids.append(_u32_from_py(_get(net, "net_id")))
        var sp = _get(net, "start")
        var gp = _get(net, "goal")
        start_idxs.append(
            g.idx(_int_from_py(_get(sp, "layer")), _int_from_py(_get(sp, "x")), _int_from_py(_get(sp, "y")))
        )
        goal_idxs.append(
            g.idx(_int_from_py(_get(gp, "layer")), _int_from_py(_get(gp, "x")), _int_from_py(_get(gp, "y")))
        )
        track_width_mm.append(_f64_from_py(_get(net, "track_width_mm")))
        via_diameter_mm.append(_f64_from_py(_get(net, "via_diameter_mm")))
        via_drill_mm.append(_f64_from_py(_get(net, "via_drill_mm")))
        uvia_diameter_mm.append(_f64_from_py(_get(net, "uvia_diameter_mm")))
        uvia_drill_mm.append(_f64_from_py(_get(net, "uvia_drill_mm")))

    # Extra keepout for "<no net>" copper pads: these are true copper and KiCad DRC
    # treats them as obstacles for every net. Using only the pad geometry (without
    # any clearance margin) allows the router to "graze" them and create shorts.
    # Extra inflation for "<no net>" pads, in grid cells. The extractor is expected
    # to approximate pad geometry (including elongated pads) well enough that this
    # can remain zero for most boards; adjust only if DRC shows persistent shorts.
    var nonet_extra_cells = 1

    # Stamp circle obstacles into the base occupancy grid.
    for c in _get(d, "circles"):
        var net_id = _u32_from_py(_get(c, "net_id"))
        # Pads with no net are emitted with net_id=0 by the extractor; treat them
        # as unconditional obstacles.
        var r = _int_from_py(_get(c, "r"))
        if net_id == UInt32(0):
            net_id = UInt32(0xFFFF_FFFF)
            r = r + nonet_extra_cells
        var center = _get(c, "center")
        var x = _int_from_py(_get(center, "x"))
        var y = _int_from_py(_get(center, "y"))
        for l in _get(c, "layers"):
            g.stamp_circle_base(_int_from_py(l), x, y, r, net_id)
        # Geometry obstacle/keepout (net_id=0 means unconditional in our schema).
        var cx_mm = origin_x_mm + Float64(x) * resolution_mm
        var cy_mm = origin_y_mm + Float64(y) * resolution_mm
        var cr_mm = Float64(r) * resolution_mm
        var mask = UInt32(0)
        for l in _get(c, "layers"):
            var li = _int_from_py(l)
            if li >= 0 and li < 32:
                mask = mask | (UInt32(1) << UInt32(li))
        maze_circles.append(MazeObstacleCircle(GeoCircle(Vec2(cx_mm, cy_mm), cr_mm), mask, net_id))
        if cfg.precommit_drc_enable:
            keepout_circles.append(GeoCircle(Vec2(cx_mm, cy_mm), cr_mm))
            keepout_circle_net.append(net_id)
            keepout_circle_mask.append(mask)

    # Stamp polygon obstacles into the base occupancy grid (keepouts).
    var k_polygons = PythonObject(String("polygons"))
    if d.__contains__(k_polygons):
        for p in _get(d, "polygons"):
            var net_id = _u32_from_py(_get(p, "net_id"))
            if net_id == UInt32(0):
                net_id = UInt32(0xFFFF_FFFF)
            var pts_x = List[Int]()
            var pts_y = List[Int]()
            for pt in _get(p, "points"):
                pts_x.append(_int_from_py(_get(pt, "x")))
                pts_y.append(_int_from_py(_get(pt, "y")))
            for l in _get(p, "layers"):
                _stamp_polygon_base(g, _int_from_py(l), pts_x, pts_y, net_id)
            var poly = List[Vec2]()
            var origin_x = origin_x_mm
            var origin_y = origin_y_mm
            var i = 0
            while i < len(pts_x):
                poly.append(Vec2(origin_x + Float64(pts_x[i]) * resolution_mm, origin_y + Float64(pts_y[i]) * resolution_mm))
                i += 1
            var mask = UInt32(0)
            for l in _get(p, "layers"):
                var li = _int_from_py(l)
                if li >= 0 and li < 32:
                    mask = mask | (UInt32(1) << UInt32(li))
            maze_polys.append(MazeObstaclePoly(poly.copy(), mask, net_id))
            if cfg.precommit_drc_enable:
                keepout_polygons.append(poly^)
                keepout_poly_net.append(net_id)
                keepout_poly_mask.append(mask)

    # Build global keepout offsets (Rust-like).
    var clearance_eff = clearance_mm * cfg.keepout_clearance_scale
    var track_w_mm = _f64_from_py(_get(defaults, "track_width_mm"))
    var via_d_mm = _f64_from_py(_get(defaults, "via_diameter_mm"))
    var uvia_d_mm = _f64_from_py(_get(defaults, "uvia_diameter_mm"))
    var via_drill_default_mm = _f64_from_py(_get(defaults, "via_drill_mm"))
    var uvia_drill_default_mm = _f64_from_py(_get(defaults, "uvia_drill_mm"))
    var clearance_default_mm = _f64_from_py(_get(defaults, "clearance_mm"))
    # For DRC parity, use the worst-case via diameter when computing generic keepouts.
    # Some boards use large through/buried vias vs tiny microvias; under-approximating
    # via geometry leads to hole-to-hole and pad/via clearance DRC failures.
    var via_d_eff_mm = via_d_mm
    if uvia_d_mm > via_d_eff_mm:
        via_d_eff_mm = uvia_d_mm

    # Block a border band to satisfy KiCad's copper-edge clearance rule. We include
    # half the worst-case via diameter to conservatively ensure both tracks and vias
    # meet edge clearance.
    if edge_clearance_mm > 0.0:
        var edge_band_mm = edge_clearance_mm + (via_d_eff_mm / 2.0) + cfg.keepout_safety_mm
        var edge_cells = _ceil_div(edge_band_mm, resolution_mm)
        if edge_cells > 0:
            var li = 0
            while li < len(layers):
                var y = 0
                while y < edge_cells and y < height:
                    var x = 0
                    while x < width:
                        g.base_set(g.idx(li, x, y), g.blocked_value)
                        g.base_set(g.idx(li, x, (height - 1) - y), g.blocked_value)
                        x += 1
                    y += 1
                var xb = 0
                while xb < edge_cells and xb < width:
                    var yy = 0
                    while yy < height:
                        g.base_set(g.idx(li, xb, yy), g.blocked_value)
                        g.base_set(g.idx(li, (width - 1) - xb, yy), g.blocked_value)
                        yy += 1
                    xb += 1
                li += 1

    var track_keepout_mm = track_w_mm + clearance_eff + cfg.keepout_safety_mm
    var via_keepout_mm = (via_d_eff_mm / 2.0) + clearance_eff + (track_w_mm / 2.0) + cfg.keepout_safety_mm
    if cfg.keepout_track_cells > 0:
        track_keepout_mm = Float64(cfg.keepout_track_cells) * resolution_mm
    if cfg.keepout_via_cells > 0:
        via_keepout_mm = Float64(cfg.keepout_via_cells) * resolution_mm

    var spacing = SpacingBundle()
    spacing.clear.track_vs_track = build_offsets_for_min_dist_mm(track_keepout_mm, resolution_mm)
    spacing.clear.track_vs_via = build_offsets_for_min_dist_mm(via_keepout_mm, resolution_mm)
    spacing.clear.via_vs_track = build_offsets_for_min_dist_mm(via_keepout_mm, resolution_mm)
    spacing.clear.via_vs_via = build_offsets_for_min_dist_mm(
        via_d_eff_mm + clearance_eff + cfg.keepout_safety_mm,
        resolution_mm,
    )
    if cfg.enforce_touch:
        spacing.touch.track_vs_via = build_offsets_for_min_dist_mm(
            (via_d_eff_mm / 2.0) + (track_w_mm / 2.0),
            resolution_mm,
        )
        spacing.touch.via_vs_track = spacing.touch.track_vs_via.copy()
        spacing.touch.via_vs_via = build_offsets_for_min_dist_mm(
            via_d_eff_mm,
            resolution_mm,
        )

    # Optionally seed circles as fixed copper in the dynamic grid so spacing checks
    # treat pads and no-net copper as hard keepouts (important for KiCad DRC parity).
    if cfg.seed_circle_keepouts:
        var k_src = PythonObject(String("src"))
        for c in _get(d, "circles"):
            var net_id = _u32_from_py(_get(c, "net_id"))
            var r = _int_from_py(_get(c, "r"))
            # Seeding every circle is prohibitively expensive once the board already has
            # many routed tracks (track sampling generates thousands of circles). For
            # iterative routing, we only need to seed pad/no-net copper as "fixed"
            # keepouts; existing routed tracks are already enforced by commit_path and
            # (optionally) by the precommit DB.
            var src = String("pad")
            if c.__contains__(k_src):
                src = String(py=c[k_src])
            if src != String("pad") and net_id != UInt32(0):
                continue
            if net_id == UInt32(0):
                net_id = UInt32(0xFFFF_FFFF)
                r = r + nonet_extra_cells
            var center = _get(c, "center")
            var cx = _int_from_py(_get(center, "x"))
            var cy = _int_from_py(_get(center, "y"))
            if r <= 0:
                continue
            var r2 = r * r
            var x0 = max(cx - r, 0)
            var x1 = min(cx + r, width - 1)
            var y0 = max(cy - r, 0)
            var y1 = min(cy + r, height - 1)
            for l in _get(c, "layers"):
                var li = _int_from_py(l)
                if li < 0 or li >= len(layers):
                    continue
                var track_idxs = List[Int]()
                var yy = y0
                while yy <= y1:
                    var dy = yy - cy
                    var dy2 = dy * dy
                    var xx = x0
                    while xx <= x1:
                        var dx = xx - cx
                        if dx * dx + dy2 <= r2:
                            track_idxs.append(g.idx(li, xx, yy))
                        xx += 1
                    yy += 1
                g.commit_indices(net_id, track_idxs, List[Int](), cfg.enforce_spacing, spacing)

    # Pre-existing vias are treated as fixed copper and participate in spacing checks.
    var existing_vias_py = py.list()
    var k_existing_vias = PythonObject(String("existing_vias"))
    if d.__contains__(k_existing_vias):
        existing_vias_py = d[k_existing_vias]
    # Through-hole pad stacks (vertical connectivity) are used to suppress generating
    # microvias on top of drilled pads (KiCad hole-to-hole DRC).
    var pad_stacks_py = py.list()
    var k_pad_stacks = PythonObject(String("pad_stacks"))
    if d.__contains__(k_pad_stacks):
        pad_stacks_py = d[k_pad_stacks]
    if existing_vias_py:
        for v in existing_vias_py:
            var net_id = _u32_from_py(_get(v, "net_id"))
            var center = _get(v, "center")
            var x = _int_from_py(_get(center, "x"))
            var y = _int_from_py(_get(center, "y"))
            var via_idxs = List[Int]()
            for l in _get(v, "layers"):
                var li = _int_from_py(l)
                if g.in_bounds(li, x, y):
                    via_idxs.append(g.idx(li, x, y))
            g.commit_indices(net_id, List[Int](), via_idxs, cfg.enforce_spacing, spacing)

    # Include pre-existing vias in the shorts/clearance DB so we don't route new
    # vias/tracks that violate hole clearance against already-present drill holes.
    if cfg.precommit_shorts_enable and cfg.precommit_index_existing_vias and existing_vias_py:
        var k_center = PythonObject(String("center"))
        var k_x = PythonObject(String("x"))
        var k_y = PythonObject(String("y"))
        var k_layers = PythonObject(String("layers"))
        var k_size_mm = PythonObject(String("size_mm"))
        for v in existing_vias_py:
            var net_id = _u32_from_py(_get(v, "net_id"))
            var center = v[k_center]
            var x = Int(py=center[k_x])
            var y = Int(py=center[k_y])
            var span = v[k_layers]
            var lo = 1_000_000
            var hi = -1
            for l in span:
                var li = Int(py=l)
                if li < lo:
                    lo = li
                if li > hi:
                    hi = li
            if lo < 0:
                lo = 0
            if hi >= len(layers):
                hi = len(layers) - 1
            var cx = origin_x_mm + Float64(x) * resolution_mm
            var cy = origin_y_mm + Float64(y) * resolution_mm
            var r = Float64(py=v[k_size_mm]) / Float64(2.0)
            var drill_mm = uvia_drill_default_mm if _via_is_micro(span) else via_drill_default_mm
            if drill_mm <= 0.0:
                drill_mm = r
            var drill_r = drill_mm / Float64(2.0)
            var layer_idx = lo
            while layer_idx <= hi:
                var minx = cx - (r + clearance_default_mm)
                var miny = cy - (r + clearance_default_mm)
                var maxx = cx + (r + clearance_default_mm)
                var maxy = cy + (r + clearance_default_mm)
                var rec = py.list()
                rec.append(PythonObject(Int(layer_idx)))
                rec.append(PythonObject(Int(net_id)))
                rec.append(PythonObject(r))
                rec.append(PythonObject(cx))
                rec.append(PythonObject(cy))
                rec.append(PythonObject(drill_r))
                rec.append(PythonObject(minx))
                rec.append(PythonObject(miny))
                rec.append(PythonObject(maxx))
                rec.append(PythonObject(maxy))
                pre_db.vias.append(rec)
                layer_idx += 1

    # Maps for preventing stacked vias: if a coordinate has an existing via for a net,
    # only allow layer transitions that match an existing via segment.
    var existing_via_any = List[UInt32](length=width * height, fill=UInt32(0))
    var via_seg_len = 0
    if len(layers) > 1:
        via_seg_len = (len(layers) - 1) * width * height
    var existing_via_seg = List[UInt32](length=via_seg_len, fill=UInt32(0))
    if existing_vias_py:
        for v in existing_vias_py:
            var net_id = _u32_from_py(_get(v, "net_id"))
            var center = _get(v, "center")
            var x = _int_from_py(_get(center, "x"))
            var y = _int_from_py(_get(center, "y"))
            if x < 0 or y < 0 or x >= width or y >= height:
                continue
            var xy = y * width + x
            var cur = existing_via_any[xy]
            if cur == UInt32(0) or cur == net_id:
                existing_via_any[xy] = net_id
            else:
                existing_via_any[xy] = UInt32(0xFFFF_FFFF)
            var lo = 1_000_000
            var hi = -1
            for l in _get(v, "layers"):
                var li = _int_from_py(l)
                if li < lo:
                    lo = li
                if li > hi:
                    hi = li
            if lo < 0:
                lo = 0
            if hi >= len(layers):
                hi = len(layers) - 1
            var b = lo
            while b < hi:
                var bi = b * width * height + xy
                if bi >= 0 and bi < len(existing_via_seg):
                    var prev = existing_via_seg[bi]
                    if prev == UInt32(0) or prev == net_id:
                        existing_via_seg[bi] = net_id
                    else:
                        existing_via_seg[bi] = UInt32(0xFFFF_FFFF)
                b += 1

    # Compute net ordering (BGA-friendly: route "deep" pads first).
    var n_nets = len(net_names)
    # Placeholder for per-net clearance support (currently uniform).
    var net_clearance_mm_by_spec = List[Float64](length=n_nets, fill=clearance_mm)
    # Per-net allowed layers mask (bitset). Mask=0 means "all layers".
    var all_mask = UInt32(0)
    var li = 0
    while li < len(layers) and li < 32:
        all_mask = all_mask | (UInt32(1) << UInt32(li))
        li += 1
    var allowed_mask_by_spec = List[UInt32](length=n_nets, fill=all_mask)
    # `builtins` used for checking config types; already imported above.
    if Int(py=builtins.isinstance(cfg.net_layer_allow, builtins.dict)) != 0:
        var ni = 0
        while ni < n_nets:
            var key = PythonObject(net_names[ni])
            if not cfg.net_layer_allow.__contains__(key):
                ni += 1
                continue
            var v = cfg.net_layer_allow[key]
            var mask = UInt32(0)
            var is_seq = (Int(py=builtins.isinstance(v, builtins.list)) != 0) or (Int(py=builtins.isinstance(v, builtins.tuple)) != 0)
            if is_seq:
                for item in v:
                    var lname = String(py=item)
                    var j = 0
                    while j < len(layers):
                        if layers[j] == lname:
                            mask = mask | (UInt32(1) << UInt32(j))
                            break
                        j += 1
            else:
                var lname = String(py=v)
                var j = 0
                while j < len(layers):
                    if layers[j] == lname:
                        mask = mask | (UInt32(1) << UInt32(j))
                        break
                    j += 1
            if mask != UInt32(0):
                allowed_mask_by_spec[ni] = mask
            ni += 1

    var order = List[Int](capacity=n_nets)
    var depth_keys = List[Int](capacity=n_nets)
    var goal_dx = List[Int](capacity=n_nets)
    var goal_dy = List[Int](capacity=n_nets)
    var i = 0
    var min_x = 1_000_000
    var min_y = 1_000_000
    var max_x = -1_000_000
    var max_y = -1_000_000
    var cx = width // 2
    var cy = height // 2
    while i < n_nets:
        order.append(i)
        var s = idx_to_coords(start_idxs[i], width, height)
        var t = idx_to_coords(goal_idxs[i], width, height)
        goal_dx.append(t.x - cx)
        goal_dy.append(t.y - cy)
        if s.x < min_x:
            min_x = s.x
        if s.y < min_y:
            min_y = s.y
        if s.x > max_x:
            max_x = s.x
        if s.y > max_y:
            max_y = s.y
        i += 1
    i = 0
    while i < n_nets:
        var s = idx_to_coords(start_idxs[i], width, height)
        var d_left = s.x - min_x
        var d_right = max_x - s.x
        var d_top = s.y - min_y
        var d_bot = max_y - s.y
        var d = d_left
        if d_right < d:
            d = d_right
        if d_top < d:
            d = d_top
        if d_bot < d:
            d = d_bot
        depth_keys.append(d)
        i += 1

    # Insertion sort (depth desc, then goal-angle asc).
    var j = 1
    while j < len(order):
        var cur = order[j]
        var k = j - 1
        while k >= 0 and (
            depth_keys[order[k]] < depth_keys[cur]
            or (
                depth_keys[order[k]] == depth_keys[cur]
                and _angle_less(goal_dx[cur], goal_dy[cur], goal_dx[order[k]], goal_dy[order[k]])
            )
        ):
            order[k + 1] = order[k]
            k -= 1
        order[k + 1] = cur
        j += 1

    # Optional: defer power nets to the end to avoid blocking signals.
    if cfg.route_power_last:
        var sig = List[Int]()
        var pwr = List[Int]()
        for ni in order:
            var n = net_names[ni]
            if n == "GND" or n == "VCC":
                pwr.append(ni)
            else:
                sig.append(ni)
        for ni in pwr:
            sig.append(ni)
        order = sig^

    # Store per-spec routes (input `nets` can contain multiple segments with the same net name).
    var tracks_by_spec = List[PythonObject](length=n_nets, fill=py.none())
    var vias_by_spec = List[PythonObject](length=n_nets, fill=py.none())
    var paths_by_spec = List[List[Int]](capacity=n_nets)
    var bbox_x0 = List[Int](length=n_nets, fill=-1)
    var bbox_y0 = List[Int](length=n_nets, fill=-1)
    var bbox_x1 = List[Int](length=n_nets, fill=-1)
    var bbox_y1 = List[Int](length=n_nets, fill=-1)
    var routed_state = List[Int](length=n_nets, fill=0)
    i = 0
    while i < n_nets:
        paths_by_spec.append(List[Int]())
        i += 1

    var max_margin = cfg.margin_max
    if max_margin == 0:
        max_margin = width
        if height > max_margin:
            max_margin = height
        # Ensure at least one pass runs even if margin_init exceeds board size.
        if cfg.margin_init > max_margin:
            max_margin = cfg.margin_init
    var margin_step = cfg.margin_step
    if margin_step <= 0:
        margin_step = 1
    var attempts = cfg.attempts
    if attempts <= 0:
        attempts = 1
    var t0 = _now_s()
    var max_time_s = Float64(0.0)
    if cfg.max_time_ms != UInt32(0):
        max_time_s = Float64(cfg.max_time_ms) / Float64(1000.0)
    var per_net_time_s = Float64(0.0)
    if cfg.per_net_time_ms != UInt32(0):
        per_net_time_s = Float64(cfg.per_net_time_ms) / Float64(1000.0)

    # Negotiated congestion routing (PathFinder-style) to improve multi-net completion:
    # - route all nets once (iter 0)
    # - compute conflicts via keepout fields
    # - reroute only failed/conflicting nets with history penalties
    if cfg.ncr_iters > 0 and cfg.commit_routes:
        var used_escape_exits = _py_set()
        var net_id_to_spec = py.dict()
        i = 0
        while i < n_nets:
            net_id_to_spec[PythonObject(Int(net_ids[i]))] = PythonObject(Int(i))
            i += 1
        var reroute_set = List[Int](capacity=n_nets)
        i = 0
        while i < n_nets:
            reroute_set.append(i)
            i += 1

        var iter = 0
        while iter < cfg.ncr_iters:
            if max_time_s > 0.0 and (_now_s() - t0) > max_time_s:
                break
            var pass_failed = List[Int]()
            var k = 0
            while k < len(reroute_set):
                if max_time_s > 0.0 and (_now_s() - t0) > max_time_s:
                    break
                var ni = reroute_set[k]
                if ni < 0 or ni >= n_nets:
                    k += 1
                    continue
                var net_name = net_names[ni]
                var net_id = net_ids[ni]
                var start_idx = start_idxs[ni]
                var goal_idx = goal_idxs[ni]
                var t_net0 = _now_s()
                var deadline_s = Float64(0.0)
                if max_time_s > 0.0:
                    deadline_s = t0 + max_time_s
                if per_net_time_s > 0.0:
                    var dn = t_net0 + per_net_time_s
                    if deadline_s == 0.0 or dn < deadline_s:
                        deadline_s = dn

                # Optional escape stage (e.g., BGA fanout): route start -> exit inside the
                # escape bounding box, then route exit -> goal globally.
                var esc_path = List[Int]()
                var start2 = start_idx
                if cfg.escape_enable:
                    if cfg.batch_fanout_enable:
                        var ep = _plan_escape_path_adaptive(
                            ws,
                            g,
                            start_idx,
                            net_id,
                            used_escape_exits,
                            attempts,
                            cfg,
                            spacing,
                            existing_via_any,
                            existing_via_seg,
                            allowed_mask_by_spec[ni],
                            cfg.ncr_present_cost,
                            UInt64(iter),
                            cfg.batch_fanout_max_candidates,
                            deadline_s,
                        )
                        if len(ep) > 0:
                            esc_path = ep^
                            start2 = esc_path[len(esc_path) - 1]
                    else:
                        var escape_bb = _bbox_expand(_bbox_from_point(start_idx, width, height, cfg.escape_margin), 0, width, height)
                        var candidates = _exit_candidates_from_start(g, start_idx, net_id, escape_bb, 12)
                        var found = False
                        var ci = 0
                        while ci < len(candidates) and not found:
                            var exit_idx = _pick_escape_exit(candidates, ci, used_escape_exits, cfg.escape_unique_exit)
                            if exit_idx < 0:
                                break
                            var esc_attempt = 0
                            while esc_attempt < attempts:
                                var esc_seed = cfg.seed ^ (UInt64(iter) << UInt64(32)) ^ (UInt64(net_id) << UInt64(1)) ^ UInt64(esc_attempt) ^ (UInt64(ci) << UInt64(16)) ^ UInt64(0xE5E5)
                                var ep2 = route_a_star_bounded(
                                    ws,
                                    g,
                                    start_idx,
                                    exit_idx,
                                    net_id,
                                    esc_seed,
                                    cfg.diagonal,
                                    cfg.via_penalty,
                                    cfg.layer_penalty_outer,
                                    cfg.layer_penalty_in1,
                                    cfg.layer_penalty_inner,
                                    escape_bb.x0,
                                    escape_bb.y0,
                                    escape_bb.x1,
                                    escape_bb.y1,
                                    cfg.astar_max_expansions,
                                    cfg.heuristic_weight_pct,
                                    deadline_s,
                                    cfg.enforce_spacing,
                                    cfg.enforce_touch,
                                    cfg.ncr_allow_overlaps,
                                    cfg.spacing_present_cost,
                                    cfg.spacing_present_cap,
                                    cfg.ncr_present_cost,
                                    cfg.ncr_history_cost,
                                    False,
                                    existing_via_any,
                                    existing_via_seg,
                                    cfg.forbid_stacked_vias,
                                    allowed_mask_by_spec[ni],
                                )
                                if len(ep2) > 0:
                                    esc_path = ep2^
                                    # In NCR mode we frequently reroute nets; committing escape paths early
                                    # without also uncommitting on failure can poison the board state.
                                    # Only use early-commit in the non-NCR pipelines below.
                                    start2 = esc_path[len(esc_path) - 1]
                                    used_escape_exits.add(PythonObject(exit_idx))
                                    found = True
                                    break
                                esc_attempt += 1
                            ci += 1
                        if not found:
                            # Fallback: route without escape if no exit can be found.
                            esc_path = List[Int]()
                            start2 = start_idx

                # Uncommit previous route for this net if present.
                if routed_state[ni] == 1 and len(paths_by_spec[ni]) > 0:
                    g.uncommit_path(net_id, paths_by_spec[ni].copy(), cfg.enforce_spacing, spacing)
                    routed_state[ni] = 0
                    tracks_by_spec[ni] = py.none()
                    vias_by_spec[ni] = py.none()
                    paths_by_spec[ni] = List[Int]()
                    bbox_x0[ni] = -1
                    bbox_y0[ni] = -1
                    bbox_x1[ni] = -1
                    bbox_y1[ni] = -1
                    if cfg.precommit_shorts_enable:
                        _rebuild_precommit_db_inplace(
                            pre_db,
                            tracks_by_spec,
                            vias_by_spec,
                            routed_state,
                            net_ids,
                            layers,
                            clearance_mm,
                            origin_x_mm=origin_x_mm,
                            origin_y_mm=origin_y_mm,
                            board_w_mm=(Float64(width) * resolution_mm),
                            board_h_mm=(Float64(height) * resolution_mm),
                            fast_index_enable=cfg.precommit_fast_index_enable,
                            fast_index_cell_mm=cfg.precommit_fast_index_cell_mm,
                        )

                var routed = False
                var margin = cfg.margin_init
                var shove_rips = 0
                while margin <= max_margin and not routed:
                    if per_net_time_s > 0.0 and (_now_s() - t_net0) > per_net_time_s:
                        break
                    var attempt = 0
                    while attempt < attempts:
                        if per_net_time_s > 0.0 and (_now_s() - t_net0) > per_net_time_s:
                            break
                        var seed = cfg.seed ^ (UInt64(iter) << UInt64(32)) ^ UInt64(net_id) ^ UInt64(attempt) ^ UInt64(0x5046)
                        var path = route_a_star(
                            ws,
                            g,
                            start2,
                            goal_idx,
                            net_id,
                            seed,
                            cfg.diagonal,
                            cfg.via_penalty,
                            cfg.layer_penalty_outer,
                            cfg.layer_penalty_in1,
                            cfg.layer_penalty_inner,
                            margin,
                            cfg.astar_max_expansions,
                            cfg.heuristic_weight_pct,
                            deadline_s,
                            cfg.enforce_spacing,
                            cfg.enforce_touch,
                            cfg.ncr_allow_overlaps,
                            cfg.spacing_present_cost,
                            cfg.spacing_present_cap,
                            cfg.ncr_present_cost,
                            cfg.ncr_history_cost,
                            False,
                            existing_via_any,
                            existing_via_seg,
                            cfg.forbid_stacked_vias,
                            allowed_mask_by_spec[ni],
                        )
                        if len(path) == 0 and cfg.maze_fallback_enable:
                            var sc = idx_to_coords(start2, width, height)
                            var gc = idx_to_coords(goal_idx, width, height)
                            if sc.layer == gc.layer:
                                if cfg.debug:
                                    print("  maze_prm attempt", attempt, "samples", cfg.maze_samples, "k", cfg.maze_k_neigh)
                                var sx_mm = origin_x_mm + Float64(sc.x) * resolution_mm
                                var sy_mm = origin_y_mm + Float64(sc.y) * resolution_mm
                                var gx_mm = origin_x_mm + Float64(gc.x) * resolution_mm
                                var gy_mm = origin_y_mm + Float64(gc.y) * resolution_mm
                                var mpath = List[Int]()
                                mpath = maze_route_prm_single_layer(
                                    layer=sc.layer,
                                    start_mm=Vec2(sx_mm, sy_mm),
                                    goal_mm=Vec2(gx_mm, gy_mm),
                                    net_id=net_id,
                                    track_width_mm=track_width_mm[ni],
                                    clearance_mm=clearance_mm,
                                    circles=maze_circles,
                                    polys=maze_polys,
                                    track_db=pre_db.tracks,
                                    origin_x_mm=origin_x_mm,
                                    origin_y_mm=origin_y_mm,
                                    board_w_mm=(Float64(width) * resolution_mm),
                                    board_h_mm=(Float64(height) * resolution_mm),
                                    resolution_mm=resolution_mm,
                                    width=width,
                                    height=height,
                                    seed=seed ^ UInt64(0x4D415A45),
                                    samples=cfg.maze_samples,
                                    k_neigh=cfg.maze_k_neigh,
                                )
                                if len(mpath) > 0:
                                    path = mpath^
                                elif cfg.debug:
                                    print("  maze_prm no path")
                        if len(path) > 0:
                            var full_path = _merge_paths(esc_path, path)
                            if cfg.pull_tight_enable:
                                full_path = _pull_tight_path(g, net_id, full_path, cfg.diagonal, cfg.enforce_touch, cfg.enforce_spacing)
                            var tv = _path_to_tracks_and_vias(
                                net_name,
                                track_width_mm[ni],
                                via_diameter_mm[ni],
                                via_drill_mm[ni],
                                uvia_diameter_mm[ni],
                                    uvia_drill_mm[ni],
                                    layers,
                                    resolution_mm,
                                    origin_x_mm,
                                    origin_y_mm,
                                    width,
                                    height,
                                    full_path,
                                    existing_vias_py,
                                    pad_stacks_py,
                                )
                            if cfg.precommit_drc_enable and _tracks_violate_keepouts(
                                tv.tracks,
                                keepout_circles,
                                keepout_circle_net,
                                keepout_polygons,
                                keepout_poly_net,
                                keepout_circle_mask,
                                keepout_poly_mask,
                                layers,
                                clearance_mm,
                                net_id,
                            ):
                                attempt += 1
                                continue
                            if cfg.precommit_shorts_enable:
                                var culprit = _tracks_first_conflict_net(
                                    tv.tracks,
                                    net_id,
                                    layers,
                                    pre_db.tracks,
                                    pre_db.vias,
                                    clearance_mm,
                                    track_index_enabled=pre_db.track_index_enabled,
                                    track_index=pre_db.track_index,
                                )
                                if culprit == UInt32(0):
                                    culprit = _vias_first_conflict_net(tv.vias, net_id, layers, pre_db.tracks, pre_db.vias, clearance_mm)
                                if culprit != UInt32(0):
                                    # Negotiation routing: penalize congested/conflicting cells even when the
                                    # candidate path is rejected by precommit checks, so subsequent attempts
                                    # explore alternatives instead of repeating the same conflict.
                                    if cfg.ncr_history_inc != UInt16(0):
                                        _ = g.update_history_for_path(net_id, full_path.copy(), cfg.ncr_history_inc)
                                    if cfg.shove_enable and shove_rips < cfg.shove_max_rips and net_id_to_spec.__contains__(PythonObject(Int(culprit))):
                                        var sid = Int(py=net_id_to_spec[PythonObject(Int(culprit))])
                                        if sid >= 0 and sid < n_nets and routed_state[sid] == 1 and len(paths_by_spec[sid]) > 0:
                                            if cfg.debug:
                                                print("NCR shove rip", net_name, "conflict with", culprit)
                                            var snap_bb = BBox(bbox_x0[sid], bbox_y0[sid], bbox_x1[sid], bbox_y1[sid])
                                            g.uncommit_path(culprit, paths_by_spec[sid].copy(), cfg.enforce_spacing, spacing)
                                            routed_state[sid] = 0
                                            tracks_by_spec[sid] = py.none()
                                            vias_by_spec[sid] = py.none()
                                            paths_by_spec[sid] = List[Int]()
                                            bbox_x0[sid] = -1
                                            bbox_y0[sid] = -1
                                            bbox_x1[sid] = -1
                                            bbox_y1[sid] = -1
                                            _rebuild_precommit_db_inplace(
                                                pre_db,
                                                tracks_by_spec,
                                                vias_by_spec,
                                                routed_state,
                                                net_ids,
                                                layers,
                                                clearance_mm,
                                                origin_x_mm=origin_x_mm,
                                                origin_y_mm=origin_y_mm,
                                                board_w_mm=(Float64(width) * resolution_mm),
                                                board_h_mm=(Float64(height) * resolution_mm),
                                                fast_index_enable=cfg.precommit_fast_index_enable,
                                                fast_index_cell_mm=cfg.precommit_fast_index_cell_mm,
                                            )
                                            # Try to re-route the ripped net inside a local window (a cheap shove approximation).
                                            var extra = cfg.ripup_extra_dist_cells
                                            if extra <= 0:
                                                extra = 20
                                            var bound = _bbox_expand(snap_bb, extra, width, height)
                                            var rr = _try_reroute_path_bounded(
                                                ws,
                                                g,
                                                sid,
                                                clearance_mm,
                                                net_names,
                                                net_ids,
                                                start_idxs,
                                                goal_idxs,
                                                track_width_mm,
                                                via_diameter_mm,
                                                via_drill_mm,
                                                uvia_diameter_mm,
                                                uvia_drill_mm,
                                                layers,
                                                resolution_mm,
                                                origin_x_mm,
                                                origin_y_mm,
                                                width,
                                                height,
                                                existing_vias_py,
                                                pad_stacks_py,
                                                allowed_mask_by_spec[sid],
                                                spacing,
                                                cfg,
                                                bound=bound,
                                                iter_tag=UInt64(iter),
                                                seed_tag=UInt64(0x53484F5645),
                                                deadline_s=deadline_s,
                                                pre_db=pre_db,
                                                keepout_circles=keepout_circles,
                                                keepout_circle_net=keepout_circle_net,
                                                keepout_polygons=keepout_polygons,
                                                keepout_poly_net=keepout_poly_net,
                                                keepout_circle_mask=keepout_circle_mask,
                                                keepout_poly_mask=keepout_poly_mask,
                                                clearance_mm=clearance_mm,
                                                existing_via_any=existing_via_any,
                                                existing_via_seg=existing_via_seg,
                                            )
                                            if rr.ok:
                                                tracks_by_spec[sid] = rr.tracks
                                                vias_by_spec[sid] = rr.vias
                                                paths_by_spec[sid] = rr.path.copy()
                                                g.commit_path(net_ids[sid], rr.path.copy(), cfg.enforce_spacing, spacing)
                                                routed_state[sid] = 1
                                                if cfg.precommit_shorts_enable:
                                                    _index_commit_tracks(rr.tracks, net_ids[sid], layers, pre_db.tracks)
                                                    if pre_db.track_index_enabled:
                                                        _index_commit_tracks_spatial(rr.tracks, net_ids[sid], layers, pre_db.track_index)
                                                    _index_commit_vias(rr.vias, net_ids[sid], layers, pre_db.vias, clearance_mm)
                                                var bb2 = _bbox_from_path(rr.path, width, height)
                                                bbox_x0[sid] = bb2.x0
                                                bbox_y0[sid] = bb2.y0
                                                bbox_x1[sid] = bb2.x1
                                                bbox_y1[sid] = bb2.y1
                                            shove_rips += 1
                                            attempt += 1
                                            continue
                                    attempt += 1
                                    continue
                            tracks_by_spec[ni] = tv.tracks
                            vias_by_spec[ni] = tv.vias
                            g.commit_path(net_id, full_path, cfg.enforce_spacing, spacing)
                            if cfg.precommit_shorts_enable:
                                _index_commit_tracks(
                                    tv.tracks,
                                    net_id,
                                    layers,
                                    pre_db.tracks,
                                )
                                if pre_db.track_index_enabled:
                                    _index_commit_tracks_spatial(
                                        tv.tracks,
                                        net_id,
                                        layers,
                                        pre_db.track_index,
                                    )
                                _index_commit_vias(tv.vias, net_id, layers, pre_db.vias, clearance_mm)
                            paths_by_spec[ni] = full_path.copy()
                            var bb = _bbox_from_path(full_path, width, height)
                            bbox_x0[ni] = bb.x0
                            bbox_y0[ni] = bb.y0
                            bbox_x1[ni] = bb.x1
                            bbox_y1[ni] = bb.y1
                            routed_state[ni] = 1
                            routed = True
                            break
                        attempt += 1
                    margin += margin_step

                if not routed:
                    pass_failed.append(ni)
                k += 1

            # Update history for conflicting nets and build reroute set for next iter.
            var any_conflict = False
            var next_reroute = List[Int]()
            for ni in pass_failed:
                next_reroute.append(ni)
            i = 0
            while i < n_nets:
                if routed_state[i] == 1 and len(paths_by_spec[i]) > 0:
                    var conflict = g.update_history_for_path(net_ids[i], paths_by_spec[i].copy(), cfg.ncr_history_inc)
                    if conflict:
                        any_conflict = True
                        next_reroute.append(i)
                i += 1
            if len(pass_failed) == 0 and not any_conflict:
                break

            # Dedup reroute set.
            var mark = List[UInt16](length=n_nets, fill=UInt16(0))
            var dedup = List[Int]()
            for x in next_reroute:
                if x < 0 or x >= n_nets:
                    continue
                if mark[x] == UInt16(0):
                    mark[x] = UInt16(1)
                    dedup.append(x)
            reroute_set = dedup^
            iter += 1

        # Optional legalization: reroute conflicting nets with overlaps disallowed,
        # using the precommit shorts/clearance checks as a strict filter.
        if cfg.legalize_passes > 0:
            var deadline_s0 = Float64(0.0)
            if max_time_s > 0.0:
                deadline_s0 = t0 + max_time_s
            _rebuild_precommit_db_inplace(
                pre_db,
                tracks_by_spec,
                vias_by_spec,
                routed_state,
                net_ids,
                layers,
                clearance_mm,
                origin_x_mm=origin_x_mm,
                origin_y_mm=origin_y_mm,
                board_w_mm=(Float64(width) * resolution_mm),
                board_h_mm=(Float64(height) * resolution_mm),
                fast_index_enable=cfg.precommit_fast_index_enable,
                fast_index_cell_mm=cfg.precommit_fast_index_cell_mm,
            )
            var lp = 0
            while lp < cfg.legalize_passes:
                var any_change = False
                i = 0
                while i < n_nets:
                    if routed_state[i] != 1 or len(paths_by_spec[i]) == 0:
                        i += 1
                        continue
                    var nid = net_ids[i]
                    # Optional: use the grid's own keepout fields (which include seeded pad/no-net
                    # circles when enabled) to detect spacing violations. This catches cases
                    # that the precommit DB cannot see (pads are not in the DB).
                    var grid_violation = False
                    if cfg.legalize_use_grid_keepouts:
                        grid_violation = g.path_violates_keepouts(nid, paths_by_spec[i], cfg.enforce_touch, True)
                    var culprit = UInt32(0)
                    if not grid_violation:
                        # Also check strict geometry-vs-tracks/vias conflicts via precommit DB.
                        culprit = _tracks_first_conflict_net(
                            tracks_by_spec[i],
                            nid,
                            layers,
                            pre_db.tracks,
                            pre_db.vias,
                            clearance_mm,
                            track_index_enabled=pre_db.track_index_enabled,
                            track_index=pre_db.track_index,
                        )
                        if culprit == UInt32(0):
                            culprit = _vias_first_conflict_net(vias_by_spec[i], nid, layers, pre_db.tracks, pre_db.vias, clearance_mm)
                    if not grid_violation and culprit == UInt32(0):
                        i += 1
                        continue

                    # Rip and reroute this net strictly.
                    var snap_path = paths_by_spec[i].copy()
                    var snap_tracks = tracks_by_spec[i]
                    var snap_vias = vias_by_spec[i]
                    var snap_x0 = bbox_x0[i]
                    var snap_y0 = bbox_y0[i]
                    var snap_x1 = bbox_x1[i]
                    var snap_y1 = bbox_y1[i]
                    g.uncommit_path(nid, paths_by_spec[i].copy(), cfg.enforce_spacing, spacing)
                    routed_state[i] = 0
                    tracks_by_spec[i] = py.none()
                    vias_by_spec[i] = py.none()
                    paths_by_spec[i] = List[Int]()
                    bbox_x0[i] = -1
                    bbox_y0[i] = -1
                    bbox_x1[i] = -1
                    bbox_y1[i] = -1
                    _rebuild_precommit_db_inplace(
                        pre_db,
                        tracks_by_spec,
                        vias_by_spec,
                        routed_state,
                        net_ids,
                        layers,
                        clearance_mm,
                        origin_x_mm=origin_x_mm,
                        origin_y_mm=origin_y_mm,
                        board_w_mm=(Float64(width) * resolution_mm),
                        board_h_mm=(Float64(height) * resolution_mm),
                        fast_index_enable=cfg.precommit_fast_index_enable,
                        fast_index_cell_mm=cfg.precommit_fast_index_cell_mm,
                    )

                    var net_name = net_names[i]
                    var start_idx = start_idxs[i]
                    var goal_idx = goal_idxs[i]
                    var esc_path = List[Int]()
                    var start2 = start_idx
                    if cfg.escape_enable:
                        var ep = _plan_escape_path_adaptive(
                            ws,
                            g,
                            start_idx,
                            nid,
                            used_escape_exits,
                            attempts,
                            cfg,
                            spacing,
                            existing_via_any,
                            existing_via_seg,
                            allowed_mask_by_spec[i],
                            UInt32(0),
                            UInt64(lp),
                            cfg.batch_fanout_max_candidates,
                            deadline_s0,
                        )
                        if len(ep) > 0:
                            esc_path = ep^
                            start2 = esc_path[len(esc_path) - 1]

                    var routed = False
                    var margin = cfg.margin_init
                    while margin <= max_margin and not routed:
                        var attempt = 0
                        while attempt < attempts:
                            var seed = cfg.seed ^ (UInt64(lp) << UInt64(32)) ^ UInt64(nid) ^ UInt64(attempt) ^ UInt64(0x1A2B)
                            var path = route_a_star(
                                ws,
                                g,
                                start2,
                                goal_idx,
                                nid,
                                seed,
                                cfg.diagonal,
                                cfg.via_penalty,
                                cfg.layer_penalty_outer,
                                cfg.layer_penalty_in1,
                                cfg.layer_penalty_inner,
                                margin,
                                cfg.astar_max_expansions,
                                cfg.heuristic_weight_pct,
                                deadline_s0,
                                cfg.enforce_spacing,
                                cfg.enforce_touch,
                                False,
                                cfg.spacing_present_cost,
                                cfg.spacing_present_cap,
                                UInt32(0),
                                UInt32(0),
                                False,
                                existing_via_any,
                                existing_via_seg,
                                cfg.forbid_stacked_vias,
                                allowed_mask_by_spec[i],
                            )
                            if len(path) > 0:
                                var full_path = _merge_paths(esc_path, path)
                                if cfg.legalize_use_grid_keepouts and g.path_violates_keepouts(nid, full_path, cfg.enforce_touch, True):
                                    attempt += 1
                                    continue
                                var tv = _path_to_tracks_and_vias(
                                    net_name,
                                    track_width_mm[i],
                                    via_diameter_mm[i],
                                    via_drill_mm[i],
                                    uvia_diameter_mm[i],
                                        uvia_drill_mm[i],
                                        layers,
                                        resolution_mm,
                                        origin_x_mm,
                                        origin_y_mm,
                                        width,
                                        height,
                                        full_path,
                                        existing_vias_py,
                                        pad_stacks_py,
                                    )
                                var culprit2 = _tracks_first_conflict_net(
                                    tv.tracks,
                                    nid,
                                    layers,
                                    pre_db.tracks,
                                    pre_db.vias,
                                    clearance_mm,
                                    track_index_enabled=pre_db.track_index_enabled,
                                    track_index=pre_db.track_index,
                                )
                                if culprit2 == UInt32(0):
                                    culprit2 = _vias_first_conflict_net(tv.vias, nid, layers, pre_db.tracks, pre_db.vias, clearance_mm)
                                if culprit2 != UInt32(0):
                                    attempt += 1
                                    continue
                                tracks_by_spec[i] = tv.tracks
                                vias_by_spec[i] = tv.vias
                                g.commit_path(nid, full_path, cfg.enforce_spacing, spacing)
                                _index_commit_tracks(
                                    tv.tracks,
                                    nid,
                                    layers,
                                    pre_db.tracks,
                                )
                                if pre_db.track_index_enabled:
                                    _index_commit_tracks_spatial(
                                        tv.tracks,
                                        nid,
                                        layers,
                                        pre_db.track_index,
                                    )
                                _index_commit_vias(tv.vias, nid, layers, pre_db.vias, clearance_mm)
                                paths_by_spec[i] = full_path.copy()
                                var bb = _bbox_from_path(full_path, width, height)
                                bbox_x0[i] = bb.x0
                                bbox_y0[i] = bb.y0
                                bbox_x1[i] = bb.x1
                                bbox_y1[i] = bb.y1
                                routed_state[i] = 1
                                routed = True
                                any_change = True
                                break
                            attempt += 1
                        margin += margin_step

                    if not routed:
                        # Restore the previous (possibly conflicting) route so we
                        # don't lose completion if strict reroute can't find an
                        # alternative. We'll keep trying in later passes.
                        g.commit_path(nid, snap_path.copy(), cfg.enforce_spacing, spacing)
                        routed_state[i] = 1
                        tracks_by_spec[i] = snap_tracks
                        vias_by_spec[i] = snap_vias
                        paths_by_spec[i] = snap_path.copy()
                        bbox_x0[i] = snap_x0
                        bbox_y0[i] = snap_y0
                        bbox_x1[i] = snap_x1
                        bbox_y1[i] = snap_y1
                        _rebuild_precommit_db_inplace(
                            pre_db,
                            tracks_by_spec,
                            vias_by_spec,
                            routed_state,
                            net_ids,
                            layers,
                            clearance_mm,
                            origin_x_mm=origin_x_mm,
                            origin_y_mm=origin_y_mm,
                            board_w_mm=(Float64(width) * resolution_mm),
                            board_h_mm=(Float64(height) * resolution_mm),
                            fast_index_enable=cfg.precommit_fast_index_enable,
                            fast_index_cell_mm=cfg.precommit_fast_index_cell_mm,
                        )
                    i += 1

                if not any_change:
                    break
                lp += 1

        # Write output and return.
        var out_tracks = py.list()
        var out_vias = py.list()
        var fail_map = py.dict()

        i = 0
        while i < n_nets:
            if routed_state[i] == 1:
                for t in tracks_by_spec[i]:
                    out_tracks.append(t)
                for v in vias_by_spec[i]:
                    out_vias.append(v)
            else:
                fail_map[PythonObject(net_names[i])] = PythonObject(Int(1))
            i += 1

        var failed = py.list()
        for k in fail_map:
            failed.append(k)

        var payload = py.dict()
        payload[PythonObject(String("backend"))] = PythonObject(String("pardal_router_mojo"))
        payload[PythonObject(String("problem"))] = PythonObject(problem_path)
        payload[PythonObject(String("tracks"))] = out_tracks
        payload[PythonObject(String("vias"))] = out_vias
        payload[PythonObject(String("failed_nets"))] = failed

        var json = py.import_module("json")
        var pathlib = py.import_module("pathlib")
        var txt = json.dumps(payload, indent=PythonObject(Int(2)))
        pathlib.Path(PythonObject(routes_path)).write_text(txt)
        return

    var used_escape_exits_non_ncr = _py_set()
    if not cfg.commit_routes:
        # Independent per-net routing (no conflicts).
        for ni in order:
            if max_time_s > 0.0 and (_now_s() - t0) > max_time_s:
                break
            var net_name = net_names[ni]
            var net_id = net_ids[ni]
            var start_idx = start_idxs[ni]
            var goal_idx = goal_idxs[ni]
            if cfg.debug:
                print("route", net_name, "id", net_id)
            var esc_path = List[Int]()
            var start2 = start_idx
            var esc_exit_idx = -1
            if cfg.escape_enable:
                if max_time_s > 0.0 and (_now_s() - t0) > max_time_s:
                    break
                var escape_bb = _bbox_expand(_bbox_from_point(start_idx, width, height, cfg.escape_margin), 0, width, height)
                var candidates = _exit_candidates_from_start(g, start_idx, net_id, escape_bb, 12)
                var found = False
                var ci = 0
                while ci < len(candidates) and not found:
                    if max_time_s > 0.0 and (_now_s() - t0) > max_time_s:
                        break
                    var exit_idx = _pick_escape_exit(candidates, ci, used_escape_exits_non_ncr, cfg.escape_unique_exit)
                    if exit_idx < 0:
                        break
                    esc_exit_idx = exit_idx
                    var esc_attempt = 0
                    while esc_attempt < attempts:
                        if max_time_s > 0.0 and (_now_s() - t0) > max_time_s:
                            break
                        var esc_seed = cfg.seed ^ (UInt64(net_id) << UInt64(1)) ^ UInt64(esc_attempt) ^ (UInt64(ci) << UInt64(16)) ^ UInt64(0xE5E5)
                        var ep = route_a_star_bounded(
                            ws,
                            g,
                            start_idx,
                            exit_idx,
                            net_id,
                            esc_seed,
                            cfg.diagonal,
                            cfg.via_penalty,
                            cfg.layer_penalty_outer,
                            cfg.layer_penalty_in1,
                            cfg.layer_penalty_inner,
                            escape_bb.x0,
                            escape_bb.y0,
                            escape_bb.x1,
                            escape_bb.y1,
                            cfg.astar_max_expansions,
                            cfg.heuristic_weight_pct,
                            t0 + max_time_s if max_time_s > 0.0 else Float64(0.0),
                            cfg.enforce_spacing,
                            cfg.enforce_touch,
                            cfg.ncr_allow_overlaps,
                            cfg.spacing_present_cost,
                            cfg.spacing_present_cap,
                            UInt32(0),
                            UInt32(0),
                            False,
                            existing_via_any,
                            existing_via_seg,
                            cfg.forbid_stacked_vias,
                            allowed_mask_by_spec[ni],
                        )
                        if len(ep) > 0:
                            esc_path = ep^
                            start2 = esc_path[len(esc_path) - 1]
                            found = True
                            break
                        esc_attempt += 1
                    ci += 1
                if not found:
                    continue
            var margin = cfg.margin_init
            var routed = False
            var t_net0 = _now_s()
            while margin <= max_margin:
                if per_net_time_s > 0.0 and (_now_s() - t_net0) > per_net_time_s:
                    break
                var attempt = 0
                while attempt < attempts:
                    if per_net_time_s > 0.0 and (_now_s() - t_net0) > per_net_time_s:
                        break
                    var seed = cfg.seed ^ (UInt64(net_id) << UInt64(1)) ^ UInt64(attempt)
                    var gp = route_a_star(
                        ws,
                        g,
                        start2,
                        goal_idx,
                        net_id,
                        seed,
                        cfg.diagonal,
                        cfg.via_penalty,
                        cfg.layer_penalty_outer,
                        cfg.layer_penalty_in1,
                        cfg.layer_penalty_inner,
                        margin,
                        cfg.astar_max_expansions,
                        cfg.heuristic_weight_pct,
                        t0 + max_time_s if max_time_s > 0.0 else Float64(0.0),
                        cfg.enforce_spacing,
                        cfg.enforce_touch,
                        False,
                        cfg.spacing_present_cost,
                        cfg.spacing_present_cap,
                        UInt32(0),
                        UInt32(0),
                        False,
                        existing_via_any,
                        existing_via_seg,
                        cfg.forbid_stacked_vias,
                        allowed_mask_by_spec[ni],
                    )

                    if len(gp) > 0:
                        var path = _merge_paths(esc_path, gp)
                        if cfg.pull_tight_enable:
                            path = _pull_tight_path(g, net_id, path, cfg.diagonal, cfg.enforce_touch, cfg.enforce_spacing)
                        var tv = _path_to_tracks_and_vias(
                            net_name,
                            track_width_mm[ni],
                            via_diameter_mm[ni],
                            via_drill_mm[ni],
                            uvia_diameter_mm[ni],
                                uvia_drill_mm[ni],
                                layers,
                                resolution_mm,
                                origin_x_mm,
                                origin_y_mm,
                                width,
                                height,
                                path,
                                existing_vias_py,
                                pad_stacks_py,
                            )
                        if cfg.precommit_drc_enable and _tracks_violate_keepouts(
                            tv.tracks,
                            keepout_circles,
                            keepout_circle_net,
                            keepout_polygons,
                            keepout_poly_net,
                            keepout_circle_mask,
                            keepout_poly_mask,
                            layers,
                            clearance_mm,
                            net_id,
                        ):
                            attempt += 1
                            continue
                        if cfg.precommit_shorts_enable and (
                            _tracks_violate_shorts_or_clearance(
                                tv.tracks,
                                net_id,
                                layers,
                                pre_db.tracks,
                                pre_db.vias,
                                net_clearance_mm_by_spec[ni] if ni < len(net_clearance_mm_by_spec) else clearance_mm,
                            )
                            or _vias_violate_shorts_or_clearance(tv.vias, net_id, layers, pre_db.tracks, pre_db.vias, clearance_mm)
                        ):
                            attempt += 1
                            continue
                        tracks_by_spec[ni] = tv.tracks
                        vias_by_spec[ni] = tv.vias
                        paths_by_spec[ni] = path.copy()
                        var bb = _bbox_from_path(path, width, height)
                        bbox_x0[ni] = bb.x0
                        bbox_y0[ni] = bb.y0
                        bbox_x1[ni] = bb.x1
                        bbox_y1[ni] = bb.y1
                        routed_state[ni] = 1
                        if cfg.precommit_shorts_enable:
                            _index_commit_tracks(
                                tv.tracks,
                                net_id,
                                layers,
                                pre_db.tracks,
                            )
                            _index_commit_vias(tv.vias, net_id, layers, pre_db.vias, clearance_mm)
                        margin = max_margin + 1
                        routed = True
                        break
                    attempt += 1
                if routed:
                    break
                margin += margin_step
            # Exits are reserved in _plan_escape_path().
        # done
    else:
        # Strict, sequential, no overlaps (preserves pre-existing vias committed above).
        var net_id_to_spec = py.dict()
        i = 0
        while i < n_nets:
            net_id_to_spec[PythonObject(Int(net_ids[i]))] = PythonObject(Int(i))
            i += 1

        # Batch fanout escape phase: pre-route and commit escape stubs inside each
        # start-centric bounding box to reserve channels before global routing.
        var esc_prefix = List[List[Int]](capacity=n_nets)
        i = 0
        while i < n_nets:
            esc_prefix.append(List[Int]())
            i += 1
        if cfg.escape_enable and cfg.batch_fanout_enable and cfg.escape_commit_early:
            var deadline_s0 = Float64(0.0)
            if max_time_s > 0.0:
                deadline_s0 = t0 + max_time_s
            for ni in order:
                if max_time_s > 0.0 and (_now_s() - t0) > max_time_s:
                    break
                var net_id = net_ids[ni]
                var start_idx = start_idxs[ni]
                var ep = _plan_escape_path_adaptive(
                    ws,
                    g,
                    start_idx,
                    net_id,
                    used_escape_exits_non_ncr,
                    attempts,
                    cfg,
                    spacing,
                    existing_via_any,
                    existing_via_seg,
                    allowed_mask_by_spec[ni],
                    UInt32(0),
                    UInt64(0xF00D),
                    cfg.batch_fanout_max_candidates,
                    deadline_s0,
                )
                if len(ep) > 0:
                    var ep_path = ep^
                    esc_prefix[ni] = ep_path.copy()
        for ni in order:
            if max_time_s > 0.0 and (_now_s() - t0) > max_time_s:
                break
            var net_name = net_names[ni]
            var net_id = net_ids[ni]
            var start_idx = start_idxs[ni]
            var goal_idx = goal_idxs[ni]

            var esc_path = List[Int]()
            var start2 = start_idx
            var esc_exit_idx = -1
            if cfg.escape_enable:
                if max_time_s > 0.0 and (_now_s() - t0) > max_time_s:
                    break
                if cfg.batch_fanout_enable and cfg.escape_commit_early and len(esc_prefix[ni]) > 0:
                    esc_path = esc_prefix[ni].copy()
                    g.commit_path(net_id, esc_path.copy(), cfg.enforce_spacing, spacing)
                    if cfg.precommit_shorts_enable:
                        var tv0 = _path_to_tracks_and_vias(
                            net_name,
                            track_width_mm[ni],
                            via_diameter_mm[ni],
                            via_drill_mm[ni],
                            uvia_diameter_mm[ni],
                                uvia_drill_mm[ni],
                                layers,
                                resolution_mm,
                                origin_x_mm,
                                origin_y_mm,
                                width,
                                height,
                                esc_path,
                                existing_vias_py,
                                pad_stacks_py,
                            )
                        _index_commit_tracks(
                            tv0.tracks,
                            net_id,
                            layers,
                            pre_db.tracks,
                        )
                        _index_commit_vias(tv0.vias, net_id, layers, pre_db.vias, clearance_mm)
                    start2 = esc_path[len(esc_path) - 1]
                else:
                    var ep = _plan_escape_path_adaptive(
                        ws,
                        g,
                        start_idx,
                        net_id,
                        used_escape_exits_non_ncr,
                        attempts,
                        cfg,
                        spacing,
                        existing_via_any,
                        existing_via_seg,
                        allowed_mask_by_spec[ni],
                        UInt32(0),
                        UInt64(0xE5E5),
                        12,
                        Float64(0.0),
                    )
                    # Escape is opportunistic: if we can't find a stub, fall back to
                    # routing start->goal directly rather than failing the net.
                    if len(ep) > 0:
                        esc_path = ep^
                        if cfg.escape_commit_early:
                            g.commit_path(net_id, esc_path.copy(), cfg.enforce_spacing, spacing)
                        start2 = esc_path[len(esc_path) - 1]
            var margin = cfg.margin_init
            var routed = False
            var shove_rips = 0
            var t_net0 = _now_s()
            var deadline_s = Float64(0.0)
            if max_time_s > 0.0:
                deadline_s = t0 + max_time_s
            if per_net_time_s > 0.0:
                var dn = t_net0 + per_net_time_s
                if deadline_s == 0.0 or dn < deadline_s:
                    deadline_s = dn
            while margin <= max_margin:
                if per_net_time_s > 0.0 and (_now_s() - t_net0) > per_net_time_s:
                    break
                var attempt = 0
                while attempt < attempts:
                    if per_net_time_s > 0.0 and (_now_s() - t_net0) > per_net_time_s:
                        break
                    var seed = cfg.seed ^ (UInt64(net_id) << UInt64(1)) ^ UInt64(attempt)
                    var gp = route_a_star(
                        ws,
                        g,
                        start2,
                        goal_idx,
                        net_id,
                        seed,
                        cfg.diagonal,
                        cfg.via_penalty,
                        cfg.layer_penalty_outer,
                        cfg.layer_penalty_in1,
                        cfg.layer_penalty_inner,
                        margin,
                        cfg.astar_max_expansions,
                        cfg.heuristic_weight_pct,
                        deadline_s,
                        cfg.enforce_spacing,
                        cfg.enforce_touch,
                        cfg.ncr_allow_overlaps,
                        cfg.spacing_present_cost,
                        cfg.spacing_present_cap,
                        UInt32(0),
                        UInt32(0),
                        False,
                        existing_via_any,
                        existing_via_seg,
                        cfg.forbid_stacked_vias,
                        allowed_mask_by_spec[ni],
                    )
                    if cfg.debug and len(gp) == 0:
                        print("  attempt", attempt, "margin", margin, "no path")
                    if len(gp) == 0 and cfg.maze_fallback_enable:
                        var sc = idx_to_coords(start2, width, height)
                        var gc = idx_to_coords(goal_idx, width, height)
                        if sc.layer == gc.layer:
                            if cfg.debug:
                                print("  maze_prm attempt", attempt, "samples", cfg.maze_samples, "k", cfg.maze_k_neigh)
                            var sx_mm = origin_x_mm + Float64(sc.x) * resolution_mm
                            var sy_mm = origin_y_mm + Float64(sc.y) * resolution_mm
                            var gx_mm = origin_x_mm + Float64(gc.x) * resolution_mm
                            var gy_mm = origin_y_mm + Float64(gc.y) * resolution_mm
                            var mpath = maze_route_prm_single_layer(
                                layer=sc.layer,
                                start_mm=Vec2(sx_mm, sy_mm),
                                goal_mm=Vec2(gx_mm, gy_mm),
                                net_id=net_id,
                                track_width_mm=track_width_mm[ni],
                                clearance_mm=clearance_mm,
                                circles=maze_circles,
                                polys=maze_polys,
                                track_db=pre_db.tracks,
                                origin_x_mm=origin_x_mm,
                                origin_y_mm=origin_y_mm,
                                board_w_mm=(Float64(width) * resolution_mm),
                                board_h_mm=(Float64(height) * resolution_mm),
                                resolution_mm=resolution_mm,
                                width=width,
                                height=height,
                                seed=seed ^ UInt64(0x4D415A45),
                                samples=cfg.maze_samples,
                                k_neigh=cfg.maze_k_neigh,
                            )
                            if len(mpath) > 0:
                                gp = mpath^
                            elif cfg.debug:
                                print("  maze_prm no path")
                    if len(gp) == 0 and cfg.shove_enable and len(layers) > 1:
                        # Shove/ripup tends to require re-routing on a different layer.
                        # If the default search returns no path, try forcing a non-start layer mask.
                        var s0 = idx_to_coords(start2, width, height)
                        var alt_mask = allowed_mask_by_spec[ni] & (~(UInt32(1) << UInt32(s0.layer)))
                        if alt_mask != UInt32(0):
                            gp = route_a_star(
                                ws,
                                g,
                                start2,
                                goal_idx,
                                net_id,
                                seed ^ UInt64(0xBEEF),
                                cfg.diagonal,
                                cfg.via_penalty,
                                cfg.layer_penalty_outer,
                                cfg.layer_penalty_in1,
                                cfg.layer_penalty_inner,
                                margin,
                                cfg.astar_max_expansions,
                                cfg.heuristic_weight_pct,
                                Float64(0.0),
                                cfg.enforce_spacing,
                                cfg.enforce_touch,
                                cfg.ncr_allow_overlaps,
                                cfg.spacing_present_cost,
                                cfg.spacing_present_cap,
                                UInt32(0),
                                UInt32(0),
                                False,
                                existing_via_any,
                                existing_via_seg,
                                cfg.forbid_stacked_vias,
                                alt_mask,
                            )
                            if cfg.debug:
                                print("  alt_mask path len", len(gp))

                    if len(gp) > 0:
                        var path = _merge_paths(esc_path, gp)
                        if cfg.pull_tight_enable:
                            path = _pull_tight_path(g, net_id, path, cfg.diagonal, cfg.enforce_touch, cfg.enforce_spacing)
                        var tv = _path_to_tracks_and_vias(
                            net_name,
                            track_width_mm[ni],
                            via_diameter_mm[ni],
                            via_drill_mm[ni],
                            uvia_diameter_mm[ni],
                                uvia_drill_mm[ni],
                                layers,
                                resolution_mm,
                                origin_x_mm,
                                origin_y_mm,
                                width,
                                height,
                                path,
                                existing_vias_py,
                                pad_stacks_py,
                            )
                        if cfg.precommit_drc_enable and _tracks_violate_keepouts(
                            tv.tracks,
                            keepout_circles,
                            keepout_circle_net,
                            keepout_polygons,
                            keepout_poly_net,
                            keepout_circle_mask,
                            keepout_poly_mask,
                            layers,
                            clearance_mm,
                            net_id,
                        ):
                            attempt += 1
                            continue
                        if cfg.precommit_shorts_enable:
                            var culprit = _tracks_first_conflict_net(
                                tv.tracks,
                                net_id,
                                layers,
                                pre_db.tracks,
                                pre_db.vias,
                                clearance_mm,
                                track_index_enabled=pre_db.track_index_enabled,
                                track_index=pre_db.track_index,
                            )
                            if culprit == UInt32(0):
                                culprit = _vias_first_conflict_net(tv.vias, net_id, layers, pre_db.tracks, pre_db.vias, clearance_mm)
                            if culprit != UInt32(0):
                                if cfg.ncr_history_inc != UInt16(0):
                                    _ = g.update_history_for_path(net_id, path.copy(), cfg.ncr_history_inc)
                                if cfg.debug:
                                    print("  conflict with net_id", culprit)
                                if cfg.shove_enable and shove_rips < cfg.shove_max_rips and net_id_to_spec.__contains__(PythonObject(Int(culprit))):
                                    var cid = Int(py=net_id_to_spec[PythonObject(Int(culprit))])
                                    if cid >= 0 and cid < n_nets and routed_state[cid] == 1 and len(paths_by_spec[cid]) > 0:
                                        if cfg.debug:
                                            print("  rip net", net_names[cid], "id", net_ids[cid])
                                        var snap_bb = BBox(bbox_x0[cid], bbox_y0[cid], bbox_x1[cid], bbox_y1[cid])
                                        # Rip up the conflicting net and rebuild the precommit DB, then retry.
                                        g.uncommit_path(net_ids[cid], paths_by_spec[cid].copy(), cfg.enforce_spacing, spacing)
                                        routed_state[cid] = 0
                                        tracks_by_spec[cid] = py.none()
                                        vias_by_spec[cid] = py.none()
                                        paths_by_spec[cid] = List[Int]()
                                        bbox_x0[cid] = -1
                                        bbox_y0[cid] = -1
                                        bbox_x1[cid] = -1
                                        bbox_y1[cid] = -1
                                        _rebuild_precommit_db_inplace(
                                            pre_db,
                                            tracks_by_spec,
                                            vias_by_spec,
                                            routed_state,
                                            net_ids,
                                            layers,
                                            clearance_mm,
                                            origin_x_mm=origin_x_mm,
                                            origin_y_mm=origin_y_mm,
                                            board_w_mm=(Float64(width) * resolution_mm),
                                            board_h_mm=(Float64(height) * resolution_mm),
                                            fast_index_enable=cfg.precommit_fast_index_enable,
                                            fast_index_cell_mm=cfg.precommit_fast_index_cell_mm,
                                        )
                                        # Local re-route of ripped net inside its previous window.
                                        var extra = cfg.ripup_extra_dist_cells
                                        if extra <= 0:
                                            extra = 20
                                        var bound = _bbox_expand(snap_bb, extra, width, height)
                                        var rr = _try_reroute_path_bounded(
                                            ws,
                                            g,
                                            cid,
                                            net_clearance_mm_by_spec[cid] if cid < len(net_clearance_mm_by_spec) else clearance_mm,
                                            net_names,
                                            net_ids,
                                            start_idxs,
                                            goal_idxs,
                                            track_width_mm,
                                            via_diameter_mm,
                                            via_drill_mm,
                                            uvia_diameter_mm,
                                            uvia_drill_mm,
                                            layers,
                                            resolution_mm,
                                            origin_x_mm,
                                            origin_y_mm,
                                            width,
                                            height,
                                            existing_vias_py,
                                            pad_stacks_py,
                                            allowed_mask_by_spec[cid],
                                            spacing,
                                            cfg,
                                            bound=bound,
                                            iter_tag=UInt64(0),
                                            seed_tag=UInt64(0x53484F5645),
                                            deadline_s=Float64(0.0),
                                            pre_db=pre_db,
                                            keepout_circles=keepout_circles,
                                            keepout_circle_net=keepout_circle_net,
                                            keepout_polygons=keepout_polygons,
                                            keepout_poly_net=keepout_poly_net,
                                            keepout_circle_mask=keepout_circle_mask,
                                            keepout_poly_mask=keepout_poly_mask,
                                            clearance_mm=clearance_mm,
                                            existing_via_any=existing_via_any,
                                            existing_via_seg=existing_via_seg,
                                        )
                                        if rr.ok:
                                            tracks_by_spec[cid] = rr.tracks
                                            vias_by_spec[cid] = rr.vias
                                            paths_by_spec[cid] = rr.path.copy()
                                            g.commit_path(net_ids[cid], rr.path.copy(), cfg.enforce_spacing, spacing)
                                            routed_state[cid] = 1
                                            if cfg.precommit_shorts_enable:
                                                _index_commit_tracks(
                                                    rr.tracks,
                                                    net_ids[cid],
                                                    layers,
                                                    pre_db.tracks,
                                                )
                                                if pre_db.track_index_enabled:
                                                    _index_commit_tracks_spatial(
                                                        rr.tracks,
                                                        net_ids[cid],
                                                        layers,
                                                        pre_db.track_index,
                                                    )
                                                _index_commit_vias(rr.vias, net_ids[cid], layers, pre_db.vias, clearance_mm)
                                            var bb2 = _bbox_from_path(rr.path, width, height)
                                            bbox_x0[cid] = bb2.x0
                                            bbox_y0[cid] = bb2.y0
                                            bbox_x1[cid] = bb2.x1
                                            bbox_y1[cid] = bb2.y1
                                        shove_rips += 1
                                        continue
                                attempt += 1
                                continue
                        tracks_by_spec[ni] = tv.tracks
                        vias_by_spec[ni] = tv.vias
                        if cfg.escape_commit_early and len(esc_path) > 0:
                            # Escape path already committed; only commit the global segment.
                            g.commit_path(net_id, gp, cfg.enforce_spacing, spacing)
                        else:
                            g.commit_path(net_id, path, cfg.enforce_spacing, spacing)
                        if cfg.precommit_shorts_enable:
                            _index_commit_tracks(
                                tv.tracks,
                                net_id,
                                layers,
                                pre_db.tracks,
                            )
                            _index_commit_vias(tv.vias, net_id, layers, pre_db.vias, clearance_mm)
                        paths_by_spec[ni] = path.copy()
                        var bb = _bbox_from_path(path, width, height)
                        bbox_x0[ni] = bb.x0
                        bbox_y0[ni] = bb.y0
                        bbox_x1[ni] = bb.x1
                        bbox_y1[ni] = bb.y1
                        routed_state[ni] = 1
                        margin = max_margin + 1
                        routed = True
                        if esc_exit_idx >= 0:
                            used_escape_exits_non_ncr.add(PythonObject(esc_exit_idx))
                        break
                    attempt += 1
                if routed:
                    break
                margin += margin_step
            if not routed and cfg.escape_commit_early and len(esc_path) > 0:
                g.uncommit_path(net_id, esc_path.copy(), cfg.enforce_spacing, spacing)

        # Simple negotiation: attempt to route failed nets by ripping up nearby routes.
        var failed_idxs = List[Int]()
        i = 0
        while i < n_nets:
            if routed_state[i] == 0:
                failed_idxs.append(i)
            i += 1
        if cfg.ripup_passes > 0 and len(failed_idxs) > 0:
            var rip_pass = 0
            while rip_pass < cfg.ripup_passes:
                if len(failed_idxs) == 0:
                    break
                var next_failed = List[Int]()
                for fid in failed_idxs:
                    if fid < 0 or fid >= n_nets:
                        continue
                    if routed_state[fid] == 1:
                        continue
                    var rip_margin = cfg.margin_init + (rip_pass * margin_step)
                    if rip_margin < cfg.margin_init:
                        rip_margin = cfg.margin_init
                    var target = _bbox_from_start_goal(
                        start_idxs[fid],
                        goal_idxs[fid],
                        width,
                        height,
                        rip_margin,
                    )
                    var candidates = List[Int]()
                    var cand_scores = List[Int]()
                    var oi = 0
                    var cx = (target.x0 + target.x1) // 2
                    var cy = (target.y0 + target.y1) // 2
                    while oi < len(order):
                        var rid = order[oi]
                        if rid != fid and routed_state[rid] == 1:
                            var bb = BBox(bbox_x0[rid], bbox_y0[rid], bbox_x1[rid], bbox_y1[rid])
                            if _bbox_intersects(bb, target):
                                candidates.append(rid)
                                # Prefer ripping routes that strongly overlap the target bbox.
                                var ix0 = bb.x0
                                if target.x0 > ix0:
                                    ix0 = target.x0
                                var iy0 = bb.y0
                                if target.y0 > iy0:
                                    iy0 = target.y0
                                var ix1 = bb.x1
                                if target.x1 < ix1:
                                    ix1 = target.x1
                                var iy1 = bb.y1
                                if target.y1 < iy1:
                                    iy1 = target.y1
                                var area = 0
                                if ix1 > ix0 and iy1 > iy0:
                                    area = (ix1 - ix0) * (iy1 - iy0)
                                cand_scores.append(area)
                        oi += 1
                    # If the overlap-only set is too small, optionally add nearest routes by bbox distance
                    # to the target center. This helps dense problems where bounding boxes may not
                    # intersect even though a reroute is necessary to open a corridor.
                    if cfg.ripup_extra_candidates > 0 and cfg.ripup_extra_dist_cells > 0:
                        var extra_ids = List[Int]()
                        var extra_scores = List[Int]()
                        oi = 0
                        while oi < len(order):
                            var rid = order[oi]
                            if rid != fid and routed_state[rid] == 1:
                                var bb = BBox(bbox_x0[rid], bbox_y0[rid], bbox_x1[rid], bbox_y1[rid])
                                if _bbox_intersects(bb, target):
                                    oi += 1
                                    continue
                                if bb.x0 < 0 or bb.y0 < 0 or bb.x1 < 0 or bb.y1 < 0:
                                    oi += 1
                                    continue
                                var dx = 0
                                if cx < bb.x0:
                                    dx = bb.x0 - cx
                                elif cx > bb.x1:
                                    dx = cx - bb.x1
                                var dy = 0
                                if cy < bb.y0:
                                    dy = bb.y0 - cy
                                elif cy > bb.y1:
                                    dy = cy - bb.y1
                                var dist = dx + dy
                                if dist <= cfg.ripup_extra_dist_cells:
                                    extra_ids.append(rid)
                                    # Score extras by negative distance (so closer is better, but below overlap hits).
                                    extra_scores.append(-dist)
                            oi += 1

                        # Sort extras by score (descending: 0, -1, -2 ...).
                        var esi = 1
                        while esi < len(extra_ids):
                            var cur_id = extra_ids[esi]
                            var cur_score = extra_scores[esi]
                            var esj = esi - 1
                            while esj >= 0 and extra_scores[esj] < cur_score:
                                extra_ids[esj + 1] = extra_ids[esj]
                                extra_scores[esj + 1] = extra_scores[esj]
                                esj -= 1
                            extra_ids[esj + 1] = cur_id
                            extra_scores[esj + 1] = cur_score
                            esi += 1

                        var take = cfg.ripup_extra_candidates
                        if take > len(extra_ids):
                            take = len(extra_ids)
                        var ei = 0
                        while ei < take:
                            candidates.append(extra_ids[ei])
                            cand_scores.append(extra_scores[ei])
                            ei += 1
                    if len(candidates) == 0:
                        next_failed.append(fid)
                        continue
                    if cfg.debug:
                        print("ripup fid", net_names[fid], "candidates", len(candidates), "pass", rip_pass)

                    # Sort candidates by overlap score (descending).
                    var si = 1
                    while si < len(candidates):
                        var cur_id = candidates[si]
                        var cur_score = cand_scores[si]
                        var sj = si - 1
                        while sj >= 0 and cand_scores[sj] < cur_score:
                            candidates[sj + 1] = candidates[sj]
                            cand_scores[sj + 1] = cand_scores[sj]
                            sj -= 1
                        candidates[sj + 1] = cur_id
                        cand_scores[sj + 1] = cur_score
                        si += 1

                    var max_rip = len(candidates)
                    if cfg.ripup_k > 0 and cfg.ripup_k < max_rip:
                        max_rip = cfg.ripup_k
                    # Later ripup passes can be more aggressive.
                    if rip_pass > 0:
                        var pass_rip = (rip_pass + 1) * max_rip
                        if pass_rip > len(candidates):
                            pass_rip = len(candidates)
                        max_rip = pass_rip

                    var solved = False
                    var rip_k = max_rip
                    if cfg.ripup_progressive:
                        rip_k = 4
                        if rip_k > max_rip:
                            rip_k = max_rip
                    while rip_k <= max_rip and not solved:
                        # Snapshot ripped routes so the attempt is atomic.
                        var snap_ids = List[Int]()
                        var snap_paths = List[List[Int]]()
                        var snap_tracks = List[PythonObject]()
                        var snap_vias = List[PythonObject]()
                        var snap_x0 = List[Int]()
                        var snap_y0 = List[Int]()
                        var snap_x1 = List[Int]()
                        var snap_y1 = List[Int]()

                        var ripped = List[Int]()
                        var ci = 0
                        while ci < rip_k:
                            var rid = candidates[ci]
                            ripped.append(rid)
                            if cfg.debug:
                                print("  rip", net_names[rid])
                            snap_ids.append(rid)
                            snap_paths.append(paths_by_spec[rid].copy())
                            snap_tracks.append(tracks_by_spec[rid])
                            snap_vias.append(vias_by_spec[rid])
                            snap_x0.append(bbox_x0[rid])
                            snap_y0.append(bbox_y0[rid])
                            snap_x1.append(bbox_x1[rid])
                            snap_y1.append(bbox_y1[rid])

                            g.uncommit_path(net_ids[rid], paths_by_spec[rid].copy(), cfg.enforce_spacing, spacing)
                            routed_state[rid] = 0
                            tracks_by_spec[rid] = py.none()
                            vias_by_spec[rid] = py.none()
                            paths_by_spec[rid] = List[Int]()
                            bbox_x0[rid] = -1
                            bbox_y0[rid] = -1
                            bbox_x1[rid] = -1
                            bbox_y1[rid] = -1
                            ci += 1

                        # Rebuild the precommit DB for this atomic attempt (after ripping).
                        _rebuild_precommit_db_inplace(
                            pre_db,
                            tracks_by_spec,
                            vias_by_spec,
                            routed_state,
                            net_ids,
                            layers,
                            clearance_mm,
                            origin_x_mm=origin_x_mm,
                            origin_y_mm=origin_y_mm,
                            board_w_mm=(Float64(width) * resolution_mm),
                            board_h_mm=(Float64(height) * resolution_mm),
                            fast_index_enable=cfg.precommit_fast_index_enable,
                            fast_index_cell_mm=cfg.precommit_fast_index_cell_mm,
                        )

                        # Route the failed net.
                        var net_name = net_names[fid]
                        var net_id = net_ids[fid]
                        var start_idx = start_idxs[fid]
                        var goal_idx = goal_idxs[fid]
                        var routed = False
                        var margin = cfg.margin_init
                        while margin <= max_margin and not routed:
                            var attempt = 0
                            while attempt < attempts:
                                var seed = cfg.seed ^ (UInt64(net_id) << UInt64(1)) ^ UInt64(attempt)
                                var path = route_a_star(
                                    ws,
                                    g,
                                    start_idx,
                                    goal_idx,
                                    net_id,
                                    seed,
                                    cfg.diagonal,
                                    cfg.via_penalty,
                                    cfg.layer_penalty_outer,
                                    cfg.layer_penalty_in1,
                                    cfg.layer_penalty_inner,
                                    margin,
                                    cfg.astar_max_expansions,
                                    cfg.heuristic_weight_pct,
                                    t0 + max_time_s if max_time_s > 0.0 else Float64(0.0),
                                    cfg.enforce_spacing,
                                    cfg.enforce_touch,
                                    cfg.ncr_allow_overlaps,
                                    cfg.spacing_present_cost,
                                    cfg.spacing_present_cap,
                                    UInt32(0),
                                    UInt32(0),
                                    False,
                                    existing_via_any,
                                    existing_via_seg,
                                    cfg.forbid_stacked_vias,
                                    allowed_mask_by_spec[fid],
                                )
                                if len(path) == 0 and cfg.shove_enable and len(layers) > 1:
                                    var s0 = idx_to_coords(start_idx, width, height)
                                    var alt_mask = allowed_mask_by_spec[fid] & (~(UInt32(1) << UInt32(s0.layer)))
                                    if alt_mask != UInt32(0):
                                        path = route_a_star(
                                            ws,
                                            g,
                                            start_idx,
                                            goal_idx,
                                            net_id,
                                            seed ^ UInt64(0xBEEF),
                                            cfg.diagonal,
                                            cfg.via_penalty,
                                            cfg.layer_penalty_outer,
                                            cfg.layer_penalty_in1,
                                            cfg.layer_penalty_inner,
                                            margin,
                                            cfg.astar_max_expansions,
                                            cfg.heuristic_weight_pct,
                                            t0 + max_time_s if max_time_s > 0.0 else Float64(0.0),
                                            cfg.enforce_spacing,
                                            cfg.enforce_touch,
                                            cfg.ncr_allow_overlaps,
                                            cfg.spacing_present_cost,
                                            cfg.spacing_present_cap,
                                            UInt32(0),
                                            UInt32(0),
                                            False,
                                            existing_via_any,
                                            existing_via_seg,
                                            cfg.forbid_stacked_vias,
                                            alt_mask,
                                        )
                                if len(path) > 0:
                                    if cfg.pull_tight_enable:
                                        path = _pull_tight_path(g, net_id, path, cfg.diagonal, cfg.enforce_touch, cfg.enforce_spacing)
                                    var tv = _path_to_tracks_and_vias(
                                        net_name,
                                        track_width_mm[fid],
                                        via_diameter_mm[fid],
                                        via_drill_mm[fid],
                                        uvia_diameter_mm[fid],
                                            uvia_drill_mm[fid],
                                            layers,
                                            resolution_mm,
                                            origin_x_mm,
                                            origin_y_mm,
                                            width,
                                            height,
                                            path,
                                            existing_vias_py,
                                            pad_stacks_py,
                                        )
                                    if cfg.precommit_drc_enable and _tracks_violate_keepouts(
                                        tv.tracks,
                                        keepout_circles,
                                        keepout_circle_net,
                                        keepout_polygons,
                                        keepout_poly_net,
                                        keepout_circle_mask,
                                        keepout_poly_mask,
                                        layers,
                                        clearance_mm,
                                        net_id,
                                    ):
                                        attempt += 1
                                        continue
                                    if cfg.precommit_shorts_enable and (
                                        _tracks_violate_shorts_or_clearance(
                                            tv.tracks,
                                            net_id,
                                            layers,
                                            pre_db.tracks,
                                            pre_db.vias,
                                            net_clearance_mm_by_spec[fid] if fid < len(net_clearance_mm_by_spec) else clearance_mm,
                                        )
                                        or _vias_violate_shorts_or_clearance(tv.vias, net_id, layers, pre_db.tracks, pre_db.vias, clearance_mm)
                                    ):
                                        attempt += 1
                                        continue
                                    tracks_by_spec[fid] = tv.tracks
                                    vias_by_spec[fid] = tv.vias
                                    g.commit_path(net_id, path, cfg.enforce_spacing, spacing)
                                    if cfg.precommit_shorts_enable:
                                        _index_commit_tracks(tv.tracks, net_id, layers, pre_db.tracks)
                                        _index_commit_vias(tv.vias, net_id, layers, pre_db.vias, clearance_mm)
                                    paths_by_spec[fid] = path.copy()
                                    var bb = _bbox_from_path(path, width, height)
                                    bbox_x0[fid] = bb.x0
                                    bbox_y0[fid] = bb.y0
                                    bbox_x1[fid] = bb.x1
                                    bbox_y1[fid] = bb.y1
                                    routed_state[fid] = 1
                                    routed = True
                                    if cfg.debug:
                                        print("  routed fid", net_names[fid], "path_len", len(path), "tracks", Int(py=tv.tracks.__len__()), "vias", Int(py=tv.vias.__len__()))
                                    break
                                attempt += 1
                            margin += margin_step

                        var ok_all = routed
                        if ok_all:
                            # Restore ripped routes.
                            for sid in ripped:
                                var s_net_name = net_names[sid]
                                var s_net_id = net_ids[sid]
                                var s_start_idx = start_idxs[sid]
                                var s_goal_idx = goal_idxs[sid]
                                var ok = False
                                var s_margin = cfg.margin_init
                                while s_margin <= max_margin and not ok:
                                    var attempt = 0
                                    while attempt < attempts:
                                        var seed = cfg.seed ^ (UInt64(s_net_id) << UInt64(1)) ^ UInt64(attempt)
                                        var path = route_a_star(
                                            ws,
                                            g,
                                            s_start_idx,
                                            s_goal_idx,
                                            s_net_id,
                                            seed,
                                            cfg.diagonal,
                                            cfg.via_penalty,
                                            cfg.layer_penalty_outer,
                                            cfg.layer_penalty_in1,
                                            cfg.layer_penalty_inner,
                                            s_margin,
                                            cfg.astar_max_expansions,
                                            cfg.heuristic_weight_pct,
                                            t0 + max_time_s if max_time_s > 0.0 else Float64(0.0),
                                            cfg.enforce_spacing,
                                            cfg.enforce_touch,
                                            cfg.ncr_allow_overlaps,
                                            cfg.spacing_present_cost,
                                            cfg.spacing_present_cap,
                                            UInt32(0),
                                            UInt32(0),
                                            False,
                                            existing_via_any,
                                            existing_via_seg,
                                            cfg.forbid_stacked_vias,
                                            allowed_mask_by_spec[sid],
                                        )
                                        if len(path) == 0 and cfg.shove_enable and len(layers) > 1:
                                            var s0 = idx_to_coords(s_start_idx, width, height)
                                            var alt_mask = allowed_mask_by_spec[sid] & (~(UInt32(1) << UInt32(s0.layer)))
                                            if alt_mask != UInt32(0):
                                                path = route_a_star(
                                                    ws,
                                                    g,
                                                    s_start_idx,
                                                    s_goal_idx,
                                                    s_net_id,
                                                    seed ^ UInt64(0xBEEF),
                                                    cfg.diagonal,
                                                    cfg.via_penalty,
                                                    cfg.layer_penalty_outer,
                                                    cfg.layer_penalty_in1,
                                                    cfg.layer_penalty_inner,
                                                    s_margin,
                                                    cfg.astar_max_expansions,
                                                    cfg.heuristic_weight_pct,
                                                    t0 + max_time_s if max_time_s > 0.0 else Float64(0.0),
                                                    cfg.enforce_spacing,
                                                    cfg.enforce_touch,
                                                    cfg.ncr_allow_overlaps,
                                                    cfg.spacing_present_cost,
                                                    cfg.spacing_present_cap,
                                                    UInt32(0),
                                                    UInt32(0),
                                                    False,
                                                    existing_via_any,
                                                    existing_via_seg,
                                                    cfg.forbid_stacked_vias,
                                            alt_mask,
                                        )
                                        if cfg.debug:
                                            print("    restore try", s_net_name, "attempt", attempt, "len", len(path))
                                        if len(path) > 0:
                                            if cfg.pull_tight_enable:
                                                path = _pull_tight_path(g, s_net_id, path, cfg.diagonal, cfg.enforce_touch, cfg.enforce_spacing)
                                            var tv = _path_to_tracks_and_vias(
                                                s_net_name,
                                                track_width_mm[sid],
                                                via_diameter_mm[sid],
                                                via_drill_mm[sid],
                                                uvia_diameter_mm[sid],
                                                    uvia_drill_mm[sid],
                                                    layers,
                                                    resolution_mm,
                                                    origin_x_mm,
                                                    origin_y_mm,
                                                    width,
                                                    height,
                                                    path,
                                                    existing_vias_py,
                                                    pad_stacks_py,
                                                )
                                            if cfg.precommit_drc_enable and _tracks_violate_keepouts(
                                                tv.tracks,
                                                keepout_circles,
                                                keepout_circle_net,
                                                keepout_polygons,
                                                keepout_poly_net,
                                                keepout_circle_mask,
                                                keepout_poly_mask,
                                                layers,
                                                clearance_mm,
                                                s_net_id,
                                            ):
                                                attempt += 1
                                                continue
                                            if cfg.precommit_shorts_enable:
                                                var culprit = _tracks_first_conflict_net(
                                                    tv.tracks,
                                                    s_net_id,
                                                    layers,
                                                    pre_db.tracks,
                                                    pre_db.vias,
                                                    net_clearance_mm_by_spec[sid] if sid < len(net_clearance_mm_by_spec) else clearance_mm,
                                                    track_index_enabled=pre_db.track_index_enabled,
                                                    track_index=pre_db.track_index,
                                                )
                                                if culprit == UInt32(0):
                                                    culprit = _vias_first_conflict_net(tv.vias, s_net_id, layers, pre_db.tracks, pre_db.vias, clearance_mm)
                                                if culprit != UInt32(0):
                                                    if cfg.ncr_history_inc != UInt16(0):
                                                        _ = g.update_history_for_path(s_net_id, path.copy(), cfg.ncr_history_inc)
                                                    if cfg.debug:
                                                        print("    restore conflict", s_net_name, "with", culprit)
                                                    attempt += 1
                                                    continue
                                            tracks_by_spec[sid] = tv.tracks
                                            vias_by_spec[sid] = tv.vias
                                            g.commit_path(s_net_id, path, cfg.enforce_spacing, spacing)
                                            if cfg.precommit_shorts_enable:
                                                _index_commit_tracks(
                                                    tv.tracks,
                                                    s_net_id,
                                                    layers,
                                                    pre_db.tracks,
                                                )
                                                _index_commit_vias(tv.vias, s_net_id, layers, pre_db.vias, clearance_mm)
                                            paths_by_spec[sid] = path.copy()
                                            var bb = _bbox_from_path(path, width, height)
                                            bbox_x0[sid] = bb.x0
                                            bbox_y0[sid] = bb.y0
                                            bbox_x1[sid] = bb.x1
                                            bbox_y1[sid] = bb.y1
                                            routed_state[sid] = 1
                                            ok = True
                                            break
                                        attempt += 1
                                    s_margin += margin_step
                                if not ok:
                                    if cfg.debug:
                                        print("  failed restore", net_names[sid])
                                    ok_all = False
                                    break

                        if ok_all:
                            solved = True
                            break

                        # Roll back: uncommit any new routes and restore snapshots.
                        if routed_state[fid] == 1 and len(paths_by_spec[fid]) > 0:
                            g.uncommit_path(net_ids[fid], paths_by_spec[fid].copy(), cfg.enforce_spacing, spacing)
                        routed_state[fid] = 0
                        tracks_by_spec[fid] = py.none()
                        vias_by_spec[fid] = py.none()
                        paths_by_spec[fid] = List[Int]()
                        bbox_x0[fid] = -1
                        bbox_y0[fid] = -1
                        bbox_x1[fid] = -1
                        bbox_y1[fid] = -1

                        for sid in ripped:
                            if routed_state[sid] == 1 and len(paths_by_spec[sid]) > 0:
                                g.uncommit_path(net_ids[sid], paths_by_spec[sid].copy(), cfg.enforce_spacing, spacing)
                            routed_state[sid] = 0
                            tracks_by_spec[sid] = py.none()
                            vias_by_spec[sid] = py.none()
                            paths_by_spec[sid] = List[Int]()
                            bbox_x0[sid] = -1
                            bbox_y0[sid] = -1
                            bbox_x1[sid] = -1
                            bbox_y1[sid] = -1

                        var ri = 0
                        while ri < len(snap_ids):
                            var rid = snap_ids[ri]
                            var p = snap_paths[ri].copy()
                            g.commit_path(net_ids[rid], p, cfg.enforce_spacing, spacing)
                            routed_state[rid] = 1
                            tracks_by_spec[rid] = snap_tracks[ri]
                            vias_by_spec[rid] = snap_vias[ri]
                            paths_by_spec[rid] = p.copy()
                            bbox_x0[rid] = snap_x0[ri]
                            bbox_y0[rid] = snap_y0[ri]
                            bbox_x1[rid] = snap_x1[ri]
                            bbox_y1[rid] = snap_y1[ri]
                            ri += 1
                        _rebuild_precommit_db_inplace(
                            pre_db,
                            tracks_by_spec,
                            vias_by_spec,
                            routed_state,
                            net_ids,
                            layers,
                            clearance_mm,
                            origin_x_mm=origin_x_mm,
                            origin_y_mm=origin_y_mm,
                            board_w_mm=(Float64(width) * resolution_mm),
                            board_h_mm=(Float64(height) * resolution_mm),
                            fast_index_enable=cfg.precommit_fast_index_enable,
                            fast_index_cell_mm=cfg.precommit_fast_index_cell_mm,
                        )

                        if not cfg.ripup_progressive:
                            break
                        if rip_k == max_rip:
                            break
                        var next_k = rip_k * 2
                        if next_k <= rip_k:
                            next_k = rip_k + 1
                        if next_k > max_rip:
                            next_k = max_rip
                        rip_k = next_k

                    if not solved:
                        next_failed.append(fid)
                # Dedup without relying on stdlib sorting.
                var mark = List[UInt16](length=n_nets, fill=UInt16(0))
                var dedup = List[Int]()
                for x in next_failed:
                    if x < 0 or x >= n_nets:
                        continue
                    if mark[x] == UInt16(0):
                        mark[x] = UInt16(1)
                        dedup.append(x)
                failed_idxs = dedup^
                rip_pass += 1

    # Flatten per-net routes into the output schema.
    var out_tracks = py.list()
    var out_vias = py.list()
    var fail_map = py.dict()

    i = 0
    while i < n_nets:
        if routed_state[i] == 1:
            for t in tracks_by_spec[i]:
                out_tracks.append(t)
            for v in vias_by_spec[i]:
                out_vias.append(v)
        else:
            fail_map[PythonObject(net_names[i])] = PythonObject(Int(1))
        i += 1

    var failed = py.list()
    for k in fail_map:
        failed.append(k)

    var payload = py.dict()
    payload[PythonObject(String("backend"))] = PythonObject(String("pardal_router_mojo"))
    payload[PythonObject(String("problem"))] = PythonObject(problem_path)
    payload[PythonObject(String("tracks"))] = out_tracks
    payload[PythonObject(String("vias"))] = out_vias
    payload[PythonObject(String("failed_nets"))] = failed

    var json = py.import_module("json")
    var pathlib = py.import_module("pathlib")
    var txt = json.dumps(payload, indent=PythonObject(Int(2)))
    pathlib.Path(PythonObject(routes_path)).write_text(txt)
