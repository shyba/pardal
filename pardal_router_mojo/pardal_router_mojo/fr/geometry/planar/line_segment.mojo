"""Port of `app.freerouting.geometry.planar.LineSegment` (subset).

For Phase-1/2 work we need:
- construction from 3 lines
- construction from `Polyline` (by index)
- `start_point_approx` / `end_point_approx`
- `bounding_box`
- `opposite`
"""

from math import ceil, floor

from .float_point import FloatPoint
from .int_box import IntBox
from .int_point import IntPoint
from .line import Line
from .polyline_shape import PolylineShapeBox
from .polyline import Polyline


@fieldwise_init
struct LineSegment(Movable):
    var start: Line
    var middle: Line
    var end: Line

    @staticmethod
    fn from_lines(start: Line, middle: Line, end: Line) -> LineSegment:
        # Store by value (copy endpoints) to avoid implicit copies.
        var s = Line.from_ints(start.a.x, start.a.y, start.b.x, start.b.y)
        var m = Line.from_ints(middle.a.x, middle.a.y, middle.b.x, middle.b.y)
        var e = Line.from_ints(end.a.x, end.a.y, end.b.x, end.b.y)
        var out = LineSegment(
            Line.from_ints(0, 0, 0, 0),
            Line.from_ints(0, 0, 0, 0),
            Line.from_ints(0, 0, 0, 0),
        )
        out.start = s^
        out.middle = m^
        out.end = e^
        return out^

    @staticmethod
    fn from_polyline(p: Polyline, no: Int) -> LineSegment:
        # Port of Java `LineSegment(Polyline p_polyline, int p_no)`.
        # Creates the `no`-th line segment of p for `no` between 1 and p.line_count()-2.
        if no <= 0 or no >= p.line_count() - 1:
            return LineSegment.from_lines(
                Line.from_ints(0, 0, 0, 0),
                Line.from_ints(0, 0, 0, 0),
                Line.from_ints(0, 0, 0, 0),
            )
        return LineSegment.from_lines(p.line(no - 1), p.line(no), p.line(no + 1))

    @staticmethod
    fn from_polyline_shape_box(shape: PolylineShapeBox, no: Int) -> LineSegment:
        # Port of Java `LineSegment(PolylineShape p_shape, int p_no)` for the box case.
        var line_count = shape.border_line_count()
        if no < 0 or no >= line_count:
            return LineSegment.from_lines(
                Line.from_ints(0, 0, 0, 0),
                Line.from_ints(0, 0, 0, 0),
                Line.from_ints(0, 0, 0, 0),
            )
        var start: Line
        if no == 0:
            start = shape.border_line(line_count - 1)
        else:
            start = shape.border_line(no - 1)
        var middle = shape.border_line(no)
        var end: Line
        if no == line_count - 1:
            end = shape.border_line(0)
        else:
            end = shape.border_line(no + 1)
        return LineSegment.from_lines(start, middle, end)

    fn start_point_approx(self) -> FloatPoint:
        return self.start.intersection_approx(self.middle)

    fn end_point_approx(self) -> FloatPoint:
        return self.end.intersection_approx(self.middle)

    fn opposite(self) -> LineSegment:
        return LineSegment.from_lines(
            self.end.opposite(), self.middle.opposite(), self.start.opposite()
        )

    fn bounding_box(self) -> IntBox:
        var sc = self.middle.intersection_approx(self.start)
        var ec = self.middle.intersection_approx(self.end)
        var llx = sc.x if sc.x < ec.x else ec.x
        var lly = sc.y if sc.y < ec.y else ec.y
        var urx = sc.x if sc.x > ec.x else ec.x
        var ury = sc.y if sc.y > ec.y else ec.y
        var lower_left = IntPoint(Int(floor(llx)), Int(floor(lly)))
        var upper_right = IntPoint(Int(ceil(urx)), Int(ceil(ury)))
        return IntBox(
            IntPoint(lower_left.x, lower_left.y),
            IntPoint(upper_right.x, upper_right.y),
        )
