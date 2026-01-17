use crate::ir::RoutingIr;
use crate::kernels::{
    Dial3dScratch, k6_a_star_3d_occ_owner_diag_to_goal_with_scratch,
    k6_a_star_3d_occ_owner_diag_soft_to_goal_with_scratch,
    k6_wavefront_dial_3d_occ_to_goal,
    k7_extract_path_3d,
};
use crate::kernels::{
    k13_uncommit_net_occ_3d, k9_commit_path_occ_3d, k9_commit_path_occ_3d_brush,
    k9_try_commit_path_occ_3d, k9_try_commit_path_occ_3d_brush,
};
use crate::mst::mst_manhattan;
use serde::{Deserialize, Serialize};
use std::cell::RefCell;
use std::collections::{HashMap, HashSet, VecDeque};

thread_local! {
    static DIAL3D_SCRATCH: RefCell<Dial3dScratch> = RefCell::new(Dial3dScratch::default());
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Point {
    pub x: usize,
    pub y: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Point3 {
    pub layer: usize,
    pub x: usize,
    pub y: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Path {
    pub layer: usize,
    pub points: Vec<Point>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Path3 {
    pub points: Vec<Point3>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NetRouteRequest {
    pub net_id: u32,
    pub start: Point3,
    pub goal: Point3,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetRouteResult {
    pub net_id: u32,
    pub path: Option<Path3>,
}

fn violates_min_via_spacing(points: &[Point3], min_chebyshev_dist: u8) -> bool {
    if min_chebyshev_dist <= 1 {
        return false;
    }
    let r = (min_chebyshev_dist as isize) - 1;
    let mut seen: HashSet<(isize, isize)> = HashSet::new();
    for w in points.windows(2) {
        let a = w[0];
        let b = w[1];
        if a.layer == b.layer {
            continue;
        }
        // Mirror DSN export semantics: if a layer transition is ever represented with an XY delta
        // (shouldn't happen, but can if a later stage compresses points), still treat it as a via
        // at the transition coordinate.
        let vx = (if a.x == b.x { a.x } else { b.x }) as isize;
        let vy = (if a.y == b.y { a.y } else { b.y }) as isize;
        // Multiple layer transitions at the same `(x, y)` represent a single via site (stacked
        // transitions / multi-layer travel). Don't treat duplicates as a spacing violation.
        if seen.contains(&(vx, vy)) {
            continue;
        }
        for dy in -r..=r {
            for dx in -r..=r {
                if seen.contains(&(vx + dx, vy + dy)) {
                    return true;
                }
            }
        }
        seen.insert((vx, vy));
    }
    false
}

#[derive(Debug, Clone)]
struct RequeueIndex {
    by_net: HashMap<u32, Vec<usize>>,
}

impl RequeueIndex {
    fn new(reqs: &[NetRouteRequest]) -> Self {
        let mut by_net: HashMap<u32, Vec<usize>> = HashMap::new();
        for (i, r) in reqs.iter().enumerate() {
            by_net.entry(r.net_id).or_default().push(i);
        }
        Self { by_net }
    }

    fn requeue_net(
        &self,
        reqs: &[NetRouteRequest],
        net_id: u32,
        out_paths: &mut [Option<Path3>],
        pending: &mut VecDeque<usize>,
        in_pending: &mut [bool],
    ) {
        if let Some(idxs) = self.by_net.get(&net_id) {
            for &j in idxs {
                out_paths[j] = None;
                if !in_pending[j] {
                    pending.push_back(j);
                    in_pending[j] = true;
                }
            }
            return;
        }

        // Safety fallback: if we saw a net_id in occupancy that doesn't have a request entry, keep the old
        // scan-based behavior (should be rare).
        for (j, r) in reqs.iter().enumerate() {
            if r.net_id != net_id {
                continue;
            }
            out_paths[j] = None;
            if !in_pending[j] {
                pending.push_back(j);
                in_pending[j] = true;
            }
        }
    }
}

pub trait RouterBackend {
    fn name(&self) -> &'static str;
    fn route_2d(
        &self,
        ir: &RoutingIr,
        layer: usize,
        start: Point,
        goal: Point,
        blocked_value: u32,
    ) -> Option<Path>;
}

#[derive(Debug, Default, Clone, Copy)]
pub struct BfsScalarBackend;

impl RouterBackend for BfsScalarBackend {
    fn name(&self) -> &'static str {
        "bfs_scalar"
    }

    fn route_2d(
        &self,
        ir: &RoutingIr,
        layer: usize,
        start: Point,
        goal: Point,
        blocked_value: u32,
    ) -> Option<Path> {
        route_bfs_2d(ir, layer, start, goal, blocked_value)
    }
}

/// Minimal deterministic Manhattan BFS (scalar reference).
///
/// This is intentionally simple: it provides a correctness baseline for later
/// bucketed wavefront / SIMD / GPU ports.
pub fn route_bfs_2d(
    ir: &RoutingIr,
    layer: usize,
    start: Point,
    goal: Point,
    blocked_value: u32,
) -> Option<Path> {
    if start.x >= ir.width
        || start.y >= ir.height
        || goal.x >= ir.width
        || goal.y >= ir.height
        || layer >= ir.layers
    {
        return None;
    }

    let start_i = start.y * ir.width + start.x;
    let goal_i = goal.y * ir.width + goal.x;
    let n = ir.width * ir.height;

    let mut prev: Vec<i32> = vec![-1; n];
    let mut q: std::collections::VecDeque<usize> = std::collections::VecDeque::new();

    let occ0 = ir.get_occ(layer, start.x, start.y);
    let occg = ir.get_occ(layer, goal.x, goal.y);
    if occ0 == blocked_value || occg == blocked_value {
        return None;
    }

    prev[start_i] = start_i as i32;
    q.push_back(start_i);

    // Deterministic neighbor order: R, D, L, U (stable).
    let dirs: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];

    while let Some(cur) = q.pop_front() {
        if cur == goal_i {
            break;
        }
        let cx = (cur % ir.width) as isize;
        let cy = (cur / ir.width) as isize;

        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= ir.width || nyu >= ir.height {
                continue;
            }
            if ir.get_occ(layer, nxu, nyu) == blocked_value {
                continue;
            }
            let ni = nyu * ir.width + nxu;
            if prev[ni] != -1 {
                continue;
            }
            prev[ni] = cur as i32;
            q.push_back(ni);
        }
    }

    if prev[goal_i] == -1 {
        return None;
    }

    let mut points: Vec<Point> = Vec::new();
    let mut cur = goal_i;
    loop {
        points.push(Point {
            x: cur % ir.width,
            y: cur / ir.width,
        });
        let p = prev[cur] as usize;
        if p == cur {
            break;
        }
        cur = p;
    }
    points.reverse();

    Some(Path { layer, points })
}

/// Dial-style 3D routing wrapper over `RoutingIr`.
///
/// This is a minimal API intended to exercise the 3D kernels end-to-end. The
/// cost model is entirely integer:
/// - In-layer step cost is `1 + cost_field[cell]`.
/// - Via step cost is `via_cost`.
pub fn route_dial_3d_from_ir(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
) -> Option<Path3> {
    if start.layer >= ir.layers
        || goal.layer >= ir.layers
        || start.x >= ir.width
        || start.y >= ir.height
        || goal.x >= ir.width
        || goal.y >= ir.height
    {
        return None;
    }
    let n2 = ir.width * ir.height;
    let n = ir.layers * n2;
    if cost_field.len() != n {
        return None;
    }

    let (dist, prev) =
        k6_wavefront_dial_3d_occ_to_goal(ir, start, goal, blocked_value, cost_field, via_cost);
    let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;
    if dist[goal_i] == u32::MAX {
        return None;
    }
    let points = k7_extract_path_3d(ir.width, ir.height, ir.layers, &prev, start, goal)?;
    Some(Path3 { points })
}

/// Dial-style 3D routing wrapper that treats other nets’ occupancy as blocked.
///
/// Blocked rule:
/// - `occ == blocked_value` is always blocked (board edge/keepout/etc)
/// - any other non-zero `occ` is blocked unless it equals `net_id`
pub fn route_dial_3d_for_net(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    net_id: u32,
) -> Option<Path3> {
    if start.layer >= ir.layers
        || goal.layer >= ir.layers
        || start.x >= ir.width
        || start.y >= ir.height
        || goal.x >= ir.width
        || goal.y >= ir.height
    {
        return None;
    }
    let n2 = ir.width * ir.height;
    let n = ir.layers * n2;
    if cost_field.len() != n {
        return None;
    }

    // Use diagonal moves by default; this significantly improves reachability on grid-based
    // representations of real PCBs, especially when escaping dense pin fields.
    let diag_extra_cost = 1u16;
    let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;

    // Default to scratch-based routing to avoid per-call allocations.
    DIAL3D_SCRATCH.with(|scratch| {
        let mut scratch = scratch.borrow_mut();
        let ok = k6_a_star_3d_occ_owner_diag_to_goal_with_scratch(
            ir,
            start,
            goal,
            blocked_value,
            cost_field,
            &[],
            &[],
            &[],
            via_cost,
            diag_extra_cost,
            net_id,
            &mut scratch,
        );
        if !ok || scratch.dist[goal_i] == u32::MAX {
            return None;
        }
        let points = k7_extract_path_3d(ir.width, ir.height, ir.layers, &scratch.prev, start, goal)?;
        Some(Path3 { points })
    })
}

/// Variant of `route_dial_3d_for_net` that applies per-layer direction costs.
pub fn route_dial_3d_for_net_with_layer_dir_costs(
    ir: &RoutingIr,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cost_field: &[u16],
    layer_h_costs: &[u16],
    layer_v_costs: &[u16],
    layer_d_costs: &[u16],
    via_cost: u16,
    net_id: u32,
) -> Option<Path3> {
    if start.layer >= ir.layers
        || goal.layer >= ir.layers
        || start.x >= ir.width
        || start.y >= ir.height
        || goal.x >= ir.width
        || goal.y >= ir.height
    {
        return None;
    }
    let n2 = ir.width * ir.height;
    let n = ir.layers * n2;
    if cost_field.len() != n {
        return None;
    }

    let diag_extra_cost = 1u16;
    let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;

    DIAL3D_SCRATCH.with(|scratch| {
        let mut scratch = scratch.borrow_mut();
        let ok = k6_a_star_3d_occ_owner_diag_to_goal_with_scratch(
            ir,
            start,
            goal,
            blocked_value,
            cost_field,
            layer_h_costs,
            layer_v_costs,
            layer_d_costs,
            via_cost,
            diag_extra_cost,
            net_id,
            &mut scratch,
        );
        if !ok || scratch.dist[goal_i] == u32::MAX {
            return None;
        }
        let points = k7_extract_path_3d(ir.width, ir.height, ir.layers, &scratch.prev, start, goal)?;
        Some(Path3 { points })
    })
}

fn route_dial_3d_for_net_with_scratch(
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
) -> Option<Path3> {
    if start.layer >= ir.layers
        || goal.layer >= ir.layers
        || start.x >= ir.width
        || start.y >= ir.height
        || goal.x >= ir.width
        || goal.y >= ir.height
    {
        return None;
    }
    let n2 = ir.width * ir.height;
    let n = ir.layers * n2;
    if cost_field.len() != n {
        return None;
    }

    let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;
    let ok = k6_a_star_3d_occ_owner_diag_to_goal_with_scratch(
        ir,
        start,
        goal,
        blocked_value,
        cost_field,
        layer_h_costs,
        layer_v_costs,
        layer_d_costs,
        via_cost,
        diag_extra_cost,
        net_id,
        scratch,
    );
    if !ok || scratch.dist[goal_i] == u32::MAX {
        return None;
    }
    let points = k7_extract_path_3d(ir.width, ir.height, ir.layers, &scratch.prev, start, goal)?;
    Some(Path3 { points })
}

fn route_dial_3d_for_net_soft_with_scratch(
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
) -> Option<Path3> {
    if start.layer >= ir.layers
        || goal.layer >= ir.layers
        || start.x >= ir.width
        || start.y >= ir.height
        || goal.x >= ir.width
        || goal.y >= ir.height
    {
        return None;
    }
    let n2 = ir.width * ir.height;
    let n = ir.layers * n2;
    if cost_field.len() != n {
        return None;
    }

    let goal_i = goal.layer * n2 + goal.y * ir.width + goal.x;
    let ok = k6_a_star_3d_occ_owner_diag_soft_to_goal_with_scratch(
        ir,
        start,
        goal,
        blocked_value,
        cost_field,
        layer_h_costs,
        layer_v_costs,
        layer_d_costs,
        via_cost,
        diag_extra_cost,
        other_net_penalty,
        net_id,
        scratch,
    );
    if !ok || scratch.dist[goal_i] == u32::MAX {
        return None;
    }
    let points = k7_extract_path_3d(ir.width, ir.height, ir.layers, &scratch.prev, start, goal)?;
    Some(Path3 { points })
}

fn brush_offsets(radius: u8) -> Vec<(isize, isize)> {
    let r = radius as isize;
    if r <= 0 {
        return vec![(0, 0)];
    }
    let mut out: Vec<(isize, isize)> = Vec::new();
    for dy in -r..=r {
        for dx in -r..=r {
            if dx * dx + dy * dy <= r * r {
                out.push((dx, dy));
            }
        }
    }
    out
}

fn collect_ripup_net_ids_for_path(
    ir: &RoutingIr,
    points: &[Point3],
    blocked_value: u32,
    net_id: u32,
    brush_radius: u8,
) -> Result<HashSet<u32>, ()> {
    let have_pad_owner = ir.pad_owner.len() == ir.occ.len();
    let offsets = brush_offsets(brush_radius);
    let mut out: HashSet<u32> = HashSet::new();

    for p in points {
        let layer = p.layer;
        if layer >= ir.layers {
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
            let idx = ir.idx(layer, xu, yu);
            if have_pad_owner {
                let pad = ir.pad_owner[idx];
                if pad != 0 && pad != net_id {
                    return Err(());
                }
            }
            let occ = ir.occ[idx];
            if occ == 0 || occ == net_id {
                continue;
            }
            if occ == blocked_value {
                return Err(());
            }
            out.insert(occ);
        }
    }

    Ok(out)
}

/// Minimal multi-net loop: sequentially route and commit each requested two-pin net.
///
/// This is intentionally simple (no ripup/negotiation yet). It’s meant as a
/// correctness baseline and a harness for future optimization work.
pub fn route_nets_sequential(
    ir: &mut RoutingIr,
    reqs: &[NetRouteRequest],
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
) -> Vec<NetRouteResult> {
    let diag_extra_cost = 1u16;
    let mut scratch = Dial3dScratch::default();

    let mut out: Vec<NetRouteResult> = Vec::with_capacity(reqs.len());
    for r in reqs {
        let path = route_dial_3d_for_net_with_scratch(
            ir,
            r.start,
            r.goal,
            blocked_value,
            cost_field,
            &[],
            &[],
            &[],
            via_cost,
            diag_extra_cost,
            r.net_id,
            &mut scratch,
        );
        let mut committed = path.clone();
        if let Some(p) = &path {
            let conflicts = k9_commit_path_occ_3d(ir, &p.points, r.net_id);
            if !conflicts.is_empty() {
                k13_uncommit_net_occ_3d(ir, r.net_id);
                committed = None;
            }
        }
        out.push(NetRouteResult {
            net_id: r.net_id,
            path: committed,
        });
    }
    out
}

/// Variant of `route_nets_sequential` that commits routes with a circular brush.
///
/// `brush_radius` is in grid cells. Use `0` for the old behavior.
pub fn route_nets_sequential_with_brush(
    ir: &mut RoutingIr,
    reqs: &[NetRouteRequest],
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    brush_radius: u8,
) -> Vec<NetRouteResult> {
    if brush_radius == 0 {
        return route_nets_sequential(ir, reqs, blocked_value, cost_field, via_cost);
    }

    let diag_extra_cost = 1u16;
    let mut scratch = Dial3dScratch::default();

    let mut out: Vec<NetRouteResult> = Vec::with_capacity(reqs.len());
    for r in reqs {
        let path = route_dial_3d_for_net_with_scratch(
            ir,
            r.start,
            r.goal,
            blocked_value,
            cost_field,
            &[],
            &[],
            &[],
            via_cost,
            diag_extra_cost,
            r.net_id,
            &mut scratch,
        );
        let mut committed = path.clone();
        if let Some(p) = &path {
            let conflicts = k9_commit_path_occ_3d_brush(ir, &p.points, r.net_id, brush_radius);
            if !conflicts.is_empty() {
                k13_uncommit_net_occ_3d(ir, r.net_id);
                committed = None;
            }
        }
        out.push(NetRouteResult {
            net_id: r.net_id,
            path: committed,
        });
    }
    out
}

/// Variant of `route_nets_sequential` that commits routes with a per-request brush radius.
///
/// `brush_radii` must have the same length as `reqs`. Each entry is a radius in grid cells.
pub fn route_nets_sequential_with_brushes(
    ir: &mut RoutingIr,
    reqs: &[NetRouteRequest],
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    brush_radii: &[u8],
) -> Vec<NetRouteResult> {
    if brush_radii.len() != reqs.len() {
        // Keep behavior explicit: if sizes mismatch, fall back to no-brush to avoid surprising overblocking.
        return route_nets_sequential(ir, reqs, blocked_value, cost_field, via_cost);
    }

    let diag_extra_cost = 1u16;
    let mut scratch = Dial3dScratch::default();

    let mut out: Vec<NetRouteResult> = Vec::with_capacity(reqs.len());
    for (r, &brush_radius) in reqs.iter().zip(brush_radii.iter()) {
        let path = route_dial_3d_for_net_with_scratch(
            ir,
            r.start,
            r.goal,
            blocked_value,
            cost_field,
            &[],
            &[],
            &[],
            via_cost,
            diag_extra_cost,
            r.net_id,
            &mut scratch,
        );
        let mut committed = path.clone();
        if let Some(p) = &path {
            let min_via_dist = brush_radius.saturating_add(1).max(2);
            if violates_min_via_spacing(&p.points, min_via_dist) {
                committed = None;
            } else {
                let conflicts = if brush_radius == 0 {
                    k9_commit_path_occ_3d(ir, &p.points, r.net_id)
                } else {
                    k9_commit_path_occ_3d_brush(ir, &p.points, r.net_id, brush_radius)
                };
                if !conflicts.is_empty() {
                    k13_uncommit_net_occ_3d(ir, r.net_id);
                    committed = None;
                }
            }
        }
        out.push(NetRouteResult {
            net_id: r.net_id,
            path: committed,
        });
    }
    out
}

/// Variant of `route_nets_sequential_with_brushes` that applies per-layer direction costs.
pub fn route_nets_sequential_with_brushes_and_layer_dir_costs(
    ir: &mut RoutingIr,
    reqs: &[NetRouteRequest],
    blocked_value: u32,
    cost_field: &[u16],
    layer_h_costs: &[u16],
    layer_v_costs: &[u16],
    layer_d_costs: &[u16],
    via_cost: u16,
    brush_radii: &[u8],
) -> Vec<NetRouteResult> {
    if brush_radii.len() != reqs.len() {
        return route_nets_sequential(ir, reqs, blocked_value, cost_field, via_cost);
    }

    let diag_extra_cost = 1u16;
    let mut scratch = Dial3dScratch::default();

    let mut out: Vec<NetRouteResult> = Vec::with_capacity(reqs.len());
    for (r, &brush_radius) in reqs.iter().zip(brush_radii.iter()) {
        let path = route_dial_3d_for_net_with_scratch(
            ir,
            r.start,
            r.goal,
            blocked_value,
            cost_field,
            layer_h_costs,
            layer_v_costs,
            layer_d_costs,
            via_cost,
            diag_extra_cost,
            r.net_id,
            &mut scratch,
        );
        let mut committed = path.clone();
        if let Some(p) = &path {
            let conflicts = if brush_radius == 0 {
                k9_commit_path_occ_3d(ir, &p.points, r.net_id)
            } else {
                k9_commit_path_occ_3d_brush(ir, &p.points, r.net_id, brush_radius)
            };
            if !conflicts.is_empty() {
                k13_uncommit_net_occ_3d(ir, r.net_id);
                committed = None;
            }
        }
        out.push(NetRouteResult {
            net_id: r.net_id,
            path: committed,
        });
    }
    out
}

/// Sequential routing with periodic cost-field rebuilds.
///
/// This approximates FreeRouting's "history" / congestion effects by re-deriving the routing cost
/// from the current occupancy as routing progresses, without changing reachability semantics.
pub fn route_nets_sequential_dynamic_cost_with_brushes_and_layer_dir_costs(
    ir: &mut RoutingIr,
    reqs: &[NetRouteRequest],
    blocked_value: u32,
    layer_h_costs: &[u16],
    layer_v_costs: &[u16],
    layer_d_costs: &[u16],
    via_cost: u16,
    brush_radii: &[u8],
    rebuild_every: usize,
    occ_penalty: u16,
    blocked_penalty: u16,
) -> Vec<NetRouteResult> {
    if brush_radii.len() != reqs.len() {
        // Keep behavior explicit on mismatched arrays.
        let cost_field = ir.build_cost_field_adjacent(blocked_value, occ_penalty, blocked_penalty);
        return route_nets_sequential_with_brushes_and_layer_dir_costs(
            ir,
            reqs,
            blocked_value,
            &cost_field,
            layer_h_costs,
            layer_v_costs,
            layer_d_costs,
            via_cost,
            brush_radii,
        );
    }

    let diag_extra_cost = 1u16;
    let mut scratch = Dial3dScratch::default();
    let mut cost_field = ir.build_cost_field_adjacent(blocked_value, occ_penalty, blocked_penalty);

    let mut out: Vec<NetRouteResult> = Vec::with_capacity(reqs.len());
    for (i, (r, &brush_radius)) in reqs.iter().zip(brush_radii.iter()).enumerate() {
        if rebuild_every > 0 && i > 0 && (i % rebuild_every == 0) {
            cost_field = ir.build_cost_field_adjacent(blocked_value, occ_penalty, blocked_penalty);
        }

        let path = route_dial_3d_for_net_with_scratch(
            ir,
            r.start,
            r.goal,
            blocked_value,
            &cost_field,
            layer_h_costs,
            layer_v_costs,
            layer_d_costs,
            via_cost,
            diag_extra_cost,
            r.net_id,
            &mut scratch,
        );

        let mut committed = path.clone();
        if let Some(p) = &path {
            let min_via_dist = brush_radius.saturating_add(1).max(2);
            if violates_min_via_spacing(&p.points, min_via_dist) {
                committed = None;
            } else {
                let conflicts = if brush_radius == 0 {
                    k9_commit_path_occ_3d(ir, &p.points, r.net_id)
                } else {
                    k9_commit_path_occ_3d_brush(ir, &p.points, r.net_id, brush_radius)
                };
                if !conflicts.is_empty() {
                    k13_uncommit_net_occ_3d(ir, r.net_id);
                    committed = None;
                }
            }
        }

        out.push(NetRouteResult {
            net_id: r.net_id,
            path: committed,
        });
    }
    out
}

/// Minimal negotiation/ripup loop for multi-net routing on `RoutingIr`.
///
/// This is not FreeRouting parity — it's a small, deterministic step toward negotiation:
/// - Try strict routing first (other nets are blocked).
/// - If that fails, try a “soft” A* route that can cross other nets' traces with penalty.
/// - Rip up (uncommit) conflicting nets and re-queue them.
///
/// This respects `pad_owner`: other nets' pads are never crossable and are never ripped up.
pub fn route_nets_negotiation_basic_with_brushes(
    ir: &mut RoutingIr,
    reqs: &[NetRouteRequest],
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    brush_radii: &[u8],
    other_net_penalty: u16,
    max_iters: usize,
    max_ripup_nets_per_attempt: usize,
) -> Vec<NetRouteResult> {
    let diag_extra_cost = 1u16;
    let mut strict_scratch = Dial3dScratch::default();
    let mut soft_scratch = Dial3dScratch::default();

    let mut out_paths: Vec<Option<Path3>> = vec![None; reqs.len()];
    let mut pending: VecDeque<usize> = (0..reqs.len()).collect();
    let mut in_pending: Vec<bool> = vec![true; reqs.len()];
    let mut iters: usize = 0;

    let requeue_index = RequeueIndex::new(reqs);

    while let Some(i) = pending.pop_front() {
        in_pending[i] = false;
        iters += 1;
        if max_iters > 0 && iters > max_iters {
            break;
        }

        let r = reqs[i];
        let brush = brush_radii.get(i).copied().unwrap_or(0);

        let try_commit = |ir: &mut RoutingIr, p: &Path3| -> Result<Vec<u32>, ()> {
            let conflicts = if brush == 0 {
                match k9_try_commit_path_occ_3d(ir, &p.points, r.net_id) {
                    Ok(()) => Vec::new(),
                    Err(v) => v,
                }
            } else {
                match k9_try_commit_path_occ_3d_brush(ir, &p.points, r.net_id, brush) {
                    Ok(()) => Vec::new(),
                    Err(v) => v,
                }
            };
            if conflicts.is_empty() {
                return Ok(Vec::new());
            }
            let mut ids: HashSet<u32> = HashSet::new();
            for c in conflicts {
                if c.existing == blocked_value {
                    return Err(());
                }
                if c.existing != 0 && c.existing != r.net_id {
                    ids.insert(c.existing);
                }
            }
            Ok(ids.into_iter().collect())
        };

        // 1) Strict attempt.
        if let Some(path) = route_dial_3d_for_net_with_scratch(
            ir,
            r.start,
            r.goal,
            blocked_value,
            cost_field,
            &[],
            &[],
            &[],
            via_cost,
            diag_extra_cost,
            r.net_id,
            &mut strict_scratch,
        ) {
            match try_commit(ir, &path) {
                Ok(mut conflicts) => {
                    // Brush can collide even if the strict path is free. Rip those nets and retry once.
                    conflicts.sort();
                    conflicts.dedup();
                    if conflicts.len() > max_ripup_nets_per_attempt {
                        continue;
                    }
                    for nid in &conflicts {
                        k13_uncommit_net_occ_3d(ir, *nid);
                        requeue_index.requeue_net(reqs, *nid, &mut out_paths, &mut pending, &mut in_pending);
                    }
                    if conflicts.is_empty() {
                        out_paths[i] = Some(path);
                        continue;
                    }
                    // Retry commit after ripup.
                    if matches!(try_commit(ir, &path), Ok(c) if c.is_empty()) {
                        out_paths[i] = Some(path);
                    }
                    continue;
                }
                Err(()) => continue,
            }
        }

        // 2) Soft attempt + ripup.
        let Some(path) = route_dial_3d_for_net_soft_with_scratch(
            ir,
            r.start,
            r.goal,
            blocked_value,
            cost_field,
            &[],
            &[],
            &[],
            via_cost,
            diag_extra_cost,
            other_net_penalty,
            r.net_id,
            &mut soft_scratch,
        ) else {
            continue;
        };

        let Ok(mut ripup) = collect_ripup_net_ids_for_path(ir, &path.points, blocked_value, r.net_id, brush) else {
            continue;
        };
        if ripup.len() > max_ripup_nets_per_attempt {
            continue;
        }

        // Remove conflicting nets and requeue them.
        for nid in ripup.drain() {
            k13_uncommit_net_occ_3d(ir, nid);
            requeue_index.requeue_net(reqs, nid, &mut out_paths, &mut pending, &mut in_pending);
        }

        // Commit the soft path after ripup. If it still conflicts, also rip those nets (one more round).
        match try_commit(ir, &path) {
            Ok(conflicts) => {
                if conflicts.is_empty() {
                    out_paths[i] = Some(path);
                    continue;
                }
                if conflicts.len() > max_ripup_nets_per_attempt {
                    continue;
                }
                for nid in &conflicts {
                    k13_uncommit_net_occ_3d(ir, *nid);
                    requeue_index.requeue_net(reqs, *nid, &mut out_paths, &mut pending, &mut in_pending);
                }
                if matches!(try_commit(ir, &path), Ok(c) if c.is_empty()) {
                    out_paths[i] = Some(path);
                }
            }
            Err(()) => continue,
        }
    }

    reqs.iter()
        .enumerate()
        .map(|(i, r)| NetRouteResult {
            net_id: r.net_id,
            path: out_paths[i].clone(),
        })
        .collect()
}

/// Variant of `route_nets_negotiation_basic_with_brushes` that applies per-layer direction costs.
pub fn route_nets_negotiation_basic_with_brushes_and_layer_dir_costs(
    ir: &mut RoutingIr,
    reqs: &[NetRouteRequest],
    blocked_value: u32,
    cost_field: &[u16],
    layer_h_costs: &[u16],
    layer_v_costs: &[u16],
    layer_d_costs: &[u16],
    via_cost: u16,
    brush_radii: &[u8],
    other_net_penalty: u16,
    max_iters: usize,
    max_ripup_nets_per_attempt: usize,
) -> Vec<NetRouteResult> {
    let diag_extra_cost = 1u16;
    let mut strict_scratch = Dial3dScratch::default();
    let mut soft_scratch = Dial3dScratch::default();

    let mut out_paths: Vec<Option<Path3>> = vec![None; reqs.len()];
    let mut pending: VecDeque<usize> = (0..reqs.len()).collect();
    let mut in_pending: Vec<bool> = vec![true; reqs.len()];
    let mut iters: usize = 0;
    let mut attempts_without_new_route: usize = 0;
    let stagnation_limit: usize = reqs.len().saturating_mul(4).max(200);

    let requeue_index = RequeueIndex::new(reqs);

    while let Some(i) = pending.pop_front() {
        in_pending[i] = false;
        iters += 1;
        if max_iters > 0 && iters > max_iters {
            break;
        }
        if attempts_without_new_route >= stagnation_limit {
            break;
        }

        let routed_this_iter = (|| -> bool {
            let r = reqs[i];
            let brush = brush_radii.get(i).copied().unwrap_or(0);

            let try_commit = |ir: &mut RoutingIr, p: &Path3| -> Result<Vec<u32>, ()> {
                let conflicts = if brush == 0 {
                    match k9_try_commit_path_occ_3d(ir, &p.points, r.net_id) {
                        Ok(()) => Vec::new(),
                        Err(v) => v,
                    }
                } else {
                    match k9_try_commit_path_occ_3d_brush(ir, &p.points, r.net_id, brush) {
                        Ok(()) => Vec::new(),
                        Err(v) => v,
                    }
                };
                if conflicts.is_empty() {
                    return Ok(Vec::new());
                }
                let mut ids: HashSet<u32> = HashSet::new();
                for c in conflicts {
                    if c.existing == blocked_value {
                        return Err(());
                    }
                    if c.existing != 0 && c.existing != r.net_id {
                        ids.insert(c.existing);
                    }
                }
                Ok(ids.into_iter().collect())
            };

            if let Some(path) = route_dial_3d_for_net_with_scratch(
                ir,
                r.start,
                r.goal,
                blocked_value,
                cost_field,
                layer_h_costs,
                layer_v_costs,
                layer_d_costs,
                via_cost,
                diag_extra_cost,
                r.net_id,
                &mut strict_scratch,
            ) {
                match try_commit(ir, &path) {
                    Ok(mut conflicts) => {
                        conflicts.sort();
                        conflicts.dedup();
                        if conflicts.len() > max_ripup_nets_per_attempt {
                            return false;
                        }
                        for nid in &conflicts {
                            k13_uncommit_net_occ_3d(ir, *nid);
                            requeue_index.requeue_net(reqs, *nid, &mut out_paths, &mut pending, &mut in_pending);
                        }
                        if conflicts.is_empty() {
                            out_paths[i] = Some(path);
                            return true;
                        }
                        if matches!(try_commit(ir, &path), Ok(c) if c.is_empty()) {
                            out_paths[i] = Some(path);
                            return true;
                        }
                        return false;
                    }
                    Err(()) => return false,
                }
            }

            let Some(path) = route_dial_3d_for_net_soft_with_scratch(
                ir,
                r.start,
                r.goal,
                blocked_value,
                cost_field,
                layer_h_costs,
                layer_v_costs,
                layer_d_costs,
                via_cost,
                diag_extra_cost,
                other_net_penalty,
                r.net_id,
                &mut soft_scratch,
            ) else {
                return false;
            };

            let Ok(mut ripup) =
                collect_ripup_net_ids_for_path(ir, &path.points, blocked_value, r.net_id, brush)
            else {
                return false;
            };
            if ripup.len() > max_ripup_nets_per_attempt {
                return false;
            }

            for nid in ripup.drain() {
                k13_uncommit_net_occ_3d(ir, nid);
                requeue_index.requeue_net(reqs, nid, &mut out_paths, &mut pending, &mut in_pending);
            }

            match try_commit(ir, &path) {
                Ok(conflicts) => {
                    if conflicts.is_empty() {
                        out_paths[i] = Some(path);
                        return true;
                    }
                    if conflicts.len() > max_ripup_nets_per_attempt {
                        return false;
                    }
                    for nid in &conflicts {
                        k13_uncommit_net_occ_3d(ir, *nid);
                        requeue_index.requeue_net(reqs, *nid, &mut out_paths, &mut pending, &mut in_pending);
                    }
                    if matches!(try_commit(ir, &path), Ok(c) if c.is_empty()) {
                        out_paths[i] = Some(path);
                        return true;
                    }
                    false
                }
                Err(()) => false,
            }
        })();

        if routed_this_iter {
            attempts_without_new_route = 0;
        } else {
            attempts_without_new_route = attempts_without_new_route.saturating_add(1);
        }
    }

    reqs.iter()
        .enumerate()
        .map(|(i, r)| NetRouteResult {
            net_id: r.net_id,
            path: out_paths[i].clone(),
        })
        .collect()
}

/// Negotiation routing with periodic cost-field rebuilds.
///
/// Derives a routing cost field from the current occupancy every `rebuild_every` popped requests.
/// This is a coarse approximation of congestion/history costs without changing reachability.
pub fn route_nets_negotiation_basic_dynamic_cost_with_brushes_and_layer_dir_costs(
    ir: &mut RoutingIr,
    reqs: &[NetRouteRequest],
    blocked_value: u32,
    layer_h_costs: &[u16],
    layer_v_costs: &[u16],
    layer_d_costs: &[u16],
    via_cost: u16,
    brush_radii: &[u8],
    other_net_penalty: u16,
    max_iters: usize,
    max_ripup_nets_per_attempt: usize,
    rebuild_every: usize,
    occ_penalty: u16,
    blocked_penalty: u16,
) -> Vec<NetRouteResult> {
    let mut cost_field = ir.build_cost_field_adjacent(blocked_value, occ_penalty, blocked_penalty);
    if rebuild_every == 0 {
        return route_nets_negotiation_basic_with_brushes_and_layer_dir_costs(
            ir,
            reqs,
            blocked_value,
            &cost_field,
            layer_h_costs,
            layer_v_costs,
            layer_d_costs,
            via_cost,
            brush_radii,
            other_net_penalty,
            max_iters,
            max_ripup_nets_per_attempt,
        );
    }

    let diag_extra_cost = 1u16;
    let mut strict_scratch = Dial3dScratch::default();
    let mut soft_scratch = Dial3dScratch::default();

    let mut out_paths: Vec<Option<Path3>> = vec![None; reqs.len()];
    let mut pending: VecDeque<usize> = (0..reqs.len()).collect();
    let mut in_pending: Vec<bool> = vec![true; reqs.len()];
    let mut iters: usize = 0;
    let mut attempts_without_new_route: usize = 0;
    let stagnation_limit: usize = reqs.len().saturating_mul(4).max(200);

    let requeue_index = RequeueIndex::new(reqs);

    while let Some(i) = pending.pop_front() {
        in_pending[i] = false;
        iters += 1;
        if max_iters > 0 && iters > max_iters {
            break;
        }
        if attempts_without_new_route >= stagnation_limit {
            break;
        }
        if rebuild_every > 0 && (iters % rebuild_every == 0) {
            cost_field = ir.build_cost_field_adjacent(blocked_value, occ_penalty, blocked_penalty);
        }

        let routed_this_iter = (|| -> bool {
            let r = reqs[i];
            let brush = brush_radii.get(i).copied().unwrap_or(0);

            let try_commit = |ir: &mut RoutingIr, p: &Path3| -> Result<Vec<u32>, ()> {
                let conflicts = if brush == 0 {
                    match k9_try_commit_path_occ_3d(ir, &p.points, r.net_id) {
                        Ok(()) => Vec::new(),
                        Err(v) => v,
                    }
                } else {
                    match k9_try_commit_path_occ_3d_brush(ir, &p.points, r.net_id, brush) {
                        Ok(()) => Vec::new(),
                        Err(v) => v,
                    }
                };
                if conflicts.is_empty() {
                    return Ok(Vec::new());
                }
                let mut ids: HashSet<u32> = HashSet::new();
                for c in conflicts {
                    if c.existing == blocked_value {
                        return Err(());
                    }
                    if c.existing != 0 && c.existing != r.net_id {
                        ids.insert(c.existing);
                    }
                }
                Ok(ids.into_iter().collect())
            };

            if let Some(path) = route_dial_3d_for_net_with_scratch(
                ir,
                r.start,
                r.goal,
                blocked_value,
                &cost_field,
                layer_h_costs,
                layer_v_costs,
                layer_d_costs,
                via_cost,
                diag_extra_cost,
                r.net_id,
                &mut strict_scratch,
            ) {
                let min_via_dist = brush.saturating_add(1).max(2);
                if violates_min_via_spacing(&path.points, min_via_dist) {
                    return false;
                }
                match try_commit(ir, &path) {
                    Ok(mut conflicts) => {
                        conflicts.sort();
                        conflicts.dedup();
                        if conflicts.len() > max_ripup_nets_per_attempt {
                            return false;
                        }
                        for nid in &conflicts {
                            k13_uncommit_net_occ_3d(ir, *nid);
                            requeue_index.requeue_net(reqs, *nid, &mut out_paths, &mut pending, &mut in_pending);
                        }
                        if conflicts.is_empty() {
                            out_paths[i] = Some(path);
                            return true;
                        }
                        if matches!(try_commit(ir, &path), Ok(c) if c.is_empty()) {
                            out_paths[i] = Some(path);
                            return true;
                        }
                        return false;
                    }
                    Err(()) => return false,
                }
            }

            let Some(path) = route_dial_3d_for_net_soft_with_scratch(
                ir,
                r.start,
                r.goal,
                blocked_value,
                &cost_field,
                layer_h_costs,
                layer_v_costs,
                layer_d_costs,
                via_cost,
                diag_extra_cost,
                other_net_penalty,
                r.net_id,
                &mut soft_scratch,
            ) else {
                return false;
            };
            let min_via_dist = brush.saturating_add(1).max(2);
            if violates_min_via_spacing(&path.points, min_via_dist) {
                return false;
            }

            let Ok(mut ripup) =
                collect_ripup_net_ids_for_path(ir, &path.points, blocked_value, r.net_id, brush)
            else {
                return false;
            };
            if ripup.len() > max_ripup_nets_per_attempt {
                return false;
            }

            for nid in ripup.drain() {
                k13_uncommit_net_occ_3d(ir, nid);
                requeue_index.requeue_net(reqs, nid, &mut out_paths, &mut pending, &mut in_pending);
            }

            match try_commit(ir, &path) {
                Ok(conflicts) => {
                    if conflicts.is_empty() {
                        out_paths[i] = Some(path);
                        return true;
                    }
                    if conflicts.len() > max_ripup_nets_per_attempt {
                        return false;
                    }
                    for nid in &conflicts {
                        k13_uncommit_net_occ_3d(ir, *nid);
                        requeue_index.requeue_net(reqs, *nid, &mut out_paths, &mut pending, &mut in_pending);
                    }
                    if matches!(try_commit(ir, &path), Ok(c) if c.is_empty()) {
                        out_paths[i] = Some(path);
                        return true;
                    }
                    false
                }
                Err(()) => false,
            }
        })();

        if routed_this_iter {
            attempts_without_new_route = 0;
        } else {
            attempts_without_new_route = attempts_without_new_route.saturating_add(1);
        }
    }

    reqs.iter()
        .enumerate()
        .map(|(i, r)| NetRouteResult {
            net_id: r.net_id,
            path: out_paths[i].clone(),
        })
        .collect()
}

/// Seeded variant of `route_nets_negotiation_basic_dynamic_cost_with_brushes_and_layer_dir_costs`.
///
/// - `seed_paths` is an initial solution state (typically from a fast sequential pass) that is
///   assumed to already be committed into `ir.occ`.
/// - The negotiation loop starts by routing only requests whose seed path is `None`.
/// - Seeded nets may still be ripped up if they block an attempted route; if that happens they are
///   requeued and rerouted (since they exist in `reqs`).
pub fn route_nets_negotiation_seeded_dynamic_cost_with_brushes_and_layer_dir_costs(
    ir: &mut RoutingIr,
    reqs: &[NetRouteRequest],
    blocked_value: u32,
    layer_h_costs: &[u16],
    layer_v_costs: &[u16],
    layer_d_costs: &[u16],
    via_cost: u16,
    brush_radii: &[u8],
    other_net_penalty: u16,
    max_iters: usize,
    max_ripup_nets_per_attempt: usize,
    rebuild_every: usize,
    occ_penalty: u16,
    blocked_penalty: u16,
    seed_paths: &[Option<Path3>],
    allow_ripup_seeded: bool,
) -> Vec<NetRouteResult> {
    if seed_paths.len() != reqs.len() {
        return route_nets_negotiation_basic_dynamic_cost_with_brushes_and_layer_dir_costs(
            ir,
            reqs,
            blocked_value,
            layer_h_costs,
            layer_v_costs,
            layer_d_costs,
            via_cost,
            brush_radii,
            other_net_penalty,
            max_iters,
            max_ripup_nets_per_attempt,
            rebuild_every,
            occ_penalty,
            blocked_penalty,
        );
    }

    let mut cost_field = ir.build_cost_field_adjacent(blocked_value, occ_penalty, blocked_penalty);
    let diag_extra_cost = 1u16;
    let mut strict_scratch = Dial3dScratch::default();
    let mut soft_scratch = Dial3dScratch::default();

    let mut out_paths: Vec<Option<Path3>> = seed_paths.to_vec();
    let mut seeded_net_ids: HashSet<u32> = HashSet::new();
    for (i, p) in seed_paths.iter().enumerate() {
        if p.is_some() {
            seeded_net_ids.insert(reqs[i].net_id);
        }
    }
    let mut pending: VecDeque<usize> = seed_paths
        .iter()
        .enumerate()
        .filter_map(|(i, p)| if p.is_none() { Some(i) } else { None })
        .collect();
    let mut in_pending: Vec<bool> = seed_paths.iter().map(|p| p.is_none()).collect();

    let mut iters: usize = 0;
    let mut attempts_without_new_route: usize = 0;
    let stagnation_limit: usize = reqs.len().saturating_mul(4).max(200);

    let requeue_index = RequeueIndex::new(reqs);

    while let Some(i) = pending.pop_front() {
        in_pending[i] = false;
        iters += 1;
        if max_iters > 0 && iters > max_iters {
            break;
        }
        if attempts_without_new_route >= stagnation_limit {
            break;
        }
        if rebuild_every > 0 && (iters % rebuild_every == 0) {
            cost_field = ir.build_cost_field_adjacent(blocked_value, occ_penalty, blocked_penalty);
        }

        let routed_this_iter = (|| -> bool {
            let r = reqs[i];
            let brush = brush_radii.get(i).copied().unwrap_or(0);

            let try_commit = |ir: &mut RoutingIr, p: &Path3| -> Result<Vec<u32>, ()> {
                let conflicts = if brush == 0 {
                    match k9_try_commit_path_occ_3d(ir, &p.points, r.net_id) {
                        Ok(()) => Vec::new(),
                        Err(v) => v,
                    }
                } else {
                    match k9_try_commit_path_occ_3d_brush(ir, &p.points, r.net_id, brush) {
                        Ok(()) => Vec::new(),
                        Err(v) => v,
                    }
                };
                if conflicts.is_empty() {
                    return Ok(Vec::new());
                }
                let mut ids: HashSet<u32> = HashSet::new();
                for c in conflicts {
                    if c.existing == blocked_value {
                        return Err(());
                    }
                    if c.existing != 0 && c.existing != r.net_id {
                        ids.insert(c.existing);
                    }
                }
                Ok(ids.into_iter().collect())
            };

            if let Some(path) = route_dial_3d_for_net_with_scratch(
                ir,
                r.start,
                r.goal,
                blocked_value,
                &cost_field,
                layer_h_costs,
                layer_v_costs,
                layer_d_costs,
                via_cost,
                diag_extra_cost,
                r.net_id,
                &mut strict_scratch,
            ) {
                let min_via_dist = brush.saturating_add(1).max(2);
                if violates_min_via_spacing(&path.points, min_via_dist) {
                    return false;
                }
                match try_commit(ir, &path) {
                    Ok(mut conflicts) => {
                        conflicts.sort();
                        conflicts.dedup();
                        if conflicts.len() > max_ripup_nets_per_attempt {
                            return false;
                        }
                        if !allow_ripup_seeded && conflicts.iter().any(|nid| seeded_net_ids.contains(nid)) {
                            return false;
                        }
                        for nid in &conflicts {
                            k13_uncommit_net_occ_3d(ir, *nid);
                            requeue_index.requeue_net(
                                reqs,
                                *nid,
                                &mut out_paths,
                                &mut pending,
                                &mut in_pending,
                            );
                        }
                        if conflicts.is_empty() {
                            out_paths[i] = Some(path);
                            return true;
                        }
                        if matches!(try_commit(ir, &path), Ok(c) if c.is_empty()) {
                            out_paths[i] = Some(path);
                            return true;
                        }
                        return false;
                    }
                    Err(()) => return false,
                }
            }

            let Some(path) = route_dial_3d_for_net_soft_with_scratch(
                ir,
                r.start,
                r.goal,
                blocked_value,
                &cost_field,
                layer_h_costs,
                layer_v_costs,
                layer_d_costs,
                via_cost,
                diag_extra_cost,
                other_net_penalty,
                r.net_id,
                &mut soft_scratch,
            ) else {
                return false;
            };
            let min_via_dist = brush.saturating_add(1).max(2);
            if violates_min_via_spacing(&path.points, min_via_dist) {
                return false;
            }

            let Ok(mut ripup) =
                collect_ripup_net_ids_for_path(ir, &path.points, blocked_value, r.net_id, brush)
            else {
                return false;
            };
            if ripup.len() > max_ripup_nets_per_attempt {
                return false;
            }
            if !allow_ripup_seeded && ripup.iter().any(|nid| seeded_net_ids.contains(nid)) {
                return false;
            }

            for nid in ripup.drain() {
                k13_uncommit_net_occ_3d(ir, nid);
                requeue_index.requeue_net(reqs, nid, &mut out_paths, &mut pending, &mut in_pending);
            }

            match try_commit(ir, &path) {
                Ok(conflicts) => {
                    if conflicts.is_empty() {
                        out_paths[i] = Some(path);
                        return true;
                    }
                    if conflicts.len() > max_ripup_nets_per_attempt {
                        return false;
                    }
                    if !allow_ripup_seeded && conflicts.iter().any(|nid| seeded_net_ids.contains(nid)) {
                        return false;
                    }
                    for nid in &conflicts {
                        k13_uncommit_net_occ_3d(ir, *nid);
                        requeue_index.requeue_net(
                            reqs,
                            *nid,
                            &mut out_paths,
                            &mut pending,
                            &mut in_pending,
                        );
                    }
                    if matches!(try_commit(ir, &path), Ok(c) if c.is_empty()) {
                        out_paths[i] = Some(path);
                        return true;
                    }
                    false
                }
                Err(()) => false,
            }
        })();

        if routed_this_iter {
            attempts_without_new_route = 0;
        } else {
            attempts_without_new_route = attempts_without_new_route.saturating_add(1);
        }
    }

    reqs.iter()
        .enumerate()
        .map(|(i, r)| NetRouteResult {
            net_id: r.net_id,
            path: out_paths[i].clone(),
        })
        .collect()
}

/// Route a multi-pin net by routing the Manhattan MST edges sequentially (2D MST; 3D routing).
///
/// Returns the number of routed MST edges (should be `pins.len()-1` on success).
pub fn route_net_mst(
    ir: &mut RoutingIr,
    net_id: u32,
    pins: &[Point3],
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
) -> Result<usize, String> {
    route_net_mst_with_brush(ir, net_id, pins, blocked_value, cost_field, via_cost, 0)
}

/// Variant of `route_net_mst` that commits routes with a circular brush.
///
/// `brush_radius` is in grid cells. Use `0` for the old behavior.
pub fn route_net_mst_with_brush(
    ir: &mut RoutingIr,
    net_id: u32,
    pins: &[Point3],
    blocked_value: u32,
    cost_field: &[u16],
    via_cost: u16,
    brush_radius: u8,
) -> Result<usize, String> {
    if pins.len() <= 1 {
        return Ok(0);
    }
    let pts2: Vec<Point> = pins.iter().map(|p| Point { x: p.x, y: p.y }).collect();
    let edges = mst_manhattan(&pts2);
    let mut routed = 0usize;
    let diag_extra_cost = 1u16;
    let mut scratch = Dial3dScratch::default();

    for (a, b) in edges {
        let start = pins[a];
        let goal = pins[b];
        let Some(path) = route_dial_3d_for_net_with_scratch(
            ir,
            start,
            goal,
            blocked_value,
            cost_field,
            &[],
            &[],
            &[],
            via_cost,
            diag_extra_cost,
            net_id,
            &mut scratch,
        ) else {
            return Err(format!("failed to route MST edge {a}-{b}"));
        };
        let conflicts = if brush_radius == 0 {
            k9_commit_path_occ_3d(ir, &path.points, net_id)
        } else {
            k9_commit_path_occ_3d_brush(ir, &path.points, net_id, brush_radius)
        };
        if !conflicts.is_empty() {
            k13_uncommit_net_occ_3d(ir, net_id);
            return Err(format!("conflicts committing MST edge {a}-{b}"));
        }
        routed += 1;
    }

    Ok(routed)
}

/// Variant of `route_net_mst_with_brush` that applies per-layer direction costs.
pub fn route_net_mst_with_brush_and_layer_dir_costs(
    ir: &mut RoutingIr,
    net_id: u32,
    pins: &[Point3],
    blocked_value: u32,
    cost_field: &[u16],
    layer_h_costs: &[u16],
    layer_v_costs: &[u16],
    layer_d_costs: &[u16],
    via_cost: u16,
    brush_radius: u8,
) -> Result<usize, String> {
    if pins.len() <= 1 {
        return Ok(0);
    }
    let pts2: Vec<Point> = pins.iter().map(|p| Point { x: p.x, y: p.y }).collect();
    let edges = mst_manhattan(&pts2);
    let mut routed = 0usize;
    let diag_extra_cost = 1u16;
    let mut scratch = Dial3dScratch::default();

    for (a, b) in edges {
        let start = pins[a];
        let goal = pins[b];
        let Some(path) = route_dial_3d_for_net_with_scratch(
            ir,
            start,
            goal,
            blocked_value,
            cost_field,
            layer_h_costs,
            layer_v_costs,
            layer_d_costs,
            via_cost,
            diag_extra_cost,
            net_id,
            &mut scratch,
        ) else {
            return Err(format!("failed to route MST edge {a}-{b}"));
        };
        let conflicts = if brush_radius == 0 {
            k9_commit_path_occ_3d(ir, &path.points, net_id)
        } else {
            k9_commit_path_occ_3d_brush(ir, &path.points, net_id, brush_radius)
        };
        if !conflicts.is_empty() {
            k13_uncommit_net_occ_3d(ir, net_id);
            return Err(format!("conflicts committing MST edge {a}-{b}"));
        }
        routed += 1;
    }

    Ok(routed)
}

#[cfg(test)]
mod requeue_index_tests {
    use super::*;

    #[test]
    fn requeue_net_clears_all_paths_and_avoids_duplicate_queue_entries() {
        let reqs = vec![
            NetRouteRequest {
                net_id: 10,
                start: Point3 { layer: 0, x: 0, y: 0 },
                goal: Point3 { layer: 0, x: 1, y: 0 },
            },
            NetRouteRequest {
                net_id: 10,
                start: Point3 { layer: 0, x: 0, y: 1 },
                goal: Point3 { layer: 0, x: 1, y: 1 },
            },
            NetRouteRequest {
                net_id: 20,
                start: Point3 { layer: 0, x: 0, y: 2 },
                goal: Point3 { layer: 0, x: 1, y: 2 },
            },
        ];

        let idx = RequeueIndex::new(&reqs);
        let mut out_paths: Vec<Option<Path3>> = vec![
            Some(Path3 { points: vec![reqs[0].start, reqs[0].goal] }),
            Some(Path3 { points: vec![reqs[1].start, reqs[1].goal] }),
            Some(Path3 { points: vec![reqs[2].start, reqs[2].goal] }),
        ];
        let mut pending: VecDeque<usize> = VecDeque::new();
        let mut in_pending: Vec<bool> = vec![false; reqs.len()];

        idx.requeue_net(&reqs, 10, &mut out_paths, &mut pending, &mut in_pending);
        assert_eq!(out_paths[0], None);
        assert_eq!(out_paths[1], None);
        assert!(out_paths[2].is_some());
        assert_eq!(pending.len(), 2);

        // Calling again should not enqueue duplicates.
        idx.requeue_net(&reqs, 10, &mut out_paths, &mut pending, &mut in_pending);
        assert_eq!(pending.len(), 2);

        // Requeue another net and ensure the original stays deduped.
        idx.requeue_net(&reqs, 20, &mut out_paths, &mut pending, &mut in_pending);
        assert_eq!(pending.len(), 3);
    }
}

fn dirs_for_seed(seed: u64) -> [(isize, isize); 4] {
    // Minimal seeded tie-break hook: two deterministic direction permutations.
    // This is designed to be replaced by a full deterministic shuffler later.
    if seed & 1 == 0 {
        [(1, 0), (0, 1), (-1, 0), (0, -1)] // R, D, L, U
    } else {
        [(0, 1), (1, 0), (0, -1), (-1, 0)] // D, R, U, L
    }
}

/// Seeded BFS variant: identical seed => identical tie-breaks.
pub fn route_bfs_2d_seeded(
    ir: &RoutingIr,
    layer: usize,
    start: Point,
    goal: Point,
    blocked_value: u32,
    seed: u64,
) -> Option<Path> {
    if start.x >= ir.width
        || start.y >= ir.height
        || goal.x >= ir.width
        || goal.y >= ir.height
        || layer >= ir.layers
    {
        return None;
    }

    let start_i = start.y * ir.width + start.x;
    let goal_i = goal.y * ir.width + goal.x;
    let n = ir.width * ir.height;

    let mut prev: Vec<i32> = vec![-1; n];
    let mut q: std::collections::VecDeque<usize> = std::collections::VecDeque::new();

    let occ0 = ir.get_occ(layer, start.x, start.y);
    let occg = ir.get_occ(layer, goal.x, goal.y);
    if occ0 == blocked_value || occg == blocked_value {
        return None;
    }

    prev[start_i] = start_i as i32;
    q.push_back(start_i);

    let dirs = dirs_for_seed(seed);

    while let Some(cur) = q.pop_front() {
        if cur == goal_i {
            break;
        }
        let cx = (cur % ir.width) as isize;
        let cy = (cur / ir.width) as isize;

        for (dx, dy) in dirs {
            let nx = cx + dx;
            let ny = cy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= ir.width || nyu >= ir.height {
                continue;
            }
            if ir.get_occ(layer, nxu, nyu) == blocked_value {
                continue;
            }
            let ni = nyu * ir.width + nxu;
            if prev[ni] != -1 {
                continue;
            }
            prev[ni] = cur as i32;
            q.push_back(ni);
        }
    }

    if prev[goal_i] == -1 {
        return None;
    }

    let mut points: Vec<Point> = Vec::new();
    let mut cur = goal_i;
    loop {
        points.push(Point {
            x: cur % ir.width,
            y: cur / ir.width,
        });
        let p = prev[cur] as usize;
        if p == cur {
            break;
        }
        cur = p;
    }
    points.reverse();

    Some(Path { layer, points })
}
