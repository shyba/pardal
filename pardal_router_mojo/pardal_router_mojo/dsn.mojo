from python import Python, PythonObject

from pardal_router_mojo.sexpr import parse_sexpr

comptime py = Python

fn _py_is_none(o: PythonObject) raises -> Bool:
    var operator = py.import_module("operator")
    return Bool(py=operator.is_(o, py.none()))


struct DsnPcbSummary:
    var pcb_symbol: String  # "pcb" or "PCB"
    var layer_count: Int
    # Use Python lists to avoid Mojo move/copy restrictions for nested containers.
    var layer_names: PythonObject
    var layer_kinds: PythonObject
    var has_boundary: Bool
    var boundary_xs: PythonObject
    var boundary_ys: PythonObject
    var keepout_count: Int
    var plane_count: Int

    fn __init__(
        out self,
        pcb_symbol: String,
        layer_count: Int,
        layer_names: PythonObject,
        layer_kinds: PythonObject,
        has_boundary: Bool,
        boundary_xs: PythonObject,
        boundary_ys: PythonObject,
        keepout_count: Int,
        plane_count: Int,
    ):
        self.pcb_symbol = pcb_symbol
        self.layer_count = layer_count
        self.layer_names = layer_names
        self.layer_kinds = layer_kinds
        self.has_boundary = has_boundary
        self.boundary_xs = boundary_xs
        self.boundary_ys = boundary_ys
        self.keepout_count = keepout_count
        self.plane_count = plane_count


fn _is_list(o: PythonObject) raises -> Bool:
    var builtins = py.import_module("builtins")
    return Bool(py=builtins.isinstance(o, builtins.list))


fn _len(o: PythonObject) raises -> Int:
    var builtins = py.import_module("builtins")
    return Int(py=builtins.len(o))


fn _as_str(o: PythonObject) raises -> String:
    return String(py=o)


fn _as_f64(o: PythonObject) raises -> Float64:
    # DSN numeric atoms are parsed as strings by `parse_sexpr`.
    return Float64(_as_str(o))


fn _head_symbol(x: PythonObject) raises -> String:
    if not _is_list(x):
        return _as_str(x)
    if _len(x) == 0:
        return String("")
    var h = x[PythonObject(Int(0))]
    if _is_list(h):
        return String("")
    return _as_str(h)


fn _find_first_list_with_head(root: PythonObject, head: String) raises -> PythonObject:
    # DFS, returning the first list whose head atom matches `head`.
    var stack = List[PythonObject]()
    stack.append(root)
    while len(stack) > 0:
        var n = stack.pop()
        if _is_list(n) and _len(n) > 0 and _head_symbol(n) == head:
            return n
        if _is_list(n):
            for child in n:
                if _is_list(child):
                    stack.append(child)
    raise Error("dsn: missing list head: " + head)


fn _find_all_direct_children_with_head(parent: PythonObject, head: String) raises -> List[PythonObject]:
    var out = List[PythonObject]()
    if not _is_list(parent):
        return out^
    for child in parent:
        if _is_list(child) and _len(child) > 0 and _head_symbol(child) == head:
            out.append(child)
    return out^

fn _find_all_lists_with_head(root: PythonObject, head: String) raises -> List[PythonObject]:
    # DFS returning all lists whose head atom matches `head`.
    var out = List[PythonObject]()
    var stack = List[PythonObject]()
    stack.append(root)
    while len(stack) > 0:
        var n = stack.pop()
        if _is_list(n) and _len(n) > 0:
            if _head_symbol(n) == head:
                out.append(n)
            for child in n:
                if _is_list(child):
                    stack.append(child)
    return out^


fn _extract_layers_from_structure(structure: PythonObject) raises -> Tuple[PythonObject, PythonObject]:
    var names = py.list()
    var kinds = py.list()
    var layer_lists = _find_all_direct_children_with_head(structure, String("layer"))
    for ll in layer_lists:
        if _len(ll) < 2:
            continue
        var name = _as_str(ll[PythonObject(Int(1))])
        var kind = String("")
        # Typical: (layer F.Cu (type signal) ...)
        for child in ll:
            if _is_list(child) and _len(child) >= 2 and _head_symbol(child) == String("type"):
                kind = _as_str(child[PythonObject(Int(1))])
                break
        names.append(PythonObject(name))
        kinds.append(PythonObject(kind))
    return (names, kinds)

fn _count_lists_with_head(root: PythonObject, head: String) raises -> Int:
    var count = 0
    var stack = List[PythonObject]()
    stack.append(root)
    while len(stack) > 0:
        var n = stack.pop()
        if _is_list(n) and _len(n) > 0:
            if _head_symbol(n) == head:
                count += 1
            for child in n:
                if _is_list(child):
                    stack.append(child)
    return count


fn _try_extract_boundary_from_structure(structure: PythonObject) raises -> Tuple[Bool, PythonObject, PythonObject]:
    # Minimal extraction:
    # (structure ... (boundary (path <layer> <width> x y x y ...)) ...)
    # Return the first boundary path's points.
    var xs = py.list()
    var ys = py.list()
    var boundary_lists = _find_all_direct_children_with_head(structure, String("boundary"))
    if len(boundary_lists) == 0:
        return (False, xs, ys)
    var boundary = boundary_lists[0]
    var path_lists = _find_all_direct_children_with_head(boundary, String("path"))
    if len(path_lists) == 0:
        return (True, xs, ys)
    var path = path_lists[0]
    # path format: (path <layer> <width> x y x y ...)
    if _len(path) < 5:
        return (True, xs, ys)
    var i = 3
    while i + 1 < _len(path):
        xs.append(PythonObject(_as_f64(path[PythonObject(Int(i))])))
        ys.append(PythonObject(_as_f64(path[PythonObject(Int(i + 1))])))
        i += 2
    return (True, xs, ys)


