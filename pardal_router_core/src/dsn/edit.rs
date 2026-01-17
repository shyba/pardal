use super::{tokenize, Token};

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

fn escape_string(s: &str) -> String {
    let mut out = String::new();
    out.push('"');
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            other => out.push(other),
        }
    }
    out.push('"');
    out
}

pub fn tokens_to_string(tokens: &[Token]) -> String {
    let mut out = String::new();
    let mut prev: Option<&Token> = None;

    for t in tokens {
        let need_space = match (prev, t) {
            (None, _) => false,
            (_, Token::RParen) => false,
            (Some(Token::LParen), _) => false,
            (_, Token::LParen) => true,
            _ => true,
        };
        if need_space {
            out.push(' ');
        }

        match t {
            Token::LParen => out.push('('),
            Token::RParen => out.push(')'),
            Token::Atom(s) => out.push_str(s),
            Token::Str(s) => out.push_str(&escape_string(s)),
        }
        prev = Some(t);
    }

    out.push('\n');
    out
}

/// Append DSN wiring expressions into an existing DSN.
///
/// - If `(wiring ...)` exists as a direct child of `(pcb ...)`, new items are appended inside it.
/// - Otherwise, a new `(wiring ...)` block is created at the end of the `(pcb ...)` block.
///
/// `wiring_exprs` must be valid DSN S-expressions like `(wire ...)` or `(via ...)`.
pub fn append_wiring_exprs(dsn: &str, wiring_exprs: &[String]) -> Result<String, String> {
    if wiring_exprs.is_empty() {
        return Ok(dsn.to_string());
    }

    let mut tokens = tokenize(dsn).map_err(|e| e.to_string())?;

    // Find `(pcb ...)` top-level.
    let mut pcb_start: Option<usize> = None;
    for i in 0..tokens.len().saturating_sub(1) {
        if matches!(tokens.get(i), Some(Token::LParen))
            && tokens.get(i + 1).and_then(tok_str).is_some_and(|s| s.eq_ignore_ascii_case("pcb"))
        {
            pcb_start = Some(i);
            break;
        }
    }
    let pcb_start = pcb_start.ok_or_else(|| "no (pcb ...) scope found".to_string())?;
    let pcb_end = find_matching_rparen(&tokens, pcb_start).ok_or_else(|| "unclosed (pcb ...)".to_string())?;

    // Tokenize new wiring expressions.
    let mut new_tokens: Vec<Token> = Vec::new();
    for expr in wiring_exprs {
        let expr_tokens = tokenize(expr).map_err(|e| format!("invalid wiring expr: {e}"))?;
        new_tokens.extend(expr_tokens);
    }

    // Find an existing direct-child `(wiring ...)`.
    let mut wiring_start: Option<usize> = None;
    let mut wiring_end: Option<usize> = None;
    let mut depth: i32 = 0;
    for i in pcb_start..=pcb_end {
        match tokens[i] {
            Token::LParen => {
                depth += 1;
                if depth == 2 {
                    if tokens
                        .get(i + 1)
                        .and_then(tok_str)
                        .is_some_and(|s| s.eq_ignore_ascii_case("wiring"))
                    {
                        wiring_start = Some(i);
                        wiring_end = find_matching_rparen(&tokens, i);
                        break;
                    }
                }
            }
            Token::RParen => depth -= 1,
            _ => {}
        }
    }

    if let (Some(_ws), Some(we)) = (wiring_start, wiring_end) {
        // Insert before the closing rparen of the wiring list.
        tokens.splice(we..we, new_tokens.into_iter());
        return Ok(tokens_to_string(&tokens));
    }

    // No wiring block; create one before the end of pcb.
    let mut wiring_block: Vec<Token> = Vec::new();
    wiring_block.push(Token::LParen);
    wiring_block.push(Token::Atom("wiring".to_string()));
    wiring_block.extend(new_tokens);
    wiring_block.push(Token::RParen);

    tokens.splice(pcb_end..pcb_end, wiring_block.into_iter());
    Ok(tokens_to_string(&tokens))
}

