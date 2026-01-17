use std::collections::HashMap;

use super::{tokenize, ExtractError, Token};

#[derive(Debug, Clone, Default, PartialEq)]
pub struct DsnRulesClearances {
    /// Default clearance (no `type`) in DSN coordinate units.
    pub default_clearance: Option<f64>,
    /// Typed clearances keyed by the `type` token, in DSN coordinate units.
    pub typed: HashMap<String, f64>,
    /// Pairwise clearance matrix keyed by `(a,b)` type tokens, normalized to `(min,max)`.
    pub matrix: HashMap<(String, String), f64>,
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

fn normalize_pair(a: String, b: String) -> (String, String) {
    if a <= b {
        (a, b)
    } else {
        (b, a)
    }
}

fn canonicalize_typed_clearance_key(raw: &str) -> String {
    let k = raw.trim().to_ascii_lowercase();
    match k.as_str() {
        "via_wire" => "wire_via".to_string(),
        "wire_via" => "wire_via".to_string(),
        "via_pin" => "pin_via".to_string(),
        "pin_via" => "pin_via".to_string(),
        "pin_smd" => "smd_pin".to_string(),
        "smd_pin" => "smd_pin".to_string(),
        "via_smd" => "smd_via".to_string(),
        "smd_via" => "smd_via".to_string(),
        "wire_smd" => "default_smd".to_string(),
        "smd_wire" => "default_smd".to_string(),
        "default_smd" => "default_smd".to_string(),
        "area_wire" => "wire_area".to_string(),
        "wire_area" => "wire_area".to_string(),
        "area_via" => "via_area".to_string(),
        "via_area" => "via_area".to_string(),
        "area_pin" => "pin_area".to_string(),
        "pin_area" => "pin_area".to_string(),
        "area_smd" => "smd_area".to_string(),
        "smd_area" => "smd_area".to_string(),
        "area_area" => "area_area".to_string(),
        _ => raw.to_string(),
    }
}

fn parse_type_args(child: &[Token]) -> Option<Vec<String>> {
    // child: (type <arg...>)
    if child.len() < 3 {
        return None;
    }
    if !matches!(child[0], Token::LParen) || !matches!(child[child.len() - 1], Token::RParen) {
        return None;
    }
    if !child.get(1).and_then(tok_str).is_some_and(|s| s.eq_ignore_ascii_case("type")) {
        return None;
    }
    let mut out: Vec<String> = Vec::new();
    for t in &child[2..child.len() - 1] {
        if let Some(s) = tok_str(t) {
            out.push(s.to_string());
        }
    }
    Some(out)
}

fn parse_rule_clearances(rule_tokens: &[Token], out: &mut DsnRulesClearances) {
    // (rule ... (clear <num> [(type ...)] ) ... )
    let mut depth: i32 = 0;
    let mut i = 0usize;
    while i < rule_tokens.len() {
        match &rule_tokens[i] {
            Token::LParen => {
                depth += 1;
                if depth == 2 {
                    let Some(head) = rule_tokens.get(i + 1).and_then(tok_str) else {
                        i += 1;
                        continue;
                    };
                    let end = match find_matching_rparen(rule_tokens, i) {
                        Some(e) => e,
                        None => break,
                    };
                    let child = &rule_tokens[i..=end];
                    if head.eq_ignore_ascii_case("clear") || head.eq_ignore_ascii_case("clearance") {
                        let value = child.get(2).and_then(tok_f64);
                        if let Some(v) = value {
                            // Look for a `(type ...)` sublist.
                            let mut type_args: Option<Vec<String>> = None;
                            let mut j = 0usize;
                            while j < child.len() {
                                if matches!(child.get(j), Some(Token::LParen))
                                    && child.get(j + 1).and_then(tok_str).is_some_and(|h| h.eq_ignore_ascii_case("type"))
                                {
                                    let end_ty = match find_matching_rparen(child, j) {
                                        Some(e) => e,
                                        None => break,
                                    };
                                    type_args = parse_type_args(&child[j..=end_ty]);
                                    break;
                                }
                                j += 1;
                            }
                            match type_args {
                                None => {
                                    if out.default_clearance.is_none() {
                                        out.default_clearance = Some(v);
                                    }
                                }
                                Some(args) => {
                                    if args.len() == 3 && args[1] == "-" {
                                        let key = normalize_pair(args[0].clone(), args[2].clone());
                                        out.matrix.entry(key).or_insert(v);
                                    } else if let Some(first) = args.first() {
                                        out.typed
                                            .entry(canonicalize_typed_clearance_key(first))
                                            .or_insert(v);
                                    }
                                }
                            }
                        }
                    }
                    i = end + 1;
                    depth -= 1;
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

    if out.default_clearance.is_none() {
        if let Some(v) = out.typed.get("default").copied() {
            out.default_clearance = Some(v);
        } else if let Some(v) = out.typed.values().copied().reduce(f64::max) {
            out.default_clearance = Some(v);
        }
    }
}

pub fn extract_rules_clearances(tokens: &[Token]) -> Result<DsnRulesClearances, ExtractError> {
    let mut out = DsnRulesClearances::default();

    let mut depth: i32 = 0;
    let mut in_rules_at: Option<i32> = None;

    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                depth += 1;
                let head = tokens.get(i + 1).and_then(tok_str);
                if head.is_some_and(|h| h.eq_ignore_ascii_case("rules")) {
                    in_rules_at = Some(depth);
                }
                if in_rules_at.is_some_and(|d| d < depth) && head.is_some_and(|h| h.eq_ignore_ascii_case("rule")) {
                    let end = find_matching_rparen(tokens, i).ok_or_else(|| ExtractError {
                        message: "unterminated (rule ...) list".to_string(),
                    })?;
                    parse_rule_clearances(&tokens[i..=end], &mut out);
                    i = end + 1;
                    depth -= 1;
                    continue;
                }
                i += 1;
            }
            Token::RParen => {
                if in_rules_at.is_some_and(|d| d == depth) {
                    in_rules_at = None;
                }
                depth -= 1;
                i += 1;
            }
            _ => i += 1,
        }
    }

    Ok(out)
}

pub fn extract_rules_clearances_from_str(
    input: &str,
) -> Result<DsnRulesClearances, Box<dyn std::error::Error>> {
    let tokens = tokenize(input)?;
    Ok(extract_rules_clearances(&tokens)?)
}