fn parse_dsn_summary(src: String) raises -> DsnPcbSummary:
    """Parse a DSN and extract a minimal summary.

    This is a stepping stone for DSN/SES parity:
    - typed extraction of layers
    - presence + raw points of the outline boundary
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    if not _is_list(top) or _len(top) == 0:
        raise Error("dsn: top-level form is not a list")
    var pcb_sym = _head_symbol(top)
    var structure = _find_first_list_with_head(top, String("structure"))
    var layer_names, layer_kinds = _extract_layers_from_structure(structure)
    var has_boundary, boundary_xs, boundary_ys = _try_extract_boundary_from_structure(structure)
    var layer_count = Int(py=layer_names.__len__())
    var keepouts = _count_lists_with_head(top, String("keepout"))
    var planes = _count_lists_with_head(top, String("plane"))
    return DsnPcbSummary(
        pcb_sym,
        layer_count,
        layer_names,
        layer_kinds,
        has_boundary,
        boundary_xs,
        boundary_ys,
        keepouts,
        planes,
    )


fn parse_dsn_boundary_mm(src: String) raises -> PythonObject:
    """Return boundary polygon points in mm as a Python list of `(x_mm, y_mm)` tuples."""
    var unit_name, div = parse_dsn_resolution(src)
    var s = parse_dsn_summary(src)
    if not s.has_boundary:
        return py.list()
    var out = py.list()
    var n = Int(py=s.boundary_xs.__len__())
    var i = 0
    while i < n:
        var x = Float64(py=s.boundary_xs[PythonObject(Int(i))])
        var y = Float64(py=s.boundary_ys[PythonObject(Int(i))])
        out.append(
            py.tuple(
                PythonObject(dsn_coord_to_mm(x, unit_name, div)),
                PythonObject(dsn_coord_to_mm(y, unit_name, div)),
            )
        )
        i += 1
    return out


fn parse_dsn_boundary_bbox_mm(src: String) raises -> PythonObject:
    """Return `{min_x, min_y, max_x, max_y}` for the DSN boundary in mm."""
    var pts = parse_dsn_boundary_mm(src)
    if Int(py=pts.__len__()) == 0:
        var empty = py.dict()
        empty[PythonObject(String("min_x"))] = py.none()
        empty[PythonObject(String("min_y"))] = py.none()
        empty[PythonObject(String("max_x"))] = py.none()
        empty[PythonObject(String("max_y"))] = py.none()
        return empty
    var x0 = Float64(py=pts[PythonObject(Int(0))][PythonObject(Int(0))])
    var y0 = Float64(py=pts[PythonObject(Int(0))][PythonObject(Int(1))])
    var min_x = x0
    var max_x = x0
    var min_y = y0
    var max_y = y0
    for p in pts:
        var x = Float64(py=p[PythonObject(Int(0))])
        var y = Float64(py=p[PythonObject(Int(1))])
        if x < min_x:
            min_x = x
        if x > max_x:
            max_x = x
        if y < min_y:
            min_y = y
        if y > max_y:
            max_y = y
    var rec = py.dict()
    rec[PythonObject(String("min_x"))] = PythonObject(min_x)
    rec[PythonObject(String("min_y"))] = PythonObject(min_y)
    rec[PythonObject(String("max_x"))] = PythonObject(max_x)
    rec[PythonObject(String("max_y"))] = PythonObject(max_y)
    return rec


fn parse_dsn_pcb_name(src: String) raises -> String:
    """Return the `(pcb <name> ...)` name token as a string."""
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    if not _is_list(top) or _len(top) < 2:
        raise Error("dsn: top-level form missing pcb name")
    # (pcb NAME ...)
    return _as_str(top[PythonObject(Int(1))])


fn parse_dsn_net_names(src: String) raises -> PythonObject:
    """Return DSN net names as a Python list of strings.

    Supports minimal FreeRouting/KiCad DSNs that have `(network (net <name> ...) ...)`.
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var network = _find_first_list_with_head(top, String("network"))
    var out = py.list()
    for child in network:
        if not _is_list(child) or _len(child) < 2:
            continue
        if _head_symbol(child) != String("net"):
            continue
        out.append(child[PythonObject(Int(1))])
    return out


