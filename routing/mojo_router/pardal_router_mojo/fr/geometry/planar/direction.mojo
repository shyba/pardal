"""Port of `app.freerouting.geometry.planar.Direction` (IntDirection-only subset).

FreeRouting supports `BigIntDirection`; we postpone it until needed. For now,
`Direction` is represented by `IntDirection` and exposes the same constants and
helpers.
"""

from math import cos, sin

from ...datastructures.signum import Signum
from .int_direction import IntDirection
from .int_vector import IntVector
from .side import Side

fn null() -> IntDirection:
    return IntDirection(0, 0)

fn right() -> IntDirection:
    return IntDirection(1, 0)

fn right45() -> IntDirection:
    return IntDirection(1, 1)

fn up() -> IntDirection:
    return IntDirection(0, 1)

fn up45() -> IntDirection:
    return IntDirection(-1, 1)

fn left() -> IntDirection:
    return IntDirection(-1, 0)

fn left45() -> IntDirection:
    return IntDirection(-1, -1)

fn down() -> IntDirection:
    return IntDirection(0, -1)

fn down45() -> IntDirection:
    return IntDirection(1, -1)

fn get_instance_from_vector(v: IntVector) -> IntDirection:
    return v.to_normalized_direction()

fn get_instance_approx(angle: Float64) -> IntDirection:
    # FreeRouting uses scale_factor=10000 and rounds.
    var scale_factor = 10000.0
    var x = Int(round(cos(angle) * scale_factor))
    var y = Int(round(sin(angle) * scale_factor))
    return get_instance_from_vector(IntVector(x, y))

fn equals_dir(a: IntDirection, b: IntDirection) -> Bool:
    # FreeRouting Direction.equals(Direction): collinear AND not opposite.
    if a.x == b.x and a.y == b.y:
        return True
    # collinearity check via side_of
    var side = a.get_vector().side_of(b.get_vector())
    if side.to_string() != Side.collinear().to_string():
        return False
    # projection positive: scalar product > 0
    var proj = a.get_vector().projection(b.get_vector())
    return proj.to_string() == Signum.positive().to_string()

fn side_of(a: IntDirection, b: IntDirection) -> Side:
    return a.get_vector().side_of(b.get_vector())

fn projection(a: IntDirection, b: IntDirection) -> Signum:
    return a.get_vector().projection(b.get_vector())

fn to_string(d: IntDirection) -> String:
    # Mirror Direction.toString() mapping for IntDirection constants.
    if d.compare_to_int_direction(right()) == 0:
        return "RIGHT"
    if d.compare_to_int_direction(right45()) == 0:
        return "UP-RIGHT"
    if d.compare_to_int_direction(up()) == 0:
        return "UP"
    if d.compare_to_int_direction(up45()) == 0:
        return "UP-LEFT"
    if d.compare_to_int_direction(left()) == 0:
        return "LEFT"
    if d.compare_to_int_direction(left45()) == 0:
        return "DOWN-LEFT"
    if d.compare_to_int_direction(down()) == 0:
        return "DOWN"
    if d.compare_to_int_direction(down45()) == 0:
        return "DOWN-RIGHT"
    if d.compare_to_int_direction(null()) == 0:
        return "NULL"
    return "UNKNOWN"
