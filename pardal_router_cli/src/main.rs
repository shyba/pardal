use pardal_router_core::router::Point3;
use serde::Deserialize;
use std::cmp::Ordering;
use std::collections::BinaryHeap;
use std::f64::consts::PI;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Clone, Copy, Debug, Default)]
struct AStarStats {
    heap_push: u64,
    heap_pop: u64,
    relax_attempts: u64,
    relax_success: u64,
    rej_bounds: u64,
    rej_base_blocked: u64,
    rej_forbidden: u64,
    rej_occ_other: u64,
    rej_ko_track: u64,
    rej_ko_via: u64,
}

#[derive(Clone, Debug, Default)]
struct RouterStats {
    elapsed_ms_total: u128,
    astar: AStarStats,
    per_spec: Vec<PerSpecStats>,
}

#[derive(Clone, Debug, Default)]
struct PerSpecStats {
    spec_idx: usize,
    net: String,
    elapsed_ms: u128,
    astar: AStarStats,
}

fn write_progress(
    progress_path: &PathBuf,
    cfg: RouteConfig,
    phase: &str,
    pass: usize,
    current_spec: Option<usize>,
    routes: &Vec<Option<RouteRecord>>,
    stats: &RouterStats,
    failed_idxs: &Vec<usize>,
    grid: &Grid,
    elapsed_ms: u128,
) {
    if cfg.progress_every == 0 {
        return;
    }
    let completed = routes.iter().filter(|r| r.is_some()).count();
    let mut astar = AStarStats::default();
    if cfg.emit_stats {
        for s in &stats.per_spec {
            astar.heap_push = astar.heap_push.saturating_add(s.astar.heap_push);
            astar.heap_pop = astar.heap_pop.saturating_add(s.astar.heap_pop);
            astar.relax_attempts = astar.relax_attempts.saturating_add(s.astar.relax_attempts);
            astar.relax_success = astar.relax_success.saturating_add(s.astar.relax_success);
            astar.rej_bounds = astar.rej_bounds.saturating_add(s.astar.rej_bounds);
            astar.rej_base_blocked =
                astar.rej_base_blocked.saturating_add(s.astar.rej_base_blocked);
            astar.rej_forbidden = astar.rej_forbidden.saturating_add(s.astar.rej_forbidden);
            astar.rej_occ_other = astar.rej_occ_other.saturating_add(s.astar.rej_occ_other);
            astar.rej_ko_track = astar.rej_ko_track.saturating_add(s.astar.rej_ko_track);
            astar.rej_ko_via = astar.rej_ko_via.saturating_add(s.astar.rej_ko_via);
        }
    }
    let payload = serde_json::json!({
        "backend": "pardal_router_cli",
        "phase": phase,
        "pass": pass,
        "current_spec": current_spec,
        "elapsed_ms": elapsed_ms,
        "completed_specs": completed,
        "total_specs": routes.len(),
        "failed_specs": failed_idxs.len(),
        "grid_overused_cells": grid_overuse_stats(grid).0,
        "stats_total": if cfg.emit_stats { serde_json::json!({
            "elapsed_ms": elapsed_ms,
            "astar": {
                "heap_push": astar.heap_push,
                "heap_pop": astar.heap_pop,
                "relax_attempts": astar.relax_attempts,
                "relax_success": astar.relax_success,
                "rej_bounds": astar.rej_bounds,
                "rej_base_blocked": astar.rej_base_blocked,
                "rej_forbidden": astar.rej_forbidden,
                "rej_occ_other": astar.rej_occ_other,
                "rej_ko_track": astar.rej_ko_track,
                "rej_ko_via": astar.rej_ko_via
            }
        }) } else { serde_json::Value::Null },
        "stats_by_spec": if cfg.emit_stats {
            serde_json::Value::Array(stats.per_spec.iter().map(|s| serde_json::json!({
                "spec_idx": s.spec_idx,
                "net": s.net,
                "elapsed_ms": s.elapsed_ms,
                "astar": {
                    "heap_push": s.astar.heap_push,
                    "heap_pop": s.astar.heap_pop,
                    "relax_attempts": s.astar.relax_attempts,
                    "relax_success": s.astar.relax_success
                }
            })).collect())
        } else {
            serde_json::Value::Null
        },
    });
    let _ = fs::write(
        progress_path,
        serde_json::to_string_pretty(&payload).unwrap_or_default(),
    );
}

#[derive(Debug, Deserialize)]
struct Problem {
    version: u32,
    resolution_mm: f64,
    inflate_mm: f64,
    layers: Vec<String>,
    width: usize,
    height: usize,
    net_defaults: NetDefaults,
    circles: Vec<CircleObstacle>,
    #[serde(default)]
    existing_vias: Vec<ExistingVia>,
    nets: Vec<NetSpec>,
}

#[derive(Debug, Deserialize)]
struct NetDefaults {
    track_width_mm: f64,
    clearance_mm: f64,
    via_diameter_mm: f64,
    via_drill_mm: f64,
    uvia_diameter_mm: f64,
    uvia_drill_mm: f64,
}

#[derive(Debug, Deserialize)]
struct CircleObstacle {
    net: String,
    net_id: u32,
    layers: Vec<usize>,
    center: XY,
    r: usize,
}

#[derive(Debug, Deserialize)]
struct ExistingVia {
    net: String,
    net_id: u32,
    layers: Vec<usize>,
    center: XY,
    size_mm: f64,
}

#[derive(Debug, Deserialize)]
struct XY {
    x: usize,
    y: usize,
}

#[derive(Debug, Deserialize, Clone)]
struct NetSpec {
    net: String,
    net_id: u32,
    start: Point3,
    goal: Point3,
    track_width_mm: f64,
    via_diameter_mm: f64,
    via_drill_mm: f64,
    uvia_diameter_mm: f64,
    uvia_drill_mm: f64,
}

#[derive(Debug, Deserialize, Clone, Copy)]
struct RouteConfig {
    #[serde(default = "default_margin_init")]
    margin_init: usize,
    #[serde(default = "default_margin_step")]
    margin_step: usize,
    #[serde(default = "default_margin_max")]
    margin_max: usize,
    #[serde(default = "default_via_penalty")]
    via_penalty: u32,
    #[serde(default = "default_allow_diagonal")]
    diagonal: bool,
    #[serde(default = "default_ripup_passes")]
    ripup_passes: usize,
    #[serde(default = "default_ripup_k")]
    ripup_k: usize,
    #[serde(default = "default_escape_enable")]
    escape_enable: bool,
    #[serde(default = "default_escape_margin")]
    escape_margin: usize,
    #[serde(default = "default_attempts")]
    attempts: usize,
    #[serde(default = "default_seed")]
    seed: u64,
    #[serde(default = "default_keepout_clearance_scale")]
    keepout_clearance_scale: f64,
    #[serde(default = "default_keepout_safety_mm")]
    keepout_safety_mm: f64,
    #[serde(default)]
    keepout_track_cells: Option<usize>,
    #[serde(default)]
    keepout_via_cells: Option<usize>,
    #[serde(default = "default_commit_routes")]
    commit_routes: bool,
    // Negotiated congestion routing (PathFinder-style) to resolve overlaps.
    // When `ncr_iters > 0`, routing allows temporary overlaps and iteratively
    // reroutes nets until no grid cell is overused (capacity=1) or we hit the
    // iteration limit.
    #[serde(default = "default_ncr_iters")]
    ncr_iters: usize,
    #[serde(default = "default_ncr_present_cost")]
    ncr_present_cost: u32,
    #[serde(default = "default_ncr_history_cost")]
    ncr_history_cost: u32,
    #[serde(default = "default_ncr_history_inc")]
    ncr_history_inc: u16,
    #[serde(default = "default_ncr_allow_overlaps")]
    ncr_allow_overlaps: bool,
	    #[serde(default = "default_enforce_spacing")]
	    enforce_spacing: bool,
	    #[serde(default = "default_enforce_touch")]
	    enforce_touch: bool,
	    // When NCR is enabled, optionally keep vias out of spacing violations even if tracks
	    // are allowed to treat spacing as a soft constraint.
	    #[serde(default = "default_via_spacing_hard")]
	    via_spacing_hard: bool,
    // If NCR allowed overlaps, reroute under strict constraints at the end.
    #[serde(default = "default_legalize_passes")]
    legalize_passes: usize,
    #[serde(default = "default_emit_stats")]
    emit_stats: bool,
    #[serde(default = "default_progress_every")]
    progress_every: usize,
    // Weighted A*: f = g + w*h (w in percent, 100 == classic A*).
    #[serde(default = "default_heuristic_weight_pct")]
    heuristic_weight_pct: u32,
    // When spacing is enabled and overlaps are allowed, apply a soft penalty for
    // stepping into cells that violate spacing vs already-committed copper.
    #[serde(default = "default_spacing_present_cost")]
    spacing_present_cost: u32,
    #[serde(default = "default_spacing_present_cap")]
    spacing_present_cap: u16,
    #[serde(default = "default_layer_penalty_outer")]
    layer_penalty_outer: u32,
    #[serde(default = "default_layer_penalty_in1")]
    layer_penalty_in1: u32,
    #[serde(default = "default_layer_penalty_inner")]
    layer_penalty_inner: u32,
}

fn default_margin_init() -> usize {
    128
}
fn default_margin_step() -> usize {
    128
}
fn default_margin_max() -> usize {
    0
}
fn default_via_penalty() -> u32 {
    40
}
fn default_allow_diagonal() -> bool {
    true
}
fn default_ripup_passes() -> usize {
    2
}
fn default_ripup_k() -> usize {
    8
}
fn default_escape_enable() -> bool {
    false
}
fn default_escape_margin() -> usize {
    50
}
fn default_attempts() -> usize {
    6
}
fn default_seed() -> u64 {
    0
}
fn default_keepout_clearance_scale() -> f64 {
    1.0
}
fn default_keepout_safety_mm() -> f64 {
    0.0
}
fn default_commit_routes() -> bool {
    true
}
fn default_ncr_iters() -> usize {
    0
}
fn default_ncr_present_cost() -> u32 {
    60
}
fn default_ncr_history_cost() -> u32 {
    10
}
fn default_ncr_history_inc() -> u16 {
    1
}
fn default_ncr_allow_overlaps() -> bool {
    true
}
fn default_enforce_spacing() -> bool {
    false
}
fn default_enforce_touch() -> bool {
    false
}
fn default_via_spacing_hard() -> bool {
    false
}
fn default_legalize_passes() -> usize {
    2
}
fn default_emit_stats() -> bool {
    true
}
fn default_progress_every() -> usize {
    0
}
fn default_heuristic_weight_pct() -> u32 {
    100
}
fn default_spacing_present_cost() -> u32 {
    800
}
fn default_spacing_present_cap() -> u16 {
    30
}
fn default_layer_penalty_outer() -> u32 {
    6
}
fn default_layer_penalty_in1() -> u32 {
    3
}
fn default_layer_penalty_inner() -> u32 {
    0
}

#[derive(Clone, Copy, Debug)]
struct NodeState {
    f: u32,
    g: u32,
    idx: usize,
}

impl Eq for NodeState {}

impl PartialEq for NodeState {
    fn eq(&self, other: &Self) -> bool {
        self.f == other.f && self.g == other.g && self.idx == other.idx
    }
}

impl Ord for NodeState {
    fn cmp(&self, other: &Self) -> Ordering {
        // Reverse for min-heap behavior.
        other
            .f
            .cmp(&self.f)
            .then_with(|| other.g.cmp(&self.g))
            .then_with(|| other.idx.cmp(&self.idx))
    }
}

