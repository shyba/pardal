"""Port of `app.freerouting.geometry.planar.Polyline` (minimal subset).

Mojo constraint: `List[T]` requires `T: Copyable` and many structs here are not
`ImplicitlyCopyable` in practice. To keep this hot-path friendly and simple, we
store the polyline as parallel int arrays of line endpoints.

This supports:
- construction from a list of Lines (by copying their endpoint ints)
- consecutive-parallel filtering
- `line_count`
- `corner_approx(i)` as intersection of consecutive lines
"""

from collections import List

from .float_point import FloatPoint
from .int_box import IntBox
from .line import Line
from .line_segment import LineSegment


@fieldwise_init
struct Polyline(Movable):
    var ax: List[Int]
    var ay: List[Int]
    var bx: List[Int]
    var by: List[Int]

    @staticmethod
    fn empty() -> Polyline:
        return Polyline(List[Int](), List[Int](), List[Int](), List[Int]())

    @staticmethod
    fn from_segments(
        ax_in: List[Int], ay_in: List[Int], bx_in: List[Int], by_in: List[Int]
    ) -> Polyline:
        # Each index i defines a directed line from (ax[i],ay[i]) to (bx[i],by[i]).
        if len(ax_in) < 3:
            return Polyline.empty()
        if (
            len(ax_in) != len(ay_in)
            or len(ax_in) != len(bx_in)
            or len(ax_in) != len(by_in)
        ):
            return Polyline.empty()

        var ax = List[Int]()
        var ay = List[Int]()
        var bx = List[Int]()
        var by = List[Int]()

        ax.append(ax_in[0])
        ay.append(ay_in[0])
        bx.append(bx_in[0])
        by.append(by_in[0])
        var prev_dx = bx_in[0] - ax_in[0]
        var prev_dy = by_in[0] - ay_in[0]

        var i = 1
        while i < len(ax_in):
            var dx = bx_in[i] - ax_in[i]
            var dy = by_in[i] - ay_in[i]
            if Int64(prev_dx) * Int64(dy) - Int64(prev_dy) * Int64(dx) != 0:
                ax.append(ax_in[i])
                ay.append(ay_in[i])
                bx.append(bx_in[i])
                by.append(by_in[i])
                prev_dx = dx
                prev_dy = dy
            i += 1

        if len(ax) < 3:
            return Polyline.empty()
        var out = Polyline.empty()
        out.ax = ax^
        out.ay = ay^
        out.bx = bx^
        out.by = by^
        return out^

    fn line_count(self) -> Int:
        return len(self.ax)

    fn line(self, i: Int) -> Line:
        return Line.from_ints(self.ax[i], self.ay[i], self.bx[i], self.by[i])

    fn corner_approx(self, i: Int) -> FloatPoint:
        return self.line(i).intersection_approx(self.line(i + 1))

    fn offset_box(self, half_width: Int, no: Int) -> IntBox:
        # Port of Java `Polyline.offset_box(int p_half_width, int p_no)`.
        # 0 <= no <= line_count() - 3
        if no < 0 or no > self.line_count() - 3:
            return IntBox.empty()
        var seg = LineSegment.from_polyline(self, no + 1)
        return seg.bounding_box().offset(half_width)
