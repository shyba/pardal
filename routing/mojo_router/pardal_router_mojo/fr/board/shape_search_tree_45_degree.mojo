"""Incremental port of `app.freerouting.board.ShapeSearchTree45Degree`.

Scope (initial):
- Geometry helpers (`obstacle_segment_touches_inside`, `signed_line_distance`)
- `restrain_shape` for `IntOctagon` rooms

Traversal and full board integration (SearchTreeManager, clearance compensation,
door division) are ported later.
"""

from collections import List

from ..autoroute.incomplete_free_space_expansion_room_octagon import (
    IncompleteFreeSpaceExpansionRoomOctagon,
)
from ..geometry.planar.int_octagon import IntOctagon
from ..geometry.planar.side import Side


fn obstacle_segment_touches_inside(
    obstacle: IntOctagon, obstacle_border_line_no: Int, room_shape: IntOctagon
) -> Bool:
    # Port of Java `obstacle_segment_touches_inside(...)`.
    var curr_border_line_no = obstacle_border_line_no
    var curr_x = obstacle.corner_x(obstacle_border_line_no)
    var curr_y = obstacle.corner_y(obstacle_border_line_no)
    var j = 0
    while j < 5:
        if (
            room_shape.side_of_border_line(curr_x, curr_y, curr_border_line_no)._value
            != Side.on_the_left()._value
        ):
            return False
        curr_border_line_no = (curr_border_line_no + 1) % 8
        j += 1

    var next_no = (obstacle_border_line_no + 1) % 8
    var next_x = obstacle.corner_x(next_no)
    var next_y = obstacle.corner_y(next_no)
    curr_border_line_no = (obstacle_border_line_no + 5) % 8
    j = 0
    while j < 3:
        if (
            room_shape.side_of_border_line(next_x, next_y, curr_border_line_no)._value
            != Side.on_the_left()._value
        ):
            return False
        curr_border_line_no = (curr_border_line_no + 1) % 8
        j += 1
    return True


fn signed_line_distance(
    obstacle: IntOctagon, obstacle_line_no: Int, contained: IntOctagon
) -> Float64:
    # Port of Java `signed_line_distance(...)`.
    if obstacle_line_no == 0:
        return Float64(obstacle.bottomY - contained.topY)
    if obstacle_line_no == 2:
        return Float64(contained.leftX - obstacle.rightX)
    if obstacle_line_no == 4:
        return Float64(contained.bottomY - obstacle.topY)
    if obstacle_line_no == 6:
        return Float64(obstacle.leftX - contained.rightX)
    if obstacle_line_no == 1:
        return 0.5 * Float64(
            contained.upperLeftDiagonalX - obstacle.lowerRightDiagonalX
        )
    if obstacle_line_no == 3:
        return 0.5 * Float64(
            contained.lowerLeftDiagonalX - obstacle.upperRightDiagonalX
        )
    if obstacle_line_no == 5:
        return 0.5 * Float64(
            obstacle.upperLeftDiagonalX - contained.lowerRightDiagonalX
        )
    if obstacle_line_no == 7:
        return 0.5 * Float64(
            obstacle.lowerLeftDiagonalX - contained.upperRightDiagonalX
        )
    return 0.0


fn calc_outside_restrained_shape(
    obstacle: IntOctagon, obstacle_line_no: Int, room_shape: IntOctagon
) -> IntOctagon:
    # Port of Java `calc_outside_restrained_shape(...)`.
    var lx = room_shape.leftX
    var rx = room_shape.rightX
    var ly = room_shape.bottomY
    var uy = room_shape.topY
    var ulx = room_shape.upperLeftDiagonalX
    var lrx = room_shape.lowerRightDiagonalX
    var llx = room_shape.lowerLeftDiagonalX
    var urx = room_shape.upperRightDiagonalX

    if obstacle_line_no == 0:
        uy = obstacle.bottomY
    elif obstacle_line_no == 2:
        lx = obstacle.rightX
    elif obstacle_line_no == 4:
        ly = obstacle.topY
    elif obstacle_line_no == 6:
        rx = obstacle.leftX
    elif obstacle_line_no == 1:
        ulx = obstacle.lowerRightDiagonalX
    elif obstacle_line_no == 3:
        llx = obstacle.upperRightDiagonalX
    elif obstacle_line_no == 5:
        lrx = obstacle.upperLeftDiagonalX
    elif obstacle_line_no == 7:
        urx = obstacle.lowerLeftDiagonalX

    return IntOctagon.from_freerouting(
        lx,
        ly,
        rx,
        uy,
        ulx,
        lrx,
        llx,
        urx,
    ).normalize()


