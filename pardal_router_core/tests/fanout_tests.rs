use pardal_router_core::autoroute::pad_boundary_escape_points;
use pardal_router_core::ir::RoutingIr;
use pardal_router_core::router::Point3;

#[test]
fn pad_boundary_escape_points_finds_free_neighbors() {
    let mut ir = RoutingIr::new(1, 5, 5);
    let net_id = 2u32;
    let layer = 0usize;

    // 3x3 pad region in the center (owned by net_id).
    for y in 1..=3 {
        for x in 1..=3 {
            ir.set_pad_owner(layer, x, y, net_id);
        }
    }

    let start = Point3 { layer, x: 2, y: 2 };
    let got = pad_boundary_escape_points(&ir, start, net_id, 64);

    // All 4-neighbors around the 3x3 pad block.
    let expected = vec![
        (0, 1),
        (0, 2),
        (0, 3),
        (1, 0),
        (2, 0),
        (3, 0),
        (4, 1),
        (4, 2),
        (4, 3),
        (1, 4),
        (2, 4),
        (3, 4),
    ];
    let got_xy: Vec<(usize, usize)> = got.iter().map(|p| (p.x, p.y)).collect();
    for (x, y) in expected {
        assert!(got_xy.contains(&(x, y)), "missing candidate ({x},{y})");
    }
}

#[test]
fn pad_boundary_escape_points_skips_other_net_occupied_cells() {
    let mut ir = RoutingIr::new(1, 5, 5);
    let net_id = 2u32;
    let other = 7u32;
    let layer = 0usize;
    for y in 1..=3 {
        for x in 1..=3 {
            ir.set_pad_owner(layer, x, y, net_id);
        }
    }

    // Occupy one would-be escape point.
    ir.set_occ(layer, 0, 2, other);

    let start = Point3 { layer, x: 2, y: 2 };
    let got = pad_boundary_escape_points(&ir, start, net_id, 64);
    assert!(!got.iter().any(|p| p.x == 0 && p.y == 2));
}

