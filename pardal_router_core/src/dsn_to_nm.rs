use std::collections::HashMap;

use crate::board_nm::BoardNm;
use crate::drc_nm::{
    AreaNm, KeepoutAppliesTo, KeepoutNm, KeepoutShapeNm, TerminalNm, TerminalShapeNm, TrackNm, ViaNm,
};
use crate::dsn::{
    DsnModel, DsnNetRules, DsnSummary, DsnWiring, KeepoutKind, KeepoutShapeDef, PadShapeDef, PlaneShapeDef,
};
use crate::geom_nm::{CircleNm, Nm, PointNm, SegmentNm};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DsnToNmError {
    pub message: String,
}

impl std::fmt::Display for DsnToNmError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for DsnToNmError {}

#[derive(Debug, Clone)]
struct ClearanceClassIds {
    name_to_id: HashMap<String, u32>,
    id_to_name: Vec<String>,
}

impl ClearanceClassIds {
    fn new() -> Self {
        let mut name_to_id: HashMap<String, u32> = HashMap::new();
        name_to_id.insert("default".to_string(), 0);
        Self {
            name_to_id,
            id_to_name: vec!["default".to_string()],
        }
    }

    fn id_for(&mut self, name: &str) -> u32 {
        if let Some(&id) = self.name_to_id.get(name) {
            return id;
        }
        let id = self.id_to_name.len() as u32;
        self.name_to_id.insert(name.to_string(), id);
        self.id_to_name.push(name.to_string());
        id
    }
}

fn net_clearance_class_name<'a>(rules: Option<&'a DsnNetRules>, net_name: &str) -> Option<&'a str> {
    let rules = rules?;
    let cls = rules.net_to_class.get(net_name)?;
    rules.classes.get(cls)?.clearance_class.as_deref()
}

pub fn unit_nm_scale(unit: &str) -> Option<i64> {
    // DSN "resolution" unit strings are typically: `mil`, `inch`, `mm`, `um`.
    // Interpretation used here:
    // - coordinate values are expressed in that unit (often with decimals),
    // - the "resolution" integer indicates the host's integer grid for session export.
    match unit.to_ascii_lowercase().as_str() {
        "mm" => Some(1_000_000),
        "um" => Some(1_000),
        "mil" => Some(25_400),
        "inch" => Some(25_400_000),
        _ => None,
    }
}

pub fn dsn_coord_to_nm(v: f64, unit_scale_nm: i64) -> Result<i64, DsnToNmError> {
    if !v.is_finite() {
        return Err(DsnToNmError {
            message: "non-finite DSN coordinate".to_string(),
        });
    }
    let nm = v * (unit_scale_nm as f64);
    if !nm.is_finite() {
        return Err(DsnToNmError {
            message: "DSN coordinate overflow".to_string(),
        });
    }
    Ok(nm.round() as i64)
}

pub fn summary_unit_scale_nm(summary: &DsnSummary) -> Option<i64> {
    // Prefer the resolution unit (the one DSN writers typically use for all coordinates).
    if let Some(u) = summary.resolution_unit.as_deref().and_then(unit_nm_scale) {
        return Some(u);
    }
    summary.unit.as_deref().and_then(unit_nm_scale)
}

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

pub fn wiring_to_nm_tracks_and_vias(
    summary: &DsnSummary,
    model: &DsnModel,
    wiring: &DsnWiring,
    net_name_to_id: &HashMap<String, u32>,
) -> Result<(Vec<TrackNm>, Vec<ViaNm>), DsnToNmError> {
    wiring_to_nm_tracks_and_vias_with_clearance(summary, model, wiring, net_name_to_id, None, None)
}

