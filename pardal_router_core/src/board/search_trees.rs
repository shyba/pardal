use crate::board_nm::BoardNm;
use crate::drc_nm::{TerminalNm, TrackNm, ViaNm};
use crate::geom_nm::Nm;
use crate::spatial_nm::{aabb_circle_nm, aabb_segment_nm, AabbNm, SpatialHashNm};

#[derive(Debug)]
pub struct SearchTreesNm {
    cell: i64,
    track_aabbs: Vec<AabbNm>,
    via_aabbs: Vec<AabbNm>,
    terminal_aabbs: Vec<AabbNm>,
    sh_tracks: SpatialHashNm,
    sh_vias: SpatialHashNm,
    sh_terminals: SpatialHashNm,
}

impl SearchTreesNm {
    pub fn new(cell: i64) -> Self {
        let cell = cell.max(1);
        Self {
            cell,
            track_aabbs: Vec::new(),
            via_aabbs: Vec::new(),
            terminal_aabbs: Vec::new(),
            sh_tracks: SpatialHashNm::new(cell),
            sh_vias: SpatialHashNm::new(cell),
            sh_terminals: SpatialHashNm::new(cell),
        }
    }

    pub fn from_board(board: &BoardNm, cell: i64, extra: Nm) -> Self {
        let mut out = Self::new(cell);
        for t in &board.tracks {
            out.insert_track(t, extra);
        }
        for v in &board.vias {
            out.insert_via(v, extra);
        }
        for p in &board.terminals {
            out.insert_terminal(p, extra);
        }
        out
    }

    pub fn cell(&self) -> i64 {
        self.cell
    }

    pub fn insert_track(&mut self, t: &TrackNm, extra: Nm) {
        let i = self.track_aabbs.len();
        let aabb = aabb_segment_nm(t.seg).inflate(Nm(t.r.0.saturating_add(extra.0)));
        self.track_aabbs.push(aabb);
        self.sh_tracks.insert_aabb(t.layer, aabb, i);
    }

    pub fn insert_via(&mut self, v: &ViaNm, extra: Nm) {
        let i = self.via_aabbs.len();
        let aabb = aabb_circle_nm(v.circle).inflate(extra);
        self.via_aabbs.push(aabb);
        for layer in v.layers.0..=v.layers.1 {
            self.sh_vias.insert_aabb(layer, aabb, i);
        }
    }

    pub fn insert_terminal(&mut self, t: &TerminalNm, extra: Nm) {
        let i = self.terminal_aabbs.len();
        let aabb = aabb_circle_nm(t.circle).inflate(extra);
        self.terminal_aabbs.push(aabb);
        for &layer in &t.layers {
            self.sh_terminals.insert_aabb(layer, aabb, i);
        }
    }

    pub fn query_tracks(&self, layer: usize, aabb: AabbNm, out: &mut Vec<usize>) {
        self.sh_tracks.query_aabb(layer, aabb, out);
        out.sort_unstable();
        out.dedup();
    }

    pub fn query_vias(&self, layer: usize, aabb: AabbNm, out: &mut Vec<usize>) {
        self.sh_vias.query_aabb(layer, aabb, out);
        out.sort_unstable();
        out.dedup();
    }

    pub fn query_terminals(&self, layer: usize, aabb: AabbNm, out: &mut Vec<usize>) {
        self.sh_terminals.query_aabb(layer, aabb, out);
        out.sort_unstable();
        out.dedup();
    }
}
