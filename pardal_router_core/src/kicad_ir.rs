use serde::{Deserialize, Serialize};

use crate::geom::{LayeredPolygon, Rect, Via};
use crate::ir::RoutingIr;
use crate::kernels::{k0_rasterize_layered_polygons_occ, k0_rasterize_rects_occ, k0_rasterize_vias_occ};

/// Minimal normalized input schema for building a routing IR.
///
/// This is a stepping stone toward the planned KiCad extraction pipeline:
/// `pcbnew -> normalized primitives -> RoutingIr`.
///
/// Notes:
/// - Coordinates are already in grid-cell units (not KiCad nm); higher-level code is
///   responsible for choosing the grid resolution and snapping.
/// - `blocked_value` is provided at build time so callers can select different occupancy
///   conventions (e.g. `1` for obstacles, or a per-net owner id space).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NormalizedIrInput {
    pub layers: usize,
    pub width: usize,
    pub height: usize,

    /// Axis-aligned rectangle fills per layer.
    pub rects: Vec<LayeredRect>,

    /// Filled polygons per layer (for pads/keepouts/outlines after rasterization).
    pub polygons: Vec<LayeredPolygon>,

    /// Via obstacles stamped across their `layers` span.
    pub vias: Vec<Via>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LayeredRect {
    pub layer: usize,
    pub rect: Rect,
}

impl LayeredRect {
    pub fn new(layer: usize, rect: Rect) -> Self {
        Self { layer, rect }
    }
}

/// Builds a `RoutingIr` by stamping the provided obstacles with `blocked_value`.
pub fn build_routing_ir(input: &NormalizedIrInput, blocked_value: u32) -> RoutingIr {
    let mut ir = RoutingIr::new(input.layers, input.width, input.height);

    if !input.polygons.is_empty() {
        k0_rasterize_layered_polygons_occ(&mut ir, &input.polygons, blocked_value);
    }

    if !input.vias.is_empty() {
        k0_rasterize_vias_occ(&mut ir, &input.vias, blocked_value);
    }

    if !input.rects.is_empty() {
        let mut per_layer: Vec<Vec<Rect>> = vec![Vec::new(); ir.layers];
        for lr in &input.rects {
            if lr.layer < ir.layers {
                per_layer[lr.layer].push(lr.rect);
            }
        }
        for (layer, rects) in per_layer.iter().enumerate() {
            if !rects.is_empty() {
                k0_rasterize_rects_occ(&mut ir, layer, rects, blocked_value);
            }
        }
    }

    ir
}