fn parse_dsn_net_pins(src: String) raises -> PythonObject:
    """Return `{net_name: [pin_refs...]}` as a Python dict.

    Pin refs are returned as raw DSN atoms such as `J8-1` or `U1-A1`.
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var network = _find_first_list_with_head(top, String("network"))
    var out = py.dict()
    for child in network:
        if not _is_list(child) or _len(child) < 2:
            continue
        if _head_symbol(child) != String("net"):
            continue
        var net_name = child[PythonObject(Int(1))]
        var pins = py.list()
        for n2 in child:
            if not _is_list(n2) or _len(n2) < 2:
                continue
            if _head_symbol(n2) != String("pins"):
                continue
            var i = 1
            while i < _len(n2):
                pins.append(n2[PythonObject(Int(i))])
                i += 1
        out[net_name] = pins
    return out


fn parse_dsn_class_members(src: String) raises -> PythonObject:
    """Return `{class_name: [net_name...]}` as a Python dict.

    Parses `(class <name> <description> <net> <net> ...)` entries in `(network ...)`.
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var network = _find_first_list_with_head(top, String("network"))
    var out = py.dict()
    for child in network:
        if not _is_list(child) or _len(child) < 2:
            continue
        if _head_symbol(child) != String("class"):
            continue
        # (class NAME DESC NET NET ... (rule ...) (circuit ...) ...)
        var name = child[PythonObject(Int(1))]
        var members = py.list()
        var i = 3  # skip NAME and DESC
        while i < _len(child):
            var tok = child[PythonObject(Int(i))]
            if _is_list(tok):
                break
            members.append(tok)
            i += 1
        out[name] = members
    return out


fn parse_dsn_class_rules(src: String) raises -> PythonObject:
    """Return `{class_name: {width: float|None, clearance: float|None, use_via: str|None}}`.

    Extracts a minimal subset of the DSN rules that are critical for routing parity:
    - `(rule (width <n>) (clearance <n>))` under a `(class ...)`
    - `(circuit (use_via <padstack_name>))` under a `(class ...)`
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var network = _find_first_list_with_head(top, String("network"))
    var out = py.dict()
    for child in network:
        if not _is_list(child) or _len(child) < 2:
            continue
        if _head_symbol(child) != String("class"):
            continue
        var name = child[PythonObject(Int(1))]
        var width = py.none()
        var clearance = py.none()
        var use_via = py.none()
        for n2 in child:
            if not _is_list(n2) or _len(n2) < 1:
                continue
            var h = _head_symbol(n2)
            if h == String("rule"):
                for r2 in n2:
                    if not _is_list(r2) or _len(r2) < 2:
                        continue
                    var rh = _head_symbol(r2)
                    if rh == String("width"):
                        width = PythonObject(_as_f64(r2[PythonObject(Int(1))]))
                    elif rh == String("clearance"):
                        clearance = PythonObject(_as_f64(r2[PythonObject(Int(1))]))
            elif h == String("circuit"):
                for c2 in n2:
                    if not _is_list(c2) or _len(c2) < 2:
                        continue
                    if _head_symbol(c2) == String("use_via"):
                        use_via = c2[PythonObject(Int(1))]
        var rec = py.dict()
        rec[PythonObject(String("width"))] = width
        rec[PythonObject(String("clearance"))] = clearance
        rec[PythonObject(String("use_via"))] = use_via
        out[name] = rec
    return out


fn parse_dsn_padstacks(src: String) raises -> PythonObject:
    """Return a minimal padstack library as `{name: {shapes: [(layer, kind, size...)]}}`.

    This is intentionally partial and focuses on via padstacks emitted by KiCad/FreeRouting:
    - `(structure (via ... (padstack "<name>" (shape (circle <layer> <diam>)) ...) ...))`
    - `(structure (via ... (padstack "<name>" (shape (rect <layer> x0 y0 x1 y1)) ...) ...))`

    Output shape tuples:
    - circle: `(layer_name, "circle", diam)`
    - rect: `(layer_name, "rect", x0, y0, x1, y1)`
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var library = _find_first_list_with_head(top, String("library"))
    var out = py.dict()

    for child in library:
        if not _is_list(child) or _len(child) < 2:
            continue
        if _head_symbol(child) != String("padstack"):
            continue
        var name = child[PythonObject(Int(1))]
        var shapes = py.list()
        for ps_child in child:
            if not _is_list(ps_child) or _len(ps_child) < 2:
                continue
            if _head_symbol(ps_child) != String("shape"):
                continue
            # (shape (circle F.Cu 600)) OR (shape (rect F.Cu x0 y0 x1 y1))
            var s0 = ps_child[PythonObject(Int(1))]
            if not _is_list(s0) or _len(s0) < 3:
                continue
            var kind = _head_symbol(s0)
            if kind == String("circle") and _len(s0) >= 3:
                var layer = s0[PythonObject(Int(1))]
                var diam = _as_f64(s0[PythonObject(Int(2))])
                shapes.append(py.tuple(layer, PythonObject(String("circle")), PythonObject(diam)))
            elif kind == String("rect") and _len(s0) >= 6:
                var layer = s0[PythonObject(Int(1))]
                var x0 = _as_f64(s0[PythonObject(Int(2))])
                var y0 = _as_f64(s0[PythonObject(Int(3))])
                var x1 = _as_f64(s0[PythonObject(Int(4))])
                var y1 = _as_f64(s0[PythonObject(Int(5))])
                shapes.append(
                    py.tuple(
                        layer,
                        PythonObject(String("rect")),
                        PythonObject(x0),
                        PythonObject(y0),
                        PythonObject(x1),
                        PythonObject(y1),
                    )
                )
        var rec = py.dict()
        rec[PythonObject(String("shapes"))] = shapes
        out[name] = rec
    return out


