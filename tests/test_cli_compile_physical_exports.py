import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pardal.physical as physical
import pardal.physical.spec as physical_spec_module
import pardal.project.context as project_context_module
import pardal.project.provenance as project_provenance_module
import pardal.production_checks as production_checks_module
import yaml
import pardal.cli as cli_module
from pardal.cli import (
    cmd_compile_physical,
    cmd_create_board,
    cmd_create_package,
    cmd_package_build,
    cmd_package_check,
    cmd_package_publish,
    cmd_project_add,
    cmd_project_list,
    cmd_project_remove,
    cmd_production_check,
    cmd_project_sync,
)
from pardal.checks.api import Severity, Stage, check, registered_checks
from pardal.physical.compiler import CompilePhysicalResult
from pardal.project.diagnostics import ProjectConfigError


def test_cmd_compile_physical_passes_manufacturing_export_paths(monkeypatch, tmp_path, capsys):
    output = tmp_path / "board.kicad_pcb"
    gerbers = tmp_path / "gerbers"
    drill = tmp_path / "drill"
    build_summary = tmp_path / "build-summary.json"
    captured: dict[str, object] = {}

    def fake_compile_physical(spec, **kwargs):
        captured["spec"] = spec
        captured.update(kwargs)
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=False,
            production_report=None,
            production_report_format="text",
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            route_diagnostics_report=None,
            build_summary_output=build_summary,
            manufacturing_archive_output=tmp_path / "manufacturing-package.zip",
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=gerbers,
            drill_output_dir=drill,
        )
    )

    stdout = capsys.readouterr().out
    assert result == 0
    assert captured["gerber_output_dir"] == gerbers
    assert captured["drill_output_dir"] == drill
    assert captured["build_summary_output"] == build_summary
    assert captured["manufacturing_archive_output"] == tmp_path / "manufacturing-package.zip"
    assert f"Saved Gerber files to {gerbers}" in stdout
    assert f"Saved drill files to {drill}" in stdout
    assert f"Saved build summary to {build_summary}" in stdout
    assert f"Saved manufacturing archive to {tmp_path / 'manufacturing-package.zip'}" in stdout


def test_refresh_archive_build_summary_replaces_embedded_payload(tmp_path):
    summary = tmp_path / "build-summary.json"
    archive = tmp_path / "manufacturing-package.zip"
    summary.write_text('{"pass": true, "project_provenance": {"present": true}}\n', encoding="utf-8")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("build-summary.json", '{"pass": true}\n')
        zf.writestr("jlc_bom.csv", "Comment,Designator,Footprint,LCSC Part #\n")

    cli_module._refresh_archive_build_summary(archive, summary)

    with zipfile.ZipFile(archive) as zf:
        assert zf.read("build-summary.json").decode("utf-8") == summary.read_text(
            encoding="utf-8"
        )
        assert zf.read("jlc_bom.csv").decode("utf-8").startswith("Comment,")


def test_compile_physical_accepts_documented_profile_alias(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_cmd_compile_physical(args):
        captured["profiles"] = args.production_profile
        return 0

    monkeypatch.setattr(cli_module, "cmd_compile_physical", fake_cmd_compile_physical)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pardal",
            "compile-physical",
            str(tmp_path / "board.pdl.yaml"),
            "-o",
            str(tmp_path / "board.kicad_pcb"),
            "--profile",
            "jlcpcb/lcsc:jlcpcb_smt",
        ],
    )

    assert cli_module.main() == 0
    assert captured["profiles"] == ["jlcpcb/lcsc:jlcpcb_smt"]


def test_compile_physical_accepts_documented_allow_unlocked_flag(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_cmd_compile_physical(args):
        captured["allow_unlocked"] = args.allow_unlocked
        return 0

    monkeypatch.setattr(cli_module, "cmd_compile_physical", fake_cmd_compile_physical)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pardal",
            "compile-physical",
            str(tmp_path / "board.pdl.yaml"),
            "-o",
            str(tmp_path / "board.kicad_pcb"),
            "--allow-unlocked",
        ],
    )

    assert cli_module.main() == 0
    assert captured["allow_unlocked"] is True


def test_compile_physical_accepts_documented_allow_absolute_paths_flag(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_cmd_compile_physical(args):
        captured["allow_absolute_paths"] = args.allow_absolute_paths
        return 0

    monkeypatch.setattr(cli_module, "cmd_compile_physical", fake_cmd_compile_physical)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pardal",
            "compile-physical",
            str(tmp_path / "board.pdl.yaml"),
            "-o",
            str(tmp_path / "board.kicad_pcb"),
            "--allow-absolute-paths",
        ],
    )

    assert cli_module.main() == 0
    assert captured["allow_absolute_paths"] is True


def test_cmd_compile_physical_only_reports_drc_diagnostics_when_drc_can_run(monkeypatch, tmp_path, capsys):
    output = tmp_path / "board.kicad_pcb"
    diagnostics = tmp_path / "drc-diagnostics.json"
    drc_report = tmp_path / "routed-physical-drc.rpt"

    def fake_compile_physical(spec, **kwargs):
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=drc_report,
            no_drc=True,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=False,
            production_report=None,
            production_report_format="text",
            drc_diagnostics_report=diagnostics,
            drc_diagnostics_format="json",
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
        )
    )

    stdout = capsys.readouterr().out
    assert result == 0
    assert f"Saved DRC diagnostics report to {diagnostics}" not in stdout


def test_cmd_compile_physical_reports_drc_diagnostics_when_drc_can_run(monkeypatch, tmp_path, capsys):
    output = tmp_path / "board.kicad_pcb"
    diagnostics = tmp_path / "drc-diagnostics.json"
    drc_report = tmp_path / "routed-physical-drc.rpt"

    def fake_compile_physical(spec, **kwargs):
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=drc_report,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=False,
            production_report=None,
            production_report_format="text",
            drc_diagnostics_report=diagnostics,
            drc_diagnostics_format="json",
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
        )
    )

    stdout = capsys.readouterr().out
    assert result == 0
    assert f"Saved DRC diagnostics report to {diagnostics}" in stdout


def test_cmd_compile_physical_applies_production_output_dir_preset(monkeypatch, tmp_path):
    output = tmp_path / "dspic33ak_devboard.routed_physical.kicad_pcb"
    captured: dict[str, object] = {}

    def fake_compile_physical(spec, **kwargs):
        captured["spec"] = spec
        captured.update(kwargs)
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=False,
            production_output_dir=tmp_path,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
        )
    )

    assert result == 0
    assert captured["drc_report"] == tmp_path / "routed-physical-drc.rpt"
    assert captured["bom_output"] == tmp_path / "dspic33ak_devboard.bom.csv"
    assert captured["pnp_output"] == tmp_path / "dspic33ak_devboard.pnp.csv"
    assert captured["jlc_bom_output"] == tmp_path / "dspic33ak_devboard.jlc.bom.csv"
    assert captured["jlc_pnp_output"] == tmp_path / "dspic33ak_devboard.jlc.pnp.csv"
    assert captured["production_report"] == tmp_path / "production-checks.json"
    assert captured["production_report_format"] == "json"
    assert captured["drc_diagnostics_report"] == tmp_path / "drc-diagnostics.json"
    assert captured["route_diagnostics_report"] == tmp_path / "route-diagnostics.json"
    assert captured["drc_diagnostics_format"] == "json"
    assert captured["gerber_output_dir"] == tmp_path / "gerbers"
    assert captured["drill_output_dir"] == tmp_path / "drill"
    assert captured["build_summary_output"] == tmp_path / "build-summary.json"
    assert captured["manufacturing_archive_output"] == tmp_path / "manufacturing-package.zip"


