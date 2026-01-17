use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Instant;

use pardal_router_core::clearance_nm::ClearanceResolverNm;
use pardal_router_core::connectivity_nm::nets_with_disconnected_terminals_with_areas;
use pardal_router_core::drc_nm::{
    drc_check_areas_var_clearance_indexed, drc_check_boundary_nm, drc_check_keepouts_indexed,
    drc_check_var_clearance_indexed,
};
use pardal_router_core::dsn::{
    extract_boundary_polygons_from_str, extract_model_from_str, extract_net_rules_from_str, extract_rules_clearances_from_str,
    extract_wiring_from_str, summarize_dsn,
};
use pardal_router_core::dsn_to_nm::{
    dsn_coord_to_nm, dsn_to_board_nm_with_net_rules, summary_unit_scale_nm,
};
use pardal_router_core::geom_nm::PointNm;
use pardal_router_core::board_nm::BoundaryNm;
use serde::Serialize;

fn usage() -> ! {
    eprintln!(
        "Usage:\n  pardal_dsn_check <path.dsn> [--rules path.rules] [--drc MODE] [--json]\n\n\
Prints a quick diagnostic summary from a Specctra DSN:\n\
 - parsed net classes + default rule\n\
 - DSN wiring → nm board model counts\n\
 - skeleton DRC counts (short/clearance)\n\
 - disconnected nets (terminal components > 1)\n"
    );
    eprintln!("\nDRC MODE: all|copper|keepout|boundary|areas|none (default: all)\n");
    std::process::exit(2);
}

#[derive(Debug, Clone, Serialize)]
struct DrcSummary {
    clearance_nm: i64,
    copper_violations: usize,
    shorts: usize,
    clearance: usize,
    keepout_violations: usize,
    boundary_violations: usize,
    area_violations: usize,
}

#[derive(Debug, Clone, Serialize)]
struct TimingMs {
    read: u128,
    summarize: u128,
    extract_model: u128,
    extract_wiring: u128,
    extract_net_rules: u128,
    to_board_nm: u128,
    drc_copper: u128,
    drc_keepout: u128,
    drc_boundary: u128,
    drc_areas: u128,
    connectivity: u128,
}

