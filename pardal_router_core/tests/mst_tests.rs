use pardal_router_core::mst::mst_manhattan;
use pardal_router_core::router::Point;

#[test]
fn mst_empty_and_singleton() {
    assert!(mst_manhattan(&[]).is_empty());
    assert!(mst_manhattan(&[Point { x: 0, y: 0 }]).is_empty());
}

#[test]
fn mst_three_points_is_deterministic() {
    let pts = vec![Point { x: 0, y: 0 }, Point { x: 10, y: 0 }, Point { x: 10, y: 10 }];
    let e1 = mst_manhattan(&pts);
    let e2 = mst_manhattan(&pts);
    assert_eq!(e1, e2);
    assert_eq!(e1.len(), 2);
}

#[test]
fn mst_prefers_shortest_edges() {
    // A square: MST should be 3 edges of length 10 (no diagonals needed).
    let pts = vec![
        Point { x: 0, y: 0 },
        Point { x: 10, y: 0 },
        Point { x: 10, y: 10 },
        Point { x: 0, y: 10 },
    ];
    let edges = mst_manhattan(&pts);
    assert_eq!(edges.len(), 3);

    let dist = |(a, b): (usize, usize)| -> u32 {
        pts[a].x.abs_diff(pts[b].x) as u32 + pts[a].y.abs_diff(pts[b].y) as u32
    };
    let total: u32 = edges.iter().copied().map(dist).sum();
    assert_eq!(total, 30);
}

