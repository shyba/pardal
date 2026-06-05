"""Port of `app.freerouting.geometry.planar.TileShape` (very small box-only subset).

This exists to unblock line-by-line ports that refer to `TileShape`.
Initially we only support the `IntBox` concrete implementation.
"""

from .int_box import IntBox
from .int_octagon import IntOctagon
from .int_point import IntPoint
from .line import Line
from .polyline_shape import PolylineShapeBox


@fieldwise_init
struct TileShapeBox(Copyable, Movable):
    var box: IntBox

    fn is_empty(self) -> Bool:
        return self.box.is_empty()

    fn bounding_box(self) -> IntBox:
        return IntBox(
            IntPoint(self.box.ll.x, self.box.ll.y),
            IntPoint(self.box.ur.x, self.box.ur.y),
        )

    fn border_line_count(self) -> Int:
        return PolylineShapeBox(self.box).border_line_count()

    fn border_line(self, no: Int) -> Line:
        return PolylineShapeBox(self.box).border_line(no)

    fn intersection(self, other: TileShapeBox) -> TileShapeBox:
        return TileShapeBox(self.box.intersection(other.box))

    fn union_box(self, other: TileShapeBox) -> TileShapeBox:
        return TileShapeBox(self.box.union(other.box))

    fn overlaps(self, other: TileShapeBox) -> Bool:
        return self.box.overlaps(other.box)

    fn contains(self, other: TileShapeBox) -> Bool:
        if self.box.is_empty() or other.box.is_empty():
            return False
        return (
            other.box.ll.x >= self.box.ll.x
            and other.box.ll.y >= self.box.ll.y
            and other.box.ur.x <= self.box.ur.x
            and other.box.ur.y <= self.box.ur.y
        )


@fieldwise_init
struct TileShapeOctagon(Copyable, Movable):
    var oct: IntOctagon

    fn is_empty(self) -> Bool:
        return self.oct.is_empty()

    fn bounding_box(self) -> IntBox:
        return self.oct.bounding_box()

    fn border_line_count(self) -> Int:
        if self.oct.is_empty():
            return 0
        return self.oct.border_line_count()

    fn border_line(self, no: Int) -> Line:
        return self.oct.border_line(no)

    fn intersection(self, other: TileShapeOctagon) -> TileShapeOctagon:
        return TileShapeOctagon(self.oct.intersection(other.oct))

    fn union_shape(self, other: TileShapeOctagon) -> TileShapeOctagon:
        return TileShapeOctagon(self.oct.union(other.oct))

    fn overlaps(self, other: TileShapeOctagon) -> Bool:
        return self.oct.overlaps(other.oct)

    fn contains(self, other: TileShapeOctagon) -> Bool:
        if self.oct.is_empty() or other.oct.is_empty():
            return False
        return other.oct.is_contained_in(self.oct)
