"""Port of `app.freerouting.autoroute.IncompleteFreeSpaceExpansionRoom` (octagon-only).

This mirrors the existing IntBox-only room but uses IntOctagon shapes for 45°
autoroute and room division.
"""

from ..geometry.planar.int_octagon import IntOctagon


@fieldwise_init
struct IncompleteFreeSpaceExpansionRoomOctagon(Copyable, Movable):
    var shape: IntOctagon
    var layer: Int
    var contained_shape: IntOctagon

    fn get_shape(self) -> IntOctagon:
        return IntOctagon(
            self.shape.leftX,
            self.shape.rightX,
            self.shape.bottomY,
            self.shape.topY,
            self.shape.lowerLeftDiagonalX,
            self.shape.upperRightDiagonalX,
            self.shape.upperLeftDiagonalX,
            self.shape.lowerRightDiagonalX,
        )

    fn get_layer(self) -> Int:
        return self.layer

    fn get_contained_shape(self) -> IntOctagon:
        return IntOctagon(
            self.contained_shape.leftX,
            self.contained_shape.rightX,
            self.contained_shape.bottomY,
            self.contained_shape.topY,
            self.contained_shape.lowerLeftDiagonalX,
            self.contained_shape.upperRightDiagonalX,
            self.contained_shape.upperLeftDiagonalX,
            self.contained_shape.lowerRightDiagonalX,
        )
