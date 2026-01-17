use std::path::PathBuf;
use std::time::Instant;

use pardal_router_core::dsn::{
    extract_autoroute_settings_from_str, extract_boundary_polygons_from_str, extract_model_from_str,
    extract_net_rules_from_str, extract_wiring_from_str, summarize_dsn, DsnAutorouteSettings,
    DsnNetRules,
};
use pardal_router_core::dsn::edit::append_wiring_exprs;
use pardal_router_core::dsn_to_ir::{
    apply_boundary_mask_from_world_polygons_with_holes, build_empty_ir_from_summary,
    build_net_name_to_id_sorted, stamp_keepouts_as_occ_and_via_forbidden,
    stamp_pins_as_occ_by_net, stamp_wiring_as_occ_by_padstack_layers,
};
use pardal_router_core::dsn_to_nm::wiring_to_nm_tracks_and_vias;
use pardal_router_core::export_ses::grid_path_to_nm_tracks_and_vias;
use pardal_router_core::ir::RoutingIr;
use pardal_router_core::router::{
    route_dial_3d_for_net_with_layer_dir_costs, route_net_mst_with_brush_and_layer_dir_costs,
    route_nets_negotiation_basic_dynamic_cost_with_brushes_and_layer_dir_costs,
    route_nets_negotiation_basic_with_brushes_and_layer_dir_costs,
    route_nets_negotiation_seeded_dynamic_cost_with_brushes_and_layer_dir_costs,
    route_nets_sequential_dynamic_cost_with_brushes_and_layer_dir_costs,
    route_nets_sequential_with_brushes_and_layer_dir_costs,
    NetRouteRequest, NetRouteResult, Path3, Point3,
};
use pardal_router_core::rules::RulesDb;
use pardal_router_core::ses::write_ses_minimal;

fn env_usize(name: &str) -> Option<usize> {
    std::env::var(name).ok().and_then(|v| v.parse::<usize>().ok())
}

fn env_u16(name: &str) -> Option<u16> {
    std::env::var(name).ok().and_then(|v| v.parse::<u16>().ok())
}

fn local_blocked_count(ir: &RoutingIr, p: Point3, net_id: u32, radius: usize) -> u32 {
    if p.layer >= ir.layers || p.x >= ir.width || p.y >= ir.height {
        return 0;
    }
    let mut out: u32 = 0;
    let x0 = p.x.saturating_sub(radius);
    let y0 = p.y.saturating_sub(radius);
    let x1 = (p.x + radius).min(ir.width - 1);
    let y1 = (p.y + radius).min(ir.height - 1);
    for y in y0..=y1 {
        for x in x0..=x1 {
            let occ = ir.get_occ(p.layer, x, y);
            if occ == 0 || occ == net_id {
                continue;
            }
            out = out.saturating_add(1);
        }
    }
    out
}

fn active_layers_from_autoroute_settings(
    layer_count: usize,
    settings: Option<&DsnAutorouteSettings>,
    model: &pardal_router_core::dsn::DsnModel,
) -> Vec<bool> {
    let mut active = vec![true; layer_count.max(1)];
    let Some(s) = settings else {
        return active;
    };
    for (layer_name, rule) in &s.layers {
        let Some(&idx) = model.layer_name_to_index.get(layer_name) else {
            continue;
        };
        if idx < active.len() {
            if let Some(a) = rule.active {
                active[idx] = a;
            }
        }
    }
    active
}

fn layer_dir_costs_from_autoroute_settings(
    layer_count: usize,
    settings: Option<&DsnAutorouteSettings>,
    model: &pardal_router_core::dsn::DsnModel,
) -> (Vec<u16>, Vec<u16>, Vec<u16>) {
    let mut h = vec![0u16; layer_count.max(1)];
    let mut v = vec![0u16; layer_count.max(1)];
    let mut d = vec![0u16; layer_count.max(1)];
    let Some(s) = settings else {
        return (h, v, d);
    };

    let scale = 10.0f64;
    let to_u16 = |x: f64| -> u16 {
        if !x.is_finite() || x <= 0.0 {
            return 0;
        }
        (x * scale).round().clamp(0.0, u16::MAX as f64) as u16
    };

    for (layer_name, rule) in &s.layers {
        let Some(&idx) = model.layer_name_to_index.get(layer_name) else {
            continue;
        };
        if idx >= h.len() {
            continue;
        }

        let pref = rule
            .preferred_direction_trace_costs
            .or(rule.against_preferred_direction_trace_costs)
            .unwrap_or(0.0);
        let against = rule
            .against_preferred_direction_trace_costs
            .or(rule.preferred_direction_trace_costs)
            .unwrap_or(0.0);

        let pref_u = to_u16(pref);
        let against_u = to_u16(against);

        match rule
            .preferred_direction
            .as_deref()
            .map(|s| s.to_ascii_lowercase())
            .as_deref()
        {
            Some("horizontal") => {
                h[idx] = pref_u;
                v[idx] = against_u;
            }
            Some("vertical") => {
                h[idx] = against_u;
                v[idx] = pref_u;
            }
            _ => {
                h[idx] = pref_u;
                v[idx] = pref_u;
            }
        }
        d[idx] = h[idx].max(v[idx]);
    }

    (h, v, d)
}

fn preferred_pin_layer(
    model: &pardal_router_core::dsn::DsnModel,
    pin_ref: &str,
    layer_count: usize,
    active_layers: &[bool],
) -> usize {
    if layer_count == 0 {
        return 0;
    }
    let Some(pin) = model.pins.get(pin_ref) else {
        return 0;
    };
    let Some(layers) = model.padstack_layers.get(&pin.padstack) else {
        return 0;
    };
    for &layer in layers {
        if layer < layer_count && active_layers.get(layer).copied().unwrap_or(true) {
            return layer;
        }
    }
    layers.first().copied().filter(|&l| l < layer_count).unwrap_or(0)
}

fn auto_pitch(
    summary: &pardal_router_core::dsn::DsnSummary,
    net_rules: Option<&DsnNetRules>,
    target_cells: f64,
    max_cells: f64,
) -> f64 {
    let Some(bbox) = summary.boundary_bbox else {
        return 2.0;
    };
    let dx = (bbox.max_x - bbox.min_x).abs().max(1.0);
    let dy = (bbox.max_y - bbox.min_y).abs().max(1.0);
    let max_dim = dx.max(dy);

    let target_cells = target_cells.max(64.0);

    // Limit peak memory/time for wavefront routing: total nodes ~= layers * max_cells^2.
    // `k6_wavefront_*` allocates `dist` + `prev` as `u32` each, so bytes ~= 8 * nodes.
    let layers = (summary.layer_count.max(1) as f64).max(1.0);
    let max_total_nodes = 10_000_000.0;
    let max_cells_by_layers = (max_total_nodes / layers).sqrt().max(target_cells);
    let max_cells = max_cells.max(target_cells).min(max_cells_by_layers);

    let mut pitch = (max_dim / target_cells).max(1e-9);

    if let Some(r) = net_rules {
        let w = r.default_rule.width.unwrap_or(f64::INFINITY);
        let c = r.default_rule.clearance.unwrap_or(f64::INFINITY);
        let feature = w.min(c);
        if feature.is_finite() && feature > 0.0 {
            pitch = pitch.min(feature * 0.5);
        }
    }

    // Avoid exploding the grid for very large boards.
    pitch = pitch.max(max_dim / max_cells);

    pitch.max(1e-9)
}

fn is_blocked_for_net(ir: &RoutingIr, p: Point3, blocked_value: u32, net_id: u32) -> bool {
    if p.layer >= ir.layers || p.x >= ir.width || p.y >= ir.height {
        return true;
    }
    let occ = ir.get_occ(p.layer, p.x, p.y);
    let pad = ir.get_pad_owner(p.layer, p.x, p.y);
    occ == blocked_value || (occ != 0 && occ != net_id) || (pad != 0 && pad != net_id)
}

