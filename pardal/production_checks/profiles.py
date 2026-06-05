from __future__ import annotations

# Direct-file compatibility adapter only. Project-backed builds resolve these
# profiles from package YAML through ProjectContext; keep this map in parity
# with examples/packages/*/profiles until direct-file production checks are
# deleted.
PROFILE_CHECKS: dict[str, tuple[str, ...]] = {
    "jlcpcb_4_layer_smt": (
        "release.gerbers_missing",
        "release.drill_missing",
        "release.archive_not_uploadable",
        "layout.power_net_uses_finepitch_width",
        "layout.layer_roles_no_reference_plane",
        "layout.no_ground_plane",
        "dfm.absolute_min_trace_clearance_used_globally",
        "dfm.fabrication_tolerance_margin_missing",
        "jlcpcb.smt_required_artifacts",
    ),
    "jlcpcb_smt": (
        "assembly.manual_part_present",
        "assembly.manual_part_exported_to_jlc",
        "jlcpcb.smt_required_artifacts",
    ),
    "jlcpcb_full_pcba": (
        "assembly.manual_part_present",
        "assembly.manual_part_exported_to_jlc",
        "jlcpcb.smt_required_artifacts",
    ),
    "require_or_exception": (
        "bom.lcsc_missing",
        "lcsc.parts_require_mapping_or_exception",
    ),
    "gd32f310_adc_12v": (
        "gd32.12v_input",
        "gd32.adc_frontend",
        "analog.rc_filter_contract_complete",
        "analog.rc_filter_values_resolve",
        "analog.rc_filter_cutoff_within_limit",
        "power.rail_budget_missing",
        "power.linear_regulator_drop_too_high",
    ),
    "gd32_12v_input": (
        "gd32.12v_input",
        "power.rail_budget_missing",
        "power.linear_regulator_drop_too_high",
    ),
    "gd32_adc_frontend": (
        "gd32.adc_frontend",
        "analog.rc_filter_contract_complete",
        "analog.rc_filter_values_resolve",
        "analog.rc_filter_cutoff_within_limit",
    ),
}


def checks_for_profiles(profiles: list[str]) -> set[str]:
    enabled: set[str] = set()
    for profile in profiles:
        enabled.update(PROFILE_CHECKS.get(profile, ()))
    return enabled