impl PartialOrd for NodeState {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

fn occ_allows(occ: u32, net_id: u32, blocked_value: u32) -> bool {
    if occ == blocked_value {
        return false;
    }
    occ == 0 || occ == net_id
}

#[derive(Clone, Copy, Debug, Default)]
struct BBox {
    x0: usize,
    y0: usize,
    x1: usize,
    y1: usize,
}

impl BBox {
    fn from_points(a: Point3, b: Point3, width: usize, height: usize) -> Self {
        let (minx, maxx) = if a.x <= b.x { (a.x, b.x) } else { (b.x, a.x) };
        let (miny, maxy) = if a.y <= b.y { (a.y, b.y) } else { (b.y, a.y) };
        Self {
            x0: minx.min(width.saturating_sub(1)),
            y0: miny.min(height.saturating_sub(1)),
            x1: (maxx + 1).min(width),
            y1: (maxy + 1).min(height),
        }
    }

    fn expand(&self, margin: usize, width: usize, height: usize) -> Self {
        Self {
            x0: self.x0.saturating_sub(margin),
            y0: self.y0.saturating_sub(margin),
            x1: (self.x1 + margin).min(width),
            y1: (self.y1 + margin).min(height),
        }
    }

    fn intersects(&self, other: &Self) -> bool {
        self.x0 < other.x1 && self.x1 > other.x0 && self.y0 < other.y1 && self.y1 > other.y0
    }

    fn is_valid(&self) -> bool {
        self.x0 < self.x1 && self.y0 < self.y1
    }
}

struct Grid {
    layers: usize,
    width: usize,
    height: usize,
    base_occ: Vec<u32>,
    // Dynamic occupancy counts for already-committed routes.
    // `track_usage` marks routed copper segments; `via_usage` marks via centers.
    track_usage: Vec<u16>,
    via_usage: Vec<u16>,
    // Best-effort per-cell ownership, used to ignore same-net occupancy when overlaps are disallowed.
    // If a cell is used by multiple nets (only possible when overlaps are allowed), owner is `u32::MAX`.
    track_owner: Vec<u32>,
    via_owner: Vec<u32>,
    // Dynamic keepout fields for clearance-aware routing.
    // These are stamped from committed routes so spacing checks can be O(1).
    ko_track: Vec<u16>,
    ko_via: Vec<u16>,
    ko_track_owner: Vec<u32>,
    ko_via_owner: Vec<u32>,
    // "Touch" keepout fields (prevent copper overlap / shorts). These are smaller than
    // full clearance and are always enforced as hard constraints.
    touch_track: Vec<u16>,
    touch_via: Vec<u16>,
    touch_track_owner: Vec<u32>,
    touch_via_owner: Vec<u32>,
    // Negotiated congestion "history" cost per cell (saturated).
    history: Vec<u16>,
    // Indices that have been occupied at least once (may include stale zeros).
    touched: Vec<usize>,
    touched_mark: Vec<u8>,
}

#[derive(Clone)]
struct RouteRecord {
    spec_idx: usize,
    net_id: u32,
    path: Vec<Point3>,
    track_stamped: Vec<usize>,
    via_stamped: Vec<usize>,
    bbox: BBox,
}

impl Grid {
    fn new(layers: usize, width: usize, height: usize) -> Self {
        let n = layers
            .checked_mul(width)
            .and_then(|v| v.checked_mul(height))
            .expect("grid too large");
        Self {
            layers,
            width,
            height,
            base_occ: vec![0; n],
            track_usage: vec![0; n],
            via_usage: vec![0; n],
            track_owner: vec![0; n],
            via_owner: vec![0; n],
            ko_track: vec![0; n],
            ko_via: vec![0; n],
            ko_track_owner: vec![0; n],
            ko_via_owner: vec![0; n],
            touch_track: vec![0; n],
            touch_via: vec![0; n],
            touch_track_owner: vec![0; n],
            touch_via_owner: vec![0; n],
            history: vec![0; n],
            touched: Vec::new(),
            touched_mark: vec![0; n],
        }
    }

    #[inline]
    fn idx(&self, layer: usize, x: usize, y: usize) -> usize {
        (layer * self.width * self.height) + (y * self.width + x)
    }

    #[inline]
    fn base_at(&self, layer: usize, x: usize, y: usize) -> u32 {
        self.base_occ[self.idx(layer, x, y)]
    }

    #[inline]
    fn occ_total_at_idx(&self, idx: usize) -> u16 {
        self.track_usage[idx].saturating_add(self.via_usage[idx])
    }

    #[inline]
    fn occ_other_at_idx(&self, idx: usize, net_id: u32) -> u16 {
        let mut out: u16 = 0;
        let t = self.track_usage[idx];
        if t != 0 && self.track_owner[idx] != net_id {
            out = out.saturating_add(t);
        }
        let v = self.via_usage[idx];
        if v != 0 && self.via_owner[idx] != net_id {
            out = out.saturating_add(v);
        }
        out
    }

    #[inline]
    fn ko_track_other_at_idx(&self, idx: usize, net_id: u32) -> u16 {
        let k = self.ko_track[idx];
        if k == 0 {
            return 0;
        }
        let o = self.ko_track_owner[idx];
        if o == net_id {
            0
        } else {
            k
        }
    }

    #[inline]
    fn ko_via_other_at_idx(&self, idx: usize, net_id: u32) -> u16 {
        let k = self.ko_via[idx];
        if k == 0 {
            return 0;
        }
        let o = self.ko_via_owner[idx];
        if o == net_id {
            0
        } else {
            k
        }
    }

    #[inline]
    fn touch_track_other_at_idx(&self, idx: usize, net_id: u32) -> u16 {
        let k = self.touch_track[idx];
        if k == 0 {
            return 0;
        }
        let o = self.touch_track_owner[idx];
        if o == net_id {
            0
        } else {
            k
        }
    }

    #[inline]
    fn touch_via_other_at_idx(&self, idx: usize, net_id: u32) -> u16 {
        let k = self.touch_via[idx];
        if k == 0 {
            return 0;
        }
        let o = self.touch_via_owner[idx];
        if o == net_id {
            0
        } else {
            k
        }
    }

    #[inline]
    fn touch_idx(&mut self, idx: usize) {
        if self.touched_mark[idx] == 0 {
            self.touched.push(idx);
            self.touched_mark[idx] = 1;
        }
    }

    #[inline]
    fn bump_owner(owner: &mut u32, net_id: u32) {
        if *owner == 0 || *owner == net_id {
            *owner = net_id;
        } else {
            *owner = u32::MAX;
        }
    }

    #[inline]
    fn dec_owner(owner: &mut u32, net_id: u32, remaining: u16) {
        if remaining == 0 {
            *owner = 0;
        } else if *owner != net_id {
            *owner = u32::MAX;
        }
    }

    fn stamp_ko_track_at(&mut self, idx: usize, net_id: u32, delta: i16) {
        if delta > 0 {
            if self.ko_track[idx] == 0 {
                self.touch_idx(idx);
            }
            self.ko_track[idx] = self.ko_track[idx].saturating_add(delta as u16);
            Self::bump_owner(&mut self.ko_track_owner[idx], net_id);
        } else {
            let d = (-delta) as u16;
            self.ko_track[idx] = self.ko_track[idx].saturating_sub(d);
            Self::dec_owner(&mut self.ko_track_owner[idx], net_id, self.ko_track[idx]);
        }
    }

    fn stamp_ko_via_at(&mut self, idx: usize, net_id: u32, delta: i16) {
        if delta > 0 {
            if self.ko_via[idx] == 0 {
                self.touch_idx(idx);
            }
            self.ko_via[idx] = self.ko_via[idx].saturating_add(delta as u16);
            Self::bump_owner(&mut self.ko_via_owner[idx], net_id);
        } else {
            let d = (-delta) as u16;
            self.ko_via[idx] = self.ko_via[idx].saturating_sub(d);
            Self::dec_owner(&mut self.ko_via_owner[idx], net_id, self.ko_via[idx]);
        }
    }

    fn stamp_touch_track_at(&mut self, idx: usize, net_id: u32, delta: i16) {
        if delta > 0 {
            if self.touch_track[idx] == 0 {
                self.touch_idx(idx);
            }
            self.touch_track[idx] = self.touch_track[idx].saturating_add(delta as u16);
            Self::bump_owner(&mut self.touch_track_owner[idx], net_id);
        } else {
            let d = (-delta) as u16;
            self.touch_track[idx] = self.touch_track[idx].saturating_sub(d);
            Self::dec_owner(&mut self.touch_track_owner[idx], net_id, self.touch_track[idx]);
        }
    }

    fn stamp_touch_via_at(&mut self, idx: usize, net_id: u32, delta: i16) {
        if delta > 0 {
            if self.touch_via[idx] == 0 {
                self.touch_idx(idx);
            }
            self.touch_via[idx] = self.touch_via[idx].saturating_add(delta as u16);
            Self::bump_owner(&mut self.touch_via_owner[idx], net_id);
        } else {
            let d = (-delta) as u16;
            self.touch_via[idx] = self.touch_via[idx].saturating_sub(d);
            Self::dec_owner(&mut self.touch_via_owner[idx], net_id, self.touch_via[idx]);
        }
    }

    fn stamp_keepout_for_route(
        &mut self,
        net_id: u32,
        track_indices: &[usize],
        via_indices: &[usize],
        spacing: &SpacingBundle,
        delta: i16,
    ) {
        let w = self.width;
        let h = self.height;
        for &idx in track_indices {
            let p = unidx3(idx, w, h);
            let layer = p.layer;
            let x = p.x as isize;
            let y = p.y as isize;
            for &(dx, dy) in &spacing.clear.track_vs_track {
                let nx = x + dx;
                let ny = y + dy;
                if nx < 0 || ny < 0 {
                    continue;
                }
                let (nxu, nyu) = (nx as usize, ny as usize);
                if nxu >= w || nyu >= h {
                    continue;
                }
                self.stamp_ko_track_at(self.idx(layer, nxu, nyu), net_id, delta);
            }
            for &(dx, dy) in &spacing.clear.track_vs_via {
                let nx = x + dx;
                let ny = y + dy;
                if nx < 0 || ny < 0 {
                    continue;
                }
                let (nxu, nyu) = (nx as usize, ny as usize);
                if nxu >= w || nyu >= h {
                    continue;
                }
                self.stamp_ko_via_at(self.idx(layer, nxu, nyu), net_id, delta);
            }
            for &(dx, dy) in &spacing.touch.track_vs_via {
                let nx = x + dx;
                let ny = y + dy;
                if nx < 0 || ny < 0 {
                    continue;
                }
                let (nxu, nyu) = (nx as usize, ny as usize);
                if nxu >= w || nyu >= h {
                    continue;
                }
                self.stamp_touch_via_at(self.idx(layer, nxu, nyu), net_id, delta);
            }
        }
        for &idx in via_indices {
            let p = unidx3(idx, w, h);
            let layer = p.layer;
            let x = p.x as isize;
            let y = p.y as isize;
            for &(dx, dy) in &spacing.clear.via_vs_track {
                let nx = x + dx;
                let ny = y + dy;
                if nx < 0 || ny < 0 {
                    continue;
                }
                let (nxu, nyu) = (nx as usize, ny as usize);
                if nxu >= w || nyu >= h {
                    continue;
                }
                self.stamp_ko_track_at(self.idx(layer, nxu, nyu), net_id, delta);
            }
            for &(dx, dy) in &spacing.clear.via_vs_via {
                let nx = x + dx;
                let ny = y + dy;
                if nx < 0 || ny < 0 {
                    continue;
                }
                let (nxu, nyu) = (nx as usize, ny as usize);
                if nxu >= w || nyu >= h {
                    continue;
                }
                self.stamp_ko_via_at(self.idx(layer, nxu, nyu), net_id, delta);
            }
            for &(dx, dy) in &spacing.touch.via_vs_track {
                let nx = x + dx;
                let ny = y + dy;
                if nx < 0 || ny < 0 {
                    continue;
                }
                let (nxu, nyu) = (nx as usize, ny as usize);
                if nxu >= w || nyu >= h {
                    continue;
                }
                self.stamp_touch_track_at(self.idx(layer, nxu, nyu), net_id, delta);
            }
            for &(dx, dy) in &spacing.touch.via_vs_via {
                let nx = x + dx;
                let ny = y + dy;
                if nx < 0 || ny < 0 {
                    continue;
                }
                let (nxu, nyu) = (nx as usize, ny as usize);
                if nxu >= w || nyu >= h {
                    continue;
                }
                self.stamp_touch_via_at(self.idx(layer, nxu, nyu), net_id, delta);
            }
        }
    }