fn find_nearest_free_cell_for_net(
    ir: &RoutingIr,
    seed: Point3,
    blocked_value: u32,
    net_id: u32,
    max_r: usize,
) -> Option<Point3> {
    if !is_blocked_for_net(ir, seed, blocked_value, net_id) {
        return Some(seed);
    }
    if seed.layer >= ir.layers {
        return None;
    }
    let sx = seed.x as isize;
    let sy = seed.y as isize;

    for r in 1..=max_r {
        let r_i = r as isize;
        for dx in 0..=r_i {
            let dy = r_i - dx;
            let candidates = [
                (sx + dx, sy + dy),
                (sx + dx, sy - dy),
                (sx - dx, sy + dy),
                (sx - dx, sy - dy),
            ];
            for (x, y) in candidates {
                if x < 0 || y < 0 {
                    continue;
                }
                let (xu, yu) = (x as usize, y as usize);
                if xu >= ir.width || yu >= ir.height {
                    continue;
                }
                let p = Point3 {
                    layer: seed.layer,
                    x: xu,
                    y: yu,
                };
                if !is_blocked_for_net(ir, p, blocked_value, net_id) {
                    return Some(p);
                }
            }
        }
    }
    None
}

fn find_nearest_pad_cell_for_net(ir: &RoutingIr, seed: Point3, net_id: u32, max_r: usize) -> Option<Point3> {
    if seed.layer >= ir.layers {
        return None;
    }
    if ir.pad_owner.len() != ir.occ.len() {
        return None;
    }

    if seed.x < ir.width && seed.y < ir.height {
        let idx = ir.idx(seed.layer, seed.x, seed.y);
        if ir.pad_owner[idx] == net_id {
            return Some(seed);
        }
    }

    let sx = seed.x as isize;
    let sy = seed.y as isize;

    for r in 1..=max_r {
        let r_i = r as isize;
        for dx in 0..=r_i {
            let dy = r_i - dx;
            let candidates = [
                (sx + dx, sy + dy),
                (sx + dx, sy - dy),
                (sx - dx, sy + dy),
                (sx - dx, sy - dy),
            ];
            for (x, y) in candidates {
                if x < 0 || y < 0 {
                    continue;
                }
                let (xu, yu) = (x as usize, y as usize);
                if xu >= ir.width || yu >= ir.height {
                    continue;
                }
                let idx = ir.idx(seed.layer, xu, yu);
                if ir.pad_owner[idx] == net_id {
                    return Some(Point3 {
                        layer: seed.layer,
                        x: xu,
                        y: yu,
                    });
                }
            }
        }
    }
    None
}

fn find_escape_cell_for_net(
    ir: &RoutingIr,
    seed: Point3,
    toward: Option<Point3>,
    blocked_value: u32,
    net_id: u32,
    max_r: usize,
) -> Option<Point3> {
    let pad = find_nearest_pad_cell_for_net(ir, seed, net_id, max_r)?;
    if pad.layer >= ir.layers || pad.x >= ir.width || pad.y >= ir.height {
        return None;
    }

    let (dir_x, dir_y) = toward
        .map(|t| (t.x as isize - pad.x as isize, t.y as isize - pad.y as isize))
        .unwrap_or((0, 0));

    let w = ir.width;
    let h = ir.height;

    let mut q: std::collections::VecDeque<(usize, usize)> = std::collections::VecDeque::new();
    let mut seen: std::collections::HashSet<usize> = std::collections::HashSet::new();
    q.push_back((pad.x, pad.y));
    seen.insert(pad.y * w + pad.x);

    let mut best: Option<(i64, i64, Point3)> = None; // (score, dist, point)

    let neigh8: [(isize, isize); 8] = [
        (1, 0),
        (0, 1),
        (-1, 0),
        (0, -1),
        (1, 1),
        (1, -1),
        (-1, 1),
        (-1, -1),
    ];
    let neigh4: [(isize, isize); 4] = [(1, 0), (0, 1), (-1, 0), (0, -1)];

    let max_r_i = max_r as isize;
    let mut visited: usize = 0;
    let visit_limit: usize = 4096;

    while let Some((cx, cy)) = q.pop_front() {
        visited += 1;
        if visited > visit_limit {
            break;
        }

        let dx0 = (cx as isize) - (pad.x as isize);
        let dy0 = (cy as isize) - (pad.y as isize);
        if dx0.abs().max(dy0.abs()) > max_r_i {
            continue;
        }

        // Candidate escape points: pick a pad cell on the boundary of the pad owner region.
        // We intentionally keep the endpoint on pad copper (pad_owner) so DSN export stitching
        // remains conservative; stitching directly to an outside free cell can create short
        // segments that violate clearance near dense pin fields.
        let pcx = cx as isize;
        let pcy = cy as isize;
        let mut is_boundary = false;
        for (dx, dy) in neigh8 {
            let nx = pcx + dx;
            let ny = pcy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (xu, yu) = (nx as usize, ny as usize);
            if xu >= w || yu >= h {
                continue;
            }
            let p = Point3 {
                layer: pad.layer,
                x: xu,
                y: yu,
            };
            if !is_blocked_for_net(ir, p, blocked_value, net_id) {
                is_boundary = true;
                break;
            }
        }
        if is_boundary {
            let ddx = (cx as isize) - (pad.x as isize);
            let ddy = (cy as isize) - (pad.y as isize);
            let dist = (ddx.abs() + ddy.abs()) as i64;
            let score = (ddx as i64) * (dir_x as i64) + (ddy as i64) * (dir_y as i64);
            let cand = (
                score,
                dist,
                Point3 {
                    layer: pad.layer,
                    x: cx,
                    y: cy,
                },
            );
            best = match best {
                None => Some(cand),
                Some(cur) => {
                    if cand.0 > cur.0 || (cand.0 == cur.0 && cand.1 < cur.1) {
                        Some(cand)
                    } else {
                        Some(cur)
                    }
                }
            };
        }

        // Flood fill inside this net's pad copper to find additional boundary cells.
        for (dx, dy) in neigh4 {
            let nx = pcx + dx;
            let ny = pcy + dy;
            if nx < 0 || ny < 0 {
                continue;
            }
            let (xu, yu) = (nx as usize, ny as usize);
            if xu >= w || yu >= h {
                continue;
            }
            let idx2 = yu * w + xu;
            if seen.contains(&idx2) {
                continue;
            }
            if ir.get_pad_owner(pad.layer, xu, yu) != net_id {
                continue;
            }
            seen.insert(idx2);
            q.push_back((xu, yu));
        }
    }

    best.map(|b| b.2)
}

fn usage() -> ! {
    eprintln!(
        "Usage:\n  pardal_route_dsn <path.dsn> <net_name|FIRST|ALL|ALLMST|MST:<net_name>> [pitch] [via_cost|auto] [limit] [brush|auto] [keepouts] [negotiation]\n\n\
Defaults:\n  pitch=auto (target ~900 cells)\n  via_cost=5 (or `auto` to use DSN autoroute_settings when available)\n  brush=0 (grid cells; use `auto` for width-based)\n  keepouts=auto|all|none\n  negotiation=off|basic|seeded_basic\n"
    );
    std::process::exit(2);
}

fn ir_has_any_free_cell(ir: &RoutingIr) -> bool {
    ir.occ.iter().any(|&v| v == 0)
}

