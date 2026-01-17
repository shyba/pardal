use crate::dsn::{DsnModel, DsnSummary, DsnWiring, KeepoutKind, KeepoutShapeDef};
use crate::geom::{Circle, Polygon, Rect};
use crate::ir::RoutingIr;
use crate::kernels::{k0_rasterize_circles_occ, k0_rasterize_polygon_fill_occ, k0_rasterize_rects_occ};
use crate::router::Point;
use std::collections::HashMap;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GridTransform {
    pub origin_x: f64,
    pub origin_y: f64,
    pub pitch: f64,
}

impl GridTransform {
    pub fn world_to_grid(&self, x: f64, y: f64) -> Option<Point> {
        if self.pitch <= 0.0 {
            return None;
        }
        let gx = ((x - self.origin_x) / self.pitch).round();
        let gy = ((y - self.origin_y) / self.pitch).round();
        if !gx.is_finite() || !gy.is_finite() || gx < 0.0 || gy < 0.0 {
            return None;
        }
        Some(Point {
            x: gx as usize,
            y: gy as usize,
        })
    }

    pub fn grid_to_world(&self, p: Point) -> (f64, f64) {
        (
            self.origin_x + (p.x as f64) * self.pitch,
            self.origin_y + (p.y as f64) * self.pitch,
        )
    }
}

pub fn build_empty_ir_from_summary(summary: &DsnSummary, pitch: f64) -> Option<(RoutingIr, GridTransform)> {
    let bbox = summary.boundary_bbox?;
    if pitch <= 0.0 {
        return None;
    }
    let w = ((bbox.max_x - bbox.min_x).abs() / pitch).ceil() as usize + 1;
    let h = ((bbox.max_y - bbox.min_y).abs() / pitch).ceil() as usize + 1;
    if w == 0 || h == 0 {
        return None;
    }
    let ir = RoutingIr::new(summary.layer_count.max(1), w, h);
    let tx = GridTransform {
        origin_x: bbox.min_x.min(bbox.max_x),
        origin_y: bbox.min_y.min(bbox.max_y),
        pitch,
    };
    Some((ir, tx))
}

pub fn stamp_pins_as_square_keepouts(
    ir: &mut RoutingIr,
    tx: GridTransform,
    model: &DsnModel,
    layer: usize,
    blocked_value: u32,
    allow: &[&str],
) {
    let allow_set: std::collections::HashSet<&str> = allow.iter().copied().collect();
    let mut rects: Vec<Rect> = Vec::new();

    for (pin_ref, pin) in &model.pins {
        if allow_set.contains(pin_ref.as_str()) {
            continue;
        }
        let r = model.padstacks.get(&pin.padstack).copied().unwrap_or(0.0);
        let center = match tx.world_to_grid(pin.x, pin.y) {
            Some(p) => p,
            None => continue,
        };
        let r_cells = (r / tx.pitch).ceil() as isize;
        let x0 = (center.x as isize - r_cells).max(0) as usize;
        let y0 = (center.y as isize - r_cells).max(0) as usize;
        let x1 = (center.x as isize + r_cells + 1).max(0) as usize;
        let y1 = (center.y as isize + r_cells + 1).max(0) as usize;
        rects.push(Rect::new(x0, y0, x1, y1));
    }

    k0_rasterize_rects_occ(ir, layer, &rects, blocked_value);
}

pub fn stamp_pins_as_circular_keepouts(
    ir: &mut RoutingIr,
    tx: GridTransform,
    model: &DsnModel,
    layer: usize,
    blocked_value: u32,
    allow: &[&str],
) {
    let allow_set: std::collections::HashSet<&str> = allow.iter().copied().collect();
    let mut circles: Vec<Circle> = Vec::new();

    for (pin_ref, pin) in &model.pins {
        if allow_set.contains(pin_ref.as_str()) {
            continue;
        }
        let r = model.padstacks.get(&pin.padstack).copied().unwrap_or(0.0);
        let center = match tx.world_to_grid(pin.x, pin.y) {
            Some(p) => p,
            None => continue,
        };
        let r_cells = (r / tx.pitch).ceil() as usize;
        if r_cells == 0 {
            continue;
        }
        circles.push(Circle::new(center, r_cells));
    }

    k0_rasterize_circles_occ(ir, layer, &circles, blocked_value);
}

