use pardal_router_core::clearance_nm::ClearanceResolverNm;
use pardal_router_core::drc_nm::ClearanceKind;
use pardal_router_core::dsn::{
    extract_model_from_str, extract_net_rules_from_str, extract_rules_clearances_from_str,
    extract_wiring_from_str, summarize_dsn,
};
use pardal_router_core::dsn_to_nm::dsn_to_board_nm_with_net_rules;
use pardal_router_core::geom_nm::Nm;

#[test]
fn clearance_resolver_combines_net_typed_and_matrix_rules() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (layer B.Cu)
    (boundary (rect pcb 0 0 20 20))
    (rule
      (width 0.2)
      (clearance 0.05)
      (clearance 0.3 (type wire_via))
    )
  )
  (padstack via0
    (shape (circle F.Cu 0.6))
    (shape (circle B.Cu 0.6))
  )
  (network
    (net N1 (pins))
    (net N2 (pins))
    (class default N1
      (clearance_class default)
      (rule (clearance 0.1))
      (circuit (use_layer F.Cu B.Cu))
    )
    (class class1 N2
      (clearance_class class1)
      (rule (clearance 0.2))
      (circuit (use_layer F.Cu B.Cu))
    )
  )
  (wiring
    (wire (path F.Cu 0.2  0 0  10 0) (net N1))
    (via via0 5 0 (net N2))
  )
)
"#;

    let rules_txt = r#"
(rules PCB demo
  (rule
    (clear 0.5 (type "default"-"class1"))
  )
)
"#;

    let summary = summarize_dsn(dsn).expect("summarize");
    let model = extract_model_from_str(dsn).expect("model");
    let wiring = extract_wiring_from_str(dsn).expect("wiring");
    let net_rules = extract_net_rules_from_str(dsn).expect("net rules");
    let rules = extract_rules_clearances_from_str(rules_txt).expect("rules clearances");

    let board = dsn_to_board_nm_with_net_rules(&summary, &model, &wiring, Some(&net_rules)).expect("board");

    let resolver = ClearanceResolverNm::from_dsn_and_optional_rules(&summary, &board, &net_rules, Some(&rules))
        .expect("resolver");

    let net1 = *board.net_name_to_id.get("N1").expect("N1 id");
    let net2 = *board.net_name_to_id.get("N2").expect("N2 id");
    let class_default = 0u32;
    let class1 = board
        .clearance_class_id_to_name
        .iter()
        .position(|s| s == "class1")
        .map(|i| i as u32)
        .expect("class1 id");

    // Expect max(net_clear(max=0.2), typed wire_via=0.3, matrix default-class1=0.5) = 0.5 mm.
    let c = resolver.clearance_for(
        ClearanceKind::Wire,
        net1,
        class_default,
        ClearanceKind::Via,
        net2,
        class1,
        &board,
    );
    assert_eq!(c, Nm(500_000));
    assert_eq!(resolver.max_clearance(), Nm(500_000));
}