fn wiring_to_nm_tracks_and_vias_with_clearance(
    summary: &DsnSummary,
    model: &DsnModel,
    wiring: &DsnWiring,
    net_name_to_id: &HashMap<String, u32>,
    net_rules: Option<&DsnNetRules>,
    mut clearance_ids: Option<&mut ClearanceClassIds>,
) -> Result<(Vec<TrackNm>, Vec<ViaNm>), DsnToNmError> {
    let unit_scale = summary_unit_scale_nm(summary).ok_or_else(|| DsnToNmError {
        message: "missing or unknown DSN unit; cannot convert to nm".to_string(),
    })?;
    let layer_count = summary.layer_count.max(1);

    let mut tracks: Vec<TrackNm> = Vec::new();
    for w in &wiring.wires {
        let Some(&net_id) = net_name_to_id.get(&w.net) else {
            continue;
        };
        let class_name = w
            .clearance_class
            .as_deref()
            .or_else(|| net_clearance_class_name(net_rules, &w.net))
            .unwrap_or("default");
        let clearance_class = clearance_ids
            .as_deref_mut()
            .map(|ids| ids.id_for(class_name))
            .unwrap_or(0);
        let Some(layer) = map_layer_to_index(model, &w.layer) else {
            continue;
        };
        if layer >= layer_count {
            continue;
        }
        let r_nm = dsn_coord_to_nm(w.width / 2.0, unit_scale)?;
        let r = Nm(r_nm.max(0));

        let mut pts: Vec<PointNm> = Vec::new();
        for &(x, y) in &w.points {
            let px = dsn_coord_to_nm(x, unit_scale)?;
            let py = dsn_coord_to_nm(y, unit_scale)?;
            let p = PointNm { x: Nm(px), y: Nm(py) };
            if pts.last().copied() != Some(p) {
                pts.push(p);
            }
        }
        if pts.len() < 2 {
            continue;
        }
        for seg in pts.windows(2) {
            if seg[0] == seg[1] {
                continue;
            }
            tracks.push(TrackNm {
                net_id,
                clearance_class,
                layer,
                seg: SegmentNm { a: seg[0], b: seg[1] },
                r,
            });
        }
    }

    let mut vias: Vec<ViaNm> = Vec::new();
    for v in &wiring.vias {
        let Some(&net_id) = net_name_to_id.get(&v.net) else {
            continue;
        };
        let class_name = v
            .clearance_class
            .as_deref()
            .or_else(|| net_clearance_class_name(net_rules, &v.net))
            .unwrap_or("default");
        let clearance_class = clearance_ids
            .as_deref_mut()
            .map(|ids| ids.id_for(class_name))
            .unwrap_or(0);
        let r_world = model
            .padstacks
            .get(&v.padstack)
            .copied()
            .ok_or_else(|| DsnToNmError {
                message: format!("missing padstack radius for via padstack '{}'", v.padstack),
            })?;
        let r_nm = dsn_coord_to_nm(r_world, unit_scale)?;
        let x_nm = dsn_coord_to_nm(v.x, unit_scale)?;
        let y_nm = dsn_coord_to_nm(v.y, unit_scale)?;
        let center = PointNm { x: Nm(x_nm), y: Nm(y_nm) };

        let layers: Vec<usize> = match model.padstack_layers.get(&v.padstack) {
            Some(ls) if !ls.is_empty() => ls.clone(),
            _ => (0..layer_count).collect(),
        };
        let (min_layer, max_layer) = layers.iter().fold((usize::MAX, 0usize), |(mn, mx), &l| {
            (mn.min(l), mx.max(l))
        });
        let layers = if min_layer == usize::MAX {
            (0usize, layer_count.saturating_sub(1))
        } else {
            (min_layer, max_layer.min(layer_count.saturating_sub(1)))
        };

        let mut shapes: Vec<TerminalShapeNm> = Vec::new();
        if let Some(defs) = model.padstack_shapes.get(&v.padstack) {
            for s in defs {
                match s {
                    PadShapeDef::Circle { layer, diameter, x, y } => {
                        let dx = dsn_coord_to_nm(*x, unit_scale)?;
                        let dy = dsn_coord_to_nm(*y, unit_scale)?;
                        let r = dsn_coord_to_nm(*diameter / 2.0, unit_scale)?;
                        let c = CircleNm {
                            center: PointNm { x: Nm(x_nm + dx), y: Nm(y_nm + dy) },
                            r: Nm(r.max(0)),
                        };
                        for layer_idx in layers_from_token(model, layer, layer_count) {
                            if layer_idx >= layers.0 && layer_idx <= layers.1 {
                                shapes.push(TerminalShapeNm::Circle { layer: layer_idx, circle: c });
                            }
                        }
                    }
                    PadShapeDef::Polygon { layer, points } => {
                        let mut pts_nm: Vec<PointNm> = Vec::new();
                        for (x, y) in points {
                            let px = dsn_coord_to_nm(*x, unit_scale)?;
                            let py = dsn_coord_to_nm(*y, unit_scale)?;
                            let p = PointNm { x: Nm(x_nm + px), y: Nm(y_nm + py) };
                            if pts_nm.last().copied() != Some(p) {
                                pts_nm.push(p);
                            }
                        }
                        if pts_nm.len() < 3 {
                            continue;
                        }
                        for layer_idx in layers_from_token(model, layer, layer_count) {
                            if layer_idx >= layers.0 && layer_idx <= layers.1 {
                                shapes.push(TerminalShapeNm::Polygon { layer: layer_idx, points: pts_nm.clone() });
                            }
                        }
                    }
                    PadShapeDef::Path { layer, width, points } => {
                        let mut pts_nm: Vec<PointNm> = Vec::new();
                        for (x, y) in points {
                            let px = dsn_coord_to_nm(*x, unit_scale)?;
                            let py = dsn_coord_to_nm(*y, unit_scale)?;
                            let p = PointNm { x: Nm(x_nm + px), y: Nm(y_nm + py) };
                            if pts_nm.last().copied() != Some(p) {
                                pts_nm.push(p);
                            }
                        }
                        if pts_nm.len() < 2 {
                            continue;
                        }
                        let r_nm = dsn_coord_to_nm(*width / 2.0, unit_scale)?;
                        let r = Nm(r_nm.max(0));
                        for layer_idx in layers_from_token(model, layer, layer_count) {
                            if layer_idx >= layers.0 && layer_idx <= layers.1 {
                                shapes.push(TerminalShapeNm::Path { layer: layer_idx, r, points: pts_nm.clone() });
                            }
                        }
                    }
                }
            }
        }

        if shapes.is_empty() {
            let circle = CircleNm { center, r: Nm(r_nm.max(0)) };
            for layer in layers.0..=layers.1 {
                shapes.push(TerminalShapeNm::Circle { layer, circle });
            }
        }

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

        vias.push(ViaNm {
            net_id,
            clearance_class,
            layers,
            padstack: Some(v.padstack.clone()),
            circle: CircleNm {
                center,
                r: Nm(bound_r.max(0)),
            },
            shapes,
        });
    }

    Ok((tracks, vias))
}