fn _str_find(hay: String, needle: String) -> Int:
    # Naive substring search (small inputs); returns -1 if not found.
    var i = 0
    while i + len(needle) <= len(hay):
        var ok = True
        var j = 0
        while j < len(needle):
            if hay[byte=i + j] != needle[byte=j]:
                ok = False
                break
            j += 1
        if ok:
            return i
        i += 1
    return -1


fn _parse_u32_dec(s: String) raises -> UInt32:
    # Robust decimal parsing: only used for KiCad-style via-name decoding.
    # Some DSNs contain values like "304.8"; accept those by parsing as float
    # and truncating toward zero (Python `int()` semantics).
    var builtins = py.import_module("builtins")
    var f = builtins.float(PythonObject(s))
    var i = builtins.int(f)
    return UInt32(Int(py=i))

fn _substr(s: String, start_i: Int, end_i: Int) raises -> String:
    var start = start_i
    var end = end_i
    if start < 0:
        start = 0
    if end < start:
        end = start
    if end > len(s):
        end = len(s)
    var out = String("")
    var i = start
    while i < end:
        out += String(s[byte=i])
        i += 1
    return out


fn parse_dsn_resolution(src: String) raises -> Tuple[String, Float64]:
    """Return `(unit_name, resolution)` for DSN coordinates.

    DSN commonly has:
      (resolution um 10)
      (unit um)

    This returns the resolution divisor in the unit specified by the DSN.
    For `(resolution um 10)`, 1 coordinate unit = 10 um.
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var res = _find_first_list_with_head(top, String("resolution"))
    if not _is_list(res) or _len(res) < 3:
        raise Error("dsn: invalid resolution form")
    var unit_name = _as_str(res[PythonObject(Int(1))])
    var div = _as_f64(res[PythonObject(Int(2))])
    return (unit_name, div)

fn _unit_to_mm(unit_name: String) raises -> Float64:
    # Specctra/DSN common units: um, mm, mil, inch/in.
    if unit_name == String("um") or unit_name == String("µm"):
        return Float64(0.001)
    if unit_name == String("mm"):
        return Float64(1.0)
    if unit_name == String("mil"):
        return Float64(0.0254)
    if unit_name == String("in") or unit_name == String("inch"):
        return Float64(25.4)
    raise Error("dsn: unsupported unit: " + unit_name)


fn dsn_coord_to_mm(coord: Float64, unit_name: String, resolution_div: Float64) raises -> Float64:
    """Convert a DSN coordinate value to mm."""
    return coord * resolution_div * _unit_to_mm(unit_name)


fn parse_dsn_wiring_mm(src: String) raises -> PythonObject:
    """Like `parse_dsn_wiring`, but converts numeric fields to mm floats."""
    var unit_name, div = parse_dsn_resolution(src)
    var w = parse_dsn_wiring(src)
    var wires_in = w[PythonObject(String("wires"))]
    var vias_in = w[PythonObject(String("vias"))]
    var wires_out = py.list()
    var vias_out = py.list()

    for rec in wires_in:
        var layer = rec[PythonObject(String("layer"))]
        var net = rec[PythonObject(String("net"))]
        var wtype = rec[PythonObject(String("type"))]
        var width = rec[PythonObject(String("width"))]
        var pts = rec[PythonObject(String("points"))]
        var pts_mm = py.list()
        for p in pts:
            var x = Float64(py=p[PythonObject(Int(0))])
            var y = Float64(py=p[PythonObject(Int(1))])
            pts_mm.append(
                py.tuple(
                    PythonObject(dsn_coord_to_mm(x, unit_name, div)),
                    PythonObject(dsn_coord_to_mm(y, unit_name, div)),
                )
            )
        var rec2 = py.dict()
        rec2[PythonObject(String("layer"))] = layer
        rec2[PythonObject(String("net"))] = net
        rec2[PythonObject(String("type"))] = wtype
        if not _py_is_none(width):
            rec2[PythonObject(String("width_mm"))] = PythonObject(dsn_coord_to_mm(Float64(py=width), unit_name, div))
        else:
            rec2[PythonObject(String("width_mm"))] = py.none()
        rec2[PythonObject(String("points_mm"))] = pts_mm
        wires_out.append(rec2)

    for rec in vias_in:
        var vname = rec[PythonObject(String("via"))]
        var net = rec[PythonObject(String("net"))]
        var vtype = rec[PythonObject(String("type"))]
        var x = Float64(py=rec[PythonObject(String("x"))])
        var y = Float64(py=rec[PythonObject(String("y"))])
        var rec2 = py.dict()
        rec2[PythonObject(String("via"))] = vname
        rec2[PythonObject(String("net"))] = net
        rec2[PythonObject(String("type"))] = vtype
        rec2[PythonObject(String("x_mm"))] = PythonObject(dsn_coord_to_mm(x, unit_name, div))
        rec2[PythonObject(String("y_mm"))] = PythonObject(dsn_coord_to_mm(y, unit_name, div))
        vias_out.append(rec2)

    var out = py.dict()
    out[PythonObject(String("wires"))] = wires_out
    out[PythonObject(String("vias"))] = vias_out
    return out


fn parse_dsn_wiring_vias_mm(src: String) raises -> PythonObject:
    """Return wiring vias annotated with decoded via properties in mm.

    Output: list of `{via, net, type, x_mm, y_mm, lo, hi, diameter_mm, drill_mm}`.
    Missing fields are omitted.
    """
    var wiring = parse_dsn_wiring_mm(src)
    var vias_in = wiring[PythonObject(String("vias"))]
    var catalog = parse_dsn_via_catalog_mm(src)
    var out = py.list()
    for v in vias_in:
        var vname = v[PythonObject(String("via"))]
        var rec = py.dict()
        rec[PythonObject(String("via"))] = vname
        rec[PythonObject(String("net"))] = v[PythonObject(String("net"))]
        rec[PythonObject(String("type"))] = v[PythonObject(String("type"))]
        rec[PythonObject(String("x_mm"))] = v[PythonObject(String("x_mm"))]
        rec[PythonObject(String("y_mm"))] = v[PythonObject(String("y_mm"))]
        if Bool(catalog.__contains__(vname)):
            var c = catalog[vname]
            for key in c:
                rec[key] = c[key]
        out.append(rec)
    return out


fn parse_dsn_placement(src: String) raises -> PythonObject:
    """Parse `(placement ...)` into `{ref: {x, y, side, rot, footprint, pn}}` dict.

    Notes:
    - Coordinates are returned in DSN units (no mm normalization here).
    - KiCad DSN uses `front|back` and rotation degrees.
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var placement = _find_first_list_with_head(top, String("placement"))
    var out = py.dict()

    # (component <footprint> (place <ref> x y <front/back> rot (PN ...)) ...)
    for comp in placement:
        if not _is_list(comp) or _len(comp) < 2:
            continue
        if _head_symbol(comp) != String("component"):
            continue
        var footprint = comp[PythonObject(Int(1))]
        for child in comp:
            if not _is_list(child) or _len(child) < 6:
                continue
            if _head_symbol(child) != String("place"):
                continue
            var refdes = child[PythonObject(Int(1))]
            var x = PythonObject(_as_f64(child[PythonObject(Int(2))]))
            var y = PythonObject(_as_f64(child[PythonObject(Int(3))]))
            var side = child[PythonObject(Int(4))]
            var rot = PythonObject(_as_f64(child[PythonObject(Int(5))]))
            var pn = py.none()
            # Optional: (PN <value>) list may be present after rot.
            var i = 6
            while i < _len(child):
                var extra = child[PythonObject(Int(i))]
                if _is_list(extra) and _len(extra) >= 2 and _head_symbol(extra) == String("PN"):
                    pn = extra[PythonObject(Int(1))]
                i += 1
            var rec = py.dict()
            rec[PythonObject(String("footprint"))] = footprint
            rec[PythonObject(String("x"))] = x
            rec[PythonObject(String("y"))] = y
            rec[PythonObject(String("side"))] = side
            rec[PythonObject(String("rot"))] = rot
            rec[PythonObject(String("pn"))] = pn
            out[refdes] = rec
    return out


