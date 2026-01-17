use std::collections::HashMap;

use crate::drc_nm::{TerminalShapeNm, TrackNm, ViaNm};
use crate::dsn::{DsnModel, DsnSummary, PadShapeDef};
use crate::dsn_to_ir::GridTransform;
use crate::dsn_to_nm::{dsn_coord_to_nm, summary_unit_scale_nm};
use crate::geom_nm::{CircleNm, Nm, PointNm, SegmentNm};
use crate::router::{Point, Point3};

fn map_layer_to_index(model: &DsnModel, layer: &str) -> Option<usize> {
    if let Ok(n) = layer.parse::<i64>() {
        if n >= 1 {
            return Some((n - 1) as usize);
        }
        return None;
    }
    model.layer_name_to_index.get(layer).copied()
}

fn layers_from_token(model: &DsnModel, layer: &str, layer_count: usize) -> Vec<usize> {
    if layer.eq_ignore_ascii_case("signal") || layer.is_empty() {
        return (0..layer_count).collect();
    }
    if let Some(idx) = map_layer_to_index(model, layer) {
        if idx < layer_count {
            return vec![idx];
        }
    }
    (0..layer_count).collect()
}

fn pick_via_padstack(model: &DsnModel, lo: usize, hi: usize) -> Option<String> {
    let mut names: Vec<&String> = model.padstacks.keys().collect();
    names.sort();
    for name in names {
        let Some(layers) = model.padstack_layers.get(name) else {
            continue;
        };
        if layers.contains(&lo) && layers.contains(&hi) {
            return Some(name.clone());
        }
    }
    // Fallback: first padstack by name.
    model.padstacks.keys().min().cloned()
}

fn padstack_shapes_to_terminal_shapes_nm(
    summary: &DsnSummary,
    model: &DsnModel,
    padstack: &str,
    center: PointNm,
    layers: (usize, usize),
) -> Result<(CircleNm, Vec<TerminalShapeNm>), String> {
    let unit_scale = summary_unit_scale_nm(summary).ok_or_else(|| "unknown DSN unit".to_string())?;

    let x_nm = center.x.0;
    let y_nm = center.y.0;

    let mut shapes: Vec<TerminalShapeNm> = Vec::new();

    if let Some(defs) = model.padstack_shapes.get(padstack) {
        for shape in defs {
            match shape {
                PadShapeDef::Circle {
                    layer,
                    diameter,
                    x,
                    y,
                } => {
                    let r_nm = dsn_coord_to_nm(*diameter / 2.0, unit_scale)
                        .map_err(|e| e.message)?;
                    let px = dsn_coord_to_nm(*x, unit_scale).map_err(|e| e.message)?;
                    let py = dsn_coord_to_nm(*y, unit_scale).map_err(|e| e.message)?;
                    let circle = CircleNm {
                        center: PointNm {
                            x: Nm(x_nm + px),
                            y: Nm(y_nm + py),
                        },
                        r: Nm(r_nm.max(0)),
                    };
                    for layer_idx in layers_from_token(model, layer, model.layer_name_to_index.len().max(1)) {
                        if layer_idx >= layers.0 && layer_idx <= layers.1 {
                            shapes.push(TerminalShapeNm::Circle { layer: layer_idx, circle });
                        }
                    }
                }
                PadShapeDef::Polygon { layer, points } => {
                    if points.len() < 3 {
                        continue;
                    }
                    let mut pts_nm: Vec<PointNm> = Vec::new();
                    for (x, y) in points {
                        let px = dsn_coord_to_nm(*x, unit_scale).map_err(|e| e.message)?;
                        let py = dsn_coord_to_nm(*y, unit_scale).map_err(|e| e.message)?;
                        let p = PointNm {
                            x: Nm(x_nm + px),
                            y: Nm(y_nm + py),
                        };
                        if pts_nm.last().copied() != Some(p) {
                            pts_nm.push(p);
                        }
                    }
                    if pts_nm.len() < 3 {
                        continue;
                    }
                    for layer_idx in layers_from_token(model, layer, model.layer_name_to_index.len().max(1)) {
                        if layer_idx >= layers.0 && layer_idx <= layers.1 {
                            shapes.push(TerminalShapeNm::Polygon {
                                layer: layer_idx,
                                points: pts_nm.clone(),
                            });
                        }
                    }
                }
                PadShapeDef::Path { layer, width, points } => {
                    if points.len() < 2 {
                        continue;
                    }
                    let mut pts_nm: Vec<PointNm> = Vec::new();
                    for (x, y) in points {
                        let px = dsn_coord_to_nm(*x, unit_scale).map_err(|e| e.message)?;
                        let py = dsn_coord_to_nm(*y, unit_scale).map_err(|e| e.message)?;
                        let p = PointNm {
                            x: Nm(x_nm + px),
                            y: Nm(y_nm + py),
                        };
                        if pts_nm.last().copied() != Some(p) {
                            pts_nm.push(p);
                        }
                    }
                    if pts_nm.len() < 2 {
                        continue;
                    }
                    let r_nm =
                        dsn_coord_to_nm(*width / 2.0, unit_scale).map_err(|e| e.message)?;
                    let r = Nm(r_nm.max(0));
                    for layer_idx in layers_from_token(model, layer, model.layer_name_to_index.len().max(1)) {
                        if layer_idx >= layers.0 && layer_idx <= layers.1 {
                            shapes.push(TerminalShapeNm::Path {
                                layer: layer_idx,
                                r,
                                points: pts_nm.clone(),
                            });
                        }
                    }
                }
            }
        }
    }

    // Fallback: approximate as a circle with DSN padstack radius.
    if shapes.is_empty() {
        let r_world = model.padstacks.get(padstack).copied().unwrap_or(0.0);
        let r_nm = dsn_coord_to_nm(r_world, unit_scale).map_err(|e| e.message)?;
        let circle = CircleNm {
            center,
            r: Nm(r_nm.max(0)),
        };
        for layer in layers.0..=layers.1 {
            shapes.push(TerminalShapeNm::Circle { layer, circle });
        }
    }

    // Bounding circle radius for coarse collision checks.
    let mut bound_r: i64 = 0;
    for s in &shapes {
        match s {
            TerminalShapeNm::Circle { circle, .. } => {
                let dx = (circle.center.x.0 - center.x.0) as f64;
                let dy = (circle.center.y.0 - center.y.0) as f64;
                let dist = (dx * dx + dy * dy).sqrt();
                let r = (dist + (circle.r.0 as f64)).ceil() as i64;
                bound_r = bound_r.max(r);
            }
            TerminalShapeNm::Polygon { points, .. } => {
                for p in points {
                    let dx = (p.x.0 - center.x.0) as f64;
                    let dy = (p.y.0 - center.y.0) as f64;
                    let dist = (dx * dx + dy * dy).sqrt().ceil() as i64;
                    bound_r = bound_r.max(dist);
                }
            }
            TerminalShapeNm::Path { r, points, .. } => {
                for p in points {
                    let dx = (p.x.0 - center.x.0) as f64;
                    let dy = (p.y.0 - center.y.0) as f64;
                    let dist = (dx * dx + dy * dy).sqrt();
                    let rr = (dist + (r.0 as f64)).ceil() as i64;
                    bound_r = bound_r.max(rr);
                }
            }
        }
    }

    Ok((
        CircleNm {
            center,
            r: Nm(bound_r.max(0)),
        },
        shapes,
    ))
}

