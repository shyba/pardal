use crate::drc_nm::{
    circle_within_segment_radius_nm, segments_within_radius_nm, terminal_shape_within_circle_extra_nm,
    terminal_shape_within_polygon_extra_nm, terminal_shape_within_segment_extra_nm, terminal_shapes_on_layer,
    polygons_overlap_nm, segment_fully_inside_hole_nm, segment_within_polygon_radius_nm, terminal_shape_fully_inside_hole_nm,
    AreaNm, TerminalNm, TrackNm, ViaNm,
};
use crate::geom_nm::Nm;
use crate::spatial_nm::{aabb_circle_nm, aabb_segment_nm, SpatialHashNm};

#[derive(Debug, Default)]
struct UnionFind {
    parent: Vec<usize>,
    rank: Vec<u8>,
}

impl UnionFind {
    fn new(n: usize) -> Self {
        Self {
            parent: (0..n).collect(),
            rank: vec![0; n],
        }
    }

    fn find(&mut self, x: usize) -> usize {
        if self.parent[x] != x {
            let p = self.parent[x];
            self.parent[x] = self.find(p);
        }
        self.parent[x]
    }

    fn union(&mut self, a: usize, b: usize) {
        let mut ra = self.find(a);
        let mut rb = self.find(b);
        if ra == rb {
            return;
        }
        if self.rank[ra] < self.rank[rb] {
            std::mem::swap(&mut ra, &mut rb);
        }
        self.parent[rb] = ra;
        if self.rank[ra] == self.rank[rb] {
            self.rank[ra] = self.rank[ra].saturating_add(1);
        }
    }
}

