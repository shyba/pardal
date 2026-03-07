"""Port of `app.freerouting.geometry.planar.FloatPoint` (subset)."""

from math import sqrt, floor, ceil

from .int_point import IntPoint
from .int_direction import IntDirection

@fieldwise_init
struct FloatPoint(Copyable, Movable):
    var x: Float64
    var y: Float64

    @staticmethod
    fn zero() -> FloatPoint:
        return FloatPoint(0.0, 0.0)

    fn size_square(self) -> Float64:
        return self.x * self.x + self.y * self.y

    fn size(self) -> Float64:
        return sqrt(self.size_square())

    fn distance_square(self, other: FloatPoint) -> Float64:
        var dx = other.x - self.x
        var dy = other.y - self.y
        return dx * dx + dy * dy

    fn distance(self, other: FloatPoint) -> Float64:
        return sqrt(self.distance_square(other))

    fn weighted_distance(self, other: FloatPoint, horizontal_weight: Float64, vertical_weight: Float64) -> Float64:
        var dx = (self.x - other.x) * horizontal_weight
        var dy = (self.y - other.y) * vertical_weight
        return sqrt(dx * dx + dy * dy)

    fn round(self) -> IntPoint:
        return IntPoint(Int(round(self.x)), Int(round(self.y)))

    fn change_size(self, new_size: Float64) -> FloatPoint:
        if self.x == 0.0 and self.y == 0.0:
            return self
        var length = sqrt(self.x * self.x + self.y * self.y)
        var new_x = (self.x * new_size) / length
        var new_y = (self.y * new_size) / length
        return FloatPoint(new_x, new_y)

    fn round_to_the_right(self, dir: IntDirection) -> IntPoint:
        var dv = dir.get_vector().to_float()
        var rounded_x: Int
        if dv.y > 0.0:
            rounded_x = Int(ceil(self.x))
        elif dv.y < 0.0:
            rounded_x = Int(floor(self.x))
        else:
            rounded_x = Int(round(self.x))

        var rounded_y: Int
        if dv.x > 0.0:
            rounded_y = Int(floor(self.y))
        elif dv.x < 0.0:
            rounded_y = Int(ceil(self.y))
        else:
            rounded_y = Int(round(self.y))
        return IntPoint(rounded_x, rounded_y)

    fn round_to_the_left(self, dir: IntDirection) -> IntPoint:
        var dv = dir.get_vector().to_float()
        var rounded_x: Int
        if dv.y > 0.0:
            rounded_x = Int(floor(self.x))
        elif dv.y < 0.0:
            rounded_x = Int(ceil(self.x))
        else:
            rounded_x = Int(round(self.x))

        var rounded_y: Int
        if dv.x > 0.0:
            rounded_y = Int(ceil(self.y))
        elif dv.x < 0.0:
            rounded_y = Int(floor(self.y))
        else:
            rounded_y = Int(round(self.y))
        return IntPoint(rounded_x, rounded_y)

