from collections import List

from .geometry import AABB, Segment, aabb_intersects


struct SpatialSegmentIndex:
    var cell_size: Float64
    var origin_x: Float64
    var origin_y: Float64
    var cols: Int
    var rows: Int
    var buckets: List[List[Int]]
    var segs: List[Segment]
    var layer_ids: List[Int]
    var net_ids: List[UInt32]
    var widths_mm: List[Float64]

    fn __init__(
        out self,
        *,
        origin_x: Float64,
        origin_y: Float64,
        cols: Int,
        rows: Int,
        cell_size: Float64,
    ):
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.cols = cols
        self.rows = rows
        self.cell_size = cell_size
        self.buckets = List[List[Int]](length=cols * rows, fill=List[Int]())
        self.segs = List[Segment]()
        self.layer_ids = List[Int]()
        self.net_ids = List[UInt32]()
        self.widths_mm = List[Float64]()

    fn _cell_x(self, x: Float64) -> Int:
        var fx = (x - self.origin_x) / self.cell_size
        var ix = Int(fx)
        if ix < 0:
            return 0
        if ix >= self.cols:
            return self.cols - 1
        return ix

    fn _cell_y(self, y: Float64) -> Int:
        var fy = (y - self.origin_y) / self.cell_size
        var iy = Int(fy)
        if iy < 0:
            return 0
        if iy >= self.rows:
            return self.rows - 1
        return iy

    fn _bucket_idx(self, cx: Int, cy: Int) -> Int:
        return cy * self.cols + cx

    fn add_segment(mut self, seg: Segment, layer_id: Int, net_id: UInt32, width_mm: Float64) -> Int:
        var id = len(self.segs)
        self.segs.append(seg.copy())
        self.layer_ids.append(layer_id)
        self.net_ids.append(net_id)
        self.widths_mm.append(width_mm)
        var bb = seg.aabb()
        var x0 = self._cell_x(bb.min_x)
        var x1 = self._cell_x(bb.max_x)
        var y0 = self._cell_y(bb.min_y)
        var y1 = self._cell_y(bb.max_y)
        var y = y0
        while y <= y1:
            var x = x0
            while x <= x1:
                self.buckets[self._bucket_idx(x, y)].append(id)
                x += 1
            y += 1
        return id

    fn query_aabb(self, bb: AABB) -> List[Int]:
        var out = List[Int]()
        if bb.max_x < bb.min_x:
            return out^
        var x0 = self._cell_x(bb.min_x)
        var x1 = self._cell_x(bb.max_x)
        var y0 = self._cell_y(bb.min_y)
        var y1 = self._cell_y(bb.max_y)
        var mark = List[UInt16](length=len(self.segs), fill=UInt16(0))
        var y = y0
        while y <= y1:
            var x = x0
            while x <= x1:
                for sid in self.buckets[self._bucket_idx(x, y)]:
                    if sid < 0 or sid >= len(mark):
                        continue
                    if mark[sid] != UInt16(0):
                        continue
                    mark[sid] = UInt16(1)
                    # Final BB filter, in case bucket overlap is coarse.
                    var sbb = self.segs[sid].aabb()
                    if aabb_intersects(bb, sbb):
                        out.append(sid)
                x += 1
            y += 1
        return out^
