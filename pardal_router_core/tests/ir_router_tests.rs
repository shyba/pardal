use pardal_router_core::ir::RoutingIr;
use blake3::Hasher;
use pardal_router_core::kernels::{k9_try_commit_path_occ_3d, k9_try_commit_path_occ_3d_brush};
use pardal_router_core::router::{
    route_bfs_2d, route_bfs_2d_seeded, BfsScalarBackend, Point, Point3, RouterBackend,
    route_dial_3d_from_ir,
    route_dial_3d_for_net,
    route_dial_3d_for_net_with_layer_dir_costs,
    route_nets_sequential,
    route_nets_sequential_with_brushes,
    route_nets_negotiation_basic_with_brushes,
    route_nets_negotiation_seeded_dynamic_cost_with_brushes_and_layer_dir_costs,
    NetRouteRequest,
    route_net_mst,
};

#[test]
fn ir_hash_is_deterministic() {
    let mut ir = RoutingIr::new(1, 4, 3);
    ir.set_occ(0, 1, 1, 42);
    let a = ir.stable_hash();
    let b = ir.stable_hash();
    assert_eq!(a, b);

    ir.set_occ(0, 2, 2, 1);
    let c = ir.stable_hash();
    assert_ne!(a, c);
}

#[test]
fn ir_json_roundtrip_preserves_hash() {
    let mut ir = RoutingIr::new(2, 3, 2);
    ir.set_occ(0, 0, 0, 1);
    ir.set_occ(1, 2, 1, 7);
    let h0 = ir.stable_hash();

    let json = ir.to_json().expect("to_json");
    let ir2 = RoutingIr::from_json(&json).expect("from_json");
    assert_eq!(h0, ir2.stable_hash());
}

#[test]
fn bfs_routes_around_blocker() {
    // 5x5 with a vertical wall at x=2 except at y=2.
    let mut ir = RoutingIr::new(1, 5, 5);
    let blocked = 1u32;
    for y in 0..5 {
        if y == 2 {
            continue;
        }
        ir.set_occ(0, 2, y, blocked);
    }

    let path = route_bfs_2d(
        &ir,
        0,
        Point { x: 0, y: 0 },
        Point { x: 4, y: 4 },
        blocked,
    )
    .expect("path");

    // Must cross at the gap (2,2).
    assert!(path.points.contains(&Point { x: 2, y: 2 }));
    // Start and goal included.
    assert_eq!(path.points.first(), Some(&Point { x: 0, y: 0 }));
    assert_eq!(path.points.last(), Some(&Point { x: 4, y: 4 }));
}

#[test]
fn router_backend_trait_smoke() {
    let mut ir = RoutingIr::new(1, 3, 1);
    ir.set_occ(0, 1, 0, 1);

    let backend = BfsScalarBackend::default();
    assert_eq!(backend.name(), "bfs_scalar");
    let p = backend.route_2d(&ir, 0, Point { x: 0, y: 0 }, Point { x: 2, y: 0 }, 1);
    assert!(p.is_none(), "no path through blocker");
}

#[test]
fn seeded_routing_is_deterministic_and_seed_affects_tiebreaks() {
    // Open 3x3 grid: multiple shortest paths from (0,0) to (2,2).
    let ir = RoutingIr::new(1, 3, 3);

    let start = Point { x: 0, y: 0 };
    let goal = Point { x: 2, y: 2 };

    let p0a = route_bfs_2d_seeded(&ir, 0, start, goal, 1, 0).expect("path");
    let p0b = route_bfs_2d_seeded(&ir, 0, start, goal, 1, 0).expect("path");

    let mut h = Hasher::new();
    for p in &p0a.points {
        h.update(&[p.x as u8, p.y as u8]);
    }
    let h0 = *h.finalize().as_bytes();
    let mut h = Hasher::new();
    for p in &p0b.points {
        h.update(&[p.x as u8, p.y as u8]);
    }
    let h1 = *h.finalize().as_bytes();
    assert_eq!(h0, h1);

    let p1 = route_bfs_2d_seeded(&ir, 0, start, goal, 1, 1).expect("path");
    assert_ne!(p0a.points, p1.points);
}

