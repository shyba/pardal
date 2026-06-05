from pathlib import Path
from types import SimpleNamespace
import zipfile

from pardal.production_checks import CheckContext, load_source_contract, run_production_checks


class _Spec:
    path = Path("board.pdl.yaml")
    dfm = None
    layer_roles = {"F.Cu": "signal", "B.Cu": "signal"}
    planes = []
    routes = []
    validation_tests = []
    parts = {}
    netclass_assignments = {}

    class _Rules:
        default_clearance = 0.10
        netclasses = {}

    rules = _Rules()


class _Comp:
    footprint = "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS"
    value = "12V_IN"


class _Board:
    components = {"J12V": _Comp()}


def test_source_contract_rejects_unsupported_schema(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
schema: pardal.source_contract/v2
profiles:
  design: gd32f310_adc_12v
""",
        encoding="utf-8",
    )

    try:
        load_source_contract(contract_path)
    except ValueError as exc:
        assert "schema must be pardal.source_contract/v1" in str(exc)
    else:  # pragma: no cover - explicit assertion message is clearer
        raise AssertionError("expected unsupported source contract schema to fail")


def test_source_contract_enables_gd32_and_power_checks(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
profiles:
  design: gd32f310_adc_12v
enable_checks:
  - power.rail_budget_missing
rails:
  3V3:
    source_ref: U2
inputs:
  12V_IN:
    required_protection: [reverse_polarity]
adc_filters:
  ADC0:
    input_net: ADC0_IN
""",
        encoding="utf-8",
    )

    contract = load_source_contract(contract_path)
    findings = run_production_checks(CheckContext(spec=_Spec(), source_contract=contract))
    codes = {finding.code for finding in findings}

    assert "gd32.adc_frontend" in codes
    assert "analog.rc_filter_contract_complete" in codes
    assert "analog.rc_filter_values_resolve" in codes
    assert "power.rail_budget_missing" in codes


def test_manual_part_waiver_is_narrow_warning(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
profiles:
  assembly: jlcpcb_smt
disable_checks:
  - jlcpcb.smt_required_artifacts
waive_checks:
  assembly.manual_part_present:
    refs: [J12V]
    reason: expected manual terminal
""",
        encoding="utf-8",
    )

    contract = load_source_contract(contract_path)
    findings = run_production_checks(
        CheckContext(spec=_Spec(), board=_Board(), source_contract=contract)
    )

    assert [(finding.severity, finding.code) for finding in findings] == [
        ("warning", "assembly.manual_part_present.waived")
    ]


def test_waiver_without_match_does_not_apply_by_default(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
profiles:
  assembly: jlcpcb_smt
disable_checks:
  - jlcpcb.smt_required_artifacts
waive_checks:
  assembly.manual_part_present:
    reason: broad waiver is not allowed
""",
        encoding="utf-8",
    )

    contract = load_source_contract(contract_path)
    findings = run_production_checks(
        CheckContext(spec=_Spec(), board=_Board(), source_contract=contract)
    )

    assert ("warning", "assembly.manual_part_present") in [
        (finding.severity, finding.code) for finding in findings
    ]
    assert ("warning", "waiver.unused") in [
        (finding.severity, finding.code) for finding in findings
    ]


def test_waiver_requires_reason(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
waive_checks:
  assembly.manual_part_present:
    refs: [J12V]
""",
        encoding="utf-8",
    )

    try:
        load_source_contract(contract_path)
    except ValueError as exc:
        assert "reason must be non-empty" in str(exc)
    else:  # pragma: no cover - explicit assertion message is clearer
        raise AssertionError("expected missing waiver reason to fail")


def test_design_style_waiver_requires_stage(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
waivers:
  - id: assembly.manual_part_present
    match:
      ref: J12V
    reason: connector is intentionally hand-soldered
""",
        encoding="utf-8",
    )

    try:
        load_source_contract(contract_path)
    except ValueError as exc:
        assert "waivers[0].stage must be non-empty" in str(exc)
    else:  # pragma: no cover - explicit assertion message is clearer
        raise AssertionError("expected missing waiver stage to fail")