#[derive(Debug, Clone, Serialize)]
struct Report {
    dsn: String,
    summary_layers: usize,
    summary_nets: usize,
    summary_components: usize,
    summary_pins: usize,
    rules_default_width: Option<f64>,
    rules_default_clearance: Option<f64>,
    rules_classes: usize,
    wiring_wires: usize,
    wiring_vias: usize,
    board_tracks: usize,
    board_vias: usize,
    board_terminals: usize,
    board_areas: usize,
    keepouts: usize,
    drc: DrcSummary,
    disconnected_nets: Vec<String>,
    timing_ms: TimingMs,
}

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        usage();
    }
    let dsn_path = args.remove(0);
    let mut json = false;
    let mut rules_path: Option<String> = None;
    let mut drc_mode: String = "all".to_string();

    let mut i = 0usize;
    while i < args.len() {
        match args[i].as_str() {
            "--json" => {
                json = true;
                i += 1;
            }
            "--rules" => {
                let Some(p) = args.get(i + 1) else { usage() };
                rules_path = Some(p.clone());
                i += 2;
            }
            "--drc" => {
                let Some(m) = args.get(i + 1) else { usage() };
                drc_mode = m.clone();
                i += 2;
            }
            _ => usage(),
        }
    }
    if !matches!(
        drc_mode.to_ascii_lowercase().as_str(),
        "all" | "copper" | "keepout" | "boundary" | "areas" | "none"
    ) {
        usage();
    }

    let t0 = Instant::now();
    let bytes = std::fs::read(&dsn_path).unwrap_or_else(|e| {
        eprintln!("Failed to read {dsn_path}: {e}");
        std::process::exit(1);
    });
    let t_read = t0.elapsed();
    let dsn_cow = String::from_utf8_lossy(&bytes);
    let dsn: &str = &dsn_cow;

    let t1 = Instant::now();
    let summary = summarize_dsn(dsn).unwrap_or_else(|e| {
        eprintln!("summarize_dsn failed: {e}");
        std::process::exit(1);
    });
    let t_summarize = t1.elapsed();

    let t2 = Instant::now();
    let model = extract_model_from_str(dsn).unwrap_or_else(|e| {
        eprintln!("extract_model_from_str failed: {e}");
        std::process::exit(1);
    });
    let t_model = t2.elapsed();

    let t3 = Instant::now();
    let wiring = extract_wiring_from_str(dsn).unwrap_or_else(|e| {
        eprintln!("extract_wiring_from_str failed: {e}");
        std::process::exit(1);
    });
    let t_wiring = t3.elapsed();

    let t4 = Instant::now();
    let rules = extract_net_rules_from_str(dsn).unwrap_or_else(|e| {
        eprintln!("extract_net_rules_from_str failed: {e}");
        std::process::exit(1);
    });
    let t_rules = t4.elapsed();

    let extra_rules = rules_path.as_deref().map(|p| {
        std::fs::read_to_string(p).unwrap_or_else(|e| {
            eprintln!("Failed to read {p}: {e}");
            std::process::exit(1);
        })
    });
    let rules_clearances = extra_rules.as_deref().map(|txt| {
        extract_rules_clearances_from_str(txt).unwrap_or_else(|e| {
            eprintln!("extract_rules_clearances_from_str failed: {e}");
            std::process::exit(1);
        })
    });

    let unit_scale_nm = summary_unit_scale_nm(&summary).unwrap_or(1_000_000);

    let t5 = Instant::now();
    let mut board = dsn_to_board_nm_with_net_rules(&summary, &model, &wiring, Some(&rules)).unwrap_or_else(|e| {
        eprintln!("dsn_to_board_nm failed: {e}");
        std::process::exit(1);
    });
    let t_board = t5.elapsed();

    board.boundary = extract_boundary_polygons_from_str(dsn)
        .ok()
        .and_then(|polys| {
            let mut nm_polys: Vec<Vec<PointNm>> = Vec::new();
            for poly in polys {
                let mut out: Vec<PointNm> = Vec::new();
                for (x, y) in poly {
                    let x_nm = dsn_coord_to_nm(x, unit_scale_nm).ok()?;
                    let y_nm = dsn_coord_to_nm(y, unit_scale_nm).ok()?;
                    let p = PointNm::new(x_nm, y_nm);
                    if out.last().copied() != Some(p) {
                        out.push(p);
                    }
                }
                if out.len() >= 2 && out.first().copied() == out.last().copied() {
                    out.pop();
                }
                if out.len() >= 3 {
                    nm_polys.push(out);
                }
            }
            BoundaryNm::from_polygons(nm_polys)
        });

    let mut id_to_name: HashMap<u32, String> = HashMap::new();
    for (name, id) in &board.net_name_to_id {
        id_to_name.insert(*id, name.clone());
    }

    let resolver = ClearanceResolverNm::from_dsn_and_optional_rules(
        &summary,
        &board,
        &rules,
        rules_clearances.as_ref(),
    )
    .unwrap_or_else(|e| {
        eprintln!("failed to build clearance resolver: {e}");
        std::process::exit(1);
    });

    let do_copper = drc_mode.eq_ignore_ascii_case("all") || drc_mode.eq_ignore_ascii_case("copper");
    let do_keepout = drc_mode.eq_ignore_ascii_case("all") || drc_mode.eq_ignore_ascii_case("keepout");
    let do_boundary = drc_mode.eq_ignore_ascii_case("all") || drc_mode.eq_ignore_ascii_case("boundary");
    let do_areas = drc_mode.eq_ignore_ascii_case("areas");
    let do_conn = drc_mode.eq_ignore_ascii_case("all");

    let t6 = Instant::now();
    let copper_violations = if do_copper {
        drc_check_var_clearance_indexed(
            &board.tracks,
            &board.vias,
            &board.terminals,
            |ka, na, ca, kb, nb, cb| resolver.clearance_for(ka, na, ca, kb, nb, cb, &board),
            resolver.max_clearance(),
        )
    } else {
        Vec::new()
    };
    let t_drc_copper = if do_copper { t6.elapsed() } else { std::time::Duration::from_millis(0) };

    let mut shorts = 0usize;
    let mut clearance_viol = 0usize;
    for v in &copper_violations {
        match v.kind {
            pardal_router_core::drc_nm::DrcViolationKind::Short => shorts += 1,
            pardal_router_core::drc_nm::DrcViolationKind::Clearance => clearance_viol += 1,
            pardal_router_core::drc_nm::DrcViolationKind::Keepout
            | pardal_router_core::drc_nm::DrcViolationKind::Boundary => {}
        }
    }

    let t7 = Instant::now();
    let keepout_violations = if do_keepout {
        drc_check_keepouts_indexed(&board.tracks, &board.vias, &board.terminals, &board.keepouts)
    } else {
        Vec::new()
    };
    let t_drc_keepout = if do_keepout { t7.elapsed() } else { std::time::Duration::from_millis(0) };

    let t8 = Instant::now();
    let boundary_violations = if do_boundary {
        board
            .boundary
            .as_ref()
            .map(|boundary| {
                drc_check_boundary_nm(
                    &board.tracks,
                    &board.vias,
                    &board.terminals,
                    &board.keepouts,
                    boundary,
                    resolver.boundary_clearance(),
                )
            })
            .unwrap_or_default()
    } else {
        Vec::new()
    };
    let t_drc_boundary = if do_boundary { t8.elapsed() } else { std::time::Duration::from_millis(0) };

    let t9 = Instant::now();
    let area_violations = if do_areas {
        drc_check_areas_var_clearance_indexed(
            &board.tracks,
            &board.vias,
            &board.terminals,
            &board.areas,
            |ka, na, ca, kb, nb, cb| resolver.clearance_for(ka, na, ca, kb, nb, cb, &board),
            resolver.max_clearance(),
        )
    } else {
        Vec::new()
    };
    let t_drc_areas = if do_areas { t9.elapsed() } else { std::time::Duration::from_millis(0) };

    let t10 = Instant::now();
    let disconnected = if do_conn {
        nets_with_disconnected_terminals_with_areas(
            &board.tracks,
            &board.vias,
            &board.terminals,
            &board.areas,
            board.layers,
        )
    } else {
        Vec::new()
    };
    let t_conn = if do_conn { t10.elapsed() } else { std::time::Duration::from_millis(0) };

    let mut disconnected_names: Vec<String> = Vec::new();
    for id in &disconnected {
        disconnected_names.push(
            id_to_name
                .get(id)
                .cloned()
                .unwrap_or_else(|| format!("net_id={id}")),
        );
    }
    disconnected_names.sort();

    let report = Report {
        dsn: PathBuf::from(&dsn_path).display().to_string(),
        summary_layers: summary.layer_count,
        summary_nets: summary.net_count,
        summary_components: summary.component_count,
        summary_pins: summary.pin_count,
        rules_default_width: rules.default_rule.width,
        rules_default_clearance: rules.default_rule.clearance,
        rules_classes: rules.classes.len(),
        wiring_wires: wiring.wires.len(),
        wiring_vias: wiring.vias.len(),
        board_tracks: board.tracks.len(),
        board_vias: board.vias.len(),
        board_terminals: board.terminals.len(),
        board_areas: board.areas.len(),
        keepouts: board.keepouts.len(),
        drc: DrcSummary {
            clearance_nm: resolver.max_clearance().0,
            copper_violations: copper_violations.len(),
            shorts,
            clearance: clearance_viol,
            keepout_violations: keepout_violations.len(),
            boundary_violations: boundary_violations.len(),
            area_violations: area_violations.len(),
        },
        disconnected_nets: disconnected_names,
        timing_ms: TimingMs {
            read: t_read.as_millis(),
            summarize: t_summarize.as_millis(),
            extract_model: t_model.as_millis(),
            extract_wiring: t_wiring.as_millis(),
            extract_net_rules: t_rules.as_millis(),
            to_board_nm: t_board.as_millis(),
            drc_copper: t_drc_copper.as_millis(),
            drc_keepout: t_drc_keepout.as_millis(),
            drc_boundary: t_drc_boundary.as_millis(),
            drc_areas: t_drc_areas.as_millis(),
            connectivity: t_conn.as_millis(),
        },
    };

    if json {
        println!("{}", serde_json::to_string_pretty(&report).expect("serialize JSON"));
        return;
    }

    println!("dsn: {}", report.dsn);
    println!(
        "summary: layers={} nets={} components={} pins={}",
        report.summary_layers, report.summary_nets, report.summary_components, report.summary_pins
    );
    println!(
        "rules: default_width={:?} default_clearance={:?} classes={}",
        report.rules_default_width, report.rules_default_clearance, report.rules_classes
    );
    println!("wiring: wires={} vias={}", report.wiring_wires, report.wiring_vias);
    println!(
        "board_nm: tracks={} vias={} terminals={} areas={}",
        report.board_tracks, report.board_vias, report.board_terminals, report.board_areas
    );
    println!("keepouts: {}", report.keepouts);
    println!(
        "drc_nm: clearance_nm={} copper_violations={} (shorts={} clearance={}) keepout_violations={} boundary_violations={} area_violations={}",
        report.drc.clearance_nm,
        report.drc.copper_violations,
        report.drc.shorts,
        report.drc.clearance,
        report.drc.keepout_violations,
        report.drc.boundary_violations,
        report.drc.area_violations
    );
    println!("disconnected_nets: {}", report.disconnected_nets.len());
    if !report.disconnected_nets.is_empty() {
        println!("first_disconnected:");
        for name in report.disconnected_nets.iter().take(20) {
            println!("  {name}");
        }
    }
    println!(
        "timing_ms: read={} summarize={} model={} wiring={} rules={} to_board_nm={} drc_copper={} drc_keepout={} drc_boundary={} drc_areas={} connectivity={}",
        report.timing_ms.read,
        report.timing_ms.summarize,
        report.timing_ms.extract_model,
        report.timing_ms.extract_wiring,
        report.timing_ms.extract_net_rules,
        report.timing_ms.to_board_nm,
        report.timing_ms.drc_copper,
        report.timing_ms.drc_keepout,
        report.timing_ms.drc_boundary,
        report.timing_ms.drc_areas,
        report.timing_ms.connectivity,
    );
}
