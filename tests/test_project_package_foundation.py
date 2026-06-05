from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import threading
from types import SimpleNamespace

import pytest
import yaml

import pardal.production_checks.profile_resolution as profile_resolution_module
from pardal.packages.authoring import build_package, check_package, publish_package
from pardal.checks.api import Finding, Severity, Stage, check, registered_checks
from pardal.packages.exports import ExportDefinition, scan_package_exports
from pardal.packages.footprints import load_footprint_export
from pardal.packages.parts import load_part_catalog_export
from pardal.packages.physical_libraries import load_physical_library_export
from pardal.packages.route_policies import load_route_policy_export
from pardal.packages.templates import load_board_template_export
from pardal.packages.examples import load_example_export
from pardal.packages.index import InstalledPackage, build_package_index
from pardal.packages.lock import file_hash, load_lock_file, lock_to_dict, package_content_hash
from pardal.packages.registry_client import StaticRegistryClient
from pardal.packages.commands import (
    add_dependency,
    check_project_sync,
    list_dependencies,
    remove_dependency,
    sync_project,
    update_lock,
)
from pardal.packages.create import create_board_project, create_package_project
from pardal.packages.spec import parse_dependency_spec
from pardal.physical.compiler import _build_package_physical_context
from pardal.profiles.expander import expand_profiles
from pardal.profiles.loader import load_profile_file
from pardal.production_checks import (
    CheckContext,
    CheckFinding,
    profile_resolution_for_context,
    run_production_checks,
)
from pardal.production_checks.profiles import PROFILE_CHECKS
from pardal.project.context import create_project_context, require_project_lock
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.lockfile import load_project_lock_file
from pardal.project.manifest import load_project_manifest
from pardal.project.provenance import package_resolution_for_context
from pardal.project.provenance import write_project_provenance_artifacts


def test_generated_package_manager_artifacts_are_ignored() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ignore_lines = {
        line.strip()
        for line in (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        ".pardal/",
        "dist/",
        "build/",
        "*.egg-info/",
        "__pycache__/",
        "*pyc",
        "*.pyo",
        "*.kicad_pcb.bak",
        "*.rpt",
        "package-resolution.json",
        "profile-resolution.json",
        "production-checks.json",
        "build-summary.json",
        "manufacturing-package.zip",
    } <= ignore_lines


def test_canonical_package_manager_fixtures_have_no_generated_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture_roots = (
        repo_root / "examples/packages",
        repo_root / "examples/boards",
    )
    generated_names = {
        ".pardal",
        "dist",
        "build",
        "__pycache__",
        "package-resolution.json",
        "profile-resolution.json",
        "production-checks.json",
        "build-summary.json",
        "manufacturing-package.zip",
    }
    generated_suffixes = (
        ".pyc",
        ".pyo",
        ".egg-info",
        ".kicad_pcb.bak",
        ".rpt",
    )

    generated = [
        path.relative_to(repo_root).as_posix()
        for root in fixture_roots
        if root.exists()
        for path in root.rglob("*")
        if path.name in generated_names or path.name.endswith(generated_suffixes)
    ]

    assert generated == []


def test_superseded_package_manager_docs_are_historical_pointers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    superseded_docs = (
        repo_root / "aidocs/profile_enabled_production_checks_plan.md",
        repo_root / "aidocs/gd32_missing_production_checks.md",
    )

    for doc in superseded_docs:
        text = doc.read_text(encoding="utf-8")
        assert text.startswith("# Historical:"), doc
        assert "not the active implementation plan" in text, doc
        assert "project_package_manager_design.md" in text, doc
        assert "Do not add new action items here" in text, doc


def test_package_archive_excludes_generated_production_artifacts(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    for name in (
        "package-resolution.json",
        "profile-resolution.json",
        "production-checks.json",
        "drc-report.json",
        "build-summary.json",
        "validation-results.json",
        "manufacturing-package.zip",
        "board-drc.rpt",
        "board-drc.json",
        "board.kicad_pcb.bak",
    ):
        (package_root / name).write_text("generated\n", encoding="utf-8")

    result = _build_synced_package(package_root / "pardal.yaml")

    with tarfile.open(result.archive_path, "r:gz") as archive:
        archived_names = set(archive.getnames())

    assert "pardal.yaml" in archived_names
    assert not {
        "package-resolution.json",
        "profile-resolution.json",
        "production-checks.json",
        "drc-report.json",
        "build-summary.json",
        "validation-results.json",
        "manufacturing-package.zip",
        "board-drc.rpt",
        "board-drc.json",
        "board.kicad_pcb.bak",
    } & archived_names


def test_package_content_hash_excludes_generated_production_artifacts(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    baseline = package_content_hash(package_root)
    for name in (
        "package-resolution.json",
        "profile-resolution.json",
        "production-checks.json",
        "drc-report.json",
        "build-summary.json",
        "validation-results.json",
        "manufacturing-package.zip",
        "board-drc.rpt",
        "board-drc.json",
        "board.kicad_pcb.bak",
    ):
        (package_root / name).write_text("generated\n", encoding="utf-8")
    (package_root / "build").mkdir()
    (package_root / "build" / "generated.txt").write_text("generated\n", encoding="utf-8")
    (package_root / "__pycache__").mkdir()
    (package_root / "__pycache__" / "cache.pyc").write_bytes(b"generated")

    assert package_content_hash(package_root) == baseline


def test_package_manifest_exports_are_deterministically_sorted(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)

    result = _build_synced_package(package_root / "pardal.yaml")
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    export_keys = [
        (item["kind"], item["id"], item["path"])
        for item in payload["exports"]
    ]

    assert export_keys == sorted(export_keys)


def test_board_manifest_loads_default_build(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/main.pardal.yaml
    profiles:
      - pardal/core:general_fab_ready
    options:
      require_lock: true
    outputs:
      production_checks: true
""",
        encoding="utf-8",
    )

    loaded = load_project_manifest(manifest)

    assert loaded.is_board
    assert loaded.builds["default"].entry == Path("boards/main.pardal.yaml")
    assert loaded.builds["default"].profiles == ("pardal/core:general_fab_ready",)


def test_board_manifest_rejects_malformed_yaml(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text("schema: [\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="manifest.yaml_invalid") as exc_info:
        load_project_manifest(manifest)

    assert exc_info.value.diagnostic.path == manifest
    assert exc_info.value.diagnostic.field == "yaml"


def test_board_manifest_rejects_unsupported_schema(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v2
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

    with pytest.raises(ProjectConfigError, match="manifest.schema_unsupported") as exc_info:
        load_project_manifest(manifest)

    assert exc_info.value.diagnostic.path == manifest
    assert exc_info.value.diagnostic.field == "schema"


def test_board_manifest_rejects_absolute_paths(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
paths:
  source: /tmp/source
builds:
  default:
    entry: boards/main.pardal.yaml
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="manifest.absolute_path"):
        load_project_manifest(manifest)


def test_board_manifest_allows_absolute_paths_with_explicit_development_override(
    tmp_path: Path,
) -> None:
    board_source = tmp_path / "boards" / "main.pardal.yaml"
    board_source.parent.mkdir()
    board_source.write_text("source:\n  note: absolute dev path\n", encoding="utf-8")
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        f"""
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: abs
builds:
  default:
    entry: {board_source}
""",
        encoding="utf-8",
    )

    loaded = load_project_manifest(manifest, allow_absolute_paths=True)

    assert loaded.builds["default"].entry == board_source


def test_manifest_rejects_incompatible_requires_pardal(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.2.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/main.pardal.yaml
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="manifest.requires_pardal_incompatible"):
        load_project_manifest(manifest)


def test_manifest_rejects_invalid_requires_pardal_with_field(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "next"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/main.pardal.yaml
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="manifest.requires_pardal_invalid") as exc_info:
        load_project_manifest(manifest)

    assert exc_info.value.diagnostic.path == manifest
    assert exc_info.value.diagnostic.field == "requires-pardal"


def test_dependency_shorthand_parses_registry_file_and_git() -> None:
    registry = parse_dependency_spec("jlcpcb/lcsc@0.4.0")
    file_dep = parse_dependency_spec("file://../local-pack")
    git_dep = parse_dependency_spec(
        "git://github.com/acme/gd32f310-support.git#v0.1.0:packages/gd32"
    )

    assert registry.type == "registry"
    assert registry.identifier == "jlcpcb/lcsc"
    assert registry.release == "0.4.0"
    assert file_dep.type == "file"
    assert file_dep.path == Path("../local-pack")
    assert git_dep.type == "git"
    assert git_dep.identifier is None
    assert git_dep.ref == "v0.1.0"
    assert git_dep.path_within_repo == "packages/gd32"


def test_git_dependency_path_must_stay_inside_repo() -> None:
    with pytest.raises(ProjectConfigError, match="dependency.git_path_invalid"):
        parse_dependency_spec("git://github.com/acme/support.git#v0.1.0:../support")

    with pytest.raises(ProjectConfigError, match="dependency.git_path_invalid"):
        parse_dependency_spec("git://github.com/acme/support.git#v0.1.0:/tmp/support")


@pytest.mark.parametrize("git_path", ["../support", "/tmp/support"])
def test_manifest_git_dependency_path_must_stay_inside_repo(
    tmp_path: Path,
    git_path: str,
) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        f"""
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
dependencies:
  - type: git
    identifier: acme/support
    repo: https://github.com/acme/support.git
    ref: v0.1.0
    path: {git_path}
builds:
  default:
    entry: boards/main.pardal.yaml
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="dependency.git_path_invalid") as exc_info:
        load_project_manifest(manifest)

    assert exc_info.value.diagnostic.field == "dependencies[0].path"


def test_package_manifest_scans_profiles_parts_and_checks(tmp_path: Path) -> None:
    _write_package_fixture(tmp_path)

    manifest = load_project_manifest(tmp_path / "pardal.yaml")
    exports = scan_package_exports(manifest)
    index = build_package_index(manifest)

    installed = index.packages_by_id["acme/gd32f310-support"]
    assert isinstance(installed, InstalledPackage)
    assert installed.root == tmp_path
    assert installed.manifest is manifest
    assert {export.id for export in exports} >= {
        "acme/gd32f310-support:gd32f310_adc_12v",
        "acme/gd32f310-support:GD32F310K8T6",
        "acme/gd32f310-support:gd32f310",
        "acme/gd32f310-support:starter",
    }
    assert "acme/gd32f310-support:gd32f310_adc_12v" in index.profiles_by_id
    assert "acme/gd32f310-support:GD32F310K8T6" in index.parts_by_id
    assert "acme/gd32f310-support:gd32f310" in index.checks_by_id
    assert "acme/gd32f310-support:starter" in index.examples_by_id


def test_package_export_ids_must_be_non_empty_strings(tmp_path: Path) -> None:
    _write_package_fixture(tmp_path)
    (tmp_path / "parts" / "gd32.yaml").write_text(
        """
schema: pardal.parts/v1
parts:
  123:
    manufacturer: GigaDevice
""",
        encoding="utf-8",
    )

    manifest = load_project_manifest(tmp_path / "pardal.yaml")

    with pytest.raises(ProjectConfigError, match="part_catalog.id_invalid"):
        scan_package_exports(manifest)


@pytest.mark.parametrize(
    ("relative_path", "payload", "error_code"),
    [
        (
            "parts/parts.yaml",
            """
schema: pardal.parts/v1
parts:
  other/support:foreign:
    manufacturer: Example
""",
            "part_catalog.id_invalid",
        ),
        (
            "footprints/footprints.yaml",
            """
schema: pardal.footprints/v1
footprints:
  other/support:foreign:
    kicad: Connector_Generic:Conn_01x02
""",
            "footprint.id_invalid",
        ),
        (
            "physical_libraries/libraries.yaml",
            """
schema: pardal.physical_library/v1
libraries:
  other/support:foreign:
    footprints: []
""",
            "physical_library.id_invalid",
        ),
        (
            "routing/policies.yaml",
            """
schema: pardal.route_policy/v1
policies:
  other/support:foreign:
    rules: {}
""",
            "route_policy.id_invalid",
        ),
    ],
)
def test_package_export_ids_must_not_claim_foreign_namespace(
    tmp_path: Path,
    relative_path: str,
    payload: str,
    error_code: str,
) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / relative_path).write_text(payload, encoding="utf-8")

    with pytest.raises(ProjectConfigError, match=error_code):
        check_package(result.manifest_path)


@pytest.mark.parametrize(
    ("relative_path", "payload", "load_export", "expected_id"),
    [
        (
            "parts/parts.yaml",
            """
schema: pardal.parts/v1
parts:
  acme/new-support:placeholder:
    manufacturer: Example
""",
            load_part_catalog_export,
            "acme/new-support:placeholder",
        ),
        (
            "footprints/footprints.yaml",
            """
schema: pardal.footprints/v1
footprints:
  acme/new-support:placeholder:
    kicad: Connector_Generic:Conn_01x02
""",
            load_footprint_export,
            "acme/new-support:placeholder",
        ),
        (
            "physical_libraries/libraries.yaml",
            """
schema: pardal.physical_library/v1
libraries:
  acme/new-support:default:
    footprints: []
""",
            load_physical_library_export,
            "acme/new-support:default",
        ),
        (
            "routing/policies.yaml",
            """
schema: pardal.route_policy/v1
policies:
  acme/new-support:default:
    rules: {}
""",
            load_route_policy_export,
            "acme/new-support:default",
        ),
        (
            "templates.yaml",
            """
schema: pardal.templates/v1
templates:
  acme/new-support:starter:
    path: templates/starter
""",
            load_board_template_export,
            "acme/new-support:starter",
        ),
        (
            "examples.yaml",
            """
schema: pardal.examples/v1
examples:
  acme/new-support:starter:
    mode: documentation_only
    path: examples/starter
""",
            load_example_export,
            "acme/new-support:starter",
        ),
    ],
)
def test_package_model_loaders_accept_own_qualified_export_ids(
    tmp_path: Path,
    relative_path: str,
    payload: str,
    load_export,
    expected_id: str,
) -> None:
    package_root = tmp_path / "new-support"
    package_root.mkdir()
    export_path = package_root / relative_path
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(payload, encoding="utf-8")
    export = ExportDefinition(
        kind="parts",
        id=expected_id,
        path=export_path.relative_to(package_root),
        hash=file_hash(export_path),
        package_id="acme/new-support",
        package_root=package_root,
    )

    loaded = load_export(export)

    assert tuple(loaded) == (expected_id,)


@pytest.mark.parametrize(
    ("relative_path", "payload", "load_export", "error_code"),
    [
        (
            "parts/parts.yaml",
            """
schema: pardal.parts/v1
parts:
  other/support:foreign:
    manufacturer: Example
""",
            load_part_catalog_export,
            "part_catalog.id_invalid",
        ),
        (
            "footprints/footprints.yaml",
            """
schema: pardal.footprints/v1
footprints:
  other/support:foreign:
    kicad: Connector_Generic:Conn_01x02
""",
            load_footprint_export,
            "footprint.id_invalid",
        ),
        (
            "physical_libraries/libraries.yaml",
            """
schema: pardal.physical_library/v1
libraries:
  other/support:foreign:
    footprints: []
""",
            load_physical_library_export,
            "physical_library.id_invalid",
        ),
        (
            "routing/policies.yaml",
            """
schema: pardal.route_policy/v1
policies:
  other/support:foreign:
    rules: {}
""",
            load_route_policy_export,
            "route_policy.id_invalid",
        ),
        (
            "templates.yaml",
            """
schema: pardal.templates/v1
templates:
  other/support:foreign:
    path: templates/starter
""",
            load_board_template_export,
            "template.id_invalid",
        ),
        (
            "examples.yaml",
            """
schema: pardal.examples/v1
examples:
  other/support:foreign:
    mode: documentation_only
    path: examples/starter
""",
            load_example_export,
            "example.id_invalid",
        ),
    ],
)
def test_package_model_loaders_reject_foreign_qualified_export_ids(
    tmp_path: Path,
    relative_path: str,
    payload: str,
    load_export,
    error_code: str,
) -> None:
    package_root = tmp_path / "new-support"
    package_root.mkdir()
    export_path = package_root / relative_path
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(payload, encoding="utf-8")
    export = ExportDefinition(
        kind="parts",
        id="acme/new-support:placeholder",
        path=export_path.relative_to(package_root),
        hash=file_hash(export_path),
        package_id="acme/new-support",
        package_root=package_root,
    )

    with pytest.raises(ProjectConfigError, match=error_code):
        load_export(export)


@pytest.mark.parametrize(
    ("relative_path", "load_export", "error_code"),
    [
        ("parts/parts.yaml", load_part_catalog_export, "part_catalog.yaml_invalid"),
        ("footprints/footprints.yaml", load_footprint_export, "footprint.yaml_invalid"),
        (
            "physical_libraries/libraries.yaml",
            load_physical_library_export,
            "physical_library.yaml_invalid",
        ),
        ("routing/policies.yaml", load_route_policy_export, "route_policy.yaml_invalid"),
        ("templates.yaml", load_board_template_export, "template.yaml_invalid"),
        ("examples.yaml", load_example_export, "example.yaml_invalid"),
    ],
)
def test_package_model_loaders_reject_malformed_yaml(
    tmp_path: Path,
    relative_path: str,
    load_export,
    error_code: str,
) -> None:
    package_root = tmp_path / "new-support"
    package_root.mkdir()
    export_path = package_root / relative_path
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text("schema: [\n", encoding="utf-8")
    export = ExportDefinition(
        kind="parts",
        id="acme/new-support:placeholder",
        path=export_path.relative_to(package_root),
        hash=file_hash(export_path),
        package_id="acme/new-support",
        package_root=package_root,
    )

    with pytest.raises(ProjectConfigError, match=error_code) as exc_info:
        load_export(export)

    assert exc_info.value.diagnostic.path == export_path
    assert exc_info.value.diagnostic.field == "yaml"


def test_project_and_package_module_surfaces_match_design() -> None:
    from pardal.packages.installer import (
        ResolveResult as InstallerResolveResult,
        ResolvedPackage as InstallerResolvedPackage,
        resolve_and_install_dependencies as installer_resolve_and_install_dependencies,
    )
    from pardal.packages.resolver import (
        ResolveResult,
        ResolvedPackage,
        resolve_and_install_dependencies,
    )
    from pardal.project.manifest import PathConfig
    from pardal.project.paths import PathConfig as PathsPathConfig

    assert PathsPathConfig is PathConfig
    assert InstallerResolveResult is ResolveResult
    assert InstallerResolvedPackage is ResolvedPackage
    assert installer_resolve_and_install_dependencies is resolve_and_install_dependencies


def test_profile_expansion_merges_imports_and_severity(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.yaml"
    profiles_path.write_text(
        """
schema: pardal.profile/v1
profiles:
  base:
    enable_checks:
      - analog.rc_filter_values_resolve
    requires_contract:
      adc_frontends: true
    severity:
      analog.rc_filter_values_resolve: warning
  strict:
    imports:
      - acme/support:base
    enable_checks:
      - gd32.adc_frontend
    severity:
      analog.rc_filter_values_resolve: error
""",
        encoding="utf-8",
    )

    profiles = load_profile_file(profiles_path, package_id="acme/support")
    expanded = expand_profiles(("acme/support:strict",), profiles)

    assert expanded.expanded == ("acme/support:base", "acme/support:strict")
    assert expanded.import_tree == {
        "acme/support:strict": ("acme/support:base",),
        "acme/support:base": (),
    }
    assert expanded.enabled_checks == frozenset(
        {"analog.rc_filter_values_resolve", "gd32.adc_frontend"}
    )
    assert expanded.requires_contract == {"adc_frontends": True}
    assert expanded.severity["analog.rc_filter_values_resolve"] == "error"


def test_profile_loader_rejects_invalid_severity_value(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.yaml"
    profiles_path.write_text(
        """
schema: pardal.profile/v1
profiles:
  strict:
    severity:
      analog.rc_filter_values_resolve: fatal
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="profile.severity_invalid") as exc_info:
        load_profile_file(profiles_path, package_id="acme/support")

    assert exc_info.value.diagnostic.path == profiles_path
    assert (
        exc_info.value.diagnostic.field
        == "profiles.strict.severity.analog.rc_filter_values_resolve"
    )


def test_profile_loader_rejects_malformed_yaml(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.yaml"
    profiles_path.write_text("schema: [\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="profile.yaml_invalid") as exc_info:
        load_profile_file(profiles_path, package_id="acme/support")

    assert exc_info.value.diagnostic.path == profiles_path
    assert exc_info.value.diagnostic.field == "yaml"


def test_profile_loader_rejects_empty_severity_and_contract_keys(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.yaml"
    profiles_path.write_text(
        """
schema: pardal.profile/v1
profiles:
  strict:
    severity:
      "":
        error
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="profile.mapping_invalid"):
        load_profile_file(profiles_path, package_id="acme/support")

    profiles_path.write_text(
        """
schema: pardal.profile/v1
profiles:
  strict:
    requires_contract:
      "": true
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="profile.mapping_invalid"):
        load_profile_file(profiles_path, package_id="acme/support")


def test_profile_repeated_imports_are_aliases_to_first_expansion(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.yaml"
    profiles_path.write_text(
        """
schema: pardal.profile/v1
profiles:
  shared:
    enable_checks:
      - analog.rc_filter_values_resolve
    severity:
      analog.rc_filter_values_resolve: warning
  left:
    imports:
      - acme/support:shared
    severity:
      analog.rc_filter_values_resolve: error
  right:
    imports:
      - acme/support:shared
    enable_checks:
      - gd32.adc_frontend
  top:
    imports:
      - acme/support:left
      - acme/support:right
""",
        encoding="utf-8",
    )

    profiles = load_profile_file(profiles_path, package_id="acme/support")
    expanded = expand_profiles(("acme/support:top",), profiles)

    assert expanded.expanded == (
        "acme/support:shared",
        "acme/support:left",
        "acme/support:right",
        "acme/support:top",
    )
    assert expanded.import_tree == {
        "acme/support:top": ("acme/support:left", "acme/support:right"),
        "acme/support:left": ("acme/support:shared",),
        "acme/support:shared": (),
        "acme/support:right": ("acme/support:shared",),
    }
    assert expanded.enabled_checks == frozenset(
        {"analog.rc_filter_values_resolve", "gd32.adc_frontend"}
    )
    assert expanded.severity["analog.rc_filter_values_resolve"] == "error"


def test_profile_imports_expand_in_lexical_order(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.yaml"
    profiles_path.write_text(
        """
schema: pardal.profile/v1
profiles:
  top:
    imports:
      - acme/support:z_last
      - acme/support:a_first
  z_last:
    enable_checks:
      - fixture.z
  a_first:
    enable_checks:
      - fixture.a
""",
        encoding="utf-8",
    )

    profiles = load_profile_file(profiles_path, package_id="acme/support")
    expanded = expand_profiles(("acme/support:top",), profiles)

    assert expanded.import_tree["acme/support:top"] == (
        "acme/support:a_first",
        "acme/support:z_last",
    )
    assert expanded.expanded == (
        "acme/support:a_first",
        "acme/support:z_last",
        "acme/support:top",
    )


def test_profile_import_cycle_fails(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.yaml"
    profiles_path.write_text(
        """
schema: pardal.profile/v1
profiles:
  a:
    imports: [acme/support:b]
  b:
    imports: [acme/support:a]
""",
        encoding="utf-8",
    )
    profiles = load_profile_file(profiles_path, package_id="acme/support")

    with pytest.raises(ProjectConfigError, match="profile.import_cycle"):
        expand_profiles(("acme/support:a",), profiles)


def test_package_content_hash_uses_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "file.txt").write_text("hello", encoding="utf-8")

    first = package_content_hash(tmp_path)
    second = package_content_hash(tmp_path)

    assert first.startswith("sha256:")
    assert first == second


def test_package_content_hash_normalizes_file_modes_to_regular_or_executable(
    tmp_path: Path,
) -> None:
    script = tmp_path / "tool.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o600)
    regular_hash = package_content_hash(tmp_path)

    script.chmod(0o644)
    same_regular_hash = package_content_hash(tmp_path)
    script.chmod(0o755)
    executable_hash = package_content_hash(tmp_path)

    assert same_regular_hash == regular_hash
    assert executable_hash != regular_hash


def test_public_check_decorator_registers_package_check() -> None:
    before = set(registered_checks())

    from pardal.checks import Finding, Severity as PublicSeverity, Stage as PublicStage, check

    check_id = "tests.foundation_unique_check"

    if check_id not in before:

        @check(
            id=check_id,
            stage=PublicStage.MANIFEST,
            default_severity=PublicSeverity.ERROR,
            requires_network=True,
        )
        def _foundation_check(ctx):
            return [
                Finding(
                    id=check_id,
                    severity=PublicSeverity.ERROR,
                    message="test finding",
                    stage=PublicStage.MANIFEST,
                )
            ]

    registered = registered_checks()
    assert registered[check_id].stage == Stage.MANIFEST
    assert registered[check_id].default_severity == Severity.ERROR
    assert registered[check_id].requires_network is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "id": "",
                "stage": Stage.MANIFEST,
                "default_severity": Severity.ERROR,
            },
            "check id",
        ),
        (
            {
                "id": "tests.invalid stage",
                "stage": Stage.MANIFEST,
                "default_severity": Severity.ERROR,
            },
            "check id",
        ),
        (
            {
                "id": "tests.invalid_stage",
                "stage": "manifest",
                "default_severity": Severity.ERROR,
            },
            "check stage",
        ),
        (
            {
                "id": "tests.invalid_severity",
                "stage": Stage.MANIFEST,
                "default_severity": "error",
            },
            "default_severity",
        ),
        (
            {
                "id": "tests.invalid_network_flag",
                "stage": Stage.MANIFEST,
                "default_severity": Severity.ERROR,
                "requires_network": "true",
            },
            "requires_network",
        ),
        (
            {
                "id": "tests.invalid_waiver_flag",
                "stage": Stage.MANIFEST,
                "default_severity": Severity.ERROR,
                "globally_waivable": "true",
            },
            "globally_waivable",
        ),
    ],
)
def test_public_check_decorator_rejects_malformed_metadata(kwargs, message) -> None:
    before = registered_checks()

    with pytest.raises(ValueError, match=message):
        check(**kwargs)

    assert registered_checks() == before


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"id": ""}, "finding id"),
        ({"id": "tests.invalid id"}, "finding id"),
        ({"severity": "warning"}, "finding severity"),
        ({"message": ""}, "finding message"),
        ({"stage": "manifest"}, "finding stage"),
        ({"evidence": []}, "finding evidence"),
        ({"source": []}, "finding source"),
    ],
)
def test_public_finding_rejects_malformed_shape(kwargs, message) -> None:
    payload = {
        "id": "tests.valid_finding_shape",
        "severity": Severity.WARNING,
        "message": "valid",
        "stage": Stage.MANIFEST,
        "evidence": {},
        "source": {},
    }
    payload.update(kwargs)

    with pytest.raises(ValueError, match=message):
        Finding(**payload)


def test_package_checks_run_in_stage_order_before_check_id_order() -> None:
    before = set(registered_checks())
    pre_route_id = "tests.z_pre_route_order"
    assembly_id = "tests.a_assembly_order"

    if pre_route_id not in before:

        @check(
            id=pre_route_id,
            stage=Stage.PRE_ROUTE,
            default_severity=Severity.WARNING,
        )
        def _pre_route_order_check(ctx):
            return [
                Finding(
                    id=pre_route_id,
                    severity=Severity.WARNING,
                    message="pre-route order",
                    stage=Stage.PRE_ROUTE,
                )
            ]

    if assembly_id not in before:

        @check(
            id=assembly_id,
            stage=Stage.ASSEMBLY,
            default_severity=Severity.WARNING,
        )
        def _assembly_order_check(ctx):
            return [
                Finding(
                    id=assembly_id,
                    severity=Severity.WARNING,
                    message="assembly order",
                    stage=Stage.ASSEMBLY,
                )
            ]

    findings = run_production_checks(
        CheckContext(spec=object()),
        enable_checks=[assembly_id, pre_route_id],
    )

    ordered_codes = [
        finding.code
        for finding in findings
        if finding.code in {assembly_id, pre_route_id}
    ]
    assert ordered_codes == [pre_route_id, assembly_id]


def test_package_check_findings_preserve_distinct_evidence() -> None:
    check_id = "tests.evidence_distinct_findings"
    if check_id not in registered_checks():

        @check(
            id=check_id,
            stage=Stage.SOURCE_CONTRACT,
            default_severity=Severity.WARNING,
        )
        def _evidence_distinct_findings(ctx):
            return [
                Finding(
                    id=check_id,
                    severity=Severity.WARNING,
                    message="same message",
                    stage=Stage.SOURCE_CONTRACT,
                    evidence={"ref": "R2"},
                    source={"path": "contract.yaml"},
                ),
                Finding(
                    id=check_id,
                    severity=Severity.WARNING,
                    message="same message",
                    stage=Stage.SOURCE_CONTRACT,
                    evidence={"ref": "R1"},
                    source={"path": "contract.yaml"},
                ),
            ]

    findings = [
        finding
        for finding in run_production_checks(CheckContext(spec=object()), enable_checks=[check_id])
        if finding.code == check_id
    ]

    assert [finding.evidence for finding in findings] == [{"ref": "R1"}, {"ref": "R2"}]


def test_package_check_returning_non_finding_emits_structured_error() -> None:
    check_id = "tests.invalid_return_shape"
    if check_id not in registered_checks():

        @check(
            id=check_id,
            stage=Stage.SOURCE_CONTRACT,
            default_severity=Severity.ERROR,
        )
        def _invalid_return_shape(ctx):
            return [{"not": "a Finding"}]

    findings = run_production_checks(
        CheckContext(spec=object()),
        enable_checks=[check_id],
    )
    invalid = next(
        finding
        for finding in findings
        if finding.code == "package.check_invalid_finding"
    )

    assert invalid.severity == "error"
    assert invalid.evidence == {
        "check_id": check_id,
        "index": 0,
        "type": "dict",
    }


def test_package_check_returning_none_emits_structured_error() -> None:
    check_id = "tests.invalid_none_return"
    if check_id not in registered_checks():

        @check(
            id=check_id,
            stage=Stage.SOURCE_CONTRACT,
            default_severity=Severity.ERROR,
        )
        def _invalid_none_return(ctx):
            return None

    findings = run_production_checks(
        CheckContext(spec=object()),
        enable_checks=[check_id],
    )
    invalid = next(
        finding
        for finding in findings
        if finding.code == "package.check_invalid_result"
    )

    assert invalid.stage == "source_contract"
    assert invalid.evidence == {"check_id": check_id, "type": "NoneType"}


def test_package_check_returning_scalar_emits_structured_error() -> None:
    check_id = "tests.invalid_scalar_return"
    if check_id not in registered_checks():

        @check(
            id=check_id,
            stage=Stage.SOURCE_CONTRACT,
            default_severity=Severity.ERROR,
        )
        def _invalid_scalar_return(ctx):
            return 123

    findings = run_production_checks(
        CheckContext(spec=object()),
        enable_checks=[check_id],
    )
    invalid = next(
        finding
        for finding in findings
        if finding.code == "package.check_invalid_result"
    )

    assert invalid.evidence == {"check_id": check_id, "type": "int"}


def test_package_check_exception_emits_structured_error() -> None:
    check_id = "tests.exception_return"
    if check_id not in registered_checks():

        @check(
            id=check_id,
            stage=Stage.SOURCE_CONTRACT,
            default_severity=Severity.ERROR,
        )
        def _exception_return(ctx):
            raise RuntimeError("boom")

    findings = run_production_checks(
        CheckContext(spec=object()),
        enable_checks=[check_id],
    )
    failed = next(
        finding
        for finding in findings
        if finding.code == "package.check_failed"
    )

    assert failed.stage == "source_contract"
    assert failed.evidence == {"check_id": check_id, "exception": "RuntimeError"}


def test_package_check_returning_wrong_finding_id_emits_structured_error() -> None:
    check_id = "tests.wrong_finding_id"
    if check_id not in registered_checks():

        @check(
            id=check_id,
            stage=Stage.SOURCE_CONTRACT,
            default_severity=Severity.ERROR,
        )
        def _wrong_finding_id(ctx):
            return [
                Finding(
                    id="tests.other_finding_id",
                    severity=Severity.ERROR,
                    message="wrong ID",
                    stage=Stage.SOURCE_CONTRACT,
                )
            ]

    findings = run_production_checks(
        CheckContext(spec=object()),
        enable_checks=[check_id],
    )
    wrong = next(
        finding
        for finding in findings
        if finding.code == "package.check_wrong_finding_id"
    )

    assert wrong.evidence == {
        "check_id": check_id,
        "finding_id": "tests.other_finding_id",
        "index": 0,
    }


def test_internal_check_module_surfaces_match_design() -> None:
    from pardal.checks.context import CheckContext as ContextModuleCheckContext
    from pardal.checks.findings import Finding, Severity as FindingSeverity, Stage as FindingStage
    from pardal.checks.registry import registered_checks as registry_registered_checks

    assert ContextModuleCheckContext is CheckContext
    assert FindingSeverity is Severity
    assert FindingStage is Stage
    assert Finding.__name__ == "Finding"
    assert registry_registered_checks is registered_checks


def test_package_check_duplicate_id_reports_stable_diagnostic(tmp_path: Path) -> None:
    check_id = "tests.fixture_duplicate_collision"
    if check_id not in registered_checks():

        @check(
            id=check_id,
            stage=Stage.MANIFEST,
            default_severity=Severity.WARNING,
        )
        def _duplicate_collision_anchor(ctx):
            return []

    package_root = tmp_path / "duplicate_pkg"
    package_root.mkdir()
    _write_helper_check_package(
        package_root,
        identifier="acme/duplicate-check",
        marker="duplicate_collision",
    )
    check_path = package_root / "checks" / "package_check.py"
    check_path.write_text(
        """
from pardal.checks import Severity, Stage, check

@check(id="tests.fixture_duplicate_collision", stage=Stage.MANIFEST, default_severity=Severity.WARNING)
def package_check(ctx):
    return []
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
    )
    sync_project(project)

    with pytest.raises(ProjectConfigError, match="package.check_duplicate") as exc_info:
        create_project_context(project)

    assert "tests.fixture_duplicate_collision" in str(exc_info.value)
    assert exc_info.value.diagnostic.path == (
        tmp_path / ".pardal/packages/acme/duplicate-check/checks/package_check.py"
    )


def test_package_check_rejects_malformed_public_check_metadata(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    check_path = package_root / "checks" / "gd32f310.py"
    check_path.write_text(
        """
from pardal.checks import Severity, Stage, check

@check(id="fixture invalid", stage=Stage.MANIFEST, default_severity=Severity.INFO)
def package_check(ctx):
    return []
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.check_import_failed") as exc_info:
        check_package(package_root / "pardal.yaml")

    assert "check id" in str(exc_info.value)
    assert exc_info.value.diagnostic.path == check_path


def test_project_context_selects_named_target(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/default.pardal.yaml
  alt:
    entry: boards/alt.pardal.yaml
""",
        encoding="utf-8",
    )

    ctx = create_project_context(manifest, target="alt")

    assert ctx.build_target.name == "alt"
    assert ctx.output_root == tmp_path / ".pardal/build" / "alt"


def test_manifest_rejects_non_boolean_allow_network_checks_option(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/default.pardal.yaml
    options:
      allow_network_checks: "true"
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="manifest.build_option_invalid"):
        load_project_manifest(manifest)


def test_manifest_rejects_non_boolean_require_lock_option(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/default.pardal.yaml
    options:
      require_lock: "true"
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="manifest.build_option_invalid"):
        load_project_manifest(manifest)


def test_manifest_rejects_unknown_build_output(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/default.pardal.yaml
    outputs:
      mystery_output: true
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="manifest.build_output_invalid") as exc_info:
        load_project_manifest(manifest)

    assert exc_info.value.diagnostic.field == "builds.default.outputs.mystery_output"


def test_manifest_rejects_non_boolean_build_output(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/default.pardal.yaml
    outputs:
      kicad_pcb: "true"
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="manifest.build_output_invalid") as exc_info:
        load_project_manifest(manifest)

    assert exc_info.value.diagnostic.field == "builds.default.outputs.kicad_pcb"


def test_manifest_rejects_production_output_without_require_lock(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/default.pardal.yaml
    outputs:
      production_checks: true
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="manifest.production_output_requires_lock",
    ) as exc_info:
        load_project_manifest(manifest)

    assert exc_info.value.diagnostic.field == "builds.default.outputs.production_checks"


def test_project_context_enforces_target_require_lock(tmp_path: Path) -> None:
    manifest = tmp_path / "pardal.yaml"
    manifest.write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
builds:
  default:
    entry: boards/default.pardal.yaml
    options:
      require_lock: true
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="project.lock_required"):
        create_project_context(manifest)


def test_sync_installs_file_dependency_and_writes_lock(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])

    result = sync_project(project)

    install_root = tmp_path / ".pardal" / "packages" / "acme" / "gd32f310-support"
    assert install_root.exists()
    assert not install_root.is_symlink()
    assert (install_root / "pardal.yaml").exists()
    installed_manifest_before = (install_root / "pardal.yaml").read_text(encoding="utf-8")
    (package_root / "pardal.yaml").write_text(
        (package_root / "pardal.yaml").read_text(encoding="utf-8")
        + "\n# source mutation after sync\n",
        encoding="utf-8",
    )
    assert (install_root / "pardal.yaml").read_text(encoding="utf-8") == installed_manifest_before
    assert (tmp_path / "pardal.lock").exists()
    assert "acme/gd32f310-support" in result.lock.packages
    lock_payload = yaml.safe_load((tmp_path / "pardal.lock").read_text(encoding="utf-8"))
    assert lock_payload["root"]["manifest"] == "pardal.yaml"
    assert lock_payload["root"]["project_hash"].startswith("sha256:")
    assert result.lock.manifest == "pardal.yaml"
    assert result.lock.project_hash == lock_payload["root"]["project_hash"]
    locked = result.lock.packages["acme/gd32f310-support"]
    assert locked.type == "file"
    assert locked.content_hash.startswith("sha256:")
    assert "profiles" in locked.export_hashes
    profile_exports = lock_payload["packages"]["acme/gd32f310-support"]["export_hashes"]["profiles"]
    assert profile_exports == sorted(
        profile_exports,
        key=lambda export: (export["id"], export["path"], export["hash"]),
    )


def test_sync_rejects_file_dependency_source_symlink(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "linked.py").symlink_to(package_root / "checks" / "gd32f310.py")
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])

    with pytest.raises(ProjectConfigError, match="dependency.package_source_unsafe") as exc_info:
        sync_project(project)

    assert exc_info.value.diagnostic.path == package_root / "linked.py"


def test_sync_rejects_file_dependency_source_hardlink(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    hardlink = package_root / "hardlinked.py"
    try:
        os.link(package_root / "checks" / "gd32f310.py", hardlink)
    except OSError as exc:
        pytest.skip(f"hardlinks are unavailable in this filesystem: {exc}")
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])

    with pytest.raises(ProjectConfigError, match="dependency.package_source_unsafe"):
        sync_project(project)