def test_waiver_match_must_be_mapping(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
waivers:
  - id: assembly.manual_part_present
    stage: assembly
    match: [J12V]
    reason: connector is intentionally hand-soldered
""",
        encoding="utf-8",
    )

    try:
        load_source_contract(contract_path)
    except ValueError as exc:
        assert "waive_checks.assembly.manual_part_present.match must be a mapping" in str(exc)
    else:  # pragma: no cover - explicit assertion message is clearer
        raise AssertionError("expected malformed waiver match to fail")


def test_waiver_refs_must_be_list_of_strings(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
waive_checks:
  assembly.manual_part_present:
    refs: J12V
    reason: connector is intentionally hand-soldered
""",
        encoding="utf-8",
    )

    try:
        load_source_contract(contract_path)
    except ValueError as exc:
        assert "waive_checks.assembly.manual_part_present.refs must be a list" in str(exc)
    else:  # pragma: no cover - explicit assertion message is clearer
        raise AssertionError("expected malformed waiver refs to fail")


def test_enable_checks_require_non_empty_strings(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
enable_checks:
  - 123
""",
        encoding="utf-8",
    )

    try:
        load_source_contract(contract_path)
    except ValueError as exc:
        assert "enable_checks[0] must be a non-empty string" in str(exc)
    else:  # pragma: no cover - explicit assertion message is clearer
        raise AssertionError("expected malformed enable_checks to fail")


def test_disable_checks_require_non_empty_strings(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
disable_checks:
  - ""
""",
        encoding="utf-8",
    )

    try:
        load_source_contract(contract_path)
    except ValueError as exc:
        assert "disable_checks[0] must be a non-empty string" in str(exc)
    else:  # pragma: no cover - explicit assertion message is clearer
        raise AssertionError("expected malformed disable_checks to fail")


def test_expired_waiver_does_not_hide_finding(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
profiles:
  assembly: jlcpcb_smt
disable_checks:
  - jlcpcb.smt_required_artifacts
waive_checks:
  assembly.manual_part_present:
    refs: [J12V]
    reason: old exception
    expires: 2000-01-01
""",
        encoding="utf-8",
    )

    findings = run_production_checks(
        CheckContext(
            spec=_Spec(),
            board=_Board(),
            source_contract=load_source_contract(contract_path),
        )
    )

    assert ("warning", "assembly.manual_part_present") in [
        (finding.severity, finding.code) for finding in findings
    ]
    assert ("error", "waiver.expired") in [
        (finding.severity, finding.code) for finding in findings
    ]


def test_unused_waiver_emits_warning(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
disable_checks:
  - jlcpcb.smt_required_artifacts
waive_checks:
  assembly.manual_part_present:
    refs: [J99]
    reason: wrong connector
""",
        encoding="utf-8",
    )

    findings = run_production_checks(
        CheckContext(
            spec=_Spec(),
            board=_Board(),
            source_contract=load_source_contract(contract_path),
        ),
        enable_checks=["assembly.manual_part_present"],
    )

    assert ("warning", "assembly.manual_part_present") in [
        (finding.severity, finding.code) for finding in findings
    ]
    assert ("warning", "waiver.unused") in [
        (finding.severity, finding.code) for finding in findings
    ]


def test_archive_check_requires_gerber_and_drill_files(tmp_path):
    archive = tmp_path / "mfg.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("gerbers/top.gbr", "G04 test*")

    findings = run_production_checks(
        CheckContext(
            spec=_Spec(),
            manufacturing_archive=archive,
            source_contract=load_source_contract(None),
        ),
        enable_checks=["release.archive_not_uploadable"],
    )

    assert [(finding.severity, finding.code) for finding in findings] == [
        ("error", "release.archive_not_uploadable")
    ]


def test_full_pcba_profile_escalates_manual_parts_to_error(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
profiles:
  assembly: jlcpcb_full_pcba
disable_checks:
  - jlcpcb.smt_required_artifacts
""",
        encoding="utf-8",
    )

    findings = run_production_checks(
        CheckContext(
            spec=_Spec(),
            board=_Board(),
            source_contract=load_source_contract(contract_path),
        )
    )

    assert [(finding.severity, finding.code) for finding in findings] == [
        ("error", "assembly.manual_part_present")
    ]


def test_gd32_profile_aliases_import_specific_checks(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
profiles:
  design: gd32_12v_input
""",
        encoding="utf-8",
    )

    findings = run_production_checks(
        CheckContext(spec=_Spec(), source_contract=load_source_contract(contract_path))
    )

    codes = {finding.code for finding in findings}
    assert "gd32.12v_input" in codes
    assert "power.rail_budget_missing" not in codes