/// Stamp pin keepouts on the layers implied by each pin's padstack definition.
///
/// If a padstack has no known layers, the pin is stamped on all layers (conservative fallback).
pub fn stamp_pins_as_circular_keepouts_by_padstack_layers(
    ir: &mut RoutingIr,
    tx: GridTransform,
    model: &DsnModel,
    blocked_value: u32,
    allow: &[&str],
) {
    let allow_set: std::collections::HashSet<&str> = allow.iter().copied().collect();
    let mut circles_by_layer: std::collections::HashMap<usize, Vec<Circle>> = std::collections::HashMap::new();

    for (pin_ref, pin) in &model.pins {
        if allow_set.contains(pin_ref.as_str()) {
            continue;
        }
        let r = model.padstacks.get(&pin.padstack).copied().unwrap_or(0.0);
        let center = match tx.world_to_grid(pin.x, pin.y) {
            Some(p) => p,
            None => continue,
        };
        let r_cells = (r / tx.pitch).ceil() as usize;
        if r_cells == 0 {
            continue;
        }

        let layers: Vec<usize> = match model.padstack_layers.get(&pin.padstack) {
            Some(ls) if !ls.is_empty() => ls.clone(),
            _ => (0..ir.layers).collect(),
        };
        for &layer in &layers {
            if layer >= ir.layers {
                continue;
            }
            circles_by_layer
                .entry(layer)
                .or_default()
                .push(Circle::new(center, r_cells));
        }
    }

    for (layer, circles) in circles_by_layer {
        k0_rasterize_circles_occ(ir, layer, &circles, blocked_value);
    }
}

/// Stamp pin keepouts using the explicit padstack copper shapes (circle/polygon/path).
///
/// This is more accurate than `stamp_pins_as_circular_keepouts_by_padstack_layers`, which uses only
/// a bounding radius.
pub fn stamp_pins_as_keepouts_from_shapes(
    ir: &mut RoutingIr,
    tx: GridTransform,
    model: &DsnModel,
    blocked_value: u32,
    allow: &[&str],
) {
    let allow_set: std::collections::HashSet<&str> = allow.iter().copied().collect();
    if ir.width == 0 || ir.height == 0 || ir.layers == 0 {
        return;
    }

    let n2 = ir.width * ir.height;
    let mut masks: Vec<Vec<u8>> = (0..ir.layers).map(|_| vec![0u8; n2]).collect();

    for (pin_ref, pin) in &model.pins {
        if allow_set.contains(pin_ref.as_str()) {
            continue;
        }
        if pin.shapes.is_empty() {
            // Fallback to a conservative circle based on the padstack radius if shapes are missing.
            let r = model.padstacks.get(&pin.padstack).copied().unwrap_or(0.0);
            let center = match tx.world_to_grid(pin.x, pin.y) {
                Some(p) => p,
                None => continue,
            };
            let r_cells = (r / tx.pitch).ceil() as usize;
            if r_cells == 0 {
                continue;
            }
            for layer in 0..ir.layers {
                stamp_circle_mask_u8(&mut masks[layer], ir.width, ir.height, center, r_cells, 1);
            }
            continue;
        }

        for shape in &pin.shapes {
            match shape {
                crate::dsn::PadShapeDef::Circle {
                    layer,
                    diameter,
                    x,
                    y,
                } => {
                    let layers = layer_list_from_token(model, layer, ir.layers);
                    let center = match tx.world_to_grid(*x, *y) {
                        Some(p) => p,
                        None => continue,
                    };
                    let r = (*diameter * 0.5).max(0.0);
                    let r_cells = (r / tx.pitch).ceil() as usize;
                    if r_cells == 0 {
                        continue;
                    }
                    for &l in &layers {
                        if l < ir.layers {
                            stamp_circle_mask_u8(&mut masks[l], ir.width, ir.height, center, r_cells, 1);
                        }
                    }
                }
                crate::dsn::PadShapeDef::Polygon { layer, points } => {
                    let layers = layer_list_from_token(model, layer, ir.layers);
                    let mut verts: Vec<Point> = Vec::new();
                    for &(x, y) in points {
                        if let Some(p) = tx.world_to_grid(x, y) {
                            if p.x < ir.width && p.y < ir.height {
                                verts.push(p);
                            }
                        }
                    }
                    if verts.len() < 3 {
                        continue;
                    }
                    let poly = Polygon::new(verts);
                    for &l in &layers {
                        if l < ir.layers {
                            stamp_polygon_fill_mask_u8(&mut masks[l], ir.width, ir.height, &poly, 1);
                        }
                    }
                }
                crate::dsn::PadShapeDef::Path {
                    layer,
                    width,
                    points,
                } => {
                    let layers = layer_list_from_token(model, layer, ir.layers);
                    let mut verts: Vec<Point> = Vec::new();
                    for &(x, y) in points {
                        if let Some(p) = tx.world_to_grid(x, y) {
                            if p.x < ir.width && p.y < ir.height {
                                verts.push(p);
                            }
                        }
                    }
                    if verts.len() < 2 {
                        continue;
                    }
                    let r = (*width * 0.5).max(0.0);
                    let r_cells = (r / tx.pitch).ceil() as usize;
                    if r_cells == 0 {
                        continue;
                    }
                    for &l in &layers {
                        if l < ir.layers {
                            stamp_path_mask_u8(&mut masks[l], ir.width, ir.height, &verts, r_cells, 1);
                        }
                    }
                }
            }
        }
    }

    // Apply the mask, preserving any already-stamped occupancy (existing copper/keepouts/boundary).
    for layer in 0..ir.layers {
        let base = layer * n2;
        for i in 0..n2 {
            if masks[layer][i] != 0 && ir.occ[base + i] == 0 {
                ir.occ[base + i] = blocked_value;
            }
        }
    }
}

