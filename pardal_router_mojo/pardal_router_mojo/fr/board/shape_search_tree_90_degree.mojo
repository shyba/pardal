"""Port of `app.freerouting.board.ShapeSearchTree90Degree` (geometry-only subset).

This module starts with `restrain_shape`, a key helper used by `complete_shape`
to cut a room against an obstacle while keeping a required contained shape.

We port it exactly because it is pure geometry and can be tested in isolation.
The full `complete_shape` traversal depends on the board/search-tree object
model and is ported later.
"""

from collections import List

from ..autoroute.incomplete_free_space_expansion_room import IncompleteFreeSpaceExpansionRoom
from ..geometry.planar.int_box import IntBox
from ..geometry.planar.int_point import IntPoint


fn restrain_shape(room: IncompleteFreeSpaceExpansionRoom, obstacle: IntBox) -> List[IncompleteFreeSpaceExpansionRoom]:
    # Port of Java `ShapeSearchTree90Degree.restrain_shape(...)`.
    var result = List[IncompleteFreeSpaceExpansionRoom]()

    var contained = room.get_contained_shape()
    if contained.is_empty():
        return result^

    var room_shape = room.get_shape()
    var shape_to_be_contained = IntBox(
        IntPoint(contained.ll.x, contained.ll.y),
        IntPoint(contained.ur.x, contained.ur.y),
    )

    var cut_line_distance = 0
    var restrained_shape_opt = IntBox.empty()
    var found = False

    # Right edge of obstacle intersects interior of room
    if (
        room_shape.ll.x < obstacle.ur.x
        and room_shape.ur.x > obstacle.ur.x
        and room_shape.ur.y > obstacle.ll.y
        and room_shape.ll.y < obstacle.ur.y
    ):
        var curr_distance = shape_to_be_contained.ll.x - obstacle.ur.x
        if curr_distance > cut_line_distance:
            cut_line_distance = curr_distance
            restrained_shape_opt = IntBox(
                IntPoint(obstacle.ur.x, room_shape.ll.y),
                IntPoint(room_shape.ur.x, room_shape.ur.y),
            )
            found = True

    # Left edge
    if (
        room_shape.ll.x < obstacle.ll.x
        and room_shape.ur.x > obstacle.ll.x
        and room_shape.ur.y > obstacle.ll.y
        and room_shape.ll.y < obstacle.ur.y
    ):
        var curr_distance = obstacle.ll.x - shape_to_be_contained.ur.x
        if curr_distance > cut_line_distance:
            cut_line_distance = curr_distance
            restrained_shape_opt = IntBox(
                IntPoint(room_shape.ll.x, room_shape.ll.y),
                IntPoint(obstacle.ll.x, room_shape.ur.y),
            )
            found = True

    # Lower edge
    if (
        room_shape.ll.y < obstacle.ll.y
        and room_shape.ur.y > obstacle.ll.y
        and room_shape.ur.x > obstacle.ll.x
        and room_shape.ll.x < obstacle.ur.x
    ):
        var curr_distance = obstacle.ll.y - shape_to_be_contained.ur.y
        if curr_distance > cut_line_distance:
            cut_line_distance = curr_distance
            restrained_shape_opt = IntBox(
                IntPoint(room_shape.ll.x, room_shape.ll.y),
                IntPoint(room_shape.ur.x, obstacle.ll.y),
            )
            found = True

    # Upper edge
    if (
        room_shape.ll.y < obstacle.ur.y
        and room_shape.ur.y > obstacle.ur.y
        and room_shape.ur.x > obstacle.ll.x
        and room_shape.ll.x < obstacle.ur.x
    ):
        var curr_distance = shape_to_be_contained.ll.y - obstacle.ur.y
        if curr_distance > cut_line_distance:
            cut_line_distance = curr_distance
            restrained_shape_opt = IntBox(
                IntPoint(room_shape.ll.x, obstacle.ur.y),
                IntPoint(room_shape.ur.x, room_shape.ur.y),
            )
            found = True

    if found:
        result.append(
            IncompleteFreeSpaceExpansionRoom(
                IntBox(
                    IntPoint(restrained_shape_opt.ll.x, restrained_shape_opt.ll.y),
                    IntPoint(restrained_shape_opt.ur.x, restrained_shape_opt.ur.y),
                ),
                room.get_layer(),
                IntBox(
                    IntPoint(shape_to_be_contained.ll.x, shape_to_be_contained.ll.y),
                    IntPoint(shape_to_be_contained.ur.x, shape_to_be_contained.ur.y),
                ),
            )
        )
        return result^

    # shape_to_be_contained intersects with obstacle: split.
    var inter = shape_to_be_contained.intersection(obstacle)
    if inter.is_empty():
        return result^

    var new_shape_1_opt = False
    var new_shape_1 = IntBox.empty()
    var new_shape_2 = IntBox.empty()

    if inter.ll.x > room_shape.ll.x and inter.ll.x == obstacle.ll.x and inter.ll.x < room_shape.ur.x:
        new_shape_1 = IntBox(IntPoint(room_shape.ll.x, room_shape.ll.y), IntPoint(inter.ll.x, room_shape.ur.y))
        new_shape_2 = IntBox(IntPoint(inter.ll.x, room_shape.ll.y), IntPoint(room_shape.ur.x, room_shape.ur.y))
        new_shape_1_opt = True
    elif inter.ur.x > room_shape.ll.x and inter.ur.x == obstacle.ur.x and inter.ur.x < room_shape.ur.x:
        new_shape_2 = IntBox(IntPoint(room_shape.ll.x, room_shape.ll.y), IntPoint(inter.ur.x, room_shape.ur.y))
        new_shape_1 = IntBox(IntPoint(inter.ur.x, room_shape.ll.y), IntPoint(room_shape.ur.x, room_shape.ur.y))
        new_shape_1_opt = True
    elif inter.ll.y > room_shape.ll.y and inter.ll.y == obstacle.ll.y and inter.ll.y < room_shape.ur.y:
        new_shape_1 = IntBox(IntPoint(room_shape.ll.x, room_shape.ll.y), IntPoint(room_shape.ur.x, inter.ll.y))
        new_shape_2 = IntBox(IntPoint(room_shape.ll.x, inter.ll.y), IntPoint(room_shape.ur.x, room_shape.ur.y))
        new_shape_1_opt = True
    elif inter.ur.y > room_shape.ll.y and inter.ur.y == obstacle.ur.y and inter.ur.y < room_shape.ur.y:
        new_shape_2 = IntBox(IntPoint(room_shape.ll.x, room_shape.ll.y), IntPoint(room_shape.ur.x, inter.ur.y))
        new_shape_1 = IntBox(IntPoint(room_shape.ll.x, inter.ur.y), IntPoint(room_shape.ur.x, room_shape.ur.y))
        new_shape_1_opt = True

    if new_shape_1_opt:
        var new_contained_1 = shape_to_be_contained.intersection(new_shape_1)
        if new_contained_1.dimension() > 0:
            result.append(
                IncompleteFreeSpaceExpansionRoom(
                    IntBox(IntPoint(new_shape_1.ll.x, new_shape_1.ll.y), IntPoint(new_shape_1.ur.x, new_shape_1.ur.y)),
                    room.get_layer(),
                    IntBox(IntPoint(new_contained_1.ll.x, new_contained_1.ll.y), IntPoint(new_contained_1.ur.x, new_contained_1.ur.y)),
                )
            )
            var new_room = IncompleteFreeSpaceExpansionRoom(
                IntBox(IntPoint(new_shape_2.ll.x, new_shape_2.ll.y), IntPoint(new_shape_2.ur.x, new_shape_2.ur.y)),
                room.get_layer(),
                shape_to_be_contained.intersection(new_shape_2),
            )
            var tail = restrain_shape(new_room, obstacle)
            var i = 0
            while i < len(tail):
                var t = tail[i].copy()
                result.append(
                    IncompleteFreeSpaceExpansionRoom(
                        t.get_shape(),
                        t.get_layer(),
                        t.get_contained_shape(),
                    )
                )
                i += 1
    return result^