pub fn build_net_name_to_id_sorted_from_dsn(model: &DsnModel) -> HashMap<String, u32> {
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
        out.insert(name, (i as u32) + 1);
    }
    out
}

pub fn planes_to_nm_areas(
    summary: &DsnSummary,
    model: &DsnModel,
    net_name_to_id: &HashMap<String, u32>,
) -> Result<Vec<AreaNm>, DsnToNmError> {
    planes_to_nm_areas_with_clearance(summary, model, net_name_to_id, None, None)
}

fn planes_to_nm_areas_with_clearance(
    summary: &DsnSummary,
    model: &DsnModel,
    net_name_to_id: &HashMap<String, u32>,
    net_rules: Option<&DsnNetRules>,
    mut clearance_ids: Option<&mut ClearanceClassIds>,
) -> Result<Vec<AreaNm>, DsnToNmError> {
    let unit_scale = summary_unit_scale_nm(summary).ok_or_else(|| DsnToNmError {
        message: "missing or unknown DSN unit; cannot convert planes to nm".to_string(),
    })?;
    let layer_count = summary.layer_count.max(1);

    let mut out: Vec<AreaNm> = Vec::new();
    for plane in &model.planes {
        let Some(&net_id) = net_name_to_id.get(&plane.net) else {
            continue;
        };
        let class_name = net_clearance_class_name(net_rules, &plane.net).unwrap_or("default");
        let clearance_class = clearance_ids
            .as_deref_mut()
            .map(|ids| ids.id_for(class_name))
            .unwrap_or(0);

        let mut holes_by_layer: HashMap<usize, Vec<Vec<PointNm>>> = HashMap::new();
        for w in &plane.windows {
            match w {
                PlaneShapeDef::Polygon { layer, points } => {
                    let Some(layer) = map_layer_to_index(model, layer) else {
                        continue;
                    };
                    if layer >= layer_count {
                        continue;
                    }
                    let mut pts: Vec<PointNm> = Vec::new();
                    for &(x, y) in points {
                        let x_nm = dsn_coord_to_nm(x, unit_scale)?;
                        let y_nm = dsn_coord_to_nm(y, unit_scale)?;
                        let p = PointNm { x: Nm(x_nm), y: Nm(y_nm) };
                        if pts.last().copied() != Some(p) {
                            pts.push(p);
                        }
                    }
                    if pts.len() >= 2 && pts.first().copied() == pts.last().copied() {
                        pts.pop();
                    }
                    if pts.len() < 3 {
                        continue;
                    }
                    holes_by_layer.entry(layer).or_default().push(pts);
                }
            }
        }

        for shape in &plane.shapes {
            match shape {
                PlaneShapeDef::Polygon { layer, points } => {
                    let Some(layer) = map_layer_to_index(model, layer) else {
                        continue;
                    };
                    if layer >= layer_count {
                        continue;
                    }
                    let mut pts: Vec<PointNm> = Vec::new();
                    for &(x, y) in points {
                        let x_nm = dsn_coord_to_nm(x, unit_scale)?;
                        let y_nm = dsn_coord_to_nm(y, unit_scale)?;
                        let p = PointNm { x: Nm(x_nm), y: Nm(y_nm) };
                        if pts.last().copied() != Some(p) {
                            pts.push(p);
                        }
                    }
                    if pts.len() >= 2 && pts.first().copied() == pts.last().copied() {
                        pts.pop();
                    }
                    if pts.len() < 3 {
                        continue;
                    }
                    out.push(AreaNm {
                        net_id,
                        clearance_class,
                        layer,
                        polygon: pts,
                        holes: holes_by_layer.get(&layer).cloned().unwrap_or_default(),
                    });
                }
            }
        }
    }
    Ok(out)
}