fn parse_dsn_library_pins(src: String) raises -> PythonObject:
    """Parse `(library (image <footprint> ... (pin <padstack> <pin_no> dx dy) ...) ...)`.

    Output: `{footprint: [{pin_no, padstack, dx, dy}]}` where dx/dy are in DSN units.
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var library = _find_first_list_with_head(top, String("library"))
    var out = py.dict()

    for child in library:
        if not _is_list(child) or _len(child) < 2:
            continue
        if _head_symbol(child) != String("image"):
            continue
        var footprint = child[PythonObject(Int(1))]
        var pins = py.list()
        for el in child:
            if not _is_list(el) or _len(el) < 5:
                continue
            if _head_symbol(el) != String("pin"):
                continue
            var padstack = el[PythonObject(Int(1))]
            var pin_no = el[PythonObject(Int(2))]
            var dx = PythonObject(_as_f64(el[PythonObject(Int(3))]))
            var dy = PythonObject(_as_f64(el[PythonObject(Int(4))]))
            var rec = py.dict()
            rec[PythonObject(String("padstack"))] = padstack
            rec[PythonObject(String("pin_no"))] = pin_no
            rec[PythonObject(String("dx"))] = dx
            rec[PythonObject(String("dy"))] = dy
            pins.append(rec)
        out[footprint] = pins
    return out


fn _str_rfind(hay: String, needle: String) -> Int:
    # Return last index of `needle` in `hay`, or -1.
    if len(needle) == 0:
        return -1
    var i = len(hay) - len(needle)
    while i >= 0:
        var ok = True
        var j = 0
        while j < len(needle):
            if hay[byte=i + j] != needle[byte=j]:
                ok = False
                break
            j += 1
        if ok:
            return i
        i -= 1
    return -1


fn _split_pin_ref(pin_ref: String) raises -> Tuple[String, String]:
    # DSN pin refs are commonly `REFDES-PIN`, where REFDES can contain '-' in rare cases.
    # Split on the last '-' to be conservative.
    var i = _str_rfind(pin_ref, String("-"))
    if i <= 0 or i + 1 >= len(pin_ref):
        raise Error("dsn: invalid pin ref: " + pin_ref)
    return (_substr(pin_ref, 0, i), _substr(pin_ref, i + 1, len(pin_ref)))


fn parse_dsn_pin_positions_mm(src: String) raises -> PythonObject:
    """Return `{pin_ref: (x_mm, y_mm)}` for all pins mentioned in `(network ...)`.

    Resolution path:
    - parse `(placement ...)` to map `refdes -> (footprint, x, y, rot)`
    - parse `(library (image <footprint> ... (pin <padstack> <pin_no> dx dy)))`
      to map `footprint,pin_no -> (dx,dy)` (local coordinates)
    - parse `(network (net ... (pins REF-PIN ...)))` and resolve each pin ref
      to absolute `(x,y)` with a simple rotation (degrees) around the footprint origin.

    This ignores side mirroring and assumes pin local coords are already for that side.
    It's sufficient for DSN→IR bring-up and fixture parity checks.
    """
    var unit_name, div = parse_dsn_resolution(src)
    var place = parse_dsn_placement(src)
    var pins = parse_dsn_library_pins(src)
    var pins_by_net = parse_dsn_net_pins(src)

    var out = py.dict()
    var math = py.import_module("math")

    for net_name in pins_by_net:
        var pin_list = pins_by_net[net_name]
        for p in pin_list:
            var pref = String(py=p)
            var refdes, pin_no = _split_pin_ref(pref)
            var ref_obj = PythonObject(refdes)
            if not Bool(place.__contains__(ref_obj)):
                continue
            var prec = place[ref_obj]
            var footprint = prec[PythonObject(String("footprint"))]
            if _py_is_none(footprint) or not Bool(pins.__contains__(footprint)):
                continue
            var fp_pins = pins[footprint]
            # Find matching pin_no entry.
            var dx = py.none()
            var dy = py.none()
            for e in fp_pins:
                if String(py=e[PythonObject(String("pin_no"))]) == pin_no:
                    dx = e[PythonObject(String("dx"))]
                    dy = e[PythonObject(String("dy"))]
                    break
            if _py_is_none(dx) or _py_is_none(dy):
                continue

            var x0 = Float64(py=prec[PythonObject(String("x"))])
            var y0 = Float64(py=prec[PythonObject(String("y"))])
            var rot_deg = Float64(py=prec[PythonObject(String("rot"))])
            var side_obj = prec[PythonObject(String("side"))]
            var side_lower = String(py=side_obj)
            try:
                side_lower = String(py=side_obj.lower())
            except:
                side_lower = String(py=side_obj)
            var ang = Float64(py=math.radians(PythonObject(rot_deg)))
            var c = Float64(py=math.cos(PythonObject(ang)))
            var s = Float64(py=math.sin(PythonObject(ang)))
            var lx = Float64(py=dx)
            var ly = Float64(py=dy)
            var x_local = (lx * c - ly * s)
            var y_local = (lx * s + ly * c)
            if side_lower == String("back"):
                x_local = -x_local
            var ax = x0 + x_local
            var ay = y0 + y_local

            out[p] = py.tuple(
                PythonObject(dsn_coord_to_mm(ax, unit_name, div)),
                PythonObject(dsn_coord_to_mm(ay, unit_name, div)),
            )
    return out


fn parse_dsn_via_defs(src: String) raises -> PythonObject:
    """Return via definitions from `(structure (via ...))`.

    Output: `{via_name: {layers: [lo, hi] | None, diameter: float|None, drill: float|None}}`

    Notes:
    - KiCad/FreeRouting encode via span and sizes in the via name, e.g.:
        Via[0-3]_600:300_um  -> layers 0..3, diameter 600um, drill 300um
      This decoder is best-effort and intended for parity tooling.
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var structure = _find_first_list_with_head(top, String("structure"))
    var out = py.dict()

    # Collect `(via "<name>")` entries directly from `structure`.
    for child in structure:
        if not _is_list(child) or _len(child) < 2:
            continue
        if _head_symbol(child) != String("via"):
            continue
        var name_obj = child[PythonObject(Int(1))]
        var name = _as_str(name_obj)

        var rec = py.dict()
        rec[PythonObject(String("layers"))] = py.none()
        rec[PythonObject(String("diameter"))] = py.none()
        rec[PythonObject(String("drill"))] = py.none()

        # Decode `Via[lo-hi]_diam:drill_um` (common KiCad pattern).
        var i0 = _str_find(name, String("Via["))
        if i0 >= 0:
            var i1 = _str_find(name, String("]"))
            if i1 > i0 + 4:
                var span = _substr(name, i0 + 4, i1)
                var dash = _str_find(span, String("-"))
                if dash > 0:
                    var lo_s = _substr(span, 0, dash)
                    var hi_s = _substr(span, dash + 1, len(span))
                    var lo = Int(_parse_u32_dec(lo_s))
                    var hi = Int(_parse_u32_dec(hi_s))
                    rec[PythonObject(String("layers"))] = py.tuple(PythonObject(lo), PythonObject(hi))
        # Decode `_diam:drill_um` suffix.
        var us = _str_find(name, String("_"))
        var um = _str_find(name, String("_um"))
        if us >= 0 and um > us:
            var sizes = _substr(name, us + 1, um)
            var colon = _str_find(sizes, String(":"))
            if colon > 0:
                var dia_s = _substr(sizes, 0, colon)
                var dr_s = _substr(sizes, colon + 1, len(sizes))
                rec[PythonObject(String("diameter"))] = PythonObject(Float64(_parse_u32_dec(dia_s)))
                rec[PythonObject(String("drill"))] = PythonObject(Float64(_parse_u32_dec(dr_s)))

        out[name_obj] = rec
    return out


