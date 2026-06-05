from collections import List

from time import perf_counter

from .grid import Grid
from .heap import MinHeap


fn _now_s() -> Float64:
    return perf_counter()


fn abs_i(a: Int) -> Int:
    return a if a >= 0 else -a


struct Coords:
    var layer: Int
    var x: Int
    var y: Int

    fn __init__(out self, layer: Int, x: Int, y: Int):
        self.layer = layer
        self.x = x
        self.y = y


fn idx_to_coords(idx: Int, width: Int, height: Int) -> Coords:
    var layer = idx // (width * height)
    var rem = idx - layer * (width * height)
    var y = rem // width
    var x = rem - y * width
    return Coords(layer, x, y)


struct AStarWorkspace:
    var n: Int
    var gen: UInt32
    var seen: List[UInt32]
    var g_score: List[UInt32]
    var prev: List[Int]
    var heap: MinHeap

    fn __init__(out self, n: Int):
        self.n = n
        self.gen = UInt32(1)
        self.seen = List[UInt32](length=n, fill=UInt32(0))
        self.g_score = List[UInt32](length=n, fill=UInt32(0))
        self.prev = List[Int](length=n, fill=-1)
        self.heap = MinHeap()

    fn reset(mut self):
        self.gen = self.gen + UInt32(1)
        if self.gen == UInt32(0):
            # Wraparound: clear the seen map.
            self.seen = List[UInt32](length=self.n, fill=UInt32(0))
            self.gen = UInt32(1)
        self.heap.clear()

    fn get_g(self, idx: Int, inf: UInt32) -> UInt32:
        if idx < 0 or idx >= self.n:
            return inf
        if self.seen[idx] != self.gen:
            return inf
        return self.g_score[idx]

    fn set_g(mut self, idx: Int, g: UInt32, prev_idx: Int):
        self.seen[idx] = self.gen
        self.g_score[idx] = g
        self.prev[idx] = prev_idx

    fn get_prev(self, idx: Int) -> Int:
        if idx < 0 or idx >= self.n:
            return -1
        if self.seen[idx] != self.gen:
            return -1
        return self.prev[idx]


fn heuristic_idx(
    a_idx: Int,
    b_layer: Int,
    b_x: Int,
    b_y: Int,
    width: Int,
    height: Int,
    via_penalty: UInt32,
) -> UInt32:
    var a = idx_to_coords(a_idx, width, height)
    var dx = UInt32(abs_i(a.x - b_x))
    var dy = UInt32(abs_i(a.y - b_y))
    var dl = UInt32(abs_i(a.layer - b_layer))
    return dx + dy + dl * via_penalty


fn layer_penalty_for_layer(
    layer: Int,
    layers: Int,
    layer_penalty_outer: UInt32,
    layer_penalty_in1: UInt32,
    layer_penalty_inner: UInt32,
) -> UInt32:
    if layers <= 1:
        return UInt32(0)
    if layer <= 0 or layer >= (layers - 1):
        return layer_penalty_outer
    var d = layer
    var d2 = (layers - 1) - layer
    if d2 < d:
        d = d2
    if d <= 1:
        return layer_penalty_in1
    return layer_penalty_inner


fn reconstruct_path(prev: List[Int], start_idx: Int, goal_idx: Int) -> List[Int]:
    var out = List[Int]()
    var cur = goal_idx
    while True:
        out.append(cur)
        if cur == start_idx:
            break
        var p = prev[cur]
        if p == -1:
            return List[Int]()  # unreachable
        cur = p
    out.reverse()
    return out^