def test_source_contract_path_can_come_from_spec_yaml(tmp_path):
    from pardal.physical.compiler import _source_contract_path_from_spec

    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """
source_contract:
  path: source_contract.yaml
""",
        encoding="utf-8",
    )

    assert _source_contract_path_from_spec(spec_path) == Path("source_contract.yaml")


def test_diagnostics_dashboard_includes_production_checks():
    from pardal.physical.diagnostics import build_diagnostics_dashboard

    dashboard = build_diagnostics_dashboard(
        build_summary={
            "production_checks": {"enabled": True, "error_count": 0},
            "dfm_report": {"error_count": 0, "warning_count": 1},
        }
    )

    assert dashboard["production_checks"] == {"enabled": True, "error_count": 0}
    assert dashboard["dfm_report"] == {"error_count": 0, "warning_count": 1}


def test_diagnostics_dashboard_loads_strict_summary_from_route_file_sibling(tmp_path):
    import json

    from pardal.physical.diagnostics import load_route_diagnostics_dashboard

    route_path = tmp_path / "route-diagnostics.json"
    route_path.write_text("{}", encoding="utf-8")
    (tmp_path / "build-summary-strict.json").write_text(
        json.dumps(
            {
                "production_checks": {"enabled": True, "error_count": 0},
                "dfm_report": {"error_count": 0},
            }
        ),
        encoding="utf-8",
    )

    dashboard = load_route_diagnostics_dashboard(route_path)

    assert dashboard["production_checks"]["error_count"] == 0
    assert dashboard["dfm_report"]["error_count"] == 0


def test_validation_claims_must_match_non_visual_spec_tests(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
enable_checks:
  - validation.only_visual_inspection
validation:
  erc_like_policy: true
  measured_tests: true
""",
        encoding="utf-8",
    )

    spec = SimpleNamespace(
        path=Path("board.pdl.yaml"),
        validation_tests=[SimpleNamespace(kind="visual_inspection")],
    )
    findings = run_production_checks(
        CheckContext(spec=spec, source_contract=load_source_contract(contract_path))
    )

    assert [(finding.severity, finding.code) for finding in findings] == [
        ("error", "validation.only_visual_inspection")
    ]


def test_power_width_uses_implicit_netclass_assignment(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
enable_checks:
  - layout.power_net_uses_finepitch_width
rails:
  3V3:
    output_net: 3V3
    min_trace_width_mm: 0.25
""",
        encoding="utf-8",
    )
    spec = SimpleNamespace(
        path=Path("board.pdl.yaml"),
        routes=[SimpleNamespace(raw={"name": "r3v3", "net": "3V3"})],
        netclass_assignments={"FinePitch": ["*"]},
        rules=SimpleNamespace(
            default_clearance=0.10,
            netclasses={"FinePitch": SimpleNamespace(width=0.10)},
        ),
    )

    findings = run_production_checks(
        CheckContext(spec=spec, source_contract=load_source_contract(contract_path))
    )

    assert [(finding.severity, finding.code) for finding in findings] == [
        ("error", "layout.power_net_uses_finepitch_width")
    ]


def test_absolute_minimum_dfm_warning_ignores_scoped_finepitch_netclass(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
enable_checks:
  - dfm.absolute_min_trace_clearance_used_globally
""",
        encoding="utf-8",
    )
    spec = SimpleNamespace(
        path=Path("board.pdl.yaml"),
        netclass_assignments={"FinePitch": ["ADC0_FILT"]},
        rules=SimpleNamespace(
            default_clearance=0.15,
            default_width=0.15,
            netclasses={"FinePitch": SimpleNamespace(width=0.10, clearance=0.10)},
        ),
    )

    findings = run_production_checks(
        CheckContext(spec=spec, source_contract=load_source_contract(contract_path))
    )

    assert [finding.code for finding in findings] == []


def test_absolute_minimum_dfm_warning_flags_wildcard_finepitch_netclass(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
enable_checks:
  - dfm.absolute_min_trace_clearance_used_globally
""",
        encoding="utf-8",
    )
    spec = SimpleNamespace(
        path=Path("board.pdl.yaml"),
        netclass_assignments={"FinePitch": ["*"]},
        rules=SimpleNamespace(
            default_clearance=0.15,
            default_width=0.15,
            netclasses={"FinePitch": SimpleNamespace(width=0.10, clearance=0.10)},
        ),
    )

    findings = run_production_checks(
        CheckContext(spec=spec, source_contract=load_source_contract(contract_path))
    )

    assert [(finding.severity, finding.code) for finding in findings] == [
        ("warning", "dfm.absolute_min_trace_clearance_used_globally")
    ]


