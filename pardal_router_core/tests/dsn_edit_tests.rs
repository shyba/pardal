use pardal_router_core::dsn::edit::append_wiring_exprs;
use pardal_router_core::dsn::tokenize;

#[test]
fn append_wiring_inserts_into_existing_wiring_block() {
    let dsn = r#"
(pcb demo
  (structure (layer F.Cu) (boundary (rect pcb 0 0 10 10)))
  (network (net N1 (pins)))
  (wiring
    (wire (path F.Cu 1.0  0 0  5 0) (net N1))
  )
)
"#;
    let out = append_wiring_exprs(
        dsn,
        &[String::from("(via via0 5 0 (net N1))")],
    )
    .expect("append");

    assert!(out.contains("(wiring"));
    assert!(out.contains("(wire (path F.Cu"));
    assert!(out.contains("(via via0 5 0 (net N1))"));

    // Ensure the output is still valid tokenizable DSN.
    tokenize(&out).expect("tokenize output");
}

#[test]
fn append_wiring_creates_wiring_block_when_missing() {
    let dsn = r#"
(pcb demo
  (structure (layer F.Cu) (boundary (rect pcb 0 0 10 10)))
  (network (net N1 (pins)))
)
"#;
    let out = append_wiring_exprs(
        dsn,
        &[String::from("(via via0 1 2 (net N1))")],
    )
    .expect("append");

    assert!(out.contains("(wiring"));
    assert!(out.contains("(via via0 1 2 (net N1))"));
    tokenize(&out).expect("tokenize output");
}

