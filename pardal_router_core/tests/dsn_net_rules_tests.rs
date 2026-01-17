use std::path::PathBuf;

use pardal_router_core::dsn::{extract_net_rules_from_str, tokenize, Token};

fn ee_root() -> PathBuf {
    // pardal-pcb/pardal_router_core/tests -> pardal-pcb -> ee root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("expected pardal-pcb/pardal_router_core structure")
        .to_path_buf()
}

#[test]
fn parse_issue313_class_rule_has_width_and_clearance() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue313-FastTest.dsn"))
        .expect("read Issue313-FastTest.dsn");
    let rules = extract_net_rules_from_str(&dsn).expect("extract rules");

    let cls = rules.classes.get("R6_2").expect("R6_2 class");
    assert!(cls.rule.width.is_some());
    assert!(cls.rule.clearance.is_some());
    assert!(cls.use_via.is_some());
}

#[test]
fn parse_issue103_kicad_default_class_contains_known_net_and_width() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue103-Board-Routed.dsn"))
        .expect("read Issue103-Board-Routed.dsn");
    let rules = extract_net_rules_from_str(&dsn).expect("extract rules");

    let cls = rules.classes.get("kicad_default").expect("kicad_default class");
    assert!(cls.nets.iter().any(|n| n == "/pcIU16"));
    assert_eq!(cls.rule.width, Some(250.0));
    assert!(cls.use_layers.iter().any(|l| l == "F.Cu"));
    assert!(cls.use_layers.iter().any(|l| l == "B.Cu"));

    assert_eq!(rules.net_to_class.get("/pcIU16").map(|s| s.as_str()), Some("kicad_default"));
}

#[test]
fn parse_issue143_structure_typed_clearances_are_extracted() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue143-rpi_splitter.dsn"))
        .expect("read Issue143-rpi_splitter.dsn");
    let rules = extract_net_rules_from_str(&dsn).expect("extract rules");

    assert!(rules.typed_clearances.contains_key("default_boundary"));
    assert!(rules.typed_clearances.contains_key("wire_via"));
    assert!(rules.typed_clearances.contains_key("pin_pin"));
    assert!(rules.typed_clearances.contains_key("smd_smd"));
    assert!(rules.default_rule.clearance.is_some());
}

#[test]
fn parse_structure_typed_clearances_are_canonicalized() {
    let dsn = r#"
(pcb demo
  (resolution mil 2540)
  (unit mil)
  (structure
    (layer "1#Top" (type signal))
    (boundary (rect pcb 0 0 10 10))
    (rule (clearance 10 (type area_wire)))
    (rule (clearance 11 (type area_via)))
    (rule (clearance 12 (type via_wire)))
  )
)
"#;
    let rules = extract_net_rules_from_str(dsn).expect("extract rules");
    assert_eq!(rules.typed_clearances.get("wire_area").copied(), Some(10.0));
    assert_eq!(rules.typed_clearances.get("via_area").copied(), Some(11.0));
    assert_eq!(rules.typed_clearances.get("wire_via").copied(), Some(12.0));
}

#[test]
fn tokenize_supports_quoted_dash_quoted_sequences() {
    let input = r#"(rule (clear 1 (type "default"-"1A EXTERNAL 1oz")))"#;
    let tokens = tokenize(input).expect("tokenize");
    let mut found = false;
    for w in tokens.windows(3) {
        if w[0] == Token::Str("default".to_string())
            && w[1] == Token::Atom("-".to_string())
            && w[2] == Token::Str("1A EXTERNAL 1oz".to_string())
        {
            found = true;
            break;
        }
    }
    assert!(found, "expected Str(\"default\"), Atom(\"-\"), Str(\"1A EXTERNAL 1oz\") token sequence");
}
