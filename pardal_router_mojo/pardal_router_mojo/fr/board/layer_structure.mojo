"""Port of `app.freerouting.board.LayerStructure` (minimal).

FreeRouting stores `Layer[] arr`. We keep a `List[Layer]`.
"""

from collections import List

from .layer import Layer

@fieldwise_init
struct LayerStructure(Movable):
    var arr: List[Layer]

    fn layer_count(self) -> Int:
        return len(self.arr)