#[test]
fn dial_3d_from_ir_uses_via_when_layer0_is_high_cost() {
    let ir = RoutingIr::new(2, 5, 1);
    let blocked_value = 1u32;

    let n2 = ir.width * ir.height;
    let mut cost_field = vec![0u16; ir.layers * n2];
    for x in 1..4 {
        cost_field[0 * n2 + x] = 50;
    }

    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 0, x: 4, y: 0 };

    let path = route_dial_3d_from_ir(&ir, start, goal, blocked_value, &cost_field, 1).expect("path");
    assert!(path.points.iter().any(|p| p.layer == 1));
}

#[test]
fn dial_3d_for_net_can_use_direction_costs_to_pick_layers() {
    let ir = RoutingIr::new(2, 5, 5);
    let blocked_value = 1u32;
    let n2 = ir.width * ir.height;
    let cost_field = vec![0u16; ir.layers * n2];

    // Penalize diagonals strongly so the cheapest path is orth-only.
    // Layer0: horizontal cheap, vertical expensive.
    // Layer1: vertical cheap, horizontal expensive.
    let layer_h = vec![0u16, 200u16];
    let layer_v = vec![200u16, 0u16];
    let layer_d = vec![200u16, 200u16];

    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 0, x: 4, y: 4 };

    let via_cost = 1u16;
    let net_id = 10u32;
    let path = route_dial_3d_for_net_with_layer_dir_costs(
        &ir,
        start,
        goal,
        blocked_value,
        &cost_field,
        &layer_h,
        &layer_v,
        &layer_d,
        via_cost,
        net_id,
    )
    .expect("path");

    assert!(
        path.points.iter().any(|p| p.layer == 1),
        "expected direction costs to encourage using layer1 for vertical travel"
    );
}

#[test]
fn dial_3d_for_net_treats_other_nets_as_blocked() {
    let mut ir = RoutingIr::new(1, 5, 5);
    let blocked_value = 1u32;
    let n2 = ir.width * ir.height;
    let cost_field = vec![0u16; ir.layers * n2];

    // Route net 10 horizontally through the center row and commit it.
    let n1 = 10u32;
    let p1 = route_dial_3d_for_net(
        &ir,
        Point3 { layer: 0, x: 0, y: 2 },
        Point3 { layer: 0, x: 4, y: 2 },
        blocked_value,
        &cost_field,
        0,
        n1,
    )
    .expect("path for net1");
    for p in &p1.points {
        ir.set_occ(p.layer, p.x, p.y, n1);
    }

    // Now try to route net 20 vertically through the center column; it must fail because the crossing is occupied.
    let n2_id = 20u32;
    let p2 = route_dial_3d_for_net(
        &ir,
        Point3 { layer: 0, x: 2, y: 0 },
        Point3 { layer: 0, x: 2, y: 4 },
        blocked_value,
        &cost_field,
        0,
        n2_id,
    );
    assert!(p2.is_none());
}

#[test]
fn pad_owner_blocks_other_nets_but_allows_own_net() {
    let mut ir = RoutingIr::new(1, 7, 5);
    let blocked_value = 1u32;
    let n2 = ir.width * ir.height;
    let cost_field = vec![0u16; ir.layers * n2];

    // Make a single horizontal corridor at y=2.
    for y in 0..ir.height {
        for x in 0..ir.width {
            if y == 2 {
                continue;
            }
            ir.set_occ(0, x, y, blocked_value);
        }
    }

    // Put a pad owned by net 10 in the corridor; net 20 must not be able to route through it.
    ir.set_pad_owner(0, 3, 2, 10);

    let p_other = route_dial_3d_for_net(
        &ir,
        Point3 { layer: 0, x: 0, y: 2 },
        Point3 { layer: 0, x: 6, y: 2 },
        blocked_value,
        &cost_field,
        0,
        20,
    );
    assert!(p_other.is_none(), "expected other net to be blocked by pad_owner");

    let p_own = route_dial_3d_for_net(
        &ir,
        Point3 { layer: 0, x: 0, y: 2 },
        Point3 { layer: 0, x: 6, y: 2 },
        blocked_value,
        &cost_field,
        0,
        10,
    );
    assert!(p_own.is_some(), "expected owning net to be allowed through pad_owner");
}

