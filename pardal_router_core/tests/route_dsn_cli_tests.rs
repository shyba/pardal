use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn tmp_file(name: &str) -> PathBuf {
    let mut p = std::env::temp_dir();
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    p.push(format!("pardal_route_dsn_test_{name}_{ts}_{}", std::process::id()));
    p
}

fn write_tmp_dsn(name: &str, contents: &str) -> PathBuf {
    let p = tmp_file(name);
    std::fs::write(&p, contents).expect("write tmp dsn");
    p
}

#[test]
fn cli_respects_inactive_layer_rules() {
    // Two-layer board; pins exist only on B.Cu so the router must use B.Cu.
    // When B.Cu is inactive, routing must fail. When B.Cu is active, routing must succeed.
    let dsn_inactive = r#"
(pcb demo
  (resolution mm 1)
  (unit mm)
  (structure
    (layer F.Cu)
    (layer B.Cu)
    (boundary (polygon signal 0  0 0  10 0  10 10  0 10  0 0))
    (autoroute_settings
      (layer_rule F.Cu (active off))
      (layer_rule B.Cu (active off))
    )
  )
  (library
    (image U
      (pin ppad 1 1 1)
      (pin ppad 2 9 9)
    )
  )
  (placement (component U (place U1 0 0 front 0)))
  (padstack ppad (shape (rect B.Cu -0.2 -0.2 0.2 0.2)))
  (network
    (net N1 (pins U1-1 U1-2))
  )
)
"#;
    let dsn_active = dsn_inactive.replace("(layer_rule B.Cu (active off))", "(layer_rule B.Cu (active on))");

    let p_inactive = write_tmp_dsn("inactive", &dsn_inactive);
    let p_active = write_tmp_dsn("active", &dsn_active);

    let bin = env!("CARGO_BIN_EXE_pardal_route_dsn");

    let st = Command::new(bin)
        .arg(&p_inactive)
        .arg("FIRST")
        .arg("auto")
        .arg("0")
        .arg("10")
        .arg("0")
        .arg("none")
        .arg("off")
        .status()
        .expect("run pardal_route_dsn (inactive)");
    assert_eq!(st.code(), Some(3), "expected routing to fail when B.Cu is inactive");

    let out = Command::new(bin)
        .arg(&p_active)
        .arg("FIRST")
        .arg("auto")
        .arg("0")
        .arg("10")
        .arg("0")
        .arg("none")
        .arg("off")
        .output()
        .expect("run pardal_route_dsn (active)");
    assert!(out.status.success(), "expected routing to succeed when B.Cu is active");
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("path_points:"), "expected success output to include path_points");

    let _ = std::fs::remove_file(p_inactive);
    let _ = std::fs::remove_file(p_active);
}

#[test]
fn cli_allmst_expands_multi_pin_net() {
    // One net with three pins; ALLMST should emit 2 requests (MST edges).
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (unit mm)
  (structure
    (layer F.Cu)
    (boundary (polygon signal 0  0 0  20 0  20 20  0 20  0 0))
  )
  (library
    (image U
      (pin ppad 1 2 2)
      (pin ppad 2 18 2)
      (pin ppad 3 10 18)
    )
  )
  (placement (component U (place U1 0 0 front 0)))
  (padstack ppad (shape (rect F.Cu -0.5 -0.5 0.5 0.5)))
  (network
    (net N1 (pins U1-1 U1-2 U1-3))
  )
)
"#;
    let p = write_tmp_dsn("allmst", dsn);

    let bin = env!("CARGO_BIN_EXE_pardal_route_dsn");
    let out = Command::new(bin)
        .arg(&p)
        .arg("ALLMST")
        .arg("auto")
        .arg("0")
        // net_limit=1 => choose 1 net, then expand to MST edges
        .arg("1")
        .arg("0")
        .arg("none")
        .arg("off")
        .output()
        .expect("run pardal_route_dsn (ALLMST)");
    assert!(out.status.success(), "expected ALLMST routing to succeed on open board");
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("mode: ALL"), "expected ALL* modes to print mode: ALL");
    assert!(stdout.contains("requested: 2"), "expected 3-pin net to expand to 2 MST edge requests");

    let _ = std::fs::remove_file(p);
}

#[test]
fn cli_endpoint_escape_env_var_smoke() {
    // Smoke: exercise the endpoint escape code path on a tiny DSN.
    let dsn = r#"
(pcb demo
  (resolution mil 2540)
  (unit mil)
  (structure
    (layer 1 (type signal))
    (boundary (polygon signal 0  0 0  100 0  100 50  0 50  0 0))
    (via via0)
    (rule (width 4)(clearance 4))
  )
  (placement
    (component u1 (place u1 0 0 front 0))
    (component j1 (place j1 0 0 front 0))
  )
  (library
    (image u1 (pin p 1 10 25))
    (image j1 (pin p 1 90 25))
    (padstack p (shape (circle 1 18 0 0)))
    (padstack via0 (shape (circle 1 10)))
  )
  (network (net N1 (pins u1-1 j1-1)))
)
"#;
    let p = write_tmp_dsn("endpoint_escape", dsn);
    let out_dsn = tmp_file("endpoint_escape_out");

    let bin = env!("CARGO_BIN_EXE_pardal_route_dsn");
    let out = Command::new(bin)
        .env("PARDAL_ENDPOINT_ESCAPE", "1")
        .env("PARDAL_ROUTE_DSN_OUT", &out_dsn)
        .arg(&p)
        .arg("ALL")
        .arg("2")
        .arg("1")
        .arg("10")
        .arg("auto")
        .arg("none")
        .arg("off")
        .output()
        .expect("run pardal_route_dsn (endpoint escape)");
    assert!(
        out.status.success(),
        "stdout={:?} stderr={:?}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );

    let _ = std::fs::remove_file(p);
    let _ = std::fs::remove_file(out_dsn);
}