def test_manual_parts_must_not_be_exported_to_jlc(tmp_path):
    bom = tmp_path / "bom.csv"
    bom.write_text("Designator,Comment,Footprint,LCSC Part #\nJ12V,12V_IN,THT,C8465\n", encoding="utf-8")
    pnp = tmp_path / "pnp.csv"
    pnp.write_text("Designator,Mid X,Mid Y,Layer,Rotation\nJ12V,1mm,1mm,Top,0\n", encoding="utf-8")
    spec = SimpleNamespace(
        path=Path("board.pdl.yaml"),
        dfm=SimpleNamespace(assembly_methods={"J12V": "manual_tht"}),
    )

    findings = run_production_checks(
        CheckContext(
            spec=spec,
            board=_Board(),
            source_contract=load_source_contract(None),
            artifact_paths={"jlc_bom": bom, "jlc_pnp": pnp},
        ),
        enable_checks=["assembly.manual_part_exported_to_jlc"],
    )

    assert [(finding.severity, finding.code) for finding in findings] == [
        ("error", "assembly.manual_part_exported_to_jlc"),
        ("error", "assembly.manual_part_exported_to_jlc"),
    ]


def test_gd32_12v_contract_requires_hardware_protection(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
profiles:
  design: gd32_12v_input
inputs:
  12V_IN:
    required_protection: [reverse_polarity, current_limit, transient]
""",
        encoding="utf-8",
    )
    spec = SimpleNamespace(
        path=Path("board.pdl.yaml"),
        parts={
            "D1": SimpleNamespace(footprint="Diode_SMD:D_SMA"),
            "U2": SimpleNamespace(footprint="Package_TO_SOT_SMD:SOT-89-3"),
        },
    )

    findings = run_production_checks(
        CheckContext(spec=spec, source_contract=load_source_contract(contract_path))
    )

    messages = "\n".join(finding.message for finding in findings)
    assert "current_limit" in messages
    assert "transient protection" in messages


def test_analog_adc_cutoff_must_satisfy_contract(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
enable_checks:
  - analog.rc_filter_cutoff_within_limit
adc_filters:
  ADC0:
    input_net: ADC0_IN
    filtered_net: ADC0_FILT
    resistor_ref: RAD0
    capacitor_ref: CAD0
    max_bandwidth_hz: 500
""",
        encoding="utf-8",
    )
    board = SimpleNamespace(
        components={
            "RAD0": SimpleNamespace(value="1k"),
            "CAD0": SimpleNamespace(value="100nF"),
        }
    )

    findings = run_production_checks(
        CheckContext(spec=_Spec(), board=board, source_contract=load_source_contract(contract_path))
    )

    assert any(
        finding.code == "analog.rc_filter_cutoff_within_limit" and "exceeds contract" in finding.message
        for finding in findings
    )


def test_analog_adc_values_must_resolve(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
enable_checks:
  - analog.rc_filter_values_resolve
adc_filters:
  ADC0:
    input_net: ADC0_IN
    filtered_net: ADC0_FILT
    resistor_ref: RAD0
    capacitor_ref: CAD0
    max_bandwidth_hz: 500
""",
        encoding="utf-8",
    )

    findings = run_production_checks(
        CheckContext(spec=_Spec(), board=SimpleNamespace(components={}), source_contract=load_source_contract(contract_path))
    )

    messages = "\n".join(finding.message for finding in findings)
    assert [(finding.severity, finding.code) for finding in findings] == [
        ("error", "analog.rc_filter_values_resolve"),
        ("error", "analog.rc_filter_values_resolve"),
    ]
    assert "RAD0" in messages
    assert "CAD0" in messages


def test_gd32_adc_frontend_requires_ten_device_channels(tmp_path):
    contract_path = tmp_path / "source_contract.yaml"
    contract_path.write_text(
        """
enable_checks:
  - gd32.adc_frontend
adc_filters:
  ADC0:
    input_net: ADC0_IN
    filtered_net: ADC0_FILT
    resistor_ref: RAD0
    capacitor_ref: CAD0
    max_bandwidth_hz: 500
""",
        encoding="utf-8",
    )

    findings = run_production_checks(
        CheckContext(spec=_Spec(), source_contract=load_source_contract(contract_path))
    )

    assert any(
        finding.code == "gd32.adc_frontend" and "ADC9 filter contract is missing" in finding.message
        for finding in findings
    )
