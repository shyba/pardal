use crate::ir::RoutingIr;
use crate::kernels::k6_wavefront_bfs_3d_diag_to_goals;
use crate::router::Point3;

/// Returns the subset of `goals` that are unreachable from `start` under the current occupancy,
/// using the same 3D diagonal connectivity semantics as the Python router:
/// - 8-neighborhood per layer (no corner-cutting)
/// - via transitions between adjacent layers at the same `(x, y)`
pub fn unreachable_goals_diag(
    ir: &RoutingIr,
    start: Point3,
    goals: &[Point3],
    blocked_value: u32,
) -> Vec<Point3> {
    let (dist, _) = k6_wavefront_bfs_3d_diag_to_goals(ir, start, goals, blocked_value);
    let w = ir.width;
    let h = ir.height;
    let n2 = w * h;

    goals
        .iter()
        .copied()
        .filter(|g| {
            if g.layer >= ir.layers || g.x >= w || g.y >= h {
                return true;
            }
            let gi = g.layer * n2 + g.y * w + g.x;
            dist[gi] == u32::MAX
        })
        .collect()
}

