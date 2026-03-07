"""Port of `app.freerouting.autoroute.CompleteFreeSpaceExpansionRoom` (minimal).

The Java class implements `SearchTreeObject` and is stored in a `ShapeTree`.
In the Mojo port we only keep the fields needed for algorithm ports:
- id_no (for stable ordering)
- room_is_net_dependent marker
- target_doors list (left as opaque ints for now)
"""

from ..geometry.planar.tile_shape import TileShapeBox
from .free_space_expansion_room import FreeSpaceExpansionRoomBox


@fieldwise_init
struct CompleteFreeSpaceExpansionRoomBox(Copyable, Movable):
    var base: FreeSpaceExpansionRoomBox
    var id_no: Int
    var room_is_net_dependent: Bool
    var target_door_count: Int
    var target_door0: Int
    var target_door1: Int
    var target_door2: Int
    var target_door3: Int

    fn __init__(out self, shape: TileShapeBox, layer: Int, id_no: Int):
        self.base = FreeSpaceExpansionRoomBox(shape, layer)
        self.id_no = id_no
        self.room_is_net_dependent = False
        self.target_door_count = 0
        self.target_door0 = -1
        self.target_door1 = -1
        self.target_door2 = -1
        self.target_door3 = -1

    fn set_net_dependent(mut self):
        self.room_is_net_dependent = True

    fn is_net_dependent(self) -> Bool:
        return self.room_is_net_dependent

    fn add_target_door(mut self, door_id: Int):
        if self.target_door_count == 0:
            self.target_door0 = door_id
        elif self.target_door_count == 1:
            self.target_door1 = door_id
        elif self.target_door_count == 2:
            self.target_door2 = door_id
        elif self.target_door_count == 3:
            self.target_door3 = door_id
        else:
            return
        self.target_door_count += 1
