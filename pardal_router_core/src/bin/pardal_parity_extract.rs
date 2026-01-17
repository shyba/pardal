use std::path::PathBuf;

use pardal_router_core::parity_metrics::parse_freerouting_metrics_json_str;

fn usage() -> ! {
    eprintln!("Usage: pardal_parity_extract <path.json>");
    std::process::exit(2);
}

fn main() {
    let mut args = std::env::args().skip(1);
    let Some(path) = args.next() else { usage() };
    if args.next().is_some() {
        usage();
    }

    let bytes = std::fs::read(&path).unwrap_or_else(|e| {
        eprintln!("Failed to read {path}: {e}");
        std::process::exit(1);
    });
    let s = String::from_utf8_lossy(&bytes);
    let m = parse_freerouting_metrics_json_str(&s).unwrap_or_else(|e| {
        eprintln!("Failed to parse metrics: {e}");
        std::process::exit(1);
    });

    let json = serde_json::to_string_pretty(&m).unwrap_or_else(|e| {
        eprintln!("Failed to serialize metrics: {e}");
        std::process::exit(1);
    });
    println!("{json}");

    // Hint for humans running it.
    eprintln!("ok: {}", PathBuf::from(&path).display());
}

