use pardal_router_core::parity_metrics::parse_freerouting_metrics_json_str;

#[test]
fn parses_freerouting_boardstatistics_minimal() {
    let s = r#"
{
  "layers": { "total_count": 4 },
  "connections": { "incomplete_count": 12 },
  "clearance_violations": { "total_count": 3 }
}
"#;
    let m = parse_freerouting_metrics_json_str(s).expect("parse");
    assert_eq!(m.layers_total, Some(4));
    assert_eq!(m.connections_incomplete, Some(12));
    assert_eq!(m.clearance_violations_total, Some(3));
    assert_eq!(m.unconnected_items_total, None);
}

#[test]
fn parses_freerouting_drc_minimal() {
    let s = r#"
{
  "unconnected_items": [{}, {}, {}],
  "clearance_violations": [{}]
}
"#;
    let m = parse_freerouting_metrics_json_str(s).expect("parse");
    assert_eq!(m.unconnected_items_total, Some(3));
    assert_eq!(m.clearance_violations_total, Some(1));
    assert_eq!(m.connections_incomplete, None);
}

#[test]
fn parses_freerouting_drc_kicad_schema() {
    let s = r#"
{
  "$schema": "https://schemas.kicad.org/drc.v1.json",
  "unconnected_items": [{}, {}],
  "violations": [
    { "type": "clearance" },
    { "type": "clearance" },
    { "type": "something_else" }
  ]
}
"#;
    let m = parse_freerouting_metrics_json_str(s).expect("parse");
    assert_eq!(m.unconnected_items_total, Some(2));
    assert_eq!(m.clearance_violations_total, Some(2));
    assert_eq!(m.connections_incomplete, None);
}
