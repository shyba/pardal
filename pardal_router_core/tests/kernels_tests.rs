use pardal_router_core::geom::{Circle, LayeredPolygon, Polygon, Rect, Via};
use pardal_router_core::ir::RoutingIr;
use pardal_router_core::kernels::{
    k0_rasterize_circles_occ, k0_rasterize_polygon_fill_occ, k0_rasterize_rects_occ,
    k0_rasterize_layered_polygons_occ, k0_rasterize_vias_occ,
    k13_uncommit_net_occ,
    k13_uncommit_net_occ_3d,
    k3_clearance_distance_manhattan,
    k6_wavefront_bfs_2d, k6_wavefront_bfs_3d, k6_wavefront_bfs_3d_diag,
    k6_wavefront_bfs_3d_diag_to_goal,
    k6_wavefront_bfs_3d_diag_to_goals,
    k6_wavefront_dial_2d, k7_extract_path_2d,
    k7_extract_path_3d, k8_simplify_collinear_manhattan, k6_wavefront_dial_3d,
    k6_wavefront_dial_2d_diag, k6_wavefront_dial_3d_diag,
    k6_wavefront_dial_3d_occ,
    k6_wavefront_dial_3d_occ_diag,
    k6_wavefront_dial_3d_occ_diag_to_goal,
    k6_wavefront_dial_3d_occ_to_goal,
    k6_wavefront_dial_3d_occ_owner,
    k6_wavefront_dial_3d_occ_owner_diag,
    k6_wavefront_dial_3d_occ_owner_diag_to_goal,
    k6_wavefront_dial_3d_occ_owner_to_goal,
    k9_commit_path_occ, k9_commit_path_occ_3d, k9_commit_path_occ_3d_brush,
};
use pardal_router_core::connectivity::unreachable_goals_diag;
use pardal_router_core::kicad_ir::{build_routing_ir, LayeredRect, NormalizedIrInput};
use pardal_router_core::router::{route_dial_3d_from_ir, Point, Point3};

#[test]
fn k0_rasterize_rects_fills_expected_cells() {
    let mut ir = RoutingIr::new(1, 6, 4);
    let rects = [Rect::new(1, 1, 4, 3)];
    k0_rasterize_rects_occ(&mut ir, 0, &rects, 7);

    for y in 0..4 {
        for x in 0..6 {
            let v = ir.get_occ(0, x, y);
            let expected = if (1..4).contains(&x) && (1..3).contains(&y) {
                7
            } else {
                0
            };
            assert_eq!(v, expected, "x={x} y={y}");
        }
    }
}

#[test]
fn k0_rasterize_circles_fills_expected_cells() {
    let mut ir = RoutingIr::new(1, 7, 7);
    let circles = [Circle::new(Point { x: 3, y: 3 }, 2)];
    k0_rasterize_circles_occ(&mut ir, 0, &circles, 5);

    let filled = |x: usize, y: usize| -> bool { ir.get_occ(0, x, y) == 5 };
    assert!(filled(3, 3));
    assert!(filled(3, 1));
    assert!(filled(3, 5));
    assert!(filled(1, 3));
    assert!(filled(5, 3));

    // Corners outside radius-2 circle.
    assert!(!filled(1, 1));
    assert!(!filled(5, 5));
    assert!(!filled(1, 5));
    assert!(!filled(5, 1));
}

#[test]
fn k0_rasterize_polygon_fill_matches_axis_aligned_rect() {
    let mut ir = RoutingIr::new(1, 6, 4);
    let poly = Polygon::new(vec![
        Point { x: 1, y: 1 },
        Point { x: 4, y: 1 },
        Point { x: 4, y: 3 },
        Point { x: 1, y: 3 },
    ]);
    k0_rasterize_polygon_fill_occ(&mut ir, 0, &[poly], 7);

    for y in 0..4 {
        for x in 0..6 {
            let v = ir.get_occ(0, x, y);
            let expected = if (1..4).contains(&x) && (1..3).contains(&y) {
                7
            } else {
                0
            };
            assert_eq!(v, expected, "x={x} y={y}");
        }
    }
}

#[test]
fn k0_rasterize_vias_stamps_only_selected_layers() {
    let mut ir = RoutingIr::new(3, 7, 7);
    let via = Via::new(Point { x: 3, y: 3 }, 1, vec![0, 2]);

    k0_rasterize_vias_occ(&mut ir, &[via], 9);

    // Center always filled on stamped layers.
    assert_eq!(ir.get_occ(0, 3, 3), 9);
    assert_eq!(ir.get_occ(2, 3, 3), 9);
    // Middle layer untouched.
    assert_eq!(ir.get_occ(1, 3, 3), 0);
}

