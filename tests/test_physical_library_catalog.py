import json

import pytest

from pardal.physical_libraries import (
    CatalogValidationError,
    expand_catalog_entry,
    get_catalog_entry,
    load_catalog,
    validate_catalog,
)


def test_loads_jlc_two_layer_low_cost_profile():
    catalog = load_catalog()

    entry = get_catalog_entry("jlc_2layer_low_cost", catalog)

    assert entry["kind"] == "dfm_profile"
    assert entry["manufacturer"] == "JLCPCB"
    assert entry["service"] == "2layer_low_cost"
    assert entry["limits"]["max_width_mm"] == 100.0
    assert entry["limits"]["max_height_mm"] == 100.0
    assert entry["limits"]["min_via_diameter_mm"] > entry["limits"]["min_via_drill_mm"]


def test_placeholder_entries_are_non_executing_route_group_targets():
    catalog = load_catalog()
    placeholders = [
        entry
        for entry in catalog["entries"].values()
        if entry["kind"] == "pattern_placeholder"
    ]

    assert {entry["pattern_family"] for entry in placeholders} == {
        "qfp_escape",
        "icsp_corridor",
        "gpio_bank_lane_ordering",
        "passive_cluster",
    }
    for entry in placeholders:
        assert entry["target_expansion_kind"] == "route_group"
        assert entry["execution"]["enabled"] is False
        assert entry["required_parameters"]


def test_rejects_malformed_jlc_profile():
    catalog = load_catalog()
    malformed = json.loads(json.dumps(catalog))
    malformed["entries"]["jlc_2layer_low_cost"]["limits"]["min_via_diameter_mm"] = 0.1

    with pytest.raises(CatalogValidationError, match="min_via_diameter_mm"):
        validate_catalog(malformed)


def test_rejects_executable_placeholder():
    catalog = load_catalog()
    malformed = json.loads(json.dumps(catalog))
    malformed["entries"]["qfp_escape_placeholder"]["execution"]["enabled"] = True

    with pytest.raises(CatalogValidationError, match="execution.enabled"):
        validate_catalog(malformed)


def test_rejects_placeholder_without_route_group_target():
    catalog = load_catalog()
    malformed = json.loads(json.dumps(catalog))
    malformed["entries"]["icsp_corridor_placeholder"][
        "target_expansion_kind"
    ] = "custom_router"

    with pytest.raises(CatalogValidationError, match="target_expansion_kind"):
        validate_catalog(malformed)


def test_expands_icsp_placeholder_into_pure_route_group():
    catalog = load_catalog()
    parameters = {
        "pgc_net": "PGC1_RB4",
        "pgd_net": "PGD1_RB5",
        "connector_ref": "J2",
        "corridor_side": "left",
    }
    route_details = {
        "name": "icsp_corridor_j2_left",
        "description": "ICSP corridor for J2 on the left side",
        "group": ["icsp", "source_native"],
        "templates": [
            {
                "name": "pgc_lane",
                "net": "PGC1_RB4",
                "start_layer": "F.Cu",
                "points": ["U1.12", ["x:lane_x", "25.0mm"], "J2.1"],
            },
            {
                "name": "pgd_lane",
                "net": "PGD1_RB5",
                "start_layer": "F.Cu",
                "points": ["U1.13", ["x:lane_x", "26.0mm"], "J2.2"],
            },
        ],
        "replace_existing": {
            "nets": ["PGC1_RB4", "PGD1_RB5"],
            "include_fanout": True,
            "require_all_nets": True,
            "max_removed_segments": 64,
            "max_removed_vias": 16,
            "allow_power_nets": False,
        },
    }
    original_details = json.loads(json.dumps(route_details))

    expanded = expand_catalog_entry(
        "icsp_corridor_placeholder",
        parameters,
        route_details=route_details,
        catalog=catalog,
    )

    assert expanded["kind"] == "route_group"
    assert expanded["name"] == "icsp_corridor_j2_left"
    assert expanded["schema_version"] == 1
    assert expanded["description"] == "ICSP corridor for J2 on the left side"
    assert expanded["library"] == {
        "entry_id": "icsp_corridor_placeholder",
        "pattern_family": "icsp_corridor",
        "parameters": parameters,
        "expanded_by": "physical_libraries.catalog",
        "catalog_schema_version": 1,
    }
    assert expanded["templates"] == original_details["templates"]
    assert expanded["replace_existing"] == original_details["replace_existing"]
    assert route_details == original_details
    assert expanded is not route_details
    assert expanded["library"]["parameters"] is not parameters


def test_rejects_missing_or_unknown_catalog_entry_for_expansion():
    catalog = load_catalog()

    with pytest.raises(CatalogValidationError, match="missing catalog entry"):
        expand_catalog_entry(
            "missing_placeholder",
            {
                "pgc_net": "PGC1_RB4",
                "pgd_net": "PGD1_RB5",
                "connector_ref": "J2",
                "corridor_side": "left",
            },
            route_details={
                "name": "missing",
                "templates": [{"name": "a"}, {"name": "b"}],
            },
            catalog=catalog,
        )

    with pytest.raises(CatalogValidationError, match="only pattern placeholders"):
        expand_catalog_entry(
            "jlc_2layer_low_cost",
            {
                "pgc_net": "PGC1_RB4",
                "pgd_net": "PGD1_RB5",
                "connector_ref": "J2",
                "corridor_side": "left",
            },
            route_details={
                "name": "not_allowed",
                "templates": [{"name": "a"}, {"name": "b"}],
            },
            catalog=catalog,
        )


def test_rejects_malformed_parameters_for_expansion():
    catalog = load_catalog()

    with pytest.raises(CatalogValidationError, match="missing required parameters"):
        expand_catalog_entry(
            "icsp_corridor_placeholder",
            {"pgc_net": "PGC1_RB4"},
            route_details={
                "name": "icsp_corridor_j2_left",
                "templates": [{"name": "a"}, {"name": "b"}],
            },
            catalog=catalog,
        )

    with pytest.raises(CatalogValidationError, match="parameter connector_ref"):
        expand_catalog_entry(
            "icsp_corridor_placeholder",
            {
                "pgc_net": "PGC1_RB4",
                "pgd_net": "PGD1_RB5",
                "connector_ref": "",
                "corridor_side": "left",
            },
            route_details={
                "name": "icsp_corridor_j2_left",
                "templates": [{"name": "a"}, {"name": "b"}],
            },
            catalog=catalog,
        )


def test_preserves_placeholder_non_executing_validation():
    catalog = load_catalog()
    original = json.loads(json.dumps(catalog))

    validate_catalog(catalog)

    assert catalog == original
    assert catalog["entries"]["icsp_corridor_placeholder"]["execution"]["enabled"] is False