def test_lock_export_hashes_round_trip_ignores_malformed_entries(tmp_path: Path) -> None:
    lock_path = tmp_path / "pardal.lock"
    lock_path.write_text(
        yaml.safe_dump(
            {
                "schema": "pardal.lock/v1",
                "packages": {
                    "acme/pkg": {
                        "type": "file",
                        "source": ".pardal/packages/acme/pkg",
                        "manifest_hash": "sha256:manifest",
                        "content_hash": "sha256:content",
                        "export_hashes": {
                            "profiles": [
                                "not-a-mapping",
                                {
                                    "id": "acme/pkg:z",
                                    "path": "profiles/z.yaml",
                                    "hash": "sha256:z",
                                },
                                {
                                    "id": "acme/pkg:a",
                                    "path": "profiles/a.yaml",
                                    "hash": "sha256:a",
                                },
                            ]
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    lock = load_lock_file(lock_path)
    payload = lock_to_dict(lock)

    assert payload["packages"]["acme/pkg"]["export_hashes"]["profiles"] == [
        {"hash": "sha256:a", "id": "acme/pkg:a", "path": "profiles/a.yaml"},
        {"hash": "sha256:z", "id": "acme/pkg:z", "path": "profiles/z.yaml"},
    ]


def test_lock_file_rejects_malformed_package_metadata(tmp_path: Path) -> None:
    lock_path = tmp_path / "pardal.lock"
    lock_path.write_text(
        yaml.safe_dump(
            {
                "schema": "pardal.lock/v1",
                "root": {"project_hash": ["not", "a", "hash"]},
                "packages": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="root.project_hash must be a string"):
        load_lock_file(lock_path)

    lock_path.write_text(
        yaml.safe_dump(
            {
                "schema": "pardal.lock/v1",
                "packages": {
                    "acme/pkg": {
                        "type": "file",
                        "source": ".pardal/packages/acme/pkg",
                        "manifest_hash": "sha256:manifest",
                        "content_hash": 123,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="packages.acme/pkg.content_hash must be a string"):
        load_lock_file(lock_path)


def test_project_context_wraps_malformed_lock_file_diagnostic(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
    )
    lock_path = tmp_path / "pardal.lock"
    lock_path.write_text(
        yaml.safe_dump(
            {
                "schema": "pardal.lock/v1",
                "root": {"project_hash": ["not", "a", "hash"]},
                "packages": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="project.lock_invalid") as exc_info:
        create_project_context(project)

    assert exc_info.value.diagnostic.path == lock_path
    assert exc_info.value.diagnostic.field == "pardal.lock"
    assert "root.project_hash must be a string" in str(exc_info.value)


def test_lock_file_rejects_invalid_schema_and_package_type(tmp_path: Path) -> None:
    lock_path = tmp_path / "pardal.lock"
    lock_path.write_text(
        yaml.safe_dump({"schema": "pardal.lock/v0", "packages": {}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema must be pardal.lock/v1"):
        load_lock_file(lock_path)

    lock_path.write_text(
        yaml.safe_dump(
            {
                "schema": "pardal.lock/v1",
                "packages": {
                    "acme/pkg": {
                        "type": "unknown",
                        "source": ".pardal/packages/acme/pkg",
                        "manifest_hash": "sha256:manifest",
                        "content_hash": "sha256:content",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="packages.acme/pkg.type must be file, registry, or git"):
        load_lock_file(lock_path)


def test_project_lock_loader_wraps_malformed_yaml(tmp_path: Path) -> None:
    lock_path = tmp_path / "pardal.lock"
    lock_path.write_text("schema: [\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="project.lock_invalid") as exc_info:
        load_project_lock_file(lock_path)

    assert exc_info.value.diagnostic.path == lock_path
    assert exc_info.value.diagnostic.field == "pardal.lock"
    assert "lock file must be valid YAML" in str(exc_info.value)


def test_lock_file_rejects_missing_type_specific_source_fields(tmp_path: Path) -> None:
    lock_path = tmp_path / "pardal.lock"
    lock_path.write_text(
        yaml.safe_dump(
            {
                "schema": "pardal.lock/v1",
                "packages": {
                    "acme/pkg": {
                        "type": "registry",
                        "source": ".pardal/cache/registry/acme-pkg-0.1.0.tar.gz",
                        "manifest_hash": "sha256:manifest",
                        "content_hash": "sha256:content",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="packages.acme/pkg.release must be a non-empty string"):
        load_lock_file(lock_path)

    lock_path.write_text(
        yaml.safe_dump(
            {
                "schema": "pardal.lock/v1",
                "packages": {
                    "acme/pkg": {
                        "type": "git",
                        "source": ".pardal/packages/acme/pkg",
                        "repo": "https://github.com/acme/pkg.git",
                        "manifest_hash": "sha256:manifest",
                        "content_hash": "sha256:content",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="packages.acme/pkg.commit must be a non-empty string"):
        load_lock_file(lock_path)


def test_lock_file_rejects_malformed_dependency_list(tmp_path: Path) -> None:
    lock_path = tmp_path / "pardal.lock"
    lock_path.write_text(
        yaml.safe_dump(
            {
                "schema": "pardal.lock/v1",
                "packages": {
                    "acme/pkg": {
                        "type": "file",
                        "source": ".pardal/packages/acme/pkg",
                        "manifest_hash": "sha256:manifest",
                        "content_hash": "sha256:content",
                        "dependencies": ["acme/ok", 123],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"dependencies\[1\] must be a string"):
        load_lock_file(lock_path)


def test_sync_check_validates_without_mutating_files(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])
    sync_project(project)
    lock_path = tmp_path / "pardal.lock"
    installed_manifest = tmp_path / ".pardal/packages/acme/gd32f310-support/pardal.yaml"
    before_lock = lock_path.read_text(encoding="utf-8")
    before_installed = installed_manifest.read_text(encoding="utf-8")

    check_project_sync(project)

    assert lock_path.read_text(encoding="utf-8") == before_lock
    assert installed_manifest.read_text(encoding="utf-8") == before_installed


def test_sync_check_rejects_missing_lock(tmp_path: Path) -> None:
    project = _write_board_project(tmp_path, dependencies=[])

    with pytest.raises(ProjectConfigError, match="project.lock_required"):
        check_project_sync(project)


def test_sync_project_wraps_malformed_existing_lock(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])
    lock_path = tmp_path / "pardal.lock"
    _write_malformed_lock(lock_path)

    with pytest.raises(ProjectConfigError, match="project.lock_invalid") as exc_info:
        sync_project(project)

    assert exc_info.value.diagnostic.path == lock_path
    assert exc_info.value.diagnostic.field == "pardal.lock"


def test_sync_check_wraps_malformed_lock(tmp_path: Path) -> None:
    project = _write_board_project(tmp_path, dependencies=[])
    lock_path = tmp_path / "pardal.lock"
    _write_malformed_lock(lock_path)

    with pytest.raises(ProjectConfigError, match="project.lock_invalid") as exc_info:
        check_project_sync(project)

    assert exc_info.value.diagnostic.path == lock_path
    assert exc_info.value.diagnostic.field == "pardal.lock"


def test_list_dependencies_wraps_malformed_lock_status(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
    )
    lock_path = tmp_path / "pardal.lock"
    _write_malformed_lock(lock_path)

    with pytest.raises(ProjectConfigError, match="project.lock_invalid") as exc_info:
        list_dependencies(project, include_status=True)

    assert exc_info.value.diagnostic.path == lock_path
    assert exc_info.value.diagnostic.field == "pardal.lock"


def test_sync_check_rejects_manifest_lock_mismatch(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    extra_root = tmp_path / "extra_pkg"
    extra_root.mkdir()
    _write_minimal_package_fixture(
        extra_root,
        identifier="acme/extra-support",
        profile_name="extra_defaults",
    )
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])
    sync_project(project)
    raw = yaml.safe_load(project.read_text(encoding="utf-8"))
    raw["dependencies"].append({"type": "file", "path": extra_root.name})
    project.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="project.lock_out_of_sync"):
        check_project_sync(project)


def test_sync_installs_transitive_file_dependencies(tmp_path: Path) -> None:
    core_root = tmp_path / "analog_pkg"
    core_root.mkdir()
    _write_minimal_package_fixture(
        core_root,
        identifier="acme/analog-support",
        profile_name="analog_defaults",
    )
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    raw = (package_root / "pardal.yaml").read_text(encoding="utf-8")
    (package_root / "pardal.yaml").write_text(
        raw + "\ndependencies:\n  - type: file\n    path: ../analog_pkg\n",
        encoding="utf-8",
    )
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])

    result = sync_project(project)
    ctx = create_project_context(project)

    assert tuple(package.identifier for package in result.packages) == (
        "acme/analog-support",
        "acme/gd32f310-support",
    )
    assert set(result.lock.packages) == {
        "acme/analog-support",
        "acme/gd32f310-support",
    }
    assert result.lock.packages["acme/gd32f310-support"].dependencies == (
        "acme/analog-support",
    )
    resolution = package_resolution_for_context(ctx)
    assert resolution["flattened_package_set"] == (
        "acme/analog-support",
        "acme/gd32f310-support",
    )
    assert resolution["dependency_tree"] == (
        {
            "id": "acme/gd32f310-support",
            "dependencies": (
                {
                    "id": "acme/analog-support",
                    "dependencies": (),
                },
            ),
        },
    )
    assert (
        tmp_path / ".pardal/packages/acme/analog-support/pardal.yaml"
    ).exists()
    assert "acme/analog-support:analog_defaults" in ctx.package_index.profiles_by_id


def test_remove_dependency_prunes_only_unreferenced_transitives(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_pkg"
    shared_root.mkdir()
    _write_minimal_package_fixture(
        shared_root,
        identifier="acme/shared-support",
        profile_name="shared_defaults",
    )
    first_root = tmp_path / "first_pkg"
    first_root.mkdir()
    _write_minimal_package_fixture(
        first_root,
        identifier="acme/first-support",
        profile_name="first_defaults",
        dependencies=["../shared_pkg"],
    )
    second_root = tmp_path / "second_pkg"
    second_root.mkdir()
    _write_minimal_package_fixture(
        second_root,
        identifier="acme/second-support",
        profile_name="second_defaults",
        dependencies=["../shared_pkg"],
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{first_root.name}", f"file://{second_root.name}"],
    )
    sync_project(project)

    remove_dependency("acme/first-support", project)

    package_root = tmp_path / ".pardal/packages/acme"
    lock = load_lock_file(tmp_path / "pardal.lock")
    assert set(lock.packages) == {"acme/second-support", "acme/shared-support"}
    assert not (package_root / "first-support/pardal.yaml").exists()
    assert (package_root / "second-support/pardal.yaml").exists()
    assert (package_root / "shared-support/pardal.yaml").exists()

    remove_dependency("acme/second-support", project)

    lock = load_lock_file(tmp_path / "pardal.lock")
    assert lock.packages == {}
    assert not (package_root / "second-support/pardal.yaml").exists()
    assert not (package_root / "shared-support/pardal.yaml").exists()


def test_sync_rejects_conflicting_transitive_dependency(tmp_path: Path) -> None:
    shared_a = tmp_path / "shared_a"
    shared_b = tmp_path / "shared_b"
    parent_a = tmp_path / "parent_a"
    parent_b = tmp_path / "parent_b"
    for path in (shared_a, shared_b, parent_a, parent_b):
        path.mkdir()
    _write_minimal_package_fixture(
        shared_a,
        identifier="acme/shared-support",
        profile_name="shared_a",
    )
    _write_minimal_package_fixture(
        shared_b,
        identifier="acme/shared-support",
        profile_name="shared_b",
    )
    _write_minimal_package_fixture(
        parent_a,
        identifier="acme/parent-a",
        profile_name="parent_a",
        dependencies=["../shared_a"],
    )
    _write_minimal_package_fixture(
        parent_b,
        identifier="acme/parent-b",
        profile_name="parent_b",
        dependencies=["../shared_b"],
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["file://parent_a", "file://parent_b"],
    )

    with pytest.raises(ProjectConfigError, match="dependency.conflict") as exc_info:
        sync_project(project)

    message = str(exc_info.value)
    assert "introduced_by=" in message
    assert "requested_by=" in message
    assert (parent_a / "pardal.yaml").as_posix() in message
    assert (parent_b / "pardal.yaml").as_posix() in message


def test_sync_rejects_transitive_file_dependency_cycle(tmp_path: Path) -> None:
    package_a = tmp_path / "package_a"
    package_b = tmp_path / "package_b"
    package_a.mkdir()
    package_b.mkdir()
    _write_minimal_package_fixture(
        package_a,
        identifier="acme/package-a",
        profile_name="package_a",
        dependencies=["../package_b"],
    )
    _write_minimal_package_fixture(
        package_b,
        identifier="acme/package-b",
        profile_name="package_b",
        dependencies=["../package_a"],
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["file://package_a"],
    )

    with pytest.raises(ProjectConfigError, match="dependency.cycle"):
        sync_project(project)


def test_sync_rejects_profile_export_claiming_foreign_namespace(tmp_path: Path) -> None:
    package_a = tmp_path / "package_a"
    package_b = tmp_path / "package_b"
    package_a.mkdir()
    package_b.mkdir()
    _write_minimal_package_fixture(
        package_a,
        identifier="acme/package-a",
        profile_name="shared",
    )
    _write_minimal_package_fixture(
        package_b,
        identifier="acme/package-b",
        profile_name="placeholder",
    )
    (package_b / "profiles" / "default.yaml").write_text(
        """
schema: pardal.profile/v1
profiles:
  acme/package-a:shared:
    enable_checks: []
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["file://package_a", "file://package_b"],
    )

    with pytest.raises(ProjectConfigError, match="profile.id_invalid"):
        sync_project(project)


def test_update_lock_refreshes_declared_dependency(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])
    sync_project(project)
    (tmp_path / "pardal.lock").unlink()

    result = update_lock(project, package_id="acme/gd32f310-support")

    assert (tmp_path / "pardal.lock").exists()
    assert "acme/gd32f310-support" in result.lock.packages


def test_update_lock_accepts_locked_transitive_dependency(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    parent = tmp_path / "parent"
    shared.mkdir()
    parent.mkdir()
    _write_minimal_package_fixture(
        shared,
        identifier="acme/shared-support",
        profile_name="shared",
    )
    _write_minimal_package_fixture(
        parent,
        identifier="acme/parent-support",
        profile_name="parent",
        dependencies=["../shared"],
    )
    project = _write_board_project(tmp_path, dependencies=["file://parent"])
    sync_project(project)
    before = load_lock_file(tmp_path / "pardal.lock").packages["acme/shared-support"].content_hash
    (shared / "README.md").write_text("changed shared package\n", encoding="utf-8")

    result = update_lock(project, package_id="acme/shared-support")

    after = result.lock.packages["acme/shared-support"].content_hash
    assert after != before
    assert "acme/shared-support" in result.lock.packages["acme/parent-support"].dependencies


def test_update_lock_rejects_unknown_dependency(tmp_path: Path) -> None:
    project = _write_board_project(tmp_path, dependencies=[])

    with pytest.raises(ProjectConfigError, match="dependency.update_missing"):
        update_lock(project, package_id="acme/missing")


def test_project_context_indexes_installed_package_exports(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])
    sync_project(project)

    ctx = create_project_context(project)

    installed = ctx.package_index.packages_by_id["acme/gd32f310-support"]
    assert installed.root == tmp_path / ".pardal/packages/acme/gd32f310-support"
    assert installed.manifest.project.identifier == "acme/gd32f310-support"
    assert "acme/gd32f310-support:gd32f310_adc_12v" in ctx.package_index.profiles_by_id
    assert "acme/gd32f310-support:GD32F310K8T6" in ctx.package_index.parts_by_id
    assert "acme/gd32f310-support:gd32f310" in ctx.package_index.checks_by_id


def test_project_context_loads_physical_libraries_and_route_policies(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(tmp_path, profiles=[])
    sync_project(project)

    ctx = create_project_context(project)

    part = ctx.parts["acme/gd32f310-support:GD32F310K8T6"]
    footprint = ctx.footprints["acme/gd32f310-support:gd32f310_lqfp32"]
    library = ctx.physical_libraries["acme/gd32f310-support:gd32f310"]
    policy = ctx.route_policies["acme/gd32f310-support:gd32f310_12v_adc"]
    template = ctx.board_templates["acme/gd32f310-support:gd32f310_12v_adc"]
    assert part.manufacturer == "GigaDevice"
    assert part.lcsc == "C112130"
    assert part.pins == 32
    assert part.footprint == "acme/gd32f310-support:gd32f310_lqfp32"
    assert part.attributes["mcu.family"] == "GD32F310"
    assert footprint.kicad == "Package_QFP:LQFP-32_7x7mm_P0.8mm"
    assert footprint.kind == "kicad_mod"
    assert footprint.package_name == "LQFP-32"
    assert footprint.pitch == "0.8 mm"
    assert footprint.courtyard_required is True
    assert footprint.source_path == (
        tmp_path
        / ".pardal/packages/acme/gd32f310-support/footprints/GD32F310K8_LQFP32.kicad_mod"
    )
    assert footprint.aliases == ("LQFP-32", "GD32F310K8T6")
    assert library.footprints == ("acme/gd32f310-support:gd32f310_lqfp32",)
    assert library.netclasses == ("signal", "power")
    assert library.placements == ("templates/placements/gd32f310_12v_adc.yaml",)
    assert library.route_groups == ("templates/routes/adc_frontend.yaml",)
    assert library.mechanical == ("templates/mechanical/mounting_holes.yaml",)
    assert policy.backend == "pardal-routing-dsl"
    assert policy.layer_stack == "four_layer"
    assert policy.net_patterns == ("ADC*", "SENSE_*")
    assert policy.rules["ground_plane_required"] is True
    assert template.template_path == Path("templates/gd32f310_12v_adc")
    assert template.default_dependencies == ("acme/gd32f310-support", "jlcpcb/lcsc")


def test_project_context_package_physical_handoff_is_serializable(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(tmp_path, profiles=[])
    sync_project(project)

    ctx = create_project_context(project)
    payload = _build_package_physical_context(ctx)

    json.dumps(payload)
    assert payload["schema"] == "pardal.package_physical_context/v1"
    assert payload["physical_libraries"]["acme/gd32f310-support:gd32f310"] == {
        "package_id": "acme/gd32f310-support",
        "path": str(
            tmp_path
            / ".pardal/packages/acme/gd32f310-support/physical_libraries/gd32.yaml"
        ),
        "footprints": ["acme/gd32f310-support:gd32f310_lqfp32"],
        "netclasses": ["signal", "power"],
        "placements": ["templates/placements/gd32f310_12v_adc.yaml"],
        "route_groups": ["templates/routes/adc_frontend.yaml"],
        "mechanical": ["templates/mechanical/mounting_holes.yaml"],
        "metadata": {"purpose": "gd32f310_12v_adc"},
    }
    assert payload["route_policies"]["acme/gd32f310-support:gd32f310_12v_adc"] == {
        "package_id": "acme/gd32f310-support",
        "path": str(tmp_path / ".pardal/packages/acme/gd32f310-support/routing/gd32.yaml"),
        "backend": "pardal-routing-dsl",
        "layer_stack": "four_layer",
        "net_patterns": ["ADC*", "SENSE_*"],
        "rules": {
            "ground_plane_required": True,
            "power_width_mm": 0.2,
            "signal_width_mm": 0.15,
        },
    }
    assert ctx.examples["acme/gd32f310-support:starter"].example_path == Path(
        "templates/gd32f310_12v_adc"
    )

    resolution = package_resolution_for_context(ctx)
    assert resolution["parts"]["acme/gd32f310-support:GD32F310K8T6"]["pins"] == 32
    assert resolution["footprints"]["acme/gd32f310-support:gd32f310_lqfp32"][
        "source_path"
    ].endswith("footprints/GD32F310K8_LQFP32.kicad_mod")
    assert resolution["footprints"]["acme/gd32f310-support:gd32f310_lqfp32"][
        "courtyard_required"
    ] is True
    assert resolution["footprints"]["acme/gd32f310-support:gd32f310_lqfp32"][
        "package_name"
    ] == "LQFP-32"


def test_canonical_gd32_adc_board_fixture_resolves_through_packages(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture_root = repo_root / "examples/boards/gd32_12v_adc_project"
    package_root = repo_root / "examples/packages"
    project_root = tmp_path / "gd32_12v_adc_project"
    packages_copy = tmp_path / "packages"
    shutil.copytree(fixture_root, project_root)
    shutil.copytree(package_root, packages_copy)
    project = project_root / "pardal.yaml"

    sync_project(project)
    ctx = create_project_context(project)

    assert ctx.manifest.project.name == "gd32f310-12v-adc"
    assert ctx.build_target.entry == Path("boards/gd32f310_12v_adc.pardal.yaml")
    assert "acme/gd32f310-support:gd32f310_adc_12v" in ctx.profile_set.expanded
    assert "jlcpcb/lcsc:jlcpcb_smt" in ctx.profile_set.expanded
    assert ctx.source_contract.components["U1"]["part_id"] == (
        "acme/gd32f310-support:GD32F310K8T6"
    )
    assert ctx.source_contract.components["U1"]["part_alias"] == "MCU"
    assert "acme/gd32f310-support:GD32F310K8T6" in ctx.parts
    assert "acme/gd32f310-support:gd32f310_lqfp32" in ctx.footprints
    assert "acme/gd32f310-support:gd32f310_12v_adc" in ctx.route_policies
    assert ctx.lock is not None
    assert set(ctx.lock.packages) == {
        "acme/gd32f310-support",
        "jlcpcb/lcsc",
        "pardal/core",
    }


def test_production_profile_requires_package_footprint_id(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    footprint_id: acme/gd32f310-support:missing_lqfp32
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["pardal/core:production_real_footprints"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )

    assert [
        finding.code
        for finding in findings
        if finding.code == "footprint.package_reference_missing"
    ] == ["footprint.package_reference_missing"]


def test_production_profile_accepts_package_footprint_id(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    footprint_id: acme/gd32f310-support:gd32f310_lqfp32
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["pardal/core:production_real_footprints"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )

    assert [
        finding
        for finding in findings
        if finding.code == "footprint.package_reference_missing"
    ] == []


def test_production_profile_rejects_part_footprint_mismatch(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    part_id: acme/gd32f310-support:GD32F310K8T6
    footprint_id: acme/gd32f310-support:test_socket_lqfp32
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["pardal/core:production_real_footprints"],
        source_contract="contracts/board.contract.yaml",
    )
    (tmp_path / "deps" / "gd32f310-support" / "footprints" / "gd32.yaml").write_text(
        """
schema: pardal.footprints/v1
footprints:
  gd32f310_lqfp32:
    kicad: Package_QFP:LQFP-32_7x7mm_P0.8mm
  test_socket_lqfp32:
    kicad: Package_QFP:LQFP-32_9x9mm_P0.8mm
""",
        encoding="utf-8",
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )

    assert [
        finding.code
        for finding in findings
        if finding.code == "footprint.package_mismatch"
    ] == ["footprint.package_mismatch"]
    assert [
        finding
        for finding in findings
        if finding.code == "footprint.package_reference_missing"
    ] == []


def test_prototype_profile_allows_raw_synthetic_footprint(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    footprint: Package_QFP:LQFP-32_7x7mm_P0.8mm
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["pardal/core:prototype"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )

    assert [
        finding
        for finding in findings
        if finding.code == "footprint.package_reference_missing"
    ] == []


def test_lcsc_profile_accepts_package_part_metadata(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    part_id: acme/gd32f310-support:GD32F310K8T6
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["jlcpcb/lcsc:require_or_exception"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )

    assert [
        finding
        for finding in findings
        if finding.code == "lcsc.parts_require_mapping_or_exception"
    ] == []


def test_package_resolution_records_selected_component_metadata(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    part_id: acme/gd32f310-support:GD32F310K8T6
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    ctx = create_project_context(project)
    lock = load_lock_file(tmp_path / "pardal.lock")

    resolution = package_resolution_for_context(ctx)

    assert resolution["parts"]["acme/gd32f310-support:GD32F310K8T6"][
        "footprint"
    ] == "acme/gd32f310-support:gd32f310_lqfp32"
    assert resolution["selected_components"]["U1"] == {
        "part_id": "acme/gd32f310-support:GD32F310K8T6",
        "part_package": "acme/gd32f310-support",
        "manufacturer": "GigaDevice",
        "mpn": "GD32F310K8T6",
        "lcsc": "C112130",
        "footprint_id": "acme/gd32f310-support:gd32f310_lqfp32",
        "footprint_package": "acme/gd32f310-support",
        "kicad_footprint": "Package_QFP:LQFP-32_7x7mm_P0.8mm",
    }


def test_source_contract_part_alias_resolves_selected_component_metadata(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
part_aliases:
  MCU: acme/gd32f310-support:GD32F310K8T6
components:
  U1:
    part_id: MCU
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["jlcpcb/lcsc:require_or_exception"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )
    payload = package_resolution_for_context(project_context)

    assert [
        finding
        for finding in findings
        if finding.code == "lcsc.parts_require_mapping_or_exception"
    ] == []
    assert project_context.source_contract.components["U1"]["part_id"] == (
        "acme/gd32f310-support:GD32F310K8T6"
    )
    assert project_context.source_contract.components["U1"]["part_alias"] == "MCU"
    assert payload["part_aliases"] == {
        "MCU": "acme/gd32f310-support:GD32F310K8T6"
    }
    assert payload["selected_components"]["U1"]["part_id"] == (
        "acme/gd32f310-support:GD32F310K8T6"
    )
    assert payload["selected_components"]["U1"]["lcsc"] == "C112130"


def test_source_contract_part_aliases_reject_non_string_keys(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
part_aliases:
  123: acme/gd32f310-support:GD32F310K8T6
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    with pytest.raises(ValueError, match="part_aliases keys"):
        create_project_context(project)


def test_source_contract_part_aliases_reject_non_string_targets(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
part_aliases:
  MCU: 123
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    with pytest.raises(ValueError, match="part_aliases.MCU"):
        create_project_context(project)


def test_source_contract_profiles_reject_non_string_values(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
profiles:
  manufacturer: 123
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    with pytest.raises(ValueError, match="profiles.manufacturer"):
        create_project_context(project)


def test_source_contract_components_reject_non_string_keys(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  1:
    part_id: acme/gd32f310-support:GD32F310K8T6
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    with pytest.raises(ValueError, match="components keys"):
        create_project_context(project)


def test_source_contract_components_reject_non_string_part_ids(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    part_id: 123
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    with pytest.raises(ValueError, match="components.U1.part_id"):
        create_project_context(project)


def test_source_contract_components_reject_non_string_footprint_ids(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    footprint_id: 123
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    with pytest.raises(ValueError, match="components.U1.footprint_id"):
        create_project_context(project)


def test_unqualified_unique_part_id_resolves_without_alias(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    part_id: GD32F310K8T6
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    project_context = create_project_context(project)

    assert project_context.source_contract.components["U1"]["part_id"] == (
        "acme/gd32f310-support:GD32F310K8T6"
    )


def test_conflicting_unqualified_part_id_requires_local_alias(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    part_id: GD32F310K8T6
""",
        encoding="utf-8",
    )
    duplicate = tmp_path / "duplicate-mcu"
    _write_part_only_package_fixture(
        duplicate,
        identifier="acme/alternate-mcu",
        part_name="GD32F310K8T6",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    manifest = project.read_text(encoding="utf-8")
    project.write_text(
        manifest.replace(
            "builds:\n",
            "  - file://duplicate-mcu\nbuilds:\n",
        ),
        encoding="utf-8",
    )
    sync_project(project)

    with pytest.raises(ProjectConfigError, match="source_contract.part_alias_required"):
        create_project_context(project)


def test_lcsc_profile_rejects_source_component_without_package_lcsc(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
components:
  U1:
    part_id: acme/gd32f310-support:missing
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["jlcpcb/lcsc:require_or_exception"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )

    assert [
        finding.code
        for finding in findings
        if finding.code == "lcsc.parts_require_mapping_or_exception"
    ] == ["lcsc.parts_require_mapping_or_exception"]


def test_project_context_expands_installed_package_profile(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )
    sync_project(project)

    ctx = create_project_context(project)

    assert ctx.profile_set.requested == ("acme/gd32f310-support:gd32f310_adc_12v",)
    assert ctx.profile_set.expanded == ("acme/gd32f310-support:gd32f310_adc_12v",)
    assert ctx.profile_set.enabled_checks == frozenset({"gd32.adc_frontend"})


def test_unqualified_core_profile_resolves_to_pardal_core(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["general_fab_ready"],
    )
    sync_project(project)

    ctx = create_project_context(project)

    assert ctx.profile_set.requested == ("pardal/core:general_fab_ready",)
    assert ctx.profile_set.expanded == ("pardal/core:general_fab_ready",)
    assert ctx.profile_set.enabled_checks == frozenset(
        {
            "release.gerbers_missing",
            "release.drill_missing",
            "release.archive_not_uploadable",
        }
    )


def test_unqualified_non_core_profile_fails(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["jlcpcb_smt"],
    )
    sync_project(project)

    with pytest.raises(ProjectConfigError, match="profile.unqualified_non_core"):
        create_project_context(project)


def test_project_context_expands_source_contract_profiles_after_build_profiles(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
profiles:
  manufacturer: jlcpcb/lcsc:jlcpcb_smt
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["general_fab_ready"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    ctx = create_project_context(project)

    assert ctx.source_contract.profiles == {"manufacturer": "jlcpcb/lcsc:jlcpcb_smt"}
    assert ctx.profile_set.requested == (
        "pardal/core:general_fab_ready",
        "jlcpcb/lcsc:jlcpcb_smt",
    )
    assert ctx.profile_set.expanded == (
        "pardal/core:general_fab_ready",
        "jlcpcb/lcsc:jlcpcb_smt",
    )
    assert ctx.profile_set.enabled_checks == frozenset(
        {
            "release.gerbers_missing",
            "release.drill_missing",
            "release.archive_not_uploadable",
            "jlcpcb.smt_required_artifacts",
            "assembly.manual_part_present",
            "assembly.manual_part_exported_to_jlc",
        }
    )


def test_legacy_profile_aliases_match_package_profile_sources() -> None:
    root = Path(__file__).resolve().parents[1]
    available = {}
    for package_id, profile_path in (
        ("pardal/core", root / "examples/packages/pardal-core/profiles/core.yaml"),
        ("jlcpcb/lcsc", root / "examples/packages/jlcpcb-lcsc/profiles/jlcpcb.yaml"),
        ("acme/gd32f310-support", root / "examples/packages/gd32f310-support/profiles/gd32.yaml"),
    ):
        available.update(load_profile_file(profile_path, package_id=package_id))

    legacy_aliases = {
        "jlcpcb_4_layer_smt": "jlcpcb/lcsc:jlcpcb_4_layer_smt",
        "jlcpcb_smt": "jlcpcb/lcsc:jlcpcb_smt",
        "jlcpcb_full_pcba": "jlcpcb/lcsc:jlcpcb_full_pcba",
        "require_or_exception": "jlcpcb/lcsc:require_or_exception",
        "gd32f310_adc_12v": "acme/gd32f310-support:gd32f310_adc_12v",
        "gd32_12v_input": "acme/gd32f310-support:gd32_12v_input",
        "gd32_adc_frontend": "acme/gd32f310-support:gd32_adc_frontend",
    }

    assert set(legacy_aliases) == set(PROFILE_CHECKS)
    for legacy_name, package_profile in legacy_aliases.items():
        expanded = expand_profiles((package_profile,), available)
        assert expanded.enabled_checks == frozenset(PROFILE_CHECKS[legacy_name])


def test_profile_resolution_keeps_source_contract_package_profiles_out_of_legacy(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
profiles:
  manufacturer: jlcpcb/lcsc:jlcpcb_smt
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["general_fab_ready"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    ctx = create_project_context(project)

    resolution = profile_resolution_for_context(
        CheckContext(spec=object(), project_context=ctx)
    )

    assert resolution["legacy_profiles"] == ()
    assert resolution["package_profiles"]["requested"] == (
        "pardal/core:general_fab_ready",
        "jlcpcb/lcsc:jlcpcb_smt",
    )
    assert "jlcpcb/lcsc:jlcpcb_smt" in resolution["package_profiles"]["expanded"]


def test_project_backed_profile_resolution_bypasses_static_legacy_adapter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["jlcpcb/lcsc:jlcpcb_smt"],
    )
    sync_project(project)
    ctx = create_project_context(project)

    def fail_static_adapter(_profiles):
        raise AssertionError("static PROFILE_CHECKS adapter should not be used")

    monkeypatch.setattr(
        profile_resolution_module,
        "checks_for_profiles",
        fail_static_adapter,
    )

    resolution = profile_resolution_for_context(
        CheckContext(spec=object(), project_context=ctx)
    )

    assert resolution["legacy_profiles"] == ()
    assert "jlcpcb.smt_required_artifacts" in resolution["enabled_checks"]


def test_package_profile_enables_production_check(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    _replace_package_profiles(
        package_root,
        """
schema: pardal.profile/v1
profiles:
  gd32f310_adc_12v:
    enable_checks:
      - fixture.package_file_check
    severity:
      fixture.package_file_check: error
""",
    )
    (package_root / "check_helpers.py").write_text(
        """
def package_check_message():
    return "enabled by package check module"
""",
        encoding="utf-8",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from check_helpers import package_check_message
from pardal.checks import Finding, Severity, Stage, check

@check(id="fixture.package_file_check", stage=Stage.SOURCE_CONTRACT, default_severity=Severity.WARNING)
def package_check(ctx):
    return [
        Finding(
            id="fixture.package_file_check",
            severity=Severity.WARNING,
            message=package_check_message(),
            stage=Stage.SOURCE_CONTRACT,
            source={"path": "checks/gd32f310.py", "field": "package_check"},
        )
    ]
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(
            spec=object(),
            project_context=project_context,
        )
    )

    fixture_findings = [
        finding for finding in findings if finding.code == "fixture.package_file_check"
    ]
    assert fixture_findings == [
        CheckFinding(
            "error",
            "fixture.package_file_check",
            "enabled by package check module",
            "checks/gd32f310.py:package_check",
            stage="source_contract",
            package="acme/gd32f310-support",
            source_details={"path": "checks/gd32f310.py", "field": "package_check"},
        )
    ]


def test_project_context_rejects_profile_unknown_check_id(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    _replace_package_profiles(
        package_root,
        """
schema: pardal.profile/v1
profiles:
  gd32f310_adc_12v:
    enable_checks:
      - fixture.missing_profile_check
""",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )
    sync_project(project)

    with pytest.raises(ProjectConfigError, match="profile.check_unknown"):
        create_project_context(project)


def test_package_check_receives_immutable_context(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    _replace_package_profiles(
        package_root,
        """
schema: pardal.profile/v1
profiles:
  gd32f310_adc_12v:
    enable_checks:
      - fixture.immutable_context
""",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pardal.checks import Finding, Severity, Stage, check

@check(id="fixture.immutable_context", stage=Stage.SOURCE_CONTRACT, default_severity=Severity.WARNING)
def package_check(ctx):
    mutations = [
        lambda: ctx.source_contract.rails.__setitem__("3V3", {"voltage": "5 V"}),
        lambda: ctx.artifact_paths.__setitem__("new", "artifact"),
        lambda: ctx.build_summary.__setitem__("mutated", True),
        lambda: ctx.project_context.parts.__setitem__("new:part", object()),
    ]
    blocked = 0
    for mutate in mutations:
        try:
            mutate()
        except (AttributeError, TypeError):
            blocked += 1
    if blocked == len(mutations):
        return [
            Finding(
                id="fixture.immutable_context",
                severity=Severity.INFO,
                message="context is immutable",
                stage=Stage.SOURCE_CONTRACT,
            )
        ]
    return [
        Finding(
            id="fixture.immutable_context",
            severity=Severity.ERROR,
            message="context mutation succeeded",
            stage=Stage.SOURCE_CONTRACT,
        )
    ]
""",
        encoding="utf-8",
    )
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
supply_rails:
  3V3:
    voltage: 3.3 V
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(
            spec=object(),
            project_context=project_context,
            artifact_paths={"bom": tmp_path / "bom.csv"},
            build_summary={"profiles": ["acme/gd32f310-support:gd32f310_adc_12v"]},
        )
    )

    assert [
        finding
        for finding in findings
        if finding.code == "fixture.immutable_context"
    ] == [
        CheckFinding(
            "info",
            "fixture.immutable_context",
            "context is immutable",
            "",
            stage="source_contract",
            package="acme/gd32f310-support",
        )
    ]


def test_package_check_findings_carry_stage_package_evidence_and_source(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    _replace_package_profiles(
        package_root,
        """
schema: pardal.profile/v1
profiles:
  gd32f310_adc_12v:
    enable_checks:
      - fixture.metadata_check
""",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pardal.checks import Finding, Severity, Stage, check

@check(id="fixture.metadata_check", stage=Stage.SOURCE_CONTRACT, default_severity=Severity.ERROR)
def package_check(ctx):
    return [
        Finding(
            id="fixture.metadata_check",
            severity=Severity.ERROR,
            message="metadata finding",
            stage=Stage.SOURCE_CONTRACT,
            evidence={"channel": "ADC0"},
            source={"path": "contracts/board.contract.yaml", "field": "adc_frontends.ADC0"},
        )
    ]
""",
        encoding="utf-8",
    )
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
adc_frontends:
  ADC0:
    source_impedance: 10k
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )

    finding = next(item for item in findings if item.code == "fixture.metadata_check")
    assert finding.stage == "source_contract"
    assert finding.package == "acme/gd32f310-support"
    assert finding.evidence == {"channel": "ADC0"}
    assert finding.source == "contracts/board.contract.yaml:adc_frontends.ADC0"
    assert finding.source_details == {
        "path": "contracts/board.contract.yaml",
        "field": "adc_frontends.ADC0",
    }


def test_design_style_waiver_matches_package_finding_stage_and_evidence(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    _replace_package_profiles(
        package_root,
        """
schema: pardal.profile/v1
profiles:
  gd32f310_adc_12v:
    enable_checks:
      - fixture.waived_metadata_check
""",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pardal.checks import Finding, Severity, Stage, check

@check(id="fixture.waived_metadata_check", stage=Stage.SOURCE_CONTRACT, default_severity=Severity.ERROR)
def package_check(ctx):
    return [
        Finding(
            id="fixture.waived_metadata_check",
            severity=Severity.ERROR,
            message="metadata finding",
            stage=Stage.SOURCE_CONTRACT,
            evidence={"channel": "ADC0"},
        )
    ]
""",
        encoding="utf-8",
    )
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
waivers:
  - id: fixture.waived_metadata_check
    stage: source_contract
    match:
      channel: ADC0
    reason: ADC0 frontend is covered by external validation
    owner: hardware
    expires: 2026-12-31
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    project_context = create_project_context(project)
    waiver = project_context.source_contract.waivers[0]
    assert waiver.id == "fixture.waived_metadata_check"
    assert waiver.stage == "source_contract"
    assert waiver.match == {"channel": "ADC0"}
    assert waiver.reason == "ADC0 frontend is covered by external validation"
    assert waiver.owner == "hardware"
    assert waiver.expires == "2026-12-31"

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )

    finding = next(item for item in findings if item.code == "fixture.waived_metadata_check.waived")
    assert finding.waived is True
    assert finding.waiver_reason == "ADC0 frontend is covered by external validation"
    assert "waiver.unused" not in {item.code for item in findings}


def test_project_context_rejects_unknown_waiver_check_id(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
waive_checks:
  fixture.missing_check:
    reason: typo should fail
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    with pytest.raises(ProjectConfigError, match="source_contract.waiver_unknown"):
        create_project_context(project)


def test_project_context_wraps_invalid_source_contract_diagnostic(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    contract_path = contracts / "board.contract.yaml"
    contract_path.write_text(
        """
schema: pardal.source_contract/v1
waive_checks:
  assembly.manual_part_present:
    refs:
      - J12V
""",
        encoding="utf-8",
    )
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    with pytest.raises(ProjectConfigError, match="source_contract.invalid") as exc_info:
        create_project_context(project)

    assert exc_info.value.diagnostic.path == contract_path
    assert "waive_checks.assembly.manual_part_present.reason" in str(exc_info.value)


def test_project_context_accepts_package_check_waiver_id(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    _replace_package_profiles(
        package_root,
        """
schema: pardal.profile/v1
profiles:
  gd32f310_adc_12v:
    enable_checks:
      - fixture.package_waived_check
""",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pardal.checks import Finding, Severity, Stage, check

@check(id="fixture.package_waived_check", stage=Stage.SOURCE_CONTRACT, default_severity=Severity.WARNING)
def package_check(ctx):
    return [
        Finding(
            id="fixture.package_waived_check",
            severity=Severity.WARNING,
            message="enabled by package check module",
            stage=Stage.SOURCE_CONTRACT,
        )
    ]
""",
        encoding="utf-8",
    )
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
waive_checks:
  fixture.package_waived_check:
    reason: expected package finding
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)

    ctx = create_project_context(project)

    assert "fixture.package_waived_check" in ctx.source_contract.waive_checks


def test_package_check_global_waiver_requires_decorator_opt_in(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    _replace_package_profiles(
        package_root,
        """
schema: pardal.profile/v1
profiles:
  gd32f310_adc_12v:
    enable_checks:
      - fixture.package_global_waiver_check
""",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pardal.checks import Finding, Severity, Stage, check

@check(
    id="fixture.package_global_waiver_check",
    stage=Stage.SOURCE_CONTRACT,
    default_severity=Severity.ERROR,
    globally_waivable=True,
)
def package_check(ctx):
    return [
        Finding(
            id="fixture.package_global_waiver_check",
            severity=Severity.ERROR,
            message="global waiver opt-in finding",
            stage=Stage.SOURCE_CONTRACT,
        )
    ]
""",
        encoding="utf-8",
    )
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "board.contract.yaml").write_text(
        """
schema: pardal.source_contract/v1
waive_checks:
  fixture.package_global_waiver_check:
    reason: package check declared this globally waivable
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
        source_contract="contracts/board.contract.yaml",
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )

    finding = next(
        item for item in findings if item.code == "fixture.package_global_waiver_check.waived"
    )
    assert finding.waived is True
    assert "waiver.unused" not in {item.code for item in findings}


def test_network_package_check_requires_explicit_permission(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    _replace_package_profiles(
        package_root,
        """
schema: pardal.profile/v1
profiles:
  gd32f310_adc_12v:
    enable_checks:
      - fixture.network_check
""",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pardal.checks import Finding, Severity, Stage, check

@check(id="fixture.network_check", stage=Stage.SOURCE_CONTRACT, default_severity=Severity.WARNING, requires_network=True)
def package_check(ctx):
    return [
        Finding(
            id="fixture.network_check",
            severity=Severity.WARNING,
            message="network check ran",
            stage=Stage.SOURCE_CONTRACT,
        )
    ]
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )
    sync_project(project)
    project_context = create_project_context(project)

    blocked = run_production_checks(CheckContext(spec=object(), project_context=project_context))
    allowed = run_production_checks(
        CheckContext(
            spec=object(),
            project_context=project_context,
            allow_network_checks=True,
        )
    )
    resolution = package_resolution_for_context(project_context)

    assert [
        finding.code for finding in blocked if finding.code == "production_check.network_disabled"
    ] == ["production_check.network_disabled"]
    assert [
        finding.code for finding in allowed if finding.code == "fixture.network_check"
    ] == ["fixture.network_check"]
    assert resolution["checks"]["registered"]["fixture.network_check"]["requires_network"] is True

    blocked_resolution = profile_resolution_for_context(
        CheckContext(spec=object(), project_context=project_context)
    )
    allowed_resolution = profile_resolution_for_context(
        CheckContext(
            spec=object(),
            project_context=project_context,
            allow_network_checks=True,
        )
    )

    assert blocked_resolution["network"]["allow_network_checks"] is False
    assert "fixture.network_check" in blocked_resolution["network"]["network_capable_checks"]
    assert blocked_resolution["network"]["enabled_network_checks"] == ("fixture.network_check",)
    assert blocked_resolution["network"]["disabled_network_checks"] == ()
    assert blocked_resolution["network"]["skipped_network_checks"] == ("fixture.network_check",)
    assert allowed_resolution["network"]["allow_network_checks"] is True
    assert "fixture.network_check" in allowed_resolution["network"]["network_capable_checks"]
    assert allowed_resolution["network"]["enabled_network_checks"] == ("fixture.network_check",)
    assert allowed_resolution["network"]["disabled_network_checks"] == ()
    assert allowed_resolution["network"]["skipped_network_checks"] == ()


def test_package_profile_severity_overrides_emitted_findings(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    _replace_package_profiles(
        package_root,
        """
schema: pardal.profile/v1
profiles:
  gd32f310_adc_12v:
    enable_checks:
      - fixture.severity_override
    severity:
      fixture.severity_override: error
""",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pardal.checks import Finding, Severity, Stage, check

@check(id="fixture.severity_override", stage=Stage.SOURCE_CONTRACT, default_severity=Severity.WARNING)
def package_check(ctx):
    return [
        Finding(
            id="fixture.severity_override",
            severity=Severity.WARNING,
            message="profile should escalate this",
            stage=Stage.SOURCE_CONTRACT,
        )
    ]
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )
    sync_project(project)
    project_context = create_project_context(project)

    findings = run_production_checks(
        CheckContext(spec=object(), project_context=project_context)
    )

    assert [
        (finding.severity, finding.code)
        for finding in findings
        if finding.code == "fixture.severity_override"
    ] == [("error", "fixture.severity_override")]


def test_profile_resolution_reports_package_profile_provenance(tmp_path: Path) -> None:
    contract_path = _write_minimal_required_contract(tmp_path)
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
        source_contract=contract_path,
    )
    sync_project(project)
    project_context = create_project_context(project)

    resolution = profile_resolution_for_context(
        CheckContext(spec=object(), project_context=project_context),
        cli_disable_checks=["fixture.warning"],
        cli_disable_check_reasons={
            "fixture.warning": "fixture warning is covered by a signed board waiver"
        },
    )

    assert resolution["schema"] == "pardal.profile_resolution/v1"
    assert resolution["package_profiles"]["requested"] == (
        "acme/gd32f310-support:gd32f310_adc_12v",
    )
    assert resolution["package_profiles"]["imported_profiles"] == (
        "acme/gd32f310-support:gd32_12v_input",
        "pardal/core:analog_rc_filters",
        "acme/gd32f310-support:gd32_adc_frontend",
    )
    assert resolution["package_profiles"]["import_tree"] == {
        "acme/gd32f310-support:gd32f310_adc_12v": (
            "acme/gd32f310-support:gd32_12v_input",
            "acme/gd32f310-support:gd32_adc_frontend",
        ),
        "acme/gd32f310-support:gd32_12v_input": (),
        "acme/gd32f310-support:gd32_adc_frontend": (
            "pardal/core:analog_rc_filters",
        ),
        "pardal/core:analog_rc_filters": (),
    }
    assert set(resolution["package_profiles"]["enabled_checks"]) >= {
        "gd32.adc_frontend",
        "analog.rc_filter_values_resolve",
    }
    assert "gd32.adc_frontend" in resolution["enabled_checks"]
    assert resolution["cli"]["disable_check_reasons"] == {
        "fixture.warning": "fixture warning is covered by a signed board waiver"
    }


def test_profile_resolution_expands_cli_package_profiles(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(tmp_path, profiles=[])
    sync_project(project)
    project_context = create_project_context(project)

    resolution = profile_resolution_for_context(
        CheckContext(spec=object(), project_context=project_context),
        cli_profiles=["acme/gd32f310-support:gd32_adc_frontend"],
    )

    assert resolution["legacy_profiles"] == ()
    assert resolution["cli"]["profiles"] == (
        "acme/gd32f310-support:gd32_adc_frontend",
    )
    assert resolution["package_profiles"]["requested"] == (
        "acme/gd32f310-support:gd32_adc_frontend",
    )
    assert resolution["package_profiles"]["imported_profiles"] == (
        "pardal/core:analog_rc_filters",
    )
    assert "gd32.adc_frontend" in resolution["enabled_checks"]
    assert "analog.rc_filter_values_resolve" in resolution["enabled_checks"]


def test_jlc_full_pcba_package_profile_escalates_manual_part_severity(
    tmp_path: Path,
) -> None:
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["jlcpcb/lcsc:jlcpcb_full_pcba"],
    )
    sync_project(project)
    project_context = create_project_context(project)
    component = SimpleNamespace(
        footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS",
        value="12V_IN",
    )
    spec = SimpleNamespace(
        path=tmp_path / "board.pdl.yaml",
        dfm=None,
        layer_roles={},
        planes=[],
        routes=[],
        validation_tests=[],
        parts={},
        netclass_assignments={},
        rules=SimpleNamespace(default_clearance=0.10, netclasses={}),
    )
    board = SimpleNamespace(components={"J12V": component})

    findings = run_production_checks(
        CheckContext(spec=spec, board=board, project_context=project_context),
        disable_checks=["jlcpcb.smt_required_artifacts"],
    )

    assert [
        (finding.severity, finding.code)
        for finding in findings
        if finding.code == "assembly.manual_part_present"
    ] == [("error", "assembly.manual_part_present")]


def test_canonical_package_profiles_cover_legacy_static_profile_map(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(tmp_path, profiles=[])
    contract_path = _write_minimal_required_contract(tmp_path)
    legacy_to_package = {
        "jlcpcb_4_layer_smt": "jlcpcb/lcsc:jlcpcb_4_layer_smt",
        "jlcpcb_smt": "jlcpcb/lcsc:jlcpcb_smt",
        "jlcpcb_full_pcba": "jlcpcb/lcsc:jlcpcb_full_pcba",
        "require_or_exception": "jlcpcb/lcsc:require_or_exception",
        "gd32f310_adc_12v": "acme/gd32f310-support:gd32f310_adc_12v",
        "gd32_12v_input": "acme/gd32f310-support:gd32_12v_input",
        "gd32_adc_frontend": "acme/gd32f310-support:gd32_adc_frontend",
    }
    sync_project(project)

    for legacy_id, package_id in legacy_to_package.items():
        project = _write_board_project_with_canonical_packages(
            tmp_path,
            profiles=[package_id],
            source_contract=contract_path,
        )
        ctx = create_project_context(project)
        assert ctx.profile_set.enabled_checks == frozenset(PROFILE_CHECKS[legacy_id])


def test_profile_requires_source_contract_sections(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )
    sync_project(project)

    with pytest.raises(ProjectConfigError, match="source_contract.required_section_missing"):
        create_project_context(project)


def test_profile_required_source_contract_sections_accept_design_names(tmp_path: Path) -> None:
    contract_path = _write_minimal_required_contract(tmp_path)
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
        source_contract=contract_path,
    )
    sync_project(project)

    ctx = create_project_context(project)

    assert set(ctx.profile_set.requires_contract) == {"adc_frontends", "supply_rails"}
    assert "3V3" in ctx.source_contract.rails
    assert "ADC0" in ctx.source_contract.adc_filters


def test_stm32_package_reuses_core_analog_profile_without_pardal_source_changes(
    tmp_path: Path,
) -> None:
    source_root = Path(__file__).resolve().parents[1] / "examples" / "packages"
    deps_root = tmp_path / "deps"
    deps_root.mkdir()
    shutil.copytree(source_root / "pardal-core", deps_root / "pardal-core")
    stm32_root = deps_root / "stm32-support"
    (stm32_root / "profiles").mkdir(parents=True)
    (stm32_root / "checks").mkdir()
    (stm32_root / "pardal.yaml").write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: package
  identifier: acme/stm32-support
  version: 0.1.0
  repository: https://github.com/acme/stm32-support
  summary: STM32 support
  license: MIT
  authors:
    - name: Hardware
trust:
  python_checks: true
exports:
  profiles:
    - profiles/
  checks:
    - checks/stm32.py
""",
        encoding="utf-8",
    )
    (stm32_root / "profiles" / "stm32.yaml").write_text(
        """
schema: pardal.profile/v1
profiles:
  stm32_adc_frontend:
    imports:
      - pardal/core:analog_rc_filters
    enable_checks:
      - stm32.adc_frontend
""",
        encoding="utf-8",
    )
    (stm32_root / "checks" / "stm32.py").write_text(
        """
from pardal.checks import Severity, Stage, check

@check(id="stm32.adc_frontend", stage=Stage.SOURCE_CONTRACT, default_severity=Severity.WARNING)
def stm32_adc_frontend(ctx):
    return []
""",
        encoding="utf-8",
    )
    contract_path = _write_minimal_required_contract(tmp_path)
    project = _write_board_project(
        tmp_path,
        dependencies=[
            "file://deps/pardal-core",
            "file://deps/stm32-support",
        ],
        profiles=["acme/stm32-support:stm32_adc_frontend"],
        source_contract=contract_path,
    )

    sync_project(project)
    ctx = create_project_context(project)
    resolution = profile_resolution_for_context(CheckContext(spec=object(), project_context=ctx))

    assert ctx.profile_set.expanded == (
        "pardal/core:analog_rc_filters",
        "acme/stm32-support:stm32_adc_frontend",
    )
    assert "analog.rc_filter_values_resolve" in ctx.profile_set.enabled_checks
    assert "stm32.adc_frontend" in ctx.profile_set.enabled_checks
    assert resolution["package_profiles"]["import_tree"] == {
        "acme/stm32-support:stm32_adc_frontend": ("pardal/core:analog_rc_filters",),
        "pardal/core:analog_rc_filters": (),
    }


def test_package_resolution_provenance_includes_lock_exports_profiles_and_checks(tmp_path: Path) -> None:
    contract_path = _write_minimal_required_contract(tmp_path)
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
        source_contract=contract_path,
    )
    sync_project(project)
    ctx = create_project_context(project)
    lock = load_lock_file(tmp_path / "pardal.lock")

    resolution = package_resolution_for_context(ctx)

    assert resolution["schema"] == "pardal.package_resolution/v1"
    assert resolution["project"]["target"] == "default"
    assert resolution["lock"]["present"] is True
    assert resolution["lock"]["manifest"] == "pardal.yaml"
    assert resolution["lock"]["project_hash"].startswith("sha256:")
    assert resolution["lock"]["lock_hash"].startswith("sha256:")
    assert resolution["lock"]["lock_hash"] == file_hash(tmp_path / "pardal.lock")
    assert set(resolution["lock"]["packages"]) == {
        "acme/gd32f310-support",
        "jlcpcb/lcsc",
        "pardal/core",
    }
    gd32_lock_exports = resolution["lock"]["packages"]["acme/gd32f310-support"][
        "export_hashes"
    ]
    assert gd32_lock_exports == lock.packages["acme/gd32f310-support"].export_hashes
    assert set(gd32_lock_exports) >= {
        "profiles",
        "checks",
        "parts",
        "footprints",
        "physical_libraries",
        "route_policies",
        "examples",
    }
    assert gd32_lock_exports["profiles"] == tuple(
        sorted(
            gd32_lock_exports["profiles"],
            key=lambda export: (export["id"], export["path"], export["hash"]),
        )
    )
    assert resolution["packages"]["acme/gd32f310-support"]["locked"] is True
    assert resolution["packages"]["acme/gd32f310-support"]["type"] == "file"
    assert resolution["packages"]["acme/gd32f310-support"]["release"] == "0.1.0"
    assert resolution["packages"]["acme/gd32f310-support"]["source"] == str(
        tmp_path / ".pardal/packages/acme/gd32f310-support"
    )
    assert resolution["packages"]["acme/gd32f310-support"][
        "manifest_hash"
    ].startswith("sha256:")
    assert resolution["packages"]["acme/gd32f310-support"][
        "content_hash"
    ].startswith("sha256:")
    assert resolution["packages"]["acme/gd32f310-support"][
        "export_hashes"
    ] == lock.packages["acme/gd32f310-support"].export_hashes
    assert resolution["packages"]["acme/gd32f310-support"]["dependencies"] == (
        "jlcpcb/lcsc",
    )
    assert {
        export["id"] for export in resolution["exports"]["profiles"]
    } >= {
        "acme/gd32f310-support:gd32f310_adc_12v",
        "jlcpcb/lcsc:jlcpcb_smt",
        "pardal/core:analog_rc_filters",
    }
    assert {
        export["id"] for export in resolution["exports"]["footprints"]
    } == {"acme/gd32f310-support:gd32f310_lqfp32"}
    assert resolution["parts"]["acme/gd32f310-support:GD32F310K8T6"]["lcsc"] == "C112130"
    assert resolution["footprints"]["acme/gd32f310-support:gd32f310_lqfp32"][
        "kicad"
    ] == "Package_QFP:LQFP-32_7x7mm_P0.8mm"
    assert {
        export["id"] for export in resolution["exports"]["physical_libraries"]
    } == {"acme/gd32f310-support:gd32f310"}
    assert {
        export["id"] for export in resolution["exports"]["route_policies"]
    } == {"acme/gd32f310-support:gd32f310_12v_adc"}
    assert {
        export["id"] for export in resolution["exports"]["examples"]
    } == {"acme/gd32f310-support:starter"}
    assert {
        export["id"] for export in resolution["exports"]["board_templates"]
    } == {"acme/gd32f310-support:gd32f310_12v_adc"}
    assert resolution["checks"]["registered"]["gd32.fixture"]["package"] == (
        "acme/gd32f310-support"
    )
    assert resolution["checks"]["registered"]["gd32.fixture"]["stage"] == (
        "source_contract"
    )
    assert resolution["physical_libraries"]["acme/gd32f310-support:gd32f310"][
        "netclasses"
    ] == ("signal", "power")
    assert resolution["physical_libraries"]["acme/gd32f310-support:gd32f310"][
        "placements"
    ] == ("templates/placements/gd32f310_12v_adc.yaml",)
    assert resolution["physical_libraries"]["acme/gd32f310-support:gd32f310"][
        "route_groups"
    ] == ("templates/routes/adc_frontend.yaml",)
    assert resolution["physical_libraries"]["acme/gd32f310-support:gd32f310"][
        "mechanical"
    ] == ("templates/mechanical/mounting_holes.yaml",)
    assert resolution["route_policies"]["acme/gd32f310-support:gd32f310_12v_adc"][
        "net_patterns"
    ] == ("ADC*", "SENSE_*")
    assert resolution["route_policies"]["acme/gd32f310-support:gd32f310_12v_adc"][
        "rules"
    ]["ground_plane_required"] is True
    assert resolution["examples"]["acme/gd32f310-support:starter"][
        "example_path"
    ] == "templates/gd32f310_12v_adc"
    assert resolution["board_templates"][
        "acme/gd32f310-support:gd32f310_12v_adc"
    ]["default_dependencies"] == ("acme/gd32f310-support", "jlcpcb/lcsc")
    assert "acme/gd32f310-support:gd32f310" in resolution["checks"]["loaded_exports"]
    assert resolution["profiles"]["expanded"] == (
        "acme/gd32f310-support:gd32_12v_input",
        "pardal/core:analog_rc_filters",
        "acme/gd32f310-support:gd32_adc_frontend",
        "acme/gd32f310-support:gd32f310_adc_12v",
    )


def test_write_project_provenance_artifacts(tmp_path: Path) -> None:
    contract_path = _write_minimal_required_contract(tmp_path)
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
        source_contract=contract_path,
    )
    sync_project(project)
    ctx = create_project_context(project)

    artifacts = write_project_provenance_artifacts(ctx)

    package_payload = json.loads(artifacts.package_resolution.read_text(encoding="utf-8"))
    profile_payload = json.loads(artifacts.profile_resolution.read_text(encoding="utf-8"))
    assert artifacts.package_resolution == tmp_path / ".pardal/build/default/package-resolution.json"
    assert artifacts.profile_resolution == tmp_path / ".pardal/build/default/profile-resolution.json"
    assert package_payload["schema"] == "pardal.package_resolution/v1"
    assert profile_payload["schema"] == "pardal.profile_resolution/v1"
    assert profile_payload["package_profiles"]["requires_contract"] == {
        "adc_frontends": True,
        "supply_rails": True,
    }
    assert profile_payload["network"]["allow_network_checks"] is False
    assert profile_payload["network"]["skipped_network_checks"] == []

    override_artifacts = write_project_provenance_artifacts(
        ctx,
        output_dir=tmp_path / "network-provenance",
        allow_network_checks=True,
        cli_profiles=["jlcpcb/lcsc:jlcpcb_smt"],
        cli_enable_checks=["fixture.required"],
        cli_disable_checks=["fixture.warning"],
        cli_disable_check_reasons={
            "fixture.warning": "fixture warning is covered by signed review"
        },
    )
    override_profile_payload = json.loads(
        override_artifacts.profile_resolution.read_text(encoding="utf-8")
    )
    assert override_profile_payload["network"]["allow_network_checks"] is True
    assert override_profile_payload["cli"] == {
        "profiles": ["jlcpcb/lcsc:jlcpcb_smt"],
        "enable_checks": ["fixture.required"],
        "disable_checks": ["fixture.warning"],
        "disable_check_reasons": {
            "fixture.warning": "fixture warning is covered by signed review"
        },
    }


def test_production_project_context_requires_lock(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
    )
    ctx = create_project_context(project)

    with pytest.raises(ProjectConfigError, match="project.lock_required"):
        require_project_lock(ctx)

    sync_project(project)
    locked_ctx = create_project_context(project)
    require_project_lock(locked_ctx)


def test_production_project_context_rejects_stale_root_manifest_lock(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])
    sync_project(project)
    project.write_text(
        project.read_text(encoding="utf-8") + "\n# root manifest changed after sync\n",
        encoding="utf-8",
    )
    stale_ctx = create_project_context(project)

    with pytest.raises(ProjectConfigError, match="project.lock_out_of_sync"):
        require_project_lock(stale_ctx)

    sync_project(project)
    fresh_ctx = create_project_context(project)
    require_project_lock(fresh_ctx)


def test_production_project_context_rejects_lock_for_different_root_manifest(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])
    sync_project(project)
    lock_path = tmp_path / "pardal.lock"
    payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    payload["root"]["manifest"] = "other/pardal.yaml"
    lock_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    stale_ctx = create_project_context(project)

    with pytest.raises(ProjectConfigError, match="project.lock_out_of_sync"):
        require_project_lock(stale_ctx)


def test_production_project_context_rejects_stale_file_dependency_lock(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])
    sync_project(project)

    (package_root / "README.md").write_text("changed package content\n", encoding="utf-8")
    stale_ctx = create_project_context(project)

    with pytest.raises(ProjectConfigError, match="project.lock_stale"):
        require_project_lock(stale_ctx)

    update_lock(project, package_id="acme/gd32f310-support")
    fresh_ctx = create_project_context(project)
    require_project_lock(fresh_ctx)


def test_production_project_context_rejects_tampered_installed_package(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])
    sync_project(project)

    installed_readme = tmp_path / ".pardal/packages/acme/gd32f310-support/README.md"
    installed_readme.write_text("tampered installed package content\n", encoding="utf-8")
    stale_ctx = create_project_context(project)

    with pytest.raises(ProjectConfigError, match="project.lock_stale"):
        require_project_lock(stale_ctx)


def test_production_project_context_rejects_missing_installed_package(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[f"file://{package_root.name}"])
    sync_project(project)

    shutil.rmtree(tmp_path / ".pardal/packages/acme/gd32f310-support")
    stale_ctx = create_project_context(project)

    with pytest.raises(ProjectConfigError, match="project.lock_stale"):
        require_project_lock(stale_ctx)


def test_production_project_context_rejects_git_lock_without_commit_at_parse(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repos" / "acme" / "gd32f310-support"
    repo_root.mkdir(parents=True)
    _write_package_fixture(repo_root)
    commit = _init_git_repo(repo_root)
    project = _write_board_project(
        tmp_path,
        dependencies=[f"git://{repo_root.as_posix()}#{commit}"],
    )
    sync_project(project)
    lock_path = tmp_path / "pardal.lock"
    lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock_payload["packages"]["acme/gd32f310-support"].pop("commit")
    lock_path.write_text(
        yaml.safe_dump(lock_payload, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="packages.acme/gd32f310-support.commit"):
        create_project_context(project)


def test_add_list_remove_dependency_round_trip(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[])

    add_dependency(f"file://{package_root.name}", project)
    assert list_dependencies(project) == [f"file://{package_root.name}"]
    assert (tmp_path / ".pardal" / "packages" / "acme" / "gd32f310-support").exists()

    remove_dependency("acme/gd32f310-support", project)

    assert list_dependencies(project) == []
    assert not (tmp_path / ".pardal" / "packages" / "acme" / "gd32f310-support").exists()
    assert (tmp_path / "pardal.lock").exists()


def test_cli_add_sync_list_remove_file_dependency(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(tmp_path, dependencies=[])

    add_result = _run_cli(tmp_path, "add", f"file://{package_root.name}", "--project", str(project))
    assert add_result.returncode == 0, add_result.stderr
    assert "installed acme/gd32f310-support" in add_result.stdout

    list_result = _run_cli(tmp_path, "list", "--project", str(project))
    assert list_result.returncode == 0, list_result.stderr
    assert f"file://{package_root.name}" in list_result.stdout
    assert "[locked acme/gd32f310-support installed]" in list_result.stdout

    sync_result = _run_cli(tmp_path, "sync", "--project", str(project))
    assert sync_result.returncode == 0, sync_result.stderr
    assert "wrote pardal.lock" in sync_result.stdout

    lock_result = _run_cli(
        tmp_path,
        "lock",
        "--update",
        "acme/gd32f310-support",
        "--project",
        str(project),
    )
    assert lock_result.returncode == 0, lock_result.stderr
    assert "wrote pardal.lock" in lock_result.stdout

    missing_lock_result = _run_cli(
        tmp_path,
        "lock",
        "--update",
        "acme/missing",
        "--project",
        str(project),
    )
    assert missing_lock_result.returncode == 1
    assert "dependency.update_missing" in missing_lock_result.stderr

    remove_result = _run_cli(
        tmp_path,
        "remove",
        "acme/gd32f310-support",
        "--project",
        str(project),
    )
    assert remove_result.returncode == 0, remove_result.stderr
    assert "wrote pardal.lock" in remove_result.stdout
    assert not (tmp_path / ".pardal" / "packages" / "acme" / "gd32f310-support").exists()


def test_cli_add_git_dependency_installs_and_locks_commit(tmp_path: Path) -> None:
    repo_root = tmp_path / "repos" / "acme" / "gd32f310-support"
    repo_root.mkdir(parents=True)
    _write_package_fixture(repo_root)
    commit = _init_git_repo(repo_root)
    project = _write_board_project(tmp_path, dependencies=[])

    add_result = _run_cli(
        tmp_path,
        "add",
        f"git://{repo_root.as_posix()}#{commit}",
        "--project",
        str(project),
    )
    assert add_result.returncode == 0, add_result.stderr
    assert "installed acme/gd32f310-support" in add_result.stdout

    lock = load_lock_file(tmp_path / "pardal.lock")
    locked = lock.packages["acme/gd32f310-support"]
    list_result = _run_cli(tmp_path, "list", "--project", str(project))

    assert locked.type == "git"
    assert locked.repo == repo_root.as_posix()
    assert locked.ref == commit
    assert locked.commit == commit
    assert (tmp_path / ".pardal/packages/acme/gd32f310-support/pardal.yaml").exists()
    assert list_result.returncode == 0, list_result.stderr
    assert f"git://{repo_root.as_posix()}#{commit}" in list_result.stdout


def test_package_check_and_build_create_dist_outputs(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)

    report = check_package(package_root / "pardal.yaml")
    result = _build_synced_package(package_root / "pardal.yaml")

    assert report.manifest.project.identifier == "acme/gd32f310-support"
    assert result.archive_path.exists()
    assert result.manifest_path.exists()
    assert result.sha256_path.exists()
    assert result.archive_path.name == "acme-gd32f310-support-0.1.0.tar.gz"


def test_package_build_manifest_and_sha256_match_archive(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)

    result = _build_synced_package(package_root / "pardal.yaml")
    manifest_payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    sidecar = result.sha256_path.read_text(encoding="utf-8").strip()

    assert manifest_payload["schema"] == "pardal.package_manifest/v1"
    assert manifest_payload["identifier"] == "acme/gd32f310-support"
    assert manifest_payload["version"] == "0.1.0"
    assert manifest_payload["archive"] == result.archive_path.name
    assert manifest_payload["content_hash"] == package_content_hash(package_root)
    assert sidecar == f"{_sha256(result.archive_path)}  {result.archive_path.name}"


def test_package_check_does_not_mutate_package_source(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    before_package_files = _file_snapshot(package_root)

    check_package(package_root / "pardal.yaml")

    assert _file_snapshot(package_root) == before_package_files
    assert not (package_root / "checks" / "__pycache__").exists()


def test_project_context_loading_checks_does_not_mutate_installed_package(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
    )
    sync_project(project)
    installed_root = tmp_path / ".pardal" / "packages" / "acme" / "gd32f310-support"
    before_installed_files = _file_snapshot(installed_root)

    create_project_context(project)

    assert _file_snapshot(installed_root) == before_installed_files
    assert not (installed_root / "checks" / "__pycache__").exists()


def test_project_context_rejects_installed_check_module_source_mutation(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pathlib import Path
from pardal.checks import Severity, Stage, check

@check(id="fixture.installed_mutating_check", stage=Stage.MANIFEST, default_severity=Severity.INFO)
def package_check(ctx):
    return []

Path(__file__).resolve().parents[1].joinpath("mutated.txt").write_text("mutation")
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
    )
    sync_project(project)
    installed_check = (
        tmp_path
        / ".pardal"
        / "packages"
        / "acme"
        / "gd32f310-support"
        / "checks"
        / "gd32f310.py"
    )
    before_registry = registered_checks()

    with pytest.raises(ProjectConfigError, match="package.source_mutated") as exc_info:
        create_project_context(project)

    assert exc_info.value.diagnostic.path == installed_check
    assert exc_info.value.diagnostic.field == "package"
    assert registered_checks() == before_registry


def test_package_check_rejects_missing_package_authors(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    manifest_path = package_root / "pardal.yaml"
    raw = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        raw.replace("  authors:\n    - name: Hardware\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="manifest.package_authors_missing"):
        check_package(manifest_path)


@pytest.mark.parametrize(
    ("old", "new", "error_code", "field"),
    [
        (
            "identifier: acme/gd32f310-support",
            "identifier: Acme/GD32",
            "manifest.package_identifier_invalid",
            "project.identifier",
        ),
        (
            "version: 0.1.0",
            "version: invalid",
            "manifest.package_version_invalid",
            "project.version",
        ),
        (
            "repository: https://github.com/acme/gd32f310-support",
            "repository: ''",
            "manifest.required_string_missing",
            "project.repository",
        ),
        (
            "license: MIT",
            "license: ''",
            "manifest.required_string_missing",
            "project.license",
        ),
    ],
)
def test_package_manifest_rejects_invalid_metadata_fields(
    tmp_path: Path,
    old: str,
    new: str,
    error_code: str,
    field: str,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    manifest_path = package_root / "pardal.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(old, new),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match=error_code) as exc_info:
        check_package(manifest_path)

    assert exc_info.value.diagnostic.path == manifest_path
    assert exc_info.value.diagnostic.field == field


def test_package_check_rejects_package_author_without_name(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    manifest_path = package_root / "pardal.yaml"
    raw = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        raw.replace("    - name: Hardware\n", "    - email: hardware@example.com\n"),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="manifest.package_author_name_missing"):
        check_package(manifest_path)


def test_package_build_requires_synced_lock(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)

    with pytest.raises(ProjectConfigError, match="project.lock_required"):
        build_package(package_root / "pardal.yaml")


def test_package_build_rejects_stale_manifest_lock(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    manifest_path = package_root / "pardal.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\n# stale after sync\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="project.lock_out_of_sync"):
        build_package(manifest_path)


def test_package_build_rejects_lock_with_unreachable_package(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    lock_path = package_root / "pardal.lock"
    payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    payload["packages"]["acme/unreachable"] = {
        "type": "registry",
        "release": "0.1.0",
        "source": "registry/acme-unreachable-0.1.0.tar.gz",
        "manifest_hash": "sha256:manifest",
        "content_hash": "sha256:unreachable",
    }
    lock_path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="project.lock_out_of_sync"):
        build_package(package_root / "pardal.yaml")


def test_package_build_excludes_generated_production_artifacts(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    generated_names = {
        "package-resolution.json",
        "profile-resolution.json",
        "production-checks.json",
        "build-summary.json",
        "manufacturing-package.zip",
        "board-drc.rpt",
        "board-drc.json",
    }
    for name in generated_names:
        (package_root / name).write_text("generated output\n", encoding="utf-8")

    result = _build_synced_package(package_root / "pardal.yaml")

    with tarfile.open(result.archive_path, "r:gz") as archive:
        archived_names = set(archive.getnames())
    assert "pardal.yaml" in archived_names
    assert "profiles/gd32.yaml" in archived_names
    assert archived_names.isdisjoint(generated_names)


def test_package_build_archive_is_metadata_deterministic(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    output_one = tmp_path / "dist-one"
    output_two = tmp_path / "dist-two"

    first = _build_synced_package(package_root / "pardal.yaml", output_dir=output_one)
    for path in package_root.rglob("*"):
        if path.is_file():
            os.utime(path, (123456789, 123456789))
            path.chmod(0o600)
    second = build_package(package_root / "pardal.yaml", output_dir=output_two)

    assert _sha256(first.archive_path) == _sha256(second.archive_path)
    with tarfile.open(second.archive_path, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
    assert members["pardal.yaml"].mtime == 0
    assert members["pardal.yaml"].uid == 0
    assert members["pardal.yaml"].gid == 0
    assert members["pardal.yaml"].mode == 0o644


def test_package_check_rejects_source_symlink(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "linked.py").symlink_to(package_root / "checks" / "gd32f310.py")

    with pytest.raises(ProjectConfigError, match="package.source_unsafe") as exc_info:
        check_package(package_root / "pardal.yaml")

    assert exc_info.value.diagnostic.path == package_root / "linked.py"


def test_package_check_rejects_source_hardlink(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    hardlink = package_root / "hardlinked.py"
    try:
        os.link(package_root / "checks" / "gd32f310.py", hardlink)
    except OSError as exc:
        pytest.skip(f"hardlinks are unavailable in this filesystem: {exc}")

    with pytest.raises(ProjectConfigError, match="package.source_unsafe"):
        check_package(package_root / "pardal.yaml")


def test_package_check_rejects_check_module_source_mutation(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pathlib import Path
from pardal.checks import Severity, Stage, check

Path(__file__).resolve().parents[1].joinpath("mutated.txt").write_text("mutation")

@check(id="fixture.mutating_check", stage=Stage.MANIFEST, default_severity=Severity.INFO)
def package_check(ctx):
    return []
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.source_mutated") as exc_info:
        check_package(package_root / "pardal.yaml")

    assert exc_info.value.diagnostic.path == package_root / "pardal.yaml"
    assert exc_info.value.diagnostic.field == "package"


def test_package_check_rejects_source_fifo(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is unavailable on this platform")
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    fifo = package_root / "named-pipe"
    os.mkfifo(fifo)

    with pytest.raises(ProjectConfigError, match="package.source_unsafe") as exc_info:
        check_package(package_root / "pardal.yaml")

    assert exc_info.value.diagnostic.path == fifo


def test_package_check_does_not_pollute_check_registry(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pardal.checks import Severity, Stage, check

@check(id="fixture.repeatable", stage=Stage.MANIFEST, default_severity=Severity.INFO)
def fixture(ctx):
    return []
""",
        encoding="utf-8",
    )
    before = set(registered_checks())

    check_package(package_root / "pardal.yaml")
    check_package(package_root / "pardal.yaml")

    assert set(registered_checks()) == before


def test_package_check_rejects_duplicate_public_check_id(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "checks" / "a.py").write_text(
        """
from pardal.checks import Severity, Stage, check

@check(id="fixture.duplicate", stage=Stage.MANIFEST, default_severity=Severity.INFO)
def first(ctx):
    return []
""",
        encoding="utf-8",
    )
    (package_root / "checks" / "b.py").write_text(
        """
from pardal.checks import Severity, Stage, check

@check(id="fixture.duplicate", stage=Stage.MANIFEST, default_severity=Severity.INFO)
def second(ctx):
    return []
""",
        encoding="utf-8",
    )
    raw = (package_root / "pardal.yaml").read_text(encoding="utf-8")
    (package_root / "pardal.yaml").write_text(
        raw.replace("    - checks/gd32f310.py", "    - checks/"),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.check_duplicate") as exc_info:
        check_package(package_root / "pardal.yaml")

    assert "fixture.duplicate" in str(exc_info.value)
    assert exc_info.value.diagnostic.path == package_root / "checks" / "b.py"


def test_package_check_rejects_empty_check_export(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "checks" / "gd32f310.py").write_text(
        "# placeholder without public checks\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.check_export_empty"):
        check_package(package_root / "pardal.yaml")


def test_package_check_rejects_check_export_importing_internal_pardal(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pardal.checks.api import Severity, Stage, check

@check(id="fixture.internal_import", stage=Stage.MANIFEST, default_severity=Severity.INFO)
def internal_import(ctx):
    return []
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.check_internal_import"):
        check_package(package_root / "pardal.yaml")


def test_package_check_rejects_check_export_importing_internal_pardal_module(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "checks" / "gd32f310.py").write_text(
        """
import pardal.production_checks
from pardal.checks import Severity, Stage, check

@check(id="fixture.internal_module_import", stage=Stage.MANIFEST, default_severity=Severity.INFO)
def internal_import(ctx):
    return []
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.check_internal_import"):
        check_package(package_root / "pardal.yaml")


def test_package_check_allows_package_local_check_helper_import(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "check_helpers.py").write_text(
        """
def check_id():
    return "fixture.local_helper"
""",
        encoding="utf-8",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from check_helpers import check_id
from pardal.checks import Severity, Stage, check

@check(id=check_id(), stage=Stage.MANIFEST, default_severity=Severity.INFO)
def local_helper(ctx):
    return []
""",
        encoding="utf-8",
    )

    report = check_package(package_root / "pardal.yaml")

    assert "acme/gd32f310-support:gd32f310" in {export.id for export in report.exports}


def test_package_check_isolates_package_local_helper_submodules(tmp_path: Path) -> None:
    first = tmp_path / "first_pkg"
    second = tmp_path / "second_pkg"
    first.mkdir()
    second.mkdir()
    _write_helper_check_package(first, identifier="acme/first-support", marker="first")
    _write_helper_check_package(second, identifier="acme/second-support", marker="second")

    check_package(first / "pardal.yaml")
    check_package(second / "pardal.yaml")


def test_project_context_isolates_installed_package_local_helper_submodules(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first_pkg"
    second = tmp_path / "second_pkg"
    first.mkdir()
    second.mkdir()
    _write_helper_check_package(first, identifier="acme/first-support", marker="first")
    _write_helper_check_package(second, identifier="acme/second-support", marker="second")
    project = _write_board_project(
        tmp_path,
        dependencies=[
            "file://first_pkg",
            "file://second_pkg",
        ],
    )

    sync_project(project)
    ctx = create_project_context(project)

    assert ctx.loaded_check_exports == (
        "acme/first-support:package_check",
        "acme/second-support:package_check",
    )
    assert registered_checks()["first.package_check"].package == "acme/first-support"
    assert registered_checks()["second.package_check"].package == "acme/second-support"
    assert "helpers" not in sys.modules


def test_project_context_scopes_registered_checks_to_active_packages(
    tmp_path: Path,
) -> None:
    check_id = f"fixture.stale_context_{tmp_path.name}"
    first_root = tmp_path / "first"
    first_package = first_root / "stale_pkg"
    first_package.mkdir(parents=True)
    _write_check_only_package_fixture(
        first_package,
        identifier="acme/stale-support",
        check_id=check_id,
        requires_network=True,
    )
    first_project = _write_board_project(
        first_root,
        dependencies=[f"file://{first_package.name}"],
    )
    sync_project(first_project)
    create_project_context(first_project)
    assert check_id in registered_checks()

    second_root = tmp_path / "second"
    second_package = second_root / "profile_pkg"
    second_package.mkdir(parents=True)
    _write_minimal_package_fixture(
        second_package,
        identifier="acme/profile-support",
        profile_name="default",
    )
    second_project = _write_board_project(
        second_root,
        dependencies=[f"file://{second_package.name}"],
        profiles=["acme/profile-support:default"],
    )
    sync_project(second_project)
    second_context = create_project_context(second_project)
    package_resolution = package_resolution_for_context(second_context)
    profile_resolution = profile_resolution_for_context(
        CheckContext(spec=object(), project_context=second_context)
    )

    assert check_id not in package_resolution["checks"]["registered"]
    assert check_id not in profile_resolution["network"]["network_capable_checks"]

    _replace_minimal_package_profile(
        second_package,
        profile_name="default",
        enable_checks=[check_id],
    )
    sync_project(second_project)

    with pytest.raises(ProjectConfigError, match="profile.check_unknown"):
        create_project_context(second_project)


def test_project_context_rejects_untrusted_installed_package_checks_before_import(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    raw = yaml.safe_load((package_root / "pardal.yaml").read_text(encoding="utf-8"))
    raw.pop("trust")
    (package_root / "pardal.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from pathlib import Path

Path("check-imported.marker").write_text("imported", encoding="utf-8")
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
    )
    sync_project(project)

    with pytest.raises(ProjectConfigError, match="package.python_checks_untrusted"):
        create_project_context(project)

    assert not (tmp_path / "check-imported.marker").exists()


def test_package_check_rejects_internal_import_in_package_local_helper(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "check_helpers.py").write_text(
        """
from pardal.production_checks import CheckFinding

def check_id():
    return "fixture.local_helper"
""",
        encoding="utf-8",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from check_helpers import check_id
from pardal.checks import Severity, Stage, check

@check(id=check_id(), stage=Stage.MANIFEST, default_severity=Severity.INFO)
def local_helper(ctx):
    return []
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.check_internal_import"):
        check_package(package_root / "pardal.yaml")


def test_project_context_rejects_internal_import_in_installed_package_helper(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "check_helpers.py").write_text(
        """
import pardal.production_checks

def check_id():
    return "fixture.local_helper"
""",
        encoding="utf-8",
    )
    (package_root / "checks" / "gd32f310.py").write_text(
        """
from check_helpers import check_id
from pardal.checks import Severity, Stage, check

@check(id=check_id(), stage=Stage.MANIFEST, default_severity=Severity.INFO)
def local_helper(ctx):
    return []
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{package_root.name}"],
    )
    sync_project(project)

    with pytest.raises(ProjectConfigError, match="package.check_internal_import"):
        create_project_context(project)


def test_project_context_isolates_installed_package_helper_submodules(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first_pkg"
    second = tmp_path / "second_pkg"
    first.mkdir()
    second.mkdir()
    _write_helper_check_package(first, identifier="acme/first-support", marker="first")
    _write_helper_check_package(second, identifier="acme/second-support", marker="second")
    project = _write_board_project(
        tmp_path,
        dependencies=[f"file://{first.name}", f"file://{second.name}"],
    )
    sync_project(project)

    ctx = create_project_context(project)

    assert ctx.loaded_check_exports == (
        "acme/first-support:package_check",
        "acme/second-support:package_check",
    )


def test_package_check_rejects_missing_export_path(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    raw = (package_root / "pardal.yaml").read_text(encoding="utf-8")
    (package_root / "pardal.yaml").write_text(
        raw.replace("    - parts/", "    - missing-parts/"),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.export_path_missing"):
        check_package(package_root / "pardal.yaml")


def test_package_check_rejects_export_path_outside_package_root(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    outside = tmp_path / "outside-parts"
    outside.mkdir()
    (outside / "parts.yaml").write_text(
        """
schema: pardal.parts/v1
parts:
  outside:
    manufacturer: outside
""",
        encoding="utf-8",
    )
    raw = (package_root / "pardal.yaml").read_text(encoding="utf-8")
    (package_root / "pardal.yaml").write_text(
        raw.replace("    - parts/", "    - ../outside-parts/"),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.export_path_outside"):
        check_package(package_root / "pardal.yaml")


def test_package_check_rejects_explicit_export_file_with_wrong_schema(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    raw = (package_root / "pardal.yaml").read_text(encoding="utf-8")
    (package_root / "pardal.yaml").write_text(
        raw.replace("    - parts/", "    - profiles/gd32.yaml"),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.export_schema_invalid"):
        check_package(package_root / "pardal.yaml")


def test_package_check_ignores_unrelated_files_inside_export_directory(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "parts" / "note.yaml").write_text(
        """
schema: pardal.profile/v1
profiles:
  unrelated:
    enable_checks: []
""",
        encoding="utf-8",
    )

    report = check_package(package_root / "pardal.yaml")

    assert "acme/gd32f310-support:GD32F310K8T6" in {
        export.id for export in report.exports
    }
    assert "acme/gd32f310-support:unrelated" not in {
        export.id for export in report.exports
    }


def test_package_check_ignores_malformed_yaml_inside_export_directory(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "parts" / "scratch.yaml").write_text(
        "schema: [not: valid\n",
        encoding="utf-8",
    )

    report = check_package(package_root / "pardal.yaml")

    assert "acme/gd32f310-support:GD32F310K8T6" in {
        export.id for export in report.exports
    }


def test_package_check_rejects_explicit_export_file_with_malformed_yaml(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    (package_root / "parts" / "scratch.yaml").write_text(
        "schema: [not: valid\n",
        encoding="utf-8",
    )
    raw = yaml.safe_load((package_root / "pardal.yaml").read_text(encoding="utf-8"))
    raw["exports"]["parts"] = ["parts/scratch.yaml"]
    (package_root / "pardal.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.export_file_invalid") as exc_info:
        check_package(package_root / "pardal.yaml")

    assert exc_info.value.diagnostic.path == package_root / "parts" / "scratch.yaml"
    assert exc_info.value.diagnostic.field == "yaml"


def test_package_check_requires_explicit_trust_for_python_checks(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    raw = yaml.safe_load((package_root / "pardal.yaml").read_text(encoding="utf-8"))
    raw.pop("trust")
    (package_root / "pardal.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.python_checks_untrusted"):
        check_package(package_root / "pardal.yaml")


def test_package_check_rejects_template_absolute_project_path(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    package_root = result.root
    template_note = package_root / "templates" / "starter" / "absolute-note.txt"
    template_note.write_text(
        f"generated from {package_root.resolve()}\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.template_absolute_path"):
        check_package(result.manifest_path)


def test_package_check_rejects_template_manifest_absolute_project_path(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    package_root = result.root
    template_manifest = package_root / "templates" / "starter" / "pardal.yaml"
    template_manifest.write_text(
        template_manifest.read_text(encoding="utf-8")
        + f"\npaths:\n  generated_from: {package_root.resolve()}\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.template_absolute_path"):
        check_package(result.manifest_path)


def test_package_check_rejects_template_file_dependency(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    template_manifest = result.root / "templates" / "starter" / "pardal.yaml"
    template_manifest.write_text(
        template_manifest.read_text(encoding="utf-8")
        + "\ndependencies:\n  - type: file\n    path: ../..\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.template_file_dependency"):
        check_package(result.manifest_path)


def test_package_check_rejects_template_missing_manifest(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "templates" / "starter" / "pardal.yaml").unlink()

    with pytest.raises(ProjectConfigError, match="package.template_manifest_missing"):
        check_package(result.manifest_path)


def test_package_check_rejects_template_default_dependencies_not_list(
    tmp_path: Path,
) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    templates_path = result.root / "templates.yaml"
    templates_path.write_text(
        """
schema: pardal.templates/v1
templates:
  starter:
    description: Starter board project for this package
    path: templates/starter
    default_dependencies: acme/other
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.template_default_dependencies_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_template_default_dependency_invalid_id(
    tmp_path: Path,
) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    templates_path = result.root / "templates.yaml"
    templates_path.write_text(
        """
schema: pardal.templates/v1
templates:
  starter:
    description: Starter board project for this package
    path: templates/starter
    default_dependencies:
      - Not/A-Package
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.template_default_dependency_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_template_id(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    templates_path = result.root / "templates.yaml"
    templates_path.write_text(
        """
schema: pardal.templates/v1
templates:
  "":
    description: Starter board project for this package
    path: templates/starter
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.template_id_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_physical_library_export(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "physical_libraries" / "libraries.yaml").write_text(
        """
schema: pardal.physical_library/v1
libraries:
  default:
    metadata:
      - not-a-mapping
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="physical_library.mapping_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_physical_library_id(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "physical_libraries" / "libraries.yaml").write_text(
        """
schema: pardal.physical_library/v1
libraries:
  "":
    footprints: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="physical_library.id_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_physical_library_template_lists(
    tmp_path: Path,
) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "physical_libraries" / "libraries.yaml").write_text(
        """
schema: pardal.physical_library/v1
libraries:
  default:
    placements:
      - templates/placement/default.yaml
      - 123
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="physical_library.string_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_part_catalog_export(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "parts" / "parts.yaml").write_text(
        """
schema: pardal.parts/v1
parts:
  placeholder:
    attributes:
      - not-a-mapping
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="part_catalog.mapping_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_part_catalog_pins(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "parts" / "parts.yaml").write_text(
        """
schema: pardal.parts/v1
parts:
  placeholder:
    pins: "32"
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="part_catalog.positive_int_invalid"):
        check_package(result.manifest_path)

    (result.root / "parts" / "parts.yaml").write_text(
        """
schema: pardal.parts/v1
parts:
  placeholder:
    pins: 0
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="part_catalog.positive_int_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_unqualified_part_catalog_footprint(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "parts" / "parts.yaml").write_text(
        """
schema: pardal.parts/v1
parts:
  placeholder:
    footprint: placeholder_footprint
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="part_catalog.footprint_unqualified"):
        check_package(result.manifest_path)


def test_package_check_rejects_unknown_same_package_part_catalog_footprint(
    tmp_path: Path,
) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "parts" / "parts.yaml").write_text(
        """
schema: pardal.parts/v1
parts:
  placeholder:
    footprint: acme/new-support:missing_footprint
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="part_catalog.footprint_unknown"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_part_catalog_id(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "parts" / "parts.yaml").write_text(
        """
schema: pardal.parts/v1
parts:
  123:
    manufacturer: example
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="part_catalog.id_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_footprint_export(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "footprints" / "footprints.yaml").write_text(
        """
schema: pardal.footprints/v1
footprints:
  placeholder:
    metadata:
      - not-a-mapping
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="footprint.mapping_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_footprint_schema_fields(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "footprints" / "footprints.yaml").write_text(
        """
schema: pardal.footprints/v1
footprints:
  placeholder:
    kind: [kicad_mod]
    courtyard_required: "true"
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="footprint.string_invalid"):
        check_package(result.manifest_path)

    (result.root / "footprints" / "footprints.yaml").write_text(
        """
schema: pardal.footprints/v1
footprints:
  placeholder:
    kind: kicad_mod
    courtyard_required: "true"
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="footprint.boolean_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_footprint_id(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "footprints" / "footprints.yaml").write_text(
        """
schema: pardal.footprints/v1
footprints:
  "":
    kicad: Connector_Generic:Conn_01x02
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="footprint.id_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_missing_footprint_source_path(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "footprints" / "footprints.yaml").write_text(
        """
schema: pardal.footprints/v1
footprints:
  placeholder:
    path: missing.pretty
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="footprint.path_missing"):
        check_package(result.manifest_path)


def test_package_check_rejects_footprint_source_path_outside_package(
    tmp_path: Path,
) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    outside = tmp_path / "outside.kicad_mod"
    outside.write_text("(footprint outside)\n", encoding="utf-8")
    (result.root / "footprints" / "footprints.yaml").write_text(
        """
schema: pardal.footprints/v1
footprints:
  placeholder:
    path: ../../outside.kicad_mod
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="footprint.path_outside_package"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_route_policy_export(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "routing" / "policies.yaml").write_text(
        """
schema: pardal.route_policy/v1
policies:
  default:
    rules:
      - not-a-mapping
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="route_policy.mapping_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_route_policy_id(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "routing" / "policies.yaml").write_text(
        """
schema: pardal.route_policy/v1
policies:
  123:
    rules: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="route_policy.id_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_example_path_outside_package_root(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    examples_path = result.root / "examples.yaml"
    examples_path.write_text(
        """
schema: pardal.examples/v1
examples:
  escaped:
    description: Escaped example
    mode: documentation_only
    path: ../outside
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.example_path_outside"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_example_id(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    examples_path = result.root / "examples.yaml"
    examples_path.write_text(
        """
schema: pardal.examples/v1
examples:
  123:
    description: Numeric example ID
    mode: documentation_only
    path: templates/starter
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="example.id_invalid"):
        check_package(result.manifest_path)


def test_package_check_rejects_example_missing_path(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    examples_path = result.root / "examples.yaml"
    examples_path.write_text(
        """
schema: pardal.examples/v1
examples:
  missing:
    description: Missing path
    mode: documentation_only
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="example.path_invalid"):
        check_package(result.manifest_path)


def test_package_check_validates_non_root_exported_examples_file(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    raw = yaml.safe_load(result.manifest_path.read_text(encoding="utf-8"))
    raw["exports"]["examples"] = ["docs/examples.yaml"]
    result.manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    (result.root / "docs").mkdir()
    (result.root / "docs" / "examples.yaml").write_text(
        """
schema: pardal.examples/v1
examples:
  escaped:
    description: Escaped example
    mode: documentation_only
    path: ../outside
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.example_path_outside"):
        check_package(result.manifest_path)


def test_package_check_rejects_invalid_example_metadata_mapping(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    (result.root / "examples" / "datasheet-only").mkdir()
    (result.root / "examples.yaml").write_text(
        """
schema: pardal.examples/v1
examples:
  datasheet:
    description: Documentation-only example
    mode: documentation_only
    path: examples/datasheet-only
    metadata:
      - not-a-mapping
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="example.mapping_invalid"):
        check_package(result.manifest_path)


def test_package_check_keeps_documentation_only_examples_non_building(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    examples_path = result.root / "examples.yaml"
    (result.root / "examples" / "datasheet-only").mkdir()
    examples_path.write_text(
        """
schema: pardal.examples/v1
examples:
  datasheet:
    description: Documentation-only example
    mode: documentation_only
    path: examples/datasheet-only
""",
        encoding="utf-8",
    )

    check_package(result.manifest_path)


def test_package_check_smokes_build_examples_in_isolated_project(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    example_root = result.root / "examples" / "buildable"
    (example_root / "boards").mkdir(parents=True)
    (example_root / "boards" / "demo.pardal.yaml").write_text(
        "source:\n  note: build example\n",
        encoding="utf-8",
    )
    (example_root / "pardal.yaml").write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: buildable
builds:
  default:
    entry: boards/demo.pardal.yaml
""",
        encoding="utf-8",
    )
    (result.root / "examples.yaml").write_text(
        """
schema: pardal.examples/v1
examples:
  buildable:
    description: Buildable example
    mode: build
    path: examples/buildable
""",
        encoding="utf-8",
    )

    check_package(result.manifest_path)
    assert not (example_root / "pardal.lock").exists()


def test_package_check_fails_build_example_smoke(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")
    example_root = result.root / "examples" / "broken"
    (example_root / "boards").mkdir(parents=True)
    (example_root / "boards" / "demo.pardal.yaml").write_text(
        "source:\n  note: broken build example\n",
        encoding="utf-8",
    )
    (example_root / "pardal.yaml").write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: broken
builds:
  default:
    entry: boards/demo.pardal.yaml
    profiles:
      - acme/new-support:missing
""",
        encoding="utf-8",
    )
    (result.root / "examples.yaml").write_text(
        """
schema: pardal.examples/v1
examples:
  broken:
    description: Broken build example
    mode: build
    path: examples/broken
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.example_smoke_failed"):
        check_package(result.manifest_path)


def test_package_check_publish_rejects_file_dependency(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    raw = (package_root / "pardal.yaml").read_text(encoding="utf-8")
    (package_root / "pardal.yaml").write_text(
        raw + "\ndependencies:\n  - type: file\n    path: ../local\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.file_dependency_not_publishable"):
        check_package(package_root / "pardal.yaml", publish=True)


def test_package_check_publish_rejects_git_dependency_without_ref(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    raw = (package_root / "pardal.yaml").read_text(encoding="utf-8")
    (package_root / "pardal.yaml").write_text(
        raw
        + "\ndependencies:\n"
        + "  - type: git\n"
        + "    identifier: acme/other-support\n"
        + "    repo: https://github.com/acme/other-support.git\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.git_dependency_ref_required"):
        check_package(package_root / "pardal.yaml", publish=True)


def test_package_publish_dry_run_validates_artifacts_without_writing_dist(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")

    result = publish_package(package_root / "pardal.yaml", dry_run=True)

    assert result.dry_run is True
    assert not result.archive_path.exists()
    assert not result.manifest_path.exists()
    assert not result.sha256_path.exists()
    assert not (package_root / "dist").exists()
    assert result.archive_path.parent == package_root / "dist"
    assert result.archive_path.name == "acme-gd32f310-support-0.1.0.tar.gz"


def test_package_publish_dry_run_does_not_write_explicit_output_dir(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    dry_run_output_dir = tmp_path / "dry-run-output"

    result = publish_package(
        package_root / "pardal.yaml",
        dry_run=True,
        output_dir=dry_run_output_dir,
    )

    assert result.dry_run is True
    assert result.archive_path.parent == dry_run_output_dir
    assert not dry_run_output_dir.exists()


def test_package_publish_requires_synced_lock(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)

    with pytest.raises(ProjectConfigError, match="project.lock_required"):
        publish_package(package_root / "pardal.yaml", dry_run=True)


def test_package_publish_wraps_malformed_lock(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    lock_path = package_root / "pardal.lock"
    _write_malformed_lock(lock_path)

    with pytest.raises(ProjectConfigError, match="project.lock_invalid") as exc_info:
        publish_package(package_root / "pardal.yaml", dry_run=True)

    assert exc_info.value.diagnostic.path == lock_path
    assert exc_info.value.diagnostic.field == "pardal.lock"


def test_package_publish_dry_run_validates_static_registry_metadata(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages: {}
""",
        encoding="utf-8",
    )

    result = publish_package(
        package_root / "pardal.yaml",
        dry_run=True,
        registry_index=registry_index,
    )

    assert result.dry_run is True
    assert result.archive_path.parent == package_root / "dist"
    assert not (package_root / "dist").exists()


def test_package_publish_dry_run_rejects_malformed_registry_yaml(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text("schema: [\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="package.publish_registry_yaml_invalid") as exc_info:
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )

    assert exc_info.value.diagnostic.path == registry_index
    assert exc_info.value.diagnostic.field == "yaml"


def test_static_registry_client_rejects_malformed_yaml(tmp_path: Path) -> None:
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text("schema: [\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="registry.yaml_invalid") as exc_info:
        StaticRegistryClient(registry_index)

    assert exc_info.value.diagnostic.path == registry_index
    assert exc_info.value.diagnostic.field == "yaml"


def test_package_publish_dry_run_rejects_existing_registry_release(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
    )

    with pytest.raises(ProjectConfigError, match="package.publish_registry_release_exists"):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_incompatible_registry_metadata(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
        requires_pardal="^0.2.0",
    )

    with pytest.raises(ProjectConfigError, match="manifest.requires_pardal_incompatible"):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_non_string_registry_requires_pardal(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.1.0:
        url: {package_build.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(package_build.archive_path)}
        yanked: false
        requires_pardal: 1
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="package.publish_registry_requires_pardal_invalid",
    ):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_non_boolean_registry_yanked(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.1.0:
        url: {package_build.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(package_build.archive_path)}
        yanked: "false"
        requires_pardal: "^0.1.0"
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="package.publish_registry_yanked_invalid",
    ):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_invalid_registry_package_key(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages:
  InvalidPackage:
    versions: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="package.publish_registry_package_id_invalid",
    ):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_invalid_registry_version_key(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      not-semver:
        url: {package_build.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(package_build.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="package.publish_registry_version_invalid",
    ):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_invalid_unrelated_registry_version_key(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages:
  acme/other-support:
    versions:
      2026:
        url: packages/other.tar.gz
        sha256: sha256:other
        yanked: false
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="package.publish_registry_version_invalid",
    ):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_invalid_unrelated_release_mapping(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages:
  acme/other-support:
    versions:
      0.1.0: "not-a-release-mapping"
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="package.publish_registry_release_invalid",
    ):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_unrelated_release_missing_url_hash(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages:
  acme/other-support:
    versions:
      0.1.0:
        url: packages/other.tar.gz
        yanked: false
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="package.publish_registry_release_invalid",
    ):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_unrelated_release_bad_sha256(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages:
  acme/other-support:
    versions:
      0.1.0:
        url: packages/other.tar.gz
        sha256: sha256:not-hex
        yanked: false
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="package.publish_registry_sha256_invalid",
    ):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_unrelated_release_bad_yanked(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages:
  acme/other-support:
        versions:
          0.1.0:
            url: packages/other.tar.gz
            sha256: sha256:0000000000000000000000000000000000000000000000000000000000000000
            yanked: "false"
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="package.publish_registry_yanked_invalid",
    ):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_unrelated_release_bad_requires_pardal(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages:
  acme/other-support:
        versions:
          0.1.0:
            url: packages/other.tar.gz
            sha256: sha256:0000000000000000000000000000000000000000000000000000000000000000
            yanked: false
            requires_pardal: 1
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectConfigError,
        match="package.publish_registry_requires_pardal_invalid",
    ):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=True,
            registry_index=registry_index,
        )


def test_package_publish_dry_run_rejects_file_dependency(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    raw = (package_root / "pardal.yaml").read_text(encoding="utf-8")
    (package_root / "pardal.yaml").write_text(
        raw + "\ndependencies:\n  - type: file\n    path: ../local\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.file_dependency_not_publishable"):
        publish_package(package_root / "pardal.yaml", dry_run=True)


def test_package_publish_dry_run_rejects_git_dependency_without_ref(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    raw = (package_root / "pardal.yaml").read_text(encoding="utf-8")
    (package_root / "pardal.yaml").write_text(
        raw
        + "\ndependencies:\n"
        + "  - type: git\n"
        + "    identifier: acme/other-support\n"
        + "    repo: https://github.com/acme/other-support.git\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="package.git_dependency_ref_required"):
        publish_package(package_root / "pardal.yaml", dry_run=True)


def test_package_publish_requires_registry_index_without_dry_run(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")

    with pytest.raises(ProjectConfigError, match="package.publish_registry_required"):
        publish_package(package_root / "pardal.yaml", dry_run=False)


def test_package_publish_rejects_output_dir_without_dry_run(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages: {}
""",
        encoding="utf-8",
    )
    explicit_output_dir = tmp_path / "external-dist"

    with pytest.raises(ProjectConfigError, match="package.publish_output_dir_invalid"):
        publish_package(
            package_root / "pardal.yaml",
            dry_run=False,
            output_dir=explicit_output_dir,
            registry_index=registry_index,
        )

    assert not explicit_output_dir.exists()


def test_package_publish_updates_static_registry_index(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages: {}
""",
        encoding="utf-8",
    )

    result = publish_package(
        package_root / "pardal.yaml",
        dry_run=False,
        registry_index=registry_index,
    )
    payload = yaml.safe_load(registry_index.read_text(encoding="utf-8"))
    release = payload["packages"]["acme/gd32f310-support"]["versions"]["0.1.0"]

    assert result.dry_run is False
    assert result.registry_index == registry_index
    assert result.archive_path.exists()
    assert release["url"] == "packages/acme-gd32f310-support-0.1.0.tar.gz"
    assert release["sha256"].startswith("sha256:")
    assert release["yanked"] is False
    assert release["requires_pardal"] == "^0.1.0"


def test_package_publish_mutates_only_registry_outputs(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    sync_project(package_root / "pardal.yaml")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages: {}
""",
        encoding="utf-8",
    )
    before_package_files = _file_snapshot(package_root)

    result = publish_package(
        package_root / "pardal.yaml",
        dry_run=False,
        registry_index=registry_index,
    )

    after_package_files = _file_snapshot(package_root)
    assert after_package_files == before_package_files
    assert result.archive_path == tmp_path / "packages/acme-gd32f310-support-0.1.0.tar.gz"
    assert result.manifest_path == tmp_path / "packages/acme-gd32f310-support-0.1.0.manifest.json"
    assert result.sha256_path == tmp_path / "packages/acme-gd32f310-support-0.1.0.sha256"
    assert result.archive_path.exists()
    assert result.manifest_path.exists()
    assert result.sha256_path.exists()
    assert not (package_root / "dist").exists()


def test_cli_package_check_and_build(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)

    check_result = _run_cli(
        tmp_path,
        "package",
        "check",
        "--project",
        str(package_root / "pardal.yaml"),
    )
    assert check_result.returncode == 0, check_result.stderr
    assert "package ok: acme/gd32f310-support" in check_result.stdout

    sync_result = _run_cli(
        tmp_path,
        "sync",
        "--project",
        str(package_root / "pardal.yaml"),
    )
    assert sync_result.returncode == 0, sync_result.stderr
    assert "wrote pardal.lock" in sync_result.stdout

    build_result = _run_cli(
        tmp_path,
        "package",
        "build",
        "--project",
        str(package_root / "pardal.yaml"),
    )
    assert build_result.returncode == 0, build_result.stderr
    assert str(package_root / "dist" / "acme-gd32f310-support-0.1.0.tar.gz") in build_result.stdout

    publish_result = _run_cli(
        tmp_path,
        "package",
        "publish",
        "--dry-run",
        "--project",
        str(package_root / "pardal.yaml"),
    )
    assert publish_result.returncode == 0, publish_result.stderr
    assert "publish dry-run ok" in publish_result.stdout
    assert str(package_root / "dist" / "acme-gd32f310-support-0.1.0.tar.gz") in publish_result.stdout

    registry_index = tmp_path / "empty-registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages: {}
""",
        encoding="utf-8",
    )
    registry_publish_result = _run_cli(
        tmp_path,
        "package",
        "publish",
        "--dry-run",
        "--registry-index",
        str(registry_index),
        "--project",
        str(package_root / "pardal.yaml"),
    )
    assert registry_publish_result.returncode == 0, registry_publish_result.stderr
    assert "publish dry-run ok" in registry_publish_result.stdout

    upload_result = _run_cli(
        tmp_path,
        "package",
        "publish",
        "--project",
        str(package_root / "pardal.yaml"),
        "--registry-index",
        str(registry_index),
    )
    assert upload_result.returncode == 0, upload_result.stderr
    assert f"published to {registry_index}" in upload_result.stdout
    payload = yaml.safe_load(registry_index.read_text(encoding="utf-8"))
    assert "0.1.0" in payload["packages"]["acme/gd32f310-support"]["versions"]


def test_cli_project_provenance_writes_resolution_artifacts(tmp_path: Path) -> None:
    contract_path = _write_minimal_required_contract(tmp_path)
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
        source_contract=contract_path,
    )
    sync_project(project)
    output_dir = tmp_path / "provenance-out"

    result = _run_cli(
        tmp_path,
        "project",
        "provenance",
        "--project",
        str(project),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stderr
    package_payload = json.loads((output_dir / "package-resolution.json").read_text(encoding="utf-8"))
    profile_payload = json.loads((output_dir / "profile-resolution.json").read_text(encoding="utf-8"))
    assert package_payload["schema"] == "pardal.package_resolution/v1"
    assert profile_payload["package_profiles"]["expanded"] == [
        "acme/gd32f310-support:gd32_12v_input",
        "pardal/core:analog_rc_filters",
        "acme/gd32f310-support:gd32_adc_frontend",
        "acme/gd32f310-support:gd32f310_adc_12v",
    ]


def test_cli_project_provenance_production_requires_lock(tmp_path: Path) -> None:
    project = _write_board_project_with_canonical_packages(
        tmp_path,
        profiles=[],
    )
    output_dir = tmp_path / "provenance-out"

    missing_lock = _run_cli(
        tmp_path,
        "project",
        "provenance",
        "--project",
        str(project),
        "--output-dir",
        str(output_dir),
        "--production",
    )

    assert missing_lock.returncode == 1
    assert "project.lock_required" in missing_lock.stderr
    assert not (output_dir / "package-resolution.json").exists()

    sync_project(project)
    locked = _run_cli(
        tmp_path,
        "project",
        "provenance",
        "--project",
        str(project),
        "--output-dir",
        str(output_dir),
        "--production",
    )

    assert locked.returncode == 0, locked.stderr
    assert (output_dir / "package-resolution.json").exists()
    assert (output_dir / "profile-resolution.json").exists()


def test_sync_installs_registry_dependency_from_static_index(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )

    result = sync_project(project, registry_index=registry_index)
    ctx = create_project_context(project)

    assert result.lock.packages["acme/gd32f310-support"].type == "registry"
    assert result.lock.packages["acme/gd32f310-support"].release == "0.1.0"
    assert "acme/gd32f310-support:gd32f310_adc_12v" in ctx.package_index.profiles_by_id


def test_sync_rejects_registry_archive_manifest_version_mismatch(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.2.0",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.2.0"],
    )

    with pytest.raises(ProjectConfigError, match="registry.version_mismatch") as exc_info:
        sync_project(project, registry_index=registry_index)

    assert exc_info.value.diagnostic.field == "project.version"


def test_sync_rejects_invalid_registry_package_key(tmp_path: Path) -> None:
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        """
schema: pardal.registry/v1
packages:
  InvalidPackage:
    versions: {}
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="registry.package_id_invalid"):
        sync_project(project, registry_index=registry_index)


def test_sync_unversioned_registry_dependency_selects_latest_semver(
    tmp_path: Path,
) -> None:
    package_v09 = tmp_path / "gd32_pkg_09"
    package_v10 = tmp_path / "gd32_pkg_10"
    package_v09.mkdir()
    package_v10.mkdir()
    _write_package_fixture(package_v09)
    _write_package_fixture(package_v10)
    for package_root, version in ((package_v09, "0.9.0"), (package_v10, "0.10.0")):
        manifest_path = package_root / "pardal.yaml"
        manifest_path.write_text(
            manifest_path.read_text(encoding="utf-8").replace(
                "version: 0.1.0",
                f"version: {version}",
            ),
            encoding="utf-8",
        )
    build_v09 = _build_synced_package(package_v09 / "pardal.yaml", output_dir=tmp_path / "registry")
    build_v10 = _build_synced_package(package_v10 / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.9.0:
        url: {build_v09.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(build_v09.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
      0.10.0:
        url: {build_v10.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(build_v10.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )

    result = sync_project(project, registry_index=registry_index)

    assert result.lock.packages["acme/gd32f310-support"].release == "0.10.0"


def test_sync_unversioned_registry_dependency_preserves_locked_release(
    tmp_path: Path,
) -> None:
    package_v10 = tmp_path / "gd32_pkg_10"
    package_v11 = tmp_path / "gd32_pkg_11"
    package_v10.mkdir()
    package_v11.mkdir()
    _write_package_fixture(package_v10)
    _write_package_fixture(package_v11)
    for package_root, version in ((package_v10, "0.10.0"), (package_v11, "0.11.0")):
        manifest_path = package_root / "pardal.yaml"
        manifest_path.write_text(
            manifest_path.read_text(encoding="utf-8").replace(
                "version: 0.1.0",
                f"version: {version}",
            ),
            encoding="utf-8",
        )
    build_v10 = _build_synced_package(package_v10 / "pardal.yaml", output_dir=tmp_path / "registry")
    build_v11 = _build_synced_package(package_v11 / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.10.0:
        url: {build_v10.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(build_v10.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )
    sync_project(project, registry_index=registry_index)
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.10.0:
        url: {build_v10.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(build_v10.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
      0.11.0:
        url: {build_v11.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(build_v11.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
""",
        encoding="utf-8",
    )

    sync_result = sync_project(project, registry_index=registry_index)
    update_result = update_lock(
        project,
        package_id="acme/gd32f310-support",
        registry_index=registry_index,
    )

    assert sync_result.lock.packages["acme/gd32f310-support"].release == "0.10.0"
    assert update_result.lock.packages["acme/gd32f310-support"].release == "0.11.0"


def test_sync_unversioned_registry_dependency_skips_yanked_latest(
    tmp_path: Path,
) -> None:
    package_v09 = tmp_path / "gd32_pkg_09"
    package_v10 = tmp_path / "gd32_pkg_10"
    package_v09.mkdir()
    package_v10.mkdir()
    _write_package_fixture(package_v09)
    _write_package_fixture(package_v10)
    for package_root, version in ((package_v09, "0.9.0"), (package_v10, "0.10.0")):
        manifest_path = package_root / "pardal.yaml"
        manifest_path.write_text(
            manifest_path.read_text(encoding="utf-8").replace(
                "version: 0.1.0",
                f"version: {version}",
            ),
            encoding="utf-8",
        )
    build_v09 = _build_synced_package(package_v09 / "pardal.yaml", output_dir=tmp_path / "registry")
    build_v10 = _build_synced_package(package_v10 / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.9.0:
        url: {build_v09.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(build_v09.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
      0.10.0:
        url: {build_v10.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(build_v10.archive_path)}
        yanked: true
        requires_pardal: "^0.1.0"
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )

    result = sync_project(project, registry_index=registry_index)

    assert result.lock.packages["acme/gd32f310-support"].release == "0.9.0"


def test_sync_unversioned_registry_dependency_fails_when_all_releases_yanked(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
        yanked=True,
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support"],
    )

    with pytest.raises(ProjectConfigError, match="registry.release_yanked"):
        sync_project(project, registry_index=registry_index)


def test_sync_rejects_invalid_registry_version_key_for_explicit_dependency(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.1.0:
        url: {package_build.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(package_build.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
      latest:
        url: {package_build.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(package_build.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="registry.version_invalid"):
        sync_project(project, registry_index=registry_index)


def test_sync_rejects_registry_dependency_version_conflict(tmp_path: Path) -> None:
    package_v1 = tmp_path / "gd32_pkg_v1"
    package_v2 = tmp_path / "gd32_pkg_v2"
    package_v1.mkdir()
    package_v2.mkdir()
    _write_package_fixture(package_v1)
    _write_package_fixture(package_v2)
    manifest_v2 = package_v2 / "pardal.yaml"
    manifest_v2.write_text(
        manifest_v2.read_text(encoding="utf-8").replace("version: 0.1.0", "version: 0.2.0"),
        encoding="utf-8",
    )
    build_v1 = _build_synced_package(package_v1 / "pardal.yaml", output_dir=tmp_path / "registry")
    build_v2 = _build_synced_package(package_v2 / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.1.0:
        url: {build_v1.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(build_v1.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
      0.2.0:
        url: {build_v2.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(build_v2.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=[
            "acme/gd32f310-support@0.1.0",
            "acme/gd32f310-support@0.2.0",
        ],
    )

    with pytest.raises(ProjectConfigError, match="requested release '0.2.0'"):
        sync_project(project, registry_index=registry_index)


def test_registry_hash_mismatch_fails(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
        sha256="sha256:" + "0" * 64,
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="registry.hash_mismatch"):
        sync_project(project, registry_index=registry_index)


def test_registry_archive_rejects_symlinks(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    archive = tmp_path / "registry" / "acme-gd32f310-support-0.1.0.tar.gz"
    archive.parent.mkdir()
    with tarfile.open(archive, "w:gz") as package_archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                package_archive.add(
                    path,
                    arcname=path.relative_to(package_root).as_posix(),
                )
        symlink = tarfile.TarInfo("linked-pardal.yaml")
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = "pardal.yaml"
        package_archive.addfile(symlink)
    registry_index = _write_registry_index(
        tmp_path,
        archive=archive,
        identifier="acme/gd32f310-support",
        version="0.1.0",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="registry.archive_unsafe") as exc_info:
        sync_project(project, registry_index=registry_index)

    assert exc_info.value.diagnostic.field == "linked-pardal.yaml"


def test_registry_archive_rejects_hardlinks(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    archive = tmp_path / "registry" / "acme-gd32f310-support-0.1.0.tar.gz"
    archive.parent.mkdir()
    with tarfile.open(archive, "w:gz") as package_archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                package_archive.add(
                    path,
                    arcname=path.relative_to(package_root).as_posix(),
                )
        hardlink = tarfile.TarInfo("hardlinked-pardal.yaml")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "pardal.yaml"
        package_archive.addfile(hardlink)
    registry_index = _write_registry_index(
        tmp_path,
        archive=archive,
        identifier="acme/gd32f310-support",
        version="0.1.0",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="registry.archive_unsafe") as exc_info:
        sync_project(project, registry_index=registry_index)

    assert exc_info.value.diagnostic.field == "hardlinked-pardal.yaml"


def test_registry_http_archive_install_verifies_hash(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        archive_url = (
            f"http://127.0.0.1:{server.server_port}/"
            f"{package_build.archive_path.relative_to(tmp_path).as_posix()}"
        )
        registry_index = tmp_path / "registry.yaml"
        registry_index.write_text(
            f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.1.0:
        url: {archive_url}
        sha256: sha256:{_sha256(package_build.archive_path)}
        yanked: false
        requires_pardal: "^0.1.0"
""",
            encoding="utf-8",
        )
        project = _write_board_project(
            tmp_path,
            dependencies=["acme/gd32f310-support@0.1.0"],
        )

        result = sync_project(project, registry_index=registry_index)

        assert result.lock.packages["acme/gd32f310-support"].release == "0.1.0"
        assert (tmp_path / ".pardal/packages/acme/gd32f310-support/pardal.yaml").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_registry_release_sha256_must_be_digest_shape(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
        sha256="sha256:not-a-real-digest",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="registry.release_sha256_invalid"):
        sync_project(project, registry_index=registry_index)


def test_yanked_registry_release_fails_for_new_sync(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
        yanked=True,
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="registry.release_yanked"):
        sync_project(project, registry_index=registry_index)


def test_registry_release_yanked_must_be_boolean(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.1.0:
        url: {package_build.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(package_build.archive_path)}
        yanked: "false"
        requires_pardal: "^0.1.0"
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="registry.release_yanked_invalid"):
        sync_project(project, registry_index=registry_index)


def test_yanked_registry_release_can_reinstall_from_existing_lock(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )
    sync_project(project, registry_index=registry_index)
    shutil.rmtree(tmp_path / ".pardal" / "packages" / "acme" / "gd32f310-support")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
        yanked=True,
    )

    result = sync_project(project, registry_index=registry_index)

    assert result.lock.packages["acme/gd32f310-support"].release == "0.1.0"
    assert (tmp_path / ".pardal/packages/acme/gd32f310-support/pardal.yaml").exists()


def test_unversioned_yanked_registry_release_can_reinstall_from_existing_lock(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support"],
    )
    sync_project(project, registry_index=registry_index)
    shutil.rmtree(tmp_path / ".pardal" / "packages" / "acme" / "gd32f310-support")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
        yanked=True,
    )

    result = sync_project(project, registry_index=registry_index)

    assert result.lock.packages["acme/gd32f310-support"].release == "0.1.0"
    assert (tmp_path / ".pardal/packages/acme/gd32f310-support/pardal.yaml").exists()


def test_registry_release_requires_compatible_pardal(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
        requires_pardal="^0.2.0",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="manifest.requires_pardal_incompatible"):
        sync_project(project, registry_index=registry_index)


def test_registry_release_requires_pardal_must_be_string(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = tmp_path / "registry.yaml"
    registry_index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  acme/gd32f310-support:
    versions:
      0.1.0:
        url: {package_build.archive_path.relative_to(tmp_path).as_posix()}
        sha256: sha256:{_sha256(package_build.archive_path)}
        yanked: false
        requires_pardal: 1
""",
        encoding="utf-8",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="registry.release_requires_pardal_invalid"):
        sync_project(project, registry_index=registry_index)


def test_registry_release_requires_pardal_invalid_range_reports_registry_field(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
        requires_pardal="next",
    )
    project = _write_board_project(
        tmp_path,
        dependencies=["acme/gd32f310-support@0.1.0"],
    )

    with pytest.raises(ProjectConfigError, match="manifest.requires_pardal_invalid") as exc_info:
        sync_project(project, registry_index=registry_index)

    assert exc_info.value.diagnostic.path == registry_index
    assert (
        exc_info.value.diagnostic.field
        == "packages.acme/gd32f310-support.versions.0.1.0.requires_pardal"
    )


def test_cli_add_registry_dependency_with_static_index(tmp_path: Path) -> None:
    package_root = tmp_path / "gd32_pkg"
    package_root.mkdir()
    _write_package_fixture(package_root)
    package_build = _build_synced_package(package_root / "pardal.yaml", output_dir=tmp_path / "registry")
    registry_index = _write_registry_index(
        tmp_path,
        archive=package_build.archive_path,
        identifier="acme/gd32f310-support",
        version="0.1.0",
    )
    project = _write_board_project(tmp_path, dependencies=[])

    add_result = _run_cli(
        tmp_path,
        "add",
        "acme/gd32f310-support@0.1.0",
        "--project",
        str(project),
        "--registry-index",
        str(registry_index),
    )

    assert add_result.returncode == 0, add_result.stderr
    assert "installed acme/gd32f310-support" in add_result.stdout
    assert (tmp_path / ".pardal/packages/acme/gd32f310-support/pardal.yaml").exists()


def test_sync_installs_git_dependency_and_locks_commit(tmp_path: Path) -> None:
    repo_root = tmp_path / "repos" / "acme" / "gd32f310-support"
    repo_root.mkdir(parents=True)
    _write_package_fixture(repo_root)
    commit = _init_git_repo(repo_root)
    project = _write_board_project(
        tmp_path,
        dependencies=[f"git://{repo_root.as_posix()}#{commit}"],
        profiles=["acme/gd32f310-support:gd32f310_adc_12v"],
    )

    result = sync_project(project)
    ctx = create_project_context(project)

    locked = result.lock.packages["acme/gd32f310-support"]
    assert locked.type == "git"
    assert locked.repo == repo_root.as_posix()
    assert locked.ref == commit
    assert locked.commit == commit
    assert "acme/gd32f310-support:gd32f310_adc_12v" in ctx.package_index.profiles_by_id
    assert not (tmp_path / ".pardal/packages/acme/gd32f310-support/.git").exists()


def test_sync_installs_git_dependency_from_subdirectory(tmp_path: Path) -> None:
    repo_root = tmp_path / "repos" / "acme" / "monorepo"
    package_root = repo_root / "packages" / "gd32"
    package_root.mkdir(parents=True)
    _write_package_fixture(package_root)
    commit = _init_git_repo(repo_root)
    project = _write_board_project(
        tmp_path,
        dependencies=[f"git://{repo_root.as_posix()}#{commit}:packages/gd32"],
    )

    result = sync_project(project)
    ctx = create_project_context(project)

    locked = result.lock.packages["acme/gd32f310-support"]
    lock_payload = yaml.safe_load((tmp_path / "pardal.lock").read_text(encoding="utf-8"))
    resolution = package_resolution_for_context(ctx)
    assert locked.type == "git"
    assert locked.commit == commit
    assert locked.path_within_repo == "packages/gd32"
    assert lock_payload["packages"]["acme/gd32f310-support"]["path"] == "packages/gd32"
    assert resolution["lock"]["packages"]["acme/gd32f310-support"]["path"] == "packages/gd32"
    assert (tmp_path / ".pardal/packages/acme/gd32f310-support/pardal.yaml").exists()
    assert not (tmp_path / ".pardal/packages/acme/gd32f310-support/.git").exists()


def test_sync_rejects_git_dependency_ref_conflict(tmp_path: Path) -> None:
    repo_root = tmp_path / "repos" / "acme" / "gd32f310-support"
    repo_root.mkdir(parents=True)
    _write_package_fixture(repo_root)
    first_commit = _init_git_repo(repo_root)
    (repo_root / "profiles" / "extra.yaml").write_text(
        """
schema: pardal.profile/v1
profiles:
  extra:
    enable_checks: []
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True, stdout=subprocess.PIPE)
    subprocess.run(
        ["git", "commit", "-m", "extra profile"],
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
    )
    second_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
    ).strip()
    project = _write_board_project(
        tmp_path,
        dependencies=[
            f"git://{repo_root.as_posix()}#{first_commit}",
            f"git://{repo_root.as_posix()}#{second_commit}",
        ],
    )

    with pytest.raises(ProjectConfigError, match="requested ref"):
        sync_project(project)


def test_sync_rejects_git_dependency_subdirectory_conflict(tmp_path: Path) -> None:
    repo_root = tmp_path / "repos" / "acme" / "monorepo"
    package_a = repo_root / "packages" / "a"
    package_b = repo_root / "packages" / "b"
    package_a.mkdir(parents=True)
    package_b.mkdir(parents=True)
    _write_package_fixture(package_a)
    _write_package_fixture(package_b)
    commit = _init_git_repo(repo_root)
    project = _write_board_project(
        tmp_path,
        dependencies=[
            f"git://{repo_root.as_posix()}#{commit}:packages/a",
            f"git://{repo_root.as_posix()}#{commit}:packages/b",
        ],
    )

    with pytest.raises(ProjectConfigError, match="requested path"):
        sync_project(project)


def test_sync_installs_development_git_dependency_without_ref_and_locks_commit(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repos" / "acme" / "gd32f310-support"
    repo_root.mkdir(parents=True)
    _write_package_fixture(repo_root)
    commit = _init_git_repo(repo_root)
    project = _write_board_project(tmp_path, dependencies=[f"git://{repo_root.as_posix()}"])

    sync_project(project)

    lock = load_lock_file(tmp_path / "pardal.lock")
    locked = lock.packages["acme/gd32f310-support"]
    assert locked.ref is None
    assert locked.commit == commit
    assert (tmp_path / ".pardal/packages/acme/gd32f310-support/pardal.yaml").exists()


def test_create_package_project_outputs_checkable_package(tmp_path: Path) -> None:
    result = create_package_project("acme/new-support", output_dir=tmp_path / "new-support")

    manifest = load_project_manifest(result.manifest_path)
    report = check_package(result.manifest_path)

    assert manifest.project.identifier == "acme/new-support"
    assert manifest.raw["trust"]["python_checks"] is True
    assert report.exports
    assert (result.root / "profiles/default.yaml").exists()
    assert (result.root / "checks/default.py").exists()
    assert (result.root / "parts/parts.yaml").exists()
    assert (result.root / "footprints/footprints.yaml").exists()
    assert (result.root / "physical_libraries/libraries.yaml").exists()
    assert (result.root / "routing/policies.yaml").exists()
    assert (result.root / "templates.yaml").exists()
    assert (result.root / "examples.yaml").exists()
    assert (result.root / "templates/starter/pardal.yaml").exists()
    profile_payload = yaml.safe_load(
        (result.root / "profiles/default.yaml").read_text(encoding="utf-8")
    )
    check_source = (result.root / "checks/default.py").read_text(encoding="utf-8")
    assert profile_payload["profiles"]["default"]["enable_checks"] == [
        "acme/new-support:default"
    ]
    assert 'id="acme/new-support:default"' in check_source
    template_manifest = load_project_manifest(result.root / "templates/starter/pardal.yaml")
    assert template_manifest.dependencies == ()
    assert {export.kind for export in report.exports} == {
        "profiles",
        "checks",
        "parts",
        "footprints",
        "physical_libraries",
        "route_policies",
        "board_templates",
        "examples",
    }

    board = create_board_project(
        "starter_board",
        output_dir=tmp_path / "starter_board",
        template="acme/new-support:starter",
        package_root=result.root,
    )
    board_manifest = load_project_manifest(board.manifest_path)

    assert board_manifest.builds["default"].profiles == ("acme/new-support:default",)
    assert board_manifest.dependencies[0].type == "file"
    assert board_manifest.dependencies[0].path == Path("../new-support")
    assert (board.root / "boards/new-support_starter.pardal.yaml").exists()


def test_create_board_project_outputs_default_board(tmp_path: Path) -> None:
    result = create_board_project("my_board", output_dir=tmp_path / "my_board")

    manifest = load_project_manifest(result.manifest_path)

    assert manifest.project.type == "board"
    assert manifest.project.name == "my_board"
    assert manifest.builds["default"].entry == Path("boards/my_board.pardal.yaml")
    assert (result.root / "boards/my_board.pardal.yaml").exists()


def test_cli_create_project_outputs_default_board_project(tmp_path: Path) -> None:
    result = _run_cli(
        tmp_path,
        "create",
        "project",
        "cli_project",
        "--output-dir",
        str(tmp_path / "cli_project"),
    )

    manifest = load_project_manifest(tmp_path / "cli_project/pardal.yaml")

    assert result.returncode == 0, result.stderr
    assert manifest.project.type == "board"
    assert manifest.project.name == "cli_project"
    assert manifest.builds["default"].entry == Path("boards/cli_project.pardal.yaml")
    assert (tmp_path / "cli_project/boards/cli_project.pardal.yaml").exists()


def test_create_board_from_local_template_is_editable_project(tmp_path: Path) -> None:
    package_root = Path(__file__).resolve().parents[1] / "examples/packages/gd32f310-support"
    result = create_board_project(
        "gd32_board",
        output_dir=tmp_path / "gd32_board",
        template="acme/gd32f310-support:gd32f310_12v_adc",
        package_root=package_root,
    )

    manifest = load_project_manifest(result.manifest_path)

    assert manifest.project.type == "board"
    assert manifest.builds["default"].profiles == (
        "acme/gd32f310-support:gd32f310_adc_12v",
    )
    assert manifest.dependencies[0].type == "file"
    assert (result.root / manifest.dependencies[0].path).resolve() == package_root.resolve()
    assert manifest.dependencies[1].type == "registry"
    assert manifest.dependencies[1].identifier == "jlcpcb/lcsc"
    assert (result.root / "boards/gd32f310_12v_adc.pardal.yaml").exists()


def test_create_board_from_template_wraps_malformed_template_manifest(
    tmp_path: Path,
) -> None:
    package_root = create_package_project(
        "acme/new-support",
        output_dir=tmp_path / "template_pkg",
    ).root
    (package_root / "templates" / "starter" / "pardal.yaml").write_text(
        "schema: [\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="manifest.yaml_invalid") as exc_info:
        create_board_project(
            "broken_template_board",
            output_dir=tmp_path / "broken_template_board",
            template="acme/new-support:starter",
            package_root=package_root,
        )

    assert exc_info.value.diagnostic.path == tmp_path / "broken_template_board" / "pardal.yaml"
    assert exc_info.value.diagnostic.field == "yaml"


def test_create_board_from_template_rejects_source_symlink(tmp_path: Path) -> None:
    package_root = tmp_path / "template_pkg"
    create_package_project("acme/template-support", output_dir=package_root)
    template_root = package_root / "templates" / "starter"
    (template_root / "linked.yaml").symlink_to("pardal.yaml")

    with pytest.raises(ProjectConfigError, match="create.template_source_unsafe"):
        create_board_project(
            "template_board",
            output_dir=tmp_path / "template_board",
            template="acme/template-support:starter",
            package_root=package_root,
        )

    assert not (tmp_path / "template_board" / "linked.yaml").exists()


def test_create_board_from_template_rejects_source_hardlink(tmp_path: Path) -> None:
    package_root = tmp_path / "template_pkg"
    create_package_project("acme/template-support", output_dir=package_root)
    template_root = package_root / "templates" / "starter"
    os.link(template_root / "pardal.yaml", template_root / "hardlinked.yaml")

    with pytest.raises(ProjectConfigError, match="create.template_source_unsafe"):
        create_board_project(
            "template_board",
            output_dir=tmp_path / "template_board",
            template="acme/template-support:starter",
            package_root=package_root,
        )

    assert not (tmp_path / "template_board" / "hardlinked.yaml").exists()


def test_create_board_from_installed_template_uses_registry_dependency(tmp_path: Path) -> None:
    package_source = Path(__file__).resolve().parents[1] / "examples/packages/gd32f310-support"
    install_root = tmp_path / ".pardal" / "packages"
    installed_root = install_root / "acme" / "gd32f310-support"
    shutil.copytree(package_source, installed_root)

    result = create_board_project(
        "gd32_board",
        output_dir=tmp_path / "gd32_board",
        template="acme/gd32f310-support:gd32f310_12v_adc",
        package_install_root=install_root,
    )

    manifest = load_project_manifest(result.manifest_path)

    assert manifest.dependencies[0].type == "registry"
    assert {dependency.identifier for dependency in manifest.dependencies} == {
        "acme/gd32f310-support",
        "jlcpcb/lcsc",
    }
    assert manifest.dependencies[0].path is None
    assert (result.root / "boards/gd32f310_12v_adc.pardal.yaml").exists()


def test_cli_create_package_and_board_from_template(tmp_path: Path) -> None:
    package_result = _run_cli(
        tmp_path,
        "create",
        "package",
        "acme/cli-support",
        "--output-dir",
        str(tmp_path / "cli-support"),
    )
    assert package_result.returncode == 0, package_result.stderr
    assert (tmp_path / "cli-support/pardal.yaml").exists()

    package_root = Path(__file__).resolve().parents[1] / "examples/packages/gd32f310-support"
    board_result = _run_cli(
        tmp_path,
        "create",
        "board",
        "cli_board",
        "--output-dir",
        str(tmp_path / "cli_board"),
        "--template",
        "acme/gd32f310-support:gd32f310_12v_adc",
        "--package-root",
        str(package_root),
    )
    assert board_result.returncode == 0, board_result.stderr
    cli_board_manifest = load_project_manifest(tmp_path / "cli_board/pardal.yaml")
    assert cli_board_manifest.dependencies[0].type == "file"
    assert (
        tmp_path / "cli_board" / cli_board_manifest.dependencies[0].path
    ).resolve() == package_root.resolve()
    assert (tmp_path / "cli_board/boards/gd32f310_12v_adc.pardal.yaml").exists()

    install_root = tmp_path / ".pardal" / "packages"
    installed_root = install_root / "acme" / "gd32f310-support"
    shutil.copytree(package_root, installed_root)
    installed_board_result = _run_cli(
        tmp_path,
        "create",
        "board",
        "cli_installed_board",
        "--output-dir",
        str(tmp_path / "cli_installed_board"),
        "--template",
        "acme/gd32f310-support:gd32f310_12v_adc",
        "--package-install-root",
        str(install_root),
    )
    assert installed_board_result.returncode == 0, installed_board_result.stderr
    installed_manifest = load_project_manifest(
        tmp_path / "cli_installed_board/pardal.yaml"
    )
    assert installed_manifest.dependencies[0].type == "registry"
    assert {dependency.identifier for dependency in installed_manifest.dependencies} == {
        "acme/gd32f310-support",
        "jlcpcb/lcsc",
    }


def test_canonical_package_fixtures_pass_package_check() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixtures = [
        repo_root / "examples/packages/pardal-core/pardal.yaml",
        repo_root / "examples/packages/jlcpcb-lcsc/pardal.yaml",
        repo_root / "examples/packages/gd32f310-support/pardal.yaml",
    ]

    for fixture in fixtures:
        report = check_package(fixture)
        assert report.exports, fixture


def _write_package_fixture(root: Path) -> None:
    (root / "profiles").mkdir()
    (root / "parts").mkdir()
    (root / "footprints").mkdir()
    (root / "checks").mkdir()
    (root / "templates" / "starter").mkdir(parents=True)
    (root / "pardal.yaml").write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: package
  identifier: acme/gd32f310-support
  version: 0.1.0
  repository: https://github.com/acme/gd32f310-support
  summary: GD32 support
  license: MIT
  authors:
    - name: Hardware
trust:
  python_checks: true
exports:
  profiles:
    - profiles/
  parts:
    - parts/
  footprints:
    - footprints/
  checks:
    - checks/gd32f310.py
  examples:
    - examples.yaml
""",
        encoding="utf-8",
    )
    (root / "profiles" / "gd32.yaml").write_text(
        """
schema: pardal.profile/v1
profiles:
  gd32f310_adc_12v:
    enable_checks:
      - gd32.adc_frontend
""",
        encoding="utf-8",
    )
    (root / "parts" / "gd32.yaml").write_text(
        """
schema: pardal.parts/v1
parts:
  GD32F310K8T6:
    manufacturer: GigaDevice
    mpn: GD32F310K8T6
    footprint: acme/gd32f310-support:gd32f310_lqfp32
""",
        encoding="utf-8",
    )
    (root / "footprints" / "gd32.yaml").write_text(
        """
schema: pardal.footprints/v1
footprints:
  gd32f310_lqfp32:
    kicad: Package_QFP:LQFP-32_7x7mm_P0.8mm
""",
        encoding="utf-8",
    )
    (root / "checks" / "gd32f310.py").write_text(
        """
from pardal.checks import Severity, Stage, check

@check(id="gd32.adc_frontend", stage=Stage.SOURCE_CONTRACT, default_severity=Severity.INFO)
def gd32_adc_frontend(ctx):
    return []
""",
        encoding="utf-8",
    )
    (root / "examples.yaml").write_text(
        """
schema: pardal.examples/v1
examples:
  starter:
    description: Starter example
    mode: documentation_only
    path: templates/starter
""",
        encoding="utf-8",
    )
    (root / "templates" / "starter" / "pardal.yaml").write_text(
        """
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: starter
builds:
  default:
    entry: boards/starter.pardal.yaml
""",
        encoding="utf-8",
    )


def _write_minimal_package_fixture(
    root: Path,
    *,
    identifier: str,
    profile_name: str,
    dependencies: list[str] | None = None,
) -> None:
    (root / "profiles").mkdir()
    owner, name = identifier.split("/", 1)
    dependency_lines = "\n".join(
        f"  - type: file\n    path: {dependency}"
        for dependency in dependencies or []
    )
    dependency_block = f"dependencies:\n{dependency_lines}\n" if dependency_lines else ""
    (root / "pardal.yaml").write_text(
        f"""
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: package
  identifier: {identifier}
  version: 0.1.0
  repository: https://github.com/{owner}/{name}
  summary: Minimal support
  license: MIT
  authors:
    - name: Hardware
{dependency_block}exports:
  profiles:
    - profiles/
""",
        encoding="utf-8",
    )
    (root / "profiles" / "default.yaml").write_text(
        f"""
schema: pardal.profile/v1
profiles:
  {profile_name}:
    enable_checks: []
""",
        encoding="utf-8",
    )


def _write_helper_check_package(root: Path, *, identifier: str, marker: str) -> None:
    (root / "checks").mkdir()
    (root / "helpers").mkdir()
    owner, name = identifier.split("/", 1)
    root.joinpath("pardal.yaml").write_text(
        f"""
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: package
  identifier: {identifier}
  version: 0.1.0
  repository: https://github.com/{owner}/{name}
  summary: Helper isolation support
  license: MIT
  authors:
    - name: Hardware
trust:
  python_checks: true
exports:
  checks:
    - checks/package_check.py
""",
        encoding="utf-8",
    )
    (root / "helpers" / "__init__.py").write_text("", encoding="utf-8")
    (root / "helpers" / "util.py").write_text(
        f"""
def marker():
    return {marker!r}
""",
        encoding="utf-8",
    )
    (root / "checks" / "package_check.py").write_text(
        f"""
from helpers.util import marker
from pardal.checks import Severity, Stage, check

if marker() != {marker!r}:
    raise RuntimeError("stale helper module")

@check(id="{marker}.package_check", stage=Stage.MANIFEST, default_severity=Severity.INFO)
def package_check(ctx):
    return []
""",
        encoding="utf-8",
    )


def _write_check_only_package_fixture(
    root: Path,
    *,
    identifier: str,
    check_id: str,
    requires_network: bool = False,
) -> None:
    (root / "checks").mkdir()
    owner, name = identifier.split("/", 1)
    root.joinpath("pardal.yaml").write_text(
        f"""
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: package
  identifier: {identifier}
  version: 0.1.0
  repository: https://github.com/{owner}/{name}
  summary: Check support
  license: MIT
  authors:
    - name: Hardware
trust:
  python_checks: true
exports:
  checks:
    - checks/package_check.py
""",
        encoding="utf-8",
    )
    (root / "checks" / "package_check.py").write_text(
        f"""
from pardal.checks import Severity, Stage, check

@check(id={check_id!r}, stage=Stage.MANIFEST, default_severity=Severity.INFO, requires_network={requires_network!r})
def package_check(ctx):
    return []
""",
        encoding="utf-8",
    )


def _write_malformed_lock(path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema": "pardal.lock/v1",
                "root": {"project_hash": ["not", "a", "hash"]},
                "packages": {},
            }
        ),
        encoding="utf-8",
    )


def _build_synced_package(
    manifest_path: Path,
    *,
    output_dir: Path | None = None,
):
    sync_project(manifest_path)
    return build_package(manifest_path, output_dir=output_dir)


def _write_part_only_package_fixture(
    root: Path,
    *,
    identifier: str,
    part_name: str,
) -> None:
    (root / "parts").mkdir(parents=True)
    owner, name = identifier.split("/", 1)
    root.joinpath("pardal.yaml").write_text(
        f"""
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: package
  identifier: {identifier}
  version: 0.1.0
  repository: https://github.com/{owner}/{name}
  summary: Alternate parts
  license: MIT
  authors:
    - name: Hardware
exports:
  parts:
    - parts/
""",
        encoding="utf-8",
    )
    root.joinpath("parts", "parts.yaml").write_text(
        f"""
schema: pardal.parts/v1
parts:
  {part_name}:
    manufacturer: Alternate
    mpn: {part_name}
    lcsc: C000001
""",
        encoding="utf-8",
    )


def _replace_package_profiles(root: Path, content: str) -> None:
    (root / "profiles" / "gd32.yaml").write_text(content, encoding="utf-8")


def _replace_minimal_package_profile(
    root: Path,
    *,
    profile_name: str,
    enable_checks: list[str],
) -> None:
    check_lines = "\n".join(f"      - {check_id}" for check_id in enable_checks)
    (root / "profiles" / "default.yaml").write_text(
        f"""
schema: pardal.profile/v1
profiles:
  {profile_name}:
    enable_checks:
{check_lines}
""",
        encoding="utf-8",
    )




def _write_board_project(
    root: Path,
    *,
    dependencies: list[str],
    profiles: list[str] | None = None,
    source_contract: str | None = None,
) -> Path:
    dependency_lines = "\n".join(f"  - {dependency}" for dependency in dependencies)
    dependency_block = f"dependencies:\n{dependency_lines}\n" if dependencies else ""
    profile_lines = "\n".join(f"      - {profile}" for profile in profiles or [])
    profile_block = f"    profiles:\n{profile_lines}\n" if profiles else ""
    contract_block = f"    source_contract: {source_contract}\n" if source_contract else ""
    manifest = root / "pardal.yaml"
    manifest.write_text(
        f"""
schema: pardal.project/v1
requires-pardal: "^0.1.0"
project:
  type: board
  name: sample
{dependency_block}builds:
  default:
    entry: boards/main.pardal.yaml
{contract_block}{profile_block}""",
        encoding="utf-8",
    )
    return manifest


def _write_board_project_with_canonical_packages(
    root: Path,
    *,
    profiles: list[str],
    source_contract: str | None = None,
) -> Path:
    source_root = Path(__file__).resolve().parents[1] / "examples" / "packages"
    deps_root = root / "deps"
    deps_root.mkdir(exist_ok=True)
    dependencies: list[str] = []
    for package_name in ("pardal-core", "jlcpcb-lcsc", "gd32f310-support"):
        target = deps_root / package_name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source_root / package_name, target)
        dependencies.append(f"file://deps/{package_name}")
    return _write_board_project(
        root,
        dependencies=dependencies,
        profiles=profiles,
        source_contract=source_contract,
    )


def _write_minimal_required_contract(root: Path) -> str:
    contracts = root / "contracts"
    contracts.mkdir(exist_ok=True)
    contract = contracts / "required.contract.yaml"
    contract.write_text(
        """
schema: pardal.source_contract/v1
supply_rails:
  3V3:
    voltage: 3.3 V
adc_frontends:
  ADC0:
    net: SENSE_0
    resistor: R1
    capacitor: C1
""",
        encoding="utf-8",
    )
    return "contracts/required.contract.yaml"


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(repo_root)
        if not existing_pythonpath
        else f"{repo_root}{os.pathsep}{existing_pythonpath}"
    )
    return subprocess.run(
        [sys.executable, "-m", "pardal.cli", *args],
        cwd=cwd,
        check=False,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _write_registry_index(
    root: Path,
    *,
    archive: Path,
    identifier: str,
    version: str,
    sha256: str | None = None,
    yanked: bool = False,
    requires_pardal: str = "^0.1.0",
) -> Path:
    digest = sha256 or "sha256:" + _sha256(archive)
    index = root / "registry.yaml"
    index.write_text(
        f"""
schema: pardal.registry/v1
packages:
  {identifier}:
    versions:
      {version}:
        url: {archive.relative_to(root).as_posix()}
        sha256: {digest}
        yanked: {"true" if yanked else "false"}
        requires_pardal: "{requires_pardal}"
""",
        encoding="utf-8",
    )
    return index


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _file_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _init_git_repo(path: Path) -> str:
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
