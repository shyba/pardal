from collections import List


@fieldwise_init
struct ClearanceMatrix(Copyable, Movable):
    # Symmetric matrix of clearances between clearance classes, optionally per-layer.
    #
    # Storage: flattened [layer][i][j] with symmetric enforcement on set().
    var layer_count: Int
    var class_names: List[String]
    var values: List[Int]  # microunits (e.g. um) or "grid units" decided by caller

    fn __init__(out self, layer_count: Int, class_names: List[String], default_value: Int):
        var lc = layer_count
        if lc <= 0:
            lc = 1
        self.layer_count = lc
        self.class_names = class_names.copy()
        var n = len(class_names)
        if n <= 0:
            self.values = List[Int](length=0, fill=0)
            return
        self.values = List[Int](length=lc * n * n, fill=default_value)

    fn class_count(self) -> Int:
        return len(self.class_names)

    fn idx(self, layer: Int, i: Int, j: Int) -> Int:
        var n = len(self.class_names)
        var l = layer
        if l < 0:
            l = 0
        if l >= self.layer_count:
            l = self.layer_count - 1
        return l * n * n + i * n + j

    fn get(self, i: Int, j: Int, layer: Int) -> Int:
        var n = len(self.class_names)
        if i < 0 or j < 0 or i >= n or j >= n or n == 0:
            return 0
        return self.values[self.idx(layer, i, j)]

    fn set(mut self, i: Int, j: Int, layer: Int, value: Int):
        var n = len(self.class_names)
        if i < 0 or j < 0 or i >= n or j >= n or n == 0:
            return
        var k0 = self.idx(layer, i, j)
        var k1 = self.idx(layer, j, i)
        self.values[k0] = value
        self.values[k1] = value

    fn class_index(self, name: String) -> Int:
        var i = 0
        while i < len(self.class_names):
            if self.class_names[i] == name:
                return i
            i += 1
        return -1


@fieldwise_init
struct NetClassRules(Copyable, Movable):
    var name: String
    var track_width: Int
    var via_diameter: Int
    var via_drill: Int
    var uvia_diameter: Int
    var uvia_drill: Int
    var trace_clearance_class: Int
    var via_clearance_class: Int

    fn __init__(out self, name: String):
        self.name = name
        self.track_width = 0
        self.via_diameter = 0
        self.via_drill = 0
        self.uvia_diameter = 0
        self.uvia_drill = 0
        self.trace_clearance_class = 0
        self.via_clearance_class = 0


struct BoardRules:
    var clearance: ClearanceMatrix
    var netclasses: List[NetClassRules]

    fn __init__(out self, clearance: ClearanceMatrix):
        self.clearance = clearance.copy()
        self.netclasses = List[NetClassRules]()

    fn add_netclass(mut self, nc: NetClassRules) -> Int:
        var id = len(self.netclasses)
        self.netclasses.append(nc.copy())
        return id

    fn netclass_index(self, name: String) -> Int:
        var i = 0
        while i < len(self.netclasses):
            if self.netclasses[i].name == name:
                return i
            i += 1
        return -1
