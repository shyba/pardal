use super::{tokenize, ExtractError, Token};

#[derive(Debug, Clone, PartialEq)]
pub struct DsnWire {
    /// `path` or `polyline_path`
    pub path_kind: String,
    /// Layer token from DSN (`"F.Cu"`, `"B.Cu"`, or a 1-based numeric layer index)
    pub layer: String,
    pub width: f64,
    pub points: Vec<(f64, f64)>,
    pub net: String,
    pub clearance_class: Option<String>,
    pub wire_type: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DsnVia {
    pub padstack: String,
    pub x: f64,
    pub y: f64,
    pub net: String,
    pub clearance_class: Option<String>,
    pub via_type: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct DsnWiring {
    pub wires: Vec<DsnWire>,
    pub vias: Vec<DsnVia>,
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

fn parse_path_list(tokens: &[Token]) -> Option<(String, String, f64, Vec<(f64, f64)>)> {
    // tokens: ( <kind> <layer> <width> <x0> <y0> <x1> <y1> ... )
    if tokens.len() < 6 {
        return None;
    }
    if !matches!(tokens[0], Token::LParen) || !matches!(tokens[tokens.len() - 1], Token::RParen) {
        return None;
    }
    let kind = tok_str(&tokens[1])?.to_string();
    if !(kind.eq_ignore_ascii_case("path") || kind.eq_ignore_ascii_case("polyline_path")) {
        return None;
    }
    let layer = tok_str(&tokens[2])?.to_string();
    let width = tok_f64(&tokens[3])?;

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
    Some((kind, layer, width, points))
}

fn parse_simple_kv_list(tokens: &[Token]) -> Option<(String, Vec<String>)> {
    // tokens: ( <head> <arg1> <arg2> ... )
    if tokens.len() < 3 {
        return None;
    }
    if !matches!(tokens[0], Token::LParen) || !matches!(tokens[tokens.len() - 1], Token::RParen) {
        return None;
    }
    let head = tok_str(&tokens[1])?.to_string();
    let mut args: Vec<String> = Vec::new();
    for t in &tokens[2..tokens.len() - 1] {
        if let Some(s) = tok_str(t) {
            args.push(s.to_string());
        }
    }
    Some((head, args))
}

fn parse_wire_list(tokens: &[Token]) -> Option<DsnWire> {
    // tokens: ( wire <child lists>... )
    if tokens.len() < 4 {
        return None;
    }
    if !matches!(tokens[0], Token::LParen) || !matches!(tokens[tokens.len() - 1], Token::RParen) {
        return None;
    }
    let head = tok_str(&tokens[1])?;
    if !head.eq_ignore_ascii_case("wire") {
        return None;
    }

    let mut net: Option<String> = None;
    let mut clearance_class: Option<String> = None;
    let mut wire_type: Option<String> = None;
    let mut path: Option<(String, String, f64, Vec<(f64, f64)>)> = None;

    let mut depth: i32 = 0;
    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                depth += 1;
                if depth == 2 {
                    let Some(child_head) = tokens.get(i + 1).and_then(tok_str) else {
                        i += 1;
                        continue;
                    };
                    let end = find_matching_rparen(tokens, i)?;
                    let child = &tokens[i..=end];

                    if child_head.eq_ignore_ascii_case("path") || child_head.eq_ignore_ascii_case("polyline_path") {
                        if path.is_none() {
                            path = parse_path_list(child);
                        }
                    } else if child_head.eq_ignore_ascii_case("net") {
                        if let Some((_h, args)) = parse_simple_kv_list(child) {
                            if let Some(name) = args.first() {
                                net = Some(name.clone());
                            }
                        }
                    } else if child_head.eq_ignore_ascii_case("clearance_class") {
                        if let Some((_h, args)) = parse_simple_kv_list(child) {
                            clearance_class = args.first().cloned();
                        }
                    } else if child_head.eq_ignore_ascii_case("type") {
                        if let Some((_h, args)) = parse_simple_kv_list(child) {
                            wire_type = args.first().cloned();
                        }
                    }

                    i = end + 1;
                    depth -= 1; // we consumed the matching ')'
                    continue;
                }
                i += 1;
            }
            Token::RParen => {
                depth -= 1;
                i += 1;
            }
            _ => i += 1,
        }
    }

