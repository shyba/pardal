"""Port of `app.freerouting.geometry.planar.IntDirection` (core behavior).

FreeRouting models `Direction` as an equivalence class of vectors; `IntDirection`
is the primary concrete representation.
"""

from ...datastructures.signum import Signum
from .int_vector import IntVector

@fieldwise_init
struct IntDirection(Copyable, Movable):
    var x: Int
    var y: Int

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

    fn get_vector(self) -> IntVector:
        return IntVector(self.x, self.y)

    fn opposite(self) -> IntDirection:
        return IntDirection(-self.x, -self.y)

    fn turn_45_degree(self, factor: Int) -> IntDirection:
        # FreeRouting: n = p_factor % 8 (Java `%` keeps sign); we mimic by
        # normalizing into [0..7].
        var n = factor % 8
        while n < 0:
            n += 8
        var new_x: Int
        var new_y: Int
        if n == 0:
            new_x = self.x
            new_y = self.y
        elif n == 1:
            new_x = self.x - self.y
            new_y = self.x + self.y
        elif n == 2:
            new_x = -self.y
            new_y = self.x
        elif n == 3:
            new_x = -self.x - self.y
            new_y = self.x - self.y
        elif n == 4:
            new_x = -self.x
            new_y = -self.y
        elif n == 5:
            new_x = self.y - self.x
            new_y = -self.x - self.y
        elif n == 6:
            new_x = self.y
            new_y = -self.x
        elif n == 7:
            new_x = self.x + self.y
            new_y = self.y - self.x
        else:
            new_x = 0
            new_y = 0
        return IntDirection(new_x, new_y)

    fn compare_to_int_direction(self, other: IntDirection) -> Int:
        # Port of `IntDirection.compareTo(IntDirection)`.
        if self.y > 0:
            if other.y < 0:
                return -1
            if other.y == 0:
                if other.x > 0:
                    return 1
                return -1
        elif self.y < 0:
            if other.y >= 0:
                return 1
        else:  # self.y == 0
            if self.x > 0:
                if other.y != 0 or other.x < 0:
                    return -1
                return 0
            # self.x <= 0
            if other.y > 0 or (other.y == 0 and other.x > 0):
                return 1
            if other.y < 0:
                return -1
            return 0

        # now both directions are located in the same open horizontal half plane
        var det = Float64(other.x) * Float64(self.y) - Float64(other.y) * Float64(self.x)
        # Java: Signum.as_int(determinant)
        return Signum.as_int(det)

