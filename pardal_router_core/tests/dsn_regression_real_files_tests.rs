use std::path::PathBuf;

use pardal_router_core::dsn::{summarize_dsn, tokenize, Token};

fn repo_path(rel: &str) -> PathBuf {
    let here = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo = here
        .parent()
        .and_then(|p| p.parent())
        .expect("resolve repo root (../.. from crate)");
    repo.join(rel)
}

fn assert_tokens_balanced(tokens: &[Token]) {
    let mut depth: i32 = 0;
    let mut open_stack: Vec<usize> = Vec::new();
    for (i, t) in tokens.iter().enumerate() {
        match t {
            Token::LParen => {
                depth += 1;
                open_stack.push(i);
            }
            Token::RParen => {
                depth -= 1;
                open_stack.pop();
            }
            _ => {}
        }
        assert!(
            depth >= 0,
            "depth went negative at token index {i} (tokens.len()={})",
            tokens.len()
        );
    }
    if depth != 0 {
        let tail_start = tokens.len().saturating_sub(40);
        let tail: Vec<String> = tokens[tail_start..]
            .iter()
            .map(|t| match t {
                Token::LParen => "(".to_string(),
                Token::RParen => ")".to_string(),
                Token::Atom(s) => format!("A:{s}"),
                Token::Str(s) => format!("S:{s}"),
            })
            .collect();
        let mut ctx: Vec<(usize, Vec<String>)> = Vec::new();
        for &open_i in &open_stack[open_stack.len().saturating_sub(8)..] {
            let start = open_i.saturating_sub(6);
            let end = (open_i + 20).min(tokens.len());
            let snippet: Vec<String> = tokens[start..end]
                .iter()
                .map(|t| match t {
                    Token::LParen => "(".to_string(),
                    Token::RParen => ")".to_string(),
                    Token::Atom(s) => format!("A:{s}"),
                    Token::Str(s) => format!("S:{s}"),
                })
                .collect();
            ctx.push((open_i, snippet));
        }
        panic!(
            "final token depth is not zero: depth={depth}, remaining_opens={:?}, open_context={:?}, tail_tokens={:?}",
            &open_stack[open_stack.len().saturating_sub(8)..],
            ctx,
            tail
        );
    }
}

#[test]
fn issue035_read_place_scope_parses_and_summarizes() {
    let txt = std::fs::read_to_string(repo_path("freerouting/tests/Issue035-ReadPlaceScope.dsn"))
        .expect("read");
    let toks = tokenize(&txt).expect("tokenize");
    assert_tokens_balanced(&toks);
    let _summary = summarize_dsn(&txt).expect("summarize");
}