fn parse_dsn_via_catalog_mm(src: String) raises -> PythonObject:
    """Return `{via_name: {lo, hi, diameter_mm, drill_mm}}` from DSN name decoding.

    This uses:
    - `(resolution ...)` for unit conversion,
    - `parse_dsn_via_defs()` best-effort name decoding.
    """
    var unit_name, div = parse_dsn_resolution(src)
    var defs = parse_dsn_via_defs(src)
    var out = py.dict()
    for k in defs:
        var rec0 = defs[k]
        var rec = py.dict()
        var layers = rec0[PythonObject(String("layers"))]
        if not _py_is_none(layers):
            rec[PythonObject(String("lo"))] = layers[PythonObject(Int(0))]
            rec[PythonObject(String("hi"))] = layers[PythonObject(Int(1))]
        var dia = rec0[PythonObject(String("diameter"))]
        if not _py_is_none(dia):
            rec[PythonObject(String("diameter_mm"))] = PythonObject(
                dsn_coord_to_mm(Float64(py=dia), unit_name, div)
            )
        var dr = rec0[PythonObject(String("drill"))]
        if not _py_is_none(dr):
            rec[PythonObject(String("drill_mm"))] = PythonObject(
                dsn_coord_to_mm(Float64(py=dr), unit_name, div)
            )
        out[k] = rec
    return out


