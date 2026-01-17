use blake3::Hasher;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoutingIr {
    pub layers: usize,
    pub width: usize,
    pub height: usize,
    /// Flattened occupancy, indexed by `(layer * width * height) + (y * width + x)`.
    pub occ: Vec<u32>,
    /// Flattened pin/pad ownership mask, indexed like `occ`.
    ///
    /// This is a routing-only mask used to model “unpoppable” pad copper:
    /// - `0` means no pad at this cell.
    /// - non-zero means the cell belongs to a pad owned by `net_id`.
    ///
    /// Unlike `occ`, this is not modified by commit/uncommit kernels. It exists to:
    /// - keep other nets from routing through pads even when allowing negotiation/ripup through traces
    /// - still allow a net to legally route into its own pads
    #[serde(default)]
    pub pad_owner: Vec<u32>,
    /// Per-cell via restriction mask, indexed like `occ`.
    ///
    /// - `0` means vias are allowed at this cell.
    /// - non-zero means vias are forbidden at this cell.
    ///
    /// This is intended to model Specctra/Freerouting `via_keepout` regions without also
    /// blocking trace routing through that region.
    #[serde(default)]
    pub via_forbidden: Vec<u8>,
}

impl RoutingIr {
    pub fn new(layers: usize, width: usize, height: usize) -> Self {
        let len = layers
            .checked_mul(width)
            .and_then(|v| v.checked_mul(height))
            .expect("grid too large");
        Self {
            layers,
            width,
            height,
            occ: vec![0; len],
            pad_owner: vec![0; len],
            via_forbidden: vec![0; len],
        }
    }

    #[inline]
    pub fn idx(&self, layer: usize, x: usize, y: usize) -> usize {
        (layer * self.width * self.height) + (y * self.width + x)
    }

    pub fn set_occ(&mut self, layer: usize, x: usize, y: usize, v: u32) {
        let i = self.idx(layer, x, y);
        self.occ[i] = v;
    }

    pub fn get_occ(&self, layer: usize, x: usize, y: usize) -> u32 {
        self.occ[self.idx(layer, x, y)]
    }

    pub fn set_pad_owner(&mut self, layer: usize, x: usize, y: usize, v: u32) {
        let i = self.idx(layer, x, y);
        if self.pad_owner.len() == self.occ.len() {
            self.pad_owner[i] = v;
        }
    }

    pub fn get_pad_owner(&self, layer: usize, x: usize, y: usize) -> u32 {
        let i = self.idx(layer, x, y);
        if self.pad_owner.len() == self.occ.len() {
            self.pad_owner[i]
        } else {
            0
        }
    }

    pub fn set_via_forbidden(&mut self, layer: usize, x: usize, y: usize, v: u8) {
        let i = self.idx(layer, x, y);
        if self.via_forbidden.len() == self.occ.len() {
            self.via_forbidden[i] = v;
        }
    }

    pub fn get_via_forbidden(&self, layer: usize, x: usize, y: usize) -> u8 {
        let i = self.idx(layer, x, y);
        if self.via_forbidden.len() == self.occ.len() {
            self.via_forbidden[i]
        } else {
            0
        }
    }

    pub fn normalize_lengths(mut self) -> Self {
        if self.pad_owner.len() != self.occ.len() {
            self.pad_owner = vec![0; self.occ.len()];
        }
        if self.via_forbidden.len() != self.occ.len() {
            self.via_forbidden = vec![0; self.occ.len()];
        }
        self
    }

