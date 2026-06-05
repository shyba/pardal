"""Port of `app.freerouting.geometry.planar.PolylineShape` (minimal concrete shapes).

FreeRouting models a hierarchy:
- PolylineShape (abstract)
- TileShape (convex polyline border)
- RegularTileShape (tile shape with "regular" border order)
- IntBox/IntOctagon/... as concrete implementations

Mojo has no Java-style inheritance; for parity porting we start with concrete
wrappers that expose the methods the router core expects.
"""

from .float_point import FloatPoint
from .int_box import IntBox
from .int_point import IntPoint
from .line import Line


@fieldwise_init
struct PolylineShapeBox(Copyable, Movable):
    var box: IntBox

    fn is_empty(self) -> Bool:
        return self.box.is_empty()

    fn border_line_count(self) -> Int:
        if self.box.is_empty():
            return 0
        return 4

    fn border_line(self, no: Int) -> Line:
        # Counter-clockwise, starting with the smallest direction (RIGHT).
        # 0: bottom (RIGHT), 1: right (UP), 2: top (LEFT), 3: left (DOWN)
        if self.box.is_empty():
            return Line.from_ints(0, 0, 0, 0)
        if no == 0:
            return Line.from_points(
                IntPoint(self.box.ll.x, self.box.ll.y),
                IntPoint(self.box.ur.x, self.box.ll.y),
            )
        if no == 1:
            return Line.from_points(
                IntPoint(self.box.ur.x, self.box.ll.y),
                IntPoint(self.box.ur.x, self.box.ur.y),
            )
        if no == 2:
            return Line.from_points(
                IntPoint(self.box.ur.x, self.box.ur.y),
                IntPoint(self.box.ll.x, self.box.ur.y),
            )
        if no == 3:
            return Line.from_points(
                IntPoint(self.box.ll.x, self.box.ur.y),
                IntPoint(self.box.ll.x, self.box.ll.y),
            )
        return Line.from_ints(0, 0, 0, 0)

    fn corner_approx(self, no: Int) -> FloatPoint:
        if self.box.is_empty():
            return FloatPoint(0.0, 0.0)
        var p = self.box.corner(no)
        return FloatPoint(Float64(p.x), Float64(p.y))
