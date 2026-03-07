"""Port of `app.freerouting.geometry.planar.Line` (IntPoint-only subset).

FreeRouting supports generic `Point`/`Vector`/`Direction` hierarchies; we start
with the core integer geometry paths used by the router (orthogonal/45-degree).
"""

from .direction import get_instance_from_vector
from .float_point import FloatPoint
from .int_direction import IntDirection
from .int_point import IntPoint
from .side import Side

@fieldwise_init
struct Line(Copyable, Movable):
    var a: IntPoint
    var b: IntPoint
    var _has_dir: Bool
    var _dir: IntDirection

    @staticmethod
    fn from_points(a: IntPoint, b: IntPoint) -> Line:
        return Line(IntPoint(a.x, a.y), IntPoint(b.x, b.y), False, IntDirection(0, 0))

    @staticmethod
    fn from_ints(ax: Int, ay: Int, bx: Int, by: Int) -> Line:
        return Line(IntPoint(ax, ay), IntPoint(bx, by), False, IntDirection(0, 0))

    @staticmethod
    fn from_point_dir(a: IntPoint, d: IntDirection) -> Line:
        var b = a.translate_by(d.get_vector())
        return Line(IntPoint(a.x, a.y), IntPoint(b.x, b.y), True, IntDirection(d.x, d.y))

    fn direction(mut self) -> IntDirection:
        if not self._has_dir:
            var v = self.b.difference_by(self.a)
            self._dir = get_instance_from_vector(v)
            self._has_dir = True
        return IntDirection(self._dir.x, self._dir.y)

    fn side_of_point(self, p: IntPoint) -> Side:
        var dx = self.b.x - self.a.x
        var dy = self.b.y - self.a.y
        var px = p.x - self.a.x
        var py = p.y - self.a.y
        var det = Float64(dx) * Float64(py) - Float64(dy) * Float64(px)
        return Side.of(det)

    fn side_of_float(self, p: FloatPoint, tolerance: Float64) -> Side:
        var dx = Float64(self.b.x - self.a.x)
        var dy = Float64(self.b.y - self.a.y)
        var det = dy * (p.x - Float64(self.a.x)) - dx * (p.y - Float64(self.a.y))
        if det - tolerance > 0.0:
            return Side.on_the_left()
        if det + tolerance < 0.0:
            return Side.on_the_right()
        return Side.collinear()

    fn overlaps(self, other: Line) -> Bool:
        return self.side_of_point(other.a).to_string() == Side.collinear().to_string() and self.side_of_point(other.b).to_string() == Side.collinear().to_string()

    fn is_parallel(self, other: Line) -> Bool:
        # Parallel if direction vectors are collinear.
        var v1 = self.b.difference_by(self.a)
        var v2 = other.b.difference_by(other.a)
        return v1.determinant(v2) == 0

    fn opposite(self) -> Line:
        return Line.from_points(self.b, self.a)

    fn intersection_approx(self, other: Line) -> FloatPoint:
        # Float intersection for general case (used by Polyline corner approx).
        var p1 = FloatPoint(Float64(self.a.x), Float64(self.a.y))
        var p2 = FloatPoint(Float64(self.b.x), Float64(self.b.y))
        var p3 = FloatPoint(Float64(other.a.x), Float64(other.a.y))
        var p4 = FloatPoint(Float64(other.b.x), Float64(other.b.y))
        var den = (p1.x - p2.x) * (p3.y - p4.y) - (p1.y - p2.y) * (p3.x - p4.x)
        if den == 0.0:
            return FloatPoint(0.0, 0.0)
        var x = ((p1.x * p2.y - p1.y * p2.x) * (p3.x - p4.x) - (p1.x - p2.x) * (p3.x * p4.y - p3.y * p4.x)) / den
        var y = ((p1.x * p2.y - p1.y * p2.x) * (p3.y - p4.y) - (p1.y - p2.y) * (p3.x * p4.y - p3.y * p4.x)) / den
        return FloatPoint(x, y)

    fn intersection(self, other: Line) -> IntPoint:
        var d1 = self.b.difference_by(self.a)
        var d2 = other.b.difference_by(other.a)

        if d1.x == 0:
            if d2.y == 0:
                return IntPoint(self.a.x, other.a.y)
            if d2.x == d2.y:
                var this_x = self.a.x
                return IntPoint(this_x, other.a.y + this_x - other.a.x)
            if d2.x == -d2.y:
                var this_x = self.a.x
                return IntPoint(this_x, other.a.y + other.a.x - this_x)
        elif d1.y == 0:
            if d2.x == 0:
                return IntPoint(other.a.x, self.a.y)
            if d2.x == d2.y:
                var this_y = self.a.y
                return IntPoint(other.a.x + this_y - other.a.y, this_y)
            if d2.x == -d2.y:
                var this_y = self.a.y
                return IntPoint(other.a.x + other.a.y - this_y, this_y)
        elif d1.x == d1.y:
            if d2.x == 0:
                var other_x = other.a.x
                return IntPoint(other_x, self.a.y + other_x - self.a.x)
            if d2.y == 0:
                var other_y = other.a.y
                return IntPoint(self.a.x + other_y - self.a.y, other_y)
        elif d1.x == -d1.y:
            if d2.x == 0:
                var other_x = other.a.x
                return IntPoint(other_x, self.a.y + self.a.x - other_x)
            if d2.y == 0:
                var other_y = other.a.y
                return IntPoint(self.a.x + self.a.y - other_y, other_y)

        return self.intersection_approx(other).round()
