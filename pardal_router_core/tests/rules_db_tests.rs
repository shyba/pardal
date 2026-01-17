use pardal_router_core::dsn::extract_net_rules_from_str;
use pardal_router_core::dsn::extract_rules_clearances_from_str;
use pardal_router_core::rules::RulesDb;

#[test]
fn rules_db_brush_radius_uses_width_plus_clearance() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (rule (width 1.0))
    (rule (clear 0.2))
    (boundary (polygon signal 0  0 0  10 0  10 10  0 10  0 0))
  )
  (network
    (net N1 (pins))
    (net N2 (pins))
    (class fast N2
      (circuit (use_layer F.Cu))
      (rule (width 2.0) (clearance 0.5))
    )
  )
)
"#;
    let nr = extract_net_rules_from_str(dsn).expect("net rules");
    let rules = RulesDb::from_dsn_net_rules(nr);

    // pitch=1: (1.0/2 + 0.2) => 0.7 => ceil => 1
    assert_eq!(rules.brush_radius_cells_for_net("N1", 1.0), 1);
    // pitch=1: (2.0/2 + 0.5) => 1.5 => ceil => 2
    assert_eq!(rules.brush_radius_cells_for_net("N2", 1.0), 2);
}

#[test]
fn rules_db_via_padstack_prefers_class_via_rule_mapping() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (layer B.Cu)
    (boundary (polygon signal 0  0 0  10 0  10 10  0 10  0 0))
  )
  (network
    (via_rule default via0)
    (via_rule fast via_fast)
    (net N1 (pins))
    (class default N1 (via_rule default))
    (net N2 (pins))
    (class fast N2 (via_rule fast))
  )
)
"#;
    let nr = extract_net_rules_from_str(dsn).expect("net rules");
    let rules = RulesDb::from_dsn_net_rules(nr);

    assert_eq!(rules.via_padstack_for_net("N1").as_deref(), Some("via0"));
    assert_eq!(rules.via_padstack_for_net("N2").as_deref(), Some("via_fast"));
}

#[test]
fn rules_db_merges_optional_rules_clearances() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (rule (width 1.0))
    (rule (clear 0.2))
    (rule (clear 0.5 (type default_smd)))
    (boundary (polygon signal 0  0 0  10 0  10 10  0 10  0 0))
  )
  (network
    (net N1 (pins))
  )
)
"#;
    let nr = extract_net_rules_from_str(dsn).expect("net rules");

    let rules_txt = r#"
(rules
  (rule (clearance 0.3))
  (rule (clearance 0.6 (type default_smd)))
  (rule (clearance 0.9 (type high - low)))
)
"#;
    let rc = extract_rules_clearances_from_str(rules_txt).expect("rules clearances");
    let rules = RulesDb::from_dsn_net_rules_and_rules_clearances(nr, rc);

    // Default clearance should be the max across DSN net rules and external rules.
    assert_eq!(rules.default_clearance_world(), Some(0.3));

    // Typed clearances are merged by max.
    let typed = rules.typed_clearances_world();
    assert_eq!(typed.get("default_smd").copied(), Some(0.6));

    // Pairwise matrix is available (and order-insensitive).
    assert_eq!(rules.clearance_matrix_world_for_classes("high", "low"), Some(0.9));
    assert_eq!(rules.clearance_matrix_world_for_classes("low", "high"), Some(0.9));
}
