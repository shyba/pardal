"""Port of `app.freerouting.autoroute.ExpansionDoor` (minimal, box-only).

This module is a dependency for porting the FreeRouting maze expansion graph.
The full class is an `ExpandableObject` with sections, but for now we only keep:
- room ids (stable integers owned by the autoroute engine)
- precomputed door intersection shape (TileShapeBox)
- dimension (1 or 2)
"""

from ..geometry.planar.tile_shape import TileShapeBox


struct ExpansionDoorBox(Copyable, Movable):
    var first_room_id: Int
    var second_room_id: Int
    var dimension: Int
    var shape: TileShapeBox

    fn __init__(
        out self,
        first_room_id: Int,
        second_room_id: Int,
        dimension: Int,
        shape: TileShapeBox,
    ):
        self.first_room_id = first_room_id
        self.second_room_id = second_room_id
        self.dimension = dimension
        self.shape = shape.copy()

    fn other_room_id(self, room_id: Int) -> Int:
        if room_id == self.first_room_id:
            return self.second_room_id
        if room_id == self.second_room_id:
            return self.first_room_id
        return -1

    fn reset(mut self):
        # Placeholder: full parity adds per-section MazeSearchElement state.
        # The minimal box-only port does not model per-section buffers yet.
        return