pub fn pins_to_nm_terminals(
    summary: &DsnSummary,
    model: &DsnModel,
    net_name_to_id: &HashMap<String, u32>,
) -> Result<Vec<TerminalNm>, DsnToNmError> {
    pins_to_nm_terminals_with_clearance(summary, model, net_name_to_id, None, None)
}

fn pins_to_nm_terminals_with_clearance(
    summary: &DsnSummary,
    model: &DsnModel,
    net_name_to_id: &HashMap<String, u32>,
    net_rules: Option<&DsnNetRules>,
    mut clearance_ids: Option<&mut ClearanceClassIds>,
) -> Result<Vec<TerminalNm>, DsnToNmError> {
    let unit_scale = summary_unit_scale_nm(summary).ok_or_else(|| DsnToNmError {
        message: "missing or unknown DSN unit; cannot convert pins to nm".to_string(),
    })?;
    let layer_count = summary.layer_count.max(1);

    let mut out: Vec<TerminalNm> = Vec::new();
    for (net_name, net) in &model.nets {
        let Some(&net_id) = net_name_to_id.get(net_name) else {
            continue;
        };
        for pin_ref in &net.pins {
            let Some(pin) = model.pins.get(pin_ref) else {
                continue;
            };
            let class_name = model
                .pin_clearance_classes
                .get(pin_ref)
                .map(|s| s.as_str())
                .or_else(|| net_clearance_class_name(net_rules, net_name))
                .unwrap_or("default");
            let clearance_class = clearance_ids
                .as_deref_mut()
                .map(|ids| ids.id_for(class_name))
                .unwrap_or(0);
            let x_nm = dsn_coord_to_nm(pin.x, unit_scale)?;
            let y_nm = dsn_coord_to_nm(pin.y, unit_scale)?;
            let center = PointNm { x: Nm(x_nm), y: Nm(y_nm) };

            let mut shapes: Vec<TerminalShapeNm> = Vec::new();
            for s in &pin.shapes {
                match s {
                    PadShapeDef::Circle { layer, diameter, x, y } => {
                        let cx = dsn_coord_to_nm(*x, unit_scale)?;
                        let cy = dsn_coord_to_nm(*y, unit_scale)?;
                        let r = dsn_coord_to_nm(*diameter / 2.0, unit_scale)?;
                        let c = CircleNm {
                            center: PointNm { x: Nm(cx), y: Nm(cy) },
                            r: Nm(r.max(0)),
                        };
                        for layer_idx in layers_from_token(model, layer, layer_count) {
                            if layer_idx < layer_count {
                                shapes.push(TerminalShapeNm::Circle { layer: layer_idx, circle: c });
                            }
                        }
                    }
                    PadShapeDef::Polygon { layer, points } => {
                        let mut pts_nm: Vec<PointNm> = Vec::new();
                        for (x, y) in points {
                            let px = dsn_coord_to_nm(*x, unit_scale)?;
                            let py = dsn_coord_to_nm(*y, unit_scale)?;
                            let p = PointNm { x: Nm(px), y: Nm(py) };
                            if pts_nm.last().copied() != Some(p) {
                                pts_nm.push(p);
                            }
                        }
                        if pts_nm.len() < 3 {
                            continue;
                        }
                        for layer_idx in layers_from_token(model, layer, layer_count) {
                            if layer_idx < layer_count {
                                shapes.push(TerminalShapeNm::Polygon {
                                    layer: layer_idx,
                                    points: pts_nm.clone(),
                                });
                            }
                        }
                    }
                    PadShapeDef::Path { layer, width, points } => {
                        let mut pts_nm: Vec<PointNm> = Vec::new();
                        for (x, y) in points {
                            let px = dsn_coord_to_nm(*x, unit_scale)?;
                            let py = dsn_coord_to_nm(*y, unit_scale)?;
                            let p = PointNm { x: Nm(px), y: Nm(py) };
                            if pts_nm.last().copied() != Some(p) {
                                pts_nm.push(p);
                            }
                        }
                        if pts_nm.len() < 2 {
                            continue;
                        }
                        let r_nm = dsn_coord_to_nm(*width / 2.0, unit_scale)?;
                        let r = Nm(r_nm.max(0));
                        for layer_idx in layers_from_token(model, layer, layer_count) {
                            if layer_idx < layer_count {
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

            if shapes.is_empty() {
                // Fallback to the legacy circle-only approximation.
                let Some(&r_world) = model.padstacks.get(&pin.padstack) else {
                    continue;
                };
                let r_nm = dsn_coord_to_nm(r_world, unit_scale)?;
                let mut layers: Vec<usize> = match model.padstack_layers.get(&pin.padstack) {
                    Some(ls) if !ls.is_empty() => ls.clone(),
                    _ => (0..layer_count).collect(),
                };
                layers.retain(|&l| l < layer_count);
                layers.sort_unstable();
                layers.dedup();
                if layers.is_empty() {
                    layers = (0..layer_count).collect();
                }
                let circle = CircleNm { center, r: Nm(r_nm.max(0)) };
                for &layer in &layers {
                    shapes.push(TerminalShapeNm::Circle { layer, circle });
                }
                out.push(TerminalNm {
                    net_id,
                    pin_ref: Some(pin_ref.clone()),
                    clearance_class,
                    layers,
                    circle,
                    shapes,
                });
                continue;
            }

            let mut layers: Vec<usize> = shapes
                .iter()
                .map(|s| match s {
                    TerminalShapeNm::Circle { layer, .. } => *layer,
                    TerminalShapeNm::Polygon { layer, .. } => *layer,
                    TerminalShapeNm::Path { layer, .. } => *layer,
                })
                .collect();
            layers.sort_unstable();
            layers.dedup();

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

            out.push(TerminalNm {
                net_id,
                pin_ref: Some(pin_ref.clone()),
                clearance_class,
                layers,
                circle: CircleNm { center, r: Nm(bound_r.max(0)) },
                shapes,
            });
        }
    }
    Ok(out)
}

pub fn keepouts_to_nm(
    summary: &DsnSummary,
    model: &DsnModel,
) -> Result<Vec<KeepoutNm>, DsnToNmError> {
    let unit_scale = summary_unit_scale_nm(summary).ok_or_else(|| DsnToNmError {
        message: "missing or unknown DSN unit; cannot convert keepouts to nm".to_string(),
    })?;
    let layer_count = summary.layer_count.max(1);

    let mut out: Vec<KeepoutNm> = Vec::new();
    for ko in &model.keepouts {
        match ko {
            KeepoutShapeDef::Circle {
                kind,
                layer,
                diameter,
                x,
                y,
            } => {
                let applies_to = match kind {
                    KeepoutKind::All => KeepoutAppliesTo::All,
                    KeepoutKind::Wire => KeepoutAppliesTo::Wire,
                    KeepoutKind::Via => KeepoutAppliesTo::Via,
                };
                let layers = layers_from_token(model, layer, layer_count);
                let r_nm = dsn_coord_to_nm(diameter / 2.0, unit_scale)?;
                let x_nm = dsn_coord_to_nm(*x, unit_scale)?;
                let y_nm = dsn_coord_to_nm(*y, unit_scale)?;
                out.push(KeepoutNm {
                    layers,
                    applies_to,
                    shape: KeepoutShapeNm::Circle {
                        circle: CircleNm {
                            center: PointNm { x: Nm(x_nm), y: Nm(y_nm) },
                            r: Nm(r_nm.max(0)),
                        },
                    },
                });
            }
            KeepoutShapeDef::Polygon { kind, layer, points } => {
                let applies_to = match kind {
                    KeepoutKind::All => KeepoutAppliesTo::All,
                    KeepoutKind::Wire => KeepoutAppliesTo::Wire,
                    KeepoutKind::Via => KeepoutAppliesTo::Via,
                };
                let layers = layers_from_token(model, layer, layer_count);
                let mut pts: Vec<PointNm> = Vec::new();
                for &(x, y) in points {
                    let x_nm = dsn_coord_to_nm(x, unit_scale)?;
                    let y_nm = dsn_coord_to_nm(y, unit_scale)?;
                    pts.push(PointNm { x: Nm(x_nm), y: Nm(y_nm) });
                }
                if pts.len() < 3 {
                    continue;
                }
                out.push(KeepoutNm {
                    layers,
                    applies_to,
                    shape: KeepoutShapeNm::Polygon { points: pts },
                });
            }
            KeepoutShapeDef::Path {
                kind,
                layer,
                width,
                points,
            } => {
                let applies_to = match kind {
                    KeepoutKind::All => KeepoutAppliesTo::All,
                    KeepoutKind::Wire => KeepoutAppliesTo::Wire,
                    KeepoutKind::Via => KeepoutAppliesTo::Via,
                };
                let layers = layers_from_token(model, layer, layer_count);
                let mut pts: Vec<PointNm> = Vec::new();
                for &(x, y) in points {
                    let x_nm = dsn_coord_to_nm(x, unit_scale)?;
                    let y_nm = dsn_coord_to_nm(y, unit_scale)?;
                    let p = PointNm { x: Nm(x_nm), y: Nm(y_nm) };
                    if pts.last().copied() != Some(p) {
                        pts.push(p);
                    }
                }
                if pts.len() < 2 {
                    continue;
                }
                let r_nm = dsn_coord_to_nm(width / 2.0, unit_scale)?;
                out.push(KeepoutNm {
                    layers,
                    applies_to,
                    shape: KeepoutShapeNm::Path {
                        r: Nm(r_nm.max(0)),
                        points: pts,
                    },
                });
            }
        }
    }
    Ok(out)
}

pub fn dsn_to_board_nm(
    summary: &DsnSummary,
    model: &DsnModel,
    wiring: &DsnWiring,
) -> Result<BoardNm, DsnToNmError> {
    dsn_to_board_nm_with_net_rules(summary, model, wiring, None)
}

pub fn dsn_to_board_nm_with_net_rules(
    summary: &DsnSummary,
    model: &DsnModel,
    wiring: &DsnWiring,
    net_rules: Option<&DsnNetRules>,
) -> Result<BoardNm, DsnToNmError> {
    let net_name_to_id = build_net_name_to_id_sorted_from_dsn(model);
    let mut clearance_ids = ClearanceClassIds::new();
    let (tracks, vias) = wiring_to_nm_tracks_and_vias_with_clearance(
        summary,
        model,
        wiring,
        &net_name_to_id,
        net_rules,
        Some(&mut clearance_ids),
    )?;
    let terminals = pins_to_nm_terminals_with_clearance(
        summary,
        model,
        &net_name_to_id,
        net_rules,
        Some(&mut clearance_ids),
    )?;
    let areas = planes_to_nm_areas_with_clearance(
        summary,
        model,
        &net_name_to_id,
        net_rules,
        Some(&mut clearance_ids),
    )?;
    let keepouts = keepouts_to_nm(summary, model)?;

    Ok(BoardNm {
        layers: summary.layer_count.max(1),
        net_name_to_id,
        boundary: None,
        clearance_class_id_to_name: clearance_ids.id_to_name,
        tracks,
        vias,
        terminals,
        areas,
        keepouts,
    })
}
