use std::path::PathBuf;

use pardal_router_core::dsn::extract_autoroute_settings_from_str;

fn ee_root() -> PathBuf {
    // pardal-pcb/pardal_router_core/tests -> pardal-pcb -> ee root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("expected pardal-pcb/pardal_router_core structure")
        .to_path_buf()
}

#[test]
fn parse_minimal_autoroute_settings_and_layer_rules() {
    let dsn = r#"
(pcb demo
  (structure
    (layer F.Cu)
    (layer B.Cu)
    (autoroute_settings
      (fanout on)
      (eu.mihosoft.freerouting.autoroute off)
      (postroute off)
      (vias on)
      (via_costs 50)
      (plane_via_costs 5)
      (start_ripup_costs 100)
      (start_pass_no 25)
      (layer_rule F.Cu
        (active on)
        (preferred_direction horizontal)
        (preferred_direction_trace_costs 1.0)
        (against_preferred_direction_trace_costs 2.1)
      )
      (layer_rule B.Cu
        (active off)
        (preferred_direction vertical)
      )
    )
  )
)
"#;
    let s = extract_autoroute_settings_from_str(dsn)
        .expect("extract autoroute_settings")
        .expect("settings present");
    assert_eq!(s.fanout, Some(true));
    assert_eq!(s.router_enabled, Some(false));
    assert_eq!(s.postroute, Some(false));
    assert_eq!(s.vias, Some(true));
    assert_eq!(s.via_costs, Some(50));
    assert_eq!(s.plane_via_costs, Some(5));
    assert_eq!(s.start_ripup_costs, Some(100));
    assert_eq!(s.start_pass_no, Some(25));

    let f = s.layers.get("F.Cu").expect("F.Cu rule");
    assert_eq!(f.active, Some(true));
    assert_eq!(f.preferred_direction.as_deref(), Some("horizontal"));
    assert_eq!(f.preferred_direction_trace_costs, Some(1.0));
    assert_eq!(f.against_preferred_direction_trace_costs, Some(2.1));

    let b = s.layers.get("B.Cu").expect("B.Cu rule");
    assert_eq!(b.active, Some(false));
    assert_eq!(b.preferred_direction.as_deref(), Some("vertical"));
}

#[test]
fn parse_issue103_autoroute_settings_smoke() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue103-Board-Routed.dsn"))
        .expect("read Issue103-Board-Routed.dsn");
    let s = extract_autoroute_settings_from_str(&dsn)
        .expect("extract autoroute_settings")
        .expect("settings present");
    assert!(s.via_costs.is_some());
    assert!(s.layers.contains_key("F.Cu"));
    assert!(s.layers.contains_key("B.Cu"));
}