def test_cmd_compile_physical_rejects_direct_file_production_check(monkeypatch, tmp_path, capsys):
    calls: dict[str, bool] = {}

    def fake_compile_physical(spec, **kwargs):
        calls["compiled"] = True
        return CompilePhysicalResult(output=tmp_path / "board.kicad_pcb")

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=None,
            target="default",
            netlist=None,
            output=tmp_path / "board.kicad_pcb",
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=True,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert calls == {}
    assert "--production-check requires --project and pardal.lock" in captured.err


def test_cmd_compile_physical_rejects_allow_unlocked_with_production_check(
    monkeypatch, tmp_path, capsys
):
    calls: dict[str, bool] = {}

    monkeypatch.setattr(
        physical,
        "compile_physical",
        lambda spec, **kwargs: calls.setdefault("compiled", True),
    )

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            output=tmp_path / "board.kicad_pcb",
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=True,
            allow_unlocked=True,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert calls == {}
    assert "--allow-unlocked is invalid with --production-check" in captured.err


def test_cmd_compile_physical_rejects_allow_absolute_paths_with_production_check(
    monkeypatch, tmp_path, capsys
):
    calls: dict[str, bool] = {}

    monkeypatch.setattr(
        physical,
        "compile_physical",
        lambda spec, **kwargs: calls.setdefault("compiled", True),
    )

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            output=tmp_path / "board.kicad_pcb",
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=True,
            allow_unlocked=False,
            allow_absolute_paths=True,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert calls == {}
    assert "--allow-absolute-paths is invalid with --production-check" in captured.err


def test_cmd_compile_physical_writes_project_provenance(monkeypatch, tmp_path, capsys):
    output = tmp_path / "board.kicad_pcb"
    project = tmp_path / "pardal.yaml"
    ctx = object()
    calls: dict[str, object] = {}

    def fake_compile_physical(spec, **kwargs):
        calls["spec"] = spec
        calls.update(kwargs)
        return CompilePhysicalResult(output=output)

    def fake_create_project_context(manifest_path, *, target):
        calls["project"] = manifest_path
        calls["target"] = target
        return ctx

    def fake_require_project_lock(loaded_ctx):
        calls["locked_ctx"] = loaded_ctx

    def fake_write_project_provenance_artifacts(
        loaded_ctx,
        *,
        output_dir=None,
        allow_network_checks=None,
        cli_profiles=None,
        cli_enable_checks=None,
        cli_disable_checks=None,
        cli_disable_check_reasons=None,
    ):
        calls["provenance_ctx"] = loaded_ctx
        calls["provenance_output_dir"] = output_dir
        calls["provenance_allow_network_checks"] = allow_network_checks
        calls["provenance_cli_profiles"] = cli_profiles
        calls["provenance_cli_enable_checks"] = cli_enable_checks
        calls["provenance_cli_disable_checks"] = cli_disable_checks
        calls["provenance_cli_disable_check_reasons"] = cli_disable_check_reasons
        return SimpleNamespace(
            package_resolution=tmp_path / "package-resolution.json",
            profile_resolution=tmp_path / "profile-resolution.json",
        )

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)
    monkeypatch.setattr(project_context_module, "create_project_context", fake_create_project_context)
    monkeypatch.setattr(project_context_module, "require_project_lock", fake_require_project_lock)
    monkeypatch.setattr(
        project_provenance_module,
        "write_project_provenance_artifacts",
        fake_write_project_provenance_artifacts,
    )

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=project,
            target="fab",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=True,
            production_output_dir=tmp_path,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
            production_profile=["jlcpcb/lcsc:jlcpcb_smt"],
            enable_check=["fixture.required"],
            disable_check=["fixture.warning"],
            reason="fixture warning is signed off",
            warnerr=False,
        )
    )

    stdout = capsys.readouterr().out
    assert result == 0
    assert calls["project"] == project
    assert calls["target"] == "fab"
    assert calls["locked_ctx"] is ctx
    assert calls["provenance_ctx"] is ctx
    assert calls["provenance_output_dir"] == tmp_path
    assert calls["provenance_allow_network_checks"] is False
    assert calls["provenance_cli_profiles"] == ["jlcpcb/lcsc:jlcpcb_smt"]
    assert calls["provenance_cli_enable_checks"] == ["fixture.required"]
    assert calls["provenance_cli_disable_checks"] == ["fixture.warning"]
    assert calls["provenance_cli_disable_check_reasons"] == {
        "fixture.warning": "fixture warning is signed off"
    }
    assert f"Saved package resolution to {tmp_path / 'package-resolution.json'}" in stdout
    assert f"Saved profile resolution to {tmp_path / 'profile-resolution.json'}" in stdout


def test_cli_check_overrides_reject_unknown_check(tmp_path):
    ctx = SimpleNamespace(manifest=SimpleNamespace(path=tmp_path / "pardal.yaml"))

    try:
        cli_module._validate_cli_check_overrides(
            SimpleNamespace(enable_check=["fixture.unknown"], disable_check=[]),
            ctx,
        )
    except ProjectConfigError as exc:
        assert exc.diagnostic.code == "profile.check_unknown"
        assert exc.diagnostic.path == tmp_path / "pardal.yaml"
        assert exc.diagnostic.field == "cli.enable_check"
    else:
        raise AssertionError("expected unknown CLI check to fail")


def test_cli_check_overrides_accept_known_public_check(tmp_path):
    check_id = "fixture.cli_known"
    if check_id not in registered_checks():

        @check(
            id=check_id,
            stage=Stage.SOURCE_CONTRACT,
            default_severity=Severity.WARNING,
        )
        def _fixture_cli_known(ctx):
            return []

    ctx = SimpleNamespace(manifest=SimpleNamespace(path=tmp_path / "pardal.yaml"))

    cli_module._validate_cli_check_overrides(
        SimpleNamespace(enable_check=[check_id], disable_check=[]),
        ctx,
    )


def test_cmd_compile_physical_enforces_target_require_lock_without_production_check(
    monkeypatch,
    tmp_path,
):
    output = tmp_path / "board.kicad_pcb"
    project = tmp_path / "pardal.yaml"
    ctx = SimpleNamespace(build_target=SimpleNamespace(options={"require_lock": True}))
    calls: dict[str, object] = {}

    def fake_compile_physical(spec, **kwargs):
        calls["compiled"] = True
        return CompilePhysicalResult(output=output)

    def fake_create_project_context(manifest_path, *, target):
        calls["project"] = manifest_path
        calls["target"] = target
        return ctx

    def fake_require_project_lock(loaded_ctx):
        calls["locked_ctx"] = loaded_ctx

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)
    monkeypatch.setattr(project_context_module, "create_project_context", fake_create_project_context)
    monkeypatch.setattr(project_context_module, "require_project_lock", fake_require_project_lock)
    monkeypatch.setattr(
        project_provenance_module,
        "write_project_provenance_artifacts",
        lambda loaded_ctx, **kwargs: SimpleNamespace(
            package_resolution=tmp_path / "package-resolution.json",
            profile_resolution=tmp_path / "profile-resolution.json",
        ),
    )

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=project,
            target="fab",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=False,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
            allow_unlocked=False,
            allow_absolute_paths=False,
        )
    )

    assert result == 0
    assert calls["project"] == project
    assert calls["target"] == "fab"
    assert calls["locked_ctx"] is ctx
    assert calls["compiled"] is True


