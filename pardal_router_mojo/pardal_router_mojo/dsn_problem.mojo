from collections import List

from python import Python, PythonObject

from .dsn import (
    dsn_coord_to_mm,
    parse_dsn_boundary_bbox_mm,
    parse_dsn_class_members,
    parse_dsn_class_rules,
    parse_dsn_keepout_circles_mm,
    parse_dsn_keepout_polygons_mm,
    parse_dsn_layers,
    parse_dsn_net_pins,
    parse_dsn_pin_positions_mm,
    parse_dsn_resolution,
    parse_dsn_structure_rules,
    parse_dsn_wiring_mm,
    parse_dsn_wiring_vias_mm,
)

comptime py = Python


fn _py_is_none(o: PythonObject) raises -> Bool:
    var operator = py.import_module("operator")
    return Bool(py=operator.is_(o, py.none()))


fn _round_int(x: Float64) raises -> Int:
    var builtins = py.import_module("builtins")
    return Int(py=builtins.round(PythonObject(x)))


fn _ceil_int(x: Float64) raises -> Int:
    var math = py.import_module("math")
    return Int(py=math.ceil(PythonObject(x)))


fn _grid_xy(x_mm: Float64, y_mm: Float64, origin_x_mm: Float64, origin_y_mm: Float64, resolution_mm: Float64) raises -> Tuple[Int, Int]:
    var gx = _round_int((x_mm - origin_x_mm) / resolution_mm)
    var gy = _round_int((y_mm - origin_y_mm) / resolution_mm)
    return (gx, gy)


fn _layers_sorted_by_index(layer_recs: PythonObject) raises -> List[String]:
    var names = List[String]()
    var idxs = List[Int]()
    for rec in layer_recs:
        var name = String(py=rec[PythonObject(String("name"))])
        var idx_obj = rec[PythonObject(String("index"))]
        var idx = 0
        if _py_is_none(idx_obj):
            idx = len(names)
        else:
            idx = Int(py=idx_obj)
        names.append(name)
        idxs.append(idx)

    # Selection sort by index.
    var out = List[String]()
    var used = List[Bool](length=len(names), fill=False)
    var k = 0
    while k < len(names):
        var best = -1
        var best_idx = 1_000_000_000
        var i = 0
        while i < len(names):
            if not used[i] and idxs[i] < best_idx:
                best_idx = idxs[i]
                best = i
            i += 1
        if best < 0:
            break
        used[best] = True
        out.append(names[best])
        k += 1
    return out^