    #[inline]
    fn occ_total_at(&self, layer: usize, x: usize, y: usize) -> u16 {
        self.occ_total_at_idx(self.idx(layer, x, y))
    }

    #[inline]
    fn base_allows(
        &self,
        layer: usize,
        x: usize,
        y: usize,
        net_id: u32,
        blocked_value: u32,
    ) -> bool {
        let b = self.base_at(layer, x, y);
        if b == blocked_value {
            return false;
        }
        if b != 0 && b != net_id {
            return false;
        }
        true
    }

    #[inline]
    fn step_cost(
        &self,
        idx: usize,
        net_id: u32,
        cfg: RouteConfig,
        ignore_congestion: bool,
    ) -> u32 {
        if ignore_congestion {
            return 0;
        }
        let u = self.occ_other_at_idx(idx, net_id) as u32;
        // When evaluating a step into a cell, assume we'll consume that resource.
        // For already-occupied cells, this biases away from creating overuse.
        let u_eff = if u == 0 { 0 } else { u.saturating_add(1) };
        let h = self.history[idx] as u32;
        u_eff
            .saturating_mul(cfg.ncr_present_cost)
            .saturating_add(h.saturating_mul(cfg.ncr_history_cost))
    }

    fn stamp_circle_base(
        &mut self,
        layer: usize,
        cx: usize,
        cy: usize,
        r: usize,
        net_id: u32,
        blocked_value: u32,
    ) {
        if layer >= self.layers || cx >= self.width || cy >= self.height {
            return;
        }
        let r_i = r as isize;
        let cx_i = cx as isize;
        let cy_i = cy as isize;
        let r2 = r_i * r_i;
        let x0 = (cx_i - r_i).max(0) as usize;
        let x1 = (cx_i + r_i).min(self.width as isize - 1) as usize;
        let y0 = (cy_i - r_i).max(0) as usize;
        let y1 = (cy_i + r_i).min(self.height as isize - 1) as usize;
        for y in y0..=y1 {
            let dy = y as isize - cy_i;
            let dy2 = dy * dy;
            for x in x0..=x1 {
                let dx = x as isize - cx_i;
                if dx * dx + dy2 > r2 {
                    continue;
                }
                let idx = self.idx(layer, x, y);
                let cur = self.base_occ[idx];
                if cur == 0 || cur == net_id {
                    self.base_occ[idx] = net_id;
                } else {
                    self.base_occ[idx] = blocked_value;
                }
            }
        }
    }

    fn commit_path(
        &mut self,
        net_id: u32,
        points: &[Point3],
        spacing: Option<&SpacingBundle>,
    ) -> (Vec<usize>, Vec<usize>) {
        let mut tracks: Vec<usize> = Vec::new();
        let mut vias: Vec<usize> = Vec::new();
        if points.is_empty() {
            return (tracks, vias);
        }

        for w in points.windows(2) {
            let a = w[0];
            let b = w[1];
            if a.x == b.x && a.y == b.y && a.layer != b.layer {
                vias.push(self.idx(a.layer, a.x, a.y));
                vias.push(self.idx(b.layer, b.x, b.y));
            } else {
                // Mark both endpoints as copper for spacing/occupancy purposes.
                tracks.push(self.idx(a.layer, a.x, a.y));
                tracks.push(self.idx(b.layer, b.x, b.y));
            }
        }

        tracks.sort_unstable();
        tracks.dedup();
        vias.sort_unstable();
        vias.dedup();

        for &idx in tracks.iter().chain(vias.iter()) {
            if self.occ_total_at_idx(idx) == 0 {
                self.touch_idx(idx);
            }
        }
        for &idx in &tracks {
            self.track_usage[idx] = self.track_usage[idx].saturating_add(1);
            let o = self.track_owner[idx];
            if o == 0 || o == net_id {
                self.track_owner[idx] = net_id;
            } else {
                self.track_owner[idx] = u32::MAX;
            }
        }
        for &idx in &vias {
            self.via_usage[idx] = self.via_usage[idx].saturating_add(1);
            let o = self.via_owner[idx];
            if o == 0 || o == net_id {
                self.via_owner[idx] = net_id;
            } else {
                self.via_owner[idx] = u32::MAX;
            }
        }
        if let Some(sp) = spacing {
            self.stamp_keepout_for_route(net_id, &tracks, &vias, sp, 1);
        }
        (tracks, vias)
    }

    fn commit_indices(
        &mut self,
        net_id: u32,
        track_indices: &[usize],
        via_indices: &[usize],
        spacing: Option<&SpacingBundle>,
    ) {
        for &idx in track_indices.iter().chain(via_indices.iter()) {
            if self.occ_total_at_idx(idx) == 0 {
                self.touch_idx(idx);
            }
        }
        for &idx in track_indices {
            self.track_usage[idx] = self.track_usage[idx].saturating_add(1);
            let o = self.track_owner[idx];
            if o == 0 || o == net_id {
                self.track_owner[idx] = net_id;
            } else {
                self.track_owner[idx] = u32::MAX;
            }
        }
        for &idx in via_indices {
            self.via_usage[idx] = self.via_usage[idx].saturating_add(1);
            let o = self.via_owner[idx];
            if o == 0 || o == net_id {
                self.via_owner[idx] = net_id;
            } else {
                self.via_owner[idx] = u32::MAX;
            }
        }
        if let Some(sp) = spacing {
            self.stamp_keepout_for_route(net_id, track_indices, via_indices, sp, 1);
        }
    }

    fn uncommit(
        &mut self,
        net_id: u32,
        track_indices: &[usize],
        via_indices: &[usize],
        spacing: Option<&SpacingBundle>,
    ) {
        for &idx in track_indices {
            self.track_usage[idx] = self.track_usage[idx].saturating_sub(1);
            if self.track_usage[idx] == 0 {
                self.track_owner[idx] = 0;
            } else if self.track_owner[idx] != net_id {
                // In mixed-ownership cells (possible when overlaps are allowed), keep `MAX`.
                self.track_owner[idx] = u32::MAX;
            }
        }
        for &idx in via_indices {
            self.via_usage[idx] = self.via_usage[idx].saturating_sub(1);
            if self.via_usage[idx] == 0 {
                self.via_owner[idx] = 0;
            } else if self.via_owner[idx] != net_id {
                self.via_owner[idx] = u32::MAX;
            }
        }
        if let Some(sp) = spacing {
            self.stamp_keepout_for_route(net_id, track_indices, via_indices, sp, -1);
        }
    }

    #[inline]
    fn track_clear(&self, layer: usize, x: usize, y: usize, net_id: u32, spacing: &Spacing) -> bool {
        if layer >= self.layers || x >= self.width || y >= self.height {
            return false;
        }
        let idx = self.idx(layer, x, y);
        if self.occ_other_at_idx(idx, net_id) != 0 {
            return false;
        }
        for &(dx, dy) in &spacing.track_vs_track {
            let nx = x as isize + dx;
            let ny = y as isize + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= self.width || nyu >= self.height {
                continue;
            }
            let nidx = self.idx(layer, nxu, nyu);
            if self.track_usage[nidx] != 0 && self.track_owner[nidx] != net_id {
                return false;
            }
        }
        for &(dx, dy) in &spacing.track_vs_via {
            let nx = x as isize + dx;
            let ny = y as isize + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= self.width || nyu >= self.height {
                continue;
            }
            let nidx = self.idx(layer, nxu, nyu);
            if self.via_usage[nidx] != 0 && self.via_owner[nidx] != net_id {
                return false;
            }
        }
        true
    }

    #[inline]
    fn via_clear(&self, layer: usize, x: usize, y: usize, net_id: u32, spacing: &Spacing) -> bool {
        if layer >= self.layers || x >= self.width || y >= self.height {
            return false;
        }
        let idx = self.idx(layer, x, y);
        if self.occ_other_at_idx(idx, net_id) != 0 {
            return false;
        }
        for &(dx, dy) in &spacing.via_vs_track {
            let nx = x as isize + dx;
            let ny = y as isize + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= self.width || nyu >= self.height {
                continue;
            }
            let nidx = self.idx(layer, nxu, nyu);
            if self.track_usage[nidx] != 0 && self.track_owner[nidx] != net_id {
                return false;
            }
        }
        for &(dx, dy) in &spacing.via_vs_via {
            let nx = x as isize + dx;
            let ny = y as isize + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= self.width || nyu >= self.height {
                continue;
            }
            let nidx = self.idx(layer, nxu, nyu);
            if self.via_usage[nidx] != 0 && self.via_owner[nidx] != net_id {
                return false;
            }
        }
        true
    }

    #[inline]
    fn track_spacing_conflicts(
        &self,
        layer: usize,
        x: usize,
        y: usize,
        net_id: u32,
        spacing: &Spacing,
        cap: u16,
    ) -> u16 {
        if layer >= self.layers || x >= self.width || y >= self.height {
            return cap;
        }
        let mut c: u16 = 0;
        let idx = self.idx(layer, x, y);
        if self.occ_other_at_idx(idx, net_id) != 0 {
            c = c.saturating_add(4);
            if c >= cap {
                return cap;
            }
        }
        for &(dx, dy) in &spacing.track_vs_track {
            let nx = x as isize + dx;
            let ny = y as isize + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= self.width || nyu >= self.height {
                continue;
            }
            let nidx = self.idx(layer, nxu, nyu);
            if self.track_usage[nidx] != 0 && self.track_owner[nidx] != net_id {
                c = c.saturating_add(1);
                if c >= cap {
                    return cap;
                }
            }
        }
        for &(dx, dy) in &spacing.track_vs_via {
            let nx = x as isize + dx;
            let ny = y as isize + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= self.width || nyu >= self.height {
                continue;
            }
            let nidx = self.idx(layer, nxu, nyu);
            if self.via_usage[nidx] != 0 && self.via_owner[nidx] != net_id {
                c = c.saturating_add(1);
                if c >= cap {
                    return cap;
                }
            }
        }
        c
    }