fn calc_inside_restrained_shape(
    obstacle: IntOctagon, obstacle_line_no: Int, room_shape: IntOctagon
) -> IntOctagon:
    # Port of Java `calc_inside_restrained_shape(...)`.
    var lx = room_shape.leftX
    var rx = room_shape.rightX
    var ly = room_shape.bottomY
    var uy = room_shape.topY
    var ulx = room_shape.upperLeftDiagonalX
    var lrx = room_shape.lowerRightDiagonalX
    var llx = room_shape.lowerLeftDiagonalX
    var urx = room_shape.upperRightDiagonalX

    if obstacle_line_no == 0:
        ly = obstacle.bottomY
    elif obstacle_line_no == 2:
        rx = obstacle.rightX
    elif obstacle_line_no == 4:
        uy = obstacle.topY
    elif obstacle_line_no == 6:
        lx = obstacle.leftX
    elif obstacle_line_no == 1:
        lrx = obstacle.lowerRightDiagonalX
    elif obstacle_line_no == 3:
        urx = obstacle.upperRightDiagonalX
    elif obstacle_line_no == 5:
        ulx = obstacle.upperLeftDiagonalX
    elif obstacle_line_no == 7:
        llx = obstacle.lowerLeftDiagonalX

    return IntOctagon.from_freerouting(
        lx,
        ly,
        rx,
        uy,
        ulx,
        lrx,
        llx,
        urx,
    ).normalize()


fn restrain_shape(
    room: IncompleteFreeSpaceExpansionRoomOctagon, obstacle_shape: IntOctagon
) -> List[IncompleteFreeSpaceExpansionRoomOctagon]:
    # Port of Java `ShapeSearchTree45Degree.restrain_shape(...)` for IntOctagon-only.
    var result = List[IncompleteFreeSpaceExpansionRoomOctagon]()

    var contained = room.get_contained_shape()
    if contained.is_empty():
        return result^

    var room_shape = room.get_shape()
    var cut_line_distance = Float64(-1.0)
    var restraining_line_no = -1

    var obstacle_line_no = 0
    while obstacle_line_no < 8:
        var curr_distance = signed_line_distance(
            obstacle_shape, obstacle_line_no, contained
        )
        if curr_distance > cut_line_distance:
            if obstacle_segment_touches_inside(
                obstacle_shape, obstacle_line_no, room_shape
            ):
                cut_line_distance = curr_distance
                restraining_line_no = obstacle_line_no
        obstacle_line_no += 1

    if cut_line_distance >= 0.0:
        var restrained = calc_outside_restrained_shape(
            obstacle_shape, restraining_line_no, room_shape
        )
        result.append(
            IncompleteFreeSpaceExpansionRoomOctagon(
                restrained.copy(), room.get_layer(), contained.copy()
            )
        )
        return result^

    if contained.dimension() < 1:
        return result^

    restraining_line_no = -1
    obstacle_line_no = 0
    while obstacle_line_no < 8:
        if obstacle_segment_touches_inside(
            obstacle_shape, obstacle_line_no, room_shape
        ):
            var curr_line = obstacle_shape.border_line(obstacle_line_no)
            if contained.side_of_line(curr_line)._value == Side.collinear()._value:
                restraining_line_no = obstacle_line_no
                break
        obstacle_line_no += 1

    if restraining_line_no < 0:
        return result^

    var restrained = calc_outside_restrained_shape(
        obstacle_shape, restraining_line_no, room_shape
    )
    if restrained.dimension() >= 2:
        var new_contained = contained.intersection(restrained)
        if new_contained.dimension() > 0:
            result.append(
                IncompleteFreeSpaceExpansionRoomOctagon(
                    restrained.copy(), room.get_layer(), new_contained.copy()
                )
            )

    var rest_piece = calc_inside_restrained_shape(
        obstacle_shape, restraining_line_no, room_shape
    )
    if rest_piece.dimension() >= 2:
        var rest_contained = contained.intersection(rest_piece)
        if rest_contained.dimension() >= 0:
            var rest_room = IncompleteFreeSpaceExpansionRoomOctagon(
                rest_piece.copy(), room.get_layer(), rest_contained.copy()
            )
            var more = restrain_shape(rest_room, obstacle_shape)
            for r in more:
                result.append(r.copy())

    return result^