def test_cmd_compile_physical_adds_project_parts_to_build_summary(monkeypatch, tmp_path):
    output = tmp_path / "board.kicad_pcb"
    build_summary = tmp_path / "build-summary.json"
    project = tmp_path / "pardal.yaml"
    contract = tmp_path / "contract.override.yaml"
    ctx = SimpleNamespace(
        source_contract=SimpleNamespace(path=tmp_path / "contract.yaml"),
        build_target=SimpleNamespace(options={"allow_network_checks": True}),
        loaded_check_exports=("acme/gd32f310-support:checks/gd32f310.py",),
        profile_set=SimpleNamespace(
            requested=("acme/gd32f310-support:gd32f310_adc_12v",),
            expanded=(
                "pardal/core:analog_rc_filters",
                "acme/gd32f310-support:gd32_adc_frontend",
                "acme/gd32f310-support:gd32f310_adc_12v",
            ),
            enabled_checks=frozenset(
                {
                    "analog.rc_filter_contract_complete",
                    "analog.rc_filter_values_resolve",
                    "gd32.adc_frontend",
                }
            ),
            disabled_checks=frozenset({"fixture.warning"}),
            severity={"gd32.adc_frontend": "error"},
            requires_contract={"gd32.adc_frontend": ("adc.channels",)},
        ),
    )
    captured: dict[str, object] = {}

    def fake_compile_physical(spec, **kwargs):
        captured.update(kwargs)
        build_summary.write_text('{"schema": "pardal.build_summary/v1"}\n', encoding="utf-8")
        return CompilePhysicalResult(output=output)

    def fake_create_project_context(manifest_path, *, target):
        return ctx

    def fake_write_project_provenance_artifacts(
        loaded_ctx,
        *,
        output_dir=None,
        allow_network_checks=None,
        **kwargs,
    ):
        captured["provenance_allow_network_checks"] = allow_network_checks
        return SimpleNamespace(
            package_resolution=tmp_path / "package-resolution.json",
            profile_resolution=tmp_path / "profile-resolution.json",
        )

    def fake_package_resolution_for_context(loaded_ctx):
        assert loaded_ctx is ctx
        return {
            "part_aliases": {"MCU": "acme/gd32f310-support:GD32F310K8T6"},
            "selected_components": {
                "U1": {
                    "part_id": "acme/gd32f310-support:GD32F310K8T6",
                    "mpn": "GD32F310K8T6",
                    "lcsc": "C112130",
                    "footprint_id": "acme/gd32f310-support:gd32f310_lqfp32",
                }
            },
            "physical_libraries": {
                "acme/gd32f310-support:gd32f310": {
                    "footprints": ["acme/gd32f310-support:gd32f310_lqfp32"],
                    "route_groups": ["templates/routes/adc_frontend.yaml"],
                    "mechanical": ["templates/mechanical/mounting_holes.yaml"],
                    "metadata": {"board_family": "gd32"},
                }
            },
            "route_policies": {
                "acme/gd32f310-support:gd32f310_12v_adc": {
                    "backend": "pardal-routing-dsl",
                    "layer_stack": "two_layer",
                    "net_patterns": ["ADC*"],
                    "rules": {"clearance_mm": 0.2},
                }
            },
        }

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)
    monkeypatch.setattr(project_context_module, "create_project_context", fake_create_project_context)
    monkeypatch.setattr(project_context_module, "require_project_lock", lambda loaded_ctx: None)
    monkeypatch.setattr(
        project_provenance_module,
        "write_project_provenance_artifacts",
        fake_write_project_provenance_artifacts,
    )
    monkeypatch.setattr(
        project_provenance_module,
        "package_resolution_for_context",
        fake_package_resolution_for_context,
    )

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=project,
            target="fab",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=True,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=build_summary,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
            source_contract=contract,
            enable_check=["fixture.required"],
            disable_check=["fixture.warning"],
            production_profile=["jlcpcb/lcsc:jlcpcb_smt"],
            reason="fixture warning is covered by a signed board waiver",
            warnerr=True,
        )
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert result == 0
    assert captured["allow_network_checks"] is True
    assert captured["provenance_allow_network_checks"] is True
    assert captured["project_context"] is ctx
    assert payload["package_parts"] == {
        "schema": "pardal.package_parts_summary/v1",
        "part_aliases": {"MCU": "acme/gd32f310-support:GD32F310K8T6"},
        "selected_components": {
            "U1": {
                "part_id": "acme/gd32f310-support:GD32F310K8T6",
                "mpn": "GD32F310K8T6",
                "lcsc": "C112130",
                "footprint_id": "acme/gd32f310-support:gd32f310_lqfp32",
            }
        },
    }
    assert payload["package_physical"] == {
        "schema": "pardal.package_physical_summary/v1",
        "physical_libraries": {
            "acme/gd32f310-support:gd32f310": {
                "footprints": ["acme/gd32f310-support:gd32f310_lqfp32"],
                "route_groups": ["templates/routes/adc_frontend.yaml"],
                "mechanical": ["templates/mechanical/mounting_holes.yaml"],
                "metadata": {"board_family": "gd32"},
            }
        },
        "route_policies": {
            "acme/gd32f310-support:gd32f310_12v_adc": {
                "backend": "pardal-routing-dsl",
                "layer_stack": "two_layer",
                "net_patterns": ["ADC*"],
                "rules": {"clearance_mm": 0.2},
            }
        },
    }
    assert payload["project_overrides"] == {
        "schema": "pardal.project_overrides/v1",
        "project": str(project),
        "target": "fab",
        "production_profiles": ["jlcpcb/lcsc:jlcpcb_smt"],
        "enable_checks": ["fixture.required"],
        "disable_checks": ["fixture.warning"],
        "disable_check_reasons": {
            "fixture.warning": "fixture warning is covered by a signed board waiver"
        },
        "source_contract": str(contract),
        "source_contract_override": str(contract),
        "warnerr": True,
    }
    assert payload["project_provenance"] == {
        "schema": "pardal.project_provenance_summary/v1",
        "package_resolution": str(tmp_path / "package-resolution.json"),
        "profile_resolution": str(tmp_path / "profile-resolution.json"),
        "loaded_check_exports": ["acme/gd32f310-support:checks/gd32f310.py"],
        "profiles": {
            "requested": ["acme/gd32f310-support:gd32f310_adc_12v"],
            "expanded": [
                "pardal/core:analog_rc_filters",
                "acme/gd32f310-support:gd32_adc_frontend",
                "acme/gd32f310-support:gd32f310_adc_12v",
            ],
            "enabled_checks": [
                "analog.rc_filter_contract_complete",
                "analog.rc_filter_values_resolve",
                "gd32.adc_frontend",
            ],
            "disabled_checks": ["fixture.warning"],
            "severity": {"gd32.adc_frontend": "error"},
            "requires_contract": {"gd32.adc_frontend": ["adc.channels"]},
        },
    }


