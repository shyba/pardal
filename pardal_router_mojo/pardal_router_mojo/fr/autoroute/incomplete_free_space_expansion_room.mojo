"""Port of `app.freerouting.autoroute.IncompleteFreeSpaceExpansionRoom` (minimal).

The full FreeRouting class participates in room/door expansion. For the 90-degree
search-tree work we only need:
- shape (TileShape) — for now `IntBox`
- layer
- contained shape (subset) — `IntBox`
"""

from ..geometry.planar.int_box import IntBox
from ..geometry.planar.int_point import IntPoint

@fieldwise_init
struct IncompleteFreeSpaceExpansionRoom(Copyable, Movable):
    var shape: IntBox
    var layer: Int
    var contained_shape: IntBox

    fn get_shape(self) -> IntBox:
        return IntBox(
            IntPoint(self.shape.ll.x, self.shape.ll.y),
            IntPoint(self.shape.ur.x, self.shape.ur.y),
        )

    fn get_layer(self) -> Int:
        return self.layer

    fn get_contained_shape(self) -> IntBox:
        return IntBox(
            IntPoint(self.contained_shape.ll.x, self.contained_shape.ll.y),
            IntPoint(self.contained_shape.ur.x, self.contained_shape.ur.y),
        )
