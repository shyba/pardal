"""Port of `app.freerouting.autoroute.FreeSpaceExpansionRoom` (box-only, minimal).

FreeRouting uses expansion rooms + doors as the state space for the maze router.
This is a pure data container in the Mojo port (no inheritance), designed to be
used by a future `AutorouteEngine` port.
"""

from ..geometry.planar.tile_shape import TileShapeBox


@fieldwise_init
struct FreeSpaceExpansionRoomBox(Copyable, Movable):
    var layer: Int
    var shape: TileShapeBox
    # Minimal fixed-capacity door list to keep the struct Copyable.
    # The full port will replace this with a proper door store once we have a
    # Movable-friendly container abstraction.
    var door_count: Int
    var door0: Int
    var door1: Int
    var door2: Int
    var door3: Int

    fn __init__(out self, shape: TileShapeBox, layer: Int):
        self.layer = layer
        self.shape = shape.copy()
        self.door_count = 0
        self.door0 = -1
        self.door1 = -1
        self.door2 = -1
        self.door3 = -1

    fn add_door_id(mut self, door_id: Int):
        if self.door_count == 0:
            self.door0 = door_id
        elif self.door_count == 1:
            self.door1 = door_id
        elif self.door_count == 2:
            self.door2 = door_id
        elif self.door_count == 3:
            self.door3 = door_id
        else:
            # Fixed-capacity; ignore extras in the minimal port.
            return
        self.door_count += 1

    fn clear_doors(mut self):
        self.door_count = 0
        self.door0 = -1
        self.door1 = -1
        self.door2 = -1
        self.door3 = -1

    fn reset_doors(mut self):
        # Align with FreeRouting's `reset_doors()`, which clears cached
        # per-door section state before the next autoroute attempt.
        # The minimal box-only port stores only door IDs, so there is no
        # per-door section cache to clear here.
        return

    fn door_exists(self, other_room_id: Int) -> Bool:
        # Placeholder: the full port uses door objects; for now we keep only ids.
        # Existence checks are handled by the room graph in this minimal port.
        # Match the Java API shape by returning a direct room-id match against
        # stored door identifiers.
        if other_room_id < 0:
            return False
        if self.door0 >= 0 and self.door0 == other_room_id:
            return True
        if self.door1 >= 0 and self.door1 == other_room_id:
            return True
        if self.door2 >= 0 and self.door2 == other_room_id:
            return True
        if self.door3 >= 0 and self.door3 == other_room_id:
            return True
        return False

    fn door_id_at(self, i: Int) -> Int:
        if i == 0:
            return self.door0
        if i == 1:
            return self.door1
        if i == 2:
            return self.door2
        if i == 3:
            return self.door3
        return -1