/// Apply a boundary mask to a layer:
/// - sets the whole layer to `blocked_value`,
/// - then clears the interior of `boundary_world` (free = `0`) using polygon fill.
///
/// This is intended to be called before stamping pads/keepouts/routes into `occ`.
pub fn apply_boundary_mask_from_world_polygon(
    ir: &mut RoutingIr,
    tx: GridTransform,
    layer: usize,
    blocked_value: u32,
    boundary_world: &[(f64, f64)],
) -> bool {
    if layer >= ir.layers {
        return false;
    }
    if boundary_world.len() < 3 {
        return false;
    }

    let base = layer * ir.width * ir.height;
    ir.occ[base..base + (ir.width * ir.height)].fill(blocked_value);

    let mut verts: Vec<Point> = Vec::new();
    for &(x, y) in boundary_world {
        if let Some(p) = tx.world_to_grid(x, y) {
            if p.x < ir.width && p.y < ir.height {
                verts.push(p);
            }
        }
    }
    if verts.len() < 3 {
        return false;
    }

    k0_rasterize_polygon_fill_occ(ir, layer, &[Polygon::new(verts)], 0);
    true
}

/// Like `apply_boundary_mask_from_world_polygon`, but also blocks interior cutouts/holes.
pub fn apply_boundary_mask_from_world_polygon_with_holes(
    ir: &mut RoutingIr,
    tx: GridTransform,
    layer: usize,
    blocked_value: u32,
    outer_world: &[(f64, f64)],
    holes_world: &[Vec<(f64, f64)>],
) -> bool {
    if !apply_boundary_mask_from_world_polygon(ir, tx, layer, blocked_value, outer_world) {
        return false;
    }
    for hole in holes_world {
        if hole.len() < 3 {
            continue;
        }
        let mut verts: Vec<Point> = Vec::new();
        for &(x, y) in hole {
            if let Some(p) = tx.world_to_grid(x, y) {
                if p.x < ir.width && p.y < ir.height {
                    verts.push(p);
                }
            }
        }
        if verts.len() < 3 {
            continue;
        }
        k0_rasterize_polygon_fill_occ(ir, layer, &[Polygon::new(verts)], blocked_value);
    }
    true
}

/// Apply a boundary mask with multiple disjoint outer polygons ("islands") and cutouts ("holes").
///
/// The layer is first filled with `blocked_value`, then every `outer_world` polygon is cleared to `0`,
/// and finally every hole polygon is filled with `blocked_value`.
pub fn apply_boundary_mask_from_world_polygons_with_holes(
    ir: &mut RoutingIr,
    tx: GridTransform,
    layer: usize,
    blocked_value: u32,
    outers_world: &[Vec<(f64, f64)>],
    holes_world: &[Vec<(f64, f64)>],
) -> bool {
    if layer >= ir.layers {
        return false;
    }
    if outers_world.is_empty() {
        return false;
    }

    let base = layer * ir.width * ir.height;
    ir.occ[base..base + (ir.width * ir.height)].fill(blocked_value);

    let mut any_outer = false;
    for outer in outers_world {
        if outer.len() < 3 {
            continue;
        }
        let mut verts: Vec<Point> = Vec::new();
        for &(x, y) in outer {
            if let Some(p) = tx.world_to_grid(x, y) {
                if p.x < ir.width && p.y < ir.height {
                    verts.push(p);
                }
            }
        }
        if verts.len() < 3 {
            continue;
        }
        any_outer = true;
        k0_rasterize_polygon_fill_occ(ir, layer, &[Polygon::new(verts)], 0);
    }
    if !any_outer {
        return false;
    }

    for hole in holes_world {
        if hole.len() < 3 {
            continue;
        }
        let mut verts: Vec<Point> = Vec::new();
        for &(x, y) in hole {
            if let Some(p) = tx.world_to_grid(x, y) {
                if p.x < ir.width && p.y < ir.height {
                    verts.push(p);
                }
            }
        }
        if verts.len() < 3 {
            continue;
        }
        k0_rasterize_polygon_fill_occ(ir, layer, &[Polygon::new(verts)], blocked_value);
    }

    true
}