def test_cmd_compile_physical_applies_project_selected_footprints(monkeypatch, tmp_path):
    output = tmp_path / "board.kicad_pcb"
    spec = tmp_path / "board.pdl.yaml"
    contract = tmp_path / "board.contract.yaml"
    spec.write_text(
        """
source:
  netlist: board.net
board:
  width: 20mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:Raw_LQFP32
    at: [10mm, 10mm]
""",
        encoding="utf-8",
    )
    contract.write_text("schema: pardal.source_contract/v1\n", encoding="utf-8")
    ctx = SimpleNamespace(
        source_contract=SimpleNamespace(
            path=contract,
            components={
                "U1": {
                    "part_id": "acme/gd32f310-support:GD32F310K8T6",
                }
            },
        ),
        parts={
            "acme/gd32f310-support:GD32F310K8T6": SimpleNamespace(
                footprint="acme/gd32f310-support:gd32f310_lqfp32"
            )
        },
        footprints={
            "acme/gd32f310-support:gd32f310_lqfp32": SimpleNamespace(
                kicad="Package_QFP:LQFP-32_7x7mm_P0.8mm"
            )
        },
    )
    captured: dict[str, object] = {}

    def fake_compile_physical(spec_path, **kwargs):
        captured["spec_path"] = spec_path
        captured["spec_payload"] = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        captured.update(kwargs)
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)
    monkeypatch.setattr(project_context_module, "create_project_context", lambda manifest_path, *, target: ctx)
    monkeypatch.setattr(project_context_module, "require_project_lock", lambda loaded_ctx: None)
    monkeypatch.setattr(
        project_provenance_module,
        "write_project_provenance_artifacts",
        lambda loaded_ctx, **kwargs: SimpleNamespace(
            package_resolution=tmp_path / "package-resolution.json",
            profile_resolution=tmp_path / "profile-resolution.json",
        ),
    )

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=spec,
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=True,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
            source_contract=None,
            enable_check=[],
            disable_check=[],
            production_profile=[],
        )
    )

    assert result == 0
    assert captured["spec_path"] != spec
    assert captured["source_contract_path"] == contract
    assert captured["spec_payload"]["parts"]["U1"]["footprint"] == (
        "Package_QFP:LQFP-32_7x7mm_P0.8mm"
    )
    assert captured["spec_payload"]["footprint_aliases"] == {
        "Package_QFP:Raw_LQFP32": "Package_QFP:LQFP-32_7x7mm_P0.8mm"
    }


def test_cmd_compile_physical_passes_warnerr_to_compiler(monkeypatch, tmp_path):
    output = tmp_path / "board.kicad_pcb"
    captured: dict[str, object] = {}

    def fake_compile_physical(spec, **kwargs):
        captured.update(kwargs)
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=None,
            target="default",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=False,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
            source_contract=None,
            enable_check=[],
            disable_check=[],
            production_profile=[],
            warnerr=True,
        )
    )

    assert result == 0
    assert captured["warnerr"] is True


def test_cmd_compile_physical_requires_disable_check_reason_in_production(
    monkeypatch, tmp_path, capsys
):
    output = tmp_path / "board.kicad_pcb"
    calls: dict[str, bool] = {}

    monkeypatch.setattr(cli_module, "_load_compile_project_context", lambda args: object())
    monkeypatch.setattr(cli_module, "_project_spec_overlay", lambda args, ctx: None)
    monkeypatch.setattr(cli_module, "_write_compile_project_provenance", lambda args, ctx: None)
    monkeypatch.setattr(
        cli_module,
        "_augment_build_summary_with_project_parts",
        lambda args, ctx, provenance_artifacts=None: None,
    )
    monkeypatch.setattr(
        physical,
        "compile_physical",
        lambda spec, **kwargs: calls.setdefault("compiled", True),
    )

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=True,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
            source_contract=None,
            enable_check=[],
            disable_check=["fixture.warning"],
            production_profile=[],
            reason=None,
            warnerr=False,
        )
    )

    stderr = capsys.readouterr().err
    assert result == 1
    assert "requires --reason" in stderr
    assert "compiled" not in calls


def test_cmd_compile_physical_passes_disable_check_reason(monkeypatch, tmp_path):
    output = tmp_path / "board.kicad_pcb"
    captured: dict[str, object] = {}

    def fake_compile_physical(spec, **kwargs):
        captured.update(kwargs)
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(cli_module, "_load_compile_project_context", lambda args: object())
    monkeypatch.setattr(cli_module, "_project_spec_overlay", lambda args, ctx: None)
    monkeypatch.setattr(cli_module, "_write_compile_project_provenance", lambda args, ctx: None)
    monkeypatch.setattr(
        cli_module,
        "_augment_build_summary_with_project_parts",
        lambda args, ctx, provenance_artifacts=None: None,
    )
    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=True,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
            source_contract=None,
            enable_check=[],
            disable_check=["fixture.warning"],
            production_profile=[],
            reason="fixture warning is covered by a signed board waiver",
            warnerr=False,
        )
    )

    assert result == 0
    assert captured["disable_check_reasons"] == {
        "fixture.warning": "fixture warning is covered by a signed board waiver"
    }


def test_cmd_compile_physical_generates_project_footprint_library(monkeypatch, tmp_path):
    output = tmp_path / "build" / "board.kicad_pcb"
    spec = tmp_path / "board.pdl.yaml"
    footprint_source = tmp_path / "pkg" / "footprints" / "GD32F310K8_LQFP32.kicad_mod"
    footprint_source.parent.mkdir(parents=True)
    footprint_source.write_text('(footprint "GD32F310K8_LQFP32")\n', encoding="utf-8")
    spec.write_text(
        """
source:
  netlist: board.net
board:
  width: 20mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:Raw_LQFP32
    at: [10mm, 10mm]
""",
        encoding="utf-8",
    )
    ctx = SimpleNamespace(
        source_contract=SimpleNamespace(
            path=tmp_path / "board.contract.yaml",
            components={
                "U1": {
                    "footprint_id": "acme/gd32f310-support:gd32f310_lqfp32",
                }
            },
        ),
        parts={},
        footprints={
            "acme/gd32f310-support:gd32f310_lqfp32": SimpleNamespace(
                kicad="Package_QFP:LQFP-32_7x7mm_P0.8mm",
                source_path=footprint_source,
            )
        },
    )
    captured: dict[str, object] = {}

    def fake_compile_physical(spec_path, **kwargs):
        captured["spec_payload"] = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)
    monkeypatch.setattr(project_context_module, "create_project_context", lambda manifest_path, *, target: ctx)
    monkeypatch.setattr(project_context_module, "require_project_lock", lambda loaded_ctx: None)
    monkeypatch.setattr(
        project_provenance_module,
        "write_project_provenance_artifacts",
        lambda loaded_ctx, **kwargs: SimpleNamespace(
            package_resolution=tmp_path / "package-resolution.json",
            profile_resolution=tmp_path / "profile-resolution.json",
        ),
    )

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=spec,
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=True,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
            source_contract=None,
            enable_check=[],
            disable_check=[],
            production_profile=[],
        )
    )

    copied = output.parent / "pardal-footprints.pretty" / "GD32F310K8_LQFP32.kicad_mod"
    assert result == 0
    assert copied.read_text(encoding="utf-8") == '(footprint "GD32F310K8_LQFP32")\n'
    assert "pardal_project_footprints" in (output.parent / "fp-lib-table").read_text(encoding="utf-8")
    assert captured["spec_payload"]["parts"]["U1"]["footprint"] == (
        "pardal_project_footprints:GD32F310K8_LQFP32"
    )
    assert captured["spec_payload"]["footprint_aliases"] == {
        "Package_QFP:Raw_LQFP32": "pardal_project_footprints:GD32F310K8_LQFP32"
    }


def test_cmd_compile_physical_project_production_requires_lock(monkeypatch, tmp_path):
    output = tmp_path / "board.kicad_pcb"
    ctx = object()
    calls: dict[str, bool] = {}

    def fake_compile_physical(spec, **kwargs):
        calls["compiled"] = True
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)
    monkeypatch.setattr(
        project_context_module,
        "create_project_context",
        lambda manifest_path, *, target: ctx,
    )

    def fake_require_project_lock(loaded_ctx):
        assert loaded_ctx is ctx
        raise ProjectConfigError("project.lock_required", "lock required")

    monkeypatch.setattr(project_context_module, "require_project_lock", fake_require_project_lock)

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=True,
            production_output_dir=None,
            production_report=None,
            production_report_format="text",
            production_report_format_explicit=False,
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=False,
            route_diagnostics_report=None,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
        )
    )

    assert result == 1
    assert "compiled" not in calls


