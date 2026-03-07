"""Port of `app.freerouting.datastructures.BigIntAux` (subset).

Note: For now we only port `binaryGcd(int,int)` because it is required by
`geometry.planar.IntVector.to_normalized_direction()`.
"""

fn binary_gcd(a: Int, b: Int) -> Int:
    # Semantic equivalent of FreeRouting's `BigIntAux.binaryGcd(int,int)`.
    #
    # FreeRouting uses a bit-optimized GCD for speed. Here we use the classic
    # Euclidean algorithm, which yields the same mathematical GCD (the only
    # property relied on by the router). If perf becomes relevant, we can
    # replace this with the bitwise version once Mojo supports the needed
    # constant-table patterns.
    var aa = a
    if aa < 0:
        aa = -aa
    var bb = b
    if bb < 0:
        bb = -bb
    while bb != 0:
        var r = aa % bb
        aa = bb
        bb = r
    return aa
