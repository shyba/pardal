"""
Port of `app.freerouting.geometry.planar.IntPoint`.

Note: the Java class extends an abstract `Point` hierarchy. For the initial port
we keep the concrete integer point type and add the minimal operations needed by
the rules/board layers.
"""

from .limits import crit_int
from .int_vector import IntVector

@fieldwise_init
struct IntPoint(Copyable, Movable):
    var x: Int
    var y: Int

    fn equals(self, other: IntPoint) -> Bool:
        _ = crit_int()
        return self.x == other.x and self.y == other.y

    fn determinant(self, other: IntPoint) -> Int64:
        _ = crit_int()
        return Int64(self.x) * Int64(other.y) - Int64(self.y) * Int64(other.x)

    fn difference_by(self, other: IntPoint) -> IntVector:
        return IntVector(self.x - other.x, self.y - other.y)

    fn translate_by(self, v: IntVector) -> IntPoint:
        return IntPoint(self.x + v.x, self.y + v.y)