#[test]
fn k0_rasterize_layered_polygons_stamps_per_layer() {
    let mut ir = RoutingIr::new(2, 6, 4);
    let poly = Polygon::new(vec![
        Point { x: 1, y: 1 },
        Point { x: 4, y: 1 },
        Point { x: 4, y: 3 },
        Point { x: 1, y: 3 },
    ]);
    let layered = [
        LayeredPolygon::new(0, poly.clone()),
        LayeredPolygon::new(1, poly),
    ];

    k0_rasterize_layered_polygons_occ(&mut ir, &layered, 7);

    for layer in 0..2 {
        for y in 0..4 {
            for x in 0..6 {
                let v = ir.get_occ(layer, x, y);
                let expected = if (1..4).contains(&x) && (1..3).contains(&y) {
                    7
                } else {
                    0
                };
                assert_eq!(v, expected, "layer={layer} x={x} y={y}");
            }
        }
    }
}

#[test]
fn k3_clearance_distance_center_obstacle() {
    let mut ir = RoutingIr::new(1, 5, 5);
    let blocked = 9u32;
    ir.set_occ(0, 2, 2, blocked);

    let d = k3_clearance_distance_manhattan(&ir, 0, blocked);
    let idx = |x: usize, y: usize| -> usize { y * 5 + x };

    assert_eq!(d[idx(2, 2)], 0);
    assert_eq!(d[idx(2, 1)], 1);
    assert_eq!(d[idx(1, 2)], 1);
    assert_eq!(d[idx(4, 4)], 4);
    assert_eq!(d[idx(0, 0)], 4);
}

#[test]
fn k9_commit_detects_conflicts_and_does_not_overwrite() {
    let mut ir = RoutingIr::new(1, 3, 1);
    ir.set_occ(0, 1, 0, 2);
    let path = [Point { x: 0, y: 0 }, Point { x: 1, y: 0 }, Point { x: 2, y: 0 }];

    let conflicts = k9_commit_path_occ(&mut ir, 0, &path, 1);
    assert_eq!(conflicts.len(), 1);
    assert_eq!(conflicts[0].x, 1);
    assert_eq!(conflicts[0].existing, 2);
    assert_eq!(conflicts[0].attempted, 1);

    // Ensure we didn't overwrite the conflicting cell.
    assert_eq!(ir.get_occ(0, 1, 0), 2);
    // Other cells were committed.
    assert_eq!(ir.get_occ(0, 0, 0), 1);
    assert_eq!(ir.get_occ(0, 2, 0), 1);
}

#[test]
fn k13_uncommit_clears_only_target_net() {
    let mut ir = RoutingIr::new(1, 4, 1);
    ir.set_occ(0, 0, 0, 1);
    ir.set_occ(0, 1, 0, 2);
    ir.set_occ(0, 2, 0, 1);

    k13_uncommit_net_occ(&mut ir, 0, 1);
    assert_eq!(ir.get_occ(0, 0, 0), 0);
    assert_eq!(ir.get_occ(0, 1, 0), 2);
    assert_eq!(ir.get_occ(0, 2, 0), 0);
}

#[test]
fn k9_commit_3d_detects_conflicts_across_layers_and_uncommit_3d_clears() {
    let mut ir = RoutingIr::new(2, 3, 1);
    // Pre-own one cell on layer 1 by net 2.
    ir.set_occ(1, 1, 0, 2);

    let path = [
        Point3 { layer: 0, x: 0, y: 0 },
        Point3 { layer: 0, x: 1, y: 0 },
        Point3 { layer: 1, x: 1, y: 0 }, // via transition cell conflicts
        Point3 { layer: 1, x: 2, y: 0 },
    ];

    let conflicts = k9_commit_path_occ_3d(&mut ir, &path, 1);
    assert_eq!(conflicts.len(), 1);
    assert_eq!(conflicts[0].layer, 1);
    assert_eq!(conflicts[0].x, 1);
    assert_eq!(conflicts[0].existing, 2);

    // Non-conflicting cells committed.
    assert_eq!(ir.get_occ(0, 0, 0), 1);
    assert_eq!(ir.get_occ(0, 1, 0), 1);
    assert_eq!(ir.get_occ(1, 2, 0), 1);
    // Conflicting cell unchanged.
    assert_eq!(ir.get_occ(1, 1, 0), 2);

    k13_uncommit_net_occ_3d(&mut ir, 1);
    assert_eq!(ir.get_occ(0, 0, 0), 0);
    assert_eq!(ir.get_occ(0, 1, 0), 0);
    assert_eq!(ir.get_occ(1, 2, 0), 0);
    // Other net preserved.
    assert_eq!(ir.get_occ(1, 1, 0), 2);
}

#[test]
fn k9_commit_3d_brush_inflates_path_and_detects_neighbor_conflicts() {
    let mut ir = RoutingIr::new(1, 5, 1);
    // Pre-own a neighbor cell by another net.
    ir.set_occ(0, 3, 0, 2);

    let path = [Point3 { layer: 0, x: 2, y: 0 }];
    let conflicts = k9_commit_path_occ_3d_brush(&mut ir, &path, 1, 1);

    // Brush radius=1 stamps x=1..=3, so x=3 conflicts.
    assert!(conflicts.iter().any(|c| c.x == 3 && c.existing == 2));
    // And it inflates into x=1 as well.
    assert_eq!(ir.get_occ(0, 1, 0), 1);
    assert_eq!(ir.get_occ(0, 2, 0), 1);
    // Conflicting cell preserved.
    assert_eq!(ir.get_occ(0, 3, 0), 2);
}

