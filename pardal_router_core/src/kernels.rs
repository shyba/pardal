use crate::geom::{Circle, LayeredPolygon, Polygon, Rect, Via};
use crate::ir::RoutingIr;
use crate::router::{Point, Point3};

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
struct AStarState {
    f: u32,
    g: u32,
    node: u32,
}

impl Ord for AStarState {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        other
            .f
            .cmp(&self.f)
            .then_with(|| other.g.cmp(&self.g))
            .then_with(|| other.node.cmp(&self.node))
    }
}

impl PartialOrd for AStarState {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(Debug, Default, Clone)]
pub struct Dial3dScratch {
    pub dist: Vec<u32>,
    pub prev: Vec<u32>,
    pub touched: Vec<u32>,
    pub buckets: Vec<Vec<u32>>,
    heap: std::collections::BinaryHeap<AStarState>,
}

impl Dial3dScratch {
    pub fn reset_for(&mut self, n: usize, bucket_count: usize) {
        if self.dist.len() != n || self.prev.len() != n {
            self.dist = vec![u32::MAX; n];
            self.prev = vec![u32::MAX; n];
            self.touched.clear();
        } else {
            for &i_u in &self.touched {
                let i = i_u as usize;
                if i < self.dist.len() {
                    self.dist[i] = u32::MAX;
                    self.prev[i] = u32::MAX;
                }
            }
            self.touched.clear();
        }

        if self.buckets.len() != bucket_count {
            self.buckets = (0..bucket_count).map(|_| Vec::new()).collect();
        } else {
            for b in &mut self.buckets {
                b.clear();
            }
        }

        self.heap.clear();
    }

    #[inline]
    fn touch(&mut self, idx: usize) {
        if self.dist[idx] == u32::MAX {
            self.touched.push(idx as u32);
        }
    }
}

