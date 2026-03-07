"""Port of `app.freerouting.geometry.planar.Side`."""

@fieldwise_init
struct Side(Copyable, Movable):
    var _value: Int

    @staticmethod
    fn on_the_left() -> Side:
        return Side(1)

    @staticmethod
    fn on_the_right() -> Side:
        return Side(-1)

    @staticmethod
    fn collinear() -> Side:
        return Side(0)

    @staticmethod
    fn of(value: Float64) -> Side:
        if value > 0.0:
            return Side.on_the_left()
        if value < 0.0:
            return Side.on_the_right()
        return Side.collinear()

    fn negate(self) -> Side:
        if self._value == 1:
            return Side.on_the_right()
        if self._value == -1:
            return Side.on_the_left()
        return Side(0)

    fn to_string(self) -> String:
        if self._value == 1:
            return "on_the_left"
        if self._value == -1:
            return "on_the_right"
        return "collinear"