#[test]
fn k9_commit_3d_brush_clips_pad_owner_halo() {
    let mut ir = RoutingIr::new(1, 5, 1);
    // Neighbor pad owned by another net: the brush halo should be clipped, not treated as a conflict.
    ir.set_pad_owner(0, 3, 0, 2);

    let path = [Point3 { layer: 0, x: 2, y: 0 }];
    let conflicts = k9_commit_path_occ_3d_brush(&mut ir, &path, 1, 1);
    assert!(
        !conflicts.iter().any(|c| c.existing == 2),
        "pad_owner halo should not produce conflicts"
    );
    assert_eq!(ir.get_occ(0, 1, 0), 1);
    assert_eq!(ir.get_occ(0, 2, 0), 1);
    // Clipped cell is untouched.
    assert_eq!(ir.get_occ(0, 3, 0), 0);
}

#[test]
fn k9_try_commit_3d_brush_still_rejects_core_pad_owner_conflict() {
    let mut ir = RoutingIr::new(1, 5, 1);
    // Core point is inside another net's pad: this must still be a hard conflict.
    ir.set_pad_owner(0, 2, 0, 2);

    let path = [Point3 { layer: 0, x: 2, y: 0 }];
    let r = pardal_router_core::kernels::k9_try_commit_path_occ_3d_brush(&mut ir, &path, 1, 1);
    assert!(r.is_err());
    // Transactional: nothing is committed.
    assert_eq!(ir.get_occ(0, 1, 0), 0);
    assert_eq!(ir.get_occ(0, 2, 0), 0);
    assert_eq!(ir.get_occ(0, 3, 0), 0);
}

#[test]
fn k9_commit_3d_brush_clips_pad_owner_halo_for_vias() {
    let mut ir = RoutingIr::new(2, 5, 1);
    // Neighbor pad on layer0 only. Via stamping remains strict vs pads to preserve
    // pin↔via clearance behavior.
    ir.set_pad_owner(0, 3, 0, 2);

    let path = [
        Point3 { layer: 0, x: 2, y: 0 },
        Point3 { layer: 1, x: 2, y: 0 },
    ];
    let conflicts = k9_commit_path_occ_3d_brush(&mut ir, &path, 1, 1);
    assert!(conflicts.iter().any(|c| c.existing == 2));
    // Via core occupies both layers at x=2.
    assert_eq!(ir.get_occ(0, 2, 0), 1);
    assert_eq!(ir.get_occ(1, 2, 0), 1);
    // Conflicting cell is untouched.
    assert_eq!(ir.get_occ(0, 3, 0), 0);
}

#[test]
fn k9_commit_3d_brush_allows_via_in_pad_to_clip_pad_owner_halo() {
    let mut ir = RoutingIr::new(2, 5, 1);
    // Via center is in our own pad on layer0, but the halo overlaps a neighbor pad.
    ir.set_pad_owner(0, 2, 0, 1);
    ir.set_pad_owner(0, 3, 0, 2);

    let path = [
        Point3 { layer: 0, x: 2, y: 0 },
        Point3 { layer: 1, x: 2, y: 0 },
    ];
    let conflicts = k9_commit_path_occ_3d_brush(&mut ir, &path, 1, 1);
    assert!(
        !conflicts.iter().any(|c| c.existing == 2),
        "via-in-pad should clip the halo against other pads"
    );
    assert_eq!(ir.get_occ(0, 2, 0), 1);
    assert_eq!(ir.get_occ(1, 2, 0), 1);
}

#[test]
fn k6_k7_wavefront_and_extract_roundtrip() {
    // 5x5 with a vertical wall at x=2 except at y=2.
    let mut ir = RoutingIr::new(1, 5, 5);
    let blocked = 1u32;
    for y in 0..5 {
        if y == 2 {
            continue;
        }
        ir.set_occ(0, 2, y, blocked);
    }
    let start = Point { x: 0, y: 0 };
    let goal = Point { x: 4, y: 4 };

    let (dist, prev) = k6_wavefront_bfs_2d(&ir, 0, start, blocked);
    let goal_i = goal.y * ir.width + goal.x;
    assert_ne!(dist[goal_i], u32::MAX);

    let path = k7_extract_path_2d(ir.width, &prev, start, goal).expect("path");
    assert_eq!(path.first(), Some(&start));
    assert_eq!(path.last(), Some(&goal));
}