/// Dial-style Dijkstra for 3D grids (reference), owner-aware blocked rule + diagonals, using caller-provided scratch buffers.
///
/// Returns `true` if the goal was reached. On success, `scratch.prev` can be used to extract the path.
pub fn k6_wavefront_dial_3d_occ_owner_diag_to_goal_with_scratch(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    diag_extra_cost: u16,
    net_id: u32,
    bucket_count: usize,
    scratch: &mut Dial3dScratch,
) -> bool {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let bucket_count = bucket_count.max(1);
    let have_via_mask = ir.via_forbidden.len() == ir.occ.len();
    let have_pad_owner = ir.pad_owner.len() == ir.occ.len();

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
        || goal.layer >= layers
        || goal.x >= width
        || goal.y >= height
    {
        return false;
    }

    let start_i = start.layer * n2 + start.y * width + start.x;
    let start_occ = ir.occ[start_i];
    let start_pad = if have_pad_owner { ir.pad_owner[start_i] } else { 0 };
    if start_occ == blocked_value
        || (start_occ != 0 && start_occ != net_id)
        || (start_pad != 0 && start_pad != net_id)
    {
        return false;
    }
    let goal_i = goal.layer * n2 + goal.y * width + goal.x;
    let goal_occ = ir.occ[goal_i];
    let goal_pad = if have_pad_owner { ir.pad_owner[goal_i] } else { 0 };
    if goal_occ == blocked_value
        || (goal_occ != 0 && goal_occ != net_id)
        || (goal_pad != 0 && goal_pad != net_id)
    {
        return false;
    }

    scratch.reset_for(n, bucket_count);

    let mut queued: usize = 0;

    scratch.touch(start_i);
    scratch.dist[start_i] = 0;
    scratch.prev[start_i] = start_i as u32;
    scratch.buckets[0].push(start_i as u32);
    queued += 1;

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        while scratch.buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = scratch.buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if scratch.dist[cur_u] != cur_d {
            continue;
        }
        if cur_u == goal_i {
            break;
        }

        let cl = cur_u / n2;
        let rem = cur_u % n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let occ = ir.occ[ni];
            let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
            if occ == blocked_value
                || (occ != 0 && occ != net_id)
                || (pad != 0 && pad != net_id)
            {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < scratch.dist[ni] {
                scratch.touch(ni);
                scratch.dist[ni] = nd;
                scratch.prev[ni] = cur;
                scratch.buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let adj1 = cl * n2 + (cy as usize) * width + nxu;
            let adj2 = cl * n2 + nyu * width + (cx as usize);
            let occ_adj1 = ir.occ[adj1];
            let occ_adj2 = ir.occ[adj2];
            let pad_adj1 = if have_pad_owner { ir.pad_owner[adj1] } else { 0 };
            let pad_adj2 = if have_pad_owner { ir.pad_owner[adj2] } else { 0 };
            if occ_adj1 == blocked_value
                || (occ_adj1 != 0 && occ_adj1 != net_id)
                || occ_adj2 == blocked_value
                || (occ_adj2 != 0 && occ_adj2 != net_id)
                || (pad_adj1 != 0 && pad_adj1 != net_id)
                || (pad_adj2 != 0 && pad_adj2 != net_id)
            {
                continue;
            }
            let occ = ir.occ[ni];
            let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
            if occ == blocked_value
                || (occ != 0 && occ != net_id)
                || (pad != 0 && pad != net_id)
            {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32 + (diag_extra_cost as u32);
            let nd = cur_d.saturating_add(step);
            if nd < scratch.dist[ni] {
                scratch.touch(ni);
                scratch.dist[ni] = nd;
                scratch.prev[ni] = cur;
                scratch.buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        if via_cost > 0 {
            let via_step = via_cost as u32;
            if cl > 0 {
                let ni = (cl - 1) * n2 + rem;
                let occ = ir.occ[ni];
                let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
                if occ != blocked_value
                    && (occ == 0 || occ == net_id)
                    && (pad == 0 || pad == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < scratch.dist[ni] {
                        scratch.touch(ni);
                        scratch.dist[ni] = nd;
                        scratch.prev[ni] = cur;
                        scratch.buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let ni = (cl + 1) * n2 + rem;
                let occ = ir.occ[ni];
                let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
                if occ != blocked_value
                    && (occ == 0 || occ == net_id)
                    && (pad == 0 || pad == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < scratch.dist[ni] {
                        scratch.touch(ni);
                        scratch.dist[ni] = nd;
                        scratch.prev[ni] = cur;
                        scratch.buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    scratch.dist[goal_i] != u32::MAX
}

/// A*-style Dijkstra for 3D grids (reference), owner-aware blocked rule + diagonals, using caller-provided scratch buffers.
///
/// The heuristic is Manhattan distance in XY (unit per step) plus a lower bound on required layer
/// transitions (`abs(dl) * via_cost`). This is admissible and drastically reduces exploration on large boards.
///
/// Returns `true` if the goal was reached. On success, `scratch.prev` can be used to extract the path.
pub fn k6_a_star_3d_occ_owner_diag_to_goal_with_scratch(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    layer_h_costs: &[u16],
    layer_v_costs: &[u16],
    layer_d_costs: &[u16],
    via_cost: u16,
    diag_extra_cost: u16,
    net_id: u32,
    scratch: &mut Dial3dScratch,
) -> bool {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let have_via_mask = ir.via_forbidden.len() == ir.occ.len();
    let have_pad_owner = ir.pad_owner.len() == ir.occ.len();
    let have_dir_costs =
        layer_h_costs.len() == layers && layer_v_costs.len() == layers && layer_d_costs.len() == layers;

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
        || goal.layer >= layers
        || goal.x >= width
        || goal.y >= height
    {
        return false;
    }

    let start_i = start.layer * n2 + start.y * width + start.x;
    let start_occ = ir.occ[start_i];
    let start_pad = if have_pad_owner { ir.pad_owner[start_i] } else { 0 };
    if start_occ == blocked_value
        || (start_occ != 0 && start_occ != net_id)
        || (start_pad != 0 && start_pad != net_id)
    {
        return false;
    }
    let goal_i = goal.layer * n2 + goal.y * width + goal.x;
    let goal_occ = ir.occ[goal_i];
    let goal_pad = if have_pad_owner { ir.pad_owner[goal_i] } else { 0 };
    if goal_occ == blocked_value
        || (goal_occ != 0 && goal_occ != net_id)
        || (goal_pad != 0 && goal_pad != net_id)
    {
        return false;
    }

    scratch.reset_for(n, 1);

    let gx = goal.x;
    let gy = goal.y;
    let gl = goal.layer;
    let via_cost_u = via_cost as u32;
    let h = |x: usize, y: usize, layer: usize| -> u32 {
        let dx = if gx >= x { (gx - x) as u32 } else { (x - gx) as u32 };
        let dy = if gy >= y { (gy - y) as u32 } else { (y - gy) as u32 };
        let dl = if gl >= layer {
            (gl - layer) as u32
        } else {
            (layer - gl) as u32
        };
        dx + dy + dl.saturating_mul(via_cost_u)
    };

    scratch.heap.clear();

    scratch.touch(start_i);
    scratch.dist[start_i] = 0;
    scratch.prev[start_i] = start_i as u32;
    scratch.heap.push(AStarState {
        f: h(start.x, start.y, start.layer),
        g: 0,
        node: start_i as u32,
    });

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];

    while let Some(state) = scratch.heap.pop() {
        let cur = state.node;
        let cur_u = cur as usize;
        if state.g != scratch.dist[cur_u] {
            continue;
        }
        if cur_u == goal_i {
            break;
        }

        let cl = cur_u / n2;
        let rem = cur_u % n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let occ = ir.occ[ni];
            let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
            if occ == blocked_value
                || (occ != 0 && occ != net_id)
                || (pad != 0 && pad != net_id)
            {
                continue;
            }
            let dir = if have_dir_costs {
                if dx != 0 {
                    layer_h_costs[cl] as u32
                } else {
                    layer_v_costs[cl] as u32
                }
            } else {
                0
            };
            let step = 1u32 + cost_field[ni] as u32 + dir;
            let ng = state.g.saturating_add(step);
            if ng < scratch.dist[ni] {
                scratch.touch(ni);
                scratch.dist[ni] = ng;
                scratch.prev[ni] = cur;
                let nf = ng.saturating_add(h(nxu, nyu, cl));
                scratch.heap.push(AStarState {
                    f: nf,
                    g: ng,
                    node: ni as u32,
                });
            }
        }

        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let adj1 = cl * n2 + (cy as usize) * width + nxu;
            let adj2 = cl * n2 + nyu * width + (cx as usize);
            let occ_adj1 = ir.occ[adj1];
            let occ_adj2 = ir.occ[adj2];
            let pad_adj1 = if have_pad_owner { ir.pad_owner[adj1] } else { 0 };
            let pad_adj2 = if have_pad_owner { ir.pad_owner[adj2] } else { 0 };
            if occ_adj1 == blocked_value
                || (occ_adj1 != 0 && occ_adj1 != net_id)
                || occ_adj2 == blocked_value
                || (occ_adj2 != 0 && occ_adj2 != net_id)
                || (pad_adj1 != 0 && pad_adj1 != net_id)
                || (pad_adj2 != 0 && pad_adj2 != net_id)
            {
                continue;
            }
            let occ = ir.occ[ni];
            let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
            if occ == blocked_value
                || (occ != 0 && occ != net_id)
                || (pad != 0 && pad != net_id)
            {
                continue;
            }
            let dir = if have_dir_costs {
                layer_d_costs[cl] as u32
            } else {
                0
            };
            let step = 1u32 + cost_field[ni] as u32 + (diag_extra_cost as u32) + dir;
            let ng = state.g.saturating_add(step);
            if ng < scratch.dist[ni] {
                scratch.touch(ni);
                scratch.dist[ni] = ng;
                scratch.prev[ni] = cur;
                let nf = ng.saturating_add(h(nxu, nyu, cl));
                scratch.heap.push(AStarState {
                    f: nf,
                    g: ng,
                    node: ni as u32,
                });
            }
        }

        if via_cost > 0 {
            let via_step = via_cost as u32;
            if cl > 0 {
                let ni = (cl - 1) * n2 + rem;
                let occ = ir.occ[ni];
                let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
                if occ != blocked_value
                    && (occ == 0 || occ == net_id)
                    && (pad == 0 || pad == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let ng = state.g.saturating_add(via_step);
                    if ng < scratch.dist[ni] {
                        scratch.touch(ni);
                        scratch.dist[ni] = ng;
                        scratch.prev[ni] = cur;
                        let nf = ng.saturating_add(h(rem % width, rem / width, cl - 1));
                        scratch.heap.push(AStarState {
                            f: nf,
                            g: ng,
                            node: ni as u32,
                        });
                    }
                }
            }
            if cl + 1 < layers {
                let ni = (cl + 1) * n2 + rem;
                let occ = ir.occ[ni];
                let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
                if occ != blocked_value
                    && (occ == 0 || occ == net_id)
                    && (pad == 0 || pad == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let ng = state.g.saturating_add(via_step);
                    if ng < scratch.dist[ni] {
                        scratch.touch(ni);
                        scratch.dist[ni] = ng;
                        scratch.prev[ni] = cur;
                        let nf = ng.saturating_add(h(rem % width, rem / width, cl + 1));
                        scratch.heap.push(AStarState {
                            f: nf,
                            g: ng,
                            node: ni as u32,
                        });
                    }
                }
            }
        }
    }

    scratch.dist[goal_i] != u32::MAX
}

/// A* variant that treats other nets' traces as *soft* obstacles.
///
/// Blocked rule (hard obstacles):
/// - `occ == blocked_value`
/// - `pad_owner != 0 && pad_owner != net_id` (other nets' pads are never crossable)
///
/// Soft rule:
/// - Any other `occ != 0 && occ != net_id` is allowed but incurs `other_net_penalty` per step.
///
/// Start/goal are still required to be free (or owned by `net_id`) in `occ`, to avoid “starting inside”
/// another net’s routed copper.
pub fn k6_a_star_3d_occ_owner_diag_soft_to_goal_with_scratch(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    layer_h_costs: &[u16],
    layer_v_costs: &[u16],
    layer_d_costs: &[u16],
    via_cost: u16,
    diag_extra_cost: u16,
    other_net_penalty: u16,
    net_id: u32,
    scratch: &mut Dial3dScratch,
) -> bool {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let have_via_mask = ir.via_forbidden.len() == ir.occ.len();
    let have_pad_owner = ir.pad_owner.len() == ir.occ.len();
    let have_dir_costs =
        layer_h_costs.len() == layers && layer_v_costs.len() == layers && layer_d_costs.len() == layers;

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
        || goal.layer >= layers
        || goal.x >= width
        || goal.y >= height
    {
        return false;
    }

    let start_i = start.layer * n2 + start.y * width + start.x;
    let start_occ = ir.occ[start_i];
    let start_pad = if have_pad_owner { ir.pad_owner[start_i] } else { 0 };
    if start_occ == blocked_value
        || (start_occ != 0 && start_occ != net_id)
        || (start_pad != 0 && start_pad != net_id)
    {
        return false;
    }
    let goal_i = goal.layer * n2 + goal.y * width + goal.x;
    let goal_occ = ir.occ[goal_i];
    let goal_pad = if have_pad_owner { ir.pad_owner[goal_i] } else { 0 };
    if goal_occ == blocked_value
        || (goal_occ != 0 && goal_occ != net_id)
        || (goal_pad != 0 && goal_pad != net_id)
    {
        return false;
    }

    scratch.reset_for(n, 1);

    let gx = goal.x;
    let gy = goal.y;
    let gl = goal.layer;
    let via_cost_u = via_cost as u32;
    let h = |x: usize, y: usize, layer: usize| -> u32 {
        let dx = if gx >= x { (gx - x) as u32 } else { (x - gx) as u32 };
        let dy = if gy >= y { (gy - y) as u32 } else { (y - gy) as u32 };
        let dl = if gl >= layer {
            (gl - layer) as u32
        } else {
            (layer - gl) as u32
        };
        dx + dy + dl.saturating_mul(via_cost_u)
    };

    scratch.heap.clear();

    scratch.touch(start_i);
    scratch.dist[start_i] = 0;
    scratch.prev[start_i] = start_i as u32;
    scratch.heap.push(AStarState {
        f: h(start.x, start.y, start.layer),
        g: 0,
        node: start_i as u32,
    });

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];
    let other_net_penalty_u = other_net_penalty as u32;

    while let Some(state) = scratch.heap.pop() {
        let cur = state.node;
        let cur_u = cur as usize;
        if state.g != scratch.dist[cur_u] {
            continue;
        }
        if cur_u == goal_i {
            break;
        }

        let cl = cur_u / n2;
        let rem = cur_u % n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let occ = ir.occ[ni];
            let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
            if occ == blocked_value || (pad != 0 && pad != net_id) {
                continue;
            }
            let dir = if have_dir_costs {
                if dx != 0 {
                    layer_h_costs[cl] as u32
                } else {
                    layer_v_costs[cl] as u32
                }
            } else {
                0
            };
            let mut step = 1u32 + cost_field[ni] as u32 + dir;
            if occ != 0 && occ != net_id {
                step = step.saturating_add(other_net_penalty_u);
            }
            let ng = state.g.saturating_add(step);
            if ng < scratch.dist[ni] {
                scratch.touch(ni);
                scratch.dist[ni] = ng;
                scratch.prev[ni] = cur;
                let nf = ng.saturating_add(h(nxu, nyu, cl));
                scratch.heap.push(AStarState {
                    f: nf,
                    g: ng,
                    node: ni as u32,
                });
            }
        }

        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let adj1 = cl * n2 + (cy as usize) * width + nxu;
            let adj2 = cl * n2 + nyu * width + (cx as usize);
            let occ_adj1 = ir.occ[adj1];
            let occ_adj2 = ir.occ[adj2];
            let pad_adj1 = if have_pad_owner { ir.pad_owner[adj1] } else { 0 };
            let pad_adj2 = if have_pad_owner { ir.pad_owner[adj2] } else { 0 };
            if occ_adj1 == blocked_value
                || occ_adj2 == blocked_value
                || (pad_adj1 != 0 && pad_adj1 != net_id)
                || (pad_adj2 != 0 && pad_adj2 != net_id)
            {
                continue;
            }
            let occ = ir.occ[ni];
            let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
            if occ == blocked_value || (pad != 0 && pad != net_id) {
                continue;
            }
            let dir = if have_dir_costs {
                layer_d_costs[cl] as u32
            } else {
                0
            };
            let mut step = 1u32 + cost_field[ni] as u32 + (diag_extra_cost as u32) + dir;
            if occ != 0 && occ != net_id {
                step = step.saturating_add(other_net_penalty_u);
            }
            let ng = state.g.saturating_add(step);
            if ng < scratch.dist[ni] {
                scratch.touch(ni);
                scratch.dist[ni] = ng;
                scratch.prev[ni] = cur;
                let nf = ng.saturating_add(h(nxu, nyu, cl));
                scratch.heap.push(AStarState {
                    f: nf,
                    g: ng,
                    node: ni as u32,
                });
            }
        }

        if via_cost > 0 {
            let via_step_base = via_cost as u32;
            if cl > 0 {
                let ni = (cl - 1) * n2 + rem;
                let occ = ir.occ[ni];
                let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
                if occ != blocked_value
                    && (pad == 0 || pad == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let mut via_step = via_step_base;
                    if occ != 0 && occ != net_id {
                        via_step = via_step.saturating_add(other_net_penalty_u);
                    }
                    let ng = state.g.saturating_add(via_step);
                    if ng < scratch.dist[ni] {
                        scratch.touch(ni);
                        scratch.dist[ni] = ng;
                        scratch.prev[ni] = cur;
                        let nf = ng.saturating_add(h(rem % width, rem / width, cl - 1));
                        scratch.heap.push(AStarState {
                            f: nf,
                            g: ng,
                            node: ni as u32,
                        });
                    }
                }
            }
            if cl + 1 < layers {
                let ni = (cl + 1) * n2 + rem;
                let occ = ir.occ[ni];
                let pad = if have_pad_owner { ir.pad_owner[ni] } else { 0 };
                if occ != blocked_value
                    && (pad == 0 || pad == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let mut via_step = via_step_base;
                    if occ != 0 && occ != net_id {
                        via_step = via_step.saturating_add(other_net_penalty_u);
                    }
                    let ng = state.g.saturating_add(via_step);
                    if ng < scratch.dist[ni] {
                        scratch.touch(ni);
                        scratch.dist[ni] = ng;
                        scratch.prev[ni] = cur;
                        let nf = ng.saturating_add(h(rem % width, rem / width, cl + 1));
                        scratch.heap.push(AStarState {
                            f: nf,
                            g: ng,
                            node: ni as u32,
                        });
                    }
                }
            }
        }
    }

    scratch.dist[goal_i] != u32::MAX
}

/// K0-like stamping kernel: fill axis-aligned rectangles into the occupancy grid.
///
/// This is a scalar reference implementation intended to be replaced by SIMD and
/// later GPU compute implementations with identical semantics.
pub fn k0_rasterize_rects_occ(ir: &mut RoutingIr, layer: usize, rects: &[Rect], value: u32) {
    if layer >= ir.layers {
        return;
    }
    for r in rects {
        if r.is_empty() {
            continue;
        }
        let x0 = r.x0.min(ir.width);
        let x1 = r.x1.min(ir.width);
        let y0 = r.y0.min(ir.height);
        let y1 = r.y1.min(ir.height);
        for y in y0..y1 {
            let row = y * ir.width;
            let base = layer * ir.width * ir.height + row;
            for x in x0..x1 {
                ir.occ[base + x] = value;
            }
        }
    }
}

/// K0-like stamping kernel: fill circles into the occupancy grid.
///
/// The circle is defined in grid coordinates and uses `dx^2 + dy^2 <= r^2`.
pub fn k0_rasterize_circles_occ(ir: &mut RoutingIr, layer: usize, circles: &[Circle], value: u32) {
    if layer >= ir.layers {
        return;
    }
    let w = ir.width as isize;
    let h = ir.height as isize;

    // Precompute scanline extents per unique radius to avoid per-circle sqrt.
    let mut radius_lut: std::collections::HashMap<usize, Vec<isize>> = std::collections::HashMap::new();
    for c in circles {
        if c.r == 0 {
            continue;
        }
        radius_lut.entry(c.r).or_insert_with(|| {
            let r = c.r as i64;
            let r2 = r * r;
            let mut dx = r;
            let mut lims: Vec<isize> = Vec::with_capacity((r as usize) + 1);
            for dy_u in 0..=(r as usize) {
                let dy = dy_u as i64;
                let dy2 = dy * dy;
                while dx > 0 && (dx * dx + dy2) > r2 {
                    dx -= 1;
                }
                lims.push(dx as isize);
            }
            lims
        });
    }

    for c in circles {
        let cx = c.center.x as isize;
        let cy = c.center.y as isize;
        let r = c.r as isize;
        if r == 0 {
            if cx >= 0 && cy >= 0 && cx < w && cy < h {
                let row = (cy as usize) * ir.width;
                let base = layer * ir.width * ir.height + row;
                ir.occ[base + (cx as usize)] = value;
            }
            continue;
        }
        if r < 0 {
            continue;
        }
        let lims = match radius_lut.get(&(c.r)) {
            Some(v) => v,
            None => continue,
        };

        let y0 = (cy - r).max(0);
        let y1 = (cy + r).min(h - 1);

        for y in y0..=y1 {
            let dy = (y - cy).abs() as usize;
            if dy >= lims.len() {
                continue;
            }
            let dx_lim = lims[dy];
            let x0 = (cx - dx_lim).max(0);
            let x1 = (cx + dx_lim).min(w - 1);

            let row = (y as usize) * ir.width;
            let base = layer * ir.width * ir.height + row;
            for x in x0..=x1 {
                ir.occ[base + (x as usize)] = value;
            }
        }
    }
}

/// K0-like stamping kernel: fill simple polygons into the occupancy grid using an even-odd rule.
///
/// - `Polygon` vertices are in grid coordinates.
/// - Uses scanlines at `y + 0.5` and fills cells whose centers lie inside.
pub fn k0_rasterize_polygon_fill_occ(ir: &mut RoutingIr, layer: usize, polys: &[Polygon], value: u32) {
    if layer >= ir.layers {
        return;
    }
    let w = ir.width as isize;
    let h = ir.height as isize;
    if w <= 0 || h <= 0 {
        return;
    }

    for poly in polys {
        if poly.vertices.len() < 3 {
            continue;
        }
        let mut xs: Vec<f64> = Vec::new();
        for y in 0..(h as usize) {
            xs.clear();
            let scan_y = (y as f64) + 0.5;
            for i in 0..poly.vertices.len() {
                let p0 = poly.vertices[i];
                let p1 = poly.vertices[(i + 1) % poly.vertices.len()];
                let (x0, y0) = (p0.x as f64, p0.y as f64);
                let (x1, y1) = (p1.x as f64, p1.y as f64);
                if (y1 - y0).abs() < f64::EPSILON {
                    continue;
                }
                let ymin = y0.min(y1);
                let ymax = y0.max(y1);
                if scan_y < ymin || scan_y >= ymax {
                    continue;
                }
                let t = (scan_y - y0) / (y1 - y0);
                let x = x0 + t * (x1 - x0);
                xs.push(x);
            }
            if xs.len() < 2 {
                continue;
            }
            xs.sort_by(|a, b| a.total_cmp(b));
            let row = y * ir.width;
            let base = layer * ir.width * ir.height + row;

            for pair in xs.chunks_exact(2) {
                let mut xl = pair[0];
                let mut xr = pair[1];
                if xl > xr {
                    std::mem::swap(&mut xl, &mut xr);
                }
                let mut start = (xl - 0.5).ceil() as isize;
                let mut end = (xr - 0.5).floor() as isize;
                if end < start {
                    continue;
                }
                start = start.max(0);
                end = end.min(w - 1);
                if end < start {
                    continue;
                }
                for x in start..=end {
                    ir.occ[base + (x as usize)] = value;
                }
            }
        }
    }
}

pub fn k0_rasterize_layered_polygons_occ(
    ir: &mut RoutingIr,
    polys: &[LayeredPolygon],
    value: u32,
) {
    if polys.is_empty() {
        return;
    }
    let mut by_layer: std::collections::HashMap<usize, Vec<Polygon>> =
        std::collections::HashMap::new();
    for lp in polys {
        if lp.layer >= ir.layers {
            continue;
        }
        by_layer.entry(lp.layer).or_default().push(lp.polygon.clone());
    }
    for (layer, ps) in by_layer {
        k0_rasterize_polygon_fill_occ(ir, layer, &ps, value);
    }
}

pub fn k0_rasterize_vias_occ(ir: &mut RoutingIr, vias: &[Via], value: u32) {
    if vias.is_empty() {
        return;
    }
    let mut circles_by_layer: std::collections::HashMap<usize, Vec<Circle>> =
        std::collections::HashMap::new();
    for via in vias {
        for &layer in &via.layers {
            if layer >= ir.layers {
                continue;
            }
            circles_by_layer
                .entry(layer)
                .or_default()
                .push(Circle::new(via.center, via.r));
        }
    }
    for (layer, circles) in circles_by_layer {
        k0_rasterize_circles_occ(ir, layer, &circles, value);
    }
}

/// K3-like clearance precompute: Manhattan distance-to-obstacle for a single layer.
///
/// - `blocked_value` identifies obstacles in `occ`.
/// - Returns a flat `width*height` buffer of distances in grid cells.
///
/// This is a scalar reference implementation; later versions may implement
/// chamfer/EDT approximations for speed while preserving conservative semantics.
pub fn k3_clearance_distance_manhattan(ir: &RoutingIr, layer: usize, blocked_value: u32) -> Vec<u16> {
    if layer >= ir.layers {
        return Vec::new();
    }
    let w = ir.width;
    let h = ir.height;
    let n = w * h;
    let mut dist = vec![u16::MAX; n];
    let mut q: std::collections::VecDeque<usize> = std::collections::VecDeque::new();

    for y in 0..h {
        for x in 0..w {
            if ir.get_occ(layer, x, y) == blocked_value {
                let i = y * w + x;
                dist[i] = 0;
                q.push_back(i);
            }
        }
    }

    let dirs: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    while let Some(cur) = q.pop_front() {
        let cx = (cur % w) as isize;
        let cy = (cur / w) as isize;
        let cd = dist[cur];
        if cd == u16::MAX {
            continue;
        }
        let nd = cd.saturating_add(1);
        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= w || nyu >= h {
                continue;
            }
            let ni = nyu * w + nxu;
            if nd < dist[ni] {
                dist[ni] = nd;
                q.push_back(ni);
            }
        }
    }

    dist
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Conflict {
    pub layer: usize,
    pub x: usize,
    pub y: usize,
    pub existing: u32,
    pub attempted: u32,
}

/// K9/K10-like commit kernel: attempts to write a path into occupancy.
///
/// Semantics:
/// - If a cell is `0` (free), it is set to `net_id`.
/// - If a cell is already `net_id`, it is left unchanged.
/// - Otherwise, the commit reports a conflict and leaves the cell unchanged.
pub fn k9_commit_path_occ(
    ir: &mut RoutingIr,
    layer: usize,
    points: &[Point],
    net_id: u32,
) -> Vec<Conflict> {
    if layer >= ir.layers {
        return Vec::new();
    }
    let have_pad_owner = ir.pad_owner.len() == ir.occ.len();
    let mut conflicts: Vec<Conflict> = Vec::new();
    for p in points {
        if p.x >= ir.width || p.y >= ir.height {
            continue;
        }
        let idx = ir.idx(layer, p.x, p.y);
        if have_pad_owner {
            let pad = ir.pad_owner[idx];
            if pad != 0 && pad != net_id {
                conflicts.push(Conflict {
                    layer,
                    x: p.x,
                    y: p.y,
                    existing: pad,
                    attempted: net_id,
                });
                continue;
            }
        }
        let existing = ir.occ[idx];
        if existing == 0 || existing == net_id {
            ir.occ[idx] = net_id;
        } else {
            conflicts.push(Conflict {
                layer,
                x: p.x,
                y: p.y,
                existing,
                attempted: net_id,
            });
        }
    }
    conflicts
}

/// K13-like uncommit kernel: clears all cells owned by `net_id` on a layer.
pub fn k13_uncommit_net_occ(ir: &mut RoutingIr, layer: usize, net_id: u32) {
    if layer >= ir.layers {
        return;
    }
    let base = layer * ir.width * ir.height;
    let end = base + ir.width * ir.height;
    for v in &mut ir.occ[base..end] {
        if *v == net_id {
            *v = 0;
        }
    }
}

/// K9/K10-like commit kernel for 3D point paths.
///
/// Semantics match `k9_commit_path_occ`, but each point commits into its own layer.
pub fn k9_commit_path_occ_3d(ir: &mut RoutingIr, points: &[Point3], net_id: u32) -> Vec<Conflict> {
    fn via_coords(points: &[Point3]) -> Vec<(usize, usize)> {
        let mut out: Vec<(usize, usize)> = Vec::new();
        for w in points.windows(2) {
            let a = w[0];
            let b = w[1];
            if a.x == b.x && a.y == b.y && a.layer != b.layer {
                out.push((a.x, a.y));
            }
        }
        out.sort_unstable();
        out.dedup();
        out
    }

    let have_pad_owner = ir.pad_owner.len() == ir.occ.len();
    let mut conflicts: Vec<Conflict> = Vec::new();
    for p in points {
        if p.layer >= ir.layers || p.x >= ir.width || p.y >= ir.height {
            continue;
        }
        let idx = ir.idx(p.layer, p.x, p.y);
        if have_pad_owner {
            let pad = ir.pad_owner[idx];
            if pad != 0 && pad != net_id {
                conflicts.push(Conflict {
                    layer: p.layer,
                    x: p.x,
                    y: p.y,
                    existing: pad,
                    attempted: net_id,
                });
                continue;
            }
        }
        let existing = ir.occ[idx];
        if existing == 0 || existing == net_id {
            ir.occ[idx] = net_id;
        } else {
            conflicts.push(Conflict {
                layer: p.layer,
                x: p.x,
                y: p.y,
                existing,
                attempted: net_id,
            });
        }
    }

    // DSN padstacks for vias are typically through-hole (shapes on all signal layers). When the
    // routed path changes layers at an `(x, y)`, model that as a through via occupying all layers.
    for (x, y) in via_coords(points) {
        if x >= ir.width || y >= ir.height {
            continue;
        }
        for layer in 0..ir.layers {
            let idx = ir.idx(layer, x, y);
            if have_pad_owner {
                let pad = ir.pad_owner[idx];
                if pad != 0 && pad != net_id {
                    conflicts.push(Conflict {
                        layer,
                        x,
                        y,
                        existing: pad,
                        attempted: net_id,
                    });
                    continue;
                }
            }
            let existing = ir.occ[idx];
            if existing == 0 || existing == net_id {
                ir.occ[idx] = net_id;
            } else {
                conflicts.push(Conflict {
                    layer,
                    x,
                    y,
                    existing,
                    attempted: net_id,
                });
            }
        }
    }
    conflicts.sort_by(|a, b| {
        (a.layer, a.x, a.y, a.existing, a.attempted).cmp(&(b.layer, b.x, b.y, b.existing, b.attempted))
    });
    conflicts.dedup();
    conflicts
}

/// Transactional commit for 3D point paths: either commits all points or commits nothing.
///
/// This is intended for negotiation/ripup loops where a failed commit must not destroy previously
/// routed parts of the same net.
pub fn k9_try_commit_path_occ_3d(
    ir: &mut RoutingIr,
    points: &[Point3],
    net_id: u32,
) -> Result<(), Vec<Conflict>> {
    fn via_coords(points: &[Point3]) -> Vec<(usize, usize)> {
        let mut out: Vec<(usize, usize)> = Vec::new();
        for w in points.windows(2) {
            let a = w[0];
            let b = w[1];
            if a.x == b.x && a.y == b.y && a.layer != b.layer {
                out.push((a.x, a.y));
            }
        }
        out.sort_unstable();
        out.dedup();
        out
    }

    let have_pad_owner = ir.pad_owner.len() == ir.occ.len();
    let mut conflicts: Vec<Conflict> = Vec::new();
    let mut idxs: Vec<usize> = Vec::with_capacity(points.len());

    for p in points {
        if p.layer >= ir.layers || p.x >= ir.width || p.y >= ir.height {
            continue;
        }
        let idx = ir.idx(p.layer, p.x, p.y);
        idxs.push(idx);

        if have_pad_owner {
            let pad = ir.pad_owner[idx];
            if pad != 0 && pad != net_id {
                conflicts.push(Conflict {
                    layer: p.layer,
                    x: p.x,
                    y: p.y,
                    existing: pad,
                    attempted: net_id,
                });
                continue;
            }
        }

        let existing = ir.occ[idx];
        if existing != 0 && existing != net_id {
            conflicts.push(Conflict {
                layer: p.layer,
                x: p.x,
                y: p.y,
                existing,
                attempted: net_id,
            });
        }
    }

    for (x, y) in via_coords(points) {
        if x >= ir.width || y >= ir.height {
            continue;
        }
        for layer in 0..ir.layers {
            let idx = ir.idx(layer, x, y);
            idxs.push(idx);

            if have_pad_owner {
                let pad = ir.pad_owner[idx];
                if pad != 0 && pad != net_id {
                    conflicts.push(Conflict {
                        layer,
                        x,
                        y,
                        existing: pad,
                        attempted: net_id,
                    });
                    continue;
                }
            }

            let existing = ir.occ[idx];
            if existing != 0 && existing != net_id {
                conflicts.push(Conflict {
                    layer,
                    x,
                    y,
                    existing,
                    attempted: net_id,
                });
            }
        }
    }

    conflicts.sort_by(|a, b| {
        (a.layer, a.x, a.y, a.existing, a.attempted).cmp(&(b.layer, b.x, b.y, b.existing, b.attempted))
    });
    conflicts.dedup();
    if !conflicts.is_empty() {
        return Err(conflicts);
    }

    // Dedup indices to avoid redundant stores.
    idxs.sort_unstable();
    idxs.dedup();
    for idx in idxs {
        ir.occ[idx] = net_id;
    }
    Ok(())
}

fn brush_offsets(radius: u8) -> Vec<(isize, isize)> {
    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum BrushShape {
        Chebyshev,
        Euclidean,
    }
    fn brush_shape() -> BrushShape {
        static SHAPE: std::sync::OnceLock<BrushShape> = std::sync::OnceLock::new();
        *SHAPE.get_or_init(|| {
            match std::env::var("PARDAL_BRUSH_SHAPE")
                .unwrap_or_else(|_| "chebyshev".to_string())
                .to_ascii_lowercase()
                .as_str()
            {
                "euclidean" | "disk" | "circle" => BrushShape::Euclidean,
                _ => BrushShape::Chebyshev,
            }
        })
    }

    let r = radius as isize;
    if r <= 0 {
        return vec![(0, 0)];
    }
    let mut out: Vec<(isize, isize)> = Vec::new();
    for dy in -r..=r {
        for dx in -r..=r {
            match brush_shape() {
                BrushShape::Chebyshev => {
                    if dx.abs().max(dy.abs()) <= r {
                        out.push((dx, dy));
                    }
                }
                BrushShape::Euclidean => {
                    if (dx * dx) + (dy * dy) <= (r * r) {
                        out.push((dx, dy));
                    }
                }
            }
        }
    }
    out
}

/// Commit a 3D path, stamping a circular brush around every path point.
///
/// This is a routing-only approximation of physical track width / clearance: we "inflate" the path
/// in `occ` so future routes see the occupied area as blocked.
pub fn k9_commit_path_occ_3d_brush(
    ir: &mut RoutingIr,
    points: &[Point3],
    net_id: u32,
    brush_radius: u8,
) -> Vec<Conflict> {
    fn via_sites(points: &[Point3]) -> Vec<(usize, usize, usize)> {
        let mut out: Vec<(usize, usize, usize)> = Vec::new();
        for w in points.windows(2) {
            let a = w[0];
            let b = w[1];
            if a.x == b.x && a.y == b.y && a.layer != b.layer {
                out.push((a.x, a.y, a.layer));
            }
        }
        out.sort_unstable();
        out.dedup();
        out
    }

    let offsets = brush_offsets(brush_radius);
    let have_pad_owner = ir.pad_owner.len() == ir.occ.len();
    let mut conflicts: Vec<Conflict> = Vec::new();
    for p in points {
        if p.layer >= ir.layers {
            continue;
        }
        let px = p.x as isize;
        let py = p.y as isize;
        for (dx, dy) in &offsets {
            let x = px + dx;
            let y = py + dy;
            if x < 0 || y < 0 {
                continue;
            }
            let (xu, yu) = (x as usize, y as usize);
            if xu >= ir.width || yu >= ir.height {
                continue;
            }
            let idx = ir.idx(p.layer, xu, yu);
            if have_pad_owner {
                let pad = ir.pad_owner[idx];
                if pad != 0 && pad != net_id {
                    // The brush is an *approximate* clearance/width inflation. Pads are already
                    // stamped (often inflated by clearance) into `pad_owner`, so treating the brush
                    // overlap as a hard conflict double-counts clearances and makes dense padfields
                    // (BGA/FPGA) effectively unroutable at coarse grid pitches.
                    //
                    // Preserve strict legality at the centerline point itself, but clip the halo.
                    if *dx == 0 && *dy == 0 {
                        conflicts.push(Conflict {
                            layer: p.layer,
                            x: xu,
                            y: yu,
                            existing: pad,
                            attempted: net_id,
                        });
                    }
                    continue;
                }
            }
            let existing = ir.occ[idx];
            if existing == 0 || existing == net_id {
                ir.occ[idx] = net_id;
            } else {
                conflicts.push(Conflict {
                    layer: p.layer,
                    x: xu,
                    y: yu,
                    existing,
                    attempted: net_id,
                });
            }
        }
    }

    // Through via stamping: apply the brush on all layers at each via coordinate.
    let mut via_in_pad: std::collections::HashMap<(usize, usize), bool> = std::collections::HashMap::new();
    if have_pad_owner {
        for (x, y, layer) in via_sites(points) {
            if x >= ir.width || y >= ir.height || layer >= ir.layers {
                continue;
            }
            if ir.pad_owner[ir.idx(layer, x, y)] == net_id {
                via_in_pad.insert((x, y), true);
            } else {
                via_in_pad.entry((x, y)).or_insert(false);
            }
        }
    } else {
        for (x, y, _layer) in via_sites(points) {
            via_in_pad.entry((x, y)).or_insert(false);
        }
    }

    for ((x, y), &in_own_pad) in &via_in_pad {
        let px = (*x) as isize;
        let py = (*y) as isize;
        for layer in 0..ir.layers {
            for (dx, dy) in &offsets {
                let xx = px + dx;
                let yy = py + dy;
                if xx < 0 || yy < 0 {
                    continue;
                }
                let (xu, yu) = (xx as usize, yy as usize);
                if xu >= ir.width || yu >= ir.height {
                    continue;
                }
                let idx = ir.idx(layer, xu, yu);
                if have_pad_owner {
                    let pad = ir.pad_owner[idx];
                    if pad != 0 && pad != net_id {
                        if in_own_pad && (*dx != 0 || *dy != 0) {
                            // When the via center is inside the net's own pad ("via-in-pad"), clip the
                            // approximate halo against other pads. The pad itself already encodes the
                            // required clearance in `pad_owner`, and double-counting the via halo makes
                            // dense BGA padfields effectively unroutable at coarse grid pitches.
                            continue;
                        }
                        conflicts.push(Conflict { layer, x: xu, y: yu, existing: pad, attempted: net_id });
                        continue;
                    }
                }
                let existing = ir.occ[idx];
                if existing == 0 || existing == net_id {
                    ir.occ[idx] = net_id;
                } else {
                    conflicts.push(Conflict {
                        layer,
                        x: xu,
                        y: yu,
                        existing,
                        attempted: net_id,
                    });
                }
            }
        }
    }
    conflicts.sort_by(|a, b| {
        (a.layer, a.x, a.y, a.existing, a.attempted).cmp(&(b.layer, b.x, b.y, b.existing, b.attempted))
    });
    conflicts.dedup();
    conflicts
}

/// Transactional commit for 3D point paths with a circular brush: either commits all points or commits nothing.
pub fn k9_try_commit_path_occ_3d_brush(
    ir: &mut RoutingIr,
    points: &[Point3],
    net_id: u32,
    brush_radius: u8,
) -> Result<(), Vec<Conflict>> {
    fn via_sites(points: &[Point3]) -> Vec<(usize, usize, usize)> {
        let mut out: Vec<(usize, usize, usize)> = Vec::new();
        for w in points.windows(2) {
            let a = w[0];
            let b = w[1];
            if a.x == b.x && a.y == b.y && a.layer != b.layer {
                out.push((a.x, a.y, a.layer));
            }
        }
        out.sort_unstable();
        out.dedup();
        out
    }

    let offsets = brush_offsets(brush_radius);
    let have_pad_owner = ir.pad_owner.len() == ir.occ.len();
    let mut conflicts: Vec<Conflict> = Vec::new();
    let mut idxs: Vec<usize> = Vec::new();

    for p in points {
        if p.layer >= ir.layers {
            continue;
        }
        let px = p.x as isize;
        let py = p.y as isize;
        for (dx, dy) in &offsets {
            let x = px + dx;
            let y = py + dy;
            if x < 0 || y < 0 {
                continue;
            }
            let (xu, yu) = (x as usize, y as usize);
            if xu >= ir.width || yu >= ir.height {
                continue;
            }
            let idx = ir.idx(p.layer, xu, yu);
            if have_pad_owner {
                let pad = ir.pad_owner[idx];
                if pad != 0 && pad != net_id {
                    if *dx == 0 && *dy == 0 {
                        conflicts.push(Conflict {
                            layer: p.layer,
                            x: xu,
                            y: yu,
                            existing: pad,
                            attempted: net_id,
                        });
                    }
                    continue;
                }
            }
            idxs.push(idx);

            let existing = ir.occ[idx];
            if existing != 0 && existing != net_id {
                conflicts.push(Conflict {
                    layer: p.layer,
                    x: xu,
                    y: yu,
                    existing,
                    attempted: net_id,
                });
            }
        }
    }

    let mut via_in_pad: std::collections::HashMap<(usize, usize), bool> = std::collections::HashMap::new();
    if have_pad_owner {
        for (x, y, layer) in via_sites(points) {
            if x >= ir.width || y >= ir.height || layer >= ir.layers {
                continue;
            }
            if ir.pad_owner[ir.idx(layer, x, y)] == net_id {
                via_in_pad.insert((x, y), true);
            } else {
                via_in_pad.entry((x, y)).or_insert(false);
            }
        }
    } else {
        for (x, y, _layer) in via_sites(points) {
            via_in_pad.entry((x, y)).or_insert(false);
        }
    }

    for ((x, y), &in_own_pad) in &via_in_pad {
        let px = (*x) as isize;
        let py = (*y) as isize;
        for layer in 0..ir.layers {
            for (dx, dy) in &offsets {
                let xx = px + dx;
                let yy = py + dy;
                if xx < 0 || yy < 0 {
                    continue;
                }
                let (xu, yu) = (xx as usize, yy as usize);
                if xu >= ir.width || yu >= ir.height {
                    continue;
                }
                let idx = ir.idx(layer, xu, yu);
                if have_pad_owner {
                    let pad = ir.pad_owner[idx];
                    if pad != 0 && pad != net_id {
                        if in_own_pad && (*dx != 0 || *dy != 0) {
                            continue;
                        }
                        conflicts.push(Conflict { layer, x: xu, y: yu, existing: pad, attempted: net_id });
                        continue;
                    }
                }
                idxs.push(idx);

                let existing = ir.occ[idx];
                if existing != 0 && existing != net_id {
                    conflicts.push(Conflict {
                        layer,
                        x: xu,
                        y: yu,
                        existing,
                        attempted: net_id,
                    });
                }
            }
        }
    }

    conflicts.sort_by(|a, b| {
        (a.layer, a.x, a.y, a.existing, a.attempted).cmp(&(b.layer, b.x, b.y, b.existing, b.attempted))
    });
    conflicts.dedup();
    if !conflicts.is_empty() {
        return Err(conflicts);
    }

    idxs.sort_unstable();
    idxs.dedup();
    for idx in idxs {
        ir.occ[idx] = net_id;
    }
    Ok(())
}

/// K13-like uncommit kernel for 3D point paths: clears all cells owned by `net_id` on all layers.
pub fn k13_uncommit_net_occ_3d(ir: &mut RoutingIr, net_id: u32) {
    for layer in 0..ir.layers {
        k13_uncommit_net_occ(ir, layer, net_id);
    }
}

/// K5/K6-like wavefront: compute BFS distances and predecessor map on a single layer.
///
/// This is the scalar reference for later bucketed wavefront variants.
pub fn k6_wavefront_bfs_2d(
    ir: &RoutingIr,
    layer: usize,
    start: Point,
    blocked_value: u32,
) -> (Vec<u32>, Vec<u32>) {
    let w = ir.width;
    let h = ir.height;
    let n = w * h;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if layer >= ir.layers || start.x >= w || start.y >= h {
        return (dist, prev);
    }
    if ir.get_occ(layer, start.x, start.y) == blocked_value {
        return (dist, prev);
    }

    let start_i = (start.y * w + start.x) as u32;
    dist[start_i as usize] = 0;
    prev[start_i as usize] = start_i;
    let mut q: std::collections::VecDeque<u32> = std::collections::VecDeque::new();
    q.push_back(start_i);

    let dirs: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    while let Some(cur) = q.pop_front() {
        let cur_u = cur as usize;
        let cx = (cur_u % w) as isize;
        let cy = (cur_u / w) as isize;
        let cd = dist[cur_u];
        let nd = cd.saturating_add(1);

        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= w || nyu >= h {
                continue;
            }
            if ir.get_occ(layer, nxu, nyu) == blocked_value {
                continue;
            }
            let ni = (nyu * w + nxu) as u32;
            let ni_u = ni as usize;
            if nd < dist[ni_u] {
                dist[ni_u] = nd;
                prev[ni_u] = cur;
                q.push_back(ni);
            }
        }
    }

    (dist, prev)
}

/// K6-like wavefront: minimal 3D Manhattan BFS with via transitions.
///
/// Semantics:
/// - 4-neighborhood moves on each layer
/// - via transitions between adjacent layers at the same `(x, y)`
/// - all moves have uniform cost (reference baseline)
pub fn k6_wavefront_bfs_3d(
    ir: &RoutingIr,
    start: Point3,
    blocked_value: u32,
) -> (Vec<u32>, Vec<u32>) {
    let w = ir.width;
    let h = ir.height;
    let layers = ir.layers;
    let n2 = w * h;
    let n = layers * n2;

    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if start.layer >= layers || start.x >= w || start.y >= h {
        return (dist, prev);
    }
    if ir.get_occ(start.layer, start.x, start.y) == blocked_value {
        return (dist, prev);
    }

    let start_i = (start.layer * n2 + start.y * w + start.x) as u32;
    dist[start_i as usize] = 0;
    prev[start_i as usize] = start_i;

    let mut q: std::collections::VecDeque<u32> = std::collections::VecDeque::new();
    q.push_back(start_i);

    let dirs: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];

    while let Some(cur) = q.pop_front() {
        let cur_u = cur as usize;
        let cl = cur_u / n2;
        let rem = cur_u - cl * n2;
        let cx = (rem % w) as isize;
        let cy = (rem / w) as isize;
        let cd = dist[cur_u];
        let nd = cd.saturating_add(1);

        // In-layer moves.
        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= w || nyu >= h {
                continue;
            }
            if ir.get_occ(cl, nxu, nyu) == blocked_value {
                continue;
            }
            let ni = (cl * n2 + nyu * w + nxu) as u32;
            let ni_u = ni as usize;
            if nd < dist[ni_u] {
                dist[ni_u] = nd;
                prev[ni_u] = cur;
                q.push_back(ni);
            }
        }

        // Via transitions (adjacent layers).
        if cl > 0 {
            let nl = cl - 1;
            if ir.get_occ(nl, cx as usize, cy as usize) != blocked_value {
                let ni = (nl * n2 + (cy as usize) * w + (cx as usize)) as u32;
                let ni_u = ni as usize;
                if nd < dist[ni_u] {
                    dist[ni_u] = nd;
                    prev[ni_u] = cur;
                    q.push_back(ni);
                }
            }
        }
        if cl + 1 < layers {
            let nl = cl + 1;
            if ir.get_occ(nl, cx as usize, cy as usize) != blocked_value {
                let ni = (nl * n2 + (cy as usize) * w + (cx as usize)) as u32;
                let ni_u = ni as usize;
                if nd < dist[ni_u] {
                    dist[ni_u] = nd;
                    prev[ni_u] = cur;
                    q.push_back(ni);
                }
            }
        }
    }

    (dist, prev)
}

/// K6-like wavefront: 3D BFS with diagonal moves (8-neighborhood per layer) and via transitions.
///
/// Semantics:
/// - 8-neighborhood moves on each layer
/// - diagonal moves are disallowed from "corner cutting": both adjacent orthogonal cells on
///   the same layer must be free (matches the Python grid/A* semantics).
/// - via transitions between adjacent layers at the same `(x, y)`
/// - all moves have uniform cost (reference baseline for connectivity)
pub fn k6_wavefront_bfs_3d_diag(
    ir: &RoutingIr,
    start: Point3,
    blocked_value: u32,
) -> (Vec<u32>, Vec<u32>) {
    let w = ir.width;
    let h = ir.height;
    let layers = ir.layers;
    let n2 = w * h;
    let n = layers * n2;

    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if start.layer >= layers || start.x >= w || start.y >= h {
        return (dist, prev);
    }
    if ir.get_occ(start.layer, start.x, start.y) == blocked_value {
        return (dist, prev);
    }

    let start_i = (start.layer * n2 + start.y * w + start.x) as u32;
    dist[start_i as usize] = 0;
    prev[start_i as usize] = start_i;

    let mut q: std::collections::VecDeque<u32> = std::collections::VecDeque::new();
    q.push_back(start_i);

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];

    while let Some(cur) = q.pop_front() {
        let cur_u = cur as usize;
        let cl = cur_u / n2;
        let rem = cur_u - cl * n2;
        let cx = (rem % w) as isize;
        let cy = (rem / w) as isize;
        let cd = dist[cur_u];
        let nd = cd.saturating_add(1);

        // Orthogonal in-layer moves.
        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= w || nyu >= h {
                continue;
            }
            if ir.get_occ(cl, nxu, nyu) == blocked_value {
                continue;
            }
            let ni = (cl * n2 + nyu * w + nxu) as u32;
            let ni_u = ni as usize;
            if nd < dist[ni_u] {
                dist[ni_u] = nd;
                prev[ni_u] = cur;
                q.push_back(ni);
            }
        }

        // Diagonal in-layer moves (no corner-cutting).
        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= w || nyu >= h {
                continue;
            }
            // Require both adjacent orth cells to be free on this layer.
            if ir.get_occ(cl, nxu, cy as usize) == blocked_value
                || ir.get_occ(cl, cx as usize, nyu) == blocked_value
            {
                continue;
            }
            if ir.get_occ(cl, nxu, nyu) == blocked_value {
                continue;
            }
            let ni = (cl * n2 + nyu * w + nxu) as u32;
            let ni_u = ni as usize;
            if nd < dist[ni_u] {
                dist[ni_u] = nd;
                prev[ni_u] = cur;
                q.push_back(ni);
            }
        }

        // Via transitions (adjacent layers).
        if cl > 0 {
            let nl = cl - 1;
            if ir.get_occ(nl, cx as usize, cy as usize) != blocked_value {
                let ni = (nl * n2 + (cy as usize) * w + (cx as usize)) as u32;
                let ni_u = ni as usize;
                if nd < dist[ni_u] {
                    dist[ni_u] = nd;
                    prev[ni_u] = cur;
                    q.push_back(ni);
                }
            }
        }
        if cl + 1 < layers {
            let nl = cl + 1;
            if ir.get_occ(nl, cx as usize, cy as usize) != blocked_value {
                let ni = (nl * n2 + (cy as usize) * w + (cx as usize)) as u32;
                let ni_u = ni as usize;
                if nd < dist[ni_u] {
                    dist[ni_u] = nd;
                    prev[ni_u] = cur;
                    q.push_back(ni);
                }
            }
        }
    }

    (dist, prev)
}