fn layer_list_from_token(model: &DsnModel, layer: &str, layers: usize) -> Vec<usize> {
    if let Ok(n) = layer.parse::<i64>() {
        if n >= 1 {
            let idx = (n - 1) as usize;
            return if idx < layers { vec![idx] } else { Vec::new() };
        }
    }
    if let Some(&idx) = model.layer_name_to_index.get(layer) {
        return if idx < layers { vec![idx] } else { Vec::new() };
    }
    // Common Specctra aliases.
    if layer.eq_ignore_ascii_case("signal") || layer.eq_ignore_ascii_case("pcb") {
        return (0..layers).collect();
    }
    (0..layers).collect()
}

fn stamp_circle_mask_u8(mask: &mut [u8], width: usize, height: usize, center: Point, r: usize, value: u8) {
    if r == 0 || width == 0 || height == 0 {
        return;
    }
    let r_i = r as isize;
    let cx = center.x as isize;
    let cy = center.y as isize;
    let r2 = (r_i * r_i) as i64;
    for dy in -r_i..=r_i {
        let y = cy + dy;
        if y < 0 || y >= height as isize {
            continue;
        }
        let dy2 = (dy * dy) as i64;
        let rem = r2.saturating_sub(dy2);
        let dx_lim = (rem as f64).sqrt().floor() as isize;
        let x0 = (cx - dx_lim).max(0) as usize;
        let x1 = (cx + dx_lim).min(width as isize - 1) as usize;
        let row = (y as usize) * width;
        for x in x0..=x1 {
            mask[row + x] = value;
        }
    }
}

fn stamp_polygon_fill_mask_u8(mask: &mut [u8], width: usize, height: usize, poly: &Polygon, value: u8) {
    if poly.vertices.len() < 3 || width == 0 || height == 0 {
        return;
    }
    let w = width as isize;
    for y in 0..height {
        let scan_y = (y as f64) + 0.5;
        let mut xs: Vec<f64> = Vec::new();
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
        let row = y * width;
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
                mask[row + (x as usize)] = value;
            }
        }
    }
}

fn stamp_path_mask_u8(
    mask: &mut [u8],
    width: usize,
    height: usize,
    points: &[Point],
    r_cells: usize,
    value: u8,
) {
    if points.len() < 2 {
        return;
    }
    for w in points.windows(2) {
        for p in bresenham_line(w[0], w[1]) {
            stamp_circle_mask_u8(mask, width, height, p, r_cells, value);
        }
    }
}

fn stamp_circle_occ_if_free(
    ir: &mut RoutingIr,
    layer: usize,
    center: Point,
    r_cells: usize,
    value: u32,
    blocked_value: u32,
) {
    if r_cells == 0 || ir.width == 0 || ir.height == 0 || layer >= ir.layers {
        return;
    }
    let r_i = r_cells as isize;
    let cx = center.x as isize;
    let cy = center.y as isize;
    let r2 = (r_i * r_i) as i64;
    for dy in -r_i..=r_i {
        let y = cy + dy;
        if y < 0 || y >= ir.height as isize {
            continue;
        }
        let dy2 = (dy * dy) as i64;
        let rem = r2.saturating_sub(dy2);
        let dx_lim = (rem as f64).sqrt().floor() as isize;
        let x0 = (cx - dx_lim).max(0) as usize;
        let x1 = (cx + dx_lim).min(ir.width as isize - 1) as usize;
        for x in x0..=x1 {
            let idx = ir.idx(layer, x, y as usize);
            let cur = ir.occ[idx];
            if cur == blocked_value {
                continue;
            }
            if cur == 0 || cur == value {
                ir.occ[idx] = value;
            }
        }
    }
}

fn stamp_polygon_fill_occ_if_free(
    ir: &mut RoutingIr,
    layer: usize,
    poly: &Polygon,
    value: u32,
    blocked_value: u32,
) {
    if poly.vertices.len() < 3 || ir.width == 0 || ir.height == 0 || layer >= ir.layers {
        return;
    }
    let w = ir.width as isize;
    let min_y = poly.vertices.iter().map(|p| p.y).min().unwrap_or(0);
    let max_y = poly
        .vertices
        .iter()
        .map(|p| p.y)
        .max()
        .unwrap_or(0)
        .min(ir.height.saturating_sub(1));
    let y0 = min_y.saturating_sub(1);
    let y1 = (max_y + 1).min(ir.height.saturating_sub(1));

    let mut xs: Vec<f64> = Vec::with_capacity(poly.vertices.len());
    for y in y0..=y1 {
        let scan_y = (y as f64) + 0.5;
        xs.clear();
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
                let idx = ir.idx(layer, x as usize, y);
                let cur = ir.occ[idx];
                if cur == blocked_value {
                    continue;
                }
                if cur == 0 || cur == value {
                    ir.occ[idx] = value;
                }
            }
        }
    }
}

