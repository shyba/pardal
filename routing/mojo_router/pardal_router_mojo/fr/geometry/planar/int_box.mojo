"""Port of `app.freerouting.geometry.planar.IntBox` (subset).

In FreeRouting this is a `RegularTileShape`; we port the concrete geometry
operations first and introduce the shape hierarchy later.
"""

from math import sqrt

from .int_point import IntPoint
from .float_point import FloatPoint
from .limits import crit_int
from .int_octagon import IntOctagon


@fieldwise_init
struct IntBox(Copyable, Movable):
    var ll: IntPoint
    var ur: IntPoint

    @staticmethod
    fn empty() -> IntBox:
        # FreeRouting: EMPTY = (CRIT_INT,CRIT_INT) to (-CRIT_INT,-CRIT_INT)
        var c = crit_int()
        return IntBox(IntPoint(c, c), IntPoint(-c, -c))

    fn is_empty(self) -> Bool:
        return self.ll.x > self.ur.x or self.ll.y > self.ur.y

    fn width(self) -> Int:
        return self.ur.x - self.ll.x

    fn height(self) -> Int:
        return self.ur.y - self.ll.y

    fn max_width(self) -> Float64:
        var wx = Float64(self.ur.x - self.ll.x)
        var hy = Float64(self.ur.y - self.ll.y)
        if wx > hy:
            return wx
        return hy

    fn min_width(self) -> Float64:
        var wx = Float64(self.ur.x - self.ll.x)
        var hy = Float64(self.ur.y - self.ll.y)
        if wx < hy:
            return wx
        return hy

    fn area(self) -> Float64:
        return Float64(self.ur.x - self.ll.x) * Float64(self.ur.y - self.ll.y)

    fn circumference(self) -> Float64:
        return 2.0 * (Float64(self.ur.x - self.ll.x) + Float64(self.ur.y - self.ll.y))

    fn corner(self, no: Int) -> IntPoint:
        if no == 0:
            return self.ll
        if no == 1:
            return IntPoint(self.ur.x, self.ll.y)
        if no == 2:
            return self.ur
        if no == 3:
            return IntPoint(self.ll.x, self.ur.y)
        raise Error("IntBox.corner: no out of range")

    fn dimension(self) -> Int:
        if self.is_empty():
            return -1
        if self.ll.equals(self.ur):
            return 0
        if self.ur.x == self.ll.x or self.ll.y == self.ur.y:
            return 1
        return 2

    fn contains_inside(self, p: IntPoint) -> Bool:
        return (
            p.x > self.ll.x and p.x < self.ur.x and p.y > self.ll.y and p.y < self.ur.y
        )

    fn nearest_point(self, p: FloatPoint) -> FloatPoint:
        var x: Float64
        if p.x <= Float64(self.ll.x):
            x = Float64(self.ll.x)
        elif p.x >= Float64(self.ur.x):
            x = Float64(self.ur.x)
        else:
            x = p.x

        var y: Float64
        if p.y <= Float64(self.ll.y):
            y = Float64(self.ll.y)
        elif p.y >= Float64(self.ur.y):
            y = Float64(self.ur.y)
        else:
            y = p.y
        return FloatPoint(x, y)

    fn distance(self, p: FloatPoint) -> Float64:
        var n = self.nearest_point(p)
        return p.distance(n)

    fn union(self, other: IntBox) -> IntBox:
        var llx = self.ll.x if self.ll.x < other.ll.x else other.ll.x
        var lly = self.ll.y if self.ll.y < other.ll.y else other.ll.y
        var urx = self.ur.x if self.ur.x > other.ur.x else other.ur.x
        var ury = self.ur.y if self.ur.y > other.ur.y else other.ur.y
        return IntBox(IntPoint(llx, lly), IntPoint(urx, ury))

    fn intersection(self, other: IntBox) -> IntBox:
        if other.ll.x > self.ur.x:
            return IntBox.empty()
        if other.ll.y > self.ur.y:
            return IntBox.empty()
        if self.ll.x > other.ur.x:
            return IntBox.empty()
        if self.ll.y > other.ur.y:
            return IntBox.empty()
        var llx = self.ll.x if self.ll.x > other.ll.x else other.ll.x
        var urx = self.ur.x if self.ur.x < other.ur.x else other.ur.x
        var lly = self.ll.y if self.ll.y > other.ll.y else other.ll.y
        var ury = self.ur.y if self.ur.y < other.ur.y else other.ur.y
        return IntBox(IntPoint(llx, lly), IntPoint(urx, ury))

    fn offset(self, dist: Float64) -> IntBox:
        if dist == 0.0 or self.is_empty():
            return IntBox(
                IntPoint(self.ll.x, self.ll.y), IntPoint(self.ur.x, self.ur.y)
            )
        var d = Int(round(dist))
        return IntBox(
            IntPoint(self.ll.x - d, self.ll.y - d),
            IntPoint(self.ur.x + d, self.ur.y + d),
        )

    fn horizontal_offset(self, dist: Float64) -> IntBox:
        if dist == 0.0 or self.is_empty():
            return IntBox(
                IntPoint(self.ll.x, self.ll.y), IntPoint(self.ur.x, self.ur.y)
            )
        var d = Int(round(dist))
        return IntBox(
            IntPoint(self.ll.x - d, self.ll.y), IntPoint(self.ur.x + d, self.ur.y)
        )

    fn vertical_offset(self, dist: Float64) -> IntBox:
        if dist == 0.0 or self.is_empty():
            return IntBox(
                IntPoint(self.ll.x, self.ll.y), IntPoint(self.ur.x, self.ur.y)
            )
        var d = Int(round(dist))
        return IntBox(
            IntPoint(self.ll.x, self.ll.y - d), IntPoint(self.ur.x, self.ur.y + d)
        )

    fn shrink(self, width: Int) -> IntBox:
        # Port of `IntBox.shrink(int)`; box will not vanish completely.
        var ll_x: Int
        var ur_x: Int
        if 2 * width <= self.ur.x - self.ll.x:
            ll_x = self.ll.x + width
            ur_x = self.ur.x - width
        else:
            ll_x = (self.ll.x + self.ur.x) // 2
            ur_x = ll_x
        var ll_y: Int
        var ur_y: Int
        if 2 * width <= self.ur.y - self.ll.y:
            ll_y = self.ll.y + width
            ur_y = self.ur.y - width
        else:
            ll_y = (self.ll.y + self.ur.y) // 2
            ur_y = ll_y
        return IntBox(IntPoint(ll_x, ll_y), IntPoint(ur_x, ur_y))

    fn intersects(self, other: IntBox) -> Bool:
        # Port of `IntBox.intersects(IntBox)`
        if other.ll.x > self.ur.x:
            return False
        if other.ll.y > self.ur.y:
            return False
        if self.ll.x > other.ur.x:
            return False
        return self.ll.y <= other.ur.y

    fn overlaps(self, other: IntBox) -> Bool:
        # Port of `IntBox.overlaps(IntBox)` (strict 2D overlap)
        if other.ll.x >= self.ur.x:
            return False
        if other.ll.y >= self.ur.y:
            return False
        if self.ll.x >= other.ur.x:
            return False
        return self.ll.y < other.ur.y

    fn to_octagon(self) -> IntOctagon:
        return IntOctagon.from_box(self.ll.x, self.ll.y, self.ur.x, self.ur.y)