/// K6-like wavefront: 3D diagonal BFS with early exit once `goal` is reached.
pub fn k6_wavefront_bfs_3d_diag_to_goal(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
) -> (Vec<u32>, Vec<u32>) {
    let w = ir.width;
    let h = ir.height;
    let layers = ir.layers;
    let n2 = w * h;
    let n = layers * n2;

    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if start.layer >= layers
        || start.x >= w
        || start.y >= h
        || goal.layer >= layers
        || goal.x >= w
        || goal.y >= h
    {
        return (dist, prev);
    }
    if ir.get_occ(start.layer, start.x, start.y) == blocked_value {
        return (dist, prev);
    }
    if ir.get_occ(goal.layer, goal.x, goal.y) == blocked_value {
        return (dist, prev);
    }

    let start_i = (start.layer * n2 + start.y * w + start.x) as u32;
    let goal_i = (goal.layer * n2 + goal.y * w + goal.x) as usize;
    dist[start_i as usize] = 0;
    prev[start_i as usize] = start_i;

    let mut q: std::collections::VecDeque<u32> = std::collections::VecDeque::new();
    q.push_back(start_i);

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];

    while let Some(cur) = q.pop_front() {
        let cur_u = cur as usize;
        if cur_u == goal_i {
            break;
        }
        let cl = cur_u / n2;
        let rem = cur_u - cl * n2;
        let cx = (rem % w) as isize;
        let cy = (rem / w) as isize;
        let cd = dist[cur_u];
        let nd = cd.saturating_add(1);

        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= w || nyu >= h {
                continue;
            }
            if ir.get_occ(cl, nxu, nyu) == blocked_value {
                continue;
            }
            let ni = (cl * n2 + nyu * w + nxu) as u32;
            let ni_u = ni as usize;
            if nd < dist[ni_u] {
                dist[ni_u] = nd;
                prev[ni_u] = cur;
                q.push_back(ni);
            }
        }

        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= w || nyu >= h {
                continue;
            }
            if ir.get_occ(cl, nxu, cy as usize) == blocked_value
                || ir.get_occ(cl, cx as usize, nyu) == blocked_value
            {
                continue;
            }
            if ir.get_occ(cl, nxu, nyu) == blocked_value {
                continue;
            }
            let ni = (cl * n2 + nyu * w + nxu) as u32;
            let ni_u = ni as usize;
            if nd < dist[ni_u] {
                dist[ni_u] = nd;
                prev[ni_u] = cur;
                q.push_back(ni);
            }
        }

        if cl > 0 {
            let nl = cl - 1;
            if ir.get_occ(nl, cx as usize, cy as usize) != blocked_value {
                let ni = (nl * n2 + (cy as usize) * w + (cx as usize)) as u32;
                let ni_u = ni as usize;
                if nd < dist[ni_u] {
                    dist[ni_u] = nd;
                    prev[ni_u] = cur;
                    q.push_back(ni);
                }
            }
        }
        if cl + 1 < layers {
            let nl = cl + 1;
            if ir.get_occ(nl, cx as usize, cy as usize) != blocked_value {
                let ni = (nl * n2 + (cy as usize) * w + (cx as usize)) as u32;
                let ni_u = ni as usize;
                if nd < dist[ni_u] {
                    dist[ni_u] = nd;
                    prev[ni_u] = cur;
                    q.push_back(ni);
                }
            }
        }
    }

    (dist, prev)
}

