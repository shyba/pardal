use std::process::Command;

use pardal_router_core::parity_metrics::parse_freerouting_metrics_json_str;

fn ee_root() -> std::path::PathBuf {
    // Run from `pardal-pcb/pardal_router_core`.
    std::env::current_dir().expect("cwd")
}

#[test]
#[ignore]
fn freerouting_oracle_produces_valid_json_for_smoke_corpus() {
    // This test requires Docker and may take a while on first run (it builds the oracle image).
    let ee_root = ee_root();
    let corpus = [
        "freerouting/tests/Issue313-FastTest.dsn",
        "freerouting/tests/Issue270-non-ansi_bracket.dsn",
        "freerouting/tests/Issue103-Board-Routed.dsn",
        "freerouting/tests/Issue209-split05.dsn",
        "freerouting/tests/empty_board.dsn",
    ];

    let tmp = std::env::temp_dir().join(format!(
        "pardal_oracle_test_{}_{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis()
    ));
    std::fs::create_dir_all(&tmp).expect("create tmp");

    let tool = ee_root.join("pardal-pcb/pardal_router_core/tools/freerouting_oracle.sh");
    assert!(tool.exists(), "missing oracle script: {}", tool.display());

    for rel in corpus {
        let dsn = ee_root.join(rel);
        assert!(dsn.exists(), "missing fixture: {}", dsn.display());
        let base_noext = dsn
            .file_name()
            .expect("file name")
            .to_string_lossy()
            .to_string()
            .trim_end_matches(".dsn")
            .to_string();

        let out = Command::new("bash")
            .arg(&tool)
            .arg(&dsn)
            .arg(&tmp)
            .arg("0xDEADBEEF")
            .arg("1") // max passes
            .arg("1") // threads
            .output()
            .expect("run oracle");
        assert!(
            out.status.success(),
            "oracle failed for {rel}:\nstdout:\n{}\nstderr:\n{}",
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        );

        let stats_path = tmp.join(format!("{base_noext}.oracle.stats.json"));
        assert!(stats_path.exists(), "missing stats: {}", stats_path.display());
        let stats = std::fs::read_to_string(&stats_path).expect("read stats");

        let v: serde_json::Value = serde_json::from_str(&stats).expect("parse json");
        assert!(v.is_object(), "expected top-level object, got: {v:?}");

        let m = parse_freerouting_metrics_json_str(&stats).expect("normalized metrics");
        assert!(
            m.layers_total.is_some(),
            "expected layers_total for {rel}, got: {m:?}"
        );
        assert!(
            m.connections_incomplete.is_some(),
            "expected connections_incomplete for {rel}, got: {m:?}"
        );
        assert!(
            m.clearance_violations_total.is_some(),
            "expected clearance_violations_total for {rel}, got: {m:?}"
        );
    }
}