fn dsn_problem_from_src(
    src: String,
    *,
    resolution_mm_override: Float64,
    keepout_inflate_mm_override: Float64,
    net_limit: Int,
) raises -> PythonObject:
    var unit_name, div = parse_dsn_resolution(src)
    var res_mm = dsn_coord_to_mm(Float64(1.0), unit_name, div)
    if resolution_mm_override > Float64(0.0):
        res_mm = resolution_mm_override

    var layer_recs = parse_dsn_layers(src)
    var layer_names = _layers_sorted_by_index(layer_recs)
    if len(layer_names) == 0:
        layer_names.append(String("F.Cu"))
        layer_names.append(String("B.Cu"))

    var bb = parse_dsn_boundary_bbox_mm(src)
    var min_x = Float64(0.0)
    var min_y = Float64(0.0)
    var max_x = Float64(1000.0)
    var max_y = Float64(1000.0)
    if not _py_is_none(bb[PythonObject(String("min_x"))]):
        min_x = Float64(py=bb[PythonObject(String("min_x"))])
        min_y = Float64(py=bb[PythonObject(String("min_y"))])
        max_x = Float64(py=bb[PythonObject(String("max_x"))])
        max_y = Float64(py=bb[PythonObject(String("max_y"))])

    var origin_x_mm = min_x
    var origin_y_mm = min_y

    var w = _ceil_int((max_x - min_x) / res_mm) + 1
    var h = _ceil_int((max_y - min_y) / res_mm) + 1

    var rules = parse_dsn_structure_rules(src)
    var rule_w = rules[PythonObject(String("width"))]
    var rule_c = rules[PythonObject(String("clearance"))]
    var rule_w_mm = res_mm
    var rule_c_mm = res_mm
    var rule_w_present = False
    var rule_c_present = False
    if not _py_is_none(rule_w):
        rule_w_mm = dsn_coord_to_mm(Float64(py=rule_w), unit_name, div)
        rule_w_present = True
    if not _py_is_none(rule_c):
        rule_c_mm = dsn_coord_to_mm(Float64(py=rule_c), unit_name, div)
        rule_c_present = True

    var keepout_inflate_mm = res_mm
    if keepout_inflate_mm_override > Float64(0.0):
        keepout_inflate_mm = keepout_inflate_mm_override

    # Map net->class width overrides.
    var class_members = parse_dsn_class_members(src)
    var class_rules = parse_dsn_class_rules(src)
    var net_width_override = py.dict()
    for cname in class_members:
        if not Bool(class_rules.__contains__(cname)):
            continue
        var cr = class_rules[cname]
        var w0 = cr[PythonObject(String("width"))]
        if _py_is_none(w0):
            continue
        var w_mm = dsn_coord_to_mm(Float64(py=w0), unit_name, div)
        var nets = class_members[cname]
        for n in nets:
            net_width_override[n] = PythonObject(w_mm)

    var pin_pos = parse_dsn_pin_positions_mm(src)
    var net_pins = parse_dsn_net_pins(src)

    var net_specs = py.list()
    var net_id_by_name = py.dict()
    var next_id = 1
    var n_nets = 0

    for net_name in net_pins:
        if net_limit > 0 and n_nets >= net_limit:
            break
        var pins = net_pins[net_name]
        # Build pin coordinate arrays.
        var pts_x = List[Float64]()
        var pts_y = List[Float64]()
        for p in pins:
            if Bool(pin_pos.__contains__(p)):
                var t = pin_pos[p]
                pts_x.append(Float64(py=t[PythonObject(Int(0))]))
                pts_y.append(Float64(py=t[PythonObject(Int(1))]))
        if len(pts_x) < 2:
            continue

        if not Bool(net_id_by_name.__contains__(net_name)):
            net_id_by_name[net_name] = PythonObject(Int(next_id))
            next_id += 1
        var net_id = Int(py=net_id_by_name[net_name])

        # MST over pins (Prim, O(n^2)).
        var n = len(pts_x)
        var in_tree = List[Bool](length=n, fill=False)
        var best = List[Float64](length=n, fill=Float64(1e30))
        var parent = List[Int](length=n, fill=-1)
        best[0] = Float64(0.0)

        var it = 0
        while it < n:
            var u = -1
            var bestd = Float64(1e30)
            var i = 0
            while i < n:
                if not in_tree[i] and best[i] < bestd:
                    bestd = best[i]
                    u = i
                i += 1
            if u < 0:
                break
            in_tree[u] = True
            var ux = pts_x[u]
            var uy = pts_y[u]
            var v = 0
            while v < n:
                if in_tree[v]:
                    v += 1
                    continue
                var dx = ux - pts_x[v]
                var dy = uy - pts_y[v]
                var d2 = dx * dx + dy * dy
                if d2 < best[v]:
                    best[v] = d2
                    parent[v] = u
                v += 1
            it += 1

        var v2 = 1
        while v2 < n:
            var u2 = parent[v2]
            if u2 < 0:
                v2 += 1
                continue
            var sx, sy = _grid_xy(pts_x[u2], pts_y[u2], origin_x_mm, origin_y_mm, res_mm)
            var gx, gy = _grid_xy(pts_x[v2], pts_y[v2], origin_x_mm, origin_y_mm, res_mm)

            var spec = py.dict()
            spec[PythonObject(String("net"))] = net_name
            spec[PythonObject(String("net_id"))] = PythonObject(Int(net_id))
            var start = py.dict()
            start[PythonObject(String("layer"))] = PythonObject(Int(0))
            start[PythonObject(String("x"))] = PythonObject(Int(sx))
            start[PythonObject(String("y"))] = PythonObject(Int(sy))
            var goal = py.dict()
            goal[PythonObject(String("layer"))] = PythonObject(Int(0))
            goal[PythonObject(String("x"))] = PythonObject(Int(gx))
            goal[PythonObject(String("y"))] = PythonObject(Int(gy))
            spec[PythonObject(String("start"))] = start
            spec[PythonObject(String("goal"))] = goal

            var tw = rule_w_mm
            if Bool(net_width_override.__contains__(net_name)):
                tw = Float64(py=net_width_override[net_name])
            spec[PythonObject(String("track_width_mm"))] = PythonObject(tw)
            spec[PythonObject(String("via_diameter_mm"))] = PythonObject(Float64(0.6))
            spec[PythonObject(String("via_drill_mm"))] = PythonObject(Float64(0.3))
            spec[PythonObject(String("uvia_diameter_mm"))] = PythonObject(Float64(0.35))
            spec[PythonObject(String("uvia_drill_mm"))] = PythonObject(Float64(0.15))
            net_specs.append(spec)
            v2 += 1

        n_nets += 1

    # Keepout circles and polygons.
    var circles = py.list()
    var polygons = py.list()
    var keep_circles = parse_dsn_keepout_circles_mm(src)
    var keep_polys = parse_dsn_keepout_polygons_mm(src)
    var all_layers = py.list()
    var li = 0
    while li < len(layer_names):
        all_layers.append(PythonObject(Int(li)))
        li += 1

    for rec in keep_circles:
        var lname = String(py=rec[PythonObject(Int(0))])
        var lname_lower = lname
        try:
            lname_lower = String(py=rec[PythonObject(Int(0))].lower())
        except:
            lname_lower = lname
        var x_mm = Float64(py=rec[PythonObject(Int(1))])
        var y_mm = Float64(py=rec[PythonObject(Int(2))])
        var r_mm = Float64(py=rec[PythonObject(Int(3))])
        var keep_layers = py.list()
        if lname_lower == String("signal"):
            keep_layers = all_layers
        else:
            var idx = -1
            var i2 = 0
            while i2 < len(layer_names):
                if layer_names[i2] == lname:
                    idx = i2
                    break
                i2 += 1
            if idx >= 0:
                keep_layers.append(PythonObject(Int(idx)))
            else:
                keep_layers = all_layers
        var gx, gy = _grid_xy(x_mm, y_mm, origin_x_mm, origin_y_mm, res_mm)
        var gr = _ceil_int(r_mm / res_mm)
        var crec = py.dict()
        crec[PythonObject(String("net_id"))] = PythonObject(Int(0))
        crec[PythonObject(String("layers"))] = keep_layers
        var center = py.dict()
        center[PythonObject(String("x"))] = PythonObject(Int(gx))
        center[PythonObject(String("y"))] = PythonObject(Int(gy))
        crec[PythonObject(String("center"))] = center
        crec[PythonObject(String("r"))] = PythonObject(Int(gr))
        circles.append(crec)

    for rec in keep_polys:
        var lname = String(py=rec[PythonObject(Int(0))])
        var lname_lower = lname
        try:
            lname_lower = String(py=rec[PythonObject(Int(0))].lower())
        except:
            lname_lower = lname
        var pts = rec[PythonObject(Int(1))]
        var keep_layers = py.list()
        if lname_lower == String("signal"):
            keep_layers = all_layers
        else:
            var idx = -1
            var i3 = 0
            while i3 < len(layer_names):
                if layer_names[i3] == lname:
                    idx = i3
                    break
                i3 += 1
            if idx >= 0:
                keep_layers.append(PythonObject(Int(idx)))
            else:
                keep_layers = all_layers
        var gpts = py.list()
        for pt in pts:
            var px = Float64(py=pt[PythonObject(Int(0))])
            var pyv = Float64(py=pt[PythonObject(Int(1))])
            var gx, gy = _grid_xy(px, pyv, origin_x_mm, origin_y_mm, res_mm)
            var p = py.dict()
            p[PythonObject(String("x"))] = PythonObject(Int(gx))
            p[PythonObject(String("y"))] = PythonObject(Int(gy))
            gpts.append(p)
        var prec = py.dict()
        prec[PythonObject(String("net_id"))] = PythonObject(Int(0))
        prec[PythonObject(String("layers"))] = keep_layers
        prec[PythonObject(String("points"))] = gpts
        polygons.append(prec)

    # Existing wiring from DSN.
    var existing_tracks = py.list()
    var wiring = parse_dsn_wiring_mm(src)
    var wires = wiring[PythonObject(String("wires"))]
    for wrec in wires:
        var layer = wrec[PythonObject(String("layer"))]
        var net = wrec[PythonObject(String("net"))]
        var width_mm = wrec[PythonObject(String("width_mm"))]
        var pts = wrec[PythonObject(String("points_mm"))]
        var i = 0
        while i + 1 < Int(py=pts.__len__()):
            var p0 = pts[PythonObject(Int(i))]
            var p1 = pts[PythonObject(Int(i + 1))]
            var rec = py.dict()
            rec[PythonObject(String("net"))] = net
            if (not _py_is_none(net)) and Bool(net_id_by_name.__contains__(net)):
                rec[PythonObject(String("net_id"))] = net_id_by_name[net]
            else:
                rec[PythonObject(String("net_id"))] = PythonObject(Int(0))
            rec[PythonObject(String("layer"))] = layer
            if not _py_is_none(width_mm):
                rec[PythonObject(String("width_mm"))] = width_mm
            else:
                rec[PythonObject(String("width_mm"))] = PythonObject(rule_w_mm)
            var s_mm = py.list()
            s_mm.append(PythonObject(Float64(py=p0[PythonObject(Int(0))])))
            s_mm.append(PythonObject(Float64(py=p0[PythonObject(Int(1))])))
            var e_mm = py.list()
            e_mm.append(PythonObject(Float64(py=p1[PythonObject(Int(0))])))
            e_mm.append(PythonObject(Float64(py=p1[PythonObject(Int(1))])))
            rec[PythonObject(String("start_mm"))] = s_mm
            rec[PythonObject(String("end_mm"))] = e_mm
            existing_tracks.append(rec)
            i += 1

    var existing_vias = py.list()
    var vias = parse_dsn_wiring_vias_mm(src)
    for vrec in vias:
        var net = vrec[PythonObject(String("net"))]
        var x_mm = Float64(py=vrec[PythonObject(String("x_mm"))])
        var y_mm = Float64(py=vrec[PythonObject(String("y_mm"))])
        var size_mm = rule_w_mm
        if Bool(vrec.__contains__(PythonObject(String("diameter_mm")))):
            size_mm = Float64(py=vrec[PythonObject(String("diameter_mm"))])
        var layers = py.list()
        if Bool(vrec.__contains__(PythonObject(String("lo")))) and Bool(vrec.__contains__(PythonObject(String("hi")))):
            var lo = Int(py=vrec[PythonObject(String("lo"))])
            var hi = Int(py=vrec[PythonObject(String("hi"))])
            if lo > hi:
                var t = lo
                lo = hi
                hi = t
            var li2 = lo
            while li2 <= hi:
                layers.append(PythonObject(Int(li2)))
                li2 += 1
        else:
            layers = all_layers
        var gx, gy = _grid_xy(x_mm, y_mm, origin_x_mm, origin_y_mm, res_mm)
        var v = py.dict()
        v[PythonObject(String("net"))] = net
        if (not _py_is_none(net)) and Bool(net_id_by_name.__contains__(net)):
            v[PythonObject(String("net_id"))] = net_id_by_name[net]
        else:
            v[PythonObject(String("net_id"))] = PythonObject(Int(0))
        var center = py.dict()
        center[PythonObject(String("x"))] = PythonObject(Int(gx))
        center[PythonObject(String("y"))] = PythonObject(Int(gy))
        v[PythonObject(String("center"))] = center
        v[PythonObject(String("layers"))] = layers
        v[PythonObject(String("size_mm"))] = PythonObject(size_mm)
        existing_vias.append(v)

    var payload = py.dict()
    payload[PythonObject(String("format"))] = PythonObject(String("dsn_mvp"))
    var layer_list = py.list()
    for n in layer_names:
        layer_list.append(PythonObject(n))
    payload[PythonObject(String("layers"))] = layer_list
    payload[PythonObject(String("resolution_mm"))] = PythonObject(res_mm)
    var origin = py.dict()
    origin[PythonObject(String("x"))] = PythonObject(origin_x_mm)
    origin[PythonObject(String("y"))] = PythonObject(origin_y_mm)
    payload[PythonObject(String("origin_mm"))] = origin
    payload[PythonObject(String("width"))] = PythonObject(Int(w))
    payload[PythonObject(String("height"))] = PythonObject(Int(h))
    payload[PythonObject(String("nets"))] = net_specs
    payload[PythonObject(String("circles"))] = circles
    payload[PythonObject(String("polygons"))] = polygons
    payload[PythonObject(String("existing_tracks"))] = existing_tracks
    payload[PythonObject(String("existing_vias"))] = existing_vias
    payload[PythonObject(String("pad_stacks"))] = py.list()

    var defaults = py.dict()
    defaults[PythonObject(String("track_width_mm"))] = PythonObject(rule_w_mm if rule_w_present else res_mm)
    var clr_mm = keepout_inflate_mm
    if rule_c_present:
        clr_mm = rule_c_mm
    defaults[PythonObject(String("clearance_mm"))] = PythonObject(clr_mm)
    defaults[PythonObject(String("via_diameter_mm"))] = PythonObject(Float64(0.6))
    defaults[PythonObject(String("via_drill_mm"))] = PythonObject(Float64(0.3))
    defaults[PythonObject(String("uvia_diameter_mm"))] = PythonObject(Float64(0.35))
    defaults[PythonObject(String("uvia_drill_mm"))] = PythonObject(Float64(0.15))
    payload[PythonObject(String("net_defaults"))] = defaults

    var bbox = py.dict()
    bbox[PythonObject(String("x"))] = PythonObject(min_x)
    bbox[PythonObject(String("y"))] = PythonObject(min_y)
    bbox[PythonObject(String("w"))] = PythonObject(max_x - min_x)
    bbox[PythonObject(String("h"))] = PythonObject(max_y - min_y)
    payload[PythonObject(String("board_bbox_mm"))] = bbox
    return payload


fn dsn_problem_from_path(
    path: String,
    *,
    resolution_mm_override: Float64,
    keepout_inflate_mm_override: Float64,
    net_limit: Int,
) raises -> PythonObject:
    var pathlib = py.import_module("pathlib")
    var txt = pathlib.Path(PythonObject(path)).read_text()
    return dsn_problem_from_src(
        String(py=txt),
        resolution_mm_override=resolution_mm_override,
        keepout_inflate_mm_override=keepout_inflate_mm_override,
        net_limit=net_limit,
    )
