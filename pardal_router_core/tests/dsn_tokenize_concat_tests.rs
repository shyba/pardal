use pardal_router_core::dsn::{extract_model_from_str, tokenize, Token};

#[test]
fn tokenize_concatenated_quoted_strings_emit_dash_atom() {
    let toks = tokenize(r#"(pins "J3"-"D+")"#).expect("tokenize");
    assert_eq!(
        toks,
        vec![
            Token::LParen,
            Token::Atom("pins".to_string()),
            Token::Str("J3".to_string()),
            Token::Atom("-".to_string()),
            Token::Str("D+".to_string()),
            Token::RParen,
        ]
    );
}

#[test]
fn extract_model_joins_concatenated_pin_refs() {
    let dsn = r#"
(pcb demo
  (network
    (net N$1 (pins "J3"-"D+" "J3"-"D-"))
  )
)
"#;
    let m = extract_model_from_str(dsn).expect("extract model");
    let net = m.nets.get("N$1").expect("net");
    assert_eq!(net.pins, vec!["J3-D+".to_string(), "J3-D-".to_string()]);
}
