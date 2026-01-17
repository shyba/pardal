use std::collections::VecDeque;

use crate::ir::RoutingIr;
use crate::router::Point3;

/// Find candidate escape points on the boundary of a pad region.
///
/// Inputs
/// - `start`: must be a cell inside the pad region (`pad_owner == net_id`) on some layer.
/// - `max_pad_cells`: bounds the BFS over pad cells to keep this deterministic and fast.
///
/// Output
/// - A de-duplicated, deterministic list of `(layer, x, y)` points that are adjacent (4-neighborhood)
///   to the pad region and are not occupied by other nets.
///
/// Notes
/// - This is a routing-oriented abstraction: pads are already stamped (often with clearance) into
///   `pad_owner` by DSN→IR conversion, so the boundary candidates tend to land near the legal
///   “first routing point” outside the pad keepout halo.
pub fn pad_boundary_escape_points(ir: &RoutingIr, start: Point3, net_id: u32, max_pad_cells: usize) -> Vec<Point3> {
    if ir.pad_owner.len() != ir.occ.len() {
        return Vec::new();
    }
    if start.layer >= ir.layers || start.x >= ir.width || start.y >= ir.height {
        return Vec::new();
    }
    if ir.get_pad_owner(start.layer, start.x, start.y) != net_id {
        return Vec::new();
    }

    let w = ir.width;
    let h = ir.height;
    let mut visited: Vec<bool> = vec![false; w * h];
    let mut q: VecDeque<(usize, usize)> = VecDeque::new();
    q.push_back((start.x, start.y));
    visited[start.y * w + start.x] = true;

    let mut candidates: Vec<(usize, usize)> = Vec::new();
    let mut cand_mark: Vec<bool> = vec![false; w * h];

    let mut pad_cells = 0usize;
    while let Some((x, y)) = q.pop_front() {
        pad_cells += 1;
        if max_pad_cells > 0 && pad_cells > max_pad_cells {
            break;
        }
        let neigh = [
            (x.wrapping_sub(1), y, x > 0),
            (x + 1, y, x + 1 < w),
            (x, y.wrapping_sub(1), y > 0),
            (x, y + 1, y + 1 < h),
        ];
        for (nx, ny, ok) in neigh {
            if !ok {
                continue;
            }
            let idx = ny * w + nx;
            let po = ir.get_pad_owner(start.layer, nx, ny);
            if po == net_id {
                if !visited[idx] {
                    visited[idx] = true;
                    q.push_back((nx, ny));
                }
                continue;
            }

            let occ = ir.get_occ(start.layer, nx, ny);
            if occ != 0 && occ != net_id {
                continue;
            }

            if !cand_mark[idx] {
                cand_mark[idx] = true;
                candidates.push((nx, ny));
            }
        }
    }

    candidates.sort_by(|a, b| {
        let da = (a.0.abs_diff(start.x) + a.1.abs_diff(start.y)) as u64;
        let db = (b.0.abs_diff(start.x) + b.1.abs_diff(start.y)) as u64;
        da.cmp(&db).then_with(|| a.1.cmp(&b.1)).then_with(|| a.0.cmp(&b.0))
    });

    candidates
        .into_iter()
        .map(|(x, y)| Point3 {
            layer: start.layer,
            x,
            y,
        })
        .collect()
}