/// Connectivity check for a single net using copper overlap checks.
///
/// Connectivity model:
/// - Items are connected when their copper shapes overlap on at least one shared layer.
/// - Track↔Track uses segment overlap with radius `(ra + rb)` on the same layer.
/// - Track↔Via uses via circle vs segment overlap with extra = track radius.
/// - Track↔Terminal uses terminal shape vs segment overlap with extra = track radius.
/// - Via↔Terminal uses terminal shape vs via circle overlap.
///
/// Returns the number of connected components that contain at least one terminal.
pub fn terminal_component_count_for_net(
    net_id: u32,
    tracks: &[TrackNm],
    vias: &[ViaNm],
    terminals: &[TerminalNm],
    layer_count: usize,
) -> usize {
    let tr: Vec<&TrackNm> = tracks.iter().filter(|t| t.net_id == net_id && t.layer < layer_count).collect();
    let vi: Vec<&ViaNm> = vias.iter().filter(|v| v.net_id == net_id).collect();
    let te: Vec<&TerminalNm> = terminals.iter().filter(|t| t.net_id == net_id).collect();

    let n_tracks = tr.len();
    let n_vias = vi.len();
    let n_terms = te.len();
    if n_terms == 0 {
        return 0;
    }

    let track_offset = 0usize;
    let via_offset = track_offset + n_tracks;
    let term_offset = via_offset + n_vias;

    let mut uf = UnionFind::new(term_offset + n_terms);

    let mut max_r: i64 = 1;
    for t in &tr {
        max_r = max_r.max(t.r.0);
    }
    for v in &vi {
        max_r = max_r.max(v.circle.r.0);
    }
    for p in &te {
        max_r = max_r.max(p.circle.r.0);
    }
    let max_r = Nm(max_r);

    // Index tracks by layer.
    let cell = (max_r.0.max(1) * 4).max(1);
    let mut sh_tracks = SpatialHashNm::new(cell);
    let mut track_aabb: Vec<_> = Vec::with_capacity(n_tracks);
    for (i, t) in tr.iter().enumerate() {
        let aabb = aabb_segment_nm(t.seg).inflate(max_r);
        sh_tracks.insert_aabb(t.layer, aabb, i);
        track_aabb.push(aabb);
    }

    // Index circles (vias + terminals) by layer.
    enum CircleKind {
        Via(usize),
        Terminal(usize),
    }
    let mut sh_circles = SpatialHashNm::new(cell);
    let mut circles: Vec<(CircleKind, crate::spatial_nm::AabbNm)> = Vec::new();

    for (i, v) in vi.iter().enumerate() {
        let aabb = aabb_circle_nm(v.circle).inflate(max_r);
        for layer in v.layers.0..=v.layers.1 {
            if layer < layer_count {
                sh_circles.insert_aabb(layer, aabb, circles.len());
            }
        }
        circles.push((CircleKind::Via(i), aabb));
    }
    for (i, p) in te.iter().enumerate() {
        let aabb = aabb_circle_nm(p.circle).inflate(max_r);
        for &layer in &p.layers {
            if layer < layer_count {
                sh_circles.insert_aabb(layer, aabb, circles.len());
            }
        }
        circles.push((CircleKind::Terminal(i), aabb));
    }

    let mut scratch: Vec<usize> = Vec::new();

    // Track ↔ Track on same layer.
    for (i, a) in tr.iter().enumerate() {
        sh_tracks.query_aabb(a.layer, track_aabb[i], &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &j in &scratch {
            if j <= i {
                continue;
            }
            let b = tr[j];
            if a.layer != b.layer {
                continue;
            }
            let r = Nm(a.r.0 + b.r.0);
            if segments_within_radius_nm(a.seg, b.seg, r) {
                uf.union(track_offset + i, track_offset + j);
            }
        }
    }

    // Track ↔ Circles (vias + terminals) on same layer.
    for (ti, t) in tr.iter().enumerate() {
        sh_circles.query_aabb(t.layer, track_aabb[ti], &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &ci in &scratch {
            let (kind, _) = &circles[ci];
            match *kind {
                CircleKind::Via(vi_i) => {
                    let v = vi[vi_i];
                    if v.layers.0 > t.layer || v.layers.1 < t.layer {
                        continue;
                    }
                    if circle_within_segment_radius_nm(v.circle, t.seg, t.r) {
                        uf.union(track_offset + ti, via_offset + vi_i);
                    }
                }
                CircleKind::Terminal(te_i) => {
                    let p = te[te_i];
                    if !p.layers.contains(&t.layer) {
                        continue;
                    }
                    if terminal_shapes_on_layer(p, t.layer)
                        .any(|s| terminal_shape_within_segment_extra_nm(s, t.seg, t.r))
                    {
                        uf.union(track_offset + ti, term_offset + te_i);
                    }
                }
            }
        }
    }

    // Via ↔ Terminal (multi-layer, check overlap on any shared layer).
    for (vi_i, v) in vi.iter().enumerate() {
        // Quick AABB query by layers using the same circle index.
        let aabb = aabb_circle_nm(v.circle).inflate(max_r);
        for layer in v.layers.0..=v.layers.1 {
            if layer >= layer_count {
                continue;
            }
            sh_circles.query_aabb(layer, aabb, &mut scratch);
            scratch.sort_unstable();
            scratch.dedup();
            for &ci in &scratch {
                let (kind, _) = &circles[ci];
                let CircleKind::Terminal(te_i) = *kind else { continue };
                let p = te[te_i];
                if !p.layers.contains(&layer) {
                    continue;
                }
                if terminal_shapes_on_layer(p, layer)
                    .any(|s| terminal_shape_within_circle_extra_nm(s, v.circle, Nm::zero()))
                {
                    uf.union(via_offset + vi_i, term_offset + te_i);
                }
            }
        }
    }

    // Count distinct terminal components.
    let mut roots: Vec<usize> = Vec::new();
    for i in 0..n_terms {
        roots.push(uf.find(term_offset + i));
    }
    roots.sort_unstable();
    roots.dedup();
    roots.len()
}

/// Like [`terminal_component_count_for_net`], but also considers same-net filled copper areas (e.g. plane polygons)
/// as connectivity bridges.
pub fn terminal_component_count_for_net_with_areas(
    net_id: u32,
    tracks: &[TrackNm],
    vias: &[ViaNm],
    terminals: &[TerminalNm],
    areas: &[AreaNm],
    layer_count: usize,
) -> usize {
    let tr: Vec<&TrackNm> = tracks.iter().filter(|t| t.net_id == net_id && t.layer < layer_count).collect();
    let vi: Vec<&ViaNm> = vias.iter().filter(|v| v.net_id == net_id).collect();
    let te: Vec<&TerminalNm> = terminals.iter().filter(|t| t.net_id == net_id).collect();
    let ar: Vec<&AreaNm> = areas.iter().filter(|a| a.net_id == net_id && a.layer < layer_count).collect();

    let n_tracks = tr.len();
    let n_vias = vi.len();
    let n_terms = te.len();
    let n_areas = ar.len();
    if n_terms == 0 {
        return 0;
    }

    let track_offset = 0usize;
    let via_offset = track_offset + n_tracks;
    let term_offset = via_offset + n_vias;
    let area_offset = term_offset + n_terms;

    let mut uf = UnionFind::new(area_offset + n_areas);

    let mut max_r: i64 = 1;
    for t in &tr {
        max_r = max_r.max(t.r.0);
    }
    for v in &vi {
        max_r = max_r.max(v.circle.r.0);
    }
    for p in &te {
        max_r = max_r.max(p.circle.r.0);
    }
    let max_r = Nm(max_r);

    let cell = (max_r.0.max(1) * 4).max(1);
    let mut sh_tracks = SpatialHashNm::new(cell);
    let mut track_aabb: Vec<_> = Vec::with_capacity(n_tracks);
    for (i, t) in tr.iter().enumerate() {
        let aabb = aabb_segment_nm(t.seg).inflate(max_r);
        sh_tracks.insert_aabb(t.layer, aabb, i);
        track_aabb.push(aabb);
    }

    enum CircleKind {
        Via(usize),
        Terminal(usize),
    }
    let mut sh_circles = SpatialHashNm::new(cell);
    let mut circles: Vec<(CircleKind, crate::spatial_nm::AabbNm)> = Vec::new();

    for (i, v) in vi.iter().enumerate() {
        let aabb = aabb_circle_nm(v.circle).inflate(max_r);
        for layer in v.layers.0..=v.layers.1 {
            if layer < layer_count {
                sh_circles.insert_aabb(layer, aabb, circles.len());
            }
        }
        circles.push((CircleKind::Via(i), aabb));
    }
    for (i, p) in te.iter().enumerate() {
        let aabb = aabb_circle_nm(p.circle).inflate(max_r);
        for &layer in &p.layers {
            if layer < layer_count {
                sh_circles.insert_aabb(layer, aabb, circles.len());
            }
        }
        circles.push((CircleKind::Terminal(i), aabb));
    }

    let mut sh_areas = SpatialHashNm::new(cell);
    let mut area_aabb: Vec<crate::spatial_nm::AabbNm> = Vec::with_capacity(n_areas);
    for (i, a) in ar.iter().enumerate() {
        let mut min_x = i64::MAX;
        let mut min_y = i64::MAX;
        let mut max_x = i64::MIN;
        let mut max_y = i64::MIN;
        for p in &a.polygon {
            min_x = min_x.min(p.x.0);
            min_y = min_y.min(p.y.0);
            max_x = max_x.max(p.x.0);
            max_y = max_y.max(p.y.0);
        }
        let aabb = crate::spatial_nm::AabbNm {
            min_x,
            min_y,
            max_x,
            max_y,
        };
        sh_areas.insert_aabb(a.layer, aabb.inflate(max_r), i);
        area_aabb.push(aabb);
    }

    let mut scratch: Vec<usize> = Vec::new();

    // Track ↔ Track on same layer.
    for (i, a) in tr.iter().enumerate() {
        sh_tracks.query_aabb(a.layer, track_aabb[i], &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &j in &scratch {
            if j <= i {
                continue;
            }
            let b = tr[j];
            if a.layer != b.layer {
                continue;
            }
            let r = Nm(a.r.0 + b.r.0);
            if segments_within_radius_nm(a.seg, b.seg, r) {
                uf.union(track_offset + i, track_offset + j);
            }
        }
    }

    // Track ↔ Circles (vias + terminals) on same layer.
    for (ti, t) in tr.iter().enumerate() {
        sh_circles.query_aabb(t.layer, track_aabb[ti], &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &ci in &scratch {
            let (kind, _) = &circles[ci];
            match *kind {
                CircleKind::Via(vi_i) => {
                    let v = vi[vi_i];
                    if v.layers.0 > t.layer || v.layers.1 < t.layer {
                        continue;
                    }
                    if circle_within_segment_radius_nm(v.circle, t.seg, t.r) {
                        uf.union(track_offset + ti, via_offset + vi_i);
                    }
                }
                CircleKind::Terminal(te_i) => {
                    let p = te[te_i];
                    if !p.layers.contains(&t.layer) {
                        continue;
                    }
                    if terminal_shapes_on_layer(p, t.layer)
                        .any(|s| terminal_shape_within_segment_extra_nm(s, t.seg, t.r))
                    {
                        uf.union(track_offset + ti, term_offset + te_i);
                    }
                }
            }
        }
    }

    // Via ↔ Terminal (multi-layer).
    for (vi_i, v) in vi.iter().enumerate() {
        let aabb = aabb_circle_nm(v.circle).inflate(max_r);
        for layer in v.layers.0..=v.layers.1 {
            if layer >= layer_count {
                continue;
            }
            sh_circles.query_aabb(layer, aabb, &mut scratch);
            scratch.sort_unstable();
            scratch.dedup();
            for &ci in &scratch {
                let (kind, _) = &circles[ci];
                let CircleKind::Terminal(te_i) = *kind else { continue };
                let p = te[te_i];
                if !p.layers.contains(&layer) {
                    continue;
                }
                if terminal_shapes_on_layer(p, layer)
                    .any(|s| terminal_shape_within_circle_extra_nm(s, v.circle, Nm::zero()))
                {
                    uf.union(via_offset + vi_i, term_offset + te_i);
                }
            }
        }
    }

    // Copper areas as connectivity bridges.
    //
    // Track ↔ Area
    for (ti, t) in tr.iter().enumerate() {
        sh_areas.query_aabb(t.layer, track_aabb[ti], &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &ai in &scratch {
            let a = ar[ai];
            if a.layer != t.layer {
                continue;
            }
            if segment_within_polygon_radius_nm(t.seg, &a.polygon, t.r)
                && !a.holes.iter().any(|h| segment_fully_inside_hole_nm(t.seg, h, t.r))
            {
                uf.union(track_offset + ti, area_offset + ai);
            }
        }
    }

    // Terminal ↔ Area
    for (pi, p) in te.iter().enumerate() {
        let aabb = aabb_circle_nm(p.circle).inflate(max_r);
        for &layer in &p.layers {
            sh_areas.query_aabb(layer, aabb, &mut scratch);
            scratch.sort_unstable();
            scratch.dedup();
            for &ai in &scratch {
                let a = ar[ai];
                if a.layer != layer {
                    continue;
                }
                if terminal_shapes_on_layer(p, layer).any(|s| {
                    terminal_shape_within_polygon_extra_nm(s, &a.polygon, Nm::zero())
                        && !a.holes.iter().any(|h| terminal_shape_fully_inside_hole_nm(s, h, Nm::zero()))
                }) {
                    uf.union(term_offset + pi, area_offset + ai);
                }
            }
        }
    }

    // Via ↔ Area
    for (vi_i, v) in vi.iter().enumerate() {
        let aabb = aabb_circle_nm(v.circle).inflate(max_r);
        for layer in v.layers.0..=v.layers.1 {
            if layer >= layer_count {
                continue;
            }
            sh_areas.query_aabb(layer, aabb, &mut scratch);
            scratch.sort_unstable();
            scratch.dedup();
            for &ai in &scratch {
                let a = ar[ai];
                if a.layer != layer {
                    continue;
                }
                // Approximate via copper overlap with the area by using the via circle.
                let shape = crate::drc_nm::TerminalShapeNm::Circle { layer, circle: v.circle };
                if terminal_shape_within_polygon_extra_nm(
                    &shape,
                    &a.polygon,
                    Nm::zero(),
                ) && !a.holes.iter().any(|h| terminal_shape_fully_inside_hole_nm(&shape, h, Nm::zero())) {
                    uf.union(via_offset + vi_i, area_offset + ai);
                }
            }
        }
    }

    // Area ↔ Area
    for (ai, a) in ar.iter().enumerate() {
        sh_areas.query_aabb(a.layer, area_aabb[ai].inflate(max_r), &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &aj in &scratch {
            if aj <= ai {
                continue;
            }
            let b = ar[aj];
            if b.layer != a.layer {
                continue;
            }
            if polygons_overlap_nm(&a.polygon, &b.polygon) {
                uf.union(area_offset + ai, area_offset + aj);
            }
        }
    }

    // Count distinct terminal components.
    let mut roots: Vec<usize> = Vec::new();
    for i in 0..n_terms {
        roots.push(uf.find(term_offset + i));
    }
    roots.sort_unstable();
    roots.dedup();
    roots.len()
}

/// Returns net IDs whose terminals appear disconnected (multiple terminal components).
pub fn nets_with_disconnected_terminals(
    tracks: &[TrackNm],
    vias: &[ViaNm],
    terminals: &[TerminalNm],
    layer_count: usize,
) -> Vec<u32> {
    let mut nets: Vec<u32> = terminals.iter().map(|t| t.net_id).collect();
    nets.sort_unstable();
    nets.dedup();

    let mut out: Vec<u32> = Vec::new();
    for net_id in nets {
        if terminal_component_count_for_net(net_id, tracks, vias, terminals, layer_count) > 1 {
            out.push(net_id);
        }
    }
    out
}

/// Like [`nets_with_disconnected_terminals`], but includes same-net filled copper areas (planes).
pub fn nets_with_disconnected_terminals_with_areas(
    tracks: &[TrackNm],
    vias: &[ViaNm],
    terminals: &[TerminalNm],
    areas: &[AreaNm],
    layer_count: usize,
) -> Vec<u32> {
    let mut nets: Vec<u32> = terminals.iter().map(|t| t.net_id).collect();
    nets.sort_unstable();
    nets.dedup();

    let mut out: Vec<u32> = Vec::new();
    for net_id in nets {
        if terminal_component_count_for_net_with_areas(net_id, tracks, vias, terminals, areas, layer_count) > 1 {
            out.push(net_id);
        }
    }
    out
}
