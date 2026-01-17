use pardal_router_core::dsn::extract_boundary_polygons_from_str;

#[test]
fn extract_boundary_polygons_supports_multiple_boundaries() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (boundary (rect pcb 0 0 10 10))
    (boundary (rect pcb 3 3 7 7))
  )
)
"#;

    let polys = extract_boundary_polygons_from_str(dsn).expect("polys");
    assert_eq!(polys.len(), 2);
    assert!(polys.iter().all(|p| p.len() == 4));
}

#[test]
fn extract_boundary_polygons_parses_boundary_path() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (boundary (path pcb 0.2  0 0  10 0  10 10  0 10  0 0))
  )
)
"#;

    let polys = extract_boundary_polygons_from_str(dsn).expect("polys");
    assert_eq!(polys.len(), 1);
    assert!(polys[0].len() >= 4);
    assert_eq!(polys[0][0], (0.0, 0.0));
    assert_eq!(polys[0][1], (10.0, 0.0));
}

#[test]
fn extract_boundary_polygons_is_case_insensitive() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (boundary (PATH pcb 0.2  0 0  10 0  10 10  0 10  0 0))
  )
)
"#;

    let polys = extract_boundary_polygons_from_str(dsn).expect("polys");
    assert_eq!(polys.len(), 1);
    assert!(polys[0].len() >= 4);
}