#[test]
fn k6_k7_wavefront_3d_uses_via_to_bypass_blocked_layer() {
    let mut ir = RoutingIr::new(2, 5, 3);
    let blocked = 1u32;
    let start = Point3 { layer: 0, x: 0, y: 1 };
    let goal = Point3 { layer: 0, x: 4, y: 1 };
    // Force a via escape: block every other cell on layer 0, but keep layer 1 open.
    for y in 0..ir.height {
        for x in 0..ir.width {
            ir.set_occ(0, x, y, blocked);
        }
    }
    ir.set_occ(0, start.x, start.y, 0);
    ir.set_occ(0, goal.x, goal.y, 0);

    let (dist, prev) = k6_wavefront_bfs_3d(&ir, start, blocked);
    let goal_i = goal.layer * ir.width * ir.height + goal.y * ir.width + goal.x;
    assert_ne!(dist[goal_i], u32::MAX);

    let path = k7_extract_path_3d(ir.width, ir.height, ir.layers, &prev, start, goal).expect("path");
    assert_eq!(path.first().copied(), Some(start));
    assert_eq!(path.last().copied(), Some(goal));
    assert!(path.iter().any(|p| p.layer == 1));
}

#[test]
fn k6_dial_3d_respects_via_forbidden_mask() {
    let mut ir = RoutingIr::new(2, 3, 3);
    let blocked = 9u32;

    let start = Point3 { layer: 0, x: 1, y: 1 };
    let goal = Point3 { layer: 1, x: 1, y: 1 };

    let n2 = ir.width * ir.height;
    let cost_field = vec![0u16; ir.layers * n2];
    let via_cost = 1u16;

    // Baseline: via is allowed.
    let p0 = route_dial_3d_from_ir(&ir, start, goal, blocked, &cost_field, via_cost);
    assert!(p0.is_some(), "expected to route via transition when allowed");

    // Forbid vias at the direct overlap location on both layers; routing should still succeed,
    // but the via transition must occur elsewhere.
    ir.set_via_forbidden(0, 1, 1, 1);
    ir.set_via_forbidden(1, 1, 1, 1);
    let p1 = route_dial_3d_from_ir(&ir, start, goal, blocked, &cost_field, via_cost).expect("route");
    for w in p1.points.windows(2) {
        let a = w[0];
        let b = w[1];
        if a.layer != b.layer {
            assert_ne!((a.x, a.y), (1, 1));
            assert_ne!((b.x, b.y), (1, 1));
        }
    }

    // Forbid vias everywhere; routing should become impossible.
    for layer in 0..ir.layers {
        for y in 0..ir.height {
            for x in 0..ir.width {
                ir.set_via_forbidden(layer, x, y, 1);
            }
        }
    }
    let p2 = route_dial_3d_from_ir(&ir, start, goal, blocked, &cost_field, via_cost);
    assert!(p2.is_none(), "global via_forbidden should prevent any vertical transition");
}

#[test]
fn route_dial_3d_for_net_respects_via_forbidden() {
    use pardal_router_core::router::route_dial_3d_for_net;

    let mut ir = RoutingIr::new(2, 3, 3);
    let blocked = 1u32;
    let net_id = 2u32;

    // Make a case where the only possible layer transition is at (1,1).
    for y in 0..ir.height {
        for x in 0..ir.width {
            if (x, y) != (1, 1) {
                ir.set_occ(1, x, y, blocked);
            }
        }
    }

    let start = Point3 { layer: 0, x: 1, y: 1 };
    let goal = Point3 { layer: 1, x: 1, y: 1 };
    let n2 = ir.width * ir.height;
    let cost_field = vec![0u16; ir.layers * n2];
    let via_cost = 1u16;

    // Baseline: via is allowed.
    assert!(
        route_dial_3d_for_net(&ir, start, goal, blocked, &cost_field, via_cost, net_id).is_some(),
        "expected to route with direct via when allowed"
    );

    // Forbid the only via location.
    ir.set_via_forbidden(0, 1, 1, 1);
    ir.set_via_forbidden(1, 1, 1, 1);
    assert!(
        route_dial_3d_for_net(&ir, start, goal, blocked, &cost_field, via_cost, net_id).is_none(),
        "expected routing to fail when the only possible via is forbidden"
    );
}

#[test]
fn k6_bfs_3d_diag_shortcuts_in_open_space() {
    let ir = RoutingIr::new(1, 3, 3);
    let blocked = 1u32;
    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 0, x: 2, y: 2 };
    let goal_i = goal.layer * ir.width * ir.height + goal.y * ir.width + goal.x;

    let (d_orth, _) = k6_wavefront_bfs_3d(&ir, start, blocked);
    let (d_diag, p_diag) = k6_wavefront_bfs_3d_diag(&ir, start, blocked);

    assert_eq!(d_orth[goal_i], 4);
    assert_eq!(d_diag[goal_i], 2);

    let path = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_diag, start, goal).expect("path");
    assert_eq!(path.first().copied(), Some(start));
    assert_eq!(path.last().copied(), Some(goal));
}

