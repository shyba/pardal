"""Port of `app.freerouting.datastructures.Signum`."""

@fieldwise_init
struct Signum(Copyable, Movable):
    var _value: Int

    @staticmethod
    fn positive() -> Signum:
        return Signum(1)

    @staticmethod
    fn negative() -> Signum:
        return Signum(-1)

    @staticmethod
    fn zero() -> Signum:
        return Signum(0)

    @staticmethod
    fn of(value: Float64) -> Signum:
        if value > 0.0:
            return Signum.positive()
        if value < 0.0:
            return Signum.negative()
        return Signum.zero()

    @staticmethod
    fn as_int(value: Float64) -> Int:
        if value > 0.0:
            return 1
        if value < 0.0:
            return -1
        return 0

    fn negate(self) -> Signum:
        if self._value == 1:
            return Signum.negative()
        if self._value == -1:
            return Signum.positive()
        return Signum(self._value)

    fn to_string(self) -> String:
        if self._value == 1:
            return "positive"
        if self._value == -1:
            return "negative"
        return "zero"