fn stamp_path_occ_if_free(
    ir: &mut RoutingIr,
    layer: usize,
    points: &[Point],
    r_cells: usize,
    value: u32,
    blocked_value: u32,
) {
    if points.len() < 2 || r_cells == 0 {
        return;
    }
    for w in points.windows(2) {
        for p in bresenham_line(w[0], w[1]) {
            stamp_circle_occ_if_free(ir, layer, p, r_cells, value, blocked_value);
        }
    }
}

fn stamp_circle_pad_owner_if_free(ir: &mut RoutingIr, layer: usize, center: Point, r_cells: usize, net_id: u32) {
    if r_cells == 0 || layer >= ir.layers {
        return;
    }
    let cx = center.x as isize;
    let cy = center.y as isize;
    let r = r_cells as isize;
    let w = ir.width as isize;
    let h = ir.height as isize;
    for dy in -r..=r {
        for dx in -r..=r {
            if dx * dx + dy * dy > r * r {
                continue;
            }
            let x = cx + dx;
            let y = cy + dy;
            if x < 0 || y < 0 || x >= w || y >= h {
                continue;
            }
            let idx = ir.idx(layer, x as usize, y as usize);
            let cur = ir.pad_owner.get(idx).copied().unwrap_or(0);
            if cur == 0 || cur == net_id {
                ir.pad_owner[idx] = net_id;
            }
        }
    }
}

fn stamp_polygon_fill_pad_owner_if_free(ir: &mut RoutingIr, layer: usize, poly: &Polygon, net_id: u32) {
    if poly.vertices.len() < 3 || ir.width == 0 || ir.height == 0 || layer >= ir.layers {
        return;
    }

    let w = ir.width as isize;
    let min_y = poly.vertices.iter().map(|p| p.y).min().unwrap_or(0);
    let max_y = poly
        .vertices
        .iter()
        .map(|p| p.y)
        .max()
        .unwrap_or(0)
        .min(ir.height.saturating_sub(1));
    let y0 = min_y.saturating_sub(1);
    let y1 = (max_y + 1).min(ir.height.saturating_sub(1));

    let mut xs: Vec<f64> = Vec::with_capacity(poly.vertices.len());
    for y in y0..=y1 {
        let scan_y = (y as f64) + 0.5;
        xs.clear();
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
                let idx = ir.idx(layer, x as usize, y);
                let cur = ir.pad_owner.get(idx).copied().unwrap_or(0);
                if cur == 0 || cur == net_id {
                    ir.pad_owner[idx] = net_id;
                }
            }
        }
    }
}

fn stamp_path_pad_owner_if_free(ir: &mut RoutingIr, layer: usize, points: &[Point], r_cells: usize, net_id: u32) {
    if points.len() < 2 || r_cells == 0 || layer >= ir.layers {
        return;
    }
    for w in points.windows(2) {
        for p in bresenham_line(w[0], w[1]) {
            stamp_circle_pad_owner_if_free(ir, layer, p, r_cells, net_id);
        }
    }
}

