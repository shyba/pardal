"""Port of `app.freerouting.geometry.planar.FortyfiveDegreeDirection`."""

from .direction import right, right45, up, up45, left, left45, down, down45
from .int_direction import IntDirection

@fieldwise_init
struct FortyfiveDegreeDirection(Copyable, Movable):
    # 0..7 corresponds to RIGHT, RIGHT45, UP, UP45, LEFT, LEFT45, DOWN, DOWN45
    var idx: Int

    @staticmethod
    fn RIGHT() -> FortyfiveDegreeDirection:
        return FortyfiveDegreeDirection(0)

    @staticmethod
    fn RIGHT45() -> FortyfiveDegreeDirection:
        return FortyfiveDegreeDirection(1)

    @staticmethod
    fn UP() -> FortyfiveDegreeDirection:
        return FortyfiveDegreeDirection(2)

    @staticmethod
    fn UP45() -> FortyfiveDegreeDirection:
        return FortyfiveDegreeDirection(3)

    @staticmethod
    fn LEFT() -> FortyfiveDegreeDirection:
        return FortyfiveDegreeDirection(4)

    @staticmethod
    fn LEFT45() -> FortyfiveDegreeDirection:
        return FortyfiveDegreeDirection(5)

    @staticmethod
    fn DOWN() -> FortyfiveDegreeDirection:
        return FortyfiveDegreeDirection(6)

    @staticmethod
    fn DOWN45() -> FortyfiveDegreeDirection:
        return FortyfiveDegreeDirection(7)

    fn get_direction(self) -> IntDirection:
        if self.idx == 0:
            return right()
        if self.idx == 1:
            return right45()
        if self.idx == 2:
            return up()
        if self.idx == 3:
            return up45()
        if self.idx == 4:
            return left()
        if self.idx == 5:
            return left45()
        if self.idx == 6:
            return down()
        return down45()

