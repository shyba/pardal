from collections import List


@fieldwise_init
struct Vec2(Copyable, Movable):
    var x: Float64
    var y: Float64


@fieldwise_init
struct AABB(Copyable, Movable):
    var min_x: Float64
    var min_y: Float64
    var max_x: Float64
    var max_y: Float64

fn aabb_from_points(points: List[Vec2]) -> AABB:
    if len(points) == 0:
        return AABB(Float64(0.0), Float64(0.0), Float64(-1.0), Float64(-1.0))
    var min_x = points[0].x
    var min_y = points[0].y
    var max_x = points[0].x
    var max_y = points[0].y
    var i = 1
    while i < len(points):
        var p = points[i].copy()
        if p.x < min_x:
            min_x = p.x
        if p.y < min_y:
            min_y = p.y
        if p.x > max_x:
            max_x = p.x
        if p.y > max_y:
            max_y = p.y
        i += 1
    return AABB(min_x, min_y, max_x, max_y)


fn aabb_intersects(a: AABB, b: AABB) -> Bool:
    if a.max_x < a.min_x or b.max_x < b.min_x:
        return False
    return not (a.max_x < b.min_x or a.min_x > b.max_x or a.max_y < b.min_y or a.min_y > b.max_y)


fn clamp_f(v: Float64, lo: Float64, hi: Float64) -> Float64:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


fn dot(a: Vec2, b: Vec2) -> Float64:
    return a.x * b.x + a.y * b.y


fn sub(a: Vec2, b: Vec2) -> Vec2:
    return Vec2(a.x - b.x, a.y - b.y)


fn add(a: Vec2, b: Vec2) -> Vec2:
    return Vec2(a.x + b.x, a.y + b.y)


fn mul(a: Vec2, s: Float64) -> Vec2:
    return Vec2(a.x * s, a.y * s)


fn len2(v: Vec2) -> Float64:
    return v.x * v.x + v.y * v.y


fn dist2(a: Vec2, b: Vec2) -> Float64:
    return len2(sub(a, b))


fn dist_point_segment2(p: Vec2, a: Vec2, b: Vec2) -> Float64:
    var ab = sub(b, a)
    var ap = sub(p, a)
    var denom = len2(ab)
    if denom <= Float64(0.0):
        return dist2(p, a)
    var t = dot(ap, ab) / denom
    t = clamp_f(t, Float64(0.0), Float64(1.0))
    var q = add(a, mul(ab, t))
    return dist2(p, q)


fn orient(a: Vec2, b: Vec2, c: Vec2) -> Float64:
    # 2D cross product (b-a) x (c-a)
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


fn on_segment(a: Vec2, b: Vec2, p: Vec2) -> Bool:
    return (
        min(a.x, b.x) <= p.x
        and p.x <= max(a.x, b.x)
        and min(a.y, b.y) <= p.y
        and p.y <= max(a.y, b.y)
    )


fn segments_intersect(a0: Vec2, a1: Vec2, b0: Vec2, b1: Vec2) -> Bool:
    var o1 = orient(a0, a1, b0)
    var o2 = orient(a0, a1, b1)
    var o3 = orient(b0, b1, a0)
    var o4 = orient(b0, b1, a1)

    # General case
    if (o1 > 0 and o2 < 0 or o1 < 0 and o2 > 0) and (o3 > 0 and o4 < 0 or o3 < 0 and o4 > 0):
        return True

    # Collinear cases (epsilon-free: use exact 0 compare; inputs typically from grid/resolution)
    if o1 == Float64(0.0) and on_segment(a0, a1, b0):
        return True
    if o2 == Float64(0.0) and on_segment(a0, a1, b1):
        return True
    if o3 == Float64(0.0) and on_segment(b0, b1, a0):
        return True
    if o4 == Float64(0.0) and on_segment(b0, b1, a1):
        return True
    return False


fn dist_segment_segment2(a0: Vec2, a1: Vec2, b0: Vec2, b1: Vec2) -> Float64:
    if segments_intersect(a0, a1, b0, b1):
        return Float64(0.0)
    var d0 = dist_point_segment2(a0, b0, b1)
    var d1 = dist_point_segment2(a1, b0, b1)
    var d2 = dist_point_segment2(b0, a0, a1)
    var d3 = dist_point_segment2(b1, a0, a1)
    var d = d0
    if d1 < d:
        d = d1
    if d2 < d:
        d = d2
    if d3 < d:
        d = d3
    return d


@fieldwise_init
struct Segment(Copyable, Movable):
    var a: Vec2
    var b: Vec2

    fn aabb(self) -> AABB:
        return AABB(min(self.a.x, self.b.x), min(self.a.y, self.b.y), max(self.a.x, self.b.x), max(self.a.y, self.b.y))


@fieldwise_init
struct Circle(Copyable, Movable):
    var c: Vec2
    var r: Float64

    fn aabb(self) -> AABB:
        return AABB(self.c.x - self.r, self.c.y - self.r, self.c.x + self.r, self.c.y + self.r)


fn dist_circle_segment2(circle: Circle, seg: Segment) -> Float64:
    return dist_point_segment2(circle.c, seg.a, seg.b)


fn circle_intersects_segment(circle: Circle, seg: Segment) -> Bool:
    return dist_circle_segment2(circle, seg) <= circle.r * circle.r


fn circle_intersects_circle(a: Circle, b: Circle) -> Bool:
    var r = a.r + b.r
    return dist2(a.c, b.c) <= r * r


fn point_in_polygon(p: Vec2, poly: List[Vec2]) -> Bool:
    # Ray casting algorithm. Assumes polygon is closed implicitly.
    if len(poly) < 3:
        return False
    var inside = False
    var j = len(poly) - 1
    var i = 0
    while i < len(poly):
        var pi = poly[i].copy()
        var pj = poly[j].copy()
        var yi = pi.y
        var yj = pj.y
        var xi = pi.x
        var xj = pj.x
        # Check if edge crosses the horizontal ray at p.y.
        var intersect = ((yi > p.y) != (yj > p.y)) and (p.x < (xj - xi) * (p.y - yi) / (yj - yi + Float64(0.0)) + xi)
        if intersect:
            inside = not inside
        j = i
        i += 1
    return inside


fn dist_point_polygon2(p: Vec2, poly: List[Vec2]) -> Float64:
    if len(poly) < 2:
        return Float64(0.0)
    # If inside, distance is 0.
    if point_in_polygon(p, poly):
        return Float64(0.0)
    var best = Float64(1e30)
    var j = len(poly) - 1
    var i = 0
    while i < len(poly):
        var a = poly[j].copy()
        var b = poly[i].copy()
        var d = dist_point_segment2(p, a, b)
        if d < best:
            best = d
        j = i
        i += 1
    return best


fn dist_segment_polygon2(a: Vec2, b: Vec2, poly: List[Vec2]) -> Float64:
    if len(poly) < 2:
        return Float64(0.0)
    # If the segment intersects polygon edges or has an endpoint inside, dist is 0.
    if point_in_polygon(a, poly) or point_in_polygon(b, poly):
        return Float64(0.0)
    var best = Float64(1e30)
    var j = len(poly) - 1
    var i = 0
    while i < len(poly):
        var c0 = poly[j].copy()
        var c1 = poly[i].copy()
        var d = dist_segment_segment2(a, b, c0, c1)
        if d < best:
            best = d
        j = i
        i += 1
    return best