fn main() {
    let timing = std::env::var("PARDAL_TIMING").is_ok();
    let ses_out_path = std::env::var("PARDAL_ROUTE_SES_OUT").ok();
    let dsn_out_path = std::env::var("PARDAL_ROUTE_DSN_OUT").ok();

    let mut args = std::env::args().skip(1);
    let Some(dsn_path) = args.next() else { usage() };
    let Some(net_name) = args.next() else { usage() };
    let pitch_arg = args.next().unwrap_or_else(|| "auto".to_string());
    let via_cost_arg = args.next().unwrap_or_else(|| "5".to_string());
    let limit: usize = args
        .next()
        .as_deref()
        .unwrap_or("10")
        .parse()
        .unwrap_or(10);
    let brush_arg = args.next().unwrap_or_else(|| "0".to_string());
    let keepouts_mode = args.next().unwrap_or_else(|| "auto".to_string());
    let negotiation_mode = args.next().unwrap_or_else(|| "off".to_string());
    let keepouts_requested = !keepouts_mode.eq_ignore_ascii_case("none");
    let keepouts_auto_fallback = keepouts_mode.eq_ignore_ascii_case("auto");

    let t0 = Instant::now();
    let dsn_bytes = std::fs::read(&dsn_path).unwrap_or_else(|e| {
        eprintln!("Failed to read {dsn_path}: {e}");
        std::process::exit(1);
    });
    if timing {
        eprintln!("timing: read_dsn={}ms", t0.elapsed().as_millis());
    }
    let dsn_cow = String::from_utf8_lossy(&dsn_bytes);
    let dsn: &str = &dsn_cow;

    let t0 = Instant::now();
    let summary = summarize_dsn(&dsn).unwrap_or_else(|e| {
        eprintln!("summarize_dsn failed: {e}");
        std::process::exit(1);
    });
    if timing {
        eprintln!("timing: summarize_dsn={}ms", t0.elapsed().as_millis());
    }

    let t0 = Instant::now();
    let net_rules = if pitch_arg.eq_ignore_ascii_case("auto") {
        extract_net_rules_from_str(&dsn).ok()
    } else {
        None
    };
    let net_rules_for_width = extract_net_rules_from_str(&dsn).ok();
    let autoroute_settings = extract_autoroute_settings_from_str(&dsn).ok().flatten();
    let rules_db = net_rules_for_width.clone().map(RulesDb::from_dsn_net_rules).unwrap_or_default();
    if timing {
        eprintln!("timing: extract_net_rules={}ms", t0.elapsed().as_millis());
    }
    let pitch: f64 = if pitch_arg.eq_ignore_ascii_case("auto") {
        auto_pitch(&summary, net_rules.as_ref(), 900.0, 4000.0)
    } else {
        pitch_arg.parse().unwrap_or(2.0)
    };

    let default_width_world = rules_db.default_width_world().unwrap_or(pitch.max(0.1));
    let default_clearance_world = rules_db.default_clearance_world().unwrap_or(0.0);
    let via_cost: u16 = if via_cost_arg.eq_ignore_ascii_case("auto") {
        let vias_enabled = autoroute_settings.as_ref().and_then(|s| s.vias).unwrap_or(true);
        if !vias_enabled {
            0
        } else {
            let v = autoroute_settings.as_ref().and_then(|s| s.via_costs).unwrap_or(5);
            v.clamp(0, u16::MAX as i64) as u16
        }
    } else {
        via_cost_arg.parse().unwrap_or(5)
    };
    let brush: u8 = if brush_arg.eq_ignore_ascii_case("auto") {
        rules_db.brush_radius_cells_default(pitch)
    } else {
        brush_arg.parse().unwrap_or(0)
    };

    let t0 = Instant::now();
    let model = extract_model_from_str(&dsn).unwrap_or_else(|e| {
        eprintln!("extract_model_from_str failed: {e}");
        std::process::exit(1);
    });
    if timing {
        eprintln!("timing: extract_model={}ms", t0.elapsed().as_millis());
    }

    let t0 = Instant::now();
    let wiring = extract_wiring_from_str(&dsn).unwrap_or_else(|e| {
        eprintln!("extract_wiring_from_str failed: {e}");
        std::process::exit(1);
    });
    if timing {
        eprintln!("timing: extract_wiring={}ms", t0.elapsed().as_millis());
    }

    let t0 = Instant::now();
    let boundary_polys = extract_boundary_polygons_from_str(&dsn).unwrap_or_else(|e| {
        eprintln!("extract_boundary_polygons_from_str failed: {e}");
        std::process::exit(1);
    });
    let (boundary_outers, boundary_holes) = select_outers_and_holes(boundary_polys);
    if timing {
        eprintln!("timing: extract_boundary_polys={}ms", t0.elapsed().as_millis());
    }

    if net_name.eq_ignore_ascii_case("ALL") || net_name.eq_ignore_ascii_case("ALLMST") {
        // Route multiple nets: pick a deterministic subset of nets with >=2 pins and route each.
        // - ALL: route only the first two pins (fast smoke mode)
        // - ALLMST: expand each chosen net into its Manhattan MST edges (multi-pin support)
        let mst_mode = net_name.eq_ignore_ascii_case("ALLMST");
        let t0 = Instant::now();
        let net_name_to_id = build_net_name_to_id_sorted(&model);
        let (mut ir, tx) = build_empty_ir_from_summary(&summary, pitch).unwrap_or_else(|| {
            eprintln!("build_empty_ir_from_summary failed (missing bbox or invalid pitch)");
            std::process::exit(1);
        });
        if timing {
            eprintln!("timing: build_empty_ir={}ms", t0.elapsed().as_millis());
        }

        // Block outside the board on every layer.
        let t0 = Instant::now();
        for layer in 0..ir.layers {
            let ok = apply_boundary_mask_from_world_polygons_with_holes(
                &mut ir,
                tx,
                layer,
                1,
                &boundary_outers,
                &boundary_holes,
            );
            if !ok {
                eprintln!("apply_boundary_mask failed on layer {layer}");
                std::process::exit(1);
            }
        }
        if timing {
            eprintln!("timing: apply_boundary_masks={}ms", t0.elapsed().as_millis());
        }

        // Respect DSN autoroute_settings layer activation: if a layer is inactive, block it entirely.
        let active_layers =
            active_layers_from_autoroute_settings(ir.layers, autoroute_settings.as_ref(), &model);
        let (layer_h_costs, layer_v_costs, layer_d_costs) =
            layer_dir_costs_from_autoroute_settings(ir.layers, autoroute_settings.as_ref(), &model);
        for (layer, is_active) in active_layers.iter().copied().enumerate() {
            if !is_active && layer < ir.layers {
                let base = layer * ir.width * ir.height;
                let end = base + ir.width * ir.height;
                for v in &mut ir.occ[base..end] {
                    *v = 1;
                }
            }
        }

        let t0 = Instant::now();
        stamp_pins_as_occ_by_net(&mut ir, tx, &model, 1, default_clearance_world, &net_name_to_id);
        if timing {
            eprintln!("timing: stamp_pins={}ms", t0.elapsed().as_millis());
        }

        let mut names: Vec<&String> = model.nets.keys().collect();
        names.sort();
        let mut candidates: Vec<(i64, String, String, NetRouteRequest, (f64, f64), (f64, f64))> = Vec::new();

        for name in names {
            let net = &model.nets[name];
            if net.pins.len() < 2 {
                continue;
            }
            let Some(&net_id) = net_name_to_id.get(name.as_str()) else {
                continue;
            };
            let a = net.pins[0].as_str();
            let b = net.pins[1].as_str();
            let (Some(ap), Some(bp)) = (model.pins.get(a), model.pins.get(b)) else {
                continue;
            };
            let (Some(ag), Some(bg)) = (tx.world_to_grid(ap.x, ap.y), tx.world_to_grid(bp.x, bp.y)) else {
                continue;
            };
            if ag == bg {
                continue;
            }
            let start_layer = preferred_pin_layer(&model, a, ir.layers, &active_layers);
            let goal_layer = preferred_pin_layer(&model, b, ir.layers, &active_layers);
            let req = NetRouteRequest {
                net_id,
                start: Point3 { layer: start_layer, x: ag.x, y: ag.y },
                goal: Point3 { layer: goal_layer, x: bg.x, y: bg.y },
            };
            let dist = (ag.x as i64 - bg.x as i64).abs() + (ag.y as i64 - bg.y as i64).abs();
            candidates.push((dist, name.clone(), format!("{a}->{b}"), req, (ap.x, ap.y), (bp.x, bp.y)));
        }

        // Smoke routing: try "moderate" connections first (avoid trivial adjacent-pad escapes and
        // massive cross-board nets), which tends to be more stable across varied fixtures.
        candidates.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)));
        let median_dist = candidates.get(candidates.len() / 2).map(|c| c.0).unwrap_or(0);
        candidates.sort_by(|a, b| {
            let da = (a.0 - median_dist).abs();
            let db = (b.0 - median_dist).abs();
            da.cmp(&db)
                .then_with(|| a.0.cmp(&b.0))
                .then_with(|| a.1.cmp(&b.1))
        });
        let mut reqs: Vec<NetRouteRequest> = Vec::new();
        let mut req_names: Vec<String> = Vec::new();
        let mut req_net_names: Vec<String> = Vec::new();
        let mut req_endpoints_world: Vec<((f64, f64), (f64, f64))> = Vec::new();
        for (_, name, pins, req, axy, bxy) in candidates.into_iter().take(limit) {
            if !mst_mode {
                req_names.push(format!("{name} {pins}"));
                req_net_names.push(name.clone());
                reqs.push(req);
                req_endpoints_world.push((axy, bxy));
                continue;
            }

            let Some(net) = model.nets.get(&name) else {
                continue;
            };
            let Some(&net_id) = net_name_to_id.get(name.as_str()) else {
                continue;
            };

            // Collect pins with both world and grid coordinates.
            let mut pins3: Vec<Point3> = Vec::new();
            let mut pins2: Vec<pardal_router_core::router::Point> = Vec::new();
            let mut pins_world: Vec<(f64, f64)> = Vec::new();
            let mut pin_refs: Vec<&str> = Vec::new();
            for pin_ref in &net.pins {
                let Some(pin) = model.pins.get(pin_ref.as_str()) else {
                    continue;
                };
                let Some(g) = tx.world_to_grid(pin.x, pin.y) else {
                    continue;
                };
                let layer = preferred_pin_layer(&model, pin_ref.as_str(), ir.layers, &active_layers);
                pins3.push(Point3 {
                    layer,
                    x: g.x,
                    y: g.y,
                });
                pins2.push(pardal_router_core::router::Point { x: g.x, y: g.y });
                pins_world.push((pin.x, pin.y));
                pin_refs.push(pin_ref.as_str());
            }
            if pins3.len() < 2 {
                continue;
            }

            // Expand the net into MST edges and enqueue each edge as its own request (same `net_id`).
            let edges = pardal_router_core::mst::mst_manhattan(&pins2);
            for (a, b) in edges {
                let ra = pins3[a];
                let rb = pins3[b];
                if ra.layer == rb.layer && ra.x == rb.x && ra.y == rb.y {
                    continue;
                }
                reqs.push(NetRouteRequest {
                    net_id,
                    start: ra,
                    goal: rb,
                });
                req_names.push(format!(
                    "{name} {}->{}",
                    pin_refs.get(a).copied().unwrap_or("?"),
                    pin_refs.get(b).copied().unwrap_or("?")
                ));
                req_net_names.push(name.clone());
                req_endpoints_world.push((pins_world[a], pins_world[b]));
            }
        }

        let t0 = Instant::now();
        stamp_wiring_as_occ_by_padstack_layers(&mut ir, tx, &model, &wiring, 1, default_clearance_world, &net_name_to_id);
        if timing {
            eprintln!("timing: stamp_wiring={}ms", t0.elapsed().as_millis());
        }
        if keepouts_requested {
            let t0 = Instant::now();
            stamp_keepouts_as_occ_and_via_forbidden(&mut ir, tx, &model, 1);
            if timing {
                eprintln!("timing: stamp_keepouts={}ms", t0.elapsed().as_millis());
            }
            if keepouts_auto_fallback && !ir_has_any_free_cell(&ir) {
                eprintln!("warn: keepouts block all free cells; retrying with keepouts=none");
                let (mut ir2, tx2) = build_empty_ir_from_summary(&summary, pitch).unwrap_or_else(|| {
                    eprintln!("build_empty_ir_from_summary failed (missing bbox or invalid pitch)");
                    std::process::exit(1);
                });
                for layer in 0..ir2.layers {
                    let ok = apply_boundary_mask_from_world_polygons_with_holes(
                        &mut ir2,
                        tx2,
                        layer,
                        1,
                        &boundary_outers,
                        &boundary_holes,
                    );
                    if !ok {
                        eprintln!("apply_boundary_mask failed on layer {layer}");
                        std::process::exit(1);
                    }
                }
                stamp_pins_as_occ_by_net(&mut ir2, tx2, &model, 1, default_clearance_world, &net_name_to_id);
                stamp_wiring_as_occ_by_padstack_layers(&mut ir2, tx2, &model, &wiring, 1, default_clearance_world, &net_name_to_id);
                ir = ir2;
            }
        }

        // If endpoints land outside the boundary due to coarse grid rounding, pick the nearest free
        // cell on the same layer so we at least have a chance to route.
        for r in &mut reqs {
            r.start = find_nearest_pad_cell_for_net(&ir, r.start, r.net_id, 24)
                .or_else(|| find_nearest_free_cell_for_net(&ir, r.start, 1, r.net_id, 24))
                .unwrap_or(r.start);
            r.goal = find_nearest_pad_cell_for_net(&ir, r.goal, r.net_id, 24)
                .or_else(|| find_nearest_free_cell_for_net(&ir, r.goal, 1, r.net_id, 24))
                .unwrap_or(r.goal);
        }

        let endpoint_escape = std::env::var("PARDAL_ENDPOINT_ESCAPE").is_ok();
        if endpoint_escape {
            for r in &mut reqs {
                let start_hint = Some(r.goal);
                let goal_hint = Some(r.start);
                if let Some(p) = find_escape_cell_for_net(&ir, r.start, start_hint, 1, r.net_id, 32) {
                    r.start = p;
                }
                if let Some(p) = find_escape_cell_for_net(&ir, r.goal, goal_hint, 1, r.net_id, 32) {
                    r.goal = p;
                }
            }
        }

        let order_mode = std::env::var("PARDAL_ROUTE_ORDER").unwrap_or_else(|_| "median".to_string());
        let use_hard_first = matches!(order_mode.as_str(), "hard_first");
        let use_angle = matches!(order_mode.as_str(), "angle");
        if (use_hard_first || use_angle) && reqs.len() > 1 {
            let mut order: Vec<usize> = (0..reqs.len()).collect();
            order.sort_by(|&ia, &ib| {
                let a = reqs[ia];
                let b = reqs[ib];
                let da = (a.start.x as i64 - a.goal.x as i64).abs()
                    + (a.start.y as i64 - a.goal.y as i64).abs();
                let db = (b.start.x as i64 - b.goal.x as i64).abs()
                    + (b.start.y as i64 - b.goal.y as i64).abs();

                if use_angle && req_endpoints_world.len() == reqs.len() {
                    let (asw, agw) = req_endpoints_world[ia];
                    let (bsw, bgw) = req_endpoints_world[ib];
                    let (adx, ady) = (agw.0 - asw.0, agw.1 - asw.1);
                    let (bdx, bdy) = (bgw.0 - bsw.0, bgw.1 - bsw.1);
                    let mut aa = ady.atan2(adx);
                    let mut ba = bdy.atan2(bdx);
                    if aa < 0.0 {
                        aa += std::f64::consts::TAU;
                    }
                    if ba < 0.0 {
                        ba += std::f64::consts::TAU;
                    }
                    let aa_q = (aa * 1_000_000.0) as i64;
                    let ba_q = (ba * 1_000_000.0) as i64;
                    return aa_q
                        .cmp(&ba_q)
                        .then_with(|| da.cmp(&db))
                        .then_with(|| req_names[ia].cmp(&req_names[ib]));
                }

                let sa = local_blocked_count(&ir, a.start, a.net_id, 6)
                    .saturating_add(local_blocked_count(&ir, a.goal, a.net_id, 6));
                let sb = local_blocked_count(&ir, b.start, b.net_id, 6)
                    .saturating_add(local_blocked_count(&ir, b.goal, b.net_id, 6));
                sb.cmp(&sa)
                    .then_with(|| db.cmp(&da))
                    .then_with(|| req_names[ia].cmp(&req_names[ib]))
            });

            let req_names2: Vec<String> = order.iter().map(|&i| req_names[i].clone()).collect();
            let req_net_names2: Vec<String> = order.iter().map(|&i| req_net_names[i].clone()).collect();
            let req_endpoints_world2: Vec<((f64, f64), (f64, f64))> =
                order.iter().map(|&i| req_endpoints_world[i]).collect();
            let reqs2: Vec<NetRouteRequest> = order.iter().map(|&i| reqs[i]).collect();

            req_names = req_names2;
            req_net_names = req_net_names2;
            req_endpoints_world = req_endpoints_world2;
            reqs = reqs2;
        }

        let t0 = Instant::now();
        let cost_field = ir.build_cost_field_adjacent(1, 2, 8);
        if timing {
            eprintln!("timing: build_cost_field_adjacent={}ms", t0.elapsed().as_millis());
        }

        let t0 = Instant::now();
        let results = {
            let (brushes, _) = if brush_arg.eq_ignore_ascii_case("auto") {
                let mut brushes: Vec<u8> = Vec::with_capacity(reqs.len());
                for net in &req_net_names {
                    brushes.push(rules_db.brush_radius_cells_for_net(net, pitch));
                }
                (brushes, true)
            } else {
                (vec![brush; reqs.len()], false)
            };

            if negotiation_mode.eq_ignore_ascii_case("basic") {
                // Minimal negotiation settings (not parity): deterministic and bounded.
                let max_iters = env_usize("PARDAL_NEGOTIATION_MAX_ITERS")
                    .unwrap_or_else(|| reqs.len().saturating_mul(8).max(200));
                let other_net_penalty = env_u16("PARDAL_NEGOTIATION_OTHER_NET_PENALTY").unwrap_or(50);
                let max_ripup = env_usize("PARDAL_NEGOTIATION_MAX_RIPUP_NETS_PER_ATTEMPT").unwrap_or(64);
                let rebuild_every = env_usize("PARDAL_DYNAMIC_COST_REBUILD_EVERY").unwrap_or(0);
                if rebuild_every > 0 {
                    let occ_penalty = env_u16("PARDAL_DYNAMIC_COST_OCC_PENALTY").unwrap_or(2);
                    let blocked_penalty = env_u16("PARDAL_DYNAMIC_COST_BLOCKED_PENALTY").unwrap_or(8);
                    route_nets_negotiation_basic_dynamic_cost_with_brushes_and_layer_dir_costs(
                        &mut ir,
                        &reqs,
                        1,
                        &layer_h_costs,
                        &layer_v_costs,
                        &layer_d_costs,
                        via_cost,
                        &brushes,
                        other_net_penalty,
                        max_iters,
                        max_ripup,
                        rebuild_every,
                        occ_penalty,
                        blocked_penalty,
                    )
                } else {
                    route_nets_negotiation_basic_with_brushes_and_layer_dir_costs(
                        &mut ir,
                        &reqs,
                        1,
                        &cost_field,
                        &layer_h_costs,
                        &layer_v_costs,
                        &layer_d_costs,
                        via_cost,
                        &brushes,
                        other_net_penalty,
                        max_iters,
                        max_ripup,
                    )
                }
            } else if negotiation_mode.eq_ignore_ascii_case("seeded_basic") {
                // Seed with a fast sequential pass, then negotiate only the unrouted requests.
                //
                // This is intended as a practical stepping stone toward FreeRouting-style
                // batch completion: get a baseline solution quickly, then spend the budget on
                // the hardest remaining connections.
                let rebuild_every = env_usize("PARDAL_DYNAMIC_COST_REBUILD_EVERY").unwrap_or(0);
                let occ_penalty = env_u16("PARDAL_DYNAMIC_COST_OCC_PENALTY").unwrap_or(2);
                let blocked_penalty = env_u16("PARDAL_DYNAMIC_COST_BLOCKED_PENALTY").unwrap_or(8);

                let seed_results: Vec<NetRouteResult> = if rebuild_every > 0 {
                    route_nets_sequential_dynamic_cost_with_brushes_and_layer_dir_costs(
                        &mut ir,
                        &reqs,
                        1,
                        &layer_h_costs,
                        &layer_v_costs,
                        &layer_d_costs,
                        via_cost,
                        &brushes,
                        rebuild_every,
                        occ_penalty,
                        blocked_penalty,
                    )
                } else {
                    route_nets_sequential_with_brushes_and_layer_dir_costs(
                        &mut ir,
                        &reqs,
                        1,
                        &cost_field,
                        &layer_h_costs,
                        &layer_v_costs,
                        &layer_d_costs,
                        via_cost,
                        &brushes,
                    )
                };
                let seed_paths: Vec<Option<Path3>> =
                    seed_results.into_iter().map(|r| r.path).collect();

                let max_iters = env_usize("PARDAL_NEGOTIATION_MAX_ITERS")
                    .unwrap_or_else(|| reqs.len().saturating_mul(8).max(200));
                let other_net_penalty = env_u16("PARDAL_NEGOTIATION_OTHER_NET_PENALTY").unwrap_or(50);
                let max_ripup = env_usize("PARDAL_NEGOTIATION_MAX_RIPUP_NETS_PER_ATTEMPT").unwrap_or(64);

                route_nets_negotiation_seeded_dynamic_cost_with_brushes_and_layer_dir_costs(
                    &mut ir,
                    &reqs,
                    1,
                    &layer_h_costs,
                    &layer_v_costs,
                    &layer_d_costs,
                    via_cost,
                    &brushes,
                    other_net_penalty,
                    max_iters,
                    max_ripup,
                    rebuild_every,
                    occ_penalty,
                    blocked_penalty,
                    &seed_paths,
                    std::env::var("PARDAL_SEEDED_ALLOW_RIPUP_SEEDED").is_ok(),
                )
            } else {
                let rebuild_every = env_usize("PARDAL_DYNAMIC_COST_REBUILD_EVERY").unwrap_or(0);
                if rebuild_every > 0 {
                    let occ_penalty = env_u16("PARDAL_DYNAMIC_COST_OCC_PENALTY").unwrap_or(2);
                    let blocked_penalty = env_u16("PARDAL_DYNAMIC_COST_BLOCKED_PENALTY").unwrap_or(8);
                    route_nets_sequential_dynamic_cost_with_brushes_and_layer_dir_costs(
                        &mut ir,
                        &reqs,
                        1,
                        &layer_h_costs,
                        &layer_v_costs,
                        &layer_d_costs,
                        via_cost,
                        &brushes,
                        rebuild_every,
                        occ_penalty,
                        blocked_penalty,
                    )
                } else {
                    route_nets_sequential_with_brushes_and_layer_dir_costs(
                        &mut ir,
                        &reqs,
                        1,
                        &cost_field,
                        &layer_h_costs,
                        &layer_v_costs,
                        &layer_d_costs,
                        via_cost,
                        &brushes,
                    )
                }
            }
        };
        if timing {
            eprintln!("timing: route_nets={}ms", t0.elapsed().as_millis());
        }
        let ok = results.iter().filter(|r| r.path.is_some()).count();

        if let Some(out_path) = &dsn_out_path {
            // Append routed wiring into the original DSN so FreeRouting headless can load it.
            fn escape_ident(s: &str) -> String {
                if s.chars().any(|c| c.is_whitespace() || c == '(' || c == ')' || c == '"') {
                    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
                } else {
                    s.to_string()
                }
            }
            fn fmt_num(v: f64) -> String {
                // Compact but stable: trim trailing zeros.
                let s = format!("{v:.6}");
                let s = s.trim_end_matches('0').trim_end_matches('.').to_string();
                if s.is_empty() { "0".to_string() } else { s }
            }

            let mut id_to_name: std::collections::HashMap<u32, String> = std::collections::HashMap::new();
            for (name, id) in &net_name_to_id {
                id_to_name.insert(*id, name.clone());
            }

            let pick_via_padstack = || -> String {
                if model.padstacks.contains_key("via0") {
                    return "via0".to_string();
                }
                let mut names: Vec<&String> = model.padstacks.keys().collect();
                names.sort();
                names.first().cloned().cloned().unwrap_or_else(|| "via0".to_string())
            };
            let fallback_via_padstack = pick_via_padstack();

            // Build DSN wiring expressions for newly routed segments.
            let mut exprs: Vec<String> = Vec::new();
            let mut seen_vias: std::collections::HashSet<(u32, usize, usize)> = std::collections::HashSet::new();
            let layer_token_for = |layer_idx0: usize| -> String {
                model
                    .layer_name_to_index
                    .iter()
                    .find_map(|(k, &v)| if v == layer_idx0 { Some(k.clone()) } else { None })
                    .unwrap_or_else(|| (layer_idx0 + 1).to_string())
            };

            for (i, r) in results.iter().enumerate() {
                let Some(p) = &r.path else { continue };
                let Some(net_name) = id_to_name.get(&r.net_id) else { continue };
                let width_world = net_rules_for_width
                    .as_ref()
                    .and_then(|nr| nr.width_for_net(net_name))
                    .unwrap_or(default_width_world);

                if let (Some(p0), Some(pn)) = (p.points.first().copied(), p.points.last().copied()) {
                    if let Some((a_world, b_world)) = req_endpoints_world.get(i).copied() {
                        let (sx, sy) = a_world;
                        let (gx, gy) = b_world;

                        let (p0xw, p0yw) =
                            tx.grid_to_world(pardal_router_core::router::Point { x: p0.x, y: p0.y });
                        let (pnxw, pnyw) =
                            tx.grid_to_world(pardal_router_core::router::Point { x: pn.x, y: pn.y });

                        let layer0 = escape_ident(&layer_token_for(p0.layer));
                        let layern = escape_ident(&layer_token_for(pn.layer));

                        let ok0 = ir.get_occ(p0.layer, p0.x, p0.y) == r.net_id;
                        let okn = ir.get_occ(pn.layer, pn.x, pn.y) == r.net_id;
                        if ok0 && (sx - p0xw).abs().max((sy - p0yw).abs()) > 1e-6 {
                            exprs.push(format!(
                                "(wire (path {layer} {w} {x1} {y1} {x2} {y2}) (net {net}))",
                                layer = layer0,
                                w = fmt_num(width_world),
                                x1 = fmt_num(sx),
                                y1 = fmt_num(sy),
                                x2 = fmt_num(p0xw),
                                y2 = fmt_num(p0yw),
                                net = escape_ident(net_name),
                            ));
                        }
                        if okn && (gx - pnxw).abs().max((gy - pnyw).abs()) > 1e-6 {
                            exprs.push(format!(
                                "(wire (path {layer} {w} {x1} {y1} {x2} {y2}) (net {net}))",
                                layer = layern,
                                w = fmt_num(width_world),
                                x1 = fmt_num(pnxw),
                                y1 = fmt_num(pnyw),
                                x2 = fmt_num(gx),
                                y2 = fmt_num(gy),
                                net = escape_ident(net_name),
                            ));
                        }
                    }
                }

                for w in p.points.windows(2) {
                    let a = w[0];
                    let b = w[1];
                    if a.layer == b.layer {
                        if a.x == b.x && a.y == b.y {
                            continue;
                        }
                        let (axw, ayw) = tx.grid_to_world(pardal_router_core::router::Point { x: a.x, y: a.y });
                        let (bxw, byw) = tx.grid_to_world(pardal_router_core::router::Point { x: b.x, y: b.y });

                        // Use a stable layer token: prefer the DSN layer name if present, else numeric.
                        let layer_token = layer_token_for(a.layer);

                        exprs.push(format!(
                            "(wire (path {layer} {w} {x1} {y1} {x2} {y2}) (net {net}))",
                            layer = escape_ident(&layer_token),
                            w = fmt_num(width_world),
                            x1 = fmt_num(axw),
                            y1 = fmt_num(ayw),
                            x2 = fmt_num(bxw),
                            y2 = fmt_num(byw),
                            net = escape_ident(net_name),
                        ));
                    } else {
                        let x = if a.x == b.x { a.x } else { b.x };
                        let y = if a.y == b.y { a.y } else { b.y };
                        if !seen_vias.insert((r.net_id, x, y)) {
                            continue;
                        }
                        let (xw, yw) = tx.grid_to_world(pardal_router_core::router::Point { x, y });
                        let via_padstack = rules_db
                            .via_padstack_for_net(net_name)
                            .filter(|ps| model.padstacks.contains_key(ps))
                            .unwrap_or_else(|| fallback_via_padstack.clone());
                        exprs.push(format!(
                            "(via {ps} {x} {y} (net {net}))",
                            ps = escape_ident(&via_padstack),
                            x = fmt_num(xw),
                            y = fmt_num(yw),
                            net = escape_ident(net_name),
                        ));
                    }
                }
            }

            match append_wiring_exprs(&dsn, &exprs) {
                Ok(out_dsn) => {
                    if let Err(e) = std::fs::write(out_path, out_dsn) {
                        eprintln!("warn: failed to write DSN to {out_path}: {e}");
                    } else {
                        eprintln!("wrote: {out_path}");
                    }
                }
                Err(e) => eprintln!("warn: failed to append wiring to DSN: {e}"),
            }
        }

        if let Some(out_path) = &ses_out_path {
            let (mut tracks, mut vias) = match wiring_to_nm_tracks_and_vias(&summary, &model, &wiring, &net_name_to_id) {
                Ok(tv) => tv,
                Err(e) => {
                    eprintln!("warn: wiring_to_nm_tracks_and_vias failed: {e}");
                    (Vec::new(), Vec::new())
                }
            };

            for r in &results {
                let Some(p) = &r.path else { continue };
                let width_world = net_name_to_id
                    .iter()
                    .find_map(|(name, &id)| if id == r.net_id { Some(name.as_str()) } else { None })
                    .and_then(|name| net_rules_for_width.as_ref().and_then(|nr| nr.width_for_net(name)))
                    .unwrap_or(default_width_world);
                match grid_path_to_nm_tracks_and_vias(
                    &summary,
                    &model,
                    tx,
                    &p.points,
                    r.net_id,
                    0,
                    width_world,
                    None,
                ) {
                    Ok((mut t2, mut v2)) => {
                        tracks.append(&mut t2);
                        vias.append(&mut v2);
                    }
                    Err(e) => {
                        eprintln!("warn: failed to export route for net_id {}: {e}", r.net_id);
                    }
                }
            }

            let mut id_to_name: std::collections::HashMap<u32, String> = std::collections::HashMap::new();
            for (name, id) in &net_name_to_id {
                id_to_name.insert(*id, name.clone());
            }
            let session_name = std::path::Path::new(out_path)
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .to_string();
            let base_design_name = std::path::Path::new(&dsn_path)
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .to_string();

            let ses = write_ses_minimal(
                &session_name,
                &base_design_name,
                &summary,
                &model,
                &tracks,
                &vias,
                &id_to_name,
            );
            if let Err(e) = std::fs::write(out_path, ses) {
                eprintln!("warn: failed to write SES to {out_path}: {e}");
            } else {
                eprintln!("wrote: {out_path}");
            }
        }

        println!("dsn: {}", PathBuf::from(&dsn_path).display());
        println!("mode: ALL");
        println!("grid: {}x{}x{} pitch={pitch}", ir.width, ir.height, ir.layers);
        println!("requested: {}", results.len());
        println!("routed: {ok}");
        for (name, res) in req_names.iter().zip(results.iter()) {
            println!("net_result: {name} {}", if res.path.is_some() { "OK" } else { "FAIL" });
        }
        std::process::exit(0);
    }

    let (mst_mode, net_name) = if let Some(rest) = net_name.strip_prefix("MST:") {
        (true, rest.to_string())
    } else {
        (false, net_name)
    };

    let net = if net_name.eq_ignore_ascii_case("FIRST") {
        let mut names: Vec<&String> = model.nets.keys().collect();
        names.sort();
        let mut picked = None;
        for name in names {
            if let Some(n) = model.nets.get(name) {
                if n.pins.len() >= 2 {
                    picked = Some(n);
                    break;
                }
            }
        }
        match picked {
            Some(n) => n,
            None => {
                eprintln!("No net with >=2 pins found (nets={})", model.nets.len());
                std::process::exit(1);
            }
        }
    } else {
        let Some(net) = model.nets.get(&net_name) else {
            eprintln!("Net {net_name} not found. Total nets: {}", model.nets.len());
            let mut names: Vec<&String> = model.nets.keys().collect();
            names.sort();
            eprintln!("First 20 nets:");
            for n in names.into_iter().take(20) {
                eprintln!("  {n}");
            }
            std::process::exit(1);
        };
        net
    };
    if net.pins.len() < 2 {
        eprintln!("Net {net_name} has <2 pins");
        std::process::exit(1);
    }

    let (mut ir, tx) = build_empty_ir_from_summary(&summary, pitch).unwrap_or_else(|| {
        eprintln!("build_empty_ir_from_summary failed (missing bbox or invalid pitch)");
        std::process::exit(1);
    });

    let debug = std::env::var("PARDAL_ROUTE_DEBUG").is_ok();
    if debug {
        if let Some(bb) = summary.boundary_bbox {
            eprintln!(
                "debug: summary_bbox=({:.3},{:.3})..({:.3},{:.3}) layers={} pitch={:.6} origin=({:.3},{:.3}) grid={}x{}",
                bb.min_x,
                bb.min_y,
                bb.max_x,
                bb.max_y,
                summary.layer_count,
                pitch,
                tx.origin_x,
                tx.origin_y,
                ir.width,
                ir.height
            );
        } else {
            eprintln!("debug: summary_bbox=<none> layers={} pitch={pitch}", summary.layer_count);
        }
        eprintln!(
            "debug: boundary_polys outers={} holes={}",
            boundary_outers.len(),
            boundary_holes.len()
        );
        if let Some(p) = boundary_outers.first() {
            let (min_x, min_y, max_x, max_y) = bbox(p);
            eprintln!(
                "debug: boundary_outer0_bbox=({:.3},{:.3})..({:.3},{:.3}) verts={}",
                min_x,
                min_y,
                max_x,
                max_y,
                p.len()
            );
        }
    }

    // Block outside the board on every layer.
    for layer in 0..ir.layers {
        let ok = apply_boundary_mask_from_world_polygons_with_holes(
            &mut ir,
            tx,
            layer,
            1,
            &boundary_outers,
            &boundary_holes,
        );
        if !ok {
            eprintln!("apply_boundary_mask failed on layer {layer}");
            std::process::exit(1);
        }
    }

    // Respect DSN autoroute_settings layer activation: if a layer is inactive, block it entirely.
    let active_layers =
        active_layers_from_autoroute_settings(ir.layers, autoroute_settings.as_ref(), &model);
    for (layer, is_active) in active_layers.iter().copied().enumerate() {
        if !is_active && layer < ir.layers {
            let base = layer * ir.width * ir.height;
            let end = base + ir.width * ir.height;
            for v in &mut ir.occ[base..end] {
                *v = 1;
            }
        }
    }

    // Debug: check whether endpoints are inside the cleared boundary, before stamping anything else.
    if debug {
        let start_ref = net.pins[0].as_str();
        let goal_ref = net.pins[1].as_str();
        if let (Some(spin), Some(gpin)) = (model.pins.get(start_ref), model.pins.get(goal_ref)) {
            if let (Some(sp), Some(gp)) = (tx.world_to_grid(spin.x, spin.y), tx.world_to_grid(gpin.x, gpin.y))
            {
                let sl = preferred_pin_layer(&model, start_ref, ir.layers, &active_layers);
                let gl = preferred_pin_layer(&model, goal_ref, ir.layers, &active_layers);
                let s_occ = ir.get_occ(sl, sp.x, sp.y);
                let g_occ = ir.get_occ(gl, gp.x, gp.y);
                eprintln!(
                    "debug: after_boundary start=({},{},{}) occ={} goal=({},{},{}) occ={}",
                    sl, sp.x, sp.y, s_occ, gl, gp.x, gp.y, g_occ
                );
            }
        }
    }

    let net_name_to_id = build_net_name_to_id_sorted(&model);
    let Some(&net_id) = net_name_to_id.get(net.name.as_str()) else {
        eprintln!("No net id for {}", net.name);
        std::process::exit(1);
    };
    stamp_pins_as_occ_by_net(&mut ir, tx, &model, 1, default_clearance_world, &net_name_to_id);
    if debug {
        let start_ref = net.pins[0].as_str();
        let goal_ref = net.pins[1].as_str();
        if let (Some(spin), Some(gpin)) = (model.pins.get(start_ref), model.pins.get(goal_ref)) {
            if let (Some(sp), Some(gp)) = (tx.world_to_grid(spin.x, spin.y), tx.world_to_grid(gpin.x, gpin.y))
            {
                let sl = preferred_pin_layer(&model, start_ref, ir.layers, &active_layers);
                let gl = preferred_pin_layer(&model, goal_ref, ir.layers, &active_layers);
                let s_occ = ir.get_occ(sl, sp.x, sp.y);
                let g_occ = ir.get_occ(gl, gp.x, gp.y);
                eprintln!(
                    "debug: after_pins start=({},{},{}) occ={} goal=({},{},{}) occ={}",
                    sl, sp.x, sp.y, s_occ, gl, gp.x, gp.y, g_occ
                );
            }
        }
    }
    stamp_wiring_as_occ_by_padstack_layers(&mut ir, tx, &model, &wiring, 1, default_clearance_world, &net_name_to_id);
    if debug {
        let start_ref = net.pins[0].as_str();
        let goal_ref = net.pins[1].as_str();
        if let (Some(spin), Some(gpin)) = (model.pins.get(start_ref), model.pins.get(goal_ref)) {
            if let (Some(sp), Some(gp)) = (tx.world_to_grid(spin.x, spin.y), tx.world_to_grid(gpin.x, gpin.y))
            {
                let sl = preferred_pin_layer(&model, start_ref, ir.layers, &active_layers);
                let gl = preferred_pin_layer(&model, goal_ref, ir.layers, &active_layers);
                let s_occ = ir.get_occ(sl, sp.x, sp.y);
                let g_occ = ir.get_occ(gl, gp.x, gp.y);
                eprintln!(
                    "debug: after_wiring start=({},{},{}) occ={} goal=({},{},{}) occ={}",
                    sl, sp.x, sp.y, s_occ, gl, gp.x, gp.y, g_occ
                );
            }
        }
    }

    if keepouts_requested {
        stamp_keepouts_as_occ_and_via_forbidden(&mut ir, tx, &model, 1);
        if keepouts_auto_fallback && !ir_has_any_free_cell(&ir) {
            eprintln!("warn: keepouts block all free cells; retrying with keepouts=none");
            let (mut ir2, tx2) = build_empty_ir_from_summary(&summary, pitch).unwrap_or_else(|| {
                eprintln!("build_empty_ir_from_summary failed (missing bbox or invalid pitch)");
                std::process::exit(1);
            });
            for layer in 0..ir2.layers {
                let ok = apply_boundary_mask_from_world_polygons_with_holes(
                    &mut ir2,
                    tx2,
                    layer,
                    1,
                    &boundary_outers,
                    &boundary_holes,
                );
                if !ok {
                    eprintln!("apply_boundary_mask failed on layer {layer}");
                    std::process::exit(1);
                }
            }
            stamp_pins_as_occ_by_net(&mut ir2, tx2, &model, 1, default_clearance_world, &net_name_to_id);
            stamp_wiring_as_occ_by_padstack_layers(&mut ir2, tx2, &model, &wiring, 1, default_clearance_world, &net_name_to_id);
            ir = ir2;
        }
    }
    if debug {
        let start_ref = net.pins[0].as_str();
        let goal_ref = net.pins[1].as_str();
        // Quick sanity stats: how much free space remains for this net on the start layer.
        if let (Some(spin), Some(gpin)) = (model.pins.get(start_ref), model.pins.get(goal_ref)) {
            if let (Some(sp), Some(gp)) = (tx.world_to_grid(spin.x, spin.y), tx.world_to_grid(gpin.x, gpin.y))
            {
                let sl = preferred_pin_layer(&model, start_ref, ir.layers, &active_layers);
                let gl = preferred_pin_layer(&model, goal_ref, ir.layers, &active_layers);
                let s_occ = ir.get_occ(sl, sp.x, sp.y);
                let g_occ = ir.get_occ(gl, gp.x, gp.y);
                eprintln!(
                    "debug: after_keepouts start=({},{},{}) occ={} goal=({},{},{}) occ={}",
                    sl, sp.x, sp.y, s_occ, gl, gp.x, gp.y, g_occ
                );

                let n2 = ir.width * ir.height;
                let base = sl * n2;
                let mut free: usize = 0;
                let mut blocked: usize = 0;
                let mut own: usize = 0;
                let mut other: usize = 0;
                for &v in &ir.occ[base..base + n2] {
                    if v == 0 {
                        free += 1;
                    } else if v == 1 {
                        blocked += 1;
                    } else if v == net_id {
                        own += 1;
                    } else {
                        other += 1;
                    }
                }
                eprintln!(
                    "debug: occ_stats layer={} free={} blocked={} own={} other={}",
                    sl, free, blocked, own, other
                );
            }
        }
    }

    let cost_field = ir.build_cost_field_adjacent(1, 2, 8);
    if mst_mode {
        // Pick up to `limit` pins from the net that have definitions.
        let mut pin_refs: Vec<&str> = Vec::new();
        for p in &net.pins {
            if pin_refs.len() >= limit {
                break;
            }
            if model.pins.contains_key(p.as_str()) {
                pin_refs.push(p.as_str());
            }
        }
        if pin_refs.len() < 2 {
            eprintln!("Net {} has <2 resolvable pins", net.name);
            std::process::exit(1);
        }
        let mut pins: Vec<Point3> = Vec::new();
        for r in &pin_refs {
            let p = &model.pins[*r];
            if let Some(g) = tx.world_to_grid(p.x, p.y) {
                let layer = preferred_pin_layer(&model, r, ir.layers, &active_layers);
                let seed = Point3 { layer, x: g.x, y: g.y };
                let picked = find_nearest_free_cell_for_net(&ir, seed, 1, net_id, 24).unwrap_or(seed);
                pins.push(picked);
            }
        }

        let (layer_h_costs, layer_v_costs, layer_d_costs) =
            layer_dir_costs_from_autoroute_settings(ir.layers, autoroute_settings.as_ref(), &model);
        match route_net_mst_with_brush_and_layer_dir_costs(
            &mut ir,
            net_id,
            &pins,
            1,
            &cost_field,
            &layer_h_costs,
            &layer_v_costs,
            &layer_d_costs,
            via_cost,
            brush,
        ) {
            Err(e) => {
                eprintln!("MST routing failed: {e}");
                std::process::exit(3);
            }
            Ok(edges) => {
                println!("dsn: {}", PathBuf::from(&dsn_path).display());
                println!("net: {} (MST mode)", net.name);
                println!("pins_used: {}", pins.len());
                println!("edges_routed: {edges}");
                println!("grid: {}x{}x{} pitch={pitch}", ir.width, ir.height, ir.layers);
            }
        }
        std::process::exit(0);
    }

    // Default mode: route between first two pins.
    let start_ref = net.pins[0].as_str();
    let goal_ref = net.pins[1].as_str();

    let Some(spin) = model.pins.get(start_ref) else {
        eprintln!("Missing pin definition for {start_ref} (pins={})", model.pins.len());
        std::process::exit(1);
    };
    let Some(gpin) = model.pins.get(goal_ref) else {
        eprintln!("Missing pin definition for {goal_ref} (pins={})", model.pins.len());
        std::process::exit(1);
    };

    let sp = tx.world_to_grid(spin.x, spin.y).expect("start point");
    let gp = tx.world_to_grid(gpin.x, gpin.y).expect("goal point");

    let start_layer = preferred_pin_layer(&model, start_ref, ir.layers, &active_layers);
    let goal_layer = preferred_pin_layer(&model, goal_ref, ir.layers, &active_layers);
    let start = Point3 { layer: start_layer, x: sp.x, y: sp.y };
    let goal = Point3 { layer: goal_layer, x: gp.x, y: gp.y };

    let start = find_nearest_free_cell_for_net(&ir, start, 1, net_id, 24).unwrap_or(start);
    let goal = find_nearest_free_cell_for_net(&ir, goal, 1, net_id, 24).unwrap_or(goal);

    if std::env::var("PARDAL_ROUTE_DEBUG").is_ok() {
        let occ_s = ir.get_occ(start.layer, start.x, start.y);
        let occ_g = ir.get_occ(goal.layer, goal.x, goal.y);
        eprintln!("debug: net_id={net_id} start=({},{},{}) occ={} goal=({},{},{}) occ={}",
            start.layer, start.x, start.y, occ_s,
            goal.layer, goal.x, goal.y, occ_g
        );
    }

    let (layer_h_costs, layer_v_costs, layer_d_costs) =
        layer_dir_costs_from_autoroute_settings(ir.layers, autoroute_settings.as_ref(), &model);
    let route = route_dial_3d_for_net_with_layer_dir_costs(
        &ir,
        start,
        goal,
        1,
        &cost_field,
        &layer_h_costs,
        &layer_v_costs,
        &layer_d_costs,
        via_cost,
        net_id,
    );
    match route {
        None => {
            eprintln!("No route found for {} between {start_ref} and {goal_ref}", net.name);
            std::process::exit(3);
        }
        Some(p) => {
            let mut via_steps = 0usize;
            for w in p.points.windows(2) {
                if w[0].layer != w[1].layer {
                    via_steps += 1;
                }
            }
            println!("dsn: {}", PathBuf::from(&dsn_path).display());
            println!("net: {}", net.name);
            println!("pins: {start_ref} -> {goal_ref}");
            println!("grid: {}x{}x{} pitch={pitch}", ir.width, ir.height, ir.layers);
            println!("path_points: {}", p.points.len());
            println!("via_steps: {via_steps}");
        }
    }
}