/// Stamp pin copper shapes into `pad_owner` as owned by the corresponding net.
///
/// This is a routing-friendly alternative to stamping pins as hard keepouts: it preserves pad copper
/// and allows a net to legally route "into" its own pads, while the routing kernels can treat
/// other nets' pads as blocked even if we later allow negotiation/ripup through traces.
///
pub fn stamp_pins_as_occ_by_net(
    ir: &mut RoutingIr,
    tx: GridTransform,
    model: &DsnModel,
    _blocked_value: u32,
    inflate_world: f64,
    net_name_to_id: &HashMap<String, u32>,
) {
    if ir.width == 0 || ir.height == 0 || ir.layers == 0 {
        return;
    }
    if ir.pad_owner.len() != ir.occ.len() {
        ir.pad_owner = vec![0; ir.occ.len()];
    }

    let mut pin_to_net: HashMap<&str, u32> = HashMap::new();
    for (net_name, net) in &model.nets {
        let Some(&net_id) = net_name_to_id.get(net_name) else {
            continue;
        };
        for p in &net.pins {
            pin_to_net.insert(p.as_str(), net_id);
        }
    }

    for (pin_ref, pin) in &model.pins {
        let Some(&net_id) = pin_to_net.get(pin_ref.as_str()) else {
            continue;
        };

        if pin.shapes.is_empty() {
            let r = model.padstacks.get(&pin.padstack).copied().unwrap_or(0.0).max(0.0)
                + inflate_world.max(0.0);
            let center = match tx.world_to_grid(pin.x, pin.y) {
                Some(p) => p,
                None => continue,
            };
            let r_cells = if tx.pitch > 0.0 {
                let ratio = (r / tx.pitch).max(0.0);
                if ratio < 0.5 { 0 } else { ratio.ceil() as usize }
            } else { 0 };
            if r_cells == 0 { continue; }
            let layers: Vec<usize> = match model.padstack_layers.get(&pin.padstack) {
                Some(ls) if !ls.is_empty() => ls.clone(),
                _ => (0..ir.layers).collect(),
            };
            for &l in &layers {
                stamp_circle_pad_owner_if_free(ir, l, center, r_cells, net_id);
            }
            continue;
        }

        for shape in &pin.shapes {
            match shape {
                crate::dsn::PadShapeDef::Circle { layer, diameter, x, y } => {
                    let layers = layer_list_from_token(model, layer, ir.layers);
                    let center = match tx.world_to_grid(*x, *y) {
                        Some(p) => p,
                        None => continue,
                    };
                    let r = (*diameter * 0.5).max(0.0) + inflate_world.max(0.0);
                    let r_cells = if tx.pitch > 0.0 {
                        let ratio = (r / tx.pitch).max(0.0);
                        if ratio < 0.5 { 0 } else { ratio.ceil() as usize }
                    } else { 0 };
                    if r_cells == 0 {
                        continue;
                    }
                    for &l in &layers {
                        stamp_circle_pad_owner_if_free(ir, l, center, r_cells, net_id);
                    }
                }
                crate::dsn::PadShapeDef::Polygon { layer, points } => {
                    let layers = layer_list_from_token(model, layer, ir.layers);
                    let mut verts: Vec<Point> = Vec::new();
                    for &(x, y) in points {
                        if let Some(p) = tx.world_to_grid(x, y) {
                            if p.x < ir.width && p.y < ir.height {
                                verts.push(p);
                            }
                        }
                    }
                    if verts.len() < 3 {
                        continue;
                    }
                    let poly = Polygon::new(verts);
                    for &l in &layers {
                        stamp_polygon_fill_pad_owner_if_free(ir, l, &poly, net_id);
                    }
                }
                crate::dsn::PadShapeDef::Path { layer, width, points } => {
                    let layers = layer_list_from_token(model, layer, ir.layers);
                    let mut verts: Vec<Point> = Vec::new();
                    for &(x, y) in points {
                        if let Some(p) = tx.world_to_grid(x, y) {
                            if p.x < ir.width && p.y < ir.height {
                                verts.push(p);
                            }
                        }
                    }
                    if verts.len() < 2 {
                        continue;
                    }
                    let r = (*width * 0.5).max(0.0) + inflate_world.max(0.0);
                    let r_cells = if tx.pitch > 0.0 {
                        let ratio = (r / tx.pitch).max(0.0);
                        if ratio < 0.5 { 0 } else { ratio.ceil() as usize }
                    } else { 0 };
                    if r_cells == 0 {
                        continue;
                    }
                    for &l in &layers {
                        stamp_path_pad_owner_if_free(ir, l, &verts, r_cells, net_id);
                    }
                }
            }
        }

        // Conservative fallback inflation for polygonal pad shapes: add a radius-based halo using the padstack
        // bounding radius when available.
        if inflate_world > 0.0 {
            let r = model.padstacks.get(&pin.padstack).copied().unwrap_or(0.0).max(0.0) + inflate_world.max(0.0);
            let center = match tx.world_to_grid(pin.x, pin.y) {
                Some(p) => p,
                None => continue,
            };
            let r_cells = if tx.pitch > 0.0 {
                let ratio = (r / tx.pitch).max(0.0);
                if ratio < 0.5 { 0 } else { ratio.ceil() as usize }
            } else { 0 };
            if r_cells == 0 {
                continue;
            }
            let layers: Vec<usize> = match model.padstack_layers.get(&pin.padstack) {
                Some(ls) if !ls.is_empty() => ls.clone(),
                _ => (0..ir.layers).collect(),
            };
            for &l in &layers {
                stamp_circle_pad_owner_if_free(ir, l, center, r_cells, net_id);
            }
        }
    }
}