    /// Stable hash over the routing-relevant state of the IR.
    pub fn stable_hash(&self) -> [u8; 32] {
        let mut hasher = Hasher::new();
        hasher.update(&(self.layers as u64).to_le_bytes());
        hasher.update(&(self.width as u64).to_le_bytes());
        hasher.update(&(self.height as u64).to_le_bytes());

        // `u32` is well-defined in memory as 4 bytes; use LE to be explicit.
        for &v in &self.occ {
            hasher.update(&v.to_le_bytes());
        }
        if self.pad_owner.len() == self.occ.len() {
            for &v in &self.pad_owner {
                hasher.update(&v.to_le_bytes());
            }
        } else {
            // Hash as if `pad_owner` were all zeros, without allocating.
            let zeros = [0u8; 4096];
            let mut remaining = self.occ.len() * 4;
            while remaining > 0 {
                let n = remaining.min(zeros.len());
                hasher.update(&zeros[..n]);
                remaining -= n;
            }
        }
        if self.via_forbidden.len() == self.occ.len() {
            hasher.update(&self.via_forbidden);
        } else {
            // Hash as if `via_forbidden` were all zeros, without allocating.
            let zeros = [0u8; 4096];
            let mut remaining = self.occ.len();
            while remaining > 0 {
                let n = remaining.min(zeros.len());
                hasher.update(&zeros[..n]);
                remaining -= n;
            }
        }
        *hasher.finalize().as_bytes()
    }

    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }

    pub fn from_json(s: &str) -> Result<Self, serde_json::Error> {
        Ok(serde_json::from_str::<Self>(s)?.normalize_lengths())
    }

    /// Build a simple, static cost field derived from obstacle proximity.
    ///
    /// This is intended to bias routing away from boundaries/keepouts/other copper without
    /// changing reachability. The cost is computed only for free cells (`occ == 0`); all other
    /// cells receive `0` cost (they are blocked anyway for most routing modes).
    ///
    /// - `blocked_value` is the value used for hard obstacles in `occ` (typically `1`).
    /// - `occ_penalty` is added when any neighbor has `occ != 0` and `occ != blocked_value`.
    /// - `blocked_penalty` is added when any neighbor has `occ == blocked_value`.
    ///
    /// Neighborhood: 8-connected (Chebyshev radius 1).
    pub fn build_cost_field_adjacent(
        &self,
        blocked_value: u32,
        occ_penalty: u16,
        blocked_penalty: u16,
    ) -> Vec<u16> {
        let n = self.occ.len();
        let mut out = vec![0u16; n];
        if self.width == 0 || self.height == 0 || self.layers == 0 {
            return out;
        }

        let w = self.width;
        let h = self.height;
        let n2 = w * h;
        let have_pad_owner = self.pad_owner.len() == self.occ.len();

        for layer in 0..self.layers {
            let base = layer * n2;
            for y in 0..h {
                let row = base + y * w;
                for x in 0..w {
                    let i = row + x;
                    if self.occ[i] != 0 {
                        continue;
                    }

                    let mut c: u16 = 0;

                    // Fast path for interior cells: unrolled 8-neighborhood without bounds checks.
                    if x > 0 && x + 1 < w && y > 0 && y + 1 < h {
                        let up = i - w;
                        let dn = i + w;

                        for ni in [
                            up - 1,
                            up,
                            up + 1,
                            i - 1,
                            i + 1,
                            dn - 1,
                            dn,
                            dn + 1,
                        ] {
                            let occ = self.occ[ni];
                            let pad = if have_pad_owner { self.pad_owner[ni] } else { 0 };
                            if occ == 0 && pad == 0 {
                                continue;
                            }
                            if occ == blocked_value {
                                c = c.saturating_add(blocked_penalty);
                            } else {
                                c = c.saturating_add(occ_penalty);
                            }
                        }
                        out[i] = c;
                        continue;
                    }

                    // Boundary slow path: handle edges/corners with bounds checks.
                    for dy in [-1isize, 0, 1] {
                        for dx in [-1isize, 0, 1] {
                            if dx == 0 && dy == 0 {
                                continue;
                            }
                            let nx = x as isize + dx;
                            let ny = y as isize + dy;
                            if nx < 0 || ny < 0 {
                                continue;
                            }
                            let (nxu, nyu) = (nx as usize, ny as usize);
                            if nxu >= w || nyu >= h {
                                continue;
                            }
                            let ni = base + nyu * w + nxu;
                            let occ = self.occ[ni];
                            let pad = if have_pad_owner { self.pad_owner[ni] } else { 0 };
                            if occ == 0 && pad == 0 {
                                continue;
                            }
                            if occ == blocked_value {
                                c = c.saturating_add(blocked_penalty);
                            } else {
                                c = c.saturating_add(occ_penalty);
                            }
                        }
                    }
                    out[i] = c;
                }
            }
        }

        out
    }
}
