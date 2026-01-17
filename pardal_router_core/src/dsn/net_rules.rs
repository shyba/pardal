use std::collections::HashMap;

use super::{tokenize, ExtractError, Token};

#[derive(Debug, Clone, Default, PartialEq)]
pub struct DsnRule {
    pub width: Option<f64>,
    pub clearance: Option<f64>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct DsnNetClass {
    pub name: String,
    pub nets: Vec<String>,
    pub rule: DsnRule,
    pub clearance_class: Option<String>,
    pub via_rule: Option<String>,
    pub use_via: Option<String>,
    pub use_layers: Vec<String>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct DsnNetRules {
    pub default_rule: DsnRule,
    /// Typed clearances extracted from `structure` rules, e.g. `default_smd`, `wire_via`, `pin_pin`.
    ///
    /// Values are in DSN coordinate units (same as other rule numbers).
    pub typed_clearances: HashMap<String, f64>,
    pub classes: HashMap<String, DsnNetClass>,
    pub net_to_class: HashMap<String, String>,
    pub via_rules: HashMap<String, String>, // name -> padstack
}

impl DsnNetRules {
    pub fn clearance_for_net(&self, net_name: &str) -> Option<f64> {
        let class = self.net_to_class.get(net_name)?;
        self.classes
            .get(class)
            .and_then(|c| c.rule.clearance)
            .or(self.default_rule.clearance)
    }

    pub fn width_for_net(&self, net_name: &str) -> Option<f64> {
        let class = self.net_to_class.get(net_name)?;
        self.classes
            .get(class)
            .and_then(|c| c.rule.width)
            .or(self.default_rule.width)
    }
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

fn parse_rule_scope(tokens: &[Token]) -> DsnRule {
    // (rule (width <num>) (clear|clearance <num>) ... )
    let mut out = DsnRule::default();
    let mut depth: i32 = 0;
    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                depth += 1;
                if depth == 2 {
                    let Some(head) = tokens.get(i + 1).and_then(tok_str) else {
                        i += 1;
                        continue;
                    };
                    let end = match find_matching_rparen(tokens, i) {
                        Some(e) => e,
                        None => break,
                    };
                    let child = &tokens[i..=end];

                    if head.eq_ignore_ascii_case("width") && out.width.is_none() {
                        out.width = child.get(2).and_then(tok_f64);
                    }
                    if (head.eq_ignore_ascii_case("clear") || head.eq_ignore_ascii_case("clearance"))
                        && out.clearance.is_none()
                    {
                        // Prefer the simple form (clear <num>) without extra args.
                        if child.len() == 4 {
                            out.clearance = child.get(2).and_then(tok_f64);
                        } else {
                            out.clearance = child.get(2).and_then(tok_f64);
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
    out
}

fn parse_rule_scope_typed_clearances(tokens: &[Token]) -> (Option<f64>, Option<f64>, Vec<(String, f64)>) {
    // (rule (width <num>) (clear|clearance <num> [(type <name>)] ) ... )
    let mut width: Option<f64> = None;
    let mut default_clearance: Option<f64> = None;
    let mut typed: Vec<(String, f64)> = Vec::new();

    let mut depth: i32 = 0;
    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                depth += 1;
                if depth == 2 {
                    let Some(head) = tokens.get(i + 1).and_then(tok_str) else {
                        i += 1;
                        continue;
                    };
                    let end = match find_matching_rparen(tokens, i) {
                        Some(e) => e,
                        None => break,
                    };
                    let child = &tokens[i..=end];

                    if head.eq_ignore_ascii_case("width") && width.is_none() {
                        width = child.get(2).and_then(tok_f64);
                    }

                    if head.eq_ignore_ascii_case("clear") || head.eq_ignore_ascii_case("clearance") {
                        let value = child.get(2).and_then(tok_f64);
                        if let Some(v) = value {
                            // Find an optional `(type <name ...>)` sublist.
                            let mut ty: Option<String> = None;
                            let mut j = 0usize;
                            while j < child.len() {
                                if matches!(child.get(j), Some(Token::LParen))
                                    && child.get(j + 1).and_then(tok_str).is_some_and(|h| h.eq_ignore_ascii_case("type"))
                                {
                                    ty = child.get(j + 2).and_then(tok_str).map(|s| s.to_string());
                                    break;
                                }
                                j += 1;
                            }
                            if let Some(t) = ty {
                                typed.push((canonicalize_typed_clearance_key(&t), v));
                            } else if default_clearance.is_none() {
                                default_clearance = Some(v);
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

    (width, default_clearance, typed)
}

fn canonicalize_typed_clearance_key(raw: &str) -> String {
    // Specctra/Freerouting typed clearance names appear in multiple spellings across exporters.
    // We normalize the common symmetric ones into a canonical form expected by the nm layer.
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

fn parse_structure_default_rule_and_typed(tokens: &[Token]) -> (DsnRule, HashMap<String, f64>) {
    // Find (structure ... (rule ...) ...) and collect width, a default clearance, plus typed clearances.
    let mut depth: i32 = 0;
    let mut in_structure_at: Option<i32> = None;

    let mut out = DsnRule::default();
    let mut typed: HashMap<String, f64> = HashMap::new();

    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                depth += 1;
                let head = tokens.get(i + 1).and_then(tok_str);
                if head.is_some_and(|h| h.eq_ignore_ascii_case("structure")) {
                    in_structure_at = Some(depth);
                }
                if in_structure_at.is_some_and(|d| d < depth)
                    && head.is_some_and(|h| h.eq_ignore_ascii_case("rule"))
                {
                    let end = match find_matching_rparen(tokens, i) {
                        Some(e) => e,
                        None => break,
                    };
                    let (w, c, pairs) = parse_rule_scope_typed_clearances(&tokens[i..=end]);
                    if out.width.is_none() {
                        out.width = w;
                    }
                    if out.clearance.is_none() {
                        out.clearance = c;
                    }
                    for (k, v) in pairs {
                        typed.entry(canonicalize_typed_clearance_key(&k)).or_insert(v);
                    }

                    i = end + 1;
                    depth -= 1;
                    continue;
                }
                i += 1;
            }
            Token::RParen => {
                if in_structure_at.is_some_and(|d| d == depth) {
                    in_structure_at = None;
                }
                depth -= 1;
                i += 1;
            }
            _ => i += 1,
        }
    }

    // If no untyped clearance exists, pick a conservative default from known typed keys or the maximum typed value.
    if out.clearance.is_none() {
        if let Some(v) = typed.get("default_smd").copied() {
            out.clearance = Some(v);
        } else if let Some(v) = typed.values().copied().reduce(f64::max) {
            out.clearance = Some(v);
        }
    }

    (out, typed)
}

fn parse_circuit_scope(tokens: &[Token]) -> (Option<String>, Vec<String>) {
    // (circuit (use_via <padstack>) (use_layer <l0> <l1> ...) ...)
    let mut use_via: Option<String> = None;
    let mut use_layers: Vec<String> = Vec::new();

    let mut depth: i32 = 0;
    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                depth += 1;
                if depth == 2 {
                    let Some(head) = tokens.get(i + 1).and_then(tok_str) else {
                        i += 1;
                        continue;
                    };
                    let end = match find_matching_rparen(tokens, i) {
                        Some(e) => e,
                        None => break,
                    };
                    let child = &tokens[i..=end];

                    if head.eq_ignore_ascii_case("use_via") {
                        use_via = child.get(2).and_then(tok_str).map(|s| s.to_string());
                    } else if head.eq_ignore_ascii_case("use_layer") {
                        for t in &child[2..child.len().saturating_sub(1)] {
                            if let Some(s) = tok_str(t) {
                                use_layers.push(s.to_string());
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

    use_layers.sort();
    use_layers.dedup();
    (use_via, use_layers)
}

fn parse_via_rule_scope(tokens: &[Token]) -> Option<(String, String)> {
    // (via_rule <name> <padstack>)
    if tokens.len() < 4 {
        return None;
    }
    if !matches!(tokens[0], Token::LParen) || !matches!(tokens[tokens.len() - 1], Token::RParen) {
        return None;
    }
    let head = tokens.get(1).and_then(tok_str)?;
    if !head.eq_ignore_ascii_case("via_rule") {
        return None;
    }
    let name = tokens.get(2).and_then(tok_str)?.to_string();
    let padstack = tokens.get(3).and_then(tok_str)?.to_string();
    Some((name, padstack))
}

fn parse_class_scope(tokens: &[Token]) -> Option<DsnNetClass> {
    // (class <name> [<nets...>] (clearance_class ...) (via_rule ...) (rule ...) (circuit ...) ...)
    if tokens.len() < 4 {
        return None;
    }
    if !matches!(tokens[0], Token::LParen) || !matches!(tokens[tokens.len() - 1], Token::RParen) {
        return None;
    }
    let head = tokens.get(1).and_then(tok_str)?;
    if !head.eq_ignore_ascii_case("class") {
        return None;
    }
    let name = tokens.get(2).and_then(tok_str)?.to_string();
    let mut out = DsnNetClass {
        name: name.clone(),
        ..Default::default()
    };

    // Nets list: sequence of atoms/strings after the class name until the first '('.
    let mut i = 3usize;
    while i < tokens.len().saturating_sub(1) {
        match &tokens[i] {
            Token::LParen => break,
            Token::Atom(s) | Token::Str(s) => out.nets.push(s.clone()),
            Token::RParen => break,
        }
        i += 1;
    }

    let mut depth: i32 = 0;
    let mut j = 0usize;
    while j < tokens.len() {
        match &tokens[j] {
            Token::LParen => {
                depth += 1;
                if depth == 2 {
                    let Some(child_head) = tokens.get(j + 1).and_then(tok_str) else {
                        j += 1;
                        continue;
                    };
                    let end = find_matching_rparen(tokens, j)?;
                    let child = &tokens[j..=end];

                    if child_head.eq_ignore_ascii_case("rule") {
                        out.rule = parse_rule_scope(child);
                    } else if child_head.eq_ignore_ascii_case("circuit") {
                        let (use_via, use_layers) = parse_circuit_scope(child);
                        out.use_via = use_via;
                        out.use_layers = use_layers;
                    } else if child_head.eq_ignore_ascii_case("clearance_class") {
                        out.clearance_class = child.get(2).and_then(tok_str).map(|s| s.to_string());
                    } else if child_head.eq_ignore_ascii_case("via_rule") {
                        out.via_rule = child.get(2).and_then(tok_str).map(|s| s.to_string());
                    }

                    j = end + 1;
                    depth -= 1;
                    continue;
                }
                j += 1;
            }
            Token::RParen => {
                depth -= 1;
                j += 1;
            }
            _ => j += 1,
        }
    }

    out.nets.sort();
    out.nets.dedup();
    Some(out)
}

pub fn extract_net_rules(tokens: &[Token]) -> Result<DsnNetRules, ExtractError> {
    let mut out = DsnNetRules::default();
    let (default_rule, typed) = parse_structure_default_rule_and_typed(tokens);
    out.default_rule = default_rule;
    out.typed_clearances = typed;

    let mut depth: i32 = 0;
    let mut in_network_at: Option<i32> = None;

    let mut i = 0usize;
    while i < tokens.len() {
        match &tokens[i] {
            Token::LParen => {
                depth += 1;
                let head = tokens.get(i + 1).and_then(tok_str);
                if head.is_some_and(|h| h.eq_ignore_ascii_case("network")) {
                    in_network_at = Some(depth);
                }
                if in_network_at.is_some_and(|d| d < depth) {
                    if head.is_some_and(|h| h.eq_ignore_ascii_case("class")) {
                        let end = find_matching_rparen(tokens, i).ok_or_else(|| ExtractError {
                            message: "unterminated (class ...) list".to_string(),
                        })?;
                        if let Some(cls) = parse_class_scope(&tokens[i..=end]) {
                            for net in &cls.nets {
                                out.net_to_class.insert(net.clone(), cls.name.clone());
                            }
                            out.classes.insert(cls.name.clone(), cls);
                        }
                        i = end + 1;
                        depth -= 1;
                        continue;
                    }
                    if head.is_some_and(|h| h.eq_ignore_ascii_case("via_rule")) {
                        let end = find_matching_rparen(tokens, i).ok_or_else(|| ExtractError {
                            message: "unterminated (via_rule ...) list".to_string(),
                        })?;
                        if let Some((name, padstack)) = parse_via_rule_scope(&tokens[i..=end]) {
                            out.via_rules.insert(name, padstack);
                        }
                        i = end + 1;
                        depth -= 1;
                        continue;
                    }
                }
                i += 1;
            }
            Token::RParen => {
                if in_network_at.is_some_and(|d| d == depth) {
                    in_network_at = None;
                }
                depth -= 1;
                i += 1;
            }
            _ => i += 1,
        }
    }

    Ok(out)
}

pub fn extract_net_rules_from_str(input: &str) -> Result<DsnNetRules, Box<dyn std::error::Error>> {
    let tokens = tokenize(input)?;
    Ok(extract_net_rules(&tokens)?)
}