def test_cmd_project_sync_check_validates_without_syncing(monkeypatch, tmp_path, capsys):
    calls: dict[str, object] = {}

    def fake_check_project_sync(project):
        calls["checked"] = project

    def fake_sync_project(project, *, registry_index=None):
        calls["synced"] = (project, registry_index)
        return SimpleNamespace(packages=[])

    import pardal.packages.commands as package_commands_module

    monkeypatch.setattr(package_commands_module, "check_project_sync", fake_check_project_sync)
    monkeypatch.setattr(package_commands_module, "sync_project", fake_sync_project)

    result = cmd_project_sync(
        SimpleNamespace(
            project=tmp_path / "pardal.yaml",
            registry_index=tmp_path / "registry.yaml",
            check=True,
        )
    )

    stdout = capsys.readouterr().out
    assert result == 0
    assert calls == {"checked": tmp_path / "pardal.yaml"}
    assert "pardal.lock is up to date" in stdout
    assert "wrote pardal.lock" not in stdout


def test_cmd_project_add_installs_git_dependency_at_ref(tmp_path, capsys):
    project = tmp_path / "board" / "pardal.yaml"
    project.parent.mkdir()
    project.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/main.pardal.yaml
""",
        encoding="utf-8",
    )
    package_root = tmp_path / "repos" / "acme" / "friend-support"
    package_root.mkdir(parents=True)
    _write_cli_package_fixture(package_root)
    commit = _init_cli_git_repo(package_root)

    result = cmd_project_add(
        SimpleNamespace(
            spec=f"git://{package_root.as_posix()}#{commit}",
            project=project,
            registry_index=None,
        )
    )

    stdout = capsys.readouterr().out
    manifest_payload = yaml.safe_load(project.read_text(encoding="utf-8"))
    lock_payload = yaml.safe_load((project.parent / "pardal.lock").read_text(encoding="utf-8"))
    installed_manifest = (
        project.parent / ".pardal/packages/acme/friend-support/pardal.yaml"
    )

    assert result == 0
    assert "installed acme/friend-support" in stdout
    assert "wrote pardal.lock" in stdout
    assert manifest_payload["dependencies"] == [
        {
            "type": "git",
            "identifier": "acme/friend-support",
            "repo": package_root.as_posix(),
            "ref": commit,
        }
    ]
    assert installed_manifest.exists()
    assert lock_payload["packages"]["acme/friend-support"]["type"] == "git"
    assert lock_payload["packages"]["acme/friend-support"]["commit"] == commit


def test_cmd_project_add_list_remove_file_dependency_round_trip(tmp_path, capsys):
    project = tmp_path / "board" / "pardal.yaml"
    project.parent.mkdir()
    project.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/main.pardal.yaml
""",
        encoding="utf-8",
    )
    package_root = tmp_path / "friend_pkg"
    package_root.mkdir()
    _write_cli_package_fixture(package_root)

    add_result = cmd_project_add(
        SimpleNamespace(
            spec=f"file://../{package_root.name}",
            project=project,
            registry_index=None,
        )
    )
    add_stdout = capsys.readouterr().out

    list_result = cmd_project_list(SimpleNamespace(project=project))
    list_stdout = capsys.readouterr().out

    remove_result = cmd_project_remove(
        SimpleNamespace(
            identifier="acme/friend-support",
            project=project,
            registry_index=None,
        )
    )
    remove_stdout = capsys.readouterr().out

    manifest_payload = yaml.safe_load(project.read_text(encoding="utf-8"))
    lock_payload = yaml.safe_load((project.parent / "pardal.lock").read_text(encoding="utf-8"))
    installed_manifest = (
        project.parent / ".pardal/packages/acme/friend-support/pardal.yaml"
    )

    assert add_result == 0
    assert "installed acme/friend-support" in add_stdout
    assert list_result == 0
    assert "file://../friend_pkg [locked acme/friend-support installed]" in list_stdout
    assert remove_result == 0
    assert "wrote pardal.lock" in remove_stdout
    assert "dependencies" not in manifest_payload
    assert lock_payload["packages"] == {}
    assert not installed_manifest.exists()


def test_cmd_project_add_installs_registry_dependency_from_static_index(tmp_path, capsys):
    package_root = tmp_path / "package"
    package_root.mkdir()
    _write_cli_package_fixture(package_root)
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages: {}
""",
        encoding="utf-8",
    )
    sync_result = cmd_project_sync(
        SimpleNamespace(
            project=package_root / "pardal.yaml",
            registry_index=None,
            check=False,
        )
    )
    capsys.readouterr()
    publish_result = cmd_package_publish(
        SimpleNamespace(
            project=package_root / "pardal.yaml",
            dry_run=False,
            output_dir=None,
            registry_index=registry_index,
        )
    )
    capsys.readouterr()

    project = tmp_path / "board" / "pardal.yaml"
    project.parent.mkdir()
    project.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/main.pardal.yaml
""",
        encoding="utf-8",
    )

    add_result = cmd_project_add(
        SimpleNamespace(
            spec="acme/friend-support@0.1.0",
            project=project,
            registry_index=registry_index,
        )
    )

    stdout = capsys.readouterr().out
    manifest_payload = yaml.safe_load(project.read_text(encoding="utf-8"))
    lock_payload = yaml.safe_load((project.parent / "pardal.lock").read_text(encoding="utf-8"))
    installed_manifest = (
        project.parent / ".pardal/packages/acme/friend-support/pardal.yaml"
    )

    assert publish_result == 0
    assert sync_result == 0
    assert add_result == 0
    assert "installed acme/friend-support" in stdout
    assert manifest_payload["dependencies"] == [
        {
            "type": "registry",
            "identifier": "acme/friend-support",
            "release": "0.1.0",
        }
    ]
    assert lock_payload["packages"]["acme/friend-support"]["type"] == "registry"
    assert lock_payload["packages"]["acme/friend-support"]["release"] == "0.1.0"
    assert installed_manifest.exists()


def test_cmd_create_package_writes_checkable_scaffold(tmp_path, capsys):
    package_root = tmp_path / "cli-support"

    result = cmd_create_package(
        SimpleNamespace(
            identifier="acme/cli-support",
            output_dir=package_root,
        )
    )

    stdout = capsys.readouterr().out
    manifest_payload = yaml.safe_load((package_root / "pardal.yaml").read_text(encoding="utf-8"))

    assert result == 0
    assert str(package_root / "pardal.yaml") in stdout
    assert manifest_payload["project"]["identifier"] == "acme/cli-support"
    assert (package_root / "profiles/default.yaml").exists()
    assert (package_root / "checks/default.py").exists()
    assert (package_root / "templates/starter/pardal.yaml").exists()


def test_cmd_create_board_writes_default_board_project(tmp_path, capsys):
    board_root = tmp_path / "cli_board"

    result = cmd_create_board(
        SimpleNamespace(
            name="cli_board",
            output_dir=board_root,
            template=None,
            package_root=None,
            package_install_root=None,
        )
    )

    stdout = capsys.readouterr().out
    manifest_payload = yaml.safe_load((board_root / "pardal.yaml").read_text(encoding="utf-8"))

    assert result == 0
    assert str(board_root / "pardal.yaml") in stdout
    assert manifest_payload["project"]["type"] == "board"
    assert manifest_payload["project"]["name"] == "cli_board"
    assert manifest_payload["builds"]["default"]["entry"] == "boards/cli_board.pardal.yaml"
    assert (board_root / "boards/cli_board.pardal.yaml").exists()