fn polygon_area_abs(poly: &[(f64, f64)]) -> f64 {
    if poly.len() < 3 {
        return 0.0;
    }
    let mut s: f64 = 0.0;
    for i in 0..poly.len() {
        let (x0, y0) = poly[i];
        let (x1, y1) = poly[(i + 1) % poly.len()];
        s += x0 * y1 - x1 * y0;
    }
    (s * 0.5).abs()
}

fn bbox(poly: &[(f64, f64)]) -> (f64, f64, f64, f64) {
    let mut min_x = f64::INFINITY;
    let mut min_y = f64::INFINITY;
    let mut max_x = f64::NEG_INFINITY;
    let mut max_y = f64::NEG_INFINITY;
    for &(x, y) in poly {
        min_x = min_x.min(x);
        min_y = min_y.min(y);
        max_x = max_x.max(x);
        max_y = max_y.max(y);
    }
    (min_x, min_y, max_x, max_y)
}

fn point_on_segment(p: (f64, f64), a: (f64, f64), b: (f64, f64)) -> bool {
    let (px, py) = p;
    let (ax, ay) = a;
    let (bx, by) = b;
    let cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax);
    if cross.abs() > 1e-9 {
        return false;
    }
    let min_x = ax.min(bx) - 1e-9;
    let max_x = ax.max(bx) + 1e-9;
    let min_y = ay.min(by) - 1e-9;
    let max_y = ay.max(by) + 1e-9;
    px >= min_x && px <= max_x && py >= min_y && py <= max_y
}