/// K6-like wavefront: 3D diagonal BFS with early exit once every goal in `goals` is reached.
///
/// This is intended for connectivity queries (prove-impossible) where only terminal
/// reachability matters. The returned `dist/prev` may have `u32::MAX` for nodes that were
/// not needed to settle all goal distances.
pub fn k6_wavefront_bfs_3d_diag_to_goals(
    ir: &RoutingIr,
    start: Point3,
    goals: &[Point3],
    blocked_value: u32,
) -> (Vec<u32>, Vec<u32>) {
    let w = ir.width;
    let h = ir.height;
    let layers = ir.layers;
    let n2 = w * h;
    let n = layers * n2;

    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if start.layer >= layers || start.x >= w || start.y >= h {
        return (dist, prev);
    }
    if ir.get_occ(start.layer, start.x, start.y) == blocked_value {
        return (dist, prev);
    }

    let mut goal_indices: Vec<usize> = Vec::with_capacity(goals.len());
    for g in goals {
        if g.layer >= layers || g.x >= w || g.y >= h {
            return (dist, prev);
        }
        if ir.get_occ(g.layer, g.x, g.y) == blocked_value {
            return (dist, prev);
        }
        goal_indices.push(g.layer * n2 + g.y * w + g.x);
    }
    goal_indices.sort_unstable();
    goal_indices.dedup();
    let mut remaining = goal_indices.len();
    if remaining == 0 {
        return (dist, prev);
    }

    let start_i = (start.layer * n2 + start.y * w + start.x) as u32;
    dist[start_i as usize] = 0;
    prev[start_i as usize] = start_i;

    if goal_indices.binary_search(&(start_i as usize)).is_ok() {
        remaining -= 1;
        if remaining == 0 {
            return (dist, prev);
        }
    }

    let mut q: std::collections::VecDeque<u32> = std::collections::VecDeque::new();
    q.push_back(start_i);

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];

    while let Some(cur) = q.pop_front() {
        let cur_u = cur as usize;
        let cl = cur_u / n2;
        let rem = cur_u - cl * n2;
        let cx = (rem % w) as isize;
        let cy = (rem / w) as isize;
        let cd = dist[cur_u];
        let nd = cd.saturating_add(1);

        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= w || nyu >= h {
                continue;
            }
            if ir.get_occ(cl, nxu, nyu) == blocked_value {
                continue;
            }
            let ni = (cl * n2 + nyu * w + nxu) as u32;
            let ni_u = ni as usize;
            if nd < dist[ni_u] {
                dist[ni_u] = nd;
                prev[ni_u] = cur;
                q.push_back(ni);
                if goal_indices.binary_search(&ni_u).is_ok() {
                    remaining -= 1;
                    if remaining == 0 {
                        return (dist, prev);
                    }
                }
            }
        }

        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= w || nyu >= h {
                continue;
            }
            if ir.get_occ(cl, nxu, cy as usize) == blocked_value
                || ir.get_occ(cl, cx as usize, nyu) == blocked_value
            {
                continue;
            }
            if ir.get_occ(cl, nxu, nyu) == blocked_value {
                continue;
            }
            let ni = (cl * n2 + nyu * w + nxu) as u32;
            let ni_u = ni as usize;
            if nd < dist[ni_u] {
                dist[ni_u] = nd;
                prev[ni_u] = cur;
                q.push_back(ni);
                if goal_indices.binary_search(&ni_u).is_ok() {
                    remaining -= 1;
                    if remaining == 0 {
                        return (dist, prev);
                    }
                }
            }
        }

        if cl > 0 {
            let nl = cl - 1;
            if ir.get_occ(nl, cx as usize, cy as usize) != blocked_value {
                let ni = (nl * n2 + (cy as usize) * w + (cx as usize)) as u32;
                let ni_u = ni as usize;
                if nd < dist[ni_u] {
                    dist[ni_u] = nd;
                    prev[ni_u] = cur;
                    q.push_back(ni);
                    if goal_indices.binary_search(&ni_u).is_ok() {
                        remaining -= 1;
                        if remaining == 0 {
                            return (dist, prev);
                        }
                    }
                }
            }
        }
        if cl + 1 < layers {
            let nl = cl + 1;
            if ir.get_occ(nl, cx as usize, cy as usize) != blocked_value {
                let ni = (nl * n2 + (cy as usize) * w + (cx as usize)) as u32;
                let ni_u = ni as usize;
                if nd < dist[ni_u] {
                    dist[ni_u] = nd;
                    prev[ni_u] = cur;
                    q.push_back(ni);
                    if goal_indices.binary_search(&ni_u).is_ok() {
                        remaining -= 1;
                        if remaining == 0 {
                            return (dist, prev);
                        }
                    }
                }
            }
        }
    }

    (dist, prev)
}

