"""Port of `app.freerouting.geometry.planar.IntVector` (subset).

Note: FreeRouting uses an abstract `Vector` hierarchy. For the initial port we
keep the concrete IntVector behavior and add other vector types later.
"""

from ...datastructures.big_int_aux import binary_gcd
from ...datastructures.signum import Signum
from .int_direction import IntDirection
from .side import Side
from .float_point import FloatPoint

@fieldwise_init
struct IntVector(Copyable, Movable):
    var x: Int
    var y: Int

    fn equals(self, other: IntVector) -> Bool:
        return self.x == other.x and self.y == other.y

    fn is_zero(self) -> Bool:
        return self.x == 0 and self.y == 0

    fn negate(self) -> IntVector:
        return IntVector(-self.x, -self.y)

    fn is_orthogonal(self) -> Bool:
        return self.x == 0 or self.y == 0

    fn is_diagonal(self) -> Bool:
        var ax = self.x
        if ax < 0:
            ax = -ax
        var ay = self.y
        if ay < 0:
            ay = -ay
        return ax == ay

    fn determinant(self, other: IntVector) -> Int64:
        return Int64(self.x) * Int64(other.y) - Int64(self.y) * Int64(other.x)

    fn turn_90_degree(self, factor: Int) -> IntVector:
        var n = factor
        while n < 0:
            n += 4
        while n >= 4:
            n -= 4
        if n == 0:
            return IntVector(self.x, self.y)
        if n == 1:
            return IntVector(-self.y, self.x)
        if n == 2:
            return IntVector(-self.x, -self.y)
        if n == 3:
            return IntVector(self.y, -self.x)
        return IntVector(0, 0)

    fn mirror_at_y_axis(self) -> IntVector:
        return IntVector(-self.x, self.y)

    fn mirror_at_x_axis(self) -> IntVector:
        return IntVector(self.x, -self.y)

    fn side_of(self, other: IntVector) -> Side:
        var det = Float64(other.x) * Float64(self.y) - Float64(other.y) * Float64(self.x)
        return Side.of(det)

    fn projection(self, other: IntVector) -> Signum:
        var tmp = Float64(self.x) * Float64(other.x) + Float64(self.y) * Float64(other.y)
        return Signum.of(tmp)

    fn scalar_product(self, other: IntVector) -> Float64:
        return Float64(self.x) * Float64(other.x) + Float64(self.y) * Float64(other.y)

    fn to_float(self) -> FloatPoint:
        return FloatPoint(Float64(self.x), Float64(self.y))

    fn to_normalized_direction(self) -> IntDirection:
        var dx = self.x
        var dy = self.y
        var adx = dx
        if adx < 0:
            adx = -adx
        var ady = dy
        if ady < 0:
            ady = -ady
        var gcd = binary_gcd(adx, ady)
        if gcd > 1:
            dx //= gcd
            dy //= gcd
        return IntDirection(dx, dy)
