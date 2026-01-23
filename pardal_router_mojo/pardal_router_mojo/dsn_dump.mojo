from python import Python, PythonObject

from pardal_router_mojo.dsn import (
    parse_dsn_boundary_bbox_mm,
    parse_dsn_class_members,
    parse_dsn_class_rules,
    parse_dsn_library_pins,
    parse_dsn_placement,
    parse_dsn_layers,
    parse_dsn_net_names,
    parse_dsn_net_pins,
    parse_dsn_padstacks,
    parse_dsn_pcb_name,
    parse_dsn_pin_positions_mm,
    parse_dsn_resolution,
    parse_dsn_structure_rules,
    parse_dsn_via_catalog_mm,
    parse_dsn_via_defs,
    parse_dsn_wiring,
    parse_dsn_wiring_mm,
    parse_dsn_wiring_summary,
    parse_dsn_wiring_vias_mm,
)

comptime py = Python


fn dsn_dump(in_path: String, out_path: String) raises:
    """Parse a DSN file and write a JSON dump for parity debugging."""
    var pathlib = py.import_module("pathlib")
    var json = py.import_module("json")
    var src = String(py=pathlib.Path(PythonObject(in_path)).read_text(encoding=PythonObject(String("utf-8")), errors=PythonObject(String("replace"))))

    var unit_name, div = parse_dsn_resolution(src)

    var payload = py.dict()
    payload[PythonObject(String("pcb_name"))] = PythonObject(parse_dsn_pcb_name(src))
    payload[PythonObject(String("resolution"))] = py.dict(
        unit=PythonObject(unit_name),
        div=PythonObject(div),
    )

    payload[PythonObject(String("layers"))] = parse_dsn_layers(src)
    payload[PythonObject(String("structure_rules"))] = parse_dsn_structure_rules(src)
    payload[PythonObject(String("boundary_bbox_mm"))] = parse_dsn_boundary_bbox_mm(src)

    payload[PythonObject(String("nets"))] = parse_dsn_net_names(src)
    payload[PythonObject(String("net_pins"))] = parse_dsn_net_pins(src)
    payload[PythonObject(String("classes"))] = parse_dsn_class_members(src)
    payload[PythonObject(String("class_rules"))] = parse_dsn_class_rules(src)

    payload[PythonObject(String("padstacks"))] = parse_dsn_padstacks(src)
    payload[PythonObject(String("via_defs"))] = parse_dsn_via_defs(src)
    payload[PythonObject(String("via_catalog_mm"))] = parse_dsn_via_catalog_mm(src)

    payload[PythonObject(String("placement"))] = parse_dsn_placement(src)
    payload[PythonObject(String("library_pins"))] = parse_dsn_library_pins(src)

    payload[PythonObject(String("pin_positions_mm"))] = parse_dsn_pin_positions_mm(src)

    payload[PythonObject(String("wiring_summary"))] = parse_dsn_wiring_summary(src)
    payload[PythonObject(String("wiring"))] = parse_dsn_wiring(src)
    payload[PythonObject(String("wiring_mm"))] = parse_dsn_wiring_mm(src)
    payload[PythonObject(String("wiring_vias_mm"))] = parse_dsn_wiring_vias_mm(src)

    var txt = json.dumps(payload, indent=PythonObject(Int(2)), sort_keys=PythonObject(True))
    pathlib.Path(PythonObject(out_path)).write_text(txt, encoding=PythonObject(String("utf-8")))


fn dsn_ir(in_path: String, out_path: String) raises:
    """Emit a minimal mm-normalized routing IR JSON from a DSN file.

    This is a stepping stone toward DSN→IR→router parity, not a complete Specctra import.
    """
    var pathlib = py.import_module("pathlib")
    var json = py.import_module("json")
    var src = String(
        py=pathlib.Path(PythonObject(in_path)).read_text(
            encoding=PythonObject(String("utf-8")), errors=PythonObject(String("replace"))
        )
    )

    var payload = py.dict()
    payload[PythonObject(String("pcb_name"))] = PythonObject(parse_dsn_pcb_name(src))
    payload[PythonObject(String("boundary_bbox_mm"))] = parse_dsn_boundary_bbox_mm(src)
    payload[PythonObject(String("pin_positions_mm"))] = parse_dsn_pin_positions_mm(src)
    payload[PythonObject(String("via_catalog_mm"))] = parse_dsn_via_catalog_mm(src)
    payload[PythonObject(String("wiring_mm"))] = parse_dsn_wiring_mm(src)
    payload[PythonObject(String("wiring_vias_mm"))] = parse_dsn_wiring_vias_mm(src)

    var txt = json.dumps(payload, indent=PythonObject(Int(2)), sort_keys=PythonObject(True))
    pathlib.Path(PythonObject(out_path)).write_text(txt, encoding=PythonObject(String("utf-8")))