/// K7-like extraction: backtrace a 3D predecessor map into a point path.
pub fn k7_extract_path_3d(
    width: usize,
    height: usize,
    layers: usize,
    prev: &[u32],
    start: Point3,
    goal: Point3,
) -> Option<Vec<Point3>> {
    if start.layer >= layers
        || goal.layer >= layers
        || start.x >= width
        || start.y >= height
        || goal.x >= width
        || goal.y >= height
    {
        return None;
    }
    let n2 = width * height;
    let n = layers * n2;
    if prev.len() != n {
        return None;
    }

    let start_i = (start.layer * n2 + start.y * width + start.x) as u32;
    let goal_i = (goal.layer * n2 + goal.y * width + goal.x) as u32;
    if prev[goal_i as usize] == u32::MAX {
        return None;
    }

    let mut out: Vec<Point3> = Vec::new();
    let mut cur = goal_i;
    loop {
        let cur_u = cur as usize;
        let cl = cur_u / n2;
        let rem = cur_u - cl * n2;
        out.push(Point3 {
            layer: cl,
            x: rem % width,
            y: rem / width,
        });
        let p = prev[cur_u];
        if p == cur {
            break;
        }
        if p == u32::MAX {
            return None;
        }
        cur = p;
    }

    if cur != start_i {
        return None;
    }
    out.reverse();
    Some(out)
}

