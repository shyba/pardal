from python import Python, PythonObject

from .astar import AStarWorkspace, route_a_star
from .grid import Grid


fn _int(d: PythonObject, k: String) raises -> Int:
    return Int(py=d[PythonObject(k)])


fn _u32(d: PythonObject, k: String) raises -> UInt32:
    return UInt32(Int(py=d[PythonObject(k)]))


fn _bool(d: PythonObject, k: String, default: Bool) raises -> Bool:
    var kk = PythonObject(k)
    if d.__contains__(kk):
        return Bool(py=d[kk])
    return default


fn _idx(layer: Int, x: Int, y: Int, w: Int, h: Int) -> Int:
    return (layer * w * h) + (y * w + x)


fn _apply_rect_block(mut g: Grid, layer: Int, x0: Int, y0: Int, x1: Int, y1: Int) -> None:
    var y = y0
    while y < y1:
        var x = x0
        while x < x1:
            g.base_set(g.idx(layer, x, y), g.blocked_value)
            x += 1
        y += 1


fn _apply_rect_touch_other(mut g: Grid, net_id: UInt32, layer: Int, x0: Int, y0: Int, x1: Int, y1: Int) -> None:
    var other = UInt32(0xFFFF_FFFF)
    var y = y0
    while y < y1:
        var x = x0
        while x < x1:
            var idx = g.idx(layer, x, y)
            g.touch_track[idx] = UInt16(1)
            g.touch_via[idx] = UInt16(1)
            g.touch_track_owner[idx] = other
            g.touch_via_owner[idx] = other
            x += 1
        y += 1


fn _apply_rect_ko_other(mut g: Grid, net_id: UInt32, layer: Int, x0: Int, y0: Int, x1: Int, y1: Int) -> None:
    var other = UInt32(0xFFFF_FFFF)
    var y = y0
    while y < y1:
        var x = x0
        while x < x1:
            var idx = g.idx(layer, x, y)
            g.ko_track[idx] = UInt16(1)
            g.ko_via[idx] = UInt16(1)
            g.ko_track_owner[idx] = other
            g.ko_via_owner[idx] = other
            x += 1
        y += 1


fn astar_direct(json_path: String) raises -> Int:
    """Run route_a_star on a small synthetic grid described by JSON.

    The JSON is intentionally minimal and cell-based (not mm):
      {
        "width": 120, "height": 80, "layers": 2,
        "start": {"layer":0,"x":..,"y":..}, "goal": {...},
        "blocked_rects": [{"layer":0,"x0":..,"y0":..,"x1":..,"y1":..}, ...],
        "net_id": 7,
        "allowed_mask": 3,
        "diagonal": true,
        "via_penalty": 40,
        "layer_penalty_outer": 0,
        "layer_penalty_in1": 0,
        "layer_penalty_inner": 0,
        "margin": 200,
        "astar_max_expansions": 0,
        "heuristic_weight_pct": 100
      }
    """
    var json = Python.import_module("json")
    var builtins = Python.import_module("builtins")
    var payload = json.loads(builtins.open(json_path, "r").read())

    var w = _int(payload, "width")
    var h = _int(payload, "height")
    var layers = _int(payload, "layers")
    var net_id = _u32(payload, "net_id")
    var allowed_mask = UInt32(_int(payload, "allowed_mask"))

    var g = Grid(layers, w, h)
    # Base default: empty.
    if payload.__contains__(PythonObject("blocked_rects")):
        for r in payload[PythonObject("blocked_rects")]:
            _apply_rect_block(
                g,
                Int(py=r[PythonObject("layer")]),
                Int(py=r[PythonObject("x0")]),
                Int(py=r[PythonObject("y0")]),
                Int(py=r[PythonObject("x1")]),
                Int(py=r[PythonObject("y1")]),
            )

    # Optional: dynamic blocking fields from already-routed copper.
    if payload.__contains__(PythonObject("blocked_rects_touch")):
        for r in payload[PythonObject("blocked_rects_touch")]:
            _apply_rect_touch_other(
                g,
                net_id,
                Int(py=r[PythonObject("layer")]),
                Int(py=r[PythonObject("x0")]),
                Int(py=r[PythonObject("y0")]),
                Int(py=r[PythonObject("x1")]),
                Int(py=r[PythonObject("y1")]),
            )
    if payload.__contains__(PythonObject("blocked_rects_ko")):
        for r in payload[PythonObject("blocked_rects_ko")]:
            _apply_rect_ko_other(
                g,
                net_id,
                Int(py=r[PythonObject("layer")]),
                Int(py=r[PythonObject("x0")]),
                Int(py=r[PythonObject("y0")]),
                Int(py=r[PythonObject("x1")]),
                Int(py=r[PythonObject("y1")]),
            )

    var start = payload[PythonObject("start")]
    var goal = payload[PythonObject("goal")]
    var s_layer = Int(py=start[PythonObject("layer")])
    var s_x = Int(py=start[PythonObject("x")])
    var s_y = Int(py=start[PythonObject("y")])
    var g_layer = Int(py=goal[PythonObject("layer")])
    var g_x = Int(py=goal[PythonObject("x")])
    var g_y = Int(py=goal[PythonObject("y")])

    var start_idx = _idx(s_layer, s_x, s_y, w, h)
    var goal_idx = _idx(g_layer, g_x, g_y, w, h)

    var ws = AStarWorkspace(w * h * layers)
    var diagonal = _bool(payload, "diagonal", True)
    var via_pen = UInt32(_int(payload, "via_penalty"))
    var lp_outer = UInt32(_int(payload, "layer_penalty_outer"))
    var lp_in1 = UInt32(_int(payload, "layer_penalty_in1"))
    var lp_inner = UInt32(_int(payload, "layer_penalty_inner"))
    var margin = _int(payload, "margin")
    var max_exp = UInt32(_int(payload, "astar_max_expansions"))
    var hw = UInt32(_int(payload, "heuristic_weight_pct"))

    # Defaults match `route_a_star` signature; can be overridden by dumps.
    var enforce_spacing = _bool(payload, "enforce_spacing", False)
    var enforce_touch = _bool(payload, "enforce_touch", True)
    var allow_overlaps = _bool(payload, "allow_overlaps", True)

    var empty_u32 = List[UInt32](length=w * h * layers, fill=UInt32(0))
    var empty_u32b = List[UInt32](length=w * h * layers, fill=UInt32(0))

    var path = route_a_star(
        ws,
        g,
        start_idx,
        goal_idx,
        net_id,
        UInt64(0),
        diagonal,
        via_pen,
        lp_outer,
        lp_in1,
        lp_inner,
        margin,
        max_exp,
        hw,
        Float64(0.0),  # deadline disabled
        enforce_spacing,
        enforce_touch,
        allow_overlaps,
        UInt32(0),
        UInt16(0),
        UInt32(0),
        UInt32(0),
        False,
        empty_u32,
        empty_u32b,
        False,
        allowed_mask,
    )

    if len(path) == 0:
        print("NO_PATH")
        return 1
    print("PATH_LEN", len(path))
    return 0
