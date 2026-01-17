use std::collections::HashMap;

use super::{tokenize, ExtractError, Token};

#[derive(Debug, Clone, PartialEq)]
pub struct DsnLayerRule {
    pub layer: String,
    pub active: Option<bool>,
    pub preferred_direction: Option<String>,
    pub preferred_direction_trace_costs: Option<f64>,
    pub against_preferred_direction_trace_costs: Option<f64>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct DsnAutorouteSettings {
    pub fanout: Option<bool>,
    pub router_enabled: Option<bool>,
    pub postroute: Option<bool>,
    pub vias: Option<bool>,
    pub via_costs: Option<i64>,
    pub plane_via_costs: Option<i64>,
    pub start_ripup_costs: Option<i64>,
    pub start_pass_no: Option<i64>,
    pub layers: HashMap<String, DsnLayerRule>,
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

fn tok_i64(tok: &Token) -> Option<i64> {
    tok_str(tok)?.parse::<i64>().ok()
}

fn parse_on_off(s: &str) -> Option<bool> {
    if s.eq_ignore_ascii_case("on") {
        Some(true)
    } else if s.eq_ignore_ascii_case("off") {
        Some(false)
    } else {
        None
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

fn parse_simple_pair_bool(child: &[Token]) -> Option<bool> {
    // (key on/off)
    let v = child.get(2).and_then(tok_str)?;
    parse_on_off(v)
}

fn parse_simple_pair_i64(child: &[Token]) -> Option<i64> {
    child.get(2).and_then(tok_i64)
}

fn parse_simple_pair_f64(child: &[Token]) -> Option<f64> {
    child.get(2).and_then(tok_f64)
}

fn parse_layer_rule(child: &[Token]) -> Option<DsnLayerRule> {
    // (layer_rule <layer>
    //   (active on/off)
    //   (preferred_direction horizontal/vertical/...)
    //   (preferred_direction_trace_costs <float>)
    //   (against_preferred_direction_trace_costs <float>)
    // )
    if child.len() < 5 {
        return None;
    }
    let head = child.get(1).and_then(tok_str)?;
    if !head.eq_ignore_ascii_case("layer_rule") {
        return None;
    }
    let layer = child.get(2).and_then(tok_str)?.to_string();
    let mut out = DsnLayerRule {
        layer: layer.clone(),
        active: None,
        preferred_direction: None,
        preferred_direction_trace_costs: None,
        against_preferred_direction_trace_costs: None,
    };

    let mut depth: i32 = 0;
    let mut i = 0usize;
    while i < child.len() {
        match &child[i] {
            Token::LParen => {
                depth += 1;
                if depth == 2 {
                    let Some(sub_head) = child.get(i + 1).and_then(tok_str) else {
                        i += 1;
                        continue;
                    };
                    let end = find_matching_rparen(child, i)?;
                    let sub = &child[i..=end];

                    if sub_head.eq_ignore_ascii_case("active") {
                        out.active = parse_simple_pair_bool(sub);
                    } else if sub_head.eq_ignore_ascii_case("preferred_direction") {
                        out.preferred_direction = sub.get(2).and_then(tok_str).map(|s| s.to_string());
                    } else if sub_head.eq_ignore_ascii_case("preferred_direction_trace_costs") {
                        out.preferred_direction_trace_costs = parse_simple_pair_f64(sub);
                    } else if sub_head.eq_ignore_ascii_case("against_preferred_direction_trace_costs") {
                        out.against_preferred_direction_trace_costs = parse_simple_pair_f64(sub);
                    }

                    i = end + 1;
                    depth -= 1; // consumed matching ')'
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

    Some(out)
}

fn parse_autoroute_settings_scope(tokens: &[Token]) -> Option<DsnAutorouteSettings> {
    // tokens: (autoroute_settings <children...>)
    if tokens.len() < 3 {
        return None;
    }
    if !matches!(tokens[0], Token::LParen) || !matches!(tokens[tokens.len() - 1], Token::RParen) {
        return None;
    }
    let head = tokens.get(1).and_then(tok_str)?;
    if !head.eq_ignore_ascii_case("autoroute_settings") {
        return None;
    }

    let mut out = DsnAutorouteSettings::default();

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

                    if child_head.eq_ignore_ascii_case("layer_rule") {
                        if let Some(rule) = parse_layer_rule(child) {
                            out.layers.insert(rule.layer.clone(), rule);
                        }
                    } else if child_head.eq_ignore_ascii_case("fanout") {
                        out.fanout = parse_simple_pair_bool(child);
                    } else if child_head.eq_ignore_ascii_case("postroute") {
                        out.postroute = parse_simple_pair_bool(child);
                    } else if child_head.eq_ignore_ascii_case("vias") {
                        out.vias = parse_simple_pair_bool(child);
                    } else if child_head.eq_ignore_ascii_case("via_costs") {
                        out.via_costs = parse_simple_pair_i64(child);
                    } else if child_head.eq_ignore_ascii_case("plane_via_costs") {
                        out.plane_via_costs = parse_simple_pair_i64(child);
                    } else if child_head.eq_ignore_ascii_case("start_ripup_costs") {
                        out.start_ripup_costs = parse_simple_pair_i64(child);
                    } else if child_head.eq_ignore_ascii_case("start_pass_no") {
                        out.start_pass_no = parse_simple_pair_i64(child);
                    } else if child_head.eq_ignore_ascii_case("eu.mihosoft.freerouting.autoroute") {
                        out.router_enabled = parse_simple_pair_bool(child);
                    }

                    i = end + 1;
                    depth -= 1; // consumed matching ')'
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

    Some(out)
}

pub fn extract_autoroute_settings(tokens: &[Token]) -> Result<Option<DsnAutorouteSettings>, ExtractError> {
    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                if tokens
                    .get(i + 1)
                    .and_then(tok_str)
                    .is_some_and(|h| h.eq_ignore_ascii_case("autoroute_settings"))
                {
                    let end = find_matching_rparen(tokens, i).ok_or_else(|| ExtractError {
                        message: "unterminated (autoroute_settings ...) list".to_string(),
                    })?;
                    let scope = &tokens[i..=end];
                    return Ok(parse_autoroute_settings_scope(scope));
                }
                i += 1;
            }
            Token::RParen => {
                i += 1;
            }
            _ => i += 1,
        }
    }
    Ok(None)
}

pub fn extract_autoroute_settings_from_str(
    input: &str,
) -> Result<Option<DsnAutorouteSettings>, Box<dyn std::error::Error>> {
    let tokens = tokenize(input)?;
    Ok(extract_autoroute_settings(&tokens)?)
}