/// Stamp Specctra/Freerouting keepouts into the routing IR.
///
/// - `keepout` / `wire_keepout` blocks trace routing via `occ`.
/// - `keepout` / `via_keepout` forbids via transitions via `via_forbidden` (without blocking traces).
pub fn stamp_keepouts_as_occ_and_via_forbidden(
    ir: &mut RoutingIr,
    tx: GridTransform,
    model: &DsnModel,
    blocked_value: u32,
) {
    if ir.width == 0 || ir.height == 0 || ir.layers == 0 {
        return;
    }

    for k in &model.keepouts {
        let (kind, layer, circle, polygon, path) = match k {
            KeepoutShapeDef::Circle {
                kind,
                layer,
                diameter,
                x,
                y,
            } => {
                let r = (*diameter * 0.5).max(0.0);
                let center = match tx.world_to_grid(*x, *y) {
                    Some(p) => p,
                    None => continue,
                };
                let r_cells = (r / tx.pitch).ceil() as usize;
                (*kind, layer.as_str(), Some((center, r_cells)), None, None)
            }
            KeepoutShapeDef::Polygon { kind, layer, points } => {
                let mut verts: Vec<Point> = Vec::new();
                for &(x, y) in points {
                    if let Some(p) = tx.world_to_grid(x, y) {
                        if p.x < ir.width && p.y < ir.height {
                            verts.push(p);
                        }
                    }
                }
                if verts.len() < 3 {
                    continue;
                }
                (*kind, layer.as_str(), None, Some(Polygon::new(verts)), None)
            }
            KeepoutShapeDef::Path {
                kind,
                layer,
                width,
                points,
            } => {
                let mut verts: Vec<Point> = Vec::new();
                for &(x, y) in points {
                    if let Some(p) = tx.world_to_grid(x, y) {
                        if p.x < ir.width && p.y < ir.height {
                            verts.push(p);
                        }
                    }
                }
                if verts.len() < 2 {
                    continue;
                }
                let r = (*width * 0.5).max(0.0);
                let r_cells = (r / tx.pitch).ceil() as usize;
                (*kind, layer.as_str(), None, None, Some((verts, r_cells)))
            }
        };

        let layers = layer_list_from_token(model, layer, ir.layers);

        // Trace keepout: stamp into `occ`.
        if matches!(kind, KeepoutKind::All | KeepoutKind::Wire) {
            for &l in &layers {
                if l >= ir.layers {
                    continue;
                }
                if let Some((center, r_cells)) = circle {
                    if r_cells > 0 {
                        stamp_circle_occ_if_free(ir, l, center, r_cells, blocked_value, blocked_value);
                    }
                }
                if let Some(poly) = polygon.as_ref() {
                    stamp_polygon_fill_occ_if_free(ir, l, poly, blocked_value, blocked_value);
                }
                if let Some((pts, r_cells)) = path.as_ref() {
                    if *r_cells == 0 {
                        continue;
                    }
                    stamp_path_occ_if_free(ir, l, pts, *r_cells, blocked_value, blocked_value);
                }
            }
        }

        // Via keepout: stamp into `via_forbidden`.
        if matches!(kind, KeepoutKind::All | KeepoutKind::Via) && ir.via_forbidden.len() == ir.occ.len() {
            for &l in &layers {
                if l >= ir.layers {
                    continue;
                }
                let base = l * ir.width * ir.height;
                let mask = &mut ir.via_forbidden[base..base + (ir.width * ir.height)];
                if let Some((center, r_cells)) = circle {
                    stamp_circle_mask_u8(mask, ir.width, ir.height, center, r_cells, 1);
                }
                if let Some(poly) = polygon.as_ref() {
                    stamp_polygon_fill_mask_u8(mask, ir.width, ir.height, poly, 1);
                }
                if let Some((pts, r_cells)) = path.as_ref() {
                    stamp_path_mask_u8(mask, ir.width, ir.height, pts, *r_cells, 1);
                }
            }
        }
    }
}

fn bresenham_line(a: Point, b: Point) -> Vec<Point> {
    let (mut x0, mut y0) = (a.x as isize, a.y as isize);
    let (x1, y1) = (b.x as isize, b.y as isize);
    let dx = (x1 - x0).abs();
    let sx = if x0 < x1 { 1 } else { -1 };
    let dy = -(y1 - y0).abs();
    let sy = if y0 < y1 { 1 } else { -1 };
    let mut err = dx + dy;

    let mut out: Vec<Point> = Vec::new();
    loop {
        if x0 >= 0 && y0 >= 0 {
            out.push(Point {
                x: x0 as usize,
                y: y0 as usize,
            });
        }
        if x0 == x1 && y0 == y1 {
            break;
        }
        let e2 = 2 * err;
        if e2 >= dy {
            err += dy;
            x0 += sx;
        }
        if e2 <= dx {
            err += dx;
            y0 += sy;
        }
    }
    out
}

