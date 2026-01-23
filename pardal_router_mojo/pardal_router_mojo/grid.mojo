from collections import List

fn u32_max() -> UInt32:
    return UInt32(0xFFFF_FFFF)

fn u16_max() -> UInt16:
    return UInt16(0xFFFF)

fn sat_add_u16(a: UInt16, b: UInt16) -> UInt16:
    var x = UInt32(a) + UInt32(b)
    if x > UInt32(u16_max()):
        return u16_max()
    return UInt16(x)

fn sat_sub_u16(a: UInt16, b: UInt16) -> UInt16:
    if a <= b:
        return UInt16(0)
    return UInt16(a - b)

fn sat_mul_u16(a: UInt16, b: UInt16) -> UInt16:
    var x = UInt32(a) * UInt32(b)
    if x > UInt32(u16_max()):
        return u16_max()
    return UInt16(x)

fn bump_owner(owner: UInt32, net_id: UInt32) -> UInt32:
    if owner == UInt32(0) or owner == net_id:
        return net_id
    return u32_max()

fn dec_owner(owner: UInt32, net_id: UInt32, remaining: UInt16) -> UInt32:
    if remaining == UInt16(0):
        return UInt32(0)
    if owner != net_id:
        return u32_max()
    return owner

struct Spacing:
    # Packed offsets as [dx0, dy0, dx1, dy1, ...].
    var track_vs_track: List[Int]
    var track_vs_via: List[Int]
    var via_vs_track: List[Int]
    var via_vs_via: List[Int]

    fn __init__(out self):
        self.track_vs_track = List[Int]()
        self.track_vs_via = List[Int]()
        self.via_vs_track = List[Int]()
        self.via_vs_via = List[Int]()

struct SpacingBundle:
    var clear: Spacing
    var touch: Spacing

    fn __init__(out self):
        self.clear = Spacing()
        self.touch = Spacing()

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