    let (path_kind, layer, width, points) = path?;
    let net = net?;
    Some(DsnWire {
        path_kind,
        layer,
        width,
        points,
        net,
        clearance_class,
        wire_type,
    })
}

fn parse_via_list(tokens: &[Token]) -> Option<DsnVia> {
    // tokens: ( via <padstack> <x> <y> <child lists>... )
    if tokens.len() < 6 {
        return None;
    }
    if !matches!(tokens[0], Token::LParen) || !matches!(tokens[tokens.len() - 1], Token::RParen) {
        return None;
    }
    let head = tok_str(&tokens[1])?;
    if !head.eq_ignore_ascii_case("via") {
        return None;
    }

    let padstack = tok_str(&tokens[2])?.to_string();
    let x = tok_f64(&tokens[3])?;
    let y = tok_f64(&tokens[4])?;

    let mut net: Option<String> = None;
    let mut clearance_class: Option<String> = None;
    let mut via_type: Option<String> = None;

    let mut depth: i32 = 0;
    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                depth += 1;
                if depth == 2 {
                    let Some(child_head) = tokens.get(i + 1).and_then(tok_str) else {
                        i += 1;
                        continue;
                    };
                    let end = find_matching_rparen(tokens, i)?;
                    let child = &tokens[i..=end];

                    if child_head.eq_ignore_ascii_case("net") {
                        if let Some((_h, args)) = parse_simple_kv_list(child) {
                            if let Some(name) = args.first() {
                                net = Some(name.clone());
                            }
                        }
                    } else if child_head.eq_ignore_ascii_case("clearance_class") {
                        if let Some((_h, args)) = parse_simple_kv_list(child) {
                            clearance_class = args.first().cloned();
                        }
                    } else if child_head.eq_ignore_ascii_case("type") {
                        if let Some((_h, args)) = parse_simple_kv_list(child) {
                            via_type = args.first().cloned();
                        }
                    }

                    i = end + 1;
                    depth -= 1; // we consumed the matching ')'
                    continue;
                }
                i += 1;
            }
            Token::RParen => {
                depth -= 1;
                i += 1;
            }
            _ => i += 1,
        }
    }

    let net = net?;
    Some(DsnVia {
        padstack,
        x,
        y,
        net,
        clearance_class,
        via_type,
    })
}

pub fn extract_wiring(tokens: &[Token]) -> Result<DsnWiring, ExtractError> {
    let mut wiring = DsnWiring::default();

    let mut depth: i32 = 0;
    let mut wiring_depth: Option<i32> = None;

    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                let head = tokens.get(i + 1).and_then(tok_str);

                // Enter wiring list: (wiring ...)
                if head.is_some_and(|h| h.eq_ignore_ascii_case("wiring")) {
                    depth += 1;
                    wiring_depth = Some(depth);
                    i += 2;
                    continue;
                }

                // Direct children of wiring: (wire ...) / (via ...)
                if wiring_depth.is_some_and(|wd| wd == depth) {
                    if head.is_some_and(|h| h.eq_ignore_ascii_case("wire") || h.eq_ignore_ascii_case("via")) {
                        let end = find_matching_rparen(tokens, i).ok_or_else(|| ExtractError {
                            message: "unterminated (wire)/(via) list in wiring scope".to_string(),
                        })?;
                        let list = &tokens[i..=end];
                        if head.is_some_and(|h| h.eq_ignore_ascii_case("wire")) {
                            if let Some(w) = parse_wire_list(list) {
                                wiring.wires.push(w);
                            }
                        } else if let Some(v) = parse_via_list(list) {
                            wiring.vias.push(v);
                        }
                        i = end + 1;
                        continue;
                    }
                }

                depth += 1;
                i += 1;
            }
            Token::RParen => {
                if wiring_depth.is_some_and(|wd| wd == depth) {
                    wiring_depth = None;
                }
                depth -= 1;
                i += 1;
            }
            _ => i += 1,
        }
    }

    Ok(wiring)
}

pub fn extract_wiring_from_str(input: &str) -> Result<DsnWiring, Box<dyn std::error::Error>> {
    let tokens = tokenize(input)?;
    Ok(extract_wiring(&tokens)?)
}