/// Convert a routed grid path into nm-domain tracks/vias that can be serialized to SES.
pub fn grid_path_to_nm_tracks_and_vias(
    summary: &DsnSummary,
    model: &DsnModel,
    tx: GridTransform,
    path: &[Point3],
    net_id: u32,
    clearance_class: u32,
    width_world: f64,
    via_padstack_override: Option<&str>,
) -> Result<(Vec<TrackNm>, Vec<ViaNm>), String> {
    let unit_scale = summary_unit_scale_nm(summary).ok_or_else(|| "unknown DSN unit".to_string())?;

    let to_nm = |v: f64| -> Result<i64, String> { dsn_coord_to_nm(v, unit_scale).map_err(|e| e.message) };
    let r_nm = to_nm(width_world / 2.0)?.max(0);
    let r = Nm(r_nm);

    let mut tracks: Vec<TrackNm> = Vec::new();
    let mut vias: Vec<ViaNm> = Vec::new();
    let mut via_seen: HashMap<(usize, usize, usize, usize), ()> = HashMap::new();

    for w in path.windows(2) {
        let a = w[0];
        let b = w[1];
        if a.layer == b.layer {
            if a.x == b.x && a.y == b.y {
                continue;
            }
            let (axw, ayw) = tx.grid_to_world(Point { x: a.x, y: a.y });
            let (bxw, byw) = tx.grid_to_world(Point { x: b.x, y: b.y });
            let seg = SegmentNm {
                a: PointNm {
                    x: Nm(to_nm(axw)?),
                    y: Nm(to_nm(ayw)?),
                },
                b: PointNm {
                    x: Nm(to_nm(bxw)?),
                    y: Nm(to_nm(byw)?),
                },
            };
            tracks.push(TrackNm {
                net_id,
                clearance_class,
                layer: a.layer,
                seg,
                r,
            });
        } else {
            // Via transition: expected to be vertical at a fixed x/y.
            let x = if a.x == b.x { a.x } else { b.x };
            let y = if a.y == b.y { a.y } else { b.y };
            let lo = a.layer.min(b.layer);
            let hi = a.layer.max(b.layer);

            if via_seen.insert((x, y, lo, hi), ()).is_some() {
                continue;
            }

            let (xw, yw) = tx.grid_to_world(Point { x, y });
            let center = PointNm {
                x: Nm(to_nm(xw)?),
                y: Nm(to_nm(yw)?),
            };

            let padstack = via_padstack_override
                .map(|s| s.to_string())
                .or_else(|| pick_via_padstack(model, lo, hi))
                .unwrap_or_else(|| "via0".to_string());

            let (circle, shapes) = padstack_shapes_to_terminal_shapes_nm(
                summary,
                model,
                &padstack,
                center,
                (lo, hi),
            )?;

            vias.push(ViaNm {
                net_id,
                clearance_class,
                layers: (lo, hi),
                padstack: Some(padstack),
                circle,
                shapes,
            });
        }
    }

    Ok((tracks, vias))
}

