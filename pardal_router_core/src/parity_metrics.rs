use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct NormalizedMetrics {
    pub layers_total: Option<u64>,
    pub connections_incomplete: Option<u64>,
    pub clearance_violations_total: Option<u64>,
    pub unconnected_items_total: Option<u64>,
}

fn get_u64_path(v: &serde_json::Value, path: &[&str]) -> Option<u64> {
    let mut cur = v;
    for k in path {
        cur = cur.get(*k)?;
    }
    cur.as_u64()
}

fn get_array_len(v: &serde_json::Value, key: &str) -> Option<u64> {
    v.get(key)?.as_array().map(|a| a.len() as u64)
}

fn get_clearance_violation_count(v: &serde_json::Value) -> Option<u64> {
    if let Some(n) = get_array_len(v, "clearance_violations") {
        return Some(n);
    }
    let violations = v.get("violations")?.as_array()?;
    Some(
        violations
            .iter()
            .filter(|it| it.get("type").and_then(|t| t.as_str()) == Some("clearance"))
            .count() as u64,
    )
}

pub fn normalized_from_freerouting_boardstatistics_json(v: &serde_json::Value) -> NormalizedMetrics {
    NormalizedMetrics {
        layers_total: get_u64_path(v, &["layers", "total_count"]),
        connections_incomplete: get_u64_path(v, &["connections", "incomplete_count"]),
        clearance_violations_total: get_u64_path(v, &["clearance_violations", "total_count"]),
        unconnected_items_total: None,
    }
}

pub fn normalized_from_freerouting_drc_json(v: &serde_json::Value) -> NormalizedMetrics {
    NormalizedMetrics {
        layers_total: None,
        connections_incomplete: None,
        clearance_violations_total: get_clearance_violation_count(v),
        unconnected_items_total: get_array_len(v, "unconnected_items"),
    }
}

pub fn parse_freerouting_metrics_json_str(s: &str) -> Result<NormalizedMetrics, String> {
    let v: serde_json::Value = serde_json::from_str(s).map_err(|e| e.to_string())?;

    // Heuristic: BoardStatistics has `connections`, DRC has `unconnected_items`.
    if v.get("connections").is_some() {
        Ok(normalized_from_freerouting_boardstatistics_json(&v))
    } else if v.get("unconnected_items").is_some() {
        Ok(normalized_from_freerouting_drc_json(&v))
    } else {
        Err("unrecognized metrics JSON (missing `connections` or `unconnected_items`)".to_string())
    }
}
