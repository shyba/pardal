use std::path::PathBuf;

use criterion::{black_box, criterion_group, criterion_main, BatchSize, Criterion};

use pardal_router_core::dsn::{extract_model_from_str, summarize_dsn};
use pardal_router_core::dsn_to_ir::{build_empty_ir_from_summary, stamp_pins_as_circular_keepouts};

fn ee_root() -> PathBuf {
    // pardal-pcb/pardal_router_core -> pardal-pcb -> ee root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("expected pardal-pcb/pardal_router_core structure")
        .to_path_buf()
}

pub fn bench_issue313_stamp_pins(c: &mut Criterion) {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue313-FastTest.dsn"))
        .expect("read Issue313-FastTest.dsn");
    let summary = summarize_dsn(&dsn).expect("summarize");
    let model = extract_model_from_str(&dsn).expect("extract model");

    let vcc = model.nets.get("VCC").expect("VCC net");
    let allow = [vcc.pins[0].as_str(), vcc.pins[1].as_str()];

    let pitch = 2.0;
    let (ir0, tx) = build_empty_ir_from_summary(&summary, pitch).expect("build ir");

    c.bench_function("dsn_to_ir/stamp_pins_issue313", |b| {
        b.iter_batched(
            || ir0.clone(),
            |mut ir| {
                stamp_pins_as_circular_keepouts(&mut ir, tx, &model, 0, 1, &allow);
                black_box(ir);
            },
            BatchSize::SmallInput,
        )
    });
}

criterion_group!(benches, bench_issue313_stamp_pins);
criterion_main!(benches);