#[test]
fn k6_bfs_3d_diag_disallows_corner_cutting() {
    let mut ir = RoutingIr::new(1, 2, 2);
    let blocked = 1u32;
    ir.set_occ(0, 1, 0, blocked);
    ir.set_occ(0, 0, 1, blocked);
    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 0, x: 1, y: 1 };
    let goal_i = goal.layer * ir.width * ir.height + goal.y * ir.width + goal.x;

    let (d_diag, _) = k6_wavefront_bfs_3d_diag(&ir, start, blocked);
    assert_eq!(d_diag[goal_i], u32::MAX);
}

#[test]
fn k6_bfs_3d_diag_to_goal_matches_full_dist_prev() {
    let ir = RoutingIr::new(2, 6, 4);
    let blocked = 1u32;
    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 1, x: 5, y: 3 };
    let goal_i = goal.layer * ir.width * ir.height + goal.y * ir.width + goal.x;

    let (d_full, p_full) = k6_wavefront_bfs_3d_diag(&ir, start, blocked);
    let (d_goal, p_goal) = k6_wavefront_bfs_3d_diag_to_goal(&ir, start, goal, blocked);
    assert_eq!(d_full[goal_i], d_goal[goal_i]);

    let path_full = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_full, start, goal).expect("path");
    let path_goal = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_goal, start, goal).expect("path");
    assert_eq!(path_full, path_goal);
}

#[test]
fn k6_bfs_3d_diag_to_goals_matches_full_for_goal_nodes() {
    let ir = RoutingIr::new(2, 6, 4);
    let blocked = 1u32;
    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goals = [
        Point3 { layer: 1, x: 5, y: 3 },
        Point3 { layer: 0, x: 5, y: 0 },
    ];
    let n2 = ir.width * ir.height;

    let (d_full, p_full) = k6_wavefront_bfs_3d_diag(&ir, start, blocked);
    let (d_goals, p_goals) = k6_wavefront_bfs_3d_diag_to_goals(&ir, start, &goals, blocked);

    for goal in goals {
        let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;
        assert_eq!(d_full[goal_i], d_goals[goal_i]);
        let path_full = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_full, start, goal).expect("path");
        let path_goals = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_goals, start, goal).expect("path");
        assert_eq!(path_full, path_goals);
    }
}

#[test]
fn connectivity_unreachable_goals_diag_reports_blocked_terminal() {
    // 3x3 single-layer with a full wall at x=1 blocks access to the right side.
    let mut ir = RoutingIr::new(1, 3, 3);
    let blocked = 9u32;
    for y in 0..3 {
        ir.set_occ(0, 1, y, blocked);
    }

    let start = Point3 { layer: 0, x: 0, y: 1 };
    let goals = [Point3 { layer: 0, x: 2, y: 1 }, Point3 { layer: 0, x: 0, y: 2 }];
    let unreachable = unreachable_goals_diag(&ir, start, &goals, blocked);
    assert_eq!(unreachable, vec![Point3 { layer: 0, x: 2, y: 1 }]);
}

#[test]
fn kicad_ir_build_routing_ir_stamps_obstacles() {
    let blocked = 7u32;
    let input = NormalizedIrInput {
        layers: 2,
        width: 6,
        height: 4,
        rects: vec![LayeredRect::new(0, Rect::new(1, 1, 4, 3))],
        polygons: vec![LayeredPolygon::new(
            1,
            Polygon::new(vec![
                Point { x: 0, y: 0 },
                Point { x: 2, y: 0 },
                Point { x: 2, y: 2 },
                Point { x: 0, y: 2 },
            ]),
        )],
        vias: vec![Via::new(Point { x: 5, y: 3 }, 0, vec![0, 1])],
    };

    let ir = build_routing_ir(&input, blocked);
    assert_eq!(ir.layers, 2);
    assert_eq!(ir.width, 6);
    assert_eq!(ir.height, 4);

    // Rect stamps only layer 0.
    assert_eq!(ir.get_occ(0, 2, 2), blocked);
    assert_eq!(ir.get_occ(1, 2, 2), 0);

    // Polygon stamps only layer 1.
    assert_eq!(ir.get_occ(1, 1, 1), blocked);
    assert_eq!(ir.get_occ(0, 1, 1), blocked); // also in rect on layer 0

    // Via stamps both layers at its center.
    assert_eq!(ir.get_occ(0, 5, 3), blocked);
    assert_eq!(ir.get_occ(1, 5, 3), blocked);
}

#[test]
fn k6_dial_3d_avoids_vias_when_expensive() {
    let width = 5usize;
    let height = 1usize;
    let layers = 2usize;
    let n2 = width * height;
    let n = layers * n2;
    let blocked = vec![false; n];
    let cost = vec![0u16; n];

    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 0, x: 4, y: 0 };
    let (dist, prev) = k6_wavefront_dial_3d(width, height, layers, &blocked, &cost, start, 50);
    let goal_i = goal.layer * n2 + goal.y * width + goal.x;
    assert_ne!(dist[goal_i], u32::MAX);

    let path = k7_extract_path_3d(width, height, layers, &prev, start, goal).expect("path");
    assert!(path.iter().all(|p| p.layer == 0));
}