/// K7-like extraction: backtrace a predecessor map into a point path.
pub fn k7_extract_path_2d(width: usize, prev: &[u32], start: Point, goal: Point) -> Option<Vec<Point>> {
    if start.x >= width || goal.x >= width {
        return None;
    }
    let goal_i = (goal.y * width + goal.x) as usize;
    if goal_i >= prev.len() {
        return None;
    }
    if prev[goal_i] == u32::MAX {
        return None;
    }

    let start_i = (start.y * width + start.x) as u32;
    let mut out: Vec<Point> = Vec::new();
    let mut cur = goal_i as u32;
    loop {
        let cur_u = cur as usize;
        out.push(Point {
            x: cur_u % width,
            y: cur_u / width,
        });
        let p = prev[cur_u];
        if p == cur {
            break;
        }
        if p == u32::MAX {
            return None;
        }
        cur = p;
    }

    if cur != start_i {
        // The predecessor map did not lead back to the requested start.
        return None;
    }

    out.reverse();
    Some(out)
}

/// K8-like simplification: remove collinear interior points from a Manhattan path.
pub fn k8_simplify_collinear_manhattan(path: &[Point]) -> Vec<Point> {
    if path.len() <= 2 {
        return path.to_vec();
    }

    let mut out: Vec<Point> = Vec::with_capacity(path.len());
    out.push(path[0]);
    for w in path.windows(3) {
        let (a, b, c) = (w[0], w[1], w[2]);
        let ab = (b.x as isize - a.x as isize, b.y as isize - a.y as isize);
        let bc = (c.x as isize - b.x as isize, c.y as isize - b.y as isize);
        // Keep the middle point if direction changes.
        if ab.0.signum() != bc.0.signum() || ab.1.signum() != bc.1.signum() {
            out.push(b);
        }
    }
    out.push(*path.last().unwrap());
    out
}