struct Grid:
    var layers: Int
    var width: Int
    var height: Int
    var blocked_value: UInt32
    var base_occ: List[UInt32]
    # Dynamic occupancy (negotiated congestion + overlap detection).
    var track_usage: List[UInt16]
    var via_usage: List[UInt16]
    var track_owner: List[UInt32]
    var via_owner: List[UInt32]
    # Dynamic keepout fields for clearance-aware routing.
    # These are stamped from committed routes so spacing checks can be O(1).
    var ko_track: List[UInt16]
    var ko_via: List[UInt16]
    var ko_track_owner: List[UInt32]
    var ko_via_owner: List[UInt32]
    # "Touch" keepout fields (prevent copper overlap / shorts). These are smaller than
    # full clearance and are always enforced as hard constraints.
    var touch_track: List[UInt16]
    var touch_via: List[UInt16]
    var touch_track_owner: List[UInt32]
    var touch_via_owner: List[UInt32]
    var history: List[UInt16]
    var touched: List[Int]
    var touched_mark: List[UInt16]
    # Scratch marker for per-route index de-duplication.
    var scratch_mark: List[UInt16]
    var scratch_touched: List[Int]

    fn __init__(out self, layers: Int, width: Int, height: Int):
        self.layers = layers
        self.width = width
        self.height = height
        self.blocked_value = u32_max()
        var n = layers * width * height
        self.base_occ = List[UInt32](length=n, fill=UInt32(0))
        self.track_usage = List[UInt16](length=n, fill=UInt16(0))
        self.via_usage = List[UInt16](length=n, fill=UInt16(0))
        self.track_owner = List[UInt32](length=n, fill=UInt32(0))
        self.via_owner = List[UInt32](length=n, fill=UInt32(0))
        self.ko_track = List[UInt16](length=n, fill=UInt16(0))
        self.ko_via = List[UInt16](length=n, fill=UInt16(0))
        self.ko_track_owner = List[UInt32](length=n, fill=UInt32(0))
        self.ko_via_owner = List[UInt32](length=n, fill=UInt32(0))
        self.touch_track = List[UInt16](length=n, fill=UInt16(0))
        self.touch_via = List[UInt16](length=n, fill=UInt16(0))
        self.touch_track_owner = List[UInt32](length=n, fill=UInt32(0))
        self.touch_via_owner = List[UInt32](length=n, fill=UInt32(0))
        self.history = List[UInt16](length=n, fill=UInt16(0))
        self.touched = List[Int]()
        self.touched_mark = List[UInt16](length=n, fill=UInt16(0))
        self.scratch_mark = List[UInt16](length=n, fill=UInt16(0))
        self.scratch_touched = List[Int]()

    fn idx(self, layer: Int, x: Int, y: Int) -> Int:
        return (layer * self.width * self.height) + (y * self.width + x)

    fn base_get(self, idx: Int) -> UInt32:
        return self.base_occ[idx]

    fn base_set(mut self, idx: Int, v: UInt32):
        self.base_occ[idx] = v

    fn in_bounds(self, layer: Int, x: Int, y: Int) -> Bool:
        return layer >= 0 and layer < self.layers and x >= 0 and x < self.width and y >= 0 and y < self.height

    fn base_allows(self, layer: Int, x: Int, y: Int, net_id: UInt32) -> Bool:
        var v = self.base_occ[self.idx(layer, x, y)]
        if v == self.blocked_value:
            return False
        return v == UInt32(0) or v == net_id

    fn occ_total_at_idx(self, idx: Int) -> UInt16:
        return sat_add_u16(self.track_usage[idx], self.via_usage[idx])

    fn occ_other_at_idx(self, idx: Int, net_id: UInt32) -> UInt16:
        var out = UInt16(0)
        var t = self.track_usage[idx]
        if t != UInt16(0) and self.track_owner[idx] != net_id:
            out = UInt16(out + t)
        var v = self.via_usage[idx]
        if v != UInt16(0) and self.via_owner[idx] != net_id:
            out = UInt16(out + v)
        return out

    fn ko_track_other_at_idx(self, idx: Int, net_id: UInt32) -> UInt16:
        var k = self.ko_track[idx]
        if k == UInt16(0):
            return UInt16(0)
        var o = self.ko_track_owner[idx]
        if o == net_id:
            return UInt16(0)
        return k

    fn ko_via_other_at_idx(self, idx: Int, net_id: UInt32) -> UInt16:
        var k = self.ko_via[idx]
        if k == UInt16(0):
            return UInt16(0)
        var o = self.ko_via_owner[idx]
        if o == net_id:
            return UInt16(0)
        return k

    fn touch_track_other_at_idx(self, idx: Int, net_id: UInt32) -> UInt16:
        var k = self.touch_track[idx]
        if k == UInt16(0):
            return UInt16(0)
        var o = self.touch_track_owner[idx]
        if o == net_id:
            return UInt16(0)
        return k

    fn touch_via_other_at_idx(self, idx: Int, net_id: UInt32) -> UInt16:
        var k = self.touch_via[idx]
        if k == UInt16(0):
            return UInt16(0)
        var o = self.touch_via_owner[idx]
        if o == net_id:
            return UInt16(0)
        return k

    fn touch_idx(mut self, idx: Int):
        if self.touched_mark[idx] == UInt16(0):
            self.touched.append(idx)
            self.touched_mark[idx] = UInt16(1)

    fn stamp_ko_track_at(mut self, idx: Int, net_id: UInt32, delta: Int):
        if delta > 0:
            if self.ko_track[idx] == UInt16(0):
                self.touch_idx(idx)
            self.ko_track[idx] = sat_add_u16(self.ko_track[idx], UInt16(delta))
            self.ko_track_owner[idx] = bump_owner(self.ko_track_owner[idx], net_id)
        else:
            var d = UInt16(-delta)
            self.ko_track[idx] = sat_sub_u16(self.ko_track[idx], d)
            self.ko_track_owner[idx] = dec_owner(self.ko_track_owner[idx], net_id, self.ko_track[idx])

    fn stamp_ko_via_at(mut self, idx: Int, net_id: UInt32, delta: Int):
        if delta > 0:
            if self.ko_via[idx] == UInt16(0):
                self.touch_idx(idx)
            self.ko_via[idx] = sat_add_u16(self.ko_via[idx], UInt16(delta))
            self.ko_via_owner[idx] = bump_owner(self.ko_via_owner[idx], net_id)
        else:
            var d = UInt16(-delta)
            self.ko_via[idx] = sat_sub_u16(self.ko_via[idx], d)
            self.ko_via_owner[idx] = dec_owner(self.ko_via_owner[idx], net_id, self.ko_via[idx])

    fn stamp_touch_track_at(mut self, idx: Int, net_id: UInt32, delta: Int):
        if delta > 0:
            if self.touch_track[idx] == UInt16(0):
                self.touch_idx(idx)
            self.touch_track[idx] = sat_add_u16(self.touch_track[idx], UInt16(delta))
            self.touch_track_owner[idx] = bump_owner(self.touch_track_owner[idx], net_id)
        else:
            var d = UInt16(-delta)
            self.touch_track[idx] = sat_sub_u16(self.touch_track[idx], d)
            self.touch_track_owner[idx] = dec_owner(self.touch_track_owner[idx], net_id, self.touch_track[idx])

    fn stamp_touch_via_at(mut self, idx: Int, net_id: UInt32, delta: Int):
        if delta > 0:
            if self.touch_via[idx] == UInt16(0):
                self.touch_idx(idx)
            self.touch_via[idx] = sat_add_u16(self.touch_via[idx], UInt16(delta))
            self.touch_via_owner[idx] = bump_owner(self.touch_via_owner[idx], net_id)
        else:
            var d = UInt16(-delta)
            self.touch_via[idx] = sat_sub_u16(self.touch_via[idx], d)
            self.touch_via_owner[idx] = dec_owner(self.touch_via_owner[idx], net_id, self.touch_via[idx])

    fn step_cost(
        self,
        idx: Int,
        net_id: UInt32,
        present_cost: UInt32,
        history_cost: UInt32,
        ignore_congestion: Bool,
    ) -> UInt32:
        if ignore_congestion:
            return UInt32(0)
        var u = UInt32(self.occ_other_at_idx(idx, net_id))
        var u_eff = UInt32(0) if u == UInt32(0) else (u + UInt32(1))
        var h = UInt32(self.history[idx])
        return u_eff * present_cost + h * history_cost

    fn stamp_circle_base(mut self, layer: Int, cx: Int, cy: Int, r: Int, net_id: UInt32):
        if not self.in_bounds(layer, cx, cy):
            return
        var r2 = r * r
        var x0 = max(cx - r, 0)
        var x1 = min(cx + r, self.width - 1)
        var y0 = max(cy - r, 0)
        var y1 = min(cy + r, self.height - 1)
        var y = y0
        while y <= y1:
            var dy = y - cy
            var dy2 = dy * dy
            var x = x0
            while x <= x1:
                var dx = x - cx
                if dx * dx + dy2 <= r2:
                    var i = self.idx(layer, x, y)
                    var cur = self.base_occ[i]
                    if cur == UInt32(0) or cur == net_id:
                        self.base_occ[i] = net_id
                    else:
                        self.base_occ[i] = self.blocked_value
                x += 1
            y += 1

    fn stamp_circle_base_collect(mut self, layer: Int, cx: Int, cy: Int, r: Int, net_id: UInt32) -> List[Int]:
        var out = List[Int]()
        if not self.in_bounds(layer, cx, cy):
            return out^
        var r2 = r * r
        var x0 = max(cx - r, 0)
        var x1 = min(cx + r, self.width - 1)
        var y0 = max(cy - r, 0)
        var y1 = min(cy + r, self.height - 1)
        var y = y0
        while y <= y1:
            var dy = y - cy
            var dy2 = dy * dy
            var x = x0
            while x <= x1:
                var dx = x - cx
                if dx * dx + dy2 <= r2:
                    var i = self.idx(layer, x, y)
                    var cur = self.base_occ[i]
                    if cur == UInt32(0) or cur == net_id:
                        self.base_occ[i] = net_id
                    else:
                        self.base_occ[i] = self.blocked_value
                    out.append(i)
                x += 1
            y += 1
        return out^

    fn clear_dynamic(mut self):
        for idx in self.touched:
            if idx >= 0 and idx < len(self.track_usage):
                self.track_usage[idx] = UInt16(0)
                self.via_usage[idx] = UInt16(0)
                self.track_owner[idx] = UInt32(0)
                self.via_owner[idx] = UInt32(0)
                self.ko_track[idx] = UInt16(0)
                self.ko_via[idx] = UInt16(0)
                self.ko_track_owner[idx] = UInt32(0)
                self.ko_via_owner[idx] = UInt32(0)
                self.touch_track[idx] = UInt16(0)
                self.touch_via[idx] = UInt16(0)
                self.touch_track_owner[idx] = UInt32(0)
                self.touch_via_owner[idx] = UInt32(0)
                self.touched_mark[idx] = UInt16(0)
        self.touched = List[Int]()

    fn _bump_track(mut self, idx: Int, net_id: UInt32):
        if self.occ_total_at_idx(idx) == UInt16(0):
            self.touch_idx(idx)
        self.track_usage[idx] = sat_add_u16(self.track_usage[idx], UInt16(1))
        var o = self.track_owner[idx]
        if o == UInt32(0) or o == net_id:
            self.track_owner[idx] = net_id
        else:
            self.track_owner[idx] = u32_max()

    fn _bump_via(mut self, idx: Int, net_id: UInt32):
        if self.occ_total_at_idx(idx) == UInt16(0):
            self.touch_idx(idx)
        self.via_usage[idx] = sat_add_u16(self.via_usage[idx], UInt16(1))
        var o = self.via_owner[idx]
        if o == UInt32(0) or o == net_id:
            self.via_owner[idx] = net_id
        else:
            self.via_owner[idx] = u32_max()

    fn _scratch_reset(mut self):
        for idx in self.scratch_touched:
            if idx >= 0 and idx < len(self.scratch_mark):
                self.scratch_mark[idx] = UInt16(0)
        self.scratch_touched = List[Int]()

    fn stamp_keepout_for_route(
        mut self,
        net_id: UInt32,
        track_indices: List[Int],
        via_indices: List[Int],
        spacing: SpacingBundle,
        delta: Int,
    ):
        var w = self.width
        var h = self.height
        for idx in track_indices:
            var p = idx_to_coords(idx, w, h)
            var layer = p.layer
            var x = p.x
            var y = p.y
            var oi = 0
            while oi + 1 < len(spacing.clear.track_vs_track):
                var nx = x + spacing.clear.track_vs_track[oi]
                var ny = y + spacing.clear.track_vs_track[oi + 1]
                if nx < 0 or ny < 0 or nx >= w or ny >= h:
                    oi += 2
                    continue
                self.stamp_ko_track_at(self.idx(layer, nx, ny), net_id, delta)
                oi += 2
            oi = 0
            while oi + 1 < len(spacing.clear.track_vs_via):
                var nx = x + spacing.clear.track_vs_via[oi]
                var ny = y + spacing.clear.track_vs_via[oi + 1]
                if nx < 0 or ny < 0 or nx >= w or ny >= h:
                    oi += 2
                    continue
                self.stamp_ko_via_at(self.idx(layer, nx, ny), net_id, delta)
                oi += 2
            oi = 0
            while oi + 1 < len(spacing.touch.track_vs_via):
                var nx = x + spacing.touch.track_vs_via[oi]
                var ny = y + spacing.touch.track_vs_via[oi + 1]
                if nx < 0 or ny < 0 or nx >= w or ny >= h:
                    oi += 2
                    continue
                self.stamp_touch_via_at(self.idx(layer, nx, ny), net_id, delta)
                oi += 2
        for idx in via_indices:
            var p = idx_to_coords(idx, w, h)
            var layer = p.layer
            var x = p.x
            var y = p.y
            var oi = 0
            while oi + 1 < len(spacing.clear.via_vs_track):
                var nx = x + spacing.clear.via_vs_track[oi]
                var ny = y + spacing.clear.via_vs_track[oi + 1]
                if nx < 0 or ny < 0 or nx >= w or ny >= h:
                    oi += 2
                    continue
                self.stamp_ko_track_at(self.idx(layer, nx, ny), net_id, delta)
                oi += 2
            oi = 0
            while oi + 1 < len(spacing.clear.via_vs_via):
                var nx = x + spacing.clear.via_vs_via[oi]
                var ny = y + spacing.clear.via_vs_via[oi + 1]
                if nx < 0 or ny < 0 or nx >= w or ny >= h:
                    oi += 2
                    continue
                self.stamp_ko_via_at(self.idx(layer, nx, ny), net_id, delta)
                oi += 2
            oi = 0
            while oi + 1 < len(spacing.touch.via_vs_track):
                var nx = x + spacing.touch.via_vs_track[oi]
                var ny = y + spacing.touch.via_vs_track[oi + 1]
                if nx < 0 or ny < 0 or nx >= w or ny >= h:
                    oi += 2
                    continue
                self.stamp_touch_track_at(self.idx(layer, nx, ny), net_id, delta)
                oi += 2
            oi = 0
            while oi + 1 < len(spacing.touch.via_vs_via):
                var nx = x + spacing.touch.via_vs_via[oi]
                var ny = y + spacing.touch.via_vs_via[oi + 1]
                if nx < 0 or ny < 0 or nx >= w or ny >= h:
                    oi += 2
                    continue
                self.stamp_touch_via_at(self.idx(layer, nx, ny), net_id, delta)
                oi += 2

    fn path_violates_keepouts(
        self,
        net_id: UInt32,
        path: List[Int],
        enforce_touch: Bool,
        enforce_spacing: Bool,
    ) -> Bool:
        # Conservative cell-based legality check. This is not exact geometry, but is
        # consistent with how the router enforces dynamic keepout fields during search.
        for idx in path:
            if idx < 0 or idx >= len(self.base_occ):
                continue
            if self.occ_other_at_idx(idx, net_id) != UInt16(0):
                return True
            if enforce_touch and (
                self.touch_track_other_at_idx(idx, net_id) != UInt16(0)
                or self.touch_via_other_at_idx(idx, net_id) != UInt16(0)
            ):
                return True
            if enforce_spacing and (
                self.ko_track_other_at_idx(idx, net_id) != UInt16(0)
                or self.ko_via_other_at_idx(idx, net_id) != UInt16(0)
            ):
                return True
        return False

    fn commit_path(
        mut self,
        net_id: UInt32,
        path: List[Int],
        enforce_spacing: Bool,
        spacing: SpacingBundle,
    ):
        var tracks = List[Int]()
        var vias = List[Int]()
        self._scratch_reset()
        if len(path) == 0:
            return

        fn _sign_i(v: Int) -> Int:
            if v > 0:
                return 1
            if v < 0:
                return -1
            return 0
        fn _abs_i(v: Int) -> Int:
            return v if v >= 0 else -v

        var i = 0
        while i + 1 < len(path):
            var a_idx = path[i]
            var b_idx = path[i + 1]
            var a = idx_to_coords(a_idx, self.width, self.height)
            var b = idx_to_coords(b_idx, self.width, self.height)
            if a.x == b.x and a.y == b.y and a.layer != b.layer:
                # via endpoints on both layers
                if (self.scratch_mark[a_idx] & UInt16(2)) == UInt16(0):
                    self.scratch_mark[a_idx] = self.scratch_mark[a_idx] | UInt16(2)
                    self.scratch_touched.append(a_idx)
                    vias.append(a_idx)
                if (self.scratch_mark[b_idx] & UInt16(2)) == UInt16(0):
                    self.scratch_mark[b_idx] = self.scratch_mark[b_idx] | UInt16(2)
                    self.scratch_touched.append(b_idx)
                    vias.append(b_idx)
            else:
                # Rasterize the segment between a and b into unit steps so higher-level
                # algorithms (e.g. pull-tight) can safely emit long straight segments.
                # This preserves the "grid is truth" model used by occupancy/DRC.
                var dx0 = b.x - a.x
                var dy0 = b.y - a.y
                var sx = _sign_i(dx0)
                var sy = _sign_i(dy0)
                var dx = _abs_i(dx0)
                var dy = _abs_i(dy0)
                var prev_x = a.x
                var prev_y = a.y
                var x = a.x
                var y = a.y
                if dx >= dy:
                    var err = dx // 2
                    var s = 0
                    while s <= dx:
                        var idx = self.idx(a.layer, x, y)
                        if (self.scratch_mark[idx] & UInt16(1)) == UInt16(0):
                            self.scratch_mark[idx] = self.scratch_mark[idx] | UInt16(1)
                            self.scratch_touched.append(idx)
                            tracks.append(idx)
                        if s > 0 and x != prev_x and y != prev_y:
                            var c1 = self.idx(a.layer, x, prev_y)
                            var c2 = self.idx(a.layer, prev_x, y)
                            if (self.scratch_mark[c1] & UInt16(1)) == UInt16(0):
                                self.scratch_mark[c1] = self.scratch_mark[c1] | UInt16(1)
                                self.scratch_touched.append(c1)
                                tracks.append(c1)
                            if (self.scratch_mark[c2] & UInt16(1)) == UInt16(0):
                                self.scratch_mark[c2] = self.scratch_mark[c2] | UInt16(1)
                                self.scratch_touched.append(c2)
                                tracks.append(c2)
                        prev_x = x
                        prev_y = y
                        err -= dy
                        if err < 0:
                            y += sy
                            err += dx
                        x += sx
                        s += 1
                else:
                    var err = dy // 2
                    var s = 0
                    while s <= dy:
                        var idx = self.idx(a.layer, x, y)
                        if (self.scratch_mark[idx] & UInt16(1)) == UInt16(0):
                            self.scratch_mark[idx] = self.scratch_mark[idx] | UInt16(1)
                            self.scratch_touched.append(idx)
                            tracks.append(idx)
                        if s > 0 and x != prev_x and y != prev_y:
                            var c1 = self.idx(a.layer, x, prev_y)
                            var c2 = self.idx(a.layer, prev_x, y)
                            if (self.scratch_mark[c1] & UInt16(1)) == UInt16(0):
                                self.scratch_mark[c1] = self.scratch_mark[c1] | UInt16(1)
                                self.scratch_touched.append(c1)
                                tracks.append(c1)
                            if (self.scratch_mark[c2] & UInt16(1)) == UInt16(0):
                                self.scratch_mark[c2] = self.scratch_mark[c2] | UInt16(1)
                                self.scratch_touched.append(c2)
                                tracks.append(c2)
                        prev_x = x
                        prev_y = y
                        err -= dx
                        if err < 0:
                            x += sx
                            err += dy
                        y += sy
                        s += 1
            i += 1

        for idx in tracks:
            self._bump_track(idx, net_id)
        for idx in vias:
            self._bump_via(idx, net_id)
        if enforce_spacing:
            self.stamp_keepout_for_route(net_id, tracks, vias, spacing, 1)
        return

    fn uncommit_path(
        mut self,
        net_id: UInt32,
        path: List[Int],
        enforce_spacing: Bool,
        spacing: SpacingBundle,
    ):
        var tracks = List[Int]()
        var vias = List[Int]()
        self._scratch_reset()
        if len(path) == 0:
            return

        fn _sign_i(v: Int) -> Int:
            if v > 0:
                return 1
            if v < 0:
                return -1
            return 0
        fn _abs_i(v: Int) -> Int:
            return v if v >= 0 else -v

        var i = 0
        while i + 1 < len(path):
            var a_idx = path[i]
            var b_idx = path[i + 1]
            var a = idx_to_coords(a_idx, self.width, self.height)
            var b = idx_to_coords(b_idx, self.width, self.height)
            if a.x == b.x and a.y == b.y and a.layer != b.layer:
                if (self.scratch_mark[a_idx] & UInt16(2)) == UInt16(0):
                    self.scratch_mark[a_idx] = self.scratch_mark[a_idx] | UInt16(2)
                    self.scratch_touched.append(a_idx)
                    vias.append(a_idx)
                if (self.scratch_mark[b_idx] & UInt16(2)) == UInt16(0):
                    self.scratch_mark[b_idx] = self.scratch_mark[b_idx] | UInt16(2)
                    self.scratch_touched.append(b_idx)
                    vias.append(b_idx)
            else:
                var dx0 = b.x - a.x
                var dy0 = b.y - a.y
                var sx = _sign_i(dx0)
                var sy = _sign_i(dy0)
                var dx = _abs_i(dx0)
                var dy = _abs_i(dy0)
                var prev_x = a.x
                var prev_y = a.y
                var x = a.x
                var y = a.y
                if dx >= dy:
                    var err = dx // 2
                    var s = 0
                    while s <= dx:
                        var idx = self.idx(a.layer, x, y)
                        if (self.scratch_mark[idx] & UInt16(1)) == UInt16(0):
                            self.scratch_mark[idx] = self.scratch_mark[idx] | UInt16(1)
                            self.scratch_touched.append(idx)
                            tracks.append(idx)
                        if s > 0 and x != prev_x and y != prev_y:
                            var c1 = self.idx(a.layer, x, prev_y)
                            var c2 = self.idx(a.layer, prev_x, y)
                            if (self.scratch_mark[c1] & UInt16(1)) == UInt16(0):
                                self.scratch_mark[c1] = self.scratch_mark[c1] | UInt16(1)
                                self.scratch_touched.append(c1)
                                tracks.append(c1)
                            if (self.scratch_mark[c2] & UInt16(1)) == UInt16(0):
                                self.scratch_mark[c2] = self.scratch_mark[c2] | UInt16(1)
                                self.scratch_touched.append(c2)
                                tracks.append(c2)
                        prev_x = x
                        prev_y = y
                        err -= dy
                        if err < 0:
                            y += sy
                            err += dx
                        x += sx
                        s += 1
                else:
                    var err = dy // 2
                    var s = 0
                    while s <= dy:
                        var idx = self.idx(a.layer, x, y)
                        if (self.scratch_mark[idx] & UInt16(1)) == UInt16(0):
                            self.scratch_mark[idx] = self.scratch_mark[idx] | UInt16(1)
                            self.scratch_touched.append(idx)
                            tracks.append(idx)
                        if s > 0 and x != prev_x and y != prev_y:
                            var c1 = self.idx(a.layer, x, prev_y)
                            var c2 = self.idx(a.layer, prev_x, y)
                            if (self.scratch_mark[c1] & UInt16(1)) == UInt16(0):
                                self.scratch_mark[c1] = self.scratch_mark[c1] | UInt16(1)
                                self.scratch_touched.append(c1)
                                tracks.append(c1)
                            if (self.scratch_mark[c2] & UInt16(1)) == UInt16(0):
                                self.scratch_mark[c2] = self.scratch_mark[c2] | UInt16(1)
                                self.scratch_touched.append(c2)
                                tracks.append(c2)
                        prev_x = x
                        prev_y = y
                        err -= dx
                        if err < 0:
                            x += sx
                            err += dy
                        y += sy
                        s += 1
            i += 1
        self.uncommit(net_id, tracks, vias, enforce_spacing, spacing)
        return

    fn commit_indices(
        mut self,
        net_id: UInt32,
        track_indices: List[Int],
        via_indices: List[Int],
        enforce_spacing: Bool,
        spacing: SpacingBundle,
    ):
        for idx in track_indices:
            self._bump_track(idx, net_id)
        for idx in via_indices:
            self._bump_via(idx, net_id)
        if enforce_spacing:
            self.stamp_keepout_for_route(net_id, track_indices, via_indices, spacing, 1)

    fn uncommit(
        mut self,
        net_id: UInt32,
        track_indices: List[Int],
        via_indices: List[Int],
        enforce_spacing: Bool,
        spacing: SpacingBundle,
    ):
        for idx in track_indices:
            self.track_usage[idx] = sat_sub_u16(self.track_usage[idx], UInt16(1))
            if self.track_usage[idx] == UInt16(0):
                self.track_owner[idx] = UInt32(0)
            elif self.track_owner[idx] != net_id:
                self.track_owner[idx] = u32_max()
        for idx in via_indices:
            self.via_usage[idx] = sat_sub_u16(self.via_usage[idx], UInt16(1))
            if self.via_usage[idx] == UInt16(0):
                self.via_owner[idx] = UInt32(0)
            elif self.via_owner[idx] != net_id:
                self.via_owner[idx] = u32_max()
        if enforce_spacing:
            self.stamp_keepout_for_route(net_id, track_indices, via_indices, spacing, -1)

    fn overused_cells(self) -> Int:
        var over = 0
        for idx in self.touched:
            if idx >= 0 and idx < len(self.track_usage):
                var u = UInt16(self.track_usage[idx] + self.via_usage[idx])
                if u > UInt16(1):
                    over += 1
        return over

    fn bump_history_overused(mut self, inc: UInt16):
        for idx in self.touched:
            if idx >= 0 and idx < len(self.history):
                var u = UInt16(self.track_usage[idx] + self.via_usage[idx])
                if u > UInt16(1):
                    var cur = self.history[idx]
                    var next = UInt32(cur) + UInt32(inc)
                    if next > UInt32(u16_max()):
                        self.history[idx] = u16_max()
                    else:
                        self.history[idx] = UInt16(next)

    fn update_history_for_path(mut self, net_id: UInt32, path: List[Int], inc: UInt16) -> Bool:
        # Updates `history` for cells involved in conflicts on this path:
        # - overlapping usage (shorts/crossings)
        # - clearance violations (using stamped keepout fields)
        # Returns True if any conflicts were found.
        if len(path) == 0:
            return False
        var tracks = List[Int]()
        var vias = List[Int]()
        self._scratch_reset()

        var i = 0
        while i + 1 < len(path):
            var a_idx = path[i]
            var b_idx = path[i + 1]
            var a = idx_to_coords(a_idx, self.width, self.height)
            var b = idx_to_coords(b_idx, self.width, self.height)
            if a.x == b.x and a.y == b.y and a.layer != b.layer:
                if (self.scratch_mark[a_idx] & UInt16(2)) == UInt16(0):
                    self.scratch_mark[a_idx] = self.scratch_mark[a_idx] | UInt16(2)
                    self.scratch_touched.append(a_idx)
                    vias.append(a_idx)
                if (self.scratch_mark[b_idx] & UInt16(2)) == UInt16(0):
                    self.scratch_mark[b_idx] = self.scratch_mark[b_idx] | UInt16(2)
                    self.scratch_touched.append(b_idx)
                    vias.append(b_idx)
            else:
                if (self.scratch_mark[a_idx] & UInt16(1)) == UInt16(0):
                    self.scratch_mark[a_idx] = self.scratch_mark[a_idx] | UInt16(1)
                    self.scratch_touched.append(a_idx)
                    tracks.append(a_idx)
                if (self.scratch_mark[b_idx] & UInt16(1)) == UInt16(0):
                    self.scratch_mark[b_idx] = self.scratch_mark[b_idx] | UInt16(1)
                    self.scratch_touched.append(b_idx)
                    tracks.append(b_idx)
            i += 1

        var any_conflict = False
        for idx in tracks:
            var o = self.occ_other_at_idx(idx, net_id)
            if o != UInt16(0):
                any_conflict = True
                self.history[idx] = sat_add_u16(self.history[idx], sat_mul_u16(inc, o))
            var k = self.ko_track_other_at_idx(idx, net_id)
            if k != UInt16(0):
                any_conflict = True
                self.history[idx] = sat_add_u16(self.history[idx], sat_mul_u16(inc, k))
        for idx in vias:
            var o = self.occ_other_at_idx(idx, net_id)
            if o != UInt16(0):
                any_conflict = True
                self.history[idx] = sat_add_u16(self.history[idx], sat_mul_u16(inc, o))
            var k = self.ko_via_other_at_idx(idx, net_id)
            if k != UInt16(0):
                any_conflict = True
                self.history[idx] = sat_add_u16(self.history[idx], sat_mul_u16(inc, k))
        return any_conflict
