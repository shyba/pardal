"""Port of `app.freerouting.rules.ClearanceMatrix` (subset, lockstep semantics).

Implementation note (Mojo):
- `List[T]` requires `T: Copyable`, so we represent the matrix as a flat
  `List[Int]` and compute indices (row/col/layer) explicitly.
"""

from collections import List

from ..board.layer_structure import LayerStructure


fn _idx(class_count: Int, layer_count: Int, i: Int, j: Int, layer: Int) -> Int:
    # Storage layout: ((j * class_count + i) * layer_count + layer)
    return (j * class_count + i) * layer_count + layer


@fieldwise_init
struct ClearanceMatrix(Movable):
    # FreeRouting: public static final int clearance_safety_margin = 16;
    var clearance_safety_margin: Int

    var layer_count: Int
    var class_count: Int
    var names: List[String]

    # Flat matrix values: class_count * class_count * layer_count
    var values: List[Int]

    # Max value per "row i" (FreeRouting stores per clearance-class row), per layer.
    # Layout: class_count * layer_count
    var max_value_row_layer: List[Int]

    # Max value per layer
    var max_value_on_layer: List[Int]

    fn __init__(
        out self,
        class_count_in: Int,
        layer_structure: LayerStructure,
        name_arr: List[String],
    ):
        var class_count = class_count_in
        if class_count < 1:
            class_count = 1

        self.clearance_safety_margin = 16
        self.layer_count = len(layer_structure.arr)
        self.class_count = class_count

        # Copy names into owned list (avoid moving out of parameters).
        var names: List[String] = []
        var ni = 0
        while ni < len(name_arr):
            names.append(name_arr[ni])
            ni += 1
        self.names = names^

        var values: List[Int] = []
        var n = class_count * class_count * self.layer_count
        var k = 0
        while k < n:
            values.append(0)
            k += 1
        self.values = values^

        var mvrl: List[Int] = []
        var n2 = class_count * self.layer_count
        k = 0
        while k < n2:
            mvrl.append(0)
            k += 1
        self.max_value_row_layer = mvrl^

        var mvl: List[Int] = []
        var l = 0
        while l < self.layer_count:
            mvl.append(0)
            l += 1
        self.max_value_on_layer = mvl^

    fn get_no(self, name: String) -> Int:
        var i = 0
        while i < self.class_count:
            if self.names[i].lower() == name.lower():
                return i
            i += 1
        return -1

    fn get_name(self, cl_class: Int) -> String:
        if cl_class < 0 or cl_class >= len(self.names):
            return ""
        return self.names[cl_class]

    fn set_value(mut self, i: Int, j: Int, layer: Int, value_in: Int):
        # Assure positive + even, rounding up if odd, and handle MAX_VALUE.
        var value = value_in
        if value < 0:
            value = 0
        if value % 2 != 0:
            if value == 2147483647:  # Integer.MAX_VALUE
                value -= 1
            else:
                value += 1

        self.values[_idx(self.class_count, self.layer_count, i, j, layer)] = value

        # row max for row j (FreeRouting uses row[p_j].max_value[p_layer])
        var ridx = j * self.layer_count + layer
        if value > self.max_value_row_layer[ridx]:
            self.max_value_row_layer[ridx] = value
        if value > self.max_value_on_layer[layer]:
            self.max_value_on_layer[layer] = value

    fn get_value(self, i: Int, j: Int, layer: Int, add_safety_margin: Bool) -> Int:
        if (
            i < 0
            or i >= self.class_count
            or j < 0
            or j >= self.class_count
            or layer < 0
            or layer >= self.layer_count
        ):
            return 0
        var v = self.values[_idx(self.class_count, self.layer_count, i, j, layer)]
        if add_safety_margin:
            return v + self.clearance_safety_margin
        return v

    fn max_value_for_class(self, i: Int, layer: Int) -> Int:
        var ii = i
        if ii < 0:
            ii = 0
        if ii > self.class_count - 1:
            ii = self.class_count - 1
        var ll = layer
        if ll < 0:
            ll = 0
        if ll > self.layer_count - 1:
            ll = self.layer_count - 1
        return self.max_value_row_layer[ii * self.layer_count + ll]

    fn max_value_for_layer(self, layer: Int) -> Int:
        var ll = layer
        if ll < 0:
            ll = 0
        if ll > self.layer_count - 1:
            ll = self.layer_count - 1
        return self.max_value_on_layer[ll]

    fn clearance_compensation_value(self, clearance_class_no: Int, layer: Int) -> Int:
        # Port of Java `ClearanceMatrix.clearance_compensation_value(int,int)`.
        # Uses (value + 1) / 2 with value = (i,i) on that layer, no safety margin.
        var v = self.get_value(clearance_class_no, clearance_class_no, layer, False)
        return (v + 1) // 2
