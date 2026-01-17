use std::fmt;
use std::collections::HashMap;

mod wiring;
pub use wiring::*;
mod autoroute_settings;
pub use autoroute_settings::*;
mod net_rules;
pub use net_rules::*;
pub mod edit;
mod rules_clearances;
pub use rules_clearances::*;

#[derive(Debug, Clone, PartialEq)]
pub struct DsnSummary {
    pub pcb_name: String,
    pub unit: Option<String>,
    pub resolution_unit: Option<String>,
    pub resolution_value: Option<i64>,
    pub layer_count: usize,
    pub boundary_bbox: Option<BoundaryBbox>,
    pub net_count: usize,
    pub component_count: usize,
    pub pin_count: usize,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BoundaryBbox {
    pub min_x: f64,
    pub min_y: f64,
    pub max_x: f64,
    pub max_y: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PinDef {
    pub ref_name: String, // e.g. "u1-2406"
    pub padstack: String, // e.g. "p2391"
    pub pin_id: String,   // e.g. "2406"
    pub x: f64,
    pub y: f64,
    /// Absolute copper shapes for this pin (DSN units), after placement transforms.
    pub shapes: Vec<PadShapeDef>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetDef {
    pub name: String,
    pub pins: Vec<String>, // e.g. ["u1-2406", ...]
}

#[derive(Debug, Clone, PartialEq)]
pub struct ImagePinDef {
    pub padstack: String,
    pub pin_id: String,
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub enum PadShapeDef {
    /// Filled circle copper, expressed by diameter (DSN units) and center offset (DSN units).
    Circle {
        layer: String,
        diameter: f64,
        x: f64,
        y: f64,
    },
    /// Filled polygon copper, expressed by a sequence of vertices (DSN units).
    Polygon {
        layer: String,
        points: Vec<(f64, f64)>,
    },
    /// Stroked polyline copper, expressed by width (DSN units) and points (DSN units).
    Path {
        layer: String,
        width: f64,
        points: Vec<(f64, f64)>,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub enum KeepoutShapeDef {
    /// DSN circle-like keepout, expressed by diameter (DSN units) and center (DSN units).
    Circle {
        kind: KeepoutKind,
        layer: String,
        diameter: f64,
        x: f64,
        y: f64,
    },
    /// DSN polygon keepout, expressed by a sequence of vertices (DSN units).
    Polygon {
        kind: KeepoutKind,
        layer: String,
        points: Vec<(f64, f64)>,
    },
    /// DSN stroked path keepout, expressed by a width (DSN units) and points (DSN units).
    Path {
        kind: KeepoutKind,
        layer: String,
        width: f64,
        points: Vec<(f64, f64)>,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeepoutKind {
    /// Applies to wires, vias, and terminals.
    All,
    /// Applies only to wires/tracks.
    Wire,
    /// Applies only to vias.
    Via,
}

#[derive(Debug, Clone, PartialEq)]
pub enum PlaneShapeDef {
    /// Filled polygon copper, expressed by a sequence of vertices (DSN units).
    Polygon {
        layer: String,
        points: Vec<(f64, f64)>,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub struct PlaneDef {
    pub net: String,
    pub shapes: Vec<PlaneShapeDef>,
    pub windows: Vec<PlaneShapeDef>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct DsnModel {
    pub pins: HashMap<String, PinDef>,
    pub nets: HashMap<String, NetDef>,
    pub padstacks: HashMap<String, f64>, // radius in DSN coordinate units
    pub padstack_layers: HashMap<String, Vec<usize>>, // 0-based layer indices for which the padstack has copper
    /// Padstack copper shapes, relative to the pad origin (DSN units).
    pub padstack_shapes: HashMap<String, Vec<PadShapeDef>>,
    /// Optional per-pin clearance class overrides, usually defined inside `placement` -> `place` pin scopes.
    ///
    /// Keys are absolute pin refs like `U1-1`.
    pub pin_clearance_classes: HashMap<String, String>,
    pub images: HashMap<String, Vec<ImagePinDef>>, // footprint/image name -> relative pins
    pub image_keepouts: HashMap<String, Vec<KeepoutShapeDef>>, // footprint/image name -> relative keepouts
    pub keepouts: Vec<KeepoutShapeDef>, // absolute keepouts after placement transforms
    pub planes: Vec<PlaneDef>,          // conduction areas (typically poured copper)
    pub layer_name_to_index: HashMap<String, usize>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Token {
    LParen,
    RParen,
    Atom(String),
    Str(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TokenizeError {
    pub message: String,
    pub byte_offset: usize,
}

impl fmt::Display for TokenizeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} at byte {}", self.message, self.byte_offset)
    }
}

impl std::error::Error for TokenizeError {}

pub fn tokenize(input: &str) -> Result<Vec<Token>, TokenizeError> {
    let cleaned: std::borrow::Cow<'_, str> = if input.as_bytes().contains(&0) {
        // Some corpus inputs are UTF-16LE-ish (NUL-padded ASCII). Drop NULs to recover the text.
        std::borrow::Cow::Owned(input.chars().filter(|&c| c != '\0').collect())
    } else {
        std::borrow::Cow::Borrowed(input)
    };

    let bytes = cleaned.as_bytes();
    let mut tokens = Vec::new();
    let mut i = 0usize;

    while i < bytes.len() {
        let b = bytes[i];
        match b {
            b'(' => {
                tokens.push(Token::LParen);
                i += 1;
            }
            b')' => {
                tokens.push(Token::RParen);
                i += 1;
            }
            b'"' => {
                // DSN has constructs like `(string_quote ")` where `"` is a bare atom,
                // not a quoted string. Disambiguate by treating a `"` followed
                // immediately by whitespace or `)` as an atom token.
                if i + 1 < bytes.len() {
                    let next = bytes[i + 1];
                    if next.is_ascii_whitespace() || next == b')' {
                        tokens.push(Token::Atom("\"".to_string()));
                        i += 1;
                        continue;
                    }
                }
                // Double-quoted string
                i += 1;
                let start = i;
                let mut out: Vec<u8> = Vec::new();
                while i < bytes.len() {
                    match bytes[i] {
                        b'\\' => {
                            // Minimal escape handling: accept \" and \\ and \n \t \r
                            i += 1;
                            if i >= bytes.len() {
                                return Err(TokenizeError {
                                    message: "unterminated string escape".to_string(),
                                    byte_offset: i,
                                });
                            }
                            match bytes[i] {
                                b'"' => out.push(b'"'),
                                b'\\' => out.push(b'\\'),
                                b'n' => out.push(b'\n'),
                                b't' => out.push(b'\t'),
                                b'r' => out.push(b'\r'),
                                other => out.push(other),
                            }
                            i += 1;
                        }
                        b'"' => {
                            i += 1;
                            tokens.push(Token::Str(String::from_utf8_lossy(&out).into_owned()));
                            // FreeRouting sometimes concatenates quoted tokens with a dash without
                            // whitespace, e.g. `"default"-"class name"` or `"J3"-"D+"`. Treat the
                            // dash as a standalone atom so the next quoted token is parsed correctly.
                            if i + 1 < bytes.len() && bytes[i] == b'-' && bytes[i + 1] == b'"' {
                                tokens.push(Token::Atom("-".to_string()));
                                i += 1;
                            }
                            break;
                        }
                        other => {
                            out.push(other);
                            i += 1;
                        }
                    }
                }
                if i >= bytes.len() && !matches!(tokens.last(), Some(Token::Str(_))) {
                    return Err(TokenizeError {
                        message: "unterminated string".to_string(),
                        byte_offset: start,
                    });
                }
            }
            b';' => {
                // DSN sometimes uses `;` for comments, but it can also appear as a literal token
                // (e.g. KiCad can emit `(PN ;)`). Only treat it as a comment when it's the first
                // non-whitespace character on a line.
                let mut is_line_comment = true;
                let mut j = i;
                while j > 0 {
                    let prev = bytes[j - 1];
                    if prev == b'\n' {
                        break;
                    }
                    if !prev.is_ascii_whitespace() {
                        is_line_comment = false;
                        break;
                    }
                    j -= 1;
                }
                if is_line_comment {
                    while i < bytes.len() && bytes[i] != b'\n' {
                        i += 1;
                    }
                } else {
                    // Treat as an atom token.
                    tokens.push(Token::Atom(";".to_string()));
                    i += 1;
                }
            }
            b if b.is_ascii_whitespace() => {
                i += 1;
            }
            _ => {
                // Atom: read until whitespace or paren
                let start = i;
                while i < bytes.len() {
                    let c = bytes[i];
                    if c.is_ascii_whitespace() || c == b'(' || c == b')' {
                        break;
                    }
                    i += 1;
                }
                let atom = &cleaned[start..i];
                tokens.push(Token::Atom(atom.to_string()));
            }
        }
    }

    Ok(tokens)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParseError {
    pub message: String,
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for ParseError {}

/// Streaming summary extraction for Specctra/Electra DSN files.
///
/// This intentionally avoids building a full AST so we can handle large DSN
/// inputs with predictable memory use. It only extracts a small set of
/// structural facts needed for early TDD and corpus smoke tests.
pub fn summarize(tokens: &[Token]) -> Result<DsnSummary, ParseError> {
    let mut depth: i32 = 0;
    let mut list_head_stack: Vec<Option<String>> = Vec::new();

    let mut pcb_name: Option<String> = None;
    let mut unit: Option<String> = None;
    let mut resolution_unit: Option<String> = None;
    let mut resolution_value: Option<i64> = None;
    let mut layer_count: usize = 0;
    let mut boundary_bbox: Option<BoundaryBbox> = None;
    let mut net_count: usize = 0;
    let mut component_count: usize = 0;
    let mut pin_count: usize = 0;

    // Argument expectations, guarded by the list depth they apply to.
    let mut expect_pcb_name_at: Option<i32> = None;
    let mut expect_unit_at: Option<i32> = None;
    let mut expect_resolution_unit_at: Option<i32> = None;
    let mut expect_resolution_value_at: Option<i32> = None;
    let mut in_boundary_at: Option<i32> = None;
    let mut in_boundary_path_at: Option<i32> = None;
    let mut boundary_numbers: Vec<f64> = Vec::new();
    let mut in_boundary_rect_at: Option<i32> = None;
    let mut boundary_rect_numbers: Vec<f64> = Vec::new();
    let mut in_boundary_polygon_at: Option<i32> = None;
    let mut boundary_polygon_numbers: Vec<f64> = Vec::new();
    let mut boundary_polygon_skip_first_number: bool = false;
    let mut in_network_at: Option<i32> = None;
    let mut in_placement_at: Option<i32> = None;
    let mut in_library_at: Option<i32> = None;
    let mut in_image_at: Option<i32> = None;

    let mut i = 0usize;
    while i < tokens.len() {
        let tok = &tokens[i];
        match tok {
            Token::LParen => {
                depth += 1;
                list_head_stack.push(None);
                i += 1;
            }
            Token::RParen => {
                if depth <= 0 {
                    return Err(ParseError {
                        message: "unexpected ')'".to_string(),
                    });
                }
                depth -= 1;
                list_head_stack.pop();
                // Drop any pending expectations that were scoped to a list we just closed.
                if expect_pcb_name_at.is_some_and(|d| d > depth) {
                    expect_pcb_name_at = None;
                }
                if expect_unit_at.is_some_and(|d| d > depth) {
                    expect_unit_at = None;
                }
                if expect_resolution_unit_at.is_some_and(|d| d > depth) {
                    expect_resolution_unit_at = None;
                }
                if expect_resolution_value_at.is_some_and(|d| d > depth) {
                    expect_resolution_value_at = None;
                }
                i += 1;
            }
            Token::Atom(s) => {
                // If we're expecting a value, consume it first.
                if expect_pcb_name_at == Some(depth) && pcb_name.is_none() {
                    pcb_name = Some(s.clone());
                    expect_pcb_name_at = None;
                    i += 1;
                    continue;
                }
                if expect_unit_at == Some(depth) {
                    unit = Some(s.clone());
                    expect_unit_at = None;
                    i += 1;
                    continue;
                }
                if expect_resolution_unit_at == Some(depth) {
                    resolution_unit = Some(s.clone());
                    expect_resolution_unit_at = None;
                    expect_resolution_value_at = Some(depth);
                    i += 1;
                    continue;
                }
                if expect_resolution_value_at == Some(depth) {
                    if let Ok(v) = s.parse::<i64>() {
                        resolution_value = Some(v);
                    }
                    expect_resolution_value_at = None;
                    i += 1;
                    continue;
                }

                // Update list head if needed
                if let Some(last) = list_head_stack.last_mut() {
                    if last.is_none() {
                        *last = Some(s.clone());
                        if s.eq_ignore_ascii_case("pcb") {
                            expect_pcb_name_at = Some(depth);
                        } else if s.eq_ignore_ascii_case("unit") {
                            expect_unit_at = Some(depth);
                        } else if s.eq_ignore_ascii_case("resolution") {
                            expect_resolution_unit_at = Some(depth);
                        } else if s.eq_ignore_ascii_case("layer") {
                            // Count layers only when inside "(structure ...)" for safety.
                            if list_head_stack
                                .iter()
                                .rev()
                                .skip(1)
                                .any(|h| matches!(h, Some(h) if h.eq_ignore_ascii_case("structure")))
                            {
                                layer_count += 1;
                            }
                        } else if s.eq_ignore_ascii_case("boundary") {
                            in_boundary_at = Some(depth);
                        } else if s.eq_ignore_ascii_case("network") {
                            in_network_at = Some(depth);
                        } else if s.eq_ignore_ascii_case("placement") {
                            in_placement_at = Some(depth);
                        } else if s.eq_ignore_ascii_case("library") {
                            in_library_at = Some(depth);
                        } else if s.eq_ignore_ascii_case("image") {
                            if in_library_at.is_some_and(|d| d < depth) {
                                in_image_at = Some(depth);
                            }
                        } else if s.eq_ignore_ascii_case("path") {
                            // Collect coordinates only for a path inside a boundary.
                            if in_boundary_at.is_some_and(|d| d < depth) && in_boundary_path_at.is_none() {
                                in_boundary_path_at = Some(depth);
                                boundary_numbers.clear();
                            }
                        } else if s.eq_ignore_ascii_case("rect") {
                            if in_boundary_at.is_some_and(|d| d < depth) && in_boundary_rect_at.is_none() {
                                in_boundary_rect_at = Some(depth);
                                boundary_rect_numbers.clear();
                            }
                        } else if s.eq_ignore_ascii_case("polygon") {
                            if in_boundary_at.is_some_and(|d| d < depth) && in_boundary_polygon_at.is_none() {
                                in_boundary_polygon_at = Some(depth);
                                boundary_polygon_numbers.clear();
                                boundary_polygon_skip_first_number = true; // width/clearance field
                            }
                        }
                        if s.eq_ignore_ascii_case("net") {
                            if in_network_at.is_some_and(|d| d < depth)
                                && list_head_stack
                                    .iter()
                                    .rev()
                                    .skip(1)
                                    .any(|h| matches!(h, Some(h) if h.eq_ignore_ascii_case("network")))
                            {
                                net_count += 1;
                            }
                        }
                        if s.eq_ignore_ascii_case("component") {
                            if in_placement_at.is_some_and(|d| d < depth)
                                && list_head_stack
                                    .iter()
                                    .rev()
                                    .skip(1)
                                    .any(|h| matches!(h, Some(h) if h.eq_ignore_ascii_case("placement")))
                            {
                                component_count += 1;
                            }
                        }
                        if s.eq_ignore_ascii_case("pin") {
                            if in_image_at.is_some_and(|d| d < depth)
                                && list_head_stack
                                    .iter()
                                    .rev()
                                    .skip(1)
                                    .any(|h| matches!(h, Some(h) if h.eq_ignore_ascii_case("image")))
                            {
                                pin_count += 1;
                            }
                        }
                    }
                }

                // Collect boundary numeric tokens (best-effort; ignores the leading non-numeric fields).
                if in_boundary_path_at == Some(depth) {
                    if let Ok(v) = s.parse::<f64>() {
                        boundary_numbers.push(v);
                    }
                }
                if in_boundary_rect_at == Some(depth) {
                    if let Ok(v) = s.parse::<f64>() {
                        boundary_rect_numbers.push(v);
                    }
                }
                if in_boundary_polygon_at == Some(depth) {
                    if let Ok(v) = s.parse::<f64>() {
                        if boundary_polygon_skip_first_number {
                            boundary_polygon_skip_first_number = false;
                        } else {
                            boundary_polygon_numbers.push(v);
                        }
                    }
                }
                i += 1;
            }
            Token::Str(s) => {
                // If we're expecting a value, consume it first.
                if expect_pcb_name_at == Some(depth) && pcb_name.is_none() {
                    pcb_name = Some(s.clone());
                    expect_pcb_name_at = None;
                    i += 1;
                    continue;
                }
                if expect_unit_at == Some(depth) {
                    unit = Some(s.clone());
                    expect_unit_at = None;
                    i += 1;
                    continue;
                }
                if expect_resolution_unit_at == Some(depth) {
                    resolution_unit = Some(s.clone());
                    expect_resolution_unit_at = None;
                    expect_resolution_value_at = Some(depth);
                    i += 1;
                    continue;
                }
                if expect_resolution_value_at == Some(depth) {
                    if let Ok(v) = s.parse::<i64>() {
                        resolution_value = Some(v);
                    }
                    expect_resolution_value_at = None;
                    i += 1;
                    continue;
                }

                i += 1;
            }
        }

        // If we just exited a boundary path list, finalize bbox.
        if tok == &Token::RParen {
            // Note: depth was decremented already in the match arm above.
            if in_boundary_path_at.is_some_and(|d| d > depth) {
                if boundary_numbers.len() >= 4 {
                    // Interpret collected numbers as alternating x/y after any leading scalars.
                    if boundary_numbers.len() % 2 == 1 && boundary_numbers.len() > 1 {
                        boundary_numbers.remove(0);
                    }

                    let mut xs: Vec<f64> = Vec::new();
                    let mut ys: Vec<f64> = Vec::new();
                    for pair in boundary_numbers.chunks_exact(2) {
                        xs.push(pair[0]);
                        ys.push(pair[1]);
                    }
                    if !xs.is_empty() && !ys.is_empty() {
                        let (min_x, max_x) = xs
                            .iter()
                            .fold((f64::INFINITY, f64::NEG_INFINITY), |(mn, mx), &x| {
                                (mn.min(x), mx.max(x))
                            });
                        let (min_y, max_y) = ys
                            .iter()
                            .fold((f64::INFINITY, f64::NEG_INFINITY), |(mn, mx), &y| {
                                (mn.min(y), mx.max(y))
                            });
                        union_bbox(&mut boundary_bbox, BoundaryBbox {
                            min_x,
                            min_y,
                            max_x,
                            max_y,
                        });
                    }
                }
                in_boundary_path_at = None;
                boundary_numbers.clear();
            }
            if in_boundary_rect_at.is_some_and(|d| d > depth) {
                if boundary_rect_numbers.len() >= 4 {
                    let x0 = boundary_rect_numbers[0];
                    let y0 = boundary_rect_numbers[1];
                    let x1 = boundary_rect_numbers[2];
                    let y1 = boundary_rect_numbers[3];
                    union_bbox(&mut boundary_bbox, BoundaryBbox {
                        min_x: x0.min(x1),
                        min_y: y0.min(y1),
                        max_x: x0.max(x1),
                        max_y: y0.max(y1),
                    });
                }
                in_boundary_rect_at = None;
                boundary_rect_numbers.clear();
            }
            if in_boundary_polygon_at.is_some_and(|d| d > depth) {
                if boundary_polygon_numbers.len() >= 4 {
                    let mut xs: Vec<f64> = Vec::new();
                    let mut ys: Vec<f64> = Vec::new();
                    for pair in boundary_polygon_numbers.chunks_exact(2) {
                        xs.push(pair[0]);
                        ys.push(pair[1]);
                    }
                    if !xs.is_empty() && !ys.is_empty() {
                        let (min_x, max_x) = xs
                            .iter()
                            .fold((f64::INFINITY, f64::NEG_INFINITY), |(mn, mx), &x| {
                                (mn.min(x), mx.max(x))
                            });
                        let (min_y, max_y) = ys
                            .iter()
                            .fold((f64::INFINITY, f64::NEG_INFINITY), |(mn, mx), &y| {
                                (mn.min(y), mx.max(y))
                            });
                        union_bbox(&mut boundary_bbox, BoundaryBbox {
                            min_x,
                            min_y,
                            max_x,
                            max_y,
                        });
                    }
                }
                in_boundary_polygon_at = None;
                boundary_polygon_numbers.clear();
                boundary_polygon_skip_first_number = false;
            }
            if in_boundary_at.is_some_and(|d| d > depth) {
                in_boundary_at = None;
            }
            if in_network_at.is_some_and(|d| d > depth) {
                in_network_at = None;
            }
            if in_placement_at.is_some_and(|d| d > depth) {
                in_placement_at = None;
            }
            if in_image_at.is_some_and(|d| d > depth) {
                in_image_at = None;
            }
            if in_library_at.is_some_and(|d| d > depth) {
                in_library_at = None;
            }
        }
    }

    if depth != 0 {
        return Err(ParseError {
            message: "unbalanced parentheses".to_string(),
        });
    }

    let pcb_name = pcb_name.ok_or_else(|| ParseError {
        message: "missing (pcb ...) root".to_string(),
    })?;

    Ok(DsnSummary {
        pcb_name,
        unit,
        resolution_unit,
        resolution_value,
        layer_count,
        boundary_bbox,
        net_count,
        component_count,
        pin_count,
    })
}

pub fn summarize_dsn(input: &str) -> Result<DsnSummary, Box<dyn std::error::Error>> {
    let tokens = tokenize(input)?;
    Ok(summarize(&tokens)?)
}

/// Extract the boundary polygon vertices (in world coordinates) from a DSN.
///
/// Notes:
/// - When multiple boundary shapes exist, the largest polygon by absolute area is returned.
/// - The returned list may include a closing point equal to the first point.
pub fn extract_boundary_polygon(tokens: &[Token]) -> Result<Vec<(f64, f64)>, ExtractError> {
    let polys = extract_boundary_polygons(tokens)?;
    // Prefer the largest polygon by absolute area; this works well when both `(rect ...)` and `(path ...)`
    // boundaries are present (the rect and path have similar area, but a hole/cutout will be smaller).
    let mut best_i: Option<usize> = None;
    let mut best_area: f64 = -1.0;
    let mut best_len: usize = 0;
    for (i, p) in polys.iter().enumerate() {
        let area = polygon_area_abs(p);
        if area > best_area || (area - best_area).abs() < 1e-12 && p.len() > best_len {
            best_area = area;
            best_i = Some(i);
            best_len = p.len();
        }
    }
    best_i.map(|i| polys[i].clone()).ok_or_else(|| ExtractError {
        message: "no boundary polygon/path/rect found".to_string(),
    })
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

/// Extract all boundary polygons found in a DSN token stream.
///
/// Many DSNs include multiple boundary shapes (e.g. a `(rect ...)` plus an equivalent `(path ...)`),
/// and some boards include cutouts that can also appear as additional boundary shapes.
///
/// This function extracts the first polygon/path/rect from each `(boundary ...)` scope.
pub fn extract_boundary_polygons(tokens: &[Token]) -> Result<Vec<Vec<(f64, f64)>>, ExtractError> {
    let mut depth: i32 = 0;
    let mut list_head_stack: Vec<Option<String>> = Vec::new();
    let mut in_structure_at: Option<i32> = None;

    let mut out: Vec<Vec<(f64, f64)>> = Vec::new();

    fn parse_numbers(list_tokens: &[Token]) -> Vec<f64> {
        let mut out: Vec<f64> = Vec::new();
        for t in list_tokens {
            if let Some(s) = tok_str(t) {
                if let Ok(v) = s.parse::<f64>() {
                    out.push(v);
                }
            }
        }
        out
    }

    fn numbers_to_points(numbers: &[f64]) -> Vec<(f64, f64)> {
        let mut pts: Vec<(f64, f64)> = Vec::new();
        for pair in numbers.chunks_exact(2) {
            pts.push((pair[0], pair[1]));
        }
        pts
    }

    fn points_from_path_numbers(numbers: &[f64]) -> Option<Vec<(f64, f64)>> {
        // Common case: first numeric is width, rest are coords.
        let mut candidates: Vec<Vec<(f64, f64)>> = Vec::new();
        if numbers.len() >= 6 && numbers.len() % 2 == 0 {
            candidates.push(numbers_to_points(numbers));
        }
        if numbers.len() >= 7 && (numbers.len() - 1) % 2 == 0 {
            candidates.push(numbers_to_points(&numbers[1..]));
        }
        candidates
            .into_iter()
            .filter(|p| p.len() >= 3)
            .max_by(|a, b| polygon_area_abs(a).total_cmp(&polygon_area_abs(b)))
    }

    fn points_from_polygon_numbers(numbers: &[f64]) -> Option<Vec<(f64, f64)>> {
        // Common case: first numeric is width/clearance, rest are coords.
        points_from_path_numbers(numbers)
    }

    fn points_from_rect_numbers(numbers: &[f64]) -> Option<Vec<(f64, f64)>> {
        if numbers.len() < 4 {
            return None;
        }
        let x0 = numbers[0];
        let y0 = numbers[1];
        let x1 = numbers[2];
        let y1 = numbers[3];
        let min_x = x0.min(x1);
        let max_x = x0.max(x1);
        let min_y = y0.min(y1);
        let max_y = y0.max(y1);
        Some(vec![
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
        ])
    }

    fn extract_boundary_polygon_from_boundary_scope(tokens: &[Token]) -> Option<Vec<(f64, f64)>> {
        // tokens are expected to start with `(boundary ...)`
        let mut i = 0usize;
        while i < tokens.len() {
            let head = match tokens.get(i) {
                Some(Token::Atom(s) | Token::Str(s)) => s.as_str(),
                _ => {
                    i += 1;
                    continue;
                }
            };
            if !matches!(tokens.get(i.wrapping_sub(1)), Some(Token::LParen)) {
                i += 1;
                continue;
            }
            if !(head.eq_ignore_ascii_case("path")
                || head.eq_ignore_ascii_case("polygon")
                || head.eq_ignore_ascii_case("rect")
                || head.eq_ignore_ascii_case("rectangle"))
            {
                i += 1;
                continue;
            }
            let start = i - 1;
            let end = find_matching_rparen(tokens, start)?;
            let slice = &tokens[start..=end];
            let nums = parse_numbers(slice);
            let pts = if head.eq_ignore_ascii_case("path") {
                points_from_path_numbers(&nums)
            } else if head.eq_ignore_ascii_case("polygon") {
                points_from_polygon_numbers(&nums)
            } else if head.eq_ignore_ascii_case("rect") || head.eq_ignore_ascii_case("rectangle") {
                points_from_rect_numbers(&nums)
            } else {
                None
            }?;
            return Some(pts);
        }
        None
    }

    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                depth += 1;
                list_head_stack.push(None);
                i += 1;
            }
            Token::RParen => {
                if in_structure_at.is_some_and(|d| d == depth) {
                    in_structure_at = None;
                }
                depth -= 1;
                list_head_stack.pop();
                i += 1;
            }
            Token::Atom(s) | Token::Str(s) => {
                if let Some(head) = list_head_stack.last_mut() {
                    if head.is_none() {
                        *head = Some(s.clone());
                        if s.eq_ignore_ascii_case("structure") {
                            in_structure_at = Some(depth);
                        }
                        if s.eq_ignore_ascii_case("boundary") && in_structure_at.is_some_and(|d| d < depth) {
                            // The list head is at `i`, the '(' is at `i-1`.
                            if i == 0 || !matches!(tokens.get(i - 1), Some(Token::LParen)) {
                                i += 1;
                                continue;
                            }
                            let start = i - 1;
                            let end = find_matching_rparen(tokens, start).ok_or_else(|| ExtractError {
                                message: "unterminated (boundary ...) list".to_string(),
                            })?;
                            let slice = &tokens[start..=end];
                            if let Some(p) = extract_boundary_polygon_from_boundary_scope(slice) {
                                out.push(p);
                            }
                            i = end + 1;
                            continue;
                        }
                    }
                }
                i += 1;
            }
        }
    }

    if out.is_empty() {
        return Err(ExtractError {
            message: "no boundary polygon/path/rect found".to_string(),
        });
    }
    Ok(out)
}

pub fn extract_boundary_polygon_from_str(
    input: &str,
) -> Result<Vec<(f64, f64)>, Box<dyn std::error::Error>> {
    let tokens = tokenize(input)?;
    Ok(extract_boundary_polygon(&tokens)?)
}

pub fn extract_boundary_polygons_from_str(
    input: &str,
) -> Result<Vec<Vec<(f64, f64)>>, Box<dyn std::error::Error>> {
    let tokens = tokenize(input)?;
    Ok(extract_boundary_polygons(&tokens)?)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExtractError {
    pub message: String,
}

impl fmt::Display for ExtractError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for ExtractError {}

/// Extract a minimal net/pin model from a DSN token stream.
///
/// Supported patterns (common in FreeRouting DSNs):
/// - `(library (image <ref> (pin <padstack> <id> <x> <y>) ...))`
/// - `(network (net <name> (pins <ref-id> ...)))`
pub fn extract_model(tokens: &[Token]) -> Result<DsnModel, ExtractError> {
    let mut model = DsnModel::default();
    let mut depth: i32 = 0;
    let mut list_head_stack: Vec<Option<String>> = Vec::new();

    fn push_pin_ref(model: &mut DsnModel, current_net: &Option<String>, pin_ref: String) {
        if let Some(net) = current_net.as_ref() {
            if let Some(entry) = model.nets.get_mut(net) {
                entry.pins.push(pin_ref);
            }
        }
    }

    fn flush_pins_state(
        model: &mut DsnModel,
        current_net: &Option<String>,
        pending: &mut Option<String>,
        join_prefix: &mut Option<String>,
    ) {
        if let Some(prefix) = join_prefix.take() {
            push_pin_ref(model, current_net, prefix);
        }
        if let Some(pin) = pending.take() {
            push_pin_ref(model, current_net, pin);
        }
    }

    let mut current_image: Option<String> = None;
    let mut expect_image_name_at: Option<i32> = None;

    let mut current_net: Option<String> = None;
    let mut expect_net_name_at: Option<i32> = None;
    let mut in_pins_list_at: Option<i32> = None;
    let mut pins_pending: Option<String> = None;
    let mut pins_join_prefix: Option<String> = None;

    let mut current_padstack: Option<String> = None;
    let mut expect_padstack_name_at: Option<i32> = None;

    let mut in_structure_at: Option<i32> = None;
    let mut expect_structure_layer_name_at: Option<i32> = None;

    #[derive(Debug, Clone)]
    struct Placement {
        image: String,
        x: f64,
        y: f64,
        side: String,
        rot_deg: f64,
    }

    let mut in_placement_at: Option<i32> = None;
    let mut current_component_image: Option<String> = None;
    let mut in_component_at: Option<i32> = None;
    let mut expect_component_image_at: Option<i32> = None;
    let mut placements: HashMap<String, Placement> = HashMap::new();
    let mut pin_clearance_classes: HashMap<String, String> = HashMap::new();

    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                depth += 1;
                list_head_stack.push(None);
                i += 1;
            }
            Token::RParen => {
                depth -= 1;
                list_head_stack.pop();
                if expect_image_name_at.is_some_and(|d| d > depth) {
                    expect_image_name_at = None;
                    current_image = None;
                }
                if expect_padstack_name_at.is_some_and(|d| d > depth) {
                    expect_padstack_name_at = None;
                    current_padstack = None;
                }
                if expect_net_name_at.is_some_and(|d| d > depth) {
                    expect_net_name_at = None;
                    current_net = None;
                }
                if in_pins_list_at.is_some_and(|d| d > depth) {
                    flush_pins_state(
                        &mut model,
                        &current_net,
                        &mut pins_pending,
                        &mut pins_join_prefix,
                    );
                    in_pins_list_at = None;
                }
                if expect_structure_layer_name_at.is_some_and(|d| d > depth) {
                    expect_structure_layer_name_at = None;
                }
                if in_structure_at.is_some_and(|d| d > depth) {
                    in_structure_at = None;
                }
                if expect_component_image_at.is_some_and(|d| d > depth) {
                    expect_component_image_at = None;
                    current_component_image = None;
                }
                if in_component_at.is_some_and(|d| d > depth) {
                    in_component_at = None;
                    current_component_image = None;
                }
                if in_placement_at.is_some_and(|d| d > depth) {
                    in_placement_at = None;
                }
                i += 1;
            }
            Token::Atom(s) | Token::Str(s) => {
                // Consume expectations first.
                if expect_image_name_at == Some(depth) {
                    current_image = Some(s.clone());
                    expect_image_name_at = None;
                    model.images.entry(s.clone()).or_default();
                    i += 1;
                    continue;
                }
                if expect_padstack_name_at == Some(depth) {
                    current_padstack = Some(s.clone());
                    expect_padstack_name_at = None;
                    model.padstacks.entry(s.clone()).or_insert(0.0);
                    model.padstack_layers.entry(s.clone()).or_default();
                    i += 1;
                    continue;
                }
                if expect_net_name_at == Some(depth) {
                    current_net = Some(s.clone());
                    expect_net_name_at = None;
                    model
                        .nets
                        .entry(current_net.clone().unwrap())
                        .or_insert_with(|| NetDef {
                            name: current_net.clone().unwrap(),
                            pins: Vec::new(),
                        });
                    i += 1;
                    continue;
                }
                if expect_component_image_at == Some(depth) {
                    current_component_image = Some(s.clone());
                    expect_component_image_at = None;
                    model.images.entry(s.clone()).or_default();
                    i += 1;
                    continue;
                }
                if expect_structure_layer_name_at == Some(depth) {
                    // Assign a stable 0-based index in order of appearance.
                    let idx = model.layer_name_to_index.len();
                    model.layer_name_to_index.entry(s.clone()).or_insert(idx);
                    expect_structure_layer_name_at = None;
                    i += 1;
                    continue;
                }

                // Pins list collection: (pins <ref-id> <ref-id> ...)
                if in_pins_list_at == Some(depth) {
                    // FreeRouting sometimes emits `"J3"-"D+"` (no whitespace). Our tokenizer
                    // represents this as `"J3" "-" "D+"`, but the DSN semantics here are a
                    // single pin ref token `J3-D+`. Reconstruct these pin refs in-place.
                    if s == "-" {
                        if pins_join_prefix.is_some() {
                            // Unexpected: already waiting for a suffix. Degrade gracefully by
                            // emitting what we have and treating this dash as a literal token.
                            if let Some(prefix) = pins_join_prefix.take() {
                                push_pin_ref(&mut model, &current_net, prefix);
                            }
                            push_pin_ref(&mut model, &current_net, "-".to_string());
                        } else if let Some(prefix) = pins_pending.take() {
                            pins_join_prefix = Some(prefix);
                        } else {
                            push_pin_ref(&mut model, &current_net, "-".to_string());
                        }
                        i += 1;
                        continue;
                    }

                    if let Some(prefix) = pins_join_prefix.take() {
                        pins_pending = Some(format!("{prefix}-{s}"));
                        i += 1;
                        continue;
                    }

                    if let Some(prev) = pins_pending.replace(s.clone()) {
                        push_pin_ref(&mut model, &current_net, prev);
                    }
                    i += 1;
                    continue;
                }

                // Set list head
                if let Some(last) = list_head_stack.last_mut() {
                    if last.is_none() {
                        *last = Some(s.clone());

                        // (image <ref> ...)
                        if s.eq_ignore_ascii_case("image") {
                            expect_image_name_at = Some(depth);
                        }

                        if s.eq_ignore_ascii_case("structure") {
                            in_structure_at = Some(depth);
                        }

                        if s.eq_ignore_ascii_case("layer") && in_structure_at.is_some_and(|d| d < depth) {
                            expect_structure_layer_name_at = Some(depth);
                        }

                        if s.eq_ignore_ascii_case("placement") {
                            in_placement_at = Some(depth);
                        }

                        // (component <image-name> ...) under placement
                        if s.eq_ignore_ascii_case("component")
                            && in_placement_at.is_some_and(|d| d < depth)
                        {
                            in_component_at = Some(depth);
                            expect_component_image_at = Some(depth);
                            current_component_image = None;
                        }

                        // (padstack <name> ...)
                        if s.eq_ignore_ascii_case("padstack") {
                            expect_padstack_name_at = Some(depth);
                        }

                        // (net <name> ...)
                        if s.eq_ignore_ascii_case("net") {
                            // Require we are under a network list for safety.
                            if list_head_stack
                                .iter()
                                .rev()
                                .skip(1)
                                .any(|h| matches!(h, Some(h) if h.eq_ignore_ascii_case("network")))
                            {
                                expect_net_name_at = Some(depth);
                            }
                        }

                        // (pins ...)
                        if s.eq_ignore_ascii_case("pins") {
                            if current_net.is_some() {
                                in_pins_list_at = Some(depth);
                            }
                        }

                        // (place <refdes> <x> <y> <side> <rot> ...)
                        if s.eq_ignore_ascii_case("place") && current_component_image.is_some() {
                            let get = |k: usize| -> Option<String> {
                                match tokens.get(i + k) {
                                    Some(Token::Atom(v) | Token::Str(v)) => Some(v.clone()),
                                    _ => None,
                                }
                            };
                            let refdes = get(1);
                            let x = get(2).and_then(|v| v.parse::<f64>().ok());
                            let y = get(3).and_then(|v| v.parse::<f64>().ok());
                            let side = get(4);
                            let rot = get(5).and_then(|v| v.parse::<f64>().ok());
                            if let (Some(refdes), Some(x), Some(y), Some(side), Some(rot), Some(img)) =
                                (refdes, x, y, side, rot, current_component_image.clone())
                            {
                                // Parse optional `(pin <id> (clearance_class <name>))` subscopes.
                                if let Some(start_lparen) = i.checked_sub(1) {
                                    if matches!(tokens.get(start_lparen), Some(Token::LParen)) {
                                        if let Some(end) = find_matching_rparen(tokens, start_lparen) {
                                            let scope = &tokens[start_lparen..=end];
                                            let mut k = 0usize;
                                            while k + 6 < scope.len() {
                                                if !matches!(scope[k], Token::LParen) {
                                                    k += 1;
                                                    continue;
                                                }
                                                let Some(head) = scope.get(k + 1).and_then(tok_str) else {
                                                    k += 1;
                                                    continue;
                                                };
                                                if !head.eq_ignore_ascii_case("pin") {
                                                    k += 1;
                                                    continue;
                                                }
                                                let Some(pin_id) = scope.get(k + 2).and_then(tok_str) else {
                                                    k += 1;
                                                    continue;
                                                };
                                                // Find the end of this `(pin ...)` list.
                                                let Some(pin_end) = find_matching_rparen(scope, k) else {
                                                    break;
                                                };
                                                let pin_scope = &scope[k..=pin_end];
                                                let mut kk = 0usize;
                                                while kk + 3 < pin_scope.len() {
                                                    if matches!(pin_scope[kk], Token::LParen) {
                                                        if let Some(h) = pin_scope.get(kk + 1).and_then(tok_str) {
                                                            if h.eq_ignore_ascii_case("clearance_class") {
                                                                if let Some(cc) = pin_scope.get(kk + 2).and_then(tok_str) {
                                                                    let key = format!("{refdes}-{pin_id}");
                                                                    pin_clearance_classes.insert(key, cc.to_string());
                                                                    break;
                                                                }
                                                            }
                                                        }
                                                    }
                                                    kk += 1;
                                                }
                                                k = pin_end + 1;
                                            }
                                        }
                                    }
                                }
                                placements.insert(
                                    refdes,
                                    Placement {
                                        image: img,
                                        x,
                                        y,
                                        side,
                                        rot_deg: rot,
                                    },
                                );
                            }
                        }

                        // (pin <padstack> <id> <x> <y>)
                        if s.eq_ignore_ascii_case("pin") {
                            if current_image.is_none() {
                                i += 1;
                                continue;
                            }
                            // Parse the next 4 atoms/strings.
                            let get = |k: usize| -> Option<String> {
                                match tokens.get(i + k) {
                                    Some(Token::Atom(v) | Token::Str(v)) => Some(v.clone()),
                                    _ => None,
                                }
                            };
                            let padstack = get(1);
                            let pin_id = get(2);
                            let x = get(3).and_then(|v| v.parse::<f64>().ok());
                            let y = get(4).and_then(|v| v.parse::<f64>().ok());

                            if let (Some(padstack), Some(pin_id), Some(x), Some(y), Some(img)) =
                                (padstack, pin_id, x, y, current_image.clone())
                            {
                                model.images.entry(img).or_default().push(ImagePinDef {
                                    padstack,
                                    pin_id,
                                    x,
                                    y,
                                });
                            }
                        }

                        // padstack shapes (circle / polygon / path) inside a padstack
                        if (s.eq_ignore_ascii_case("circle")
                            || s.eq_ignore_ascii_case("polygon")
                            || s.eq_ignore_ascii_case("path")
                            || s.eq_ignore_ascii_case("polygon_path")
                            || s.eq_ignore_ascii_case("rect")
                            || s.eq_ignore_ascii_case("rectangle"))
                            && current_padstack.is_some()
                        {
                            // Require we are nested under a padstack list for safety.
                            if !list_head_stack
                                .iter()
                                .rev()
                                .skip(1)
                                .any(|h| matches!(h, Some(h) if h.eq_ignore_ascii_case("padstack")))
                            {
                                i += 1;
                                continue;
                            }

                            let layer_to_index = |layer_tok: &str| -> Option<usize> {
                                if let Ok(n) = layer_tok.parse::<i64>() {
                                    if n >= 1 {
                                        return Some((n - 1) as usize);
                                    }
                                    return None;
                                }
                                model.layer_name_to_index.get(layer_tok).copied()
                            };

                            if s.eq_ignore_ascii_case("circle") {
                                let get = |k: usize| -> Option<String> {
                                    match tokens.get(i + k) {
                                        Some(Token::Atom(v) | Token::Str(v)) => Some(v.clone()),
                                        _ => None,
                                    }
                                };
                                let layer_tok = get(1);
                                let diameter = get(2).and_then(|v| v.parse::<f64>().ok());
                                let x = get(3).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
                                let y = get(4).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
                                if let (Some(d), Some(ps)) = (diameter, current_padstack.clone()) {
                                    let r = (x.hypot(y)) + (d / 2.0);
                                    model
                                        .padstacks
                                        .entry(ps)
                                        .and_modify(|cur| *cur = cur.max(r))
                                        .or_insert(r);
                                }
                                if let (Some(layer_tok), Some(ps), Some(diameter)) =
                                    (layer_tok, current_padstack.clone(), diameter)
                                {
                                    model
                                        .padstack_shapes
                                        .entry(ps.clone())
                                        .or_default()
                                        .push(PadShapeDef::Circle {
                                            layer: layer_tok.clone(),
                                            diameter,
                                            x,
                                            y,
                                        });
                                    if let Some(idx0) = layer_to_index(&layer_tok) {
                                        let entry = model.padstack_layers.entry(ps).or_default();
                                        if !entry.contains(&idx0) {
                                            entry.push(idx0);
                                            entry.sort_unstable();
                                        }
                                    }
                                }
                            } else if s.eq_ignore_ascii_case("rect") || s.eq_ignore_ascii_case("rectangle") {
                                // rect: (rect <layer> <x1> <y1> <x2> <y2>)
                                let get = |k: usize| -> Option<String> {
                                    match tokens.get(i + k) {
                                        Some(Token::Atom(v) | Token::Str(v)) => Some(v.clone()),
                                        _ => None,
                                    }
                                };
                                let layer_tok = get(1);
                                let x1 = get(2).and_then(|v| v.parse::<f64>().ok());
                                let y1 = get(3).and_then(|v| v.parse::<f64>().ok());
                                let x2 = get(4).and_then(|v| v.parse::<f64>().ok());
                                let y2 = get(5).and_then(|v| v.parse::<f64>().ok());
                                if let (Some(layer), Some(x1), Some(y1), Some(x2), Some(y2), Some(ps)) =
                                    (layer_tok.clone(), x1, y1, x2, y2, current_padstack.clone())
                                {
                                    let pts = vec![(x1, y1), (x2, y1), (x2, y2), (x1, y2)];
                                    model
                                        .padstack_shapes
                                        .entry(ps.clone())
                                        .or_default()
                                        .push(PadShapeDef::Polygon { layer: layer.clone(), points: pts.clone() });
                                    let mut r: f64 = 0.0;
                                    for (px, py) in pts {
                                        r = r.max(px.hypot(py));
                                    }
                                    if r > 0.0 {
                                        model
                                            .padstacks
                                            .entry(ps.clone())
                                            .and_modify(|cur| *cur = cur.max(r))
                                            .or_insert(r);
                                    }
                                    if let Some(idx0) = layer_to_index(&layer) {
                                        let entry = model.padstack_layers.entry(ps).or_default();
                                        if !entry.contains(&idx0) {
                                            entry.push(idx0);
                                            entry.sort_unstable();
                                        }
                                    }
                                }
                            } else if s.eq_ignore_ascii_case("polygon") {
                                // polygon: (polygon <layer> <width> <x0> <y0> <x1> <y1> ...)
                                let get = |k: usize| -> Option<String> {
                                    match tokens.get(i + k) {
                                        Some(Token::Atom(v) | Token::Str(v)) => Some(v.clone()),
                                        _ => None,
                                    }
                                };
                                let layer_tok = get(1);
                                let width = get(2).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
                                let mut nums: Vec<f64> = Vec::new();
                                let mut k = 3usize;
                                while let Some(t) = tokens.get(i + k) {
                                    match t {
                                        Token::Atom(v) | Token::Str(v) => {
                                            if let Ok(n) = v.parse::<f64>() {
                                                nums.push(n);
                                            }
                                        }
                                        Token::RParen => break,
                                        Token::LParen => {}
                                    }
                                    k += 1;
                                }
                                let mut r: f64 = 0.0;
                                let mut points: Vec<(f64, f64)> = Vec::new();
                                for pair in nums.chunks_exact(2) {
                                    r = r.max(pair[0].hypot(pair[1]));
                                    points.push((pair[0], pair[1]));
                                }
                                if r > 0.0 {
                                    if let Some(ps) = current_padstack.clone() {
                                        model
                                            .padstacks
                                            .entry(ps)
                                            .and_modify(|cur| *cur = cur.max(r))
                                        .or_insert(r);
                                    }
                                }
                                let _ = width;
                                if let (Some(layer_tok), Some(ps)) = (layer_tok, current_padstack.clone()) {
                                    if points.len() < 3 {
                                        i += 1;
                                        continue;
                                    }
                                    model
                                        .padstack_shapes
                                        .entry(ps.clone())
                                        .or_default()
                                        .push(PadShapeDef::Polygon {
                                            layer: layer_tok.clone(),
                                            points,
                                        });
                                    if let Some(idx0) = layer_to_index(&layer_tok) {
                                        let entry = model.padstack_layers.entry(ps).or_default();
                                        if !entry.contains(&idx0) {
                                            entry.push(idx0);
                                            entry.sort_unstable();
                                        }
                                    }
                                }
                            } else {
                                // path/polygon_path: (path <layer> <width> <x0> <y0> <x1> <y1> ...)
                                let get = |k: usize| -> Option<String> {
                                    match tokens.get(i + k) {
                                        Some(Token::Atom(v) | Token::Str(v)) => Some(v.clone()),
                                        _ => None,
                                    }
                                };
                                let layer_tok = get(1);
                                let width = get(2).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
                                let mut nums: Vec<f64> = Vec::new();
                                let mut k = 3usize;
                                while let Some(t) = tokens.get(i + k) {
                                    match t {
                                        Token::Atom(v) | Token::Str(v) => {
                                            if let Ok(n) = v.parse::<f64>() {
                                                nums.push(n);
                                            }
                                        }
                                        Token::RParen => break,
                                        Token::LParen => {}
                                    }
                                    k += 1;
                                }
                                let mut max_abs: f64 = 0.0;
                                let mut points: Vec<(f64, f64)> = Vec::new();
                                for pair in nums.chunks_exact(2) {
                                    max_abs = max_abs.max(pair[0].hypot(pair[1]));
                                    points.push((pair[0], pair[1]));
                                }
                                let r = max_abs + (width / 2.0);
                                if r > 0.0 {
                                    if let Some(ps) = current_padstack.clone() {
                                        model
                                            .padstacks
                                            .entry(ps)
                                            .and_modify(|cur| *cur = cur.max(r))
                                            .or_insert(r);
                                    }
                                }
                                if let (Some(layer_tok), Some(ps)) = (layer_tok, current_padstack.clone()) {
                                    if points.len() < 2 {
                                        i += 1;
                                        continue;
                                    }
                                    model
                                        .padstack_shapes
                                        .entry(ps.clone())
                                        .or_default()
                                        .push(PadShapeDef::Path {
                                            layer: layer_tok.clone(),
                                            width,
                                            points,
                                        });
                                    if let Some(idx0) = layer_to_index(&layer_tok) {
                                        let entry = model.padstack_layers.entry(ps).or_default();
                                        if !entry.contains(&idx0) {
                                            entry.push(idx0);
                                            entry.sort_unstable();
                                        }
                                    }
                                }
                            }
                        }

                        // (keepout|wire_keepout|via_keepout ... (circle|circ|polygon ...))
                        if s.eq_ignore_ascii_case("keepout")
                            || s.eq_ignore_ascii_case("wire_keepout")
                            || s.eq_ignore_ascii_case("via_keepout")
                        {
                            // The list head token is at `i`, and the opening '(' is at `i-1`.
                            if i == 0 || !matches!(tokens.get(i - 1), Some(Token::LParen)) {
                                i += 1;
                                continue;
                            }
                            if let Some(shape) = parse_keepout_list(tokens, i - 1) {
                                if let Some(img) = current_image.clone() {
                                    model.image_keepouts.entry(img).or_default().push(shape);
                                } else {
                                    model.keepouts.push(shape);
                                }
                            }
                        }

                        // (plane <net> (polygon <layer> 0 <x y>...) ...)
                        if s.eq_ignore_ascii_case("plane") && in_structure_at.is_some() {
                            if i == 0 || !matches!(tokens.get(i - 1), Some(Token::LParen)) {
                                i += 1;
                                continue;
                            }
                            if let Some(p) = parse_plane_list(tokens, i - 1) {
                                model.planes.push(p);
                            }
                        }
                    }
                }

                i += 1;
            }
        }
    }

    // Finalize absolute pins:
    // - If placements exist, synthesize pins as `<refdes>-<pin_id>` by applying transforms.
    // - Otherwise, assume image pins are already absolute and use `<image>-<pin_id>` (legacy fixtures).
    if !placements.is_empty() {
        for (refdes, p) in placements {
            let Some(pins) = model.images.get(&p.image) else {
                continue;
            };
            let keepouts = model.image_keepouts.get(&p.image).cloned().unwrap_or_default();
            let theta = (p.rot_deg / 180.0) * std::f64::consts::PI;
            let (c, s) = (theta.cos(), theta.sin());
            let flip = p.side.eq_ignore_ascii_case("back");

            for pin in pins {
                let mut lx = pin.x;
                let ly = pin.y;
                if flip {
                    lx = -lx;
                }
                let rx = lx * c - ly * s;
                let ry = lx * s + ly * c;
                let ax = p.x + rx;
                let ay = p.y + ry;
                let pin_id = pin.pin_id.clone();
                let padstack = pin.padstack.clone();
                let ref_name = format!("{refdes}-{pin_id}");
                let mut shapes: Vec<PadShapeDef> = Vec::new();
                for shape in model
                    .padstack_shapes
                    .get(&padstack)
                    .cloned()
                    .unwrap_or_default()
                {
                    shapes.push(transform_pad_shape(shape, (pin.x, pin.y), (p.x, p.y), (c, s), flip));
                }
                model.pins.insert(
                    ref_name.clone(),
                    PinDef {
                        ref_name,
                        padstack,
                        pin_id,
                        x: ax,
                        y: ay,
                        shapes,
                    },
                );
            }

            for ko in keepouts {
                match ko {
                    KeepoutShapeDef::Circle { kind, layer, diameter, x, y } => {
                        let layer = if flip { mirror_layer_name(&layer) } else { layer };
                        let mut lx = x;
                        let ly = y;
                        if flip {
                            lx = -lx;
                        }
                        let rx = lx * c - ly * s;
                        let ry = lx * s + ly * c;
                        let ax = p.x + rx;
                        let ay = p.y + ry;
                        model.keepouts.push(KeepoutShapeDef::Circle {
                            kind,
                            layer,
                            diameter,
                            x: ax,
                            y: ay,
                        });
                    }
                    KeepoutShapeDef::Polygon { kind, layer, points } => {
                        let layer = if flip { mirror_layer_name(&layer) } else { layer };
                        let mut out_pts: Vec<(f64, f64)> = Vec::new();
                        for (mut lx, ly) in points {
                            if flip {
                                lx = -lx;
                            }
                            let rx = lx * c - ly * s;
                            let ry = lx * s + ly * c;
                            out_pts.push((p.x + rx, p.y + ry));
                        }
                        model.keepouts.push(KeepoutShapeDef::Polygon {
                            kind,
                            layer,
                            points: out_pts,
                        });
                    }
                    KeepoutShapeDef::Path { kind, layer, width, points } => {
                        let layer = if flip { mirror_layer_name(&layer) } else { layer };
                        let mut out_pts: Vec<(f64, f64)> = Vec::new();
                        for (mut lx, ly) in points {
                            if flip {
                                lx = -lx;
                            }
                            let rx = lx * c - ly * s;
                            let ry = lx * s + ly * c;
                            out_pts.push((p.x + rx, p.y + ry));
                        }
                        model.keepouts.push(KeepoutShapeDef::Path {
                            kind,
                            layer,
                            width,
                            points: out_pts,
                        });
                    }
                }
            }
        }
    } else {
        for (img, pins) in &model.images {
            for pin in pins {
                let pin_id = pin.pin_id.clone();
                let padstack = pin.padstack.clone();
                let ref_name = format!("{img}-{pin_id}");
                let mut shapes: Vec<PadShapeDef> = Vec::new();
                for shape in model
                    .padstack_shapes
                    .get(&padstack)
                    .cloned()
                    .unwrap_or_default()
                {
                    shapes.push(translate_pad_shape(shape, (pin.x, pin.y)));
                }
                model.pins.insert(
                    ref_name.clone(),
                    PinDef {
                        ref_name,
                        padstack,
                        pin_id,
                        x: pin.x,
                        y: pin.y,
                        shapes,
                    },
                );
            }
        }
        // Keepouts without placements are assumed to already be absolute.
        for (_img, kos) in &model.image_keepouts {
            for ko in kos {
                model.keepouts.push(ko.clone());
            }
        }
    }

    model.pin_clearance_classes = pin_clearance_classes;
    Ok(model)
}

fn mirror_layer_name(layer: &str) -> String {
    if layer.eq_ignore_ascii_case("top") {
        return "Bottom".to_string();
    }
    if layer.eq_ignore_ascii_case("bottom") {
        return "Top".to_string();
    }
    if layer.starts_with("F.") {
        return format!("B.{}", &layer[2..]);
    }
    if layer.starts_with("B.") {
        return format!("F.{}", &layer[2..]);
    }
    layer.to_string()
}

fn transform_point((x, y): (f64, f64), translation: (f64, f64), rot_cs: (f64, f64), flip: bool) -> (f64, f64) {
    let (tx, ty) = translation;
    let (c, s) = rot_cs;
    let mut lx = x;
    let ly = y;
    if flip {
        lx = -lx;
    }
    let rx = lx * c - ly * s;
    let ry = lx * s + ly * c;
    (tx + rx, ty + ry)
}

fn translate_pad_shape(shape: PadShapeDef, pin_xy: (f64, f64)) -> PadShapeDef {
    let (px, py) = pin_xy;
    match shape {
        PadShapeDef::Circle { layer, diameter, x, y } => PadShapeDef::Circle {
            layer,
            diameter,
            x: px + x,
            y: py + y,
        },
        PadShapeDef::Polygon { layer, points } => PadShapeDef::Polygon {
            layer,
            points: points.into_iter().map(|(x, y)| (px + x, py + y)).collect(),
        },
        PadShapeDef::Path { layer, width, points } => PadShapeDef::Path {
            layer,
            width,
            points: points.into_iter().map(|(x, y)| (px + x, py + y)).collect(),
        },
    }
}

fn transform_pad_shape(
    shape: PadShapeDef,
    pin_local_xy: (f64, f64),
    translation: (f64, f64),
    rot_cs: (f64, f64),
    flip: bool,
) -> PadShapeDef {
    let (px, py) = pin_local_xy;
    match shape {
        PadShapeDef::Circle { layer, diameter, x, y } => {
            let layer = if flip { mirror_layer_name(&layer) } else { layer };
            let (cx, cy) = transform_point((px + x, py + y), translation, rot_cs, flip);
            PadShapeDef::Circle {
                layer,
                diameter,
                x: cx,
                y: cy,
            }
        }
        PadShapeDef::Polygon { layer, points } => {
            let layer = if flip { mirror_layer_name(&layer) } else { layer };
            let pts = points
                .into_iter()
                .map(|(x, y)| transform_point((px + x, py + y), translation, rot_cs, flip))
                .collect();
            PadShapeDef::Polygon { layer, points: pts }
        }
        PadShapeDef::Path { layer, width, points } => {
            let layer = if flip { mirror_layer_name(&layer) } else { layer };
            let pts = points
                .into_iter()
                .map(|(x, y)| transform_point((px + x, py + y), translation, rot_cs, flip))
                .collect();
            PadShapeDef::Path { layer, width, points: pts }
        }
    }
}

fn find_matching_rparen(tokens: &[Token], start_lparen: usize) -> Option<usize> {
    if !matches!(tokens.get(start_lparen), Some(Token::LParen)) {
        return None;
    }
    let mut depth: i32 = 0;
    for (i, t) in tokens.iter().enumerate().skip(start_lparen) {
        match t {
            Token::LParen => depth += 1,
            Token::RParen => {
                depth -= 1;
                if depth == 0 {
                    return Some(i);
                }
            }
            _ => {}
        }
    }
    None
}

fn tok_str(tok: &Token) -> Option<&str> {
    match tok {
        Token::Atom(s) | Token::Str(s) => Some(s.as_str()),
        _ => None,
    }
}

fn tok_f64(tok: &Token) -> Option<f64> {
    tok_str(tok)?.parse::<f64>().ok()
}

fn parse_keepout_child_list(tokens: &[Token], kind: KeepoutKind) -> Option<KeepoutShapeDef> {
    if tokens.len() < 4 {
        return None;
    }
    if !matches!(tokens[0], Token::LParen) || !matches!(tokens[tokens.len() - 1], Token::RParen) {
        return None;
    }
    let head = tok_str(&tokens[1])?;

    if head.eq_ignore_ascii_case("circle") {
        let layer = tok_str(&tokens[2])?.to_string();
        let diameter = tok_f64(&tokens[3])?;
        let x = tokens.get(4).and_then(tok_f64).unwrap_or(0.0);
        let y = tokens.get(5).and_then(tok_f64).unwrap_or(0.0);
        return Some(KeepoutShapeDef::Circle {
            kind,
            layer,
            diameter,
            x,
            y,
        });
    }

    if head.eq_ignore_ascii_case("circ") {
        let layer = tok_str(&tokens[2])?.to_string();
        let radius = tok_f64(&tokens[3])?;
        let x = tokens.get(4).and_then(tok_f64).unwrap_or(0.0);
        let y = tokens.get(5).and_then(tok_f64).unwrap_or(0.0);
        return Some(KeepoutShapeDef::Circle {
            kind,
            layer,
            diameter: radius * 2.0,
            x,
            y,
        });
    }

    if head.eq_ignore_ascii_case("polygon") {
        let layer = tok_str(&tokens[2])?.to_string();
        let mut nums: Vec<f64> = Vec::new();
        for t in &tokens[3..tokens.len() - 1] {
            if let Some(v) = tok_f64(t) {
                nums.push(v);
            }
        }
        if nums.first().is_some_and(|v| v.abs() < 1e-12) {
            nums.remove(0);
        }
        let mut points: Vec<(f64, f64)> = Vec::new();
        for pair in nums.chunks_exact(2) {
            points.push((pair[0], pair[1]));
        }
        if points.len() < 3 {
            return None;
        }
        return Some(KeepoutShapeDef::Polygon { kind, layer, points });
    }

    if head.eq_ignore_ascii_case("rect") || head.eq_ignore_ascii_case("rectangle") {
        let layer = tok_str(&tokens[2])?.to_string();
        let x1 = tok_f64(&tokens[3])?;
        let y1 = tok_f64(&tokens[4])?;
        let x2 = tok_f64(&tokens[5])?;
        let y2 = tok_f64(&tokens[6])?;
        return Some(KeepoutShapeDef::Polygon {
            kind,
            layer,
            points: vec![(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
        });
    }

    if head.eq_ignore_ascii_case("path") || head.eq_ignore_ascii_case("polygon_path") {
        let layer = tok_str(&tokens[2])?.to_string();
        let width = tok_f64(&tokens[3]).unwrap_or(0.0);
        let mut nums: Vec<f64> = Vec::new();
        for t in &tokens[4..tokens.len() - 1] {
            if let Some(v) = tok_f64(t) {
                nums.push(v);
            }
        }
        let mut points: Vec<(f64, f64)> = Vec::new();
        for pair in nums.chunks_exact(2) {
            points.push((pair[0], pair[1]));
        }
        if points.len() < 2 {
            return None;
        }
        return Some(KeepoutShapeDef::Path {
            kind,
            layer,
            width,
            points,
        });
    }

    None
}

fn parse_keepout_list(tokens: &[Token], start_lparen: usize) -> Option<KeepoutShapeDef> {
    // tokens: (keepout|wire_keepout|via_keepout ... (circle|circ|polygon ...))
    let end = find_matching_rparen(tokens, start_lparen)?;
    let list = &tokens[start_lparen..=end];
    if list.len() < 4 {
        return None;
    }
    let head = tok_str(&list[1])?;
    let kind = if head.eq_ignore_ascii_case("keepout") {
        KeepoutKind::All
    } else if head.eq_ignore_ascii_case("wire_keepout") {
        KeepoutKind::Wire
    } else if head.eq_ignore_ascii_case("via_keepout") {
        KeepoutKind::Via
    } else {
        return None;
    };
    // Find first child list inside this keepout list.
    let mut i = 2usize;
    while i < list.len().saturating_sub(1) {
        if matches!(list[i], Token::LParen) {
            let child_end = find_matching_rparen(list, i)?;
            return parse_keepout_child_list(&list[i..=child_end], kind);
        }
        i += 1;
    }
    None
}

fn parse_plane_shape_list(tokens: &[Token]) -> Option<PlaneShapeDef> {
    // tokens: (polygon <layer> <skip> <x0> <y0> ... )
    if tokens.len() < 6 {
        return None;
    }
    if !matches!(tokens[0], Token::LParen) || !matches!(tokens[tokens.len() - 1], Token::RParen) {
        return None;
    }
    let head = tok_str(&tokens[1])?;
    if !head.eq_ignore_ascii_case("polygon") {
        return None;
    }
    let layer = tok_str(&tokens[2])?.to_string();

    let mut nums: Vec<f64> = Vec::new();
    for t in &tokens[3..tokens.len() - 1] {
        if let Some(v) = tok_f64(t) {
            nums.push(v);
        }
    }
    // FreeRouting DSNs typically include a leading number here (often 0) which we skip.
    if !nums.is_empty() {
        nums.remove(0);
    }
    let mut points: Vec<(f64, f64)> = Vec::new();
    for pair in nums.chunks_exact(2) {
        points.push((pair[0], pair[1]));
    }
    if points.len() < 3 {
        return None;
    }
    Some(PlaneShapeDef::Polygon { layer, points })
}

fn parse_plane_list(tokens: &[Token], start_lparen: usize) -> Option<PlaneDef> {
    // tokens: (plane <net> <shape lists>...)
    let end = find_matching_rparen(tokens, start_lparen)?;
    let list = &tokens[start_lparen..=end];
    if list.len() < 6 {
        return None;
    }
    let head = tok_str(&list[1])?;
    if !head.eq_ignore_ascii_case("plane") {
        return None;
    }
    let net = tok_str(&list[2])?.to_string();

    let mut shapes: Vec<PlaneShapeDef> = Vec::new();
    let mut windows: Vec<PlaneShapeDef> = Vec::new();
    let mut i = 3usize;
    while i < list.len().saturating_sub(1) {
        if matches!(list[i], Token::LParen) {
            let child_end = find_matching_rparen(list, i)?;
            let child = &list[i..=child_end];
            if let Some(h) = child.get(1).and_then(tok_str) {
                if h.eq_ignore_ascii_case("window") {
                    // Window scope: (window (polygon ...)) - take the first polygon child.
                    let mut j = 2usize;
                    while j < child.len().saturating_sub(1) {
                        if matches!(child[j], Token::LParen) {
                            let wnd_end = find_matching_rparen(child, j)?;
                            if let Some(s) = parse_plane_shape_list(&child[j..=wnd_end]) {
                                windows.push(s);
                            }
                            break;
                        }
                        j += 1;
                    }
                } else if let Some(s) = parse_plane_shape_list(child) {
                    shapes.push(s);
                }
            }
            i = child_end + 1;
            continue;
        }
        i += 1;
    }
    if shapes.is_empty() {
        return None;
    }
    Some(PlaneDef { net, shapes, windows })
}

pub fn extract_model_from_str(input: &str) -> Result<DsnModel, Box<dyn std::error::Error>> {
    let tokens = tokenize(input)?;
    Ok(extract_model(&tokens)?)
}
    fn union_bbox(cur: &mut Option<BoundaryBbox>, bb: BoundaryBbox) {
        match cur {
            None => *cur = Some(bb),
            Some(existing) => {
                existing.min_x = existing.min_x.min(bb.min_x);
                existing.min_y = existing.min_y.min(bb.min_y);
                existing.max_x = existing.max_x.max(bb.max_x);
                existing.max_y = existing.max_y.max(bb.max_y);
            }
        }
    }