    #[inline]
    fn via_spacing_conflicts(
        &self,
        layer: usize,
        x: usize,
        y: usize,
        net_id: u32,
        spacing: &Spacing,
        cap: u16,
    ) -> u16 {
        if layer >= self.layers || x >= self.width || y >= self.height {
            return cap;
        }
        let mut c: u16 = 0;
        let idx = self.idx(layer, x, y);
        if self.occ_other_at_idx(idx, net_id) != 0 {
            c = c.saturating_add(4);
            if c >= cap {
                return cap;
            }
        }
        for &(dx, dy) in &spacing.via_vs_track {
            let nx = x as isize + dx;
            let ny = y as isize + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= self.width || nyu >= self.height {
                continue;
            }
            let nidx = self.idx(layer, nxu, nyu);
            if self.track_usage[nidx] != 0 && self.track_owner[nidx] != net_id {
                c = c.saturating_add(1);
                if c >= cap {
                    return cap;
                }
            }
        }
        for &(dx, dy) in &spacing.via_vs_via {
            let nx = x as isize + dx;
            let ny = y as isize + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= self.width || nyu >= self.height {
                continue;
            }
            let nidx = self.idx(layer, nxu, nyu);
            if self.via_usage[nidx] != 0 && self.via_owner[nidx] != net_id {
                c = c.saturating_add(1);
                if c >= cap {
                    return cap;
                }
            }
        }
        c
    }
}

#[derive(Clone, Debug)]
struct Spacing {
    // Offsets that would violate spacing if occupied by another item.
    track_vs_track: Vec<(isize, isize)>,
    track_vs_via: Vec<(isize, isize)>,
    via_vs_track: Vec<(isize, isize)>,
    via_vs_via: Vec<(isize, isize)>,
}

#[derive(Clone, Debug)]
struct SpacingBundle {
    clear: Spacing,
    touch: Spacing,
}

fn build_offsets_for_min_dist(min_dist_cells: isize) -> Vec<(isize, isize)> {
    if min_dist_cells <= 1 {
        // Distance < 1 cell only hits the same cell; handled separately.
        return Vec::new();
    }
    let r = min_dist_cells.saturating_sub(1);
    let min2 = min_dist_cells.saturating_mul(min_dist_cells);
    let mut out: Vec<(isize, isize)> = Vec::new();
    for dy in -r..=r {
        for dx in -r..=r {
            if dx == 0 && dy == 0 {
                continue;
            }
            let d2 = dx * dx + dy * dy;
            if d2 < min2 {
                out.push((dx, dy));
            }
        }
    }
    out
}

fn build_offsets_for_min_dist_mm(min_dist_mm: f64, res_mm: f64) -> Vec<(isize, isize)> {
    if !(min_dist_mm.is_finite() && res_mm.is_finite()) || res_mm <= 0.0 || min_dist_mm <= 0.0 {
        return Vec::new();
    }
    // If the minimum distance is <= one cell, only the same cell could violate it, which is
    // handled separately by direct occupancy checks.
    if min_dist_mm <= res_mm {
        return Vec::new();
    }
    // Bound the search window by the maximum cell offset that could still be within `min_dist_mm`.
    let r = (min_dist_mm / res_mm).ceil() as isize;
    let min2 = min_dist_mm * min_dist_mm;
    let eps = 1e-12;
    let mut out: Vec<(isize, isize)> = Vec::new();
    for dy in -r..=r {
        for dx in -r..=r {
            if dx == 0 && dy == 0 {
                continue;
            }
            let fx = (dx as f64) * res_mm;
            let fy = (dy as f64) * res_mm;
            let d2 = fx * fx + fy * fy;
            if d2 + eps < min2 {
                out.push((dx, dy));
            }
        }
    }
    out
}

fn sorted_diff(a: &[usize], b: &[usize]) -> Vec<usize> {
    // Returns sorted `a \\ b` assuming both inputs are sorted and de-duplicated.
    let mut out: Vec<usize> = Vec::with_capacity(a.len());
    let mut i = 0usize;
    let mut j = 0usize;
    while i < a.len() {
        if j >= b.len() {
            out.extend_from_slice(&a[i..]);
            break;
        }
        let av = a[i];
        let bv = b[j];
        if av < bv {
            out.push(av);
            i += 1;
        } else if av > bv {
            j += 1;
        } else {
            // Equal: skip.
            i += 1;
            j += 1;
        }
    }
    out
}

fn heuristic(a: Point3, b: Point3, via_penalty: u32) -> u32 {
    let dx = a.x.abs_diff(b.x) as u32;
    let dy = a.y.abs_diff(b.y) as u32;
    let dl = a.layer.abs_diff(b.layer) as u32;
    dx + dy + dl * via_penalty
}

fn idx3(layer: usize, x: usize, y: usize, w: usize, h: usize) -> usize {
    (layer * w * h) + (y * w + x)
}

fn unidx3(idx: usize, w: usize, h: usize) -> Point3 {
    let n2 = w * h;
    let layer = idx / n2;
    let rem = idx % n2;
    let y = rem / w;
    let x = rem % w;
    Point3 { layer, x, y }
}

fn layer_step_penalty(layer: usize, layers: usize, cfg: RouteConfig) -> u32 {
    if layers <= 2 {
        return 0;
    }
    if layer == 0 || layer + 1 == layers {
        cfg.layer_penalty_outer
    } else if layer == 1 {
        cfg.layer_penalty_in1
    } else {
        cfg.layer_penalty_inner
    }
}

struct AStarWorkspace {
    gscore: Vec<u32>,
    parent: Vec<i32>,
    seen: Vec<u32>,
    gen: u32,
    heap: BinaryHeap<NodeState>,
}

impl AStarWorkspace {
    fn new(n: usize) -> Self {
        Self {
            gscore: vec![0; n],
            parent: vec![-1; n],
            seen: vec![0; n],
            gen: 1,
            heap: BinaryHeap::new(),
        }
    }

    fn reset(&mut self) {
        self.heap.clear();
        self.gen = self.gen.wrapping_add(1);
        if self.gen == 0 {
            self.seen.fill(0);
            self.gen = 1;
        }
    }

    #[inline]
    fn get_g(&self, idx: usize) -> u32 {
        if self.seen[idx] == self.gen {
            self.gscore[idx]
        } else {
            u32::MAX
        }
    }

    #[inline]
    fn set_g(&mut self, idx: usize, g: u32, parent: usize) {
        self.seen[idx] = self.gen;
        self.gscore[idx] = g;
        self.parent[idx] = parent as i32;
    }

    fn extract_path(
        &self,
        start_idx: usize,
        goal_idx: usize,
        w: usize,
        h: usize,
    ) -> Option<Vec<Point3>> {
        if self.seen[goal_idx] != self.gen {
            return None;
        }
        let mut cur = goal_idx;
        let mut out: Vec<Point3> = Vec::new();
        loop {
            out.push(unidx3(cur, w, h));
            if cur == start_idx {
                break;
            }
            let p = self.parent[cur];
            if p < 0 {
                return None;
            }
            cur = p as usize;
        }
        out.reverse();
        Some(out)
    }
}

fn astar_3d_bounded(
    ws: &mut AStarWorkspace,
    grid: &Grid,
    net_id: u32,
    start: Point3,
    goal: Point3,
    blocked_value: u32,
    cfg: RouteConfig,
    bounds: BBox,
    forbidden: Option<&[usize]>,
    allow_routed: Option<Point3>,
    seed: u64,
    emit_stats: bool,
    stats: &mut AStarStats,
) -> Option<Vec<Point3>> {
    if !bounds.is_valid() {
        return None;
    }
    if start.layer >= grid.layers || goal.layer >= grid.layers {
        return None;
    }
    if start.x >= grid.width
        || start.y >= grid.height
        || goal.x >= grid.width
        || goal.y >= grid.height
    {
        return None;
    }
    if start.x < bounds.x0 || start.x >= bounds.x1 || start.y < bounds.y0 || start.y >= bounds.y1 {
        return None;
    }
    if goal.x < bounds.x0 || goal.x >= bounds.x1 || goal.y < bounds.y0 || goal.y >= bounds.y1 {
        return None;
    }

    ws.reset();

    let w = grid.width;
    let h = grid.height;
    let layers = grid.layers;

    let sidx = idx3(start.layer, start.x, start.y, w, h);
    let gidx = idx3(goal.layer, goal.x, goal.y, w, h);
    ws.set_g(sidx, 0, sidx);
    let w_pct = cfg.heuristic_weight_pct.max(1);
    ws.heap.push(NodeState {
        f: (heuristic(start, goal, cfg.via_penalty) as u64)
            .saturating_mul(w_pct as u64)
            .saturating_div(100) as u32,
        g: 0,
        idx: sidx,
    });
    if emit_stats {
        stats.heap_push = stats.heap_push.saturating_add(1);
    }

    const DIAG_DIRS: [(isize, isize); 8] = [
        (1, 0),
        (0, 1),
        (-1, 0),
        (0, -1),
        (1, 1),
        (-1, 1),
        (1, -1),
        (-1, -1),
    ];
    const MAN_DIRS: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];
    let mut dirs_buf: [(isize, isize); 8] = DIAG_DIRS;
    let n_dirs = if cfg.diagonal { 8 } else { 4 };
    if n_dirs == 4 {
        dirs_buf[..4].copy_from_slice(&MAN_DIRS);
    }
    let rot = (seed as usize) % n_dirs;
    dirs_buf[..n_dirs].rotate_left(rot);
    if (seed & 8) != 0 {
        dirs_buf[..n_dirs].reverse();
    }
    let dirs = &dirs_buf[..n_dirs];

