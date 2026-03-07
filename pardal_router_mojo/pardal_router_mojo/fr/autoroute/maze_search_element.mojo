"""Port of `app.freerouting.autoroute.MazeSearchElement` (minimal).

The full FreeRouting maze router uses per-door/per-section `MazeSearchElement`s
to track expansion state, costs, and backpointers.

For now we only need a tiny subset to support data-structure ports:
- reset() for "next connection" reuse
"""

@fieldwise_init
struct MazeSearchElement(Copyable, Movable):
    var visited: Bool
    var cost: Int

    fn __init__(out self):
        self.visited = False
        self.cost = 0

    fn reset(mut self):
        self.visited = False
        self.cost = 0