#[test]
fn k6_dial_3d_uses_via_when_layer0_is_high_cost() {
    let width = 5usize;
    let height = 1usize;
    let layers = 2usize;
    let n2 = width * height;
    let n = layers * n2;
    let blocked = vec![false; n];
    let mut cost = vec![0u16; n];

    // Penalize the interior of layer 0 so routing should prefer layer 1 with cheap via cost.
    let idx = |layer: usize, x: usize, y: usize| -> usize { layer * n2 + y * width + x };
    for x in 1..4 {
        cost[idx(0, x, 0)] = 50;
    }

    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 0, x: 4, y: 0 };
    let (dist, prev) = k6_wavefront_dial_3d(width, height, layers, &blocked, &cost, start, 1);
    let goal_i = goal.layer * n2 + goal.y * width + goal.x;
    assert_ne!(dist[goal_i], u32::MAX);

    let path = k7_extract_path_3d(width, height, layers, &prev, start, goal).expect("path");
    assert!(path.iter().any(|p| p.layer == 1));
}

#[test]
fn k6_dial_3d_occ_matches_blocked_bool_variant() {
    let mut ir = RoutingIr::new(2, 4, 3);
    let blocked_value = 9u32;
    // Block a small wall on layer 0.
    for y in 0..ir.height {
        ir.set_occ(0, 2, y, blocked_value);
    }
    ir.set_occ(0, 2, 1, 0); // a gap

    let n2 = ir.width * ir.height;
    let n = ir.layers * n2;
    let mut blocked = vec![false; n];
    for layer in 0..ir.layers {
        for y in 0..ir.height {
            for x in 0..ir.width {
                blocked[layer * n2 + y * ir.width + x] = ir.get_occ(layer, x, y) == blocked_value;
            }
        }
    }
    let cost = vec![0u16; n];
    let start = Point3 { layer: 0, x: 0, y: 1 };

    let (d1, p1) = k6_wavefront_dial_3d(ir.width, ir.height, ir.layers, &blocked, &cost, start, 1);
    let (d2, p2) = k6_wavefront_dial_3d_occ(&ir, start, blocked_value, &cost, 1);
    assert_eq!(d1, d2);
    assert_eq!(p1, p2);
}

#[test]
fn k6_dial_3d_occ_diag_matches_blocked_bool_variant() {
    let mut ir = RoutingIr::new(2, 4, 3);
    let blocked_value = 9u32;
    // Block a small wall on layer 0.
    for y in 0..ir.height {
        ir.set_occ(0, 2, y, blocked_value);
    }
    ir.set_occ(0, 2, 1, 0); // a gap

    let n2 = ir.width * ir.height;
    let n = ir.layers * n2;
    let mut blocked = vec![false; n];
    for layer in 0..ir.layers {
        for y in 0..ir.height {
            for x in 0..ir.width {
                blocked[layer * n2 + y * ir.width + x] = ir.get_occ(layer, x, y) == blocked_value;
            }
        }
    }
    let cost = vec![0u16; n];
    let start = Point3 { layer: 0, x: 0, y: 1 };

    let (d1, p1) =
        k6_wavefront_dial_3d_diag(ir.width, ir.height, ir.layers, &blocked, &cost, start, 1, 0);
    let (d2, p2) = k6_wavefront_dial_3d_occ_diag(&ir, start, blocked_value, &cost, 1, 0);
    assert_eq!(d1, d2);
    assert_eq!(p1, p2);
}

#[test]
fn k6_dial_3d_occ_diag_to_goal_matches_full_dist_prev() {
    let ir = RoutingIr::new(2, 6, 4);
    let blocked_value = 1u32;
    let n2 = ir.width * ir.height;
    let cost = vec![0u16; ir.layers * n2];
    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 1, x: 5, y: 3 };

    let (d_full, p_full) = k6_wavefront_dial_3d_occ_diag(&ir, start, blocked_value, &cost, 3, 0);
    let (d_goal, p_goal) =
        k6_wavefront_dial_3d_occ_diag_to_goal(&ir, start, goal, blocked_value, &cost, 3, 0);
    let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;
    assert_eq!(d_full[goal_i], d_goal[goal_i]);
    let path_full = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_full, start, goal).expect("path");
    let path_goal = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_goal, start, goal).expect("path");
    assert_eq!(path_full, path_goal);
}

