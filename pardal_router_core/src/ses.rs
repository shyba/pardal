use std::collections::HashMap;

use crate::drc_nm::{TrackNm, ViaNm};
use crate::dsn::{DsnModel, DsnSummary, PadShapeDef};
use crate::dsn_to_nm::summary_unit_scale_nm;

fn escape_ident(s: &str) -> String {
    // Minimal escape: use quoted string if it contains whitespace or parentheses.
    // Freerouting uses a more complete IdentifierType; this is enough for smoke tests.
    if s.chars().any(|c| c.is_whitespace() || c == '(' || c == ')') {
        format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
    } else {
        s.to_string()
    }
}

fn layer_name_for_index(model: &DsnModel, idx: usize) -> Option<String> {
    // Invert `layer_name_to_index` by searching. Small N; OK for now.
    model
        .layer_name_to_index
        .iter()
        .find_map(|(k, &v)| if v == idx { Some(k.clone()) } else { None })
}

/// Minimal Specctra session (SES) writer.
///
/// Goal: export routed wires/vias so Freerouting can load them alongside the base DSN.
/// This is intentionally a small subset of Freerouting's `SpecctraSesFileWriter`:
/// - `session` scope
/// - `(base_design ...)`
/// - `(routes (resolution ...) (parser ...) (network_out ...))`
///
/// It does NOT currently emit:
/// - placement, was_is, library_out, conduction areas
/// - fixed-state/type annotations
pub fn write_ses_minimal(
    session_name: &str,
    base_design_name: &str,
    summary: &DsnSummary,
    model: &DsnModel,
    tracks: &[TrackNm],
    vias: &[ViaNm],
    net_id_to_name: &HashMap<u32, String>,
) -> String {
    let unit = summary
        .resolution_unit
        .as_deref()
        .or(summary.unit.as_deref())
        .unwrap_or("mm");
    let res = summary.resolution_value.unwrap_or(1);
    let unit_scale_nm = summary_unit_scale_nm(summary).unwrap_or(1_000_000);

    let nm_to_ses_i64 = |nm: i64| -> i64 {
        // session coordinates are integers; interpret as `round(coord_in_unit * resolution_value)`.
        // coord_in_unit = nm / unit_scale_nm
        // => ses = round(nm * res / unit_scale_nm)
        ((nm as f64) * (res as f64) / (unit_scale_nm as f64)).round() as i64
    };

    let mut out = String::new();
    out.push_str("(session ");
    out.push_str(&escape_ident(session_name));
    out.push('\n');

    out.push_str("  (base_design ");
    out.push_str(&escape_ident(base_design_name));
    out.push_str(")\n");

    out.push_str("  (routes\n");
    out.push_str(&format!("    (resolution {} {})\n", unit, res));
    out.push_str("    (parser (string_quote \") (space_in_quoted_tokens on))\n");

    // library_out: emit via padstacks used in this session.
    let mut via_padstacks: Vec<String> = vias
        .iter()
        .filter_map(|v| v.padstack.clone())
        .collect();
    via_padstacks.sort();
    via_padstacks.dedup();
    if !via_padstacks.is_empty() {
        out.push_str("    (library_out\n");
        for ps in &via_padstacks {
            out.push_str("      (padstack ");
            out.push_str(&escape_ident(ps));
            out.push('\n');

            let dsn_coord_to_ses = |v: f64| -> i64 {
                let nm = (v * (unit_scale_nm as f64)).round() as i64;
                nm_to_ses_i64(nm)
            };

            let mut wrote_any = false;
            if let Some(shapes) = model.padstack_shapes.get(ps) {
                for shape in shapes {
                    match shape {
                        PadShapeDef::Circle { layer, diameter, x, y } => {
                            out.push_str("        (shape (circle ");
                            out.push_str(&escape_ident(layer));
                            out.push(' ');
                            out.push_str(&format!(
                                "{} {} {}))\n",
                                dsn_coord_to_ses(*diameter),
                                dsn_coord_to_ses(*x),
                                dsn_coord_to_ses(*y)
                            ));
                            wrote_any = true;
                        }
                        PadShapeDef::Polygon { layer, points } => {
                            if points.len() < 3 {
                                continue;
                            }
                            out.push_str("        (shape (polygon ");
                            out.push_str(&escape_ident(layer));
                            out.push_str(" 0");
                            for (x, y) in points {
                                out.push(' ');
                                out.push_str(&format!("{} {}", dsn_coord_to_ses(*x), dsn_coord_to_ses(*y)));
                            }
                            out.push_str("))\n");
                            wrote_any = true;
                        }
                        PadShapeDef::Path { layer, width, points } => {
                            if points.len() < 2 {
                                continue;
                            }
                            out.push_str("        (shape (path ");
                            out.push_str(&escape_ident(layer));
                            out.push(' ');
                            out.push_str(&format!("{}", dsn_coord_to_ses(*width)));
                            for (x, y) in points {
                                out.push(' ');
                                out.push_str(&format!("{} {}", dsn_coord_to_ses(*x), dsn_coord_to_ses(*y)));
                            }
                            out.push_str("))\n");
                            wrote_any = true;
                        }
                    }
                }
            }

            if !wrote_any {
                let Some(&r_world) = model.padstacks.get(ps) else {
                    out.push_str("      )\n");
                    continue;
                };
                let diam = dsn_coord_to_ses(r_world) * 2;

                let layers: Vec<usize> = match model.padstack_layers.get(ps) {
                    Some(ls) if !ls.is_empty() => ls.clone(),
                    _ => Vec::new(),
                };
                for layer_idx in layers {
                    let layer = layer_name_for_index(model, layer_idx).unwrap_or_else(|| (layer_idx + 1).to_string());
                    out.push_str("        (shape (circle ");
                    out.push_str(&escape_ident(&layer));
                    out.push(' ');
                    out.push_str(&format!("{} 0 0))\n", diam));
                    wrote_any = true;
                }
                if !wrote_any {
                    out.push_str("        (shape (circle 1 ");
                    out.push_str(&format!("{} 0 0))\n", diam));
                }
            }
            out.push_str("      )\n");
        }
        out.push_str("    )\n");
    }

    out.push_str("    (network_out\n");

    // Group items by net_id.
    let mut wires_by_net: HashMap<u32, Vec<&TrackNm>> = HashMap::new();
    for t in tracks {
        wires_by_net.entry(t.net_id).or_default().push(t);
    }
    let mut vias_by_net: HashMap<u32, Vec<&ViaNm>> = HashMap::new();
    for v in vias {
        vias_by_net.entry(v.net_id).or_default().push(v);
    }

    let mut net_ids: Vec<u32> = wires_by_net
        .keys()
        .chain(vias_by_net.keys())
        .copied()
        .collect();
    net_ids.sort_unstable();
    net_ids.dedup();

    for net_id in net_ids {
        let Some(net_name) = net_id_to_name.get(&net_id) else {
            continue;
        };
        out.push_str("      (net ");
        out.push_str(&escape_ident(net_name));
        out.push('\n');

        if let Some(ws) = wires_by_net.get(&net_id) {
            for w in ws {
                let layer = layer_name_for_index(model, w.layer).unwrap_or_else(|| (w.layer + 1).to_string());
                // DSN width is full width. TrackNm stores half-width.
                let width = nm_to_ses_i64(w.r.0) * 2;
                out.push_str("        (wire (path ");
                out.push_str(&escape_ident(&layer));
                out.push(' ');
                out.push_str(&format!("{}", width));
                out.push_str(&format!(
                    " {} {} {} {})",
                    nm_to_ses_i64(w.seg.a.x.0),
                    nm_to_ses_i64(w.seg.a.y.0),
                    nm_to_ses_i64(w.seg.b.x.0),
                    nm_to_ses_i64(w.seg.b.y.0)
                ));
                out.push_str("))\n");
            }
        }

        if let Some(vs) = vias_by_net.get(&net_id) {
            for v in vs {
                let padstack = v.padstack.as_deref().unwrap_or("via0");
                out.push_str("        (via ");
                out.push_str(&escape_ident(padstack));
                out.push(' ');
                out.push_str(&format!(
                    "{} {}",
                    nm_to_ses_i64(v.circle.center.x.0),
                    nm_to_ses_i64(v.circle.center.y.0)
                ));
                out.push_str(")\n");
            }
        }

        out.push_str("      )\n");
    }

    out.push_str("    )\n"); // network_out
    out.push_str("  )\n"); // routes
    out.push_str(")\n"); // session
    out
}
