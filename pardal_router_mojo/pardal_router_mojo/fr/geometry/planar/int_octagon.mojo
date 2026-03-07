"""Port of `app.freerouting.geometry.planar.IntOctagon` (subset).

This is a core shape for FreeRouting (45-degree regular tile shapes).

Port scope (initial):
- construction + EMPTY
- `dimension()`
- `corner_x/corner_y` and `corner()`
- `bounding_box()` (via `IntBox`)
- `contains(FloatPoint)`
- `normalize()` (exact port; critical invariant)
- `side_of_border_line` (needed by 45° search tree)
- `intersection/union/intersects/overlaps` (needed by 45° search tree)
- `is_contained_in(IntOctagon)` (needed by ignore-door logic)
- `border_line` / `border_line_count` (needed by 45° restrain)
- `offset` (needed by clearance compensation + octagon trees)
- `side_of_line` (needed by 45° restrain)
"""

from math import ceil, floor

from .float_point import FloatPoint
from .int_box import IntBox
from .int_point import IntPoint
from .limits import crit_int, sqrt2
from .line import Line
from .side import Side


@fieldwise_init
struct IntOctagon(Copyable, Movable):
    var leftX: Int
    var rightX: Int
    var bottomY: Int
    var topY: Int
    var lowerLeftDiagonalX: Int
    var upperRightDiagonalX: Int
    var upperLeftDiagonalX: Int
    var lowerRightDiagonalX: Int

    @staticmethod
    fn empty() -> IntOctagon:
        var c = crit_int()
        # Match FreeRouting's EMPTY fields (invalid bounds sentinel).
        # Java: (CRIT_INT, CRIT_INT, -CRIT_INT, -CRIT_INT, CRIT_INT, -CRIT_INT, CRIT_INT, -CRIT_INT)
        # Here ordering is: leftX, rightX, bottomY, topY, llx, urx, ulx, lrx
        return IntOctagon(c, -c, c, -c, c, c, -c, -c)

    @staticmethod
    fn from_freerouting(
        leftX: Int,
        bottomY: Int,
        rightX: Int,
        topY: Int,
        upperLeftDiagonalX: Int,
        lowerRightDiagonalX: Int,
        lowerLeftDiagonalX: Int,
        upperRightDiagonalX: Int,
    ) -> IntOctagon:
        # FreeRouting constructor order:
        # (leftX, bottomY, rightX, topY, upperLeftDiag, lowerRightDiag, lowerLeftDiag, upperRightDiag)
        return IntOctagon(
            leftX,
            rightX,
            bottomY,
            topY,
            lowerLeftDiagonalX,
            upperRightDiagonalX,
            upperLeftDiagonalX,
            lowerRightDiagonalX,
        )

    @staticmethod
    fn from_box(llx: Int, lly: Int, urx: Int, ury: Int) -> IntOctagon:
        # A box-shaped octagon around an axis-aligned IntBox.
        return IntOctagon.from_freerouting(
            llx,
            lly,
            urx,
            ury,
            llx - ury,
            urx - lly,
            llx + lly,
            urx + ury,
        ).normalize()

    fn is_empty(self) -> Bool:
        # FreeRouting uses an identity singleton. Here we treat any invalid bounds as empty.
        return (
            self.leftX > self.rightX
            or self.bottomY > self.topY
            or self.lowerLeftDiagonalX > self.upperRightDiagonalX
            or self.upperLeftDiagonalX > self.lowerRightDiagonalX
        )

    fn bounding_box(self) -> IntBox:
        return IntBox(
            IntPoint(self.leftX, self.bottomY), IntPoint(self.rightX, self.topY)
        )

    fn border_line_count(self) -> Int:
        return 8

    fn border_line(self, no: Int) -> Line:
        # Port of Java `IntOctagon.border_line(int)`.
        var ax: Int
        var ay: Int
        var bx: Int
        var by: Int
        if no == 0:
            ax = 0
            ay = self.bottomY
            bx = 1
            by = self.bottomY
        elif no == 1:
            ax = self.lowerRightDiagonalX
            ay = 0
            bx = self.lowerRightDiagonalX + 1
            by = 1
        elif no == 2:
            ax = self.rightX
            ay = 0
            bx = self.rightX
            by = 1
        elif no == 3:
            ax = self.upperRightDiagonalX
            ay = 0
            bx = self.upperRightDiagonalX - 1
            by = 1
        elif no == 4:
            ax = 0
            ay = self.topY
            bx = -1
            by = self.topY
        elif no == 5:
            ax = self.upperLeftDiagonalX
            ay = 0
            bx = self.upperLeftDiagonalX - 1
            by = -1
        elif no == 6:
            ax = self.leftX
            ay = 0
            bx = self.leftX
            by = -1
        elif no == 7:
            ax = self.lowerLeftDiagonalX
            ay = 0
            bx = self.lowerLeftDiagonalX + 1
            by = -1
        else:
            ax = 0
            ay = 0
            bx = 0
            by = 0
        return Line.from_ints(ax, ay, bx, by)

    fn dimension(self) -> Int:
        if self.is_empty():
            return -1
        if (
            self.rightX > self.leftX
            and self.topY > self.bottomY
            and self.lowerRightDiagonalX > self.upperLeftDiagonalX
            and self.upperRightDiagonalX > self.lowerLeftDiagonalX
        ):
            return 2
        if self.rightX == self.leftX and self.topY == self.bottomY:
            return 0
        return 1

    fn corner_x(self, no: Int) -> Int:
        if no == 0:
            return self.lowerLeftDiagonalX - self.bottomY
        if no == 1:
            return self.lowerRightDiagonalX + self.bottomY
        if no == 2 or no == 3:
            return self.rightX
        if no == 4:
            return self.upperRightDiagonalX - self.topY
        if no == 5:
            return self.upperLeftDiagonalX + self.topY
        if no == 6 or no == 7:
            return self.leftX
        return 0

    fn corner_y(self, no: Int) -> Int:
        if no == 0 or no == 1:
            return self.bottomY
        if no == 2:
            return self.rightX - self.lowerRightDiagonalX
        if no == 3:
            return self.upperRightDiagonalX - self.rightX
        if no == 4 or no == 5:
            return self.topY
        if no == 6:
            return self.leftX - self.upperLeftDiagonalX
        if no == 7:
            return self.lowerLeftDiagonalX - self.leftX
        return 0

    fn corner(self, no: Int) -> IntPoint:
        return IntPoint(self.corner_x(no), self.corner_y(no))

    fn max_width(self) -> Float64:
        var w1 = Float64(self.rightX - self.leftX)
        var h1 = Float64(self.topY - self.bottomY)
        var width_1 = w1 if w1 > h1 else h1
        var d1 = Float64(self.upperRightDiagonalX - self.lowerLeftDiagonalX)
        var d2 = Float64(self.lowerRightDiagonalX - self.upperLeftDiagonalX)
        var width2 = d1 if d1 > d2 else d2
        var s2 = sqrt2()
        var v = width2 / s2
        return width_1 if width_1 > v else v

    fn min_width(self) -> Float64:
        var w1 = Float64(self.rightX - self.leftX)
        var h1 = Float64(self.topY - self.bottomY)
        var width_1 = w1 if w1 < h1 else h1
        var d1 = Float64(self.upperRightDiagonalX - self.lowerLeftDiagonalX)
        var d2 = Float64(self.lowerRightDiagonalX - self.upperLeftDiagonalX)
        var width2 = d1 if d1 < d2 else d2
        var s2 = sqrt2()
        var v = width2 / s2
        return width_1 if width_1 < v else v

    fn contains(self, p: FloatPoint) -> Bool:
        if (
            Float64(self.leftX) > p.x
            or Float64(self.bottomY) > p.y
            or Float64(self.rightX) < p.x
            or Float64(self.topY) < p.y
        ):
            return False
        var tmp1 = p.x - p.y
        var tmp2 = p.x + p.y
        if Float64(self.upperLeftDiagonalX) > tmp1:
            return False
        if Float64(self.lowerRightDiagonalX) < tmp1:
            return False
        if Float64(self.lowerLeftDiagonalX) > tmp2:
            return False
        if Float64(self.upperRightDiagonalX) < tmp2:
            return False
        return True

    fn normalize(self) -> IntOctagon:
        # Direct port of `IntOctagon.normalize()`; critical for correctness.
        if (
            self.leftX > self.rightX
            or self.bottomY > self.topY
            or self.lowerLeftDiagonalX > self.upperRightDiagonalX
            or self.upperLeftDiagonalX > self.lowerRightDiagonalX
        ):
            return IntOctagon.empty()

        var new_lx = self.leftX
        var new_rx = self.rightX
        var new_ly = self.bottomY
        var new_uy = self.topY
        var new_llx = self.lowerLeftDiagonalX
        var new_ulx = self.upperLeftDiagonalX
        var new_lrx = self.lowerRightDiagonalX
        var new_urx = self.upperRightDiagonalX

        if new_lx < new_llx - new_uy:
            new_lx = new_llx - new_uy
        if new_lx < new_ulx + new_ly:
            new_lx = new_ulx + new_ly
        if new_rx > new_urx - new_ly:
            new_rx = new_urx - new_ly
        if new_rx > new_lrx + new_uy:
            new_rx = new_lrx + new_uy
        if new_ly < new_lx - new_lrx:
            new_ly = new_lx - new_lrx
        if new_ly < new_llx - new_rx:
            new_ly = new_llx - new_rx
        if new_uy > new_urx - new_lx:
            new_uy = new_urx - new_lx
        if new_uy > new_rx - new_ulx:
            new_uy = new_rx - new_ulx
        if new_llx - new_lx < new_ly:
            new_llx = new_lx + new_ly
        if new_rx - new_lrx < new_ly:
            new_lrx = new_rx - new_ly
        if new_urx - new_rx > new_uy:
            new_urx = new_uy + new_rx
        if new_lx - new_ulx > new_uy:
            new_ulx = new_lx - new_uy

        var diag_upper_y = Int(ceil(Float64(new_urx - new_ulx) / 2.0))
        if new_uy > diag_upper_y:
            new_uy = diag_upper_y

        var diag_lower_y = Int(floor(Float64(new_llx - new_lrx) / 2.0))
        if new_ly < diag_lower_y:
            new_ly = diag_lower_y

        var diag_right_x = Int(ceil(Float64(new_urx + new_lrx) / 2.0))
        if new_rx > diag_right_x:
            new_rx = diag_right_x

        var diag_left_x = Int(floor(Float64(new_llx + new_ulx) / 2.0))
        if new_lx < diag_left_x:
            new_lx = diag_left_x

        if new_lx > new_rx or new_ly > new_uy or new_llx > new_urx or new_ulx > new_lrx:
            return IntOctagon.empty()

        return IntOctagon(
            new_lx, new_rx, new_ly, new_uy, new_llx, new_urx, new_ulx, new_lrx
        )

    fn offset(self, distance: Float64) -> IntOctagon:
        # Port of Java `IntOctagon.offset(double)`.
        var width = Int(round(distance))
        if width == 0:
            return IntOctagon(
                self.leftX,
                self.rightX,
                self.bottomY,
                self.topY,
                self.lowerLeftDiagonalX,
                self.upperRightDiagonalX,
                self.upperLeftDiagonalX,
                self.lowerRightDiagonalX,
            )
        var dia_width = Int(round(sqrt2() * distance))
        var res = IntOctagon(
            self.leftX - width,
            self.rightX + width,
            self.bottomY - width,
            self.topY + width,
            self.lowerLeftDiagonalX - dia_width,
            self.upperRightDiagonalX + dia_width,
            self.upperLeftDiagonalX - dia_width,
            self.lowerRightDiagonalX + dia_width,
        )
        return res.normalize()

    fn side_of_line(self, line: Line) -> Side:
        # If corners lie strictly on one side: that side. Otherwise COLLINEAR.
        if self.is_empty():
            return Side.collinear()
        var seen_left = False
        var seen_right = False
        var i = 0
        while i < 8:
            var c = self.corner(i)
            var s = line.side_of_point(c)
            if s._value == 1:
                seen_left = True
            elif s._value == -1:
                seen_right = True
            else:
                return Side.collinear()
            if seen_left and seen_right:
                return Side.collinear()
            i += 1
        if seen_left:
            return Side.on_the_left()
        if seen_right:
            return Side.on_the_right()
        return Side.collinear()

    fn side_of_border_line(self, x: Int, y: Int, border_line_no: Int) -> Side:
        # Port of Java `IntOctagon.side_of_border_line(int,int,int)`.
        var tmp: Int
        if border_line_no == 0:
            tmp = self.bottomY - y
        elif border_line_no == 2:
            tmp = x - self.rightX
        elif border_line_no == 4:
            tmp = y - self.topY
        elif border_line_no == 6:
            tmp = self.leftX - x
        elif border_line_no == 1:
            tmp = x - y - self.lowerRightDiagonalX
        elif border_line_no == 3:
            tmp = x + y - self.upperRightDiagonalX
        elif border_line_no == 5:
            tmp = self.upperLeftDiagonalX + y - x
        elif border_line_no == 7:
            tmp = self.lowerLeftDiagonalX - x - y
        else:
            tmp = 0
        if tmp < 0:
            return Side.on_the_left()
        if tmp > 0:
            return Side.on_the_right()
        return Side.collinear()

    fn intersection(self, other: IntOctagon) -> IntOctagon:
        var res = IntOctagon(
            self.leftX if self.leftX > other.leftX else other.leftX,
            self.rightX if self.rightX < other.rightX else other.rightX,
            self.bottomY if self.bottomY > other.bottomY else other.bottomY,
            self.topY if self.topY < other.topY else other.topY,
            self.lowerLeftDiagonalX if self.lowerLeftDiagonalX
            > other.lowerLeftDiagonalX else other.lowerLeftDiagonalX,
            self.upperRightDiagonalX if self.upperRightDiagonalX
            < other.upperRightDiagonalX else other.upperRightDiagonalX,
            self.upperLeftDiagonalX if self.upperLeftDiagonalX
            > other.upperLeftDiagonalX else other.upperLeftDiagonalX,
            self.lowerRightDiagonalX if self.lowerRightDiagonalX
            < other.lowerRightDiagonalX else other.lowerRightDiagonalX,
        )
        return res.normalize()

    fn union(self, other: IntOctagon) -> IntOctagon:
        return IntOctagon(
            self.leftX if self.leftX < other.leftX else other.leftX,
            self.rightX if self.rightX > other.rightX else other.rightX,
            self.bottomY if self.bottomY < other.bottomY else other.bottomY,
            self.topY if self.topY > other.topY else other.topY,
            self.lowerLeftDiagonalX if self.lowerLeftDiagonalX
            < other.lowerLeftDiagonalX else other.lowerLeftDiagonalX,
            self.upperRightDiagonalX if self.upperRightDiagonalX
            > other.upperRightDiagonalX else other.upperRightDiagonalX,
            self.upperLeftDiagonalX if self.upperLeftDiagonalX
            < other.upperLeftDiagonalX else other.upperLeftDiagonalX,
            self.lowerRightDiagonalX if self.lowerRightDiagonalX
            > other.lowerRightDiagonalX else other.lowerRightDiagonalX,
        )

    fn intersects(self, other: IntOctagon) -> Bool:
        # Port of Java `IntOctagon.intersects(IntOctagon)`.
        var is_lx = self.leftX if self.leftX > other.leftX else other.leftX
        var is_rx = self.rightX if self.rightX < other.rightX else other.rightX
        if is_lx > is_rx:
            return False
        var is_ly = self.bottomY if self.bottomY > other.bottomY else other.bottomY
        var is_uy = self.topY if self.topY < other.topY else other.topY
        if is_ly > is_uy:
            return False
        var is_llx = (
            self.lowerLeftDiagonalX if self.lowerLeftDiagonalX
            > other.lowerLeftDiagonalX else other.lowerLeftDiagonalX
        )
        var is_urx = (
            self.upperRightDiagonalX if self.upperRightDiagonalX
            < other.upperRightDiagonalX else other.upperRightDiagonalX
        )
        if is_llx > is_urx:
            return False
        var is_ulx = (
            self.upperLeftDiagonalX if self.upperLeftDiagonalX
            > other.upperLeftDiagonalX else other.upperLeftDiagonalX
        )
        var is_lrx = (
            self.lowerRightDiagonalX if self.lowerRightDiagonalX
            < other.lowerRightDiagonalX else other.lowerRightDiagonalX
        )
        return is_ulx <= is_lrx

    fn overlaps(self, other: IntOctagon) -> Bool:
        # Port of Java `IntOctagon.overlaps(IntOctagon)` (2D intersection).
        var is_lx = self.leftX if self.leftX > other.leftX else other.leftX
        var is_rx = self.rightX if self.rightX < other.rightX else other.rightX
        if is_lx >= is_rx:
            return False
        var is_ly = self.bottomY if self.bottomY > other.bottomY else other.bottomY
        var is_uy = self.topY if self.topY < other.topY else other.topY
        if is_ly >= is_uy:
            return False
        var is_llx = (
            self.lowerLeftDiagonalX if self.lowerLeftDiagonalX
            > other.lowerLeftDiagonalX else other.lowerLeftDiagonalX
        )
        var is_urx = (
            self.upperRightDiagonalX if self.upperRightDiagonalX
            < other.upperRightDiagonalX else other.upperRightDiagonalX
        )
        if is_llx >= is_urx:
            return False
        var is_ulx = (
            self.upperLeftDiagonalX if self.upperLeftDiagonalX
            > other.upperLeftDiagonalX else other.upperLeftDiagonalX
        )
        var is_lrx = (
            self.lowerRightDiagonalX if self.lowerRightDiagonalX
            < other.lowerRightDiagonalX else other.lowerRightDiagonalX
        )
        return is_ulx < is_lrx

    fn is_contained_in(self, other: IntOctagon) -> Bool:
        return (
            self.leftX >= other.leftX
            and self.bottomY >= other.bottomY
            and self.rightX <= other.rightX
            and self.topY <= other.topY
            and self.lowerLeftDiagonalX >= other.lowerLeftDiagonalX
            and self.upperLeftDiagonalX >= other.upperLeftDiagonalX
            and self.lowerRightDiagonalX <= other.lowerRightDiagonalX
            and self.upperRightDiagonalX <= other.upperRightDiagonalX
        )