/// K6 (variant): Dial-style Dijkstra for small non-negative integer step costs.
///
/// The cost to enter a cell is `1 + cost_field[cell]`, so `cost_field=0` reduces to BFS.
/// This is intended as a stepping stone toward bucketed wavefront implementations that
/// are portable to GPU compute.
pub fn k6_wavefront_dial_2d(
    width: usize,
    height: usize,
    blocked: &[bool],
    cost_field: &[u16],
    start: Point,
) -> (Vec<u32>, Vec<u32>) {
    let n = width * height;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if start.x >= width || start.y >= height || blocked.len() != n || cost_field.len() != n {
        return (dist, prev);
    }
    let start_i = start.y * width + start.x;
    if blocked[start_i] {
        return (dist, prev);
    }

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost = 1u32 + max_cell_cost;
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let dirs: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];

    let mut cur_d: u32 = 0;
    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }
        let cx = (cur_u % width) as isize;
        let cy = (cur_u / width) as isize;
        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = nyu * width + nxu;
            if blocked[ni] {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }
    }

    (dist, prev)
}

/// K6 (variant): Dial-style Dijkstra with diagonal moves (8-neighborhood).
///
/// - Orthogonal move cost is `1 + cost_field[cell]`.
/// - Diagonal move cost is `1 + cost_field[cell] + diag_extra_cost`.
///
/// This keeps the same distance units as `k6_wavefront_dial_2d` and uses a
/// deterministic neighbor ordering to keep results stable under equal-cost ties.
pub fn k6_wavefront_dial_2d_diag(
    width: usize,
    height: usize,
    blocked: &[bool],
    cost_field: &[u16],
    start: Point,
    diag_extra_cost: u16,
) -> (Vec<u32>, Vec<u32>) {
    let n = width * height;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if start.x >= width || start.y >= height || blocked.len() != n || cost_field.len() != n {
        return (dist, prev);
    }
    let start_i = start.y * width + start.x;
    if blocked[start_i] {
        return (dist, prev);
    }

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost = 1u32 + max_cell_cost + (diag_extra_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];

    let mut cur_d: u32 = 0;
    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }
        let cx = (cur_u % width) as isize;
        let cy = (cur_u / width) as isize;

        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = nyu * width + nxu;
            if blocked[ni] {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = nyu * width + nxu;
            // Disallow diagonal corner-cutting through obstacles: require both adjacent
            // orthogonal cells to be free (matches Python grid/A* semantics).
            let adj1 = (cy as usize) * width + nxu;
            let adj2 = nyu * width + (cx as usize);
            if blocked[adj1] || blocked[adj2] {
                continue;
            }
            if blocked[ni] {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32 + (diag_extra_cost as u32);
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }
    }

    (dist, prev)
}