fn parse_dsn_layers(src: String) raises -> PythonObject:
    """Return a Python list of layer records: `{name, type, index}`.

    Extracts from `(structure (layer <name> (type <kind>) (property (index <n>)) ...) ...)`.
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var structure = _find_first_list_with_head(top, String("structure"))
    var out = py.list()
    for child in structure:
        if not _is_list(child) or _len(child) < 2:
            continue
        if _head_symbol(child) != String("layer"):
            continue
        var name = child[PythonObject(Int(1))]
        var kind = py.none()
        var index = py.none()
        for n2 in child:
            if not _is_list(n2) or _len(n2) < 2:
                continue
            var h = _head_symbol(n2)
            if h == String("type"):
                kind = n2[PythonObject(Int(1))]
            elif h == String("property"):
                for p2 in n2:
                    if not _is_list(p2) or _len(p2) < 2:
                        continue
                    if _head_symbol(p2) == String("index"):
                        index = PythonObject(Int(_as_f64(p2[PythonObject(Int(1))])))
        var rec = py.dict()
        rec[PythonObject(String("name"))] = name
        rec[PythonObject(String("type"))] = kind
        rec[PythonObject(String("index"))] = index
        out.append(rec)
    return out


fn parse_dsn_structure_rules(src: String) raises -> PythonObject:
    """Return a minimal structure-level rule summary.

    Output schema:
    `{width: float|None, clearance: float|None, clearance_by_type: {type: float}}`
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var structure = _find_first_list_with_head(top, String("structure"))
    var rule = _find_first_list_with_head(structure, String("rule"))

    var width = py.none()
    var clearance = py.none()
    var by_type = py.dict()
    for child in rule:
        if not _is_list(child) or _len(child) < 2:
            continue
        var h = _head_symbol(child)
        if h == String("width"):
            width = PythonObject(_as_f64(child[PythonObject(Int(1))]))
        elif h == String("clearance"):
            # (clearance <n>) or (clearance <n> (type <t>))
            if _len(child) >= 2:
                var v = PythonObject(_as_f64(child[PythonObject(Int(1))]))
                if _len(child) == 2:
                    clearance = v
                elif _len(child) >= 3 and _is_list(child[PythonObject(Int(2))]):
                    var tlist = child[PythonObject(Int(2))]
                    if _len(tlist) >= 2 and _head_symbol(tlist) == String("type"):
                        by_type[tlist[PythonObject(Int(1))]] = v
    var rec = py.dict()
    rec[PythonObject(String("width"))] = width
    rec[PythonObject(String("clearance"))] = clearance
    rec[PythonObject(String("clearance_by_type"))] = by_type
    return rec


fn parse_dsn_keepout_circles_mm(src: String) raises -> PythonObject:
    """Return keepout circles as a Python list of `(layer, x_mm, y_mm, r_mm)` tuples."""
    var unit_name, div = parse_dsn_resolution(src)
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var structure = _find_first_list_with_head(top, String("structure"))
    var out = py.list()
    var keepouts = _find_all_lists_with_head(structure, String("keepout"))
    for ko in keepouts:
        for child in ko:
            if not _is_list(child) or _len(child) < 1:
                continue
            var h = _head_symbol(child)
            if h == String("circ") and _len(child) >= 5:
                var layer = child[PythonObject(Int(1))]
                var r = _as_f64(child[PythonObject(Int(2))])
                if r < 0.0:
                    r = -r
                var x = _as_f64(child[PythonObject(Int(3))])
                var y = _as_f64(child[PythonObject(Int(4))])
                out.append(
                    py.tuple(
                        layer,
                        PythonObject(dsn_coord_to_mm(x, unit_name, div)),
                        PythonObject(dsn_coord_to_mm(y, unit_name, div)),
                        PythonObject(dsn_coord_to_mm(r, unit_name, div)),
                    )
                )
    return out


