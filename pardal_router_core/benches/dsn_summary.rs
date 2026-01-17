use std::path::PathBuf;

use criterion::{criterion_group, criterion_main, Criterion};
use pardal_router_core::dsn::summarize_dsn;

fn ee_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("expected pardal-pcb/pardal_router_core structure")
        .to_path_buf()
}

fn bench_dsn_summaries(c: &mut Criterion) {
    let empty = std::fs::read_to_string(ee_root().join("freerouting/tests/empty_board.dsn"))
        .expect("read empty_board.dsn");
    let fast = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue313-FastTest.dsn"))
        .expect("read Issue313-FastTest.dsn");

    c.bench_function("dsn_summary/empty_board", |b| {
        b.iter(|| summarize_dsn(&empty).unwrap())
    });
    c.bench_function("dsn_summary/issue313_fasttest", |b| {
        b.iter(|| summarize_dsn(&fast).unwrap())
    });
}

criterion_group!(benches, bench_dsn_summaries);
criterion_main!(benches);