def test_cmd_package_check_reports_package_and_export_count(
    monkeypatch,
    tmp_path,
    capsys,
):
    calls: dict[str, object] = {}

    def fake_check_package(project, *, publish=False):
        calls["checked"] = (project, publish)
        manifest = SimpleNamespace(project=SimpleNamespace(identifier="acme/pkg"))
        return SimpleNamespace(manifest=manifest, exports=(object(), object()))

    import pardal.packages.authoring as package_authoring_module

    monkeypatch.setattr(package_authoring_module, "check_package", fake_check_package)

    result = cmd_package_check(
        SimpleNamespace(project=tmp_path / "pardal.yaml", publish=True)
    )

    stdout = capsys.readouterr().out
    assert result == 0
    assert calls == {"checked": (tmp_path / "pardal.yaml", True)}
    assert "package ok: acme/pkg" in stdout
    assert "exports: 2" in stdout


def test_cmd_package_build_prints_package_artifacts(monkeypatch, tmp_path, capsys):
    calls: dict[str, object] = {}

    archive = tmp_path / "dist" / "pkg.tar.gz"
    manifest = tmp_path / "dist" / "pkg.manifest.json"
    sha256 = tmp_path / "dist" / "pkg.sha256"

    def fake_build_package(project, *, output_dir=None):
        calls["built"] = (project, output_dir)
        return SimpleNamespace(
            archive_path=archive,
            manifest_path=manifest,
            sha256_path=sha256,
        )

    import pardal.packages.authoring as package_authoring_module

    monkeypatch.setattr(package_authoring_module, "build_package", fake_build_package)

    result = cmd_package_build(
        SimpleNamespace(project=tmp_path / "pardal.yaml", output_dir=tmp_path / "dist")
    )

    stdout = capsys.readouterr().out
    assert result == 0
    assert calls == {"built": (tmp_path / "pardal.yaml", tmp_path / "dist")}
    assert str(archive) in stdout
    assert str(manifest) in stdout
    assert str(sha256) in stdout


def test_cmd_package_publish_dry_run_reports_artifacts(monkeypatch, tmp_path, capsys):
    calls: dict[str, object] = {}

    archive = tmp_path / "dist" / "pkg.tar.gz"
    manifest = tmp_path / "dist" / "pkg.manifest.json"
    sha256 = tmp_path / "dist" / "pkg.sha256"

    def fake_publish_package(
        project,
        *,
        dry_run,
        output_dir=None,
        registry_index=None,
    ):
        calls["published"] = (project, dry_run, output_dir, registry_index)
        return SimpleNamespace(
            dry_run=True,
            registry_index=registry_index,
            archive_path=archive,
            manifest_path=manifest,
            sha256_path=sha256,
        )

    import pardal.packages.authoring as package_authoring_module

    monkeypatch.setattr(package_authoring_module, "publish_package", fake_publish_package)

    result = cmd_package_publish(
        SimpleNamespace(
            project=tmp_path / "pardal.yaml",
            dry_run=True,
            output_dir=tmp_path / "dist",
            registry_index=tmp_path / "registry.yaml",
        )
    )

    stdout = capsys.readouterr().out
    assert result == 0
    assert calls == {
        "published": (
            tmp_path / "pardal.yaml",
            True,
            tmp_path / "dist",
            tmp_path / "registry.yaml",
        )
    }
    assert "publish dry-run ok" in stdout
    assert str(archive) in stdout
    assert str(manifest) in stdout
    assert str(sha256) in stdout