pub fn build_net_name_to_id_sorted(model: &DsnModel) -> HashMap<String, u32> {
    let mut names: Vec<String> = model.nets.keys().cloned().collect();
    for p in &model.planes {
        if !names.iter().any(|n| n == &p.net) {
            names.push(p.net.clone());
        }
    }
    names.sort();
    names.dedup();
    let mut out: HashMap<String, u32> = HashMap::new();
    for (i, name) in names.into_iter().enumerate() {
        // `RoutingIr` uses:
        // - 0 = free space
        // - 1 = hard-blocked (board edge/keepout/etc)
        // - >=2 = net ids
        out.insert(name, (i as u32) + 2);
    }
    out
}

/// Stamp DSN wiring (wires + vias) into the IR occupancy buffer.
///
/// - Wires are rasterized by mapping each DSN point to a grid point and then drawing a
///   Bresenham line between consecutive grid points.
/// - Vias are stamped on the layers implied by the via padstack's copper layers. If unknown,
///   the via is stamped on all layers (conservative fallback).
///
/// Occupancy rules:
/// - Cells with `blocked_value` are not modified.
/// - Other cells are set to `net_id` for the corresponding net name.
pub fn stamp_wiring_as_occ_by_padstack_layers(
    ir: &mut RoutingIr,
    tx: GridTransform,
    model: &DsnModel,
    wiring: &DsnWiring,
    blocked_value: u32,
    inflate_world: f64,
    net_name_to_id: &HashMap<String, u32>,
) {
    fn stamp_cell(ir: &mut RoutingIr, layer: usize, p: Point, net_id: u32, blocked_value: u32) {
        if layer >= ir.layers || p.x >= ir.width || p.y >= ir.height {
            return;
        }
        let cur = ir.get_occ(layer, p.x, p.y);
        if cur == blocked_value {
            return;
        }
        ir.set_occ(layer, p.x, p.y, net_id);
    }

    for wire in &wiring.wires {
        let net_id = match net_name_to_id.get(&wire.net) {
            Some(id) => *id,
            None => continue,
        };
        let layer_idx: usize = if let Ok(n) = wire.layer.parse::<i64>() {
            if n >= 1 {
                (n - 1) as usize
            } else {
                continue;
            }
        } else {
            match model.layer_name_to_index.get(&wire.layer) {
                Some(&idx) => idx,
                None => continue,
            }
        };
        if layer_idx >= ir.layers {
            continue;
        }

        let mut grid_pts: Vec<Point> = Vec::new();
        for &(x, y) in &wire.points {
            if let Some(p) = tx.world_to_grid(x, y) {
                if p.x < ir.width && p.y < ir.height {
                    if grid_pts.last().copied() != Some(p) {
                        grid_pts.push(p);
                    }
                }
            }
        }
        if grid_pts.len() < 2 {
            continue;
        }
        let r_world = (wire.width * 0.5).max(0.0) + inflate_world.max(0.0);
        let r_cells = if tx.pitch > 0.0 {
            let ratio = (r_world / tx.pitch).max(0.0);
            if ratio < 0.5 {
                0
            } else {
                ratio.ceil() as usize
            }
        } else {
            0
        };
        for seg in grid_pts.windows(2) {
            for p in bresenham_line(seg[0], seg[1]) {
                if r_cells == 0 {
                    stamp_cell(ir, layer_idx, p, net_id, blocked_value);
                } else {
                    stamp_circle_occ_if_free(ir, layer_idx, p, r_cells, net_id, blocked_value);
                }
            }
        }
    }

    for via in &wiring.vias {
        let net_id = match net_name_to_id.get(&via.net) {
            Some(id) => *id,
            None => continue,
        };
        let p = match tx.world_to_grid(via.x, via.y) {
            Some(p) => p,
            None => continue,
        };
        let r_world = model
            .padstacks
            .get(&via.padstack)
            .copied()
            .unwrap_or(0.0)
            .max(0.0)
            + inflate_world.max(0.0);
        let r_cells = if tx.pitch > 0.0 {
            let ratio = (r_world / tx.pitch).max(0.0);
            if ratio < 0.5 {
                0
            } else {
                ratio.ceil() as usize
            }
        } else {
            0
        };

        let layers: Vec<usize> = match model.padstack_layers.get(&via.padstack) {
            Some(ls) if !ls.is_empty() => ls.clone(),
            _ => (0..ir.layers).collect(),
        };
        for &layer in &layers {
            if r_cells == 0 {
                stamp_cell(ir, layer, p, net_id, blocked_value);
            } else {
                stamp_circle_occ_if_free(ir, layer, p, r_cells, net_id, blocked_value);
            }
        }
    }
}