    while let Some(cur) = ws.heap.pop() {
        if emit_stats {
            stats.heap_pop = stats.heap_pop.saturating_add(1);
        }
        if cur.g != ws.get_g(cur.idx) {
            continue;
        }
        if cur.idx == gidx {
            return ws.extract_path(sidx, gidx, w, h);
        }

        let p = unidx3(cur.idx, w, h);
        if p.x < bounds.x0 || p.x >= bounds.x1 || p.y < bounds.y0 || p.y >= bounds.y1 {
            if emit_stats {
                stats.rej_bounds = stats.rej_bounds.saturating_add(1);
            }
            continue;
        }

        // In-layer neighbors.
        for (dx, dy) in dirs {
            let nx = p.x as isize + dx;
            let ny = p.y as isize + dy;
            if nx < 0 || ny < 0 {
                if emit_stats {
                    stats.rej_bounds = stats.rej_bounds.saturating_add(1);
                }
                continue;
            }
            let (nxu, nyu) = (nx as usize, ny as usize);
            if nxu >= w || nyu >= h {
                if emit_stats {
                    stats.rej_bounds = stats.rej_bounds.saturating_add(1);
                }
                continue;
            }
            if nxu < bounds.x0 || nxu >= bounds.x1 || nyu < bounds.y0 || nyu >= bounds.y1 {
                if emit_stats {
                    stats.rej_bounds = stats.rej_bounds.saturating_add(1);
                }
                continue;
            }
            if !grid.base_allows(p.layer, nxu, nyu, net_id, blocked_value) {
                if emit_stats {
                    stats.rej_base_blocked = stats.rej_base_blocked.saturating_add(1);
                }
                continue;
            }
            let neighbor_idx = idx3(p.layer, nxu, nyu, w, h);
            if let Some(f) = forbidden {
                if neighbor_idx != sidx
                    && neighbor_idx != gidx
                    && f.binary_search(&neighbor_idx).is_ok()
                {
                    if emit_stats {
                        stats.rej_forbidden = stats.rej_forbidden.saturating_add(1);
                    }
                    continue;
                }
            }
            // Never allow true overlaps with other nets. When doing NCR, "overlaps" only applies
            // to spacing/clearance as a soft constraint; shorts/crossings are always illegal.
            let allow_overlap =
                allow_routed.map_or(false, |q| q.layer == p.layer && q.x == nxu && q.y == nyu);
            let occ_other = grid.occ_other_at_idx(neighbor_idx, net_id);
            let ignore_congestion = allow_overlap || occ_other == 0;
            if !ignore_congestion {
                if emit_stats {
                    stats.rej_occ_other = stats.rej_occ_other.saturating_add(1);
                }
                continue;
            }
            let mut spacing_penalty: u32 = 0;
            if cfg.enforce_spacing {
                if cfg.enforce_touch {
                    // Enforce "touch" (no copper overlap / shorts) as a hard constraint.
                    if grid.touch_track_other_at_idx(neighbor_idx, net_id) != 0 {
                        if emit_stats {
                            stats.rej_ko_track = stats.rej_ko_track.saturating_add(1);
                        }
                        continue;
                    }
                }
                if !cfg.ncr_allow_overlaps {
                    if grid.ko_track_other_at_idx(neighbor_idx, net_id) != 0 {
                        if emit_stats {
                            stats.rej_ko_track = stats.rej_ko_track.saturating_add(1);
                        }
                        continue;
                    }
                } else {
                    let k = grid
                        .ko_track_other_at_idx(neighbor_idx, net_id)
                        .min(cfg.spacing_present_cap);
                    spacing_penalty = (k as u32).saturating_mul(cfg.spacing_present_cost);
                }
            }
            // Diagonal corner-cut prevention.
            if cfg.diagonal && dx.abs() + dy.abs() == 2 {
                let ax = (p.x as isize + dx) as usize;
                let ay = p.y;
                let bx = p.x;
                let by = (p.y as isize + dy) as usize;
                if ax >= w || by >= h {
                    continue;
                }
                if !grid.base_allows(p.layer, ax, ay, net_id, blocked_value)
                    || !grid.base_allows(p.layer, bx, by, net_id, blocked_value)
                {
                    continue;
                }
                if let Some(f) = forbidden {
                    let aidx = idx3(p.layer, ax, ay, w, h);
                    let bidx = idx3(p.layer, bx, by, w, h);
                    if (aidx != sidx && aidx != gidx && f.binary_search(&aidx).is_ok())
                        || (bidx != sidx && bidx != gidx && f.binary_search(&bidx).is_ok())
                    {
                        continue;
                    }
                }
                if !cfg.ncr_allow_overlaps {
                    let aidx = idx3(p.layer, ax, ay, w, h);
                    let bidx = idx3(p.layer, bx, by, w, h);
                    let allow_a = allow_routed
                        .map_or(false, |q| q.layer == p.layer && q.x == ax && q.y == ay);
                    let allow_b = allow_routed
                        .map_or(false, |q| q.layer == p.layer && q.x == bx && q.y == by);
                    if (!allow_a && grid.occ_other_at_idx(aidx, net_id) != 0)
                        || (!allow_b && grid.occ_other_at_idx(bidx, net_id) != 0)
                    {
                        continue;
                    }
                }
            }
            let base_step: u32 = if dx.abs() + dy.abs() == 2 { 2 } else { 1 };
            let cong_cost = grid.step_cost(neighbor_idx, net_id, cfg, ignore_congestion);
            let step_cost = base_step
                .saturating_add(layer_step_penalty(p.layer, layers, cfg))
                .saturating_add(cong_cost)
                .saturating_add(spacing_penalty);
            let ng = cur.g.saturating_add(step_cost);
            if emit_stats {
                stats.relax_attempts = stats.relax_attempts.saturating_add(1);
            }
            if ng < ws.get_g(neighbor_idx) {
                ws.set_g(neighbor_idx, ng, cur.idx);
                if emit_stats {
                    stats.relax_success = stats.relax_success.saturating_add(1);
                }
                let hcost = heuristic(
                    Point3 {
                        layer: p.layer,
                        x: nxu,
                        y: nyu,
                    },
                    goal,
                    cfg.via_penalty,
                );
                ws.heap.push(NodeState {
                    f: ng.saturating_add(
                        (hcost as u64)
                            .saturating_mul(w_pct as u64)
                            .saturating_div(100) as u32,
                    ),
                    g: ng,
                    idx: neighbor_idx,
                });
                if emit_stats {
                    stats.heap_push = stats.heap_push.saturating_add(1);
                }
            }
        }

        // Via neighbors: adjacent layers only.
        if cfg.via_penalty > 0 {
            for &dl in &[-1isize, 1isize] {
                let nl = p.layer as isize + dl;
                if nl < 0 || nl >= layers as isize {
                    if emit_stats {
                        stats.rej_bounds = stats.rej_bounds.saturating_add(1);
                    }
                    continue;
                }
                let nl = nl as usize;
                if !grid.base_allows(nl, p.x, p.y, net_id, blocked_value) {
                    if emit_stats {
                        stats.rej_base_blocked = stats.rej_base_blocked.saturating_add(1);
                    }
                    continue;
                }
                let nidx = idx3(nl, p.x, p.y, w, h);
                if let Some(f) = forbidden {
                    if nidx != sidx && nidx != gidx && f.binary_search(&nidx).is_ok() {
                        if emit_stats {
                            stats.rej_forbidden = stats.rej_forbidden.saturating_add(1);
                        }
                        continue;
                    }
                }
                let allow_overlap =
                    allow_routed.map_or(false, |q| q.layer == nl && q.x == p.x && q.y == p.y);
                let occ_other = grid.occ_other_at_idx(nidx, net_id);
                let ignore_congestion = allow_overlap || occ_other == 0;
                if !ignore_congestion {
                    if emit_stats {
                        stats.rej_occ_other = stats.rej_occ_other.saturating_add(1);
                    }
                    continue;
                }
                let mut spacing_penalty: u32 = 0;
                if cfg.enforce_spacing {
                    let idx0 = idx3(p.layer, p.x, p.y, w, h);
                    let idx1 = idx3(nl, p.x, p.y, w, h);
                    if cfg.enforce_touch
                        && (grid.touch_via_other_at_idx(idx0, net_id) != 0
                            || grid.touch_via_other_at_idx(idx1, net_id) != 0)
                    {
                        if emit_stats {
                            stats.rej_ko_via = stats.rej_ko_via.saturating_add(1);
                        }
                        continue;
                    }
                    let k0 = grid.ko_via_other_at_idx(idx0, net_id);
                    let k1 = grid.ko_via_other_at_idx(idx1, net_id);
                    if !cfg.ncr_allow_overlaps || cfg.via_spacing_hard {
                        if k0 != 0 || k1 != 0 {
                            if emit_stats {
                                stats.rej_ko_via = stats.rej_ko_via.saturating_add(1);
                            }
                            continue;
                        }
                    } else {
                        let k = k0.saturating_add(k1).min(cfg.spacing_present_cap);
                        spacing_penalty = (k as u32).saturating_mul(cfg.spacing_present_cost);
                    }
                }
                let ng = cur
                    .g
                    .saturating_add(cfg.via_penalty)
                    .saturating_add(grid.step_cost(nidx, net_id, cfg, ignore_congestion));
                let ng = ng.saturating_add(spacing_penalty);
                if emit_stats {
                    stats.relax_attempts = stats.relax_attempts.saturating_add(1);
                }
                if ng < ws.get_g(nidx) {
                    ws.set_g(nidx, ng, cur.idx);
                    if emit_stats {
                        stats.relax_success = stats.relax_success.saturating_add(1);
                    }
                    let hcost = heuristic(
                        Point3 {
                            layer: nl,
                            x: p.x,
                            y: p.y,
                        },
                        goal,
                        cfg.via_penalty,
                    );
                    ws.heap.push(NodeState {
                        f: ng.saturating_add(
                            (hcost as u64)
                                .saturating_mul(w_pct as u64)
                                .saturating_div(100) as u32,
                        ),
                        g: ng,
                        idx: nidx,
                    });
                    if emit_stats {
                        stats.heap_push = stats.heap_push.saturating_add(1);
                    }
                }
            }
        }
    }

    None
}

fn route_one(
    ws: &mut AStarWorkspace,
    grid: &Grid,
    net: &NetSpec,
    blocked_value: u32,
    cfg: RouteConfig,
    bounds_hint: Option<BBox>,
    forbidden: Option<&[usize]>,
    stats: &mut AStarStats,
) -> Option<Vec<Point3>> {
    let base = bounds_hint.unwrap_or_else(|| BBox::from_points(net.start, net.goal, grid.width, grid.height));
    let max_margin = if cfg.margin_max == 0 {
        grid.width.max(grid.height)
    } else {
        cfg.margin_max
    };

    let mut margin = cfg.margin_init;
    while margin <= max_margin {
        let bounds = base.expand(margin, grid.width, grid.height);
        let attempts = cfg.attempts.max(1);
        for i in 0..attempts {
            let seed = cfg.seed ^ ((net.net_id as u64) << 1) ^ (i as u64);
            if let Some(p) = astar_3d_bounded(
                ws,
                grid,
                net.net_id,
                net.start,
                net.goal,
                blocked_value,
                cfg,
                bounds,
                forbidden,
                None,
                seed,
                cfg.emit_stats,
                stats,
            ) {
                return Some(p);
            }
        }
        margin = margin.saturating_add(cfg.margin_step.max(1));
    }
    None
}

fn path_to_tracks_and_vias(
    problem: &Problem,
    net: &NetSpec,
    path: &[Point3],
) -> (Vec<serde_json::Value>, Vec<serde_json::Value>) {
    let res = problem.resolution_mm;
    let layers = &problem.layers;

    let mut tracks: Vec<serde_json::Value> = Vec::new();
    let mut vias: Vec<serde_json::Value> = Vec::new();

    if path.len() < 2 {
        return (tracks, vias);
    }

    let mut seg_start = path[0];
    let mut prev = path[0];
    let mut prev_dir: Option<(isize, isize)> = None;

    let flush_seg = |tracks: &mut Vec<serde_json::Value>, a: Point3, b: Point3| {
        if a.layer != b.layer {
            return;
        }
        if a.x == b.x && a.y == b.y {
            return;
        }
        let sx = (a.x as f64) * res;
        let sy = (a.y as f64) * res;
        let ex = (b.x as f64) * res;
        let ey = (b.y as f64) * res;
        tracks.push(serde_json::json!({
            "net": net.net,
            "layer": layers[a.layer],
            "width_mm": net.track_width_mm,
            "start_mm": [sx, sy],
            "end_mm": [ex, ey],
        }));
    };

    for &p in &path[1..] {
        if p.layer != prev.layer {
            flush_seg(&mut tracks, seg_start, prev);
            let x = (prev.x as f64) * res;
            let y = (prev.y as f64) * res;
            let l0 = &layers[prev.layer];
            let l1 = &layers[p.layer];
            vias.push(serde_json::json!({
                "net": net.net,
                "pos_mm": [x, y],
                "size_mm": net.uvia_diameter_mm,
                "drill_mm": net.uvia_drill_mm,
                "via_type": "micro",
                "layers": [l0, l1],
            }));
            seg_start = p;
            prev = p;
            prev_dir = None;
            continue;
        }

        let dx = p.x as isize - prev.x as isize;
        let dy = p.y as isize - prev.y as isize;
        let dir = (dx.signum(), dy.signum());
        if let Some(d0) = prev_dir {
            if dir != d0 {
                flush_seg(&mut tracks, seg_start, prev);
                seg_start = prev;
            }
        }
        prev_dir = Some(dir);
        prev = p;
    }
    flush_seg(&mut tracks, seg_start, prev);

    (tracks, vias)
}

fn angle_from_center(width: usize, height: usize, x: usize, y: usize) -> f64 {
    let cx = (width as f64) / 2.0;
    let cy = (height as f64) / 2.0;
    let dx = (x as f64) - cx;
    let dy = (y as f64) - cy;
    let mut a = dy.atan2(dx);
    if a < 0.0 {
        a += 2.0 * PI;
    }
    a
}