fn parse_dsn_keepout_polygons_mm(src: String) raises -> PythonObject:
    """Return keepout polygons as `[(layer, [(x_mm,y_mm)...]), ...]`."""
    var unit_name, div = parse_dsn_resolution(src)
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var structure = _find_first_list_with_head(top, String("structure"))
    var out = py.list()
    var keepouts = _find_all_lists_with_head(structure, String("keepout"))
    for ko in keepouts:
        for child in ko:
            if not _is_list(child) or _len(child) < 1:
                continue
            if _head_symbol(child) != String("polygon") or _len(child) < 5:
                continue
            var layer = child[PythonObject(Int(1))]
            var pts = py.list()
            var i = 3
            while i + 1 < _len(child):
                var x = _as_f64(child[PythonObject(Int(i))])
                var y = _as_f64(child[PythonObject(Int(i + 1))])
                pts.append(
                    py.tuple(
                        PythonObject(dsn_coord_to_mm(x, unit_name, div)),
                        PythonObject(dsn_coord_to_mm(y, unit_name, div)),
                    )
                )
                i += 2
            if Int(py=pts.__len__()) >= 3:
                out.append(py.tuple(layer, pts))
    return out


fn parse_dsn_wiring_summary(src: String) raises -> PythonObject:
    """Return a minimal summary of `(wiring ...)` contents.

    Output schema:
    `{wire_count: int, via_count: int}` where:
    - `wire_count` counts `(wire ...)` entries.
    - `via_count` counts `(via ...)` entries inside wiring.

    This is a stepping stone toward full DSN→IR import for oracle parity.
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var wiring = _find_first_list_with_head(top, String("wiring"))
    var wire_count = 0
    var via_count = 0
    for child in wiring:
        if not _is_list(child) or _len(child) < 1:
            continue
        var h = _head_symbol(child)
        if h == String("wire"):
            wire_count += 1
        elif h == String("via"):
            via_count += 1
    var rec = py.dict()
    rec[PythonObject(String("wire_count"))] = PythonObject(Int(wire_count))
    rec[PythonObject(String("via_count"))] = PythonObject(Int(via_count))
    return rec


fn parse_dsn_wiring(src: String) raises -> PythonObject:
    """Parse `(wiring ...)` into typed wire/via records (Python dict).

    Output schema:
    ```
    {
      "wires": [{"layer": str, "width": float, "points": [(x,y)...], "net": str, "type": str|None}, ...],
      "vias": [{"via": str, "x": float, "y": float, "net": str|None, "type": str|None}, ...],
    }
    ```
    All numeric values are returned as Python floats in DSN units (no normalization yet).
    """
    var xs = parse_sexpr(src)
    if _len(xs) != 1:
        raise Error("dsn: expected 1 top-level form, got " + String(_len(xs)))
    var top = xs[PythonObject(Int(0))]
    var wiring = _find_first_list_with_head(top, String("wiring"))
    var wires = py.list()
    var vias = py.list()

    for child in wiring:
        if not _is_list(child) or _len(child) < 1:
            continue
        var h = _head_symbol(child)
        if h == String("wire"):
            var layer = py.none()
            var width = py.none()
            var points = py.list()
            var net = py.none()
            var wtype = py.none()
            for w in child:
                if not _is_list(w) or _len(w) < 2:
                    continue
                var wh = _head_symbol(w)
                if wh == String("path"):
                    # (path LAYER WIDTH x y x y ...)
                    if _len(w) >= 4:
                        layer = w[PythonObject(Int(1))]
                        width = PythonObject(_as_f64(w[PythonObject(Int(2))]))
                        var i = 3
                        while i + 1 < _len(w):
                            points.append(py.tuple(PythonObject(_as_f64(w[PythonObject(Int(i))])), PythonObject(_as_f64(w[PythonObject(Int(i + 1))]))))
                            i += 2
                elif wh == String("net"):
                    net = w[PythonObject(Int(1))]
                elif wh == String("type"):
                    wtype = w[PythonObject(Int(1))]
            var rec = py.dict()
            rec[PythonObject(String("layer"))] = layer
            rec[PythonObject(String("width"))] = width
            rec[PythonObject(String("points"))] = points
            rec[PythonObject(String("net"))] = net
            rec[PythonObject(String("type"))] = wtype
            wires.append(rec)
        elif h == String("via"):
            # (via "<via_name>" x y (net <n>) (type route))
            if _len(child) < 4:
                continue
            var vname = child[PythonObject(Int(1))]
            var x = PythonObject(_as_f64(child[PythonObject(Int(2))]))
            var y = PythonObject(_as_f64(child[PythonObject(Int(3))]))
            var net = py.none()
            var vtype = py.none()
            var i = 4
            while i < _len(child):
                var w = child[PythonObject(Int(i))]
                if _is_list(w) and _len(w) >= 2:
                    var wh = _head_symbol(w)
                    if wh == String("net"):
                        net = w[PythonObject(Int(1))]
                    elif wh == String("type"):
                        vtype = w[PythonObject(Int(1))]
                i += 1
            var rec = py.dict()
            rec[PythonObject(String("via"))] = vname
            rec[PythonObject(String("x"))] = x
            rec[PythonObject(String("y"))] = y
            rec[PythonObject(String("net"))] = net
            rec[PythonObject(String("type"))] = vtype
            vias.append(rec)

    var out = py.dict()
    out[PythonObject(String("wires"))] = wires
    out[PythonObject(String("vias"))] = vias
    return out
