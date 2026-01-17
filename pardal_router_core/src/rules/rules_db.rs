use std::collections::HashMap;

use crate::dsn::{DsnNetRules, DsnRulesClearances};

#[derive(Debug, Clone, Default)]
pub struct RulesDb {
    net_rules: Option<DsnNetRules>,
    rules_clearances: Option<DsnRulesClearances>,
}

impl RulesDb {
    pub fn from_dsn_net_rules(net_rules: DsnNetRules) -> Self {
        Self {
            net_rules: Some(net_rules),
            rules_clearances: None,
        }
    }

    pub fn from_dsn_net_rules_and_rules_clearances(
        net_rules: DsnNetRules,
        rules_clearances: DsnRulesClearances,
    ) -> Self {
        Self {
            net_rules: Some(net_rules),
            rules_clearances: Some(rules_clearances),
        }
    }

    pub fn default_width_world(&self) -> Option<f64> {
        self.net_rules.as_ref().and_then(|r| r.default_rule.width)
    }

    pub fn default_clearance_world(&self) -> Option<f64> {
        let from_net = self.net_rules.as_ref().and_then(|r| r.default_rule.clearance);
        let from_rules = self.rules_clearances.as_ref().and_then(|r| r.default_clearance);
        match (from_net, from_rules) {
            (None, None) => None,
            (Some(a), None) => Some(a),
            (None, Some(b)) => Some(b),
            (Some(a), Some(b)) => Some(a.max(b)),
        }
    }

    pub fn width_world_for_net(&self, net_name: &str) -> Option<f64> {
        self.net_rules.as_ref().and_then(|r| r.width_for_net(net_name))
    }

    pub fn clearance_world_for_net(&self, net_name: &str) -> Option<f64> {
        self.net_rules
            .as_ref()
            .and_then(|r| r.clearance_for_net(net_name))
    }

    pub fn typed_clearances_world(&self) -> HashMap<String, f64> {
        let mut out: HashMap<String, f64> = HashMap::new();
        if let Some(r) = self.net_rules.as_ref() {
            for (k, v) in &r.typed_clearances {
                out.entry(k.clone())
                    .and_modify(|cur| *cur = cur.max(*v))
                    .or_insert(*v);
            }
        }
        if let Some(r) = self.rules_clearances.as_ref() {
            for (k, v) in &r.typed {
                out.entry(k.clone())
                    .and_modify(|cur| *cur = cur.max(*v))
                    .or_insert(*v);
            }
        }
        out
    }

    pub fn clearance_matrix_world_for_classes(&self, a: &str, b: &str) -> Option<f64> {
        let r = self.rules_clearances.as_ref()?;
        let (a, b) = if a <= b {
            (a.to_string(), b.to_string())
        } else {
            (b.to_string(), a.to_string())
        };
        r.matrix.get(&(a, b)).copied()
    }

    pub fn via_rules(&self) -> HashMap<String, String> {
        self.net_rules
            .as_ref()
            .map(|r| r.via_rules.clone())
            .unwrap_or_default()
    }

    pub fn via_padstack_for_net(&self, net_name: &str) -> Option<String> {
        let r = self.net_rules.as_ref()?;
        let class_name = r.net_to_class.get(net_name)?;
        let class = r.classes.get(class_name)?;

        if let Some(via_rule_name) = class.via_rule.as_ref() {
            if let Some(padstack) = r.via_rules.get(via_rule_name) {
                return Some(padstack.clone());
            }
        }
        if let Some(use_via) = class.use_via.as_ref() {
            return Some(use_via.clone());
        }
        r.via_rules.get("default").cloned()
    }

    /// Conservative IR inflation radius for a routed track, in grid cells.
    ///
    /// This is intended for the current grid router only (occupancy + brush model).
    /// It approximates:
    /// - track half-width
    /// - plus clearance (default rule today)
    pub fn brush_radius_cells_for_net(&self, net_name: &str, pitch: f64) -> u8 {
        if pitch <= 0.0 {
            return 0;
        }
        let Some(net_rules) = self.net_rules.as_ref() else {
            return 0;
        };

        let width = net_rules.width_for_net(net_name).or(net_rules.default_rule.width);
        let clearance = net_rules
            .clearance_for_net(net_name)
            .or(self.default_clearance_world())
            .unwrap_or(0.0);

        let Some(width) = width else {
            return 0;
        };
        if !width.is_finite() || width <= 0.0 {
            return 0;
        }

        let ratio = ((width * 0.5) + clearance.max(0.0)) / pitch;
        if !ratio.is_finite() || ratio < 0.5 {
            return 0;
        }
        (ratio.ceil() as u64).min(255) as u8
    }

    pub fn brush_radius_cells_default(&self, pitch: f64) -> u8 {
        if pitch <= 0.0 {
            return 0;
        }
        let width = self.default_width_world();
        let clearance = self.default_clearance_world().unwrap_or(0.0).max(0.0);
        let Some(width) = width else {
            return 0;
        };
        if !width.is_finite() || width <= 0.0 {
            return 0;
        }
        let ratio = ((width * 0.5) + clearance) / pitch;
        if !ratio.is_finite() || ratio < 0.5 {
            return 0;
        }
        (ratio.ceil() as u64).min(255) as u8
    }
}
