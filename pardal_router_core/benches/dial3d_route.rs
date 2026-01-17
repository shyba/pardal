use criterion::{black_box, criterion_group, criterion_main, Criterion};

use pardal_router_core::ir::RoutingIr;
use pardal_router_core::router::{route_dial_3d_for_net, Point3};

pub fn bench_dial3d_route_open_grid(c: &mut Criterion) {
    // Medium-sized synthetic grid to track single-net routing speed.
    let mut ir = RoutingIr::new(4, 96, 96);
    let blocked_value = 1u32;
    let n2 = ir.width * ir.height;
    let cost = vec![0u16; ir.layers * n2];

    // Block a border so the router doesn't wander outside intended area if later rules change.
    for layer in 0..ir.layers {
        for x in 0..ir.width {
            ir.set_occ(layer, x, 0, blocked_value);
            ir.set_occ(layer, x, ir.height - 1, blocked_value);
        }
        for y in 0..ir.height {
            ir.set_occ(layer, 0, y, blocked_value);
            ir.set_occ(layer, ir.width - 1, y, blocked_value);
        }
    }

    let start = Point3 { layer: 0, x: 1, y: 1 };
    let goal = Point3 {
        layer: 0,
        x: ir.width - 2,
        y: ir.height - 2,
    };

    c.bench_function("dial3d/route_open_96x96x4", |b| {
        b.iter(|| {
            let p = route_dial_3d_for_net(&ir, start, goal, blocked_value, &cost, 5, 42);
            black_box(p);
        })
    });
}

criterion_group!(benches, bench_dial3d_route_open_grid);
criterion_main!(benches);