fn point_in_polygon_or_on_edge(p: (f64, f64), poly: &[(f64, f64)]) -> bool {
    if poly.len() < 3 {
        return false;
    }
    for i in 0..poly.len() {
        let a = poly[i];
        let b = poly[(i + 1) % poly.len()];
        if point_on_segment(p, a, b) {
            return true;
        }
    }
    let (px, py) = p;
    let mut inside = false;
    let mut j = poly.len() - 1;
    for i in 0..poly.len() {
        let (xi, yi) = poly[i];
        let (xj, yj) = poly[j];
        let intersects = (yi > py) != (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi;
        if intersects {
            inside = !inside;
        }
        j = i;
    }
    inside
}

fn normalize_polygon(mut poly: Vec<(f64, f64)>) -> Option<Vec<(f64, f64)>> {
    if poly.len() < 3 {
        return None;
    }
    poly.dedup();
    if poly.len() >= 2 && poly.first().copied() == poly.last().copied() {
        poly.pop();
    }
    (poly.len() >= 3).then_some(poly)
}

fn select_outers_and_holes(polys: Vec<Vec<(f64, f64)>>) -> (Vec<Vec<(f64, f64)>>, Vec<Vec<(f64, f64)>>) {
    let polys: Vec<Vec<(f64, f64)>> = polys.into_iter().filter_map(normalize_polygon).collect();
    if polys.is_empty() {
        return (Vec::new(), Vec::new());
    }

    // Deduplicate by bbox+area (rect+path duplicates are common).
    #[derive(Clone)]
    struct PolyMeta {
        poly: Vec<(f64, f64)>,
        bbox: (f64, f64, f64, f64),
        area: f64,
    }

    let mut metas: Vec<PolyMeta> = polys
        .into_iter()
        .map(|p| {
            let bb = bbox(&p);
            let area = polygon_area_abs(&p).max(1e-12);
            PolyMeta { poly: p, bbox: bb, area }
        })
        .collect();
    metas.sort_by(|a, b| b.area.total_cmp(&a.area));

    let mut deduped: Vec<PolyMeta> = Vec::new();
    'outer: for m in metas {
        for d in &deduped {
            let bbox_same = (m.bbox.0 - d.bbox.0).abs() < 1e-9
                && (m.bbox.1 - d.bbox.1).abs() < 1e-9
                && (m.bbox.2 - d.bbox.2).abs() < 1e-9
                && (m.bbox.3 - d.bbox.3).abs() < 1e-9;
            if !bbox_same {
                continue;
            }
            let rel = (m.area - d.area).abs() / d.area.max(1e-9);
            if rel <= 1e-4 {
                continue 'outer;
            }
        }
        deduped.push(m);
    }

    // Classify:
    // - A polygon inside any already-selected outer is usually a hole (cutout).
    // - However, DSNs often include a `(rect pcb ...)` plus a slightly inset `(polygon ...)` that
    //   represents the same outline more precisely. Treat "nearly identical" contained polygons
    //   as a refinement and prefer the more detailed boundary instead of marking it as a hole.
    let mut outers: Vec<PolyMeta> = Vec::new();
    let mut holes: Vec<Vec<(f64, f64)>> = Vec::new();
    for m in deduped {
        let mut refined = false;
        for outer in &mut outers {
            if !point_in_polygon_or_on_edge(m.poly[0], &outer.poly) {
                continue;
            }

            // Heuristic: large contained polygons are usually an alternative representation of the
            // same boundary (e.g. a rounded polygon inside a coarse rectangle), not a cutout.
            //
            // True cutouts (holes) tend to be much smaller than the outer boundary.
            let area_ratio = (m.area / outer.area.max(1e-9)).clamp(0.0, 1.0);
            if area_ratio >= 0.5 {
                if m.poly.len() >= outer.poly.len() {
                    *outer = m.clone();
                }
                refined = true;
            } else {
                holes.push(m.poly.clone());
                refined = true;
            }
            break;
        }
        if !refined {
            outers.push(m);
        }
    }

    (outers.into_iter().map(|m| m.poly).collect(), holes)
}
