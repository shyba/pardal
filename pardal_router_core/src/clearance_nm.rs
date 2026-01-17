use std::collections::HashMap;
use std::path::Path;
use std::sync::OnceLock;

use crate::board_nm::BoardNm;
use crate::drc_nm::ClearanceKind;
use crate::dsn::{extract_rules_clearances_from_str, DsnNetRules, DsnRulesClearances, DsnSummary};
use crate::dsn_to_nm::{dsn_coord_to_nm, summary_unit_scale_nm};
use crate::geom_nm::Nm;

#[derive(Debug, Clone)]
pub struct ClearanceResolverNm {
    default_clearance: Nm,
    net_id_to_clearance: Vec<Nm>,
    typed: HashMap<String, Nm>,
    matrix: HashMap<(String, String), Nm>,
    max_clearance: Nm,
}

fn typed_key(a: ClearanceKind, b: ClearanceKind) -> Option<&'static str> {
    use ClearanceKind::*;
    match (a, b) {
        (Wire, Via) | (Via, Wire) => Some("wire_via"),
        (Via, Via) => Some("via_via"),
        (Pin, Pin) => Some("pin_pin"),
        (Pin, Via) | (Via, Pin) => Some("pin_via"),
        (Smd, Smd) => Some("smd_smd"),
        (Smd, Pin) | (Pin, Smd) => Some("smd_pin"),
        (Smd, Via) | (Via, Smd) => Some("smd_via"),
        // Freerouting often expresses wire↔smd via `default_smd`.
        (Wire, Smd) | (Smd, Wire) => Some("default_smd"),
        (Wire, Area) | (Area, Wire) => Some("wire_area"),
        (Via, Area) | (Area, Via) => Some("via_area"),
        (Pin, Area) | (Area, Pin) => Some("pin_area"),
        (Smd, Area) | (Area, Smd) => Some("smd_area"),
        (Area, Area) => Some("area_area"),
        _ => None,
    }
}

fn normalize_pair(a: &str, b: &str) -> (String, String) {
    if a <= b {
        (a.to_string(), b.to_string())
    } else {
        (b.to_string(), a.to_string())
    }
}

impl ClearanceResolverNm {
    pub fn max_clearance(&self) -> Nm {
        self.max_clearance
    }

    /// Clearance from copper to the board boundary (if specified), e.g. `default_boundary`.
    ///
    /// Falls back to the DSN default clearance if no boundary-specific rule exists.
    pub fn boundary_clearance(&self) -> Nm {
        let typed = self.typed.get("default_boundary").copied().unwrap_or_else(Nm::zero);
        Nm(self.default_clearance.0.max(typed.0))
    }

    pub fn clearance_for(
        &self,
        kind_a: ClearanceKind,
        net_a: u32,
        class_a: u32,
        kind_b: ClearanceKind,
        net_b: u32,
        class_b: u32,
        board: &BoardNm,
    ) -> Nm {
        let base = {
            let a = self
                .net_id_to_clearance
                .get(net_a as usize)
                .copied()
                .unwrap_or(self.default_clearance);
            let b = self
                .net_id_to_clearance
                .get(net_b as usize)
                .copied()
                .unwrap_or(self.default_clearance);
            Nm(a.0.max(b.0))
        };

        let typed = typed_key(kind_a, kind_b)
            .and_then(|k| self.typed.get(k).copied())
            .unwrap_or_else(Nm::zero);

        let class_name = |id: u32| -> &str {
            board
                .clearance_class_id_to_name
                .get(id as usize)
                .map(|s| s.as_str())
                .unwrap_or("default")
        };
        let matrix = {
            let (a, b) = normalize_pair(class_name(class_a), class_name(class_b));
            self.matrix.get(&(a, b)).copied().unwrap_or_else(Nm::zero)
        };

        Nm(base.0.max(typed.0).max(matrix.0))
    }

    pub fn from_dsn_and_optional_rules(
        summary: &DsnSummary,
        board: &BoardNm,
        net_rules: &DsnNetRules,
        rules: Option<&DsnRulesClearances>,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let unit_scale_nm = summary_unit_scale_nm(summary).ok_or("missing DSN unit scale")?;

        let default_clear_nm = net_rules
            .default_rule
            .clearance
            .and_then(|c| dsn_coord_to_nm(c, unit_scale_nm).ok())
            .unwrap_or(0);
        let default_clearance = Nm(default_clear_nm);

        let max_net_id = board.net_name_to_id.values().copied().max().unwrap_or(0) as usize;
        let mut net_id_to_clearance: Vec<Nm> = vec![default_clearance; max_net_id + 1];
        for (name, id) in &board.net_name_to_id {
            let c = net_rules
                .clearance_for_net(name)
                .and_then(|c| dsn_coord_to_nm(c, unit_scale_nm).ok())
                .map(Nm)
                .unwrap_or(default_clearance);
            if (*id as usize) < net_id_to_clearance.len() {
                net_id_to_clearance[*id as usize] = c;
            }
        }

        let mut typed: HashMap<String, Nm> = HashMap::new();
        for (k, v) in &net_rules.typed_clearances {
            if let Ok(nm) = dsn_coord_to_nm(*v, unit_scale_nm) {
                typed.entry(k.clone())
                    .and_modify(|cur| cur.0 = cur.0.max(nm))
                    .or_insert(Nm(nm));
            }
        }
        if let Some(r) = rules {
            for (k, v) in &r.typed {
                if let Ok(nm) = dsn_coord_to_nm(*v, unit_scale_nm) {
                    typed.entry(k.clone())
                        .and_modify(|cur| cur.0 = cur.0.max(nm))
                        .or_insert(Nm(nm));
                }
            }
        }

        let mut matrix: HashMap<(String, String), Nm> = HashMap::new();
        if let Some(r) = rules {
            for ((a, b), v) in &r.matrix {
                if let Ok(nm) = dsn_coord_to_nm(*v, unit_scale_nm) {
                    let key = normalize_pair(a, b);
                    matrix
                        .entry(key)
                        .and_modify(|cur| cur.0 = cur.0.max(nm))
                        .or_insert(Nm(nm));
                }
            }
        }

        let mut max_clearance = default_clearance;
        for c in &net_id_to_clearance {
            max_clearance.0 = max_clearance.0.max(c.0);
        }
        for c in typed.values() {
            max_clearance.0 = max_clearance.0.max(c.0);
        }
        for c in matrix.values() {
            max_clearance.0 = max_clearance.0.max(c.0);
        }

        Ok(Self {
            default_clearance,
            net_id_to_clearance,
            typed,
            matrix,
            max_clearance,
        })
    }
}

pub fn read_rules_clearances_cached(path: &Path) -> Result<DsnRulesClearances, Box<dyn std::error::Error>> {
    static CACHE: OnceLock<std::sync::Mutex<HashMap<String, DsnRulesClearances>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| std::sync::Mutex::new(HashMap::new()));
    let key = path.to_string_lossy().to_string();
    if let Some(v) = cache.lock().unwrap().get(&key).cloned() {
        return Ok(v);
    }
    let txt = std::fs::read_to_string(path)?;
    let parsed = extract_rules_clearances_from_str(&txt)?;
    cache.lock().unwrap().insert(key, parsed.clone());
    Ok(parsed)
}