fn route_a_star(
    mut ws: AStarWorkspace,
    grid: Grid,
    start_idx: Int,
    goal_idx: Int,
    net_id: UInt32,
    seed: UInt64,
    diagonal: Bool,
    via_penalty: UInt32,
    layer_penalty_outer: UInt32,
    layer_penalty_in1: UInt32,
    layer_penalty_inner: UInt32,
    margin: Int,
    max_expansions: UInt32,
    heuristic_weight_pct: UInt32,
    deadline_s: Float64,
    enforce_spacing: Bool,
    enforce_touch: Bool,
    ncr_allow_overlaps: Bool,
    spacing_present_cost: UInt32,
    spacing_present_cap: UInt16,
    present_cost: UInt32,
    history_cost: UInt32,
    ignore_congestion: Bool,
    existing_via_any: List[UInt32],
    existing_via_seg: List[UInt32],
    forbid_stacked_vias: Bool,
    allowed_layers_mask: UInt32,
) raises -> List[Int]:
    var n = grid.layers * grid.width * grid.height
    if start_idx < 0 or start_idx >= n:
        return List[Int]()
    if goal_idx < 0 or goal_idx >= n:
        return List[Int]()

    # Bounding box restriction in x/y only (layer unrestricted).
    var start = idx_to_coords(start_idx, grid.width, grid.height)
    var goal = idx_to_coords(goal_idx, grid.width, grid.height)
    var raw_mask = allowed_layers_mask
    var mask = raw_mask
    var via_mask = raw_mask
    # Split-mask encoding (router side):
    # - low 16 bits: track-layer mask
    # - high 16 bits: via-endpoint-layer mask
    # If high-half is zero, keep legacy single-mask behavior.
    if grid.layers <= 16:
        var lo = raw_mask & UInt32(0x0000_FFFF)
        var hi = (raw_mask >> UInt32(16)) & UInt32(0x0000_FFFF)
        if hi != UInt32(0):
            mask = lo
            via_mask = hi
    if mask == UInt32(0):
        var m = UInt32(0)
        var li = 0
        while li < grid.layers and li < 32:
            m = m | (UInt32(1) << UInt32(li))
            li += 1
        mask = m
    if via_mask == UInt32(0):
        via_mask = mask
    if (mask & (UInt32(1) << UInt32(start.layer))) == UInt32(0):
        return List[Int]()
    if (mask & (UInt32(1) << UInt32(goal.layer))) == UInt32(0):
        return List[Int]()
    var x0 = max(min(start.x, goal.x) - margin, 0)
    var y0 = max(min(start.y, goal.y) - margin, 0)
    var x1 = min(max(start.x, goal.x) + margin, grid.width - 1)
    var y1 = min(max(start.y, goal.y) + margin, grid.height - 1)

    var inf = UInt32(0xFFFF_FFFF)
    if ws.n != n:
        ws = AStarWorkspace(n)
    ws.reset()
    ws.set_g(start_idx, UInt32(0), start_idx)
    var h0 = heuristic_idx(
        start_idx,
        goal.layer,
        goal.x,
        goal.y,
        grid.width,
        grid.height,
        via_penalty,
    )
    var w = heuristic_weight_pct
    var f0 = UInt32(0) + UInt32((UInt64(h0) * UInt64(w)) // UInt64(100))
    ws.heap.push(f0, UInt32(0), start_idx)

    var dxs: List[Int] = [1, 0, -1, 0]
    var dys: List[Int] = [0, 1, 0, -1]
    if diagonal:
        dxs = [1, 0, -1, 0, 1, -1, 1, -1]
        dys = [0, 1, 0, -1, 1, 1, -1, -1]

    var n_dirs = len(dxs)
    var rot = Int(seed % UInt64(n_dirs)) if n_dirs > 0 else 0
    var reverse = (seed & UInt64(8)) != UInt64(0)
    var xy_len = grid.width * grid.height
    var seg_len = (grid.layers - 1) * xy_len
    var expansions = UInt32(0)

    while not ws.heap.is_empty():
        expansions = expansions + UInt32(1)
        # Deadline checks must be frequent enough to cap worst-case runtime on
        # large boards. Coarse checks can miss a 60s wall budget by minutes if
        # each expansion is expensive (touch/spacing/history queries).
        if deadline_s > 0.0 and (expansions & UInt32(0x00FF)) == UInt32(0):
            if _now_s() > deadline_s:
                return List[Int]()
        if max_expansions != UInt32(0) and expansions > max_expansions:
            return List[Int]()
        var cur = ws.heap.pop_min()
        var cur_g = cur.g
        var cur_idx = cur.idx
        if cur_idx == goal_idx:
            var out = List[Int]()
            var curp = goal_idx
            while True:
                out.append(curp)
                if curp == start_idx:
                    break
                var p = ws.get_prev(curp)
                if p == -1:
                    return List[Int]()
                curp = p
            out.reverse()
            return out^

        var c = idx_to_coords(cur_idx, grid.width, grid.height)
        var cur_layer = c.layer
        var cx = c.x
        var cy = c.y
        var xy = cy * grid.width + cx
        if (mask & (UInt32(1) << UInt32(cur_layer))) == UInt32(0):
            continue

        if cx < x0 or cx > x1 or cy < y0 or cy > y1:
            continue

        var best_g = ws.get_g(cur_idx, inf)
        if cur_g != best_g:
            continue

        # In-layer moves (respect allowed-layers mask).
        if (mask & (UInt32(1) << UInt32(cur_layer))) != UInt32(0):
            var i = 0
            while i < n_dirs:
                var ii = 0
                if not reverse:
                    ii = (i + rot) % n_dirs
                else:
                    ii = (rot + (n_dirs - 1 - i)) % n_dirs
                var nx = cx + dxs[ii]
                var ny = cy + dys[ii]
                if nx < x0 or nx > x1 or ny < y0 or ny > y1:
                    i += 1
                    continue
                if not grid.in_bounds(cur_layer, nx, ny):
                    i += 1
                    continue
                # Prevent diagonal corner-cutting: for a diagonal step, require both adjacent
                # orthogonal cells to be legal too. This avoids KiCad "tracks_crossing" and
                # diagonal-overlap artifacts.
                if diagonal and abs_i(dxs[ii]) == 1 and abs_i(dys[ii]) == 1:
                    var ox1 = nx
                    var oy1 = cy
                    var ox2 = cx
                    var oy2 = ny
                    if not grid.in_bounds(cur_layer, ox1, oy1) or not grid.in_bounds(
                        cur_layer, ox2, oy2
                    ):
                        i += 1
                        continue
                    if not grid.base_allows(
                        cur_layer, ox1, oy1, net_id
                    ) or not grid.base_allows(cur_layer, ox2, oy2, net_id):
                        i += 1
                        continue
                    var oidx1 = grid.idx(cur_layer, ox1, oy1)
                    var oidx2 = grid.idx(cur_layer, ox2, oy2)
                    if (
                        grid.occ_other_at_idx(oidx1, net_id) != UInt16(0)
                        or grid.occ_other_at_idx(oidx2, net_id) != UInt16(0)
                    ):
                        # Keep diagonal corner occupancy as a hard block even in
                        # overlap mode. Allowing this creates many KiCad
                        # tracks_crossing violations that postroute cleanup does
                        # not reliably remove.
                        i += 1
                        continue
                    if enforce_touch and (
                        grid.touch_track_other_at_idx(oidx1, net_id) != UInt16(0)
                        or grid.touch_track_other_at_idx(oidx2, net_id) != UInt16(0)
                        or grid.touch_via_other_at_idx(oidx1, net_id) != UInt16(0)
                        or grid.touch_via_other_at_idx(oidx2, net_id) != UInt16(0)
                    ):
                        if not ncr_allow_overlaps:
                            i += 1
                            continue
                    if enforce_spacing and (
                        grid.ko_track_other_at_idx(oidx1, net_id) != UInt16(0)
                        or grid.ko_track_other_at_idx(oidx2, net_id) != UInt16(0)
                        or grid.ko_via_other_at_idx(oidx1, net_id) != UInt16(0)
                        or grid.ko_via_other_at_idx(oidx2, net_id) != UInt16(0)
                    ):
                        if not ncr_allow_overlaps:
                            i += 1
                            continue
                if not grid.base_allows(cur_layer, nx, ny, net_id):
                    i += 1
                    continue

                var ni = grid.idx(cur_layer, nx, ny)
                # In NCR mode, allow overlaps with a cost (PathFinder-style).
                if grid.occ_other_at_idx(ni, net_id) != UInt16(0):
                    if not ncr_allow_overlaps:
                        i += 1
                        continue
                var spacing_penalty = UInt32(0)
                if enforce_touch:
                    if (
                        grid.touch_track_other_at_idx(ni, net_id) != UInt16(0)
                        or grid.touch_via_other_at_idx(ni, net_id) != UInt16(0)
                    ):
                        if not ncr_allow_overlaps:
                            i += 1
                            continue
                if enforce_spacing:
                    if not ncr_allow_overlaps:
                        if (
                            grid.ko_track_other_at_idx(ni, net_id) != UInt16(0)
                            or grid.ko_via_other_at_idx(ni, net_id) != UInt16(0)
                        ):
                            i += 1
                            continue
                    else:
                        var k = grid.ko_track_other_at_idx(ni, net_id)
                        var t = grid.touch_track_other_at_idx(ni, net_id)
                        if grid.touch_via_other_at_idx(ni, net_id) > t:
                            t = grid.touch_via_other_at_idx(ni, net_id)
                        if k > spacing_present_cap:
                            k = spacing_present_cap
                        if t > spacing_present_cap:
                            t = spacing_present_cap
                        spacing_penalty = UInt32(k + t) * spacing_present_cost
                var step = UInt32(1) + layer_penalty_for_layer(
                    cur_layer,
                    grid.layers,
                    layer_penalty_outer,
                    layer_penalty_in1,
                    layer_penalty_inner,
                )
                var extra = grid.step_cost(
                    ni, net_id, present_cost, history_cost, ignore_congestion
                )
                var ng = best_g + step + extra + spacing_penalty
                if ng < ws.get_g(ni, inf):
                    ws.set_g(ni, ng, cur_idx)
                    var h = heuristic_idx(
                        ni,
                        goal.layer,
                        goal.x,
                        goal.y,
                        grid.width,
                        grid.height,
                        via_penalty,
                    )
                    var f = ng + UInt32((UInt64(h) * UInt64(w)) // UInt64(100))
                    ws.heap.push(f, ng, ni)
                i += 1

        # Via transitions (nearest allowed layers; can skip masked internal layers).
        if via_penalty > 0:
            # A via occupies copper on both layers. We must ensure the current cell is
            # also base-legal, not just the destination layer; otherwise the search can
            # emit vias that overlap fixed copper on the current layer (KiCad DRC).
            if not grid.base_allows(cur_layer, cx, cy, net_id):
                continue
            if (via_mask & (UInt32(1) << UInt32(cur_layer))) == UInt32(0):
                continue
            var nl0 = cur_layer - 1
            while nl0 >= 0 and (via_mask & (UInt32(1) << UInt32(nl0))) == UInt32(0):
                nl0 -= 1
            if nl0 >= 0 and (via_mask & (UInt32(1) << UInt32(nl0))) != UInt32(0):
                if grid.base_allows(nl0, cx, cy, net_id):
                    var ni0 = grid.idx(nl0, cx, cy)
                    if (
                        grid.occ_other_at_idx(ni0, net_id) == UInt16(0)
                        or (ncr_allow_overlaps and (not forbid_stacked_vias))
                    ):
                        var ok0 = True
                        var spacing_penalty0 = UInt32(0)
                        var stack_ext_penalty0 = UInt32(0)
                        if (
                            forbid_stacked_vias
                            and len(existing_via_any) == xy_len
                            and existing_via_any[xy] == net_id
                        ):
                            var bi0 = nl0 * xy_len + xy
                            var seg_ok = (
                                len(existing_via_seg) == seg_len
                                and bi0 >= 0
                                and bi0 < len(existing_via_seg)
                                and existing_via_seg[bi0] == net_id
                            )
                            if not seg_ok:
                                var ext_ok = False
                                if len(existing_via_seg) == seg_len:
                                    var bi_dn = bi0 - xy_len
                                    var bi_up = bi0 + xy_len
                                    if bi_dn >= 0 and bi_dn < len(existing_via_seg) and existing_via_seg[bi_dn] == net_id:
                                        ext_ok = True
                                    if bi_up >= 0 and bi_up < len(existing_via_seg) and existing_via_seg[bi_up] == net_id:
                                        ext_ok = True
                                if not ext_ok:
                                    ok0 = False
                                else:
                                    stack_ext_penalty0 = via_penalty * UInt32(4)
                        if (
                            forbid_stacked_vias
                            and len(existing_via_any) == xy_len
                            and existing_via_any[xy] != UInt32(0)
                            and existing_via_any[xy] != net_id
                        ):
                            ok0 = False
                        var idx0 = grid.idx(cur_layer, cx, cy)
                        var idx1 = ni0
                        if enforce_touch:
                            var tv0 = grid.touch_via_other_at_idx(idx0, net_id)
                            var tv1 = grid.touch_via_other_at_idx(idx1, net_id)
                            var tt0 = grid.touch_track_other_at_idx(idx0, net_id)
                            var tt1 = grid.touch_track_other_at_idx(idx1, net_id)
                            if tv0 != UInt16(0) or tv1 != UInt16(0) or tt0 != UInt16(0) or tt1 != UInt16(0):
                                if (not ncr_allow_overlaps) or forbid_stacked_vias:
                                    ok0 = False
                                elif not enforce_spacing:
                                    var t0 = tv0
                                    var t1 = tv1
                                    if tt0 > t0:
                                        t0 = tt0
                                    if tt1 > t1:
                                        t1 = tt1
                                    var t = t0
                                    if t1 > t:
                                        t = t1
                                    if t > UInt16(spacing_present_cap):
                                        t = UInt16(spacing_present_cap)
                                    spacing_penalty0 = UInt32(t) * spacing_present_cost
                        if enforce_spacing:
                            if ok0:
                                var using_existing0 = (
                                    grid.via_usage[idx0] != UInt16(0)
                                    and grid.via_owner[idx0] == net_id
                                    and grid.via_usage[idx1] != UInt16(0)
                                    and grid.via_owner[idx1] == net_id
                                )
                                var k0 = grid.ko_via_other_at_idx(idx0, net_id)
                                var k1 = grid.ko_via_other_at_idx(idx1, net_id)
                                # When preventing stacked vias, also enforce via keepouts against
                                # already-committed vias of the same net (hole-to-hole spacing).
                                if forbid_stacked_vias and not using_existing0:
                                    k0 = grid.ko_via[idx0]
                                    k1 = grid.ko_via[idx1]
                                if not ncr_allow_overlaps:
                                    if k0 != UInt16(0) or k1 != UInt16(0):
                                        ok0 = False
                                    if (
                                        grid.ko_track_other_at_idx(idx0, net_id)
                                        != UInt16(0)
                                        or grid.ko_track_other_at_idx(idx1, net_id)
                                        != UInt16(0)
                                    ):
                                        ok0 = False
                                else:
                                    if forbid_stacked_vias:
                                        if (
                                            k0 != UInt16(0)
                                            or k1 != UInt16(0)
                                            or grid.ko_track_other_at_idx(idx0, net_id) != UInt16(0)
                                            or grid.ko_track_other_at_idx(idx1, net_id) != UInt16(0)
                                        ):
                                            ok0 = False
                                    else:
                                        var k = UInt32(k0) + UInt32(k1)
                                        if k > UInt32(spacing_present_cap):
                                            k = UInt32(spacing_present_cap)
                                        var t = UInt32(0)
                                        var tv0 = grid.touch_via_other_at_idx(idx0, net_id)
                                        var tv1 = grid.touch_via_other_at_idx(idx1, net_id)
                                        var tt0 = grid.touch_track_other_at_idx(idx0, net_id)
                                        var tt1 = grid.touch_track_other_at_idx(idx1, net_id)
                                        if tv0 < tt0:
                                            tv0 = tt0
                                        if tv1 < tt1:
                                            tv1 = tt1
                                        if tv0 > tv1:
                                            t = UInt32(tv0)
                                        else:
                                            t = UInt32(tv1)
                                        if t > UInt32(spacing_present_cap):
                                            t = UInt32(spacing_present_cap)
                                        spacing_penalty0 = (k + t) * spacing_present_cost
                        if ok0:
                            var extra0 = grid.step_cost(
                                ni0,
                                net_id,
                                present_cost,
                                history_cost,
                                ignore_congestion,
                            )
                            var ng0 = best_g + via_penalty + extra0 + spacing_penalty0
                            ng0 = ng0 + stack_ext_penalty0
                            if ng0 < ws.get_g(ni0, inf):
                                ws.set_g(ni0, ng0, cur_idx)
                                var h0 = heuristic_idx(
                                    ni0,
                                    goal.layer,
                                    goal.x,
                                    goal.y,
                                    grid.width,
                                    grid.height,
                                    via_penalty,
                                )
                                var f0 = ng0 + UInt32(
                                    (UInt64(h0) * UInt64(w)) // UInt64(100)
                                )
                                ws.heap.push(f0, ng0, ni0)
            var nl1 = cur_layer + 1
            while nl1 < grid.layers and (via_mask & (UInt32(1) << UInt32(nl1))) == UInt32(0):
                nl1 += 1
            if nl1 < grid.layers and (via_mask & (UInt32(1) << UInt32(nl1))) != UInt32(0):
                if grid.base_allows(nl1, cx, cy, net_id):
                    var ni1 = grid.idx(nl1, cx, cy)
                    if (
                        grid.occ_other_at_idx(ni1, net_id) == UInt16(0)
                        or (ncr_allow_overlaps and (not forbid_stacked_vias))
                    ):
                        var ok1 = True
                        var spacing_penalty1 = UInt32(0)
                        var stack_ext_penalty1 = UInt32(0)
                        if (
                            forbid_stacked_vias
                            and len(existing_via_any) == xy_len
                            and existing_via_any[xy] == net_id
                        ):
                            var bi1 = cur_layer * xy_len + xy
                            var seg_ok = (
                                len(existing_via_seg) == seg_len
                                and bi1 >= 0
                                and bi1 < len(existing_via_seg)
                                and existing_via_seg[bi1] == net_id
                            )
                            if not seg_ok:
                                var ext_ok = False
                                if len(existing_via_seg) == seg_len:
                                    var bi_dn = bi1 - xy_len
                                    var bi_up = bi1 + xy_len
                                    if bi_dn >= 0 and bi_dn < len(existing_via_seg) and existing_via_seg[bi_dn] == net_id:
                                        ext_ok = True
                                    if bi_up >= 0 and bi_up < len(existing_via_seg) and existing_via_seg[bi_up] == net_id:
                                        ext_ok = True
                                if not ext_ok:
                                    ok1 = False
                                else:
                                    stack_ext_penalty1 = via_penalty * UInt32(4)
                        if (
                            forbid_stacked_vias
                            and len(existing_via_any) == xy_len
                            and existing_via_any[xy] != UInt32(0)
                            and existing_via_any[xy] != net_id
                        ):
                            ok1 = False
                        var idx0 = grid.idx(cur_layer, cx, cy)
                        var idx1 = ni1
                        if enforce_touch:
                            var tv0 = grid.touch_via_other_at_idx(idx0, net_id)
                            var tv1 = grid.touch_via_other_at_idx(idx1, net_id)
                            var tt0 = grid.touch_track_other_at_idx(idx0, net_id)
                            var tt1 = grid.touch_track_other_at_idx(idx1, net_id)
                            if tv0 != UInt16(0) or tv1 != UInt16(0) or tt0 != UInt16(0) or tt1 != UInt16(0):
                                if (not ncr_allow_overlaps) or forbid_stacked_vias:
                                    ok1 = False
                                elif not enforce_spacing:
                                    var t0 = tv0
                                    var t1 = tv1
                                    if tt0 > t0:
                                        t0 = tt0
                                    if tt1 > t1:
                                        t1 = tt1
                                    var t = t0
                                    if t1 > t:
                                        t = t1
                                    if t > UInt16(spacing_present_cap):
                                        t = UInt16(spacing_present_cap)
                                    spacing_penalty1 = UInt32(t) * spacing_present_cost
                        if enforce_spacing:
                            if ok1:
                                var using_existing1 = (
                                    grid.via_usage[idx0] != UInt16(0)
                                    and grid.via_owner[idx0] == net_id
                                    and grid.via_usage[idx1] != UInt16(0)
                                    and grid.via_owner[idx1] == net_id
                                )
                                var k0 = grid.ko_via_other_at_idx(idx0, net_id)
                                var k1 = grid.ko_via_other_at_idx(idx1, net_id)
                                if forbid_stacked_vias and not using_existing1:
                                    k0 = grid.ko_via[idx0]
                                    k1 = grid.ko_via[idx1]
                                if not ncr_allow_overlaps:
                                    if k0 != UInt16(0) or k1 != UInt16(0):
                                        ok1 = False
                                    if (
                                        grid.ko_track_other_at_idx(idx0, net_id)
                                        != UInt16(0)
                                        or grid.ko_track_other_at_idx(idx1, net_id)
                                        != UInt16(0)
                                    ):
                                        ok1 = False
                                else:
                                    if forbid_stacked_vias:
                                        if (
                                            k0 != UInt16(0)
                                            or k1 != UInt16(0)
                                            or grid.ko_track_other_at_idx(idx0, net_id) != UInt16(0)
                                            or grid.ko_track_other_at_idx(idx1, net_id) != UInt16(0)
                                        ):
                                            ok1 = False
                                    else:
                                        var k = UInt32(k0) + UInt32(k1)
                                        if k > UInt32(spacing_present_cap):
                                            k = UInt32(spacing_present_cap)
                                        var t = UInt32(0)
                                        var tv0 = grid.touch_via_other_at_idx(idx0, net_id)
                                        var tv1 = grid.touch_via_other_at_idx(idx1, net_id)
                                        var tt0 = grid.touch_track_other_at_idx(idx0, net_id)
                                        var tt1 = grid.touch_track_other_at_idx(idx1, net_id)
                                        if tv0 < tt0:
                                            tv0 = tt0
                                        if tv1 < tt1:
                                            tv1 = tt1
                                        if tv0 > tv1:
                                            t = UInt32(tv0)
                                        else:
                                            t = UInt32(tv1)
                                        if t > UInt32(spacing_present_cap):
                                            t = UInt32(spacing_present_cap)
                                        spacing_penalty1 = (k + t) * spacing_present_cost
                        if ok1:
                            var extra1 = grid.step_cost(
                                ni1,
                                net_id,
                                present_cost,
                                history_cost,
                                ignore_congestion,
                            )
                            var ng1 = best_g + via_penalty + extra1 + spacing_penalty1
                            ng1 = ng1 + stack_ext_penalty1
                            if ng1 < ws.get_g(ni1, inf):
                                ws.set_g(ni1, ng1, cur_idx)
                                var h1 = heuristic_idx(
                                    ni1,
                                    goal.layer,
                                    goal.x,
                                    goal.y,
                                    grid.width,
                                    grid.height,
                                    via_penalty,
                                )
                                var f1 = ng1 + UInt32(
                                    (UInt64(h1) * UInt64(w)) // UInt64(100)
                                )
                                ws.heap.push(f1, ng1, ni1)
    return List[Int]()


fn route_a_star_bounded(
    mut ws: AStarWorkspace,
    grid: Grid,
    start_idx: Int,
    goal_idx: Int,
    net_id: UInt32,
    seed: UInt64,
    diagonal: Bool,
    via_penalty: UInt32,
    layer_penalty_outer: UInt32,
    layer_penalty_in1: UInt32,
    layer_penalty_inner: UInt32,
    bound_x0: Int,
    bound_y0: Int,
    bound_x1: Int,
    bound_y1: Int,
    max_expansions: UInt32,
    heuristic_weight_pct: UInt32,
    deadline_s: Float64,
    enforce_spacing: Bool,
    enforce_touch: Bool,
    ncr_allow_overlaps: Bool,
    spacing_present_cost: UInt32,
    spacing_present_cap: UInt16,
    present_cost: UInt32,
    history_cost: UInt32,
    ignore_congestion: Bool,
    existing_via_any: List[UInt32],
    existing_via_seg: List[UInt32],
    forbid_stacked_vias: Bool,
    allowed_layers_mask: UInt32,
) raises -> List[Int]:
    var n = grid.layers * grid.width * grid.height
    if start_idx < 0 or start_idx >= n:
        return List[Int]()
    if goal_idx < 0 or goal_idx >= n:
        return List[Int]()

    var start = idx_to_coords(start_idx, grid.width, grid.height)
    var goal = idx_to_coords(goal_idx, grid.width, grid.height)
    var raw_mask = allowed_layers_mask
    var mask = raw_mask
    var via_mask = raw_mask
    if grid.layers <= 16:
        var lo = raw_mask & UInt32(0x0000_FFFF)
        var hi = (raw_mask >> UInt32(16)) & UInt32(0x0000_FFFF)
        if hi != UInt32(0):
            mask = lo
            via_mask = hi
    if mask == UInt32(0):
        var m = UInt32(0)
        var li = 0
        while li < grid.layers and li < 32:
            m = m | (UInt32(1) << UInt32(li))
            li += 1
        mask = m
    if via_mask == UInt32(0):
        via_mask = mask
    if (mask & (UInt32(1) << UInt32(start.layer))) == UInt32(0):
        return List[Int]()
    if (mask & (UInt32(1) << UInt32(goal.layer))) == UInt32(0):
        return List[Int]()

    var x0 = bound_x0
    var y0 = bound_y0
    var x1 = bound_x1
    var y1 = bound_y1
    if x0 < 0:
        x0 = 0
    if y0 < 0:
        y0 = 0
    if x1 >= grid.width:
        x1 = grid.width - 1
    if y1 >= grid.height:
        y1 = grid.height - 1
    if x0 > x1 or y0 > y1:
        return List[Int]()
    if start.x < x0 or start.x > x1 or start.y < y0 or start.y > y1:
        return List[Int]()
    if goal.x < x0 or goal.x > x1 or goal.y < y0 or goal.y > y1:
        return List[Int]()

    var inf = UInt32(0xFFFF_FFFF)
    if ws.n != n:
        ws = AStarWorkspace(n)
    ws.reset()
    ws.set_g(start_idx, UInt32(0), start_idx)
    var h0 = heuristic_idx(
        start_idx,
        goal.layer,
        goal.x,
        goal.y,
        grid.width,
        grid.height,
        via_penalty,
    )
    var w = heuristic_weight_pct
    var f0 = UInt32(0) + UInt32((UInt64(h0) * UInt64(w)) // UInt64(100))
    ws.heap.push(f0, UInt32(0), start_idx)

    var dxs: List[Int] = [1, 0, -1, 0]
    var dys: List[Int] = [0, 1, 0, -1]
    if diagonal:
        dxs = [1, 0, -1, 0, 1, -1, 1, -1]
        dys = [0, 1, 0, -1, 1, 1, -1, -1]

    var n_dirs = len(dxs)
    var rot = Int(seed % UInt64(n_dirs)) if n_dirs > 0 else 0
    var reverse = (seed & UInt64(8)) != UInt64(0)
    var xy_len = grid.width * grid.height
    var seg_len = (grid.layers - 1) * xy_len
    var expansions = UInt32(0)

    while not ws.heap.is_empty():
        expansions = expansions + UInt32(1)
        if deadline_s > 0.0 and (expansions & UInt32(0x0FFF)) == UInt32(0):
            if _now_s() > deadline_s:
                return List[Int]()
        if max_expansions != UInt32(0) and expansions > max_expansions:
            return List[Int]()
        var cur = ws.heap.pop_min()
        var cur_g = cur.g
        var cur_idx = cur.idx
        if cur_idx == goal_idx:
            var out = List[Int]()
            var curp = goal_idx
            while True:
                out.append(curp)
                if curp == start_idx:
                    break
                var p = ws.get_prev(curp)
                if p == -1:
                    return List[Int]()
                curp = p
            out.reverse()
            return out^

        var c = idx_to_coords(cur_idx, grid.width, grid.height)
        var cur_layer = c.layer
        var cx = c.x
        var cy = c.y
        var xy = cy * grid.width + cx
        if (mask & (UInt32(1) << UInt32(cur_layer))) == UInt32(0):
            continue

        if cx < x0 or cx > x1 or cy < y0 or cy > y1:
            continue

        var best_g = ws.get_g(cur_idx, inf)
        if cur_g != best_g:
            continue

        # In-layer moves (respect allowed-layers mask).
        if (mask & (UInt32(1) << UInt32(cur_layer))) != UInt32(0):
            var i = 0
            while i < n_dirs:
                var ii = 0
                if not reverse:
                    ii = (i + rot) % n_dirs
                else:
                    ii = (rot + (n_dirs - 1 - i)) % n_dirs
                var nx = cx + dxs[ii]
                var ny = cy + dys[ii]
                if nx < x0 or nx > x1 or ny < y0 or ny > y1:
                    i += 1
                    continue
                if not grid.in_bounds(cur_layer, nx, ny):
                    i += 1
                    continue
                # Prevent diagonal corner-cutting: for a diagonal step, require both adjacent
                # orthogonal cells to be legal too.
                if diagonal and abs_i(dxs[ii]) == 1 and abs_i(dys[ii]) == 1:
                    var ox1 = nx
                    var oy1 = cy
                    var ox2 = cx
                    var oy2 = ny
                    if not grid.in_bounds(cur_layer, ox1, oy1) or not grid.in_bounds(
                        cur_layer, ox2, oy2
                    ):
                        i += 1
                        continue
                    if not grid.base_allows(
                        cur_layer, ox1, oy1, net_id
                    ) or not grid.base_allows(cur_layer, ox2, oy2, net_id):
                        i += 1
                        continue
                    var oidx1 = grid.idx(cur_layer, ox1, oy1)
                    var oidx2 = grid.idx(cur_layer, ox2, oy2)
                    if (
                        grid.occ_other_at_idx(oidx1, net_id) != UInt16(0)
                        or grid.occ_other_at_idx(oidx2, net_id) != UInt16(0)
                    ):
                        # Keep diagonal corner occupancy as a hard block even in
                        # overlap mode. Allowing this creates many KiCad
                        # tracks_crossing violations that postroute cleanup does
                        # not reliably remove.
                        i += 1
                        continue
                    if enforce_touch and (
                        grid.touch_track_other_at_idx(oidx1, net_id) != UInt16(0)
                        or grid.touch_track_other_at_idx(oidx2, net_id) != UInt16(0)
                        or grid.touch_via_other_at_idx(oidx1, net_id) != UInt16(0)
                        or grid.touch_via_other_at_idx(oidx2, net_id) != UInt16(0)
                    ):
                        if not ncr_allow_overlaps:
                            i += 1
                            continue
                    if enforce_spacing and (
                        grid.ko_track_other_at_idx(oidx1, net_id) != UInt16(0)
                        or grid.ko_track_other_at_idx(oidx2, net_id) != UInt16(0)
                        or grid.ko_via_other_at_idx(oidx1, net_id) != UInt16(0)
                        or grid.ko_via_other_at_idx(oidx2, net_id) != UInt16(0)
                    ):
                        if not ncr_allow_overlaps:
                            i += 1
                            continue
                if not grid.base_allows(cur_layer, nx, ny, net_id):
                    i += 1
                    continue

                var ni = grid.idx(cur_layer, nx, ny)
                if grid.occ_other_at_idx(ni, net_id) != UInt16(0):
                    if not ncr_allow_overlaps:
                        i += 1
                        continue
                var spacing_penalty = UInt32(0)
                if enforce_touch:
                    if (
                        grid.touch_track_other_at_idx(ni, net_id) != UInt16(0)
                        or grid.touch_via_other_at_idx(ni, net_id) != UInt16(0)
                    ):
                        if not ncr_allow_overlaps:
                            i += 1
                            continue
                if enforce_spacing:
                    if not ncr_allow_overlaps:
                        if (
                            grid.ko_track_other_at_idx(ni, net_id) != UInt16(0)
                            or grid.ko_via_other_at_idx(ni, net_id) != UInt16(0)
                        ):
                            i += 1
                            continue
                    else:
                        var k = grid.ko_track_other_at_idx(ni, net_id)
                        var t = grid.touch_track_other_at_idx(ni, net_id)
                        if grid.touch_via_other_at_idx(ni, net_id) > t:
                            t = grid.touch_via_other_at_idx(ni, net_id)
                        if k > spacing_present_cap:
                            k = spacing_present_cap
                        if t > spacing_present_cap:
                            t = spacing_present_cap
                        spacing_penalty = UInt32(k + t) * spacing_present_cost
                var step = UInt32(1) + layer_penalty_for_layer(
                    cur_layer,
                    grid.layers,
                    layer_penalty_outer,
                    layer_penalty_in1,
                    layer_penalty_inner,
                )
                var extra = grid.step_cost(
                    ni, net_id, present_cost, history_cost, ignore_congestion
                )
                var ng = best_g + step + extra + spacing_penalty
                if ng < ws.get_g(ni, inf):
                    ws.set_g(ni, ng, cur_idx)
                    var h = heuristic_idx(
                        ni,
                        goal.layer,
                        goal.x,
                        goal.y,
                        grid.width,
                        grid.height,
                        via_penalty,
                    )
                    var f = ng + UInt32((UInt64(h) * UInt64(w)) // UInt64(100))
                    ws.heap.push(f, ng, ni)
                i += 1

        # Via transitions (nearest allowed layers; can skip masked internal layers).
        if via_penalty > 0:
            if (via_mask & (UInt32(1) << UInt32(cur_layer))) == UInt32(0):
                continue
            var nl0 = cur_layer - 1
            while nl0 >= 0 and (via_mask & (UInt32(1) << UInt32(nl0))) == UInt32(0):
                nl0 -= 1
            if nl0 >= 0 and (via_mask & (UInt32(1) << UInt32(nl0))) != UInt32(0):
                if grid.base_allows(nl0, cx, cy, net_id):
                    var ni0 = grid.idx(nl0, cx, cy)
                    if (
                        grid.occ_other_at_idx(ni0, net_id) == UInt16(0)
                        or (ncr_allow_overlaps and (not forbid_stacked_vias))
                    ):
                        var ok0 = True
                        var spacing_penalty0 = UInt32(0)
                        var stack_ext_penalty0 = UInt32(0)
                        if (
                            forbid_stacked_vias
                            and len(existing_via_any) == xy_len
                            and existing_via_any[xy] == net_id
                        ):
                            var bi0 = nl0 * xy_len + xy
                            var seg_ok = (
                                len(existing_via_seg) == seg_len
                                and bi0 >= 0
                                and bi0 < len(existing_via_seg)
                                and existing_via_seg[bi0] == net_id
                            )
                            if not seg_ok:
                                var ext_ok = False
                                if len(existing_via_seg) == seg_len:
                                    var bi_dn = bi0 - xy_len
                                    var bi_up = bi0 + xy_len
                                    if bi_dn >= 0 and bi_dn < len(existing_via_seg) and existing_via_seg[bi_dn] == net_id:
                                        ext_ok = True
                                    if bi_up >= 0 and bi_up < len(existing_via_seg) and existing_via_seg[bi_up] == net_id:
                                        ext_ok = True
                                if not ext_ok:
                                    ok0 = False
                                else:
                                    stack_ext_penalty0 = via_penalty * UInt32(4)
                        if (
                            forbid_stacked_vias
                            and len(existing_via_any) == xy_len
                            and existing_via_any[xy] != UInt32(0)
                            and existing_via_any[xy] != net_id
                        ):
                            ok0 = False
                        var idx0 = grid.idx(cur_layer, cx, cy)
                        var idx1 = ni0
                        if enforce_touch:
                            var tv0 = grid.touch_via_other_at_idx(idx0, net_id)
                            var tv1 = grid.touch_via_other_at_idx(idx1, net_id)
                            var tt0 = grid.touch_track_other_at_idx(idx0, net_id)
                            var tt1 = grid.touch_track_other_at_idx(idx1, net_id)
                            if tv0 != UInt16(0) or tv1 != UInt16(0) or tt0 != UInt16(0) or tt1 != UInt16(0):
                                if (not ncr_allow_overlaps) or forbid_stacked_vias:
                                    ok0 = False
                                elif not enforce_spacing:
                                    var t0 = tv0
                                    var t1 = tv1
                                    if tt0 > t0:
                                        t0 = tt0
                                    if tt1 > t1:
                                        t1 = tt1
                                    var t = t0
                                    if t1 > t:
                                        t = t1
                                    if t > UInt16(spacing_present_cap):
                                        t = UInt16(spacing_present_cap)
                                    spacing_penalty0 = UInt32(t) * spacing_present_cost
                        if enforce_spacing:
                            if ok0:
                                var using_existing0 = (
                                    grid.via_usage[idx0] != UInt16(0)
                                    and grid.via_owner[idx0] == net_id
                                    and grid.via_usage[idx1] != UInt16(0)
                                    and grid.via_owner[idx1] == net_id
                                )
                                var k0 = grid.ko_via_other_at_idx(idx0, net_id)
                                var k1 = grid.ko_via_other_at_idx(idx1, net_id)
                                if forbid_stacked_vias and not using_existing0:
                                    k0 = grid.ko_via[idx0]
                                    k1 = grid.ko_via[idx1]
                                if not ncr_allow_overlaps:
                                    if k0 != UInt16(0) or k1 != UInt16(0):
                                        ok0 = False
                                    if (
                                        grid.ko_track_other_at_idx(idx0, net_id)
                                        != UInt16(0)
                                        or grid.ko_track_other_at_idx(idx1, net_id)
                                        != UInt16(0)
                                    ):
                                        ok0 = False
                                else:
                                    if forbid_stacked_vias:
                                        if (
                                            k0 != UInt16(0)
                                            or k1 != UInt16(0)
                                            or grid.ko_track_other_at_idx(idx0, net_id) != UInt16(0)
                                            or grid.ko_track_other_at_idx(idx1, net_id) != UInt16(0)
                                        ):
                                            ok0 = False
                                    else:
                                        var k = UInt32(k0) + UInt32(k1)
                                        if k > UInt32(spacing_present_cap):
                                            k = UInt32(spacing_present_cap)
                                        var t = UInt32(0)
                                        var tv0 = grid.touch_via_other_at_idx(idx0, net_id)
                                        var tv1 = grid.touch_via_other_at_idx(idx1, net_id)
                                        var tt0 = grid.touch_track_other_at_idx(idx0, net_id)
                                        var tt1 = grid.touch_track_other_at_idx(idx1, net_id)
                                        if tv0 < tt0:
                                            tv0 = tt0
                                        if tv1 < tt1:
                                            tv1 = tt1
                                        if tv0 > tv1:
                                            t = UInt32(tv0)
                                        else:
                                            t = UInt32(tv1)
                                        if t > UInt32(spacing_present_cap):
                                            t = UInt32(spacing_present_cap)
                                        spacing_penalty0 = (k + t) * spacing_present_cost
                        if ok0:
                            var extra0 = grid.step_cost(
                                ni0,
                                net_id,
                                present_cost,
                                history_cost,
                                ignore_congestion,
                            )
                            var ng0 = best_g + via_penalty + extra0 + spacing_penalty0
                            ng0 = ng0 + stack_ext_penalty0
                            if ng0 < ws.get_g(ni0, inf):
                                ws.set_g(ni0, ng0, cur_idx)
                                var h0 = heuristic_idx(
                                    ni0,
                                    goal.layer,
                                    goal.x,
                                    goal.y,
                                    grid.width,
                                    grid.height,
                                    via_penalty,
                                )
                                var f0 = ng0 + UInt32(
                                    (UInt64(h0) * UInt64(w)) // UInt64(100)
                                )
                                ws.heap.push(f0, ng0, ni0)
            var nl1 = cur_layer + 1
            while nl1 < grid.layers and (via_mask & (UInt32(1) << UInt32(nl1))) == UInt32(0):
                nl1 += 1
            if nl1 < grid.layers and (via_mask & (UInt32(1) << UInt32(nl1))) != UInt32(0):
                if grid.base_allows(nl1, cx, cy, net_id):
                    var ni1 = grid.idx(nl1, cx, cy)
                    if (
                        grid.occ_other_at_idx(ni1, net_id) == UInt16(0)
                        or (ncr_allow_overlaps and (not forbid_stacked_vias))
                    ):
                        var ok1 = True
                        var spacing_penalty1 = UInt32(0)
                        var stack_ext_penalty1 = UInt32(0)
                        if (
                            forbid_stacked_vias
                            and len(existing_via_any) == xy_len
                            and existing_via_any[xy] == net_id
                        ):
                            var bi1 = cur_layer * xy_len + xy
                            var seg_ok = (
                                len(existing_via_seg) == seg_len
                                and bi1 >= 0
                                and bi1 < len(existing_via_seg)
                                and existing_via_seg[bi1] == net_id
                            )
                            if not seg_ok:
                                var ext_ok = False
                                if len(existing_via_seg) == seg_len:
                                    var bi_dn = bi1 - xy_len
                                    var bi_up = bi1 + xy_len
                                    if bi_dn >= 0 and bi_dn < len(existing_via_seg) and existing_via_seg[bi_dn] == net_id:
                                        ext_ok = True
                                    if bi_up >= 0 and bi_up < len(existing_via_seg) and existing_via_seg[bi_up] == net_id:
                                        ext_ok = True
                                if not ext_ok:
                                    ok1 = False
                                else:
                                    stack_ext_penalty1 = via_penalty * UInt32(4)
                        if (
                            forbid_stacked_vias
                            and len(existing_via_any) == xy_len
                            and existing_via_any[xy] != UInt32(0)
                            and existing_via_any[xy] != net_id
                        ):
                            ok1 = False
                        var idx0 = grid.idx(cur_layer, cx, cy)
                        var idx1 = ni1
                        if enforce_touch:
                            var tv0 = grid.touch_via_other_at_idx(idx0, net_id)
                            var tv1 = grid.touch_via_other_at_idx(idx1, net_id)
                            var tt0 = grid.touch_track_other_at_idx(idx0, net_id)
                            var tt1 = grid.touch_track_other_at_idx(idx1, net_id)
                            if tv0 != UInt16(0) or tv1 != UInt16(0) or tt0 != UInt16(0) or tt1 != UInt16(0):
                                if (not ncr_allow_overlaps) or forbid_stacked_vias:
                                    ok1 = False
                                elif not enforce_spacing:
                                    var t0 = tv0
                                    var t1 = tv1
                                    if tt0 > t0:
                                        t0 = tt0
                                    if tt1 > t1:
                                        t1 = tt1
                                    var t = t0
                                    if t1 > t:
                                        t = t1
                                    if t > UInt16(spacing_present_cap):
                                        t = UInt16(spacing_present_cap)
                                    spacing_penalty1 = UInt32(t) * spacing_present_cost
                        if enforce_spacing:
                            if ok1:
                                var using_existing1 = (
                                    grid.via_usage[idx0] != UInt16(0)
                                    and grid.via_owner[idx0] == net_id
                                    and grid.via_usage[idx1] != UInt16(0)
                                    and grid.via_owner[idx1] == net_id
                                )
                                var k0 = grid.ko_via_other_at_idx(idx0, net_id)
                                var k1 = grid.ko_via_other_at_idx(idx1, net_id)
                                if forbid_stacked_vias and not using_existing1:
                                    k0 = grid.ko_via[idx0]
                                    k1 = grid.ko_via[idx1]
                                if not ncr_allow_overlaps:
                                    if k0 != UInt16(0) or k1 != UInt16(0):
                                        ok1 = False
                                    if (
                                        grid.ko_track_other_at_idx(idx0, net_id)
                                        != UInt16(0)
                                        or grid.ko_track_other_at_idx(idx1, net_id)
                                        != UInt16(0)
                                    ):
                                        ok1 = False
                                else:
                                    if forbid_stacked_vias:
                                        if (
                                            k0 != UInt16(0)
                                            or k1 != UInt16(0)
                                            or grid.ko_track_other_at_idx(idx0, net_id) != UInt16(0)
                                            or grid.ko_track_other_at_idx(idx1, net_id) != UInt16(0)
                                        ):
                                            ok1 = False
                                    else:
                                        var k = UInt32(k0) + UInt32(k1)
                                        if k > UInt32(spacing_present_cap):
                                            k = UInt32(spacing_present_cap)
                                        var t = UInt32(0)
                                        var tv0 = grid.touch_via_other_at_idx(idx0, net_id)
                                        var tv1 = grid.touch_via_other_at_idx(idx1, net_id)
                                        var tt0 = grid.touch_track_other_at_idx(idx0, net_id)
                                        var tt1 = grid.touch_track_other_at_idx(idx1, net_id)
                                        if tv0 < tt0:
                                            tv0 = tt0
                                        if tv1 < tt1:
                                            tv1 = tt1
                                        if tv0 > tv1:
                                            t = UInt32(tv0)
                                        else:
                                            t = UInt32(tv1)
                                        if t > UInt32(spacing_present_cap):
                                            t = UInt32(spacing_present_cap)
                                        spacing_penalty1 = (k + t) * spacing_present_cost
                        if ok1:
                            var extra1 = grid.step_cost(
                                ni1,
                                net_id,
                                present_cost,
                                history_cost,
                                ignore_congestion,
                            )
                            var ng1 = best_g + via_penalty + extra1 + spacing_penalty1
                            ng1 = ng1 + stack_ext_penalty1
                            if ng1 < ws.get_g(ni1, inf):
                                ws.set_g(ni1, ng1, cur_idx)
                                var h1 = heuristic_idx(
                                    ni1,
                                    goal.layer,
                                    goal.x,
                                    goal.y,
                                    grid.width,
                                    grid.height,
                                    via_penalty,
                                )
                                var f1 = ng1 + UInt32(
                                    (UInt64(h1) * UInt64(w)) // UInt64(100)
                                )
                                ws.heap.push(f1, ng1, ni1)
    return List[Int]()