fn bbox_from_starts(nets: &[NetSpec], width: usize, height: usize) -> Option<BBox> {
    if nets.is_empty() {
        return None;
    }
    let mut x0 = width;
    let mut y0 = height;
    let mut x1 = 0usize;
    let mut y1 = 0usize;
    for n in nets {
        x0 = x0.min(n.start.x);
        y0 = y0.min(n.start.y);
        x1 = x1.max(n.start.x);
        y1 = y1.max(n.start.y);
    }
    if x0 >= width || y0 >= height {
        return None;
    }
    Some(BBox {
        x0,
        y0,
        x1: (x1 + 1).min(width),
        y1: (y1 + 1).min(height),
    })
}

#[derive(Clone, Copy, Debug)]
enum ExitSide {
    Left,
    Right,
    Top,
    Bottom,
}

fn exit_side(net: &NetSpec, bga: BBox) -> ExitSide {
    // Pick the side of the BGA bbox that points toward the net's goal.
    let gx = net.goal.x as isize;
    let gy = net.goal.y as isize;
    let cx = ((bga.x0 + bga.x1) / 2) as isize;
    let cy = ((bga.y0 + bga.y1) / 2) as isize;
    let dx = gx - cx;
    let dy = gy - cy;

    if dx.abs() >= dy.abs() {
        if dx < 0 {
            ExitSide::Left
        } else {
            ExitSide::Right
        }
    } else if dy < 0 {
        ExitSide::Top
    } else {
        ExitSide::Bottom
    }
}

fn exit_candidates(
    grid: &Grid,
    net: &NetSpec,
    bga: BBox,
    blocked_value: u32,
    max_candidates: usize,
) -> Vec<Point3> {
    let side = exit_side(net, bga);
    let layer = net.start.layer;
    let mut out: Vec<Point3> = Vec::new();

    let mut push_if_ok = |out: &mut Vec<Point3>, x: usize, y: usize| {
        if x >= grid.width || y >= grid.height {
            return;
        }
        if x < bga.x0 || x >= bga.x1 || y < bga.y0 || y >= bga.y1 {
            return;
        }
        if grid.base_allows(layer, x, y, net.net_id, blocked_value)
            && grid.occ_other_at_idx(grid.idx(layer, x, y), net.net_id) == 0
        {
            out.push(Point3 { layer, x, y });
        }
    };

    match side {
        ExitSide::Left | ExitSide::Right => {
            let x = if matches!(side, ExitSide::Left) {
                bga.x0
            } else {
                bga.x1.saturating_sub(1)
            };
            let y0 = bga.y0;
            let y1 = bga.y1.saturating_sub(1);
            let y_seed = net.start.y.clamp(y0, y1);
            push_if_ok(&mut out, x, y_seed);
            for d in 1..=(y1 - y0) {
                if out.len() >= max_candidates {
                    break;
                }
                if y_seed >= d {
                    push_if_ok(&mut out, x, y_seed - d);
                }
                if out.len() >= max_candidates {
                    break;
                }
                if y_seed + d <= y1 {
                    push_if_ok(&mut out, x, y_seed + d);
                }
            }
        }
        ExitSide::Top | ExitSide::Bottom => {
            let y = if matches!(side, ExitSide::Top) {
                bga.y0
            } else {
                bga.y1.saturating_sub(1)
            };
            let x0 = bga.x0;
            let x1 = bga.x1.saturating_sub(1);
            let x_seed = net.start.x.clamp(x0, x1);
            push_if_ok(&mut out, x_seed, y);
            for d in 1..=(x1 - x0) {
                if out.len() >= max_candidates {
                    break;
                }
                if x_seed >= d {
                    push_if_ok(&mut out, x_seed - d, y);
                }
                if out.len() >= max_candidates {
                    break;
                }
                if x_seed + d <= x1 {
                    push_if_ok(&mut out, x_seed + d, y);
                }
            }
        }
    }

    out
}

fn bbox_for_path(path: &[Point3], width: usize, height: usize) -> BBox {
    if path.is_empty() {
        return BBox::default();
    }
    let x0 = path.iter().map(|p| p.x).min().unwrap_or(0);
    let y0 = path.iter().map(|p| p.y).min().unwrap_or(0);
    let x1 = (path.iter().map(|p| p.x).max().unwrap_or(0) + 1).min(width);
    let y1 = (path.iter().map(|p| p.y).max().unwrap_or(0) + 1).min(height);
    BBox { x0, y0, x1, y1 }
}

fn grid_overuse_stats(grid: &Grid) -> (usize, u16) {
    let mut overused = 0usize;
    let mut maxu: u16 = 0;
    for &idx in &grid.touched {
        let t = grid.track_usage[idx];
        let v = grid.via_usage[idx];
        let mixed = grid.track_owner[idx] == u32::MAX
            || grid.via_owner[idx] == u32::MAX
            || (t != 0
                && v != 0
                && grid.track_owner[idx] != 0
                && grid.via_owner[idx] != 0
                && grid.track_owner[idx] != grid.via_owner[idx]);
        let u = t.saturating_add(v);
        if mixed && u > 1 {
            overused += 1;
        }
        if u > maxu {
            maxu = u;
        }
    }
    (overused, maxu)
}

fn grid_overuse_samples(grid: &Grid, w: usize, h: usize, limit: usize) -> Vec<serde_json::Value> {
    let mut over: Vec<(u16, usize)> = Vec::new();
    for &idx in &grid.touched {
        let t = grid.track_usage[idx];
        let v = grid.via_usage[idx];
        let mixed = grid.track_owner[idx] == u32::MAX
            || grid.via_owner[idx] == u32::MAX
            || (t != 0
                && v != 0
                && grid.track_owner[idx] != 0
                && grid.via_owner[idx] != 0
                && grid.track_owner[idx] != grid.via_owner[idx]);
        let u = t.saturating_add(v);
        if mixed && u > 1 {
            over.push((u, idx));
        }
    }
    over.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
    over.truncate(limit);
    over.into_iter()
        .map(|(u, idx)| {
            let p = unidx3(idx, w, h);
            serde_json::json!({ "layer": p.layer, "x": p.x, "y": p.y, "usage": u })
        })
        .collect()
}

