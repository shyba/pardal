"""Port of `app.freerouting.geometry.planar.Limits`."""

from math import sqrt

fn crit_int() -> Int:
    # FreeRouting: `Limits.CRIT_INT = 2^25`
    return 33554432

fn crit_double() -> Float64:
    # FreeRouting: `Limits.CRIT_DOUBLE = 2^53`
    return 9007199254740992.0

fn sqrt2() -> Float64:
    # FreeRouting: `Limits.sqrt2 = Math.sqrt(2)`
    return sqrt(2.0)