#[test]
fn seeded_negotiation_routes_only_unrouted_then_keeps_seeded_paths() {
    // Two independent nets on a 5x3 board. Seed net 10 as already routed, then negotiate net 20.
    let mut ir = RoutingIr::new(1, 5, 3);
    let blocked = 1u32;
    let n2 = ir.width * ir.height;

    // Seed net10 on top row: (0,0)->(4,0)
    let n10 = 10u32;
    for x in 0..5 {
        ir.set_occ(0, x, 0, n10);
    }

    let reqs = vec![
        NetRouteRequest {
            net_id: n10,
            start: Point3 { layer: 0, x: 0, y: 0 },
            goal: Point3 { layer: 0, x: 4, y: 0 },
        },
        NetRouteRequest {
            net_id: 20,
            start: Point3 { layer: 0, x: 0, y: 2 },
            goal: Point3 { layer: 0, x: 4, y: 2 },
        },
    ];

    let seed_paths = vec![
        Some(pardal_router_core::router::Path3 {
            points: (0..5).map(|x| Point3 { layer: 0, x, y: 0 }).collect(),
        }),
        None,
    ];

    let layer_costs: Vec<u16> = vec![0];
    let results = route_nets_negotiation_seeded_dynamic_cost_with_brushes_and_layer_dir_costs(
        &mut ir,
        &reqs,
        blocked,
        &layer_costs,
        &layer_costs,
        &layer_costs,
        0,
        &[0, 0],
        50,
        200,
        8,
        0,
        0,
        0,
        &seed_paths,
        false,
    );

    assert_eq!(results.len(), 2);
    assert!(results[0].path.is_some(), "seeded net should remain routed");
    assert!(results[1].path.is_some(), "unrouted net should be routed by negotiation");

    // Ensure net20 is committed in occupancy on bottom row.
    for x in 0..5 {
        assert_eq!(ir.get_occ(0, x, 2), 20);
    }
    // Ensure net10 is still present (was not erased).
    for x in 0..5 {
        assert_eq!(ir.get_occ(0, x, 0), 10);
    }

    // Sanity: middle row remains empty.
    for x in 0..5 {
        assert_eq!(ir.get_occ(0, x, 1), 0);
    }

    // Ensure no accidental allocation-dependent behavior (touches cost field construction).
    let _ = vec![0u16; n2];
}

#[test]
fn route_nets_sequential_routes_two_non_conflicting_nets() {
    let mut ir = RoutingIr::new(1, 7, 5);
    let blocked_value = 1u32;
    let n2 = ir.width * ir.height;
    let cost_field = vec![0u16; ir.layers * n2];

    let reqs = vec![
        NetRouteRequest {
            net_id: 10,
            start: Point3 { layer: 0, x: 0, y: 1 },
            goal: Point3 { layer: 0, x: 6, y: 1 },
        },
        NetRouteRequest {
            net_id: 20,
            start: Point3 { layer: 0, x: 0, y: 3 },
            goal: Point3 { layer: 0, x: 6, y: 3 },
        },
    ];

    let results = route_nets_sequential(&mut ir, &reqs, blocked_value, &cost_field, 0);
    assert_eq!(results.len(), 2);
    assert!(results[0].path.is_some());
    assert!(results[1].path.is_some());
    assert!(ir.occ.iter().any(|&v| v == 10));
    assert!(ir.occ.iter().any(|&v| v == 20));
}

#[test]
fn route_net_mst_connects_three_pins() {
    let mut ir = RoutingIr::new(1, 20, 20);
    let blocked_value = 1u32;
    let n2 = ir.width * ir.height;
    let cost_field = vec![0u16; ir.layers * n2];
    let net_id = 99u32;

    let pins = vec![
        Point3 { layer: 0, x: 2, y: 2 },
        Point3 { layer: 0, x: 17, y: 2 },
        Point3 { layer: 0, x: 10, y: 17 },
    ];

    let routed_edges = route_net_mst(&mut ir, net_id, &pins, blocked_value, &cost_field, 0).expect("ok");
    assert_eq!(routed_edges, 2);
    assert!(ir.occ.iter().any(|&v| v == net_id));
}