def test_cmd_package_publish_writes_static_registry(tmp_path, capsys):
    package_root = tmp_path / "publish_pkg"
    package_root.mkdir()
    _write_cli_package_fixture(package_root)
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages: {}
""",
        encoding="utf-8",
    )
    sync_result = cmd_project_sync(
        SimpleNamespace(
            project=package_root / "pardal.yaml",
            registry_index=None,
            check=False,
        )
    )
    capsys.readouterr()

    publish_result = cmd_package_publish(
        SimpleNamespace(
            project=package_root / "pardal.yaml",
            dry_run=False,
            output_dir=None,
            registry_index=registry_index,
        )
    )

    stdout = capsys.readouterr().out
    registry_payload = yaml.safe_load(registry_index.read_text(encoding="utf-8"))
    release = registry_payload["packages"]["acme/friend-support"]["versions"]["0.1.0"]
    archive_path = tmp_path / release["url"]

    assert sync_result == 0
    assert publish_result == 0
    assert f"published to {registry_index}" in stdout
    assert archive_path.exists()
    assert release["url"] == "packages/acme-friend-support-0.1.0.tar.gz"
    assert release["sha256"].startswith("sha256:")
    assert release["yanked"] is False
    assert release["requires_pardal"] == "^0.1.0"
    assert not (package_root / "dist").exists()


def test_cmd_production_check_uses_project_context(monkeypatch, tmp_path):
    ctx = SimpleNamespace(
        source_contract=SimpleNamespace(path=tmp_path / "contract.yaml"),
        build_target=SimpleNamespace(options={"allow_network_checks": True}),
    )
    calls: dict[str, object] = {}

    def fake_create_project_context(manifest_path, *, target):
        calls["created"] = (manifest_path, target)
        return ctx

    monkeypatch.setattr(project_context_module, "create_project_context", fake_create_project_context)
    monkeypatch.setattr(
        project_context_module,
        "require_project_lock",
        lambda loaded_ctx: calls.setdefault("locked_ctx", loaded_ctx),
    )
    monkeypatch.setattr(
        physical_spec_module,
        "load_physical_spec",
        lambda path: SimpleNamespace(source_netlist=None, path=path),
    )

    def fake_run_production_checks(check_ctx, **kwargs):
        calls["check_ctx"] = check_ctx
        calls["kwargs"] = kwargs
        return []

    monkeypatch.setattr(production_checks_module, "run_production_checks", fake_run_production_checks)

    result = cmd_production_check(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="fab",
            netlist=None,
            source_contract=None,
            build_summary=None,
            manufacturing_archive=None,
            enable_check=[],
            disable_check=[],
            production_profile=[],
            allow_network_checks=False,
            format="json",
        )
    )

    assert result == 0
    assert calls["created"] == (tmp_path / "pardal.yaml", "fab")
    assert calls["locked_ctx"] is ctx
    assert calls["check_ctx"].project_context is ctx
    assert calls["check_ctx"].source_contract is ctx.source_contract
    assert calls["check_ctx"].allow_network_checks is True


def test_cmd_production_check_writes_run_specific_project_provenance(
    monkeypatch,
    tmp_path,
    capsys,
):
    ctx = SimpleNamespace(
        source_contract=SimpleNamespace(path=tmp_path / "contract.yaml"),
        build_target=SimpleNamespace(options={"allow_network_checks": False}),
    )
    calls: dict[str, object] = {}

    monkeypatch.setattr(project_context_module, "create_project_context", lambda manifest_path, *, target: ctx)
    monkeypatch.setattr(project_context_module, "require_project_lock", lambda loaded_ctx: None)
    monkeypatch.setattr(
        physical_spec_module,
        "load_physical_spec",
        lambda path: SimpleNamespace(source_netlist=None, path=path),
    )
    monkeypatch.setattr(production_checks_module, "run_production_checks", lambda check_ctx, **kwargs: [])

    def fake_write_project_provenance_artifacts(loaded_ctx, **kwargs):
        calls["ctx"] = loaded_ctx
        calls.update(kwargs)
        return SimpleNamespace(
            package_resolution=tmp_path / "package-resolution.json",
            profile_resolution=tmp_path / "profile-resolution.json",
        )

    monkeypatch.setattr(
        project_provenance_module,
        "write_project_provenance_artifacts",
        fake_write_project_provenance_artifacts,
    )

    result = cmd_production_check(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="fab",
            netlist=None,
            source_contract=None,
            build_summary=None,
            manufacturing_archive=None,
            enable_check=["fixture.required"],
            disable_check=["fixture.warning"],
            production_profile=["jlcpcb/lcsc:jlcpcb_smt"],
            reason="fixture warning is signed off",
            allow_unlocked=False,
            allow_absolute_paths=False,
            allow_network_checks=True,
            output_dir=tmp_path,
            format="json",
            warnerr=False,
        )
    )

    stderr = capsys.readouterr().err
    assert result == 0
    assert calls["ctx"] is ctx
    assert calls["output_dir"] == tmp_path
    assert calls["allow_network_checks"] is True
    assert calls["cli_profiles"] == ["jlcpcb/lcsc:jlcpcb_smt"]
    assert calls["cli_enable_checks"] == ["fixture.required"]
    assert calls["cli_disable_checks"] == ["fixture.warning"]
    assert calls["cli_disable_check_reasons"] == {
        "fixture.warning": "fixture warning is signed off"
    }
    assert f"Saved package resolution to {tmp_path / 'package-resolution.json'}" in stderr
    assert f"Saved profile resolution to {tmp_path / 'profile-resolution.json'}" in stderr


def test_cmd_production_check_project_requires_lock(monkeypatch, tmp_path):
    ctx = SimpleNamespace(source_contract=SimpleNamespace())
    calls: dict[str, bool] = {}

    monkeypatch.setattr(
        project_context_module,
        "create_project_context",
        lambda manifest_path, *, target: ctx,
    )

    def fake_require_project_lock(loaded_ctx):
        assert loaded_ctx is ctx
        raise ProjectConfigError("project.lock_required", "lock required")

    monkeypatch.setattr(project_context_module, "require_project_lock", fake_require_project_lock)
    monkeypatch.setattr(
        physical_spec_module,
        "load_physical_spec",
        lambda path: calls.setdefault("loaded_spec", True),
    )

    result = cmd_production_check(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            source_contract=None,
            build_summary=None,
            manufacturing_archive=None,
            enable_check=[],
            disable_check=[],
            production_profile=[],
            allow_network_checks=False,
            format="text",
        )
    )

    assert result == 1
    assert "loaded_spec" not in calls


def test_cmd_production_check_rejects_allow_unlocked(monkeypatch, tmp_path, capsys):
    calls: dict[str, bool] = {}

    monkeypatch.setattr(
        physical_spec_module,
        "load_physical_spec",
        lambda path: calls.setdefault("loaded_spec", True),
    )

    result = cmd_production_check(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            source_contract=None,
            build_summary=None,
            manufacturing_archive=None,
            enable_check=[],
            disable_check=[],
            production_profile=[],
            allow_unlocked=True,
            allow_network_checks=False,
            format="text",
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert calls == {}
    assert "--allow-unlocked is invalid with production-check" in captured.err


def test_cmd_production_check_rejects_allow_absolute_paths(monkeypatch, tmp_path, capsys):
    calls: dict[str, bool] = {}

    monkeypatch.setattr(
        physical_spec_module,
        "load_physical_spec",
        lambda path: calls.setdefault("loaded_spec", True),
    )

    result = cmd_production_check(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            source_contract=None,
            build_summary=None,
            manufacturing_archive=None,
            enable_check=[],
            disable_check=[],
            production_profile=[],
            allow_unlocked=False,
            allow_absolute_paths=True,
            allow_network_checks=False,
            format="text",
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert calls == {}
    assert "--allow-absolute-paths is invalid with production-check" in captured.err


def test_cmd_production_check_warnerr_escalates_warnings(monkeypatch, tmp_path, capsys):
    ctx = SimpleNamespace(source_contract=SimpleNamespace(path=tmp_path / "contract.yaml"))

    monkeypatch.setattr(project_context_module, "create_project_context", lambda manifest_path, *, target: ctx)
    monkeypatch.setattr(project_context_module, "require_project_lock", lambda loaded_ctx: None)
    monkeypatch.setattr(
        physical_spec_module,
        "load_physical_spec",
        lambda path: SimpleNamespace(source_netlist=None, path=path),
    )
    monkeypatch.setattr(
        production_checks_module,
        "run_production_checks",
        lambda check_ctx, **kwargs: [
            SimpleNamespace(
                severity="warning",
                code="fixture.warning",
                message="warning finding",
                source="contract.yaml",
            )
        ],
    )

    result = cmd_production_check(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            source_contract=None,
            build_summary=None,
            manufacturing_archive=None,
            enable_check=[],
            disable_check=[],
            production_profile=[],
            allow_network_checks=False,
            format="json",
            warnerr=True,
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert payload["findings"][0]["severity"] == "error"
    assert payload["dfm_report"]["by_severity"] == {"error": 1}
    assert payload["dfm_report"]["by_code"]["fixture.warning"]["severities"] == ["error"]


def test_cmd_production_check_requires_disable_check_reason(monkeypatch, tmp_path, capsys):
    ctx = SimpleNamespace(source_contract=SimpleNamespace(path=tmp_path / "contract.yaml"))
    calls: dict[str, bool] = {}

    monkeypatch.setattr(project_context_module, "create_project_context", lambda manifest_path, *, target: ctx)
    monkeypatch.setattr(project_context_module, "require_project_lock", lambda loaded_ctx: None)
    monkeypatch.setattr(
        physical_spec_module,
        "load_physical_spec",
        lambda path: SimpleNamespace(source_netlist=None, path=path),
    )
    monkeypatch.setattr(
        production_checks_module,
        "run_production_checks",
        lambda check_ctx, **kwargs: calls.setdefault("checked", True),
    )

    result = cmd_production_check(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            source_contract=None,
            build_summary=None,
            manufacturing_archive=None,
            enable_check=[],
            disable_check=["fixture.warning"],
            production_profile=[],
            reason="",
            allow_network_checks=False,
            format="text",
            warnerr=False,
        )
    )

    stderr = capsys.readouterr().err
    assert result == 1
    assert "requires --reason" in stderr
    assert "checked" not in calls


def test_cmd_production_check_passes_disable_check_reason(monkeypatch, tmp_path):
    ctx = SimpleNamespace(source_contract=SimpleNamespace(path=tmp_path / "contract.yaml"))
    captured: dict[str, object] = {}

    monkeypatch.setattr(project_context_module, "create_project_context", lambda manifest_path, *, target: ctx)
    monkeypatch.setattr(project_context_module, "require_project_lock", lambda loaded_ctx: None)
    monkeypatch.setattr(
        physical_spec_module,
        "load_physical_spec",
        lambda path: SimpleNamespace(source_netlist=None, path=path),
    )

    def fake_run_production_checks(check_ctx, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(production_checks_module, "run_production_checks", fake_run_production_checks)

    result = cmd_production_check(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=tmp_path / "pardal.yaml",
            target="default",
            netlist=None,
            source_contract=None,
            build_summary=None,
            manufacturing_archive=None,
            enable_check=[],
            disable_check=["fixture.warning"],
            production_profile=[],
            reason="covered by signed source-contract waiver",
            allow_network_checks=False,
            format="json",
            warnerr=False,
        )
    )

    assert result == 0
    assert captured["disable_check_reasons"] == {
        "fixture.warning": "covered by signed source-contract waiver"
    }


def test_production_check_accepts_documented_profile_alias(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_cmd_production_check(args):
        captured["profiles"] = args.production_profile
        return 0

    monkeypatch.setattr(cli_module, "cmd_production_check", fake_cmd_production_check)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pardal",
            "production-check",
            str(tmp_path / "board.pdl.yaml"),
            "--project",
            str(tmp_path / "pardal.yaml"),
            "--profile",
            "jlcpcb/lcsc:jlcpcb_full_pcba",
        ],
    )

    assert cli_module.main() == 0
    assert captured["profiles"] == ["jlcpcb/lcsc:jlcpcb_full_pcba"]


def test_production_check_accepts_documented_allow_unlocked_flag(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_cmd_production_check(args):
        captured["allow_unlocked"] = args.allow_unlocked
        return 0

    monkeypatch.setattr(cli_module, "cmd_production_check", fake_cmd_production_check)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pardal",
            "production-check",
            str(tmp_path / "board.pdl.yaml"),
            "--project",
            str(tmp_path / "pardal.yaml"),
            "--allow-unlocked",
        ],
    )

    assert cli_module.main() == 0
    assert captured["allow_unlocked"] is True


def test_production_check_accepts_output_dir_for_provenance(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_cmd_production_check(args):
        captured["output_dir"] = args.output_dir
        return 0

    monkeypatch.setattr(cli_module, "cmd_production_check", fake_cmd_production_check)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pardal",
            "production-check",
            str(tmp_path / "board.pdl.yaml"),
            "--project",
            str(tmp_path / "pardal.yaml"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert cli_module.main() == 0
    assert captured["output_dir"] == tmp_path / "out"


def test_cmd_production_check_rejects_direct_file_mode(monkeypatch, tmp_path, capsys):
    calls: dict[str, bool] = {}

    monkeypatch.setattr(
        physical_spec_module,
        "load_physical_spec",
        lambda path: calls.setdefault("loaded_spec", True),
    )

    result = cmd_production_check(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            project=None,
            target="default",
            netlist=None,
            source_contract=None,
            build_summary=None,
            manufacturing_archive=None,
            enable_check=[],
            disable_check=[],
            production_profile=[],
            allow_network_checks=False,
            format="text",
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert calls == {}
    assert "production-check requires --project and pardal.lock" in captured.err


def test_cmd_compile_physical_preset_preserves_explicit_overrides(monkeypatch, tmp_path):
    output = tmp_path / "custom-board.kicad_pcb"
    custom_drc_report = tmp_path / "custom-drc.rpt"
    custom_production_report = tmp_path / "custom-production.txt"
    custom_diagnostics = tmp_path / "custom-diagnostics.txt"
    custom_gerbers = tmp_path / "custom-gerbers"
    captured: dict[str, object] = {}

    def fake_compile_physical(spec, **kwargs):
        captured["spec"] = spec
        captured.update(kwargs)
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=custom_drc_report,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=False,
            production_output_dir=tmp_path,
            production_report=custom_production_report,
            production_report_format="text",
            production_report_format_explicit=True,
            drc_diagnostics_report=custom_diagnostics,
            drc_diagnostics_format="text",
            drc_diagnostics_format_explicit=True,
            route_diagnostics_report=tmp_path / "explicit-route-diag.json",
            build_summary_output=tmp_path / "custom-build-summary.json",
            manufacturing_archive_output=tmp_path / "custom-manufacturing-package.zip",
            bom_output=tmp_path / "custom.bom.csv",
            pnp_output=tmp_path / "custom.pnp.csv",
            jlc_bom_output=tmp_path / "custom.jlc.bom.csv",
            jlc_pnp_output=tmp_path / "custom.jlc.pnp.csv",
            exclude_helpers_in_exports=True,
            gerber_output_dir=custom_gerbers,
            drill_output_dir=tmp_path / "custom-drill",
        )
    )

    assert result == 0
    assert captured["drc_report"] == custom_drc_report
    assert captured["bom_output"] == tmp_path / "custom.bom.csv"
    assert captured["pnp_output"] == tmp_path / "custom.pnp.csv"
    assert captured["jlc_bom_output"] == tmp_path / "custom.jlc.bom.csv"
    assert captured["jlc_pnp_output"] == tmp_path / "custom.jlc.pnp.csv"
    assert captured["production_report"] == custom_production_report
    assert captured["production_report_format"] == "text"
    assert captured["drc_diagnostics_report"] == custom_diagnostics
    assert captured["drc_diagnostics_format"] == "text"
    assert captured["route_diagnostics_report"] == tmp_path / "explicit-route-diag.json"
    assert captured["gerber_output_dir"] == custom_gerbers
    assert captured["drill_output_dir"] == tmp_path / "custom-drill"
    assert captured["build_summary_output"] == tmp_path / "custom-build-summary.json"
    assert (
        captured["manufacturing_archive_output"]
        == tmp_path / "custom-manufacturing-package.zip"
    )
    assert captured["include_helpers_in_exports"] is False


def test_cmd_compile_physical_writes_diagnostics_dashboard(monkeypatch, tmp_path, capsys):
    output = tmp_path / "board.kicad_pcb"
    route_diag = tmp_path / "route-diagnostics.json"
    dashboard = tmp_path / "diagnostics-dashboard.json"
    route_diag.write_text(
        json.dumps(
            {
                "strict_aborted": True,
                "failed_candidate_count": 1,
                "violation_count": 1,
                "failures": [
                    {
                        "net": "PGC1_RB4",
                        "strategy": "escape_bundle",
                        "route_name": "pgc_lane",
                        "route_index": 1,
                        "violations": [
                            {
                                "code": "track_to_pad_clearance",
                                "distance": -0.06,
                                "layer": "F.Cu",
                                "message": (
                                    "PGC1_RB4 segment on F.Cu is -0.060mm "
                                    "from C5.1; requires 0.200mm"
                                ),
                                "net": "PGC1_RB4",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_compile_physical(spec, **kwargs):
        return CompilePhysicalResult(output=output)

    monkeypatch.setattr(physical, "compile_physical", fake_compile_physical)

    result = cmd_compile_physical(
        SimpleNamespace(
            spec=tmp_path / "board.pdl.yaml",
            netlist=None,
            output=output,
            place_only=False,
            drc_report=None,
            no_drc=False,
            strict=False,
            enable_route_group=[],
            probe_deferred_power=False,
            production_check=False,
            production_report=None,
            production_report_format="text",
            drc_diagnostics_report=None,
            drc_diagnostics_format="text",
            route_diagnostics_report=route_diag,
            diagnostics_dashboard=dashboard,
            build_summary_output=None,
            manufacturing_archive_output=None,
            bom_output=None,
            pnp_output=None,
            jlc_bom_output=None,
            jlc_pnp_output=None,
            exclude_helpers_in_exports=False,
            gerber_output_dir=None,
            drill_output_dir=None,
        )
    )

    stdout = capsys.readouterr().out
    saved = json.loads(dashboard.read_text(encoding="utf-8"))
    assert result == 0
    assert saved["first_blockers"][0]["counterparty"] == "C5.1"
    assert "Saved diagnostics dashboard" in stdout


def _write_cli_package_fixture(root: Path) -> None:
    (root / "profiles").mkdir()
    (root / "pardal.yaml").write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: package
  identifier: acme/friend-support
  version: 0.1.0
  repository: https://example.invalid/acme/friend-support
  summary: Friend-shared support package
  license: MIT
  authors:
    - name: Hardware
exports:
  profiles:
    - profiles/
""",
        encoding="utf-8",
    )
    (root / "profiles" / "default.yaml").write_text(
        """
schema: pardal.profile/v1
profiles:
  default:
    enable_checks: []
""",
        encoding="utf-8",
    )


def _init_cli_git_repo(path: Path) -> str:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=path,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()

    run("init")
    run("config", "user.email", "tests@example.invalid")
    run("config", "user.name", "Pardal Tests")
    run("add", ".")
    run("commit", "-m", "initial")
    return run("rev-parse", "HEAD")