/// K6 (variant): Dial-style Dijkstra for 3D grids with small non-negative integer step costs.
///
/// - In-layer moves cost `1 + cost_field[cell]`.
/// - Via transitions between adjacent layers at the same `(x, y)` cost `via_cost`.
///
/// This is a CPU reference implementation designed for kernel-style portability
/// (bucketed wavefront) and determinism, not ultimate performance.
pub fn k6_wavefront_dial_3d(
    width: usize,
    height: usize,
    layers: usize,
    blocked: &[bool],
    cost_field: &[u16],
    start: Point3,
    via_cost: u16,
) -> (Vec<u32>, Vec<u32>) {
    let n2 = width * height;
    let n = layers * n2;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if width == 0
        || height == 0
        || layers == 0
        || blocked.len() != n
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
    {
        return (dist, prev);
    }
    let start_i = start.layer * n2 + start.y * width + start.x;
    if blocked[start_i] {
        return (dist, prev);
    }

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost = (1u32 + max_cell_cost).max(via_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let dirs: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        // Find the next non-empty bucket.
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }

        let cl = cur_u / n2;
        let rem = cur_u - cl * n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        // In-layer moves.
        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            if blocked[ni] {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        // Via moves.
        if via_cost > 0 {
            let via_step = via_cost as u32;
            let xyu = (cy as usize) * width + (cx as usize);
            if cl > 0 {
                let nl = cl - 1;
                let ni = nl * n2 + xyu;
                if !blocked[ni] {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let nl = cl + 1;
                let ni = nl * n2 + xyu;
                if !blocked[ni] {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    (dist, prev)
}

/// K6 (variant): Dial-style Dijkstra for 3D grids with diagonal moves (8-neighborhood per layer).
///
/// Diagonal moves within a layer cost `1 + cost_field[cell] + diag_extra_cost`.
pub fn k6_wavefront_dial_3d_diag(
    width: usize,
    height: usize,
    layers: usize,
    blocked: &[bool],
    cost_field: &[u16],
    start: Point3,
    via_cost: u16,
    diag_extra_cost: u16,
) -> (Vec<u32>, Vec<u32>) {
    let n2 = width * height;
    let n = layers * n2;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if width == 0
        || height == 0
        || layers == 0
        || blocked.len() != n
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
    {
        return (dist, prev);
    }
    let start_i = start.layer * n2 + start.y * width + start.x;
    if blocked[start_i] {
        return (dist, prev);
    }

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost = (1u32 + max_cell_cost + (diag_extra_cost as u32)).max(via_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }

        let cl = cur_u / n2;
        let rem = cur_u % n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        // Orthogonal in-layer moves.
        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            if blocked[ni] {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        // Diagonal in-layer moves.
        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            // Disallow diagonal corner-cutting through obstacles: require both adjacent
            // orthogonal cells on this layer to be free.
            let adj1 = cl * n2 + (cy as usize) * width + nxu;
            let adj2 = cl * n2 + nyu * width + (cx as usize);
            if blocked[adj1] || blocked[adj2] {
                continue;
            }
            if blocked[ni] {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32 + (diag_extra_cost as u32);
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        // Via moves (adjacent layers).
        if via_cost > 0 {
            let via_step = via_cost as u32;
            if cl > 0 {
                let ni = (cl - 1) * n2 + rem;
                if !blocked[ni] {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let ni = (cl + 1) * n2 + rem;
                if !blocked[ni] {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    (dist, prev)
}

/// Dial-style Dijkstra for 3D grids (reference), reading occupancy directly from `RoutingIr`.
///
/// This avoids constructing a temporary `blocked: Vec<bool>` and is a better baseline for
/// later tiling/SIMD work where `occ` is already resident in cache.
pub fn k6_wavefront_dial_3d_occ(
    ir: &RoutingIr,
    start: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
) -> (Vec<u32>, Vec<u32>) {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
    {
        return (dist, prev);
    }
    if ir.get_occ(start.layer, start.x, start.y) == blocked_value {
        return (dist, prev);
    }

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost = (1u32 + max_cell_cost).max(via_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    let start_i = start.layer * n2 + start.y * width + start.x;
    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let dirs: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }

        let cl = cur_u / n2;
        let rem = cur_u - cl * n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            if ir.occ[ni] == blocked_value {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        if via_cost > 0 {
            let via_step = via_cost as u32;
            let xyu = (cy as usize) * width + (cx as usize);
            if cl > 0 {
                let nl = cl - 1;
                let ni = nl * n2 + xyu;
                if ir.occ[ni] != blocked_value {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let nl = cl + 1;
                let ni = nl * n2 + xyu;
                if ir.occ[ni] != blocked_value {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    (dist, prev)
}

/// Dial-style Dijkstra for 3D grids (reference), reading occupancy directly from `RoutingIr`,
/// with diagonal moves (8-neighborhood per layer).
///
/// Diagonal moves are disallowed from "corner cutting": both adjacent orthogonal cells on
/// the same layer must be free (matches the Python grid/A* semantics).
pub fn k6_wavefront_dial_3d_occ_diag(
    ir: &RoutingIr,
    start: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    diag_extra_cost: u16,
) -> (Vec<u32>, Vec<u32>) {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
    {
        return (dist, prev);
    }
    if ir.get_occ(start.layer, start.x, start.y) == blocked_value {
        return (dist, prev);
    }

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost =
        (1u32 + max_cell_cost + (diag_extra_cost as u32)).max(via_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    let start_i = start.layer * n2 + start.y * width + start.x;
    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }

        let cl = cur_u / n2;
        let rem = cur_u % n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        // Orthogonal in-layer moves.
        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            if ir.occ[ni] == blocked_value {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        // Diagonal in-layer moves.
        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let adj1 = cl * n2 + (cy as usize) * width + nxu;
            let adj2 = cl * n2 + nyu * width + (cx as usize);
            if ir.occ[adj1] == blocked_value || ir.occ[adj2] == blocked_value {
                continue;
            }
            if ir.occ[ni] == blocked_value {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32 + (diag_extra_cost as u32);
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        // Via moves (adjacent layers).
        if via_cost > 0 {
            let via_step = via_cost as u32;
            if cl > 0 {
                let ni = (cl - 1) * n2 + rem;
                if ir.occ[ni] != blocked_value {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let ni = (cl + 1) * n2 + rem;
                if ir.occ[ni] != blocked_value {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    (dist, prev)
}

/// Dial-style Dijkstra for 3D grids (reference), reading occupancy directly from `RoutingIr`,
/// with diagonal moves (8-neighborhood per layer), and early exit once `goal` is settled.
pub fn k6_wavefront_dial_3d_occ_diag_to_goal(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    diag_extra_cost: u16,
) -> (Vec<u32>, Vec<u32>) {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
        || goal.layer >= layers
        || goal.x >= width
        || goal.y >= height
    {
        return (dist, prev);
    }
    if ir.get_occ(start.layer, start.x, start.y) == blocked_value {
        return (dist, prev);
    }
    if ir.get_occ(goal.layer, goal.x, goal.y) == blocked_value {
        return (dist, prev);
    }

    let goal_i = goal.layer * n2 + goal.y * width + goal.x;

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost =
        (1u32 + max_cell_cost + (diag_extra_cost as u32)).max(via_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    let start_i = start.layer * n2 + start.y * width + start.x;
    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }
        if cur_u == goal_i {
            break;
        }

        let cl = cur_u / n2;
        let rem = cur_u % n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            if ir.occ[ni] == blocked_value {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let adj1 = cl * n2 + (cy as usize) * width + nxu;
            let adj2 = cl * n2 + nyu * width + (cx as usize);
            if ir.occ[adj1] == blocked_value || ir.occ[adj2] == blocked_value {
                continue;
            }
            if ir.occ[ni] == blocked_value {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32 + (diag_extra_cost as u32);
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        if via_cost > 0 {
            let via_step = via_cost as u32;
            if cl > 0 {
                let ni = (cl - 1) * n2 + rem;
                if ir.occ[ni] != blocked_value {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let ni = (cl + 1) * n2 + rem;
                if ir.occ[ni] != blocked_value {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    (dist, prev)
}

/// Dial-style Dijkstra for 3D grids (reference), reading occupancy directly from `RoutingIr`,
/// with early exit once `goal` is settled.
pub fn k6_wavefront_dial_3d_occ_to_goal(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
) -> (Vec<u32>, Vec<u32>) {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
        || goal.layer >= layers
        || goal.x >= width
        || goal.y >= height
    {
        return (dist, prev);
    }
    if ir.get_occ(start.layer, start.x, start.y) == blocked_value {
        return (dist, prev);
    }
    if ir.get_occ(goal.layer, goal.x, goal.y) == blocked_value {
        return (dist, prev);
    }

    let goal_i = goal.layer * n2 + goal.y * width + goal.x;

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost = (1u32 + max_cell_cost).max(via_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    let start_i = start.layer * n2 + start.y * width + start.x;
    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let have_via_mask = ir.via_forbidden.len() == ir.occ.len();
    let dirs: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }
        if cur_u == goal_i {
            break;
        }

        let cl = cur_u / n2;
        let rem = cur_u - cl * n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            if ir.occ[ni] == blocked_value {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        if via_cost > 0 {
            let via_step = via_cost as u32;
            let xyu = (cy as usize) * width + (cx as usize);
            if cl > 0 {
                let nl = cl - 1;
                let ni = nl * n2 + xyu;
                if ir.occ[ni] != blocked_value
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let nl = cl + 1;
                let ni = nl * n2 + xyu;
                if ir.occ[ni] != blocked_value
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    (dist, prev)
}

/// Dial-style Dijkstra for 3D grids (reference), owner-aware blocked rule, with diagonal moves.
///
/// A cell is considered blocked if:
/// - it equals `blocked_value`, OR
/// - it is owned by a different net (`occ != 0 && occ != net_id`).
///
/// Diagonal moves are disallowed from "corner cutting": both adjacent orthogonal cells on
/// the same layer must be free (under the same owner-aware rule).
pub fn k6_wavefront_dial_3d_occ_owner_diag(
    ir: &RoutingIr,
    start: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    diag_extra_cost: u16,
    net_id: u32,
) -> (Vec<u32>, Vec<u32>) {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
    {
        return (dist, prev);
    }
    let start_i = start.layer * n2 + start.y * width + start.x;
    let start_occ = ir.occ[start_i];
    if start_occ == blocked_value || (start_occ != 0 && start_occ != net_id) {
        return (dist, prev);
    }

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost =
        (1u32 + max_cell_cost + (diag_extra_cost as u32)).max(via_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let have_via_mask = ir.via_forbidden.len() == ir.occ.len();
    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }

        let cl = cur_u / n2;
        let rem = cur_u % n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let occ = ir.occ[ni];
            if occ == blocked_value || (occ != 0 && occ != net_id) {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let adj1 = cl * n2 + (cy as usize) * width + nxu;
            let adj2 = cl * n2 + nyu * width + (cx as usize);
            let occ_adj1 = ir.occ[adj1];
            let occ_adj2 = ir.occ[adj2];
            if occ_adj1 == blocked_value
                || (occ_adj1 != 0 && occ_adj1 != net_id)
                || occ_adj2 == blocked_value
                || (occ_adj2 != 0 && occ_adj2 != net_id)
            {
                continue;
            }
            let occ = ir.occ[ni];
            if occ == blocked_value || (occ != 0 && occ != net_id) {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32 + (diag_extra_cost as u32);
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        if via_cost > 0 {
            let via_step = via_cost as u32;
            if cl > 0 {
                let ni = (cl - 1) * n2 + rem;
                let occ = ir.occ[ni];
                if occ != blocked_value
                    && (occ == 0 || occ == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let ni = (cl + 1) * n2 + rem;
                let occ = ir.occ[ni];
                if occ != blocked_value
                    && (occ == 0 || occ == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    (dist, prev)
}

/// Dial-style Dijkstra for 3D grids (reference), owner-aware blocked rule, with diagonal moves,
/// and early exit once `goal` is settled.
pub fn k6_wavefront_dial_3d_occ_owner_diag_to_goal(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    diag_extra_cost: u16,
    net_id: u32,
) -> (Vec<u32>, Vec<u32>) {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];
    let have_via_mask = ir.via_forbidden.len() == ir.occ.len();

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
        || goal.layer >= layers
        || goal.x >= width
        || goal.y >= height
    {
        return (dist, prev);
    }
    let start_i = start.layer * n2 + start.y * width + start.x;
    let start_occ = ir.occ[start_i];
    if start_occ == blocked_value || (start_occ != 0 && start_occ != net_id) {
        return (dist, prev);
    }
    let goal_i = goal.layer * n2 + goal.y * width + goal.x;
    let goal_occ = ir.occ[goal_i];
    if goal_occ == blocked_value || (goal_occ != 0 && goal_occ != net_id) {
        return (dist, prev);
    }

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost =
        (1u32 + max_cell_cost + (diag_extra_cost as u32)).max(via_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let orth: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let diag: [(isize, isize); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }
        if cur_u == goal_i {
            break;
        }

        let cl = cur_u / n2;
        let rem = cur_u % n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        for (dx, dy) in orth {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let occ = ir.occ[ni];
            if occ == blocked_value || (occ != 0 && occ != net_id) {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        for (dx, dy) in diag {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let adj1 = cl * n2 + (cy as usize) * width + nxu;
            let adj2 = cl * n2 + nyu * width + (cx as usize);
            let occ_adj1 = ir.occ[adj1];
            let occ_adj2 = ir.occ[adj2];
            if occ_adj1 == blocked_value
                || (occ_adj1 != 0 && occ_adj1 != net_id)
                || occ_adj2 == blocked_value
                || (occ_adj2 != 0 && occ_adj2 != net_id)
            {
                continue;
            }
            let occ = ir.occ[ni];
            if occ == blocked_value || (occ != 0 && occ != net_id) {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32 + (diag_extra_cost as u32);
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        if via_cost > 0 {
            let via_step = via_cost as u32;
            if cl > 0 {
                let ni = (cl - 1) * n2 + rem;
                let occ = ir.occ[ni];
                if occ != blocked_value
                    && (occ == 0 || occ == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let ni = (cl + 1) * n2 + rem;
                let occ = ir.occ[ni];
                if occ != blocked_value
                    && (occ == 0 || occ == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    (dist, prev)
}

/// Dial-style Dijkstra for 3D grids (reference), owner-aware blocked rule.
///
/// A cell is considered blocked if:
/// - it equals `blocked_value`, OR
/// - it is owned by a different net (`occ != 0 && occ != net_id`).
pub fn k6_wavefront_dial_3d_occ_owner(
    ir: &RoutingIr,
    start: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    net_id: u32,
) -> (Vec<u32>, Vec<u32>) {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
    {
        return (dist, prev);
    }
    let start_i = start.layer * n2 + start.y * width + start.x;
    let start_occ = ir.occ[start_i];
    if start_occ == blocked_value || (start_occ != 0 && start_occ != net_id) {
        return (dist, prev);
    }

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost = (1u32 + max_cell_cost).max(via_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let dirs: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }

        let cl = cur_u / n2;
        let rem = cur_u - cl * n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let occ = ir.occ[ni];
            if occ == blocked_value || (occ != 0 && occ != net_id) {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        if via_cost > 0 {
            let via_step = via_cost as u32;
            let xyu = (cy as usize) * width + (cx as usize);
            if cl > 0 {
                let nl = cl - 1;
                let ni = nl * n2 + xyu;
                let occ = ir.occ[ni];
                if occ != blocked_value && (occ == 0 || occ == net_id) {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let nl = cl + 1;
                let ni = nl * n2 + xyu;
                let occ = ir.occ[ni];
                if occ != blocked_value && (occ == 0 || occ == net_id) {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    (dist, prev)
}

/// Dial-style Dijkstra for 3D grids (reference), owner-aware blocked rule, with early exit once
/// `goal` is settled.
pub fn k6_wavefront_dial_3d_occ_owner_to_goal(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    net_id: u32,
) -> (Vec<u32>, Vec<u32>) {
    let width = ir.width;
    let height = ir.height;
    let layers = ir.layers;
    let n2 = width * height;
    let n = layers * n2;
    let mut dist = vec![u32::MAX; n];
    let mut prev = vec![u32::MAX; n];

    if width == 0
        || height == 0
        || layers == 0
        || cost_field.len() != n
        || start.layer >= layers
        || start.x >= width
        || start.y >= height
        || goal.layer >= layers
        || goal.x >= width
        || goal.y >= height
    {
        return (dist, prev);
    }
    let start_i = start.layer * n2 + start.y * width + start.x;
    let start_occ = ir.occ[start_i];
    if start_occ == blocked_value || (start_occ != 0 && start_occ != net_id) {
        return (dist, prev);
    }
    let goal_i = goal.layer * n2 + goal.y * width + goal.x;
    let goal_occ = ir.occ[goal_i];
    if goal_occ == blocked_value || (goal_occ != 0 && goal_occ != net_id) {
        return (dist, prev);
    }

    let max_cell_cost = *cost_field.iter().max().unwrap_or(&0) as u32;
    let max_edge_cost = (1u32 + max_cell_cost).max(via_cost as u32);
    let bucket_count = (max_edge_cost as usize) + 1;
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); bucket_count];
    let mut queued: usize = 0;

    dist[start_i] = 0;
    prev[start_i] = start_i as u32;
    buckets[0].push(start_i as u32);
    queued += 1;

    let have_via_mask = ir.via_forbidden.len() == ir.occ.len();
    let dirs: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let mut cur_d: u32 = 0;

    while queued > 0 {
        while buckets[(cur_d as usize) % bucket_count].is_empty() {
            cur_d = cur_d.wrapping_add(1);
        }
        let cur = buckets[(cur_d as usize) % bucket_count].pop().unwrap();
        queued -= 1;
        let cur_u = cur as usize;
        if dist[cur_u] != cur_d {
            continue;
        }
        if cur_u == goal_i {
            break;
        }

        let cl = cur_u / n2;
        let rem = cur_u - cl * n2;
        let cx = (rem % width) as isize;
        let cy = (rem / width) as isize;

        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= width || nyu >= height {
                continue;
            }
            let ni = cl * n2 + nyu * width + nxu;
            let occ = ir.occ[ni];
            if occ == blocked_value || (occ != 0 && occ != net_id) {
                continue;
            }
            let step = 1u32 + cost_field[ni] as u32;
            let nd = cur_d.saturating_add(step);
            if nd < dist[ni] {
                dist[ni] = nd;
                prev[ni] = cur;
                buckets[(nd as usize) % bucket_count].push(ni as u32);
                queued += 1;
            }
        }

        if via_cost > 0 {
            let via_step = via_cost as u32;
            let xyu = (cy as usize) * width + (cx as usize);
            if cl > 0 {
                let nl = cl - 1;
                let ni = nl * n2 + xyu;
                let occ = ir.occ[ni];
                if occ != blocked_value
                    && (occ == 0 || occ == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
            if cl + 1 < layers {
                let nl = cl + 1;
                let ni = nl * n2 + xyu;
                let occ = ir.occ[ni];
                if occ != blocked_value
                    && (occ == 0 || occ == net_id)
                    && (!have_via_mask || (ir.via_forbidden[cur_u] == 0 && ir.via_forbidden[ni] == 0))
                {
                    let nd = cur_d.saturating_add(via_step);
                    if nd < dist[ni] {
                        dist[ni] = nd;
                        prev[ni] = cur;
                        buckets[(nd as usize) % bucket_count].push(ni as u32);
                        queued += 1;
                    }
                }
            }
        }
    }

    (dist, prev)
}