#[test]
fn route_nets_sequential_with_brushes_can_block_followup_net() {
    let mut ir = RoutingIr::new(1, 9, 5);
    let blocked_value = 1u32;
    let n2 = ir.width * ir.height;
    let cost_field = vec![0u16; ir.layers * n2];

    // Block the top and bottom rows so the only viable horizontal corridors are y=1 and y=2.
    for x in 0..ir.width {
        ir.set_occ(0, x, 0, blocked_value);
        ir.set_occ(0, x, 4, blocked_value);
    }

    let reqs = vec![
        NetRouteRequest {
            net_id: 10,
            start: Point3 { layer: 0, x: 1, y: 2 },
            goal: Point3 { layer: 0, x: 7, y: 2 },
        },
        NetRouteRequest {
            net_id: 20,
            start: Point3 { layer: 0, x: 0, y: 1 },
            goal: Point3 { layer: 0, x: 8, y: 1 },
        },
    ];

    // With a brush on the first net, its committed path occupies y=1, blocking the second corridor.
    let results = route_nets_sequential_with_brushes(
        &mut ir,
        &reqs,
        blocked_value,
        &cost_field,
        0,
        &[1, 0],
    );
    assert!(results[0].path.is_some());
    assert!(results[1].path.is_none(), "expected net2 to be blocked by net1 brush");
}

#[test]
fn negotiation_can_ripup_and_reroute() {
    // Layer0: a plus-shaped corridor; layer1: open. Net20 cannot use vias (via_forbidden),
    // so it must rip up net10 at the intersection, then net10 reroutes on layer1.
    let mut ir = RoutingIr::new(2, 5, 5);
    let blocked_value = 1u32;
    let n2 = ir.width * ir.height;
    let cost_field = vec![0u16; ir.layers * n2];

    // Block all of layer0 except row2 and col2.
    for y in 0..ir.height {
        for x in 0..ir.width {
            let keep = y == 2 || x == 2;
            if !keep {
                ir.set_occ(0, x, y, blocked_value);
            }
        }
    }

    // Forbid vias along the entire net20 corridor so it must stay on layer0.
    for y in 0..ir.height {
        ir.set_via_forbidden(0, 2, y, 1);
        ir.set_via_forbidden(1, 2, y, 1);
    }

    let reqs = vec![
        NetRouteRequest {
            net_id: 10,
            start: Point3 { layer: 0, x: 0, y: 2 },
            goal: Point3 { layer: 0, x: 4, y: 2 },
        },
        NetRouteRequest {
            net_id: 20,
            start: Point3 { layer: 0, x: 2, y: 0 },
            goal: Point3 { layer: 0, x: 2, y: 4 },
        },
    ];

    // Seed the situation: route net10 first using strict routing.
    let r0 = route_nets_sequential_with_brushes(&mut ir, &reqs[..1], blocked_value, &cost_field, 10, &[0]);
    assert!(r0[0].path.is_some(), "net10 should route in the corridor");

    // Now negotiate both nets: net20 must rip up net10; net10 must reroute on layer1.
    let results = route_nets_negotiation_basic_with_brushes(
        &mut ir,
        &reqs,
        blocked_value,
        &cost_field,
        10,
        &[0, 0],
        50, // allow crossing other nets' traces, but penalize it
        50, // max iters
        4,  // max ripups per attempt
    );
    assert_eq!(results.len(), 2);
    assert!(results[0].path.is_some(), "net10 should be rerouted");
    assert!(results[1].path.is_some(), "net20 should be routed");

    // Expect net10 to have at least one point on layer1 after reroute.
    let p10 = results[0].path.as_ref().unwrap();
    assert!(p10.points.iter().any(|p| p.layer == 1));
}

#[test]
fn transactional_commit_does_not_mutate_ir_on_conflict() {
    let mut ir = RoutingIr::new(1, 7, 3);
    let n10 = 10u32;
    let n20 = 20u32;

    // Pre-place net10 occupancy at (3,1).
    ir.set_occ(0, 3, 1, n10);

    // Try to commit a net20 path that hits the occupied cell; it must fail without mutating the grid.
    let path = vec![
        Point3 { layer: 0, x: 1, y: 1 },
        Point3 { layer: 0, x: 3, y: 1 },
        Point3 { layer: 0, x: 5, y: 1 },
    ];
    let before = ir.occ.clone();
    let err = k9_try_commit_path_occ_3d(&mut ir, &path, n20).expect_err("expected conflict");
    assert!(!err.is_empty());
    assert_eq!(ir.occ, before, "IR must not change on failed transactional commit");

    // Same for brush commit.
    let before = ir.occ.clone();
    let err = k9_try_commit_path_occ_3d_brush(&mut ir, &path, n20, 1).expect_err("expected conflict");
    assert!(!err.is_empty());
    assert_eq!(ir.occ, before, "IR must not change on failed transactional brush commit");
}