#[test]
fn k6_dial_3d_occ_to_goal_matches_full_dist_prev() {
    let ir = RoutingIr::new(2, 6, 4);
    let blocked_value = 1u32;
    let n2 = ir.width * ir.height;
    let cost = vec![0u16; ir.layers * n2];
    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 1, x: 5, y: 3 };

    let (d_full, p_full) = k6_wavefront_dial_3d_occ(&ir, start, blocked_value, &cost, 3);
    let (d_goal, p_goal) = k6_wavefront_dial_3d_occ_to_goal(&ir, start, goal, blocked_value, &cost, 3);
    let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;
    assert_eq!(d_full[goal_i], d_goal[goal_i]);
    let path_full = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_full, start, goal).expect("path");
    let path_goal = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_goal, start, goal).expect("path");
    assert_eq!(path_full, path_goal);
}

#[test]
fn k6_dial_3d_owner_to_goal_matches_full_dist_prev() {
    let mut ir = RoutingIr::new(2, 6, 4);
    let blocked_value = 1u32;
    // Add an existing route owned by net 7.
    for x in 1..5 {
        ir.set_occ(0, x, 2, 7);
    }
    let n2 = ir.width * ir.height;
    let cost = vec![0u16; ir.layers * n2];
    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 1, x: 5, y: 3 };

    let (d_full, p_full) = k6_wavefront_dial_3d_occ_owner(&ir, start, blocked_value, &cost, 3, 42);
    let (d_goal, p_goal) = k6_wavefront_dial_3d_occ_owner_to_goal(&ir, start, goal, blocked_value, &cost, 3, 42);
    let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;
    assert_eq!(d_full[goal_i], d_goal[goal_i]);
    let path_full = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_full, start, goal).expect("path");
    let path_goal = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_goal, start, goal).expect("path");
    assert_eq!(path_full, path_goal);
}

#[test]
fn k6_dial_3d_owner_diag_allows_own_net_cells() {
    let mut ir = RoutingIr::new(1, 3, 3);
    let blocked_value = 9u32;
    let n2 = ir.width * ir.height;
    let cost = vec![0u16; ir.layers * n2];

    // Pre-own the center cell by net 42.
    ir.set_occ(0, 1, 1, 42);

    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 0, x: 2, y: 2 };
    let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;

    // When routing for net 42, the owned cell is legal and the diagonal path is optimal.
    let (d_ok, p_ok) = k6_wavefront_dial_3d_occ_owner_diag(&ir, start, blocked_value, &cost, 0, 0, 42);
    assert_eq!(d_ok[goal_i], 2);
    let path_ok = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_ok, start, goal).expect("path");
    assert!(path_ok.iter().any(|p| p.x == 1 && p.y == 1));

    // For a different net, that cell is blocked and the shortest path becomes a 4-step orth route.
    let (d_blocked, _) =
        k6_wavefront_dial_3d_occ_owner_diag(&ir, start, blocked_value, &cost, 0, 0, 7);
    assert_eq!(d_blocked[goal_i], 4);
}

#[test]
fn k6_dial_3d_owner_diag_to_goal_matches_full_dist_prev() {
    let mut ir = RoutingIr::new(2, 6, 4);
    let blocked_value = 1u32;
    // Add an existing route owned by net 7.
    for x in 1..5 {
        ir.set_occ(0, x, 2, 7);
    }
    let n2 = ir.width * ir.height;
    let cost = vec![0u16; ir.layers * n2];
    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 1, x: 5, y: 3 };

    let (d_full, p_full) = k6_wavefront_dial_3d_occ_owner_diag(&ir, start, blocked_value, &cost, 3, 0, 42);
    let (d_goal, p_goal) = k6_wavefront_dial_3d_occ_owner_diag_to_goal(
        &ir,
        start,
        goal,
        blocked_value,
        &cost,
        3,
        0,
        42,
    );
    let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;
    assert_eq!(d_full[goal_i], d_goal[goal_i]);
    let path_full = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_full, start, goal).expect("path");
    let path_goal = k7_extract_path_3d(ir.width, ir.height, ir.layers, &p_goal, start, goal).expect("path");
    assert_eq!(path_full, path_goal);
}

#[test]
fn k8_simplify_removes_collinear_points() {
    let path = vec![
        Point { x: 0, y: 0 },
        Point { x: 1, y: 0 },
        Point { x: 2, y: 0 },
        Point { x: 2, y: 1 },
        Point { x: 2, y: 2 },
    ];
    let simplified = k8_simplify_collinear_manhattan(&path);
    assert_eq!(
        simplified,
        vec![Point { x: 0, y: 0 }, Point { x: 2, y: 0 }, Point { x: 2, y: 2 }]
    );
}

#[test]
fn k6_dial_prefers_low_cost_corridor() {
    // 3x5 grid:
    // start at (0,2), goal at (4,2)
    // middle row has high cost cells except ends, so optimal path should go around.
    let w = 5usize;
    let h = 3usize;
    let n = w * h;
    let blocked = vec![false; n];
    let mut cost = vec![0u16; n];

    let idx = |x: usize, y: usize| -> usize { y * w + x };
    for x in 1..4 {
        cost[idx(x, 1)] = 50;
    }

    let start = Point { x: 0, y: 1 };
    let goal = Point { x: 4, y: 1 };
    let (dist, prev) = k6_wavefront_dial_2d(w, h, &blocked, &cost, start);
    assert_ne!(dist[idx(goal.x, goal.y)], u32::MAX);

    let raw = k7_extract_path_2d(w, &prev, start, goal).expect("path");
    // The direct middle corridor would include (2,1). It should avoid it.
    assert!(!raw.contains(&Point { x: 2, y: 1 }));
}

