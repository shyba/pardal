use std::collections::HashMap;
use std::path::PathBuf;

use pardal_router_core::dsn::{extract_model_from_str, extract_wiring_from_str, summarize_dsn};
use pardal_router_core::dsn_to_nm::dsn_to_board_nm;
use pardal_router_core::ses::write_ses_minimal;

fn usage() -> ! {
    eprintln!(
        "Usage:\n  pardal_dsn_to_ses <path.dsn> <out.ses> [session_name] [base_design_name]\n\n\
Creates a Specctra SES from DSN wiring using `write_ses_minimal`.\n\
Defaults:\n\
  session_name = <out.ses filename>\n\
  base_design_name = <dsn filename>\n"
    );
    std::process::exit(2);
}

fn main() {
    let mut args = std::env::args().skip(1);
    let Some(dsn_path) = args.next() else { usage() };
    let Some(out_path) = args.next() else { usage() };
    let session_name = args
        .next()
        .unwrap_or_else(|| PathBuf::from(&out_path).file_name().unwrap_or_default().to_string_lossy().to_string());
    let base_design_name = args
        .next()
        .unwrap_or_else(|| PathBuf::from(&dsn_path).file_name().unwrap_or_default().to_string_lossy().to_string());

    if args.next().is_some() {
        usage();
    }

    let bytes = std::fs::read(&dsn_path).unwrap_or_else(|e| {
        eprintln!("Failed to read {dsn_path}: {e}");
        std::process::exit(1);
    });
    let dsn_cow = String::from_utf8_lossy(&bytes);
    let dsn: &str = &dsn_cow;

    let summary = summarize_dsn(dsn).unwrap_or_else(|e| {
        eprintln!("summarize_dsn failed: {e}");
        std::process::exit(1);
    });
    let model = extract_model_from_str(dsn).unwrap_or_else(|e| {
        eprintln!("extract_model_from_str failed: {e}");
        std::process::exit(1);
    });
    let wiring = extract_wiring_from_str(dsn).unwrap_or_else(|e| {
        eprintln!("extract_wiring_from_str failed: {e}");
        std::process::exit(1);
    });
    let board = dsn_to_board_nm(&summary, &model, &wiring).unwrap_or_else(|e| {
        eprintln!("dsn_to_board_nm failed: {e}");
        std::process::exit(1);
    });

    let mut id_to_name: HashMap<u32, String> = HashMap::new();
    for (name, id) in &board.net_name_to_id {
        id_to_name.insert(*id, name.clone());
    }

    let ses = write_ses_minimal(
        &session_name,
        &base_design_name,
        &summary,
        &model,
        &board.tracks,
        &board.vias,
        &id_to_name,
    );

    std::fs::write(&out_path, ses).unwrap_or_else(|e| {
        eprintln!("Failed to write {out_path}: {e}");
        std::process::exit(1);
    });
}
