use crate::router::Point;

/// Deterministic Prim-style MST using Manhattan distance.
///
/// Returns edges as `(u, v)` indices into `points`, where `u < v` for stability.
pub fn mst_manhattan(points: &[Point]) -> Vec<(usize, usize)> {
    let n = points.len();
    if n <= 1 {
        return Vec::new();
    }

    let mut in_tree = vec![false; n];
    let mut best_cost = vec![u32::MAX; n];
    let mut best_parent = vec![usize::MAX; n];

    // Deterministic seed: point 0.
    best_cost[0] = 0;

    let mut edges: Vec<(usize, usize)> = Vec::with_capacity(n - 1);

    for _ in 0..n {
        // Pick the next node: minimal cost, tie-break by lowest index.
        let mut u = None;
        for i in 0..n {
            if in_tree[i] {
                continue;
            }
            match u {
                None => u = Some(i),
                Some(cur) => {
                    if best_cost[i] < best_cost[cur] || (best_cost[i] == best_cost[cur] && i < cur) {
                        u = Some(i);
                    }
                }
            }
        }
        let u = u.expect("n>0");
        in_tree[u] = true;

        if best_parent[u] != usize::MAX {
            let a = best_parent[u].min(u);
            let b = best_parent[u].max(u);
            edges.push((a, b));
        }

        // Relax all remaining nodes.
        for v in 0..n {
            if in_tree[v] {
                continue;
            }
            let du = points[u].x.abs_diff(points[v].x) as u32 + points[u].y.abs_diff(points[v].y) as u32;
            if du < best_cost[v] || (du == best_cost[v] && u < best_parent[v]) {
                best_cost[v] = du;
                best_parent[v] = u;
            }
        }
    }

    edges
}