fn try_route_net(
    ws: &mut AStarWorkspace,
    grid: &mut Grid,
    spec_idx: usize,
    net: &NetSpec,
    cfg: RouteConfig,
    blocked_value: u32,
    r_track: usize,
    r_via: usize,
    escape_bbox: Option<BBox>,
    bounds_hint: Option<BBox>,
    forbidden: Option<&[usize]>,
    spacing: &SpacingBundle,
    spec_stats: &mut PerSpecStats,
) -> Option<RouteRecord> {
    let t0 = Instant::now();
    spec_stats.spec_idx = spec_idx;
    spec_stats.net = net.net.clone();

    let mut full_path: Vec<Point3> = Vec::new();

    let mut start = net.start;
    let mut escape_path: Option<Vec<Point3>> = None;
    if let Some(bga) = escape_bbox {
        let candidates = exit_candidates(grid, net, bga, blocked_value, 12);
        let escape_cfg = RouteConfig {
            // Allow vias during escape so dense BGAs can immediately drop to inner layers.
            via_penalty: cfg.via_penalty,
            ..cfg
        };
        let attempts = escape_cfg.attempts.max(1);
        let mut found: Option<Vec<Point3>> = None;
        'outer: for (ci, exit) in candidates.iter().copied().enumerate() {
            for i in 0..attempts {
                let seed = escape_cfg.seed
                    ^ ((net.net_id as u64) << 1)
                    ^ (i as u64)
                    ^ ((ci as u64) << 16)
                    ^ 0xE5E5;
                if let Some(p) = astar_3d_bounded(
                    ws,
                    grid,
                    net.net_id,
                    start,
                    exit,
                    blocked_value,
                    escape_cfg,
                    bga,
                    None,
                    None,
                    seed,
                    cfg.emit_stats,
                    &mut spec_stats.astar,
                ) {
                    found = Some(p);
                    break 'outer;
                }
            }
        }
        let ep = found?;
        start = *ep.last().unwrap_or(&start);
        full_path = ep.clone();
        escape_path = Some(ep);
    }

    let mut net2 = net.clone();
    net2.start = start;
    let global_path_opt = if start == net.goal {
        Some(vec![start])
    } else {
        route_one(
            ws,
            grid,
            &net2,
            blocked_value,
            cfg,
            bounds_hint,
            forbidden,
            &mut spec_stats.astar,
        )
    };

    let Some(global_path) = global_path_opt else {
        return None;
    };

    // Commit both segments after they are found, so the global segment isn't blocked
    // by the escape segment's keepout around the handoff point.
    let mut track_stamped: Vec<usize> = Vec::new();
    let mut via_stamped: Vec<usize> = Vec::new();
        if cfg.commit_routes {
            if let Some(ep) = &escape_path {
                let (t, v) = grid.commit_path(
                    net.net_id,
                    ep,
                    if cfg.enforce_spacing { Some(spacing) } else { None },
                );
            track_stamped.extend_from_slice(&t);
            via_stamped.extend_from_slice(&v);
        }
        let (t, v) = grid.commit_path(
            net.net_id,
            &global_path,
            if cfg.enforce_spacing { Some(spacing) } else { None },
        );
        track_stamped.extend_from_slice(&t);
        via_stamped.extend_from_slice(&v);
    }
    track_stamped.sort_unstable();
    track_stamped.dedup();
    via_stamped.sort_unstable();
    via_stamped.dedup();

    if !full_path.is_empty() {
        if full_path.last().copied() == global_path.first().copied() {
            full_path.extend_from_slice(&global_path[1..]);
        } else {
            full_path.extend_from_slice(&global_path);
        }
    } else {
        full_path = global_path;
    }

    let bbox = bbox_for_path(&full_path, grid.width, grid.height);
    spec_stats.elapsed_ms = spec_stats.elapsed_ms.saturating_add(t0.elapsed().as_millis());
    Some(RouteRecord {
        spec_idx,
        net_id: net.net_id,
        path: full_path,
        track_stamped,
        via_stamped,
        bbox,
    })
}

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let Some(in_path) = args.next() else {
        return Err("usage: pardal-router <problem.json> <routes.json>".to_string());
    };
    let Some(out_path) = args.next() else {
        return Err("usage: pardal-router <problem.json> <routes.json>".to_string());
    };
    let cfg: RouteConfig = if let Some(cfg_path) = args.next() {
        let s = fs::read_to_string(cfg_path).map_err(|e| e.to_string())?;
        serde_json::from_str(&s).map_err(|e| e.to_string())?
    } else {
        RouteConfig {
            margin_init: default_margin_init(),
            margin_step: default_margin_step(),
            margin_max: default_margin_max(),
            via_penalty: default_via_penalty(),
            diagonal: default_allow_diagonal(),
            ripup_passes: default_ripup_passes(),
            ripup_k: default_ripup_k(),
            escape_enable: default_escape_enable(),
            escape_margin: default_escape_margin(),
            attempts: default_attempts(),
            seed: default_seed(),
            keepout_clearance_scale: default_keepout_clearance_scale(),
            keepout_safety_mm: default_keepout_safety_mm(),
            keepout_track_cells: None,
            keepout_via_cells: None,
            commit_routes: default_commit_routes(),
            ncr_iters: default_ncr_iters(),
            ncr_present_cost: default_ncr_present_cost(),
            ncr_history_cost: default_ncr_history_cost(),
	            ncr_history_inc: default_ncr_history_inc(),
	            ncr_allow_overlaps: default_ncr_allow_overlaps(),
	            enforce_spacing: default_enforce_spacing(),
	            enforce_touch: default_enforce_touch(),
	            via_spacing_hard: default_via_spacing_hard(),
	            legalize_passes: default_legalize_passes(),
	            emit_stats: default_emit_stats(),
            progress_every: default_progress_every(),
            heuristic_weight_pct: default_heuristic_weight_pct(),
            spacing_present_cost: default_spacing_present_cost(),
            spacing_present_cap: default_spacing_present_cap(),
            layer_penalty_outer: default_layer_penalty_outer(),
            layer_penalty_in1: default_layer_penalty_in1(),
            layer_penalty_inner: default_layer_penalty_inner(),
        }
    };

    let problem_s = fs::read_to_string(&in_path).map_err(|e| e.to_string())?;
    let problem: Problem = serde_json::from_str(&problem_s).map_err(|e| e.to_string())?;
    if problem.version != 1 {
        return Err(format!("unsupported problem version {}", problem.version));
    }

    let blocked_value = u32::MAX;
    let mut grid = Grid::new(problem.layers.len(), problem.width, problem.height);
    for c in &problem.circles {
        for &layer in &c.layers {
            grid.stamp_circle_base(layer, c.center.x, c.center.y, c.r, c.net_id, blocked_value);
        }
    }

    let mut nets: Vec<NetSpec> = problem.nets.clone();
    let bga_bbox = bbox_from_starts(&nets, problem.width, problem.height);
    nets.sort_by(|a, b| {
        let depth = |p: &NetSpec| -> usize {
            let Some(bb) = bga_bbox else {
                return 0;
            };
            let x_left = p.start.x.saturating_sub(bb.x0);
            let x_right = bb.x1.saturating_sub(1).saturating_sub(p.start.x);
            let y_top = p.start.y.saturating_sub(bb.y0);
            let y_bottom = bb.y1.saturating_sub(1).saturating_sub(p.start.y);
            x_left.min(x_right).min(y_top.min(y_bottom))
        };

        // Route "deep" (hard-to-escape) BGA pads first.
        let da_depth = depth(a);
        let db_depth = depth(b);
        db_depth.cmp(&da_depth).then_with(|| {
            let aa = angle_from_center(problem.width, problem.height, a.goal.x, a.goal.y);
            let bb = angle_from_center(problem.width, problem.height, b.goal.x, b.goal.y);
            aa.partial_cmp(&bb).unwrap_or(Ordering::Equal)
        })
    });

    let clearance_mm = problem.net_defaults.clearance_mm * cfg.keepout_clearance_scale;
    let mut track_keepout_mm =
        problem.net_defaults.track_width_mm + clearance_mm + cfg.keepout_safety_mm;
    let mut via_keepout_mm = (problem.net_defaults.uvia_diameter_mm / 2.0)
        + clearance_mm
        + (problem.net_defaults.track_width_mm / 2.0)
        + cfg.keepout_safety_mm;
    if let Some(v) = cfg.keepout_track_cells {
        track_keepout_mm = (v as f64) * problem.resolution_mm;
    }
    if let Some(v) = cfg.keepout_via_cells {
        via_keepout_mm = (v as f64) * problem.resolution_mm;
    }

    // These are retained for compatibility with existing logging / APIs. The routing legality is
    // determined by the mm-based `spacing` offsets below.
    let r_track = (track_keepout_mm / problem.resolution_mm).ceil().max(1.0) as usize;
    let r_via = (via_keepout_mm / problem.resolution_mm).ceil().max(1.0) as usize;

    let touch = if cfg.enforce_touch {
        Spacing {
            track_vs_track: build_offsets_for_min_dist_mm(
                problem.net_defaults.track_width_mm,
                problem.resolution_mm,
            ),
            track_vs_via: build_offsets_for_min_dist_mm(
                (problem.net_defaults.uvia_diameter_mm / 2.0)
                    + (problem.net_defaults.track_width_mm / 2.0),
                problem.resolution_mm,
            ),
            via_vs_track: build_offsets_for_min_dist_mm(
                (problem.net_defaults.uvia_diameter_mm / 2.0)
                    + (problem.net_defaults.track_width_mm / 2.0),
                problem.resolution_mm,
            ),
            via_vs_via: build_offsets_for_min_dist_mm(
                problem.net_defaults.uvia_diameter_mm,
                problem.resolution_mm,
            ),
        }
    } else {
        Spacing {
            track_vs_track: Vec::new(),
            track_vs_via: Vec::new(),
            via_vs_track: Vec::new(),
            via_vs_via: Vec::new(),
        }
    };

    let spacing = SpacingBundle {
        clear: Spacing {
            track_vs_track: build_offsets_for_min_dist_mm(track_keepout_mm, problem.resolution_mm),
            track_vs_via: build_offsets_for_min_dist_mm(via_keepout_mm, problem.resolution_mm),
            via_vs_track: build_offsets_for_min_dist_mm(via_keepout_mm, problem.resolution_mm),
            via_vs_via: build_offsets_for_min_dist_mm(
                problem.net_defaults.uvia_diameter_mm + clearance_mm + cfg.keepout_safety_mm,
                problem.resolution_mm,
            ),
        },
        touch,
    };

    let t_total = Instant::now();
    let mut stats = RouterStats {
        elapsed_ms_total: 0,
        astar: AStarStats::default(),
        per_spec: nets
            .iter()
            .enumerate()
            .map(|(i, n)| PerSpecStats {
                spec_idx: i,
                net: n.net.clone(),
                elapsed_ms: 0,
                astar: AStarStats::default(),
            })
            .collect(),
    };

    // Treat pre-existing vias as fixed copper: they participate in occupancy + spacing checks.
    // This is critical for BGA fixtures which seed microvias-in-pad.
    if !problem.existing_vias.is_empty() {
        for v in &problem.existing_vias {
            let mut idxs: Vec<usize> = Vec::new();
            for &layer in &v.layers {
                if layer >= grid.layers || v.center.x >= grid.width || v.center.y >= grid.height {
                    continue;
                }
                idxs.push(grid.idx(layer, v.center.x, v.center.y));
            }
            if idxs.is_empty() {
                continue;
            }
            idxs.sort_unstable();
            idxs.dedup();
            grid.commit_indices(
                v.net_id,
                &[],
                &idxs,
                if cfg.enforce_spacing { Some(&spacing) } else { None },
            );
        }
    }

    let n_cells = grid.layers * grid.width * grid.height;
    let mut ws = AStarWorkspace::new(n_cells);

    let mut routes: Vec<Option<RouteRecord>> = vec![None; nets.len()];
    let mut failed_idxs: Vec<usize> = Vec::new();
    let progress_path = PathBuf::from(format!("{out_path}.progress.json"));

    let escape_bbox = if cfg.escape_enable {
        bbox_from_starts(&nets, grid.width, grid.height)
            .map(|bb| bb.expand(cfg.escape_margin, grid.width, grid.height))
    } else {
        None
    };

    if cfg.ncr_iters > 0 {
        // Negotiated congestion routing (PathFinder-style):
        // - route all nets once (iter 0)
        // - compute conflicts
        // - in later iterations, rip up + reroute only conflicting/failed nets
        let mut reroute_set: Vec<usize> = (0..nets.len()).collect();
        for iter in 0..cfg.ncr_iters {
            let mut pass_failed: Vec<usize> = Vec::new();
            for (k, &i) in reroute_set.iter().enumerate() {
                let Some(net) = nets.get(i) else { continue };
                let old = routes[i].take();
                if let Some(ref rec) = old {
                    grid.uncommit(
                        rec.net_id,
                        &rec.track_stamped,
                        &rec.via_stamped,
                        if cfg.enforce_spacing { Some(&spacing) } else { None },
                    );
                }
                let cfg_iter = RouteConfig {
                    seed: cfg.seed ^ ((iter as u64) << 32) ^ (net.net_id as u64) ^ 0x5046u64,
                    ..cfg
                };
                let bounds_hint = old.as_ref().map(|r| r.bbox);
                if let Some(rec) = try_route_net(
                    &mut ws,
                    &mut grid,
                    i,
                    net,
                    cfg_iter,
                    blocked_value,
                    r_track,
                    r_via,
                    escape_bbox,
                    bounds_hint,
                    None,
                    &spacing,
                    &mut stats.per_spec[i],
                ) {
                    routes[i] = Some(rec);
                } else {
                    pass_failed.push(i);
                    if let Some(rec) = old {
                        grid.commit_indices(
                            rec.net_id,
                            &rec.track_stamped,
                            &rec.via_stamped,
                            if cfg.enforce_spacing { Some(&spacing) } else { None },
                        );
                        routes[i] = Some(rec);
                    }
                }
                if cfg.progress_every != 0 && (k + 1) % cfg.progress_every == 0 {
                    write_progress(
                        &progress_path,
                        cfg,
                        "ncr",
                        iter,
                        Some(i),
                        &routes,
                        &stats,
                        &failed_idxs,
                        &grid,
                        t_total.elapsed().as_millis(),
                    );
                }
            }
            failed_idxs = pass_failed.clone();

            // Update history for cells involved in conflicts:
            // - overlapping usage (shorts / crossings)
            // - clearance violations (using stamped keepout fields)
            let mut any_conflict = false;
            let mut next_reroute: Vec<usize> = pass_failed;
            for rec in routes.iter().flatten() {
                let mut rec_conflict = false;
                for &idx in &rec.track_stamped {
                    let o = grid.occ_other_at_idx(idx, rec.net_id);
                    if o != 0 {
                        any_conflict = true;
                        rec_conflict = true;
                        let inc = cfg.ncr_history_inc.saturating_mul(o);
                        grid.history[idx] = grid.history[idx].saturating_add(inc);
                    }
                    let k = grid.ko_track_other_at_idx(idx, rec.net_id);
                    if k != 0 {
                        any_conflict = true;
                        rec_conflict = true;
                        let inc = cfg.ncr_history_inc.saturating_mul(k);
                        grid.history[idx] = grid.history[idx].saturating_add(inc);
                    }
                }
                for &idx in &rec.via_stamped {
                    let o = grid.occ_other_at_idx(idx, rec.net_id);
                    if o != 0 {
                        any_conflict = true;
                        rec_conflict = true;
                        let inc = cfg.ncr_history_inc.saturating_mul(o);
                        grid.history[idx] = grid.history[idx].saturating_add(inc);
                    }
                    let k = grid.ko_via_other_at_idx(idx, rec.net_id);
                    if k != 0 {
                        any_conflict = true;
                        rec_conflict = true;
                        let inc = cfg.ncr_history_inc.saturating_mul(k);
                        grid.history[idx] = grid.history[idx].saturating_add(inc);
                    }
                }
                if rec_conflict {
                    next_reroute.push(rec.spec_idx);
                }
            }
            if !any_conflict {
                break;
            }
            next_reroute.sort_unstable();
            next_reroute.dedup();
            reroute_set = next_reroute;
            write_progress(
                &progress_path,
                cfg,
                "ncr",
                iter,
                None,
                &routes,
                &stats,
                &failed_idxs,
                &grid,
                t_total.elapsed().as_millis(),
            );
        }
    } else {
        for (i, net) in nets.iter().enumerate() {
	            if let Some(rec) = try_route_net(
	                &mut ws,
	                &mut grid,
	                i,
	                net,
	                cfg,
	                blocked_value,
	                r_track,
	                r_via,
	                escape_bbox,
	                None,
	                None,
	                &spacing,
	                &mut stats.per_spec[i],
	            ) {
                routes[i] = Some(rec);
            } else {
                failed_idxs.push(i);
            }
            if cfg.progress_every != 0 && (i + 1) % cfg.progress_every == 0 {
                write_progress(
                    &progress_path,
                    cfg,
                    "route",
                    0,
                    Some(i),
                    &routes,
                    &stats,
                    &failed_idxs,
                    &grid,
                    t_total.elapsed().as_millis(),
                );
            }
        }
        failed_idxs.sort_unstable();
        failed_idxs.dedup();

        // Simple negotiation: attempt to route failed nets by ripping up nearby routes.
        if cfg.ripup_passes > 0 && !failed_idxs.is_empty() {
            for _pass in 0..cfg.ripup_passes {
                if failed_idxs.is_empty() {
                    break;
                }
                let mut next_failed: Vec<usize> = Vec::new();
                for &fid in &failed_idxs {
                    let Some(net) = nets.get(fid) else {
                        continue;
                    };
                    let target_bbox =
                        BBox::from_points(net.start, net.goal, grid.width, grid.height).expand(
                            cfg.margin_init,
                            grid.width,
                            grid.height,
                        );
                    let mut candidates: Vec<usize> = Vec::new();
                    for (rid, rec) in routes.iter().enumerate() {
                        if rid == fid {
                            continue;
                        }
                        let Some(r) = rec else {
                            continue;
                        };
                        if r.bbox.intersects(&target_bbox) {
                            candidates.push(rid);
                        }
                    }
                    if candidates.is_empty() {
                        next_failed.push(fid);
                        continue;
                    }
                    candidates.truncate(cfg.ripup_k);

                    let mut ripped: Vec<RouteRecord> = Vec::new();
                    for rid in &candidates {
                        if let Some(rec) = routes[*rid].take() {
                            grid.uncommit(
                                rec.net_id,
                                &rec.track_stamped,
                                &rec.via_stamped,
                                if cfg.enforce_spacing { Some(&spacing) } else { None },
                            );
                            ripped.push(rec);
                        }
                    }

	                    if let Some(rec) = try_route_net(
	                        &mut ws,
	                        &mut grid,
	                        fid,
	                        net,
	                        cfg,
	                        blocked_value,
	                        r_track,
	                        r_via,
	                        escape_bbox,
	                        None,
	                        None,
	                        &spacing,
	                        &mut stats.per_spec[fid],
	                    ) {
                        routes[fid] = Some(rec);
                    } else {
                        next_failed.push(fid);
                    }

                    // Try to restore ripped routes.
                    for rec in ripped {
                        let sid = rec.spec_idx;
                        let Some(spec) = nets.get(sid) else {
                            continue;
                        };
                        if routes[sid].is_some() {
                            continue;
                        }
	                        if let Some(restored) = try_route_net(
	                            &mut ws,
	                            &mut grid,
	                            sid,
	                            spec,
	                            cfg,
	                            blocked_value,
	                            r_track,
	                            r_via,
	                            escape_bbox,
	                            None,
	                            None,
	                            &spacing,
	                            &mut stats.per_spec[sid],
	                        ) {
                            routes[sid] = Some(restored);
                        } else {
                            next_failed.push(sid);
                        }
                    }
                }
                next_failed.sort_unstable();
                next_failed.dedup();
                failed_idxs = next_failed;
            }
        }
    }

    // Final legalization pass: when routing allowed overlaps / spacing violations as soft
    // penalties, try to repair by rerouting only the most-conflicting nets under strict
    // constraints (no overlaps, hard spacing).
	    if cfg.legalize_passes > 0 && cfg.ncr_allow_overlaps && cfg.enforce_spacing {
        let strict_cfg = RouteConfig {
            ncr_allow_overlaps: false,
            enforce_spacing: true,
            legalize_passes: 0,
            ..cfg
        };

        let conflict_score = |grid: &Grid, rec: &RouteRecord| -> u32 {
            let mut s: u32 = 0;
            for &idx in &rec.track_stamped {
                s = s.saturating_add(grid.ko_track_other_at_idx(idx, rec.net_id) as u32);
                s = s.saturating_add(grid.occ_other_at_idx(idx, rec.net_id) as u32 * 1000);
            }
            for &idx in &rec.via_stamped {
                s = s.saturating_add(grid.ko_via_other_at_idx(idx, rec.net_id) as u32);
                s = s.saturating_add(grid.occ_other_at_idx(idx, rec.net_id) as u32 * 1000);
            }
            s
        };

	        for _pass in 0..cfg.legalize_passes {
            let mut ranked: Vec<(u32, usize)> = Vec::new();
            for (i, rec) in routes.iter().enumerate() {
                let Some(r) = rec else { continue };
                let s = conflict_score(&grid, r);
                if s > 0 {
                    ranked.push((s, i));
                }
            }
            if ranked.is_empty() {
                break;
            }
            ranked.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));

            // Reroute a bounded number of offenders per pass (0 == all).
            let limit = if cfg.ripup_k == 0 {
                ranked.len()
            } else {
                cfg.ripup_k.min(ranked.len()).max(1)
            };
            let mut to_reroute: Vec<usize> = ranked.iter().take(limit).map(|&(_s, i)| i).collect();
            to_reroute.sort_unstable();
            to_reroute.dedup();

	            // Rip up selected routes.
	            let mut old_routes: Vec<(usize, RouteRecord)> = Vec::new();
	            for &i in &to_reroute {
	                if let Some(rec) = routes[i].take() {
	                    grid.uncommit(rec.net_id, &rec.track_stamped, &rec.via_stamped, Some(&spacing));
	                    old_routes.push((i, rec));
	                }
	            }
	            old_routes.sort_by(|a, b| a.0.cmp(&b.0));

	            // Prevent a rerouted net from "stealing" cells from nets that haven't been rerouted yet
	            // in this legalization batch. Without this, if a later net fails and is restored to its
	            // old route, it can overlap/short with earlier rerouted nets.
	            let mut remaining_forbidden: Vec<usize> = Vec::new();
	            for (_i, r) in &old_routes {
	                remaining_forbidden.extend_from_slice(&r.track_stamped);
	                remaining_forbidden.extend_from_slice(&r.via_stamped);
	            }
	            remaining_forbidden.sort_unstable();
	            remaining_forbidden.dedup();

	            // Reroute them under strict constraints, restoring the previous route on failure.
	            let mut any_change = false;
	            for (i, old) in old_routes {
	                let Some(net) = nets.get(i) else {
	                    continue;
	                };
	                let mut own: Vec<usize> = Vec::with_capacity(old.track_stamped.len() + old.via_stamped.len());
	                own.extend_from_slice(&old.track_stamped);
	                own.extend_from_slice(&old.via_stamped);
	                own.sort_unstable();
	                own.dedup();
	                let forbidden_vec = sorted_diff(&remaining_forbidden, &own);
	                let forbidden = if forbidden_vec.is_empty() { None } else { Some(forbidden_vec.as_slice()) };
	                let bounds_hint = Some(old.bbox);
	                if let Some(rec) = try_route_net(
	                    &mut ws,
	                    &mut grid,
	                    i,
	                    net,
	                    strict_cfg,
	                    blocked_value,
	                    r_track,
	                    r_via,
	                    escape_bbox,
	                    bounds_hint,
	                    forbidden,
	                    &spacing,
	                    &mut stats.per_spec[i],
	                ) {
	                    routes[i] = Some(rec);
	                    any_change = true;
	                } else {
	                    grid.commit_indices(old.net_id, &old.track_stamped, &old.via_stamped, Some(&spacing));
	                    routes[i] = Some(old);
	                }
	                remaining_forbidden = sorted_diff(&remaining_forbidden, &own);
	            }
	            if !any_change {
	                break;
	            }
	        }
	    }

    let mut out_tracks: Vec<serde_json::Value> = Vec::new();
    let mut out_vias: Vec<serde_json::Value> = Vec::new();
    let mut failed: Vec<String> = Vec::new();
    for (i, net) in nets.iter().enumerate() {
        if let Some(rec) = &routes[i] {
            let (tracks, vias) = path_to_tracks_and_vias(&problem, net, &rec.path);
            out_tracks.extend(tracks);
            out_vias.extend(vias);
        } else {
            failed.push(net.net.clone());
        }
    }
    failed.sort();
    failed.dedup();

    let (overused_cells, max_cell_usage) = grid_overuse_stats(&grid);
    stats.elapsed_ms_total = t_total.elapsed().as_millis();
    if cfg.emit_stats {
        for s in &stats.per_spec {
            stats.astar.heap_push = stats.astar.heap_push.saturating_add(s.astar.heap_push);
            stats.astar.heap_pop = stats.astar.heap_pop.saturating_add(s.astar.heap_pop);
            stats.astar.relax_attempts =
                stats.astar.relax_attempts.saturating_add(s.astar.relax_attempts);
            stats.astar.relax_success =
                stats.astar.relax_success.saturating_add(s.astar.relax_success);
            stats.astar.rej_bounds = stats.astar.rej_bounds.saturating_add(s.astar.rej_bounds);
            stats.astar.rej_base_blocked =
                stats.astar.rej_base_blocked.saturating_add(s.astar.rej_base_blocked);
            stats.astar.rej_forbidden =
                stats.astar.rej_forbidden.saturating_add(s.astar.rej_forbidden);
            stats.astar.rej_occ_other =
                stats.astar.rej_occ_other.saturating_add(s.astar.rej_occ_other);
            stats.astar.rej_ko_track =
                stats.astar.rej_ko_track.saturating_add(s.astar.rej_ko_track);
            stats.astar.rej_ko_via = stats.astar.rej_ko_via.saturating_add(s.astar.rej_ko_via);
        }
    }
    let payload = serde_json::json!({
        "backend": "pardal_router_cli",
        "problem": PathBuf::from(in_path).file_name().and_then(|s| s.to_str()).unwrap_or("problem.json"),
        "tracks": out_tracks,
        "vias": out_vias,
        "failed_nets": failed,
        "grid_overused_cells": overused_cells,
        "grid_max_cell_usage": max_cell_usage,
        "grid_overused_samples": grid_overuse_samples(&grid, problem.width, problem.height, 200),
        "stats_total": if cfg.emit_stats { serde_json::json!({
            "elapsed_ms": stats.elapsed_ms_total,
            "astar": {
                "heap_push": stats.astar.heap_push,
                "heap_pop": stats.astar.heap_pop,
                "relax_attempts": stats.astar.relax_attempts,
                "relax_success": stats.astar.relax_success,
                "rej_bounds": stats.astar.rej_bounds,
                "rej_base_blocked": stats.astar.rej_base_blocked,
                "rej_forbidden": stats.astar.rej_forbidden,
                "rej_occ_other": stats.astar.rej_occ_other,
                "rej_ko_track": stats.astar.rej_ko_track,
                "rej_ko_via": stats.astar.rej_ko_via
            }
        }) } else { serde_json::Value::Null },
        "stats_by_spec": if cfg.emit_stats {
            serde_json::Value::Array(stats.per_spec.iter().map(|s| serde_json::json!({
                "spec_idx": s.spec_idx,
                "net": s.net,
                "elapsed_ms": s.elapsed_ms,
                "astar": {
                    "heap_push": s.astar.heap_push,
                    "heap_pop": s.astar.heap_pop,
                    "relax_attempts": s.astar.relax_attempts,
                    "relax_success": s.astar.relax_success,
                    "rej_bounds": s.astar.rej_bounds,
                    "rej_base_blocked": s.astar.rej_base_blocked,
                    "rej_forbidden": s.astar.rej_forbidden,
                    "rej_occ_other": s.astar.rej_occ_other,
                    "rej_ko_track": s.astar.rej_ko_track,
                    "rej_ko_via": s.astar.rej_ko_via
                }
            })).collect())
        } else {
            serde_json::Value::Null
        },
    });
    fs::write(
        out_path,
        serde_json::to_string_pretty(&payload).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;

    Ok(())
}
