use crate::board::SearchTreesNm;
use crate::board_nm::BoardNm;
use crate::drc_nm::{TerminalNm, TrackNm, ViaNm};
use crate::geom_nm::Nm;
use crate::spatial_nm::AabbNm;

/// Minimal incremental board database for autoroute parity work.
///
/// This is an intentionally small stepping stone:
/// - stores `BoardNm` items (tracks/vias/terminals) as the authoritative source
/// - maintains a spatial hash index (`SearchTreesNm`) for fast candidate queries
///
/// It is not yet a full FreeRouting-style `RoutingBoard` replacement (no shove, undo, or
/// geometry normalization).
#[derive(Debug)]
pub struct BoardDbNm {
    pub board: BoardNm,
    pub search: SearchTreesNm,
    extra_index_inflate: Nm,
}

impl BoardDbNm {
    pub fn from_board(board: BoardNm, cell: i64, extra_index_inflate: Nm) -> Self {
        let search = SearchTreesNm::from_board(&board, cell, extra_index_inflate);
        Self {
            board,
            search,
            extra_index_inflate,
        }
    }

    pub fn rebuild_search(&mut self, cell: i64) {
        self.search = SearchTreesNm::from_board(&self.board, cell, self.extra_index_inflate);
    }

    pub fn insert_track(&mut self, t: TrackNm) -> usize {
        let idx = self.board.tracks.len();
        self.board.tracks.push(t.clone());
        self.search.insert_track(&t, self.extra_index_inflate);
        idx
    }

    pub fn insert_via(&mut self, v: ViaNm) -> usize {
        let idx = self.board.vias.len();
        self.board.vias.push(v.clone());
        self.search.insert_via(&v, self.extra_index_inflate);
        idx
    }

    pub fn insert_terminal(&mut self, t: TerminalNm) -> usize {
        let idx = self.board.terminals.len();
        self.board.terminals.push(t.clone());
        self.search.insert_terminal(&t, self.extra_index_inflate);
        idx
    }

    pub fn query_tracks(&self, layer: usize, aabb: AabbNm, out: &mut Vec<usize>) {
        self.search.query_tracks(layer, aabb, out);
    }

    pub fn query_vias(&self, layer: usize, aabb: AabbNm, out: &mut Vec<usize>) {
        self.search.query_vias(layer, aabb, out);
    }

    pub fn query_terminals(&self, layer: usize, aabb: AabbNm, out: &mut Vec<usize>) {
        self.search.query_terminals(layer, aabb, out);
    }
}