#[test]
fn k6_dial_2d_diag_shortcuts_when_diag_is_free() {
    let w = 3usize;
    let h = 3usize;
    let n = w * h;
    let blocked = vec![false; n];
    let cost = vec![0u16; n];
    let start = Point { x: 0, y: 0 };
    let goal = Point { x: 2, y: 2 };
    let idx = |x: usize, y: usize| -> usize { y * w + x };

    let (dist_orth, _) = k6_wavefront_dial_2d(w, h, &blocked, &cost, start);
    let (dist_diag, prev_diag) = k6_wavefront_dial_2d_diag(w, h, &blocked, &cost, start, 0);

    assert_eq!(dist_orth[idx(goal.x, goal.y)], 4);
    assert_eq!(dist_diag[idx(goal.x, goal.y)], 2);

    let path = k7_extract_path_2d(w, &prev_diag, start, goal).expect("path");
    assert_eq!(path.first(), Some(&start));
    assert_eq!(path.last(), Some(&goal));
    assert_eq!(path.len(), 3); // (0,0)->(1,1)->(2,2)
}

#[test]
fn k6_dial_2d_diag_respects_extra_cost() {
    let w = 3usize;
    let h = 3usize;
    let n = w * h;
    let blocked = vec![false; n];
    let cost = vec![0u16; n];
    let start = Point { x: 0, y: 0 };
    let goal = Point { x: 2, y: 2 };
    let idx = |x: usize, y: usize| -> usize { y * w + x };

    let (dist_diag, _) = k6_wavefront_dial_2d_diag(w, h, &blocked, &cost, start, 100);
    assert_eq!(dist_diag[idx(goal.x, goal.y)], 4);
}

#[test]
fn k6_dial_2d_diag_disallows_corner_cutting() {
    // 2x2:
    // start (0,0), goal (1,1)
    // block both orthogonal adjacent cells, so only a diagonal "corner cut" could connect.
    let w = 2usize;
    let h = 2usize;
    let n = w * h;
    let mut blocked = vec![false; n];
    let cost = vec![0u16; n];
    let start = Point { x: 0, y: 0 };
    let goal = Point { x: 1, y: 1 };
    let idx = |x: usize, y: usize| -> usize { y * w + x };

    blocked[idx(1, 0)] = true;
    blocked[idx(0, 1)] = true;

    let (dist_diag, _) = k6_wavefront_dial_2d_diag(w, h, &blocked, &cost, start, 0);
    assert_eq!(dist_diag[idx(goal.x, goal.y)], u32::MAX);
}

#[test]
fn k6_dial_3d_diag_shortcuts_without_using_vias() {
    let width = 3usize;
    let height = 3usize;
    let layers = 2usize;
    let n2 = width * height;
    let n = layers * n2;
    let blocked = vec![false; n];
    let cost = vec![0u16; n];

    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 0, x: 2, y: 2 };
    let goal_i = goal.layer * n2 + goal.y * width + goal.x;

    let (dist, prev) = k6_wavefront_dial_3d_diag(
        width,
        height,
        layers,
        &blocked,
        &cost,
        start,
        50, // expensive via
        0,  // free diagonal
    );
    assert_eq!(dist[goal_i], 2);

    let path = k7_extract_path_3d(width, height, layers, &prev, start, goal).expect("path");
    assert_eq!(path.first().copied(), Some(start));
    assert_eq!(path.last().copied(), Some(goal));
    assert!(path.iter().all(|p| p.layer == 0));
}

#[test]
fn k6_dial_3d_diag_disallows_corner_cutting() {
    // Single-layer 3D variant should match the 2D corner-cut prohibition.
    let width = 2usize;
    let height = 2usize;
    let layers = 1usize;
    let n2 = width * height;
    let n = layers * n2;
    let mut blocked = vec![false; n];
    let cost = vec![0u16; n];

    let start = Point3 { layer: 0, x: 0, y: 0 };
    let goal = Point3 { layer: 0, x: 1, y: 1 };
    let idx = |x: usize, y: usize| -> usize { y * width + x };
    blocked[idx(1, 0)] = true;
    blocked[idx(0, 1)] = true;

    let goal_i = goal.layer * n2 + goal.y * width + goal.x;
    let (dist, _) = k6_wavefront_dial_3d_diag(
        width,
        height,
        layers,
        &blocked,
        &cost,
        start,
        0,
        0,
    );
    assert_eq!(dist[goal_i], u32::MAX);
}
