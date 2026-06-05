from __future__ import annotations

import re
import shutil
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pardal.packages.exports import scan_package_exports
from pardal.packages.source_safety import check_package_source_members
from pardal.packages.templates import BoardTemplateDefinition, load_board_template_export
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.manifest import PACKAGE_ID_RE, load_project_manifest
from pardal.project.yaml import load_yaml_file

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class CreateResult:
    root: Path
    manifest_path: Path


def create_package_project(identifier: str, output_dir: Path | str | None = None) -> CreateResult:
    if not PACKAGE_ID_RE.match(identifier):
        raise ProjectConfigError(
            "create.package_identifier_invalid",
            "package identifier must match owner/name",
        )
    owner, name = identifier.split("/", 1)
    root = Path(output_dir) if output_dir is not None else Path(name)
    _ensure_new_directory(root)
    (root / "profiles").mkdir(parents=True)
    (root / "checks").mkdir()
    (root / "parts").mkdir()
    (root / "footprints").mkdir()
    (root / "physical_libraries").mkdir()
    (root / "routing").mkdir()
    (root / "templates" / "starter").mkdir(parents=True)
    (root / "examples").mkdir()
    (root / "pardal.yaml").write_text(
        f"""schema: pardal.project/v1
requires-pardal: "^0.1.0"

project:
  type: package
  identifier: {identifier}
  version: 0.1.0
  repository: https://example.invalid/{owner}/{name}
  summary: {name} Pardal package
  license: MIT
  authors:
    - name: {owner}

trust:
  python_checks: true

exports:
  profiles:
    - profiles/
  checks:
    - checks/
  parts:
    - parts/
  footprints:
    - footprints/
  physical_libraries:
    - physical_libraries/
  route_policies:
    - routing/
  board_templates:
    - templates.yaml
  examples:
    - examples.yaml
""",
        encoding="utf-8",
    )
    (root / "profiles" / "default.yaml").write_text(
        f"""schema: pardal.profile/v1

profiles:
  default:
    enable_checks:
      - {identifier}:default
""",
        encoding="utf-8",
    )
    (root / "checks" / "default.py").write_text(
        f"""from pardal.checks import Severity, Stage, check


@check(id="{identifier}:default", stage=Stage.MANIFEST, default_severity=Severity.INFO)
def default_check(ctx):
    return []
""",
        encoding="utf-8",
    )
    (root / "parts" / "parts.yaml").write_text(
        """schema: pardal.parts/v1

parts:
  placeholder:
    manufacturer: example
    mpn: placeholder
    package: placeholder
    attributes:
      note: replace with a real component definition
""",
        encoding="utf-8",
    )
    (root / "footprints" / "footprints.yaml").write_text(
        """schema: pardal.footprints/v1

footprints:
  placeholder:
    kicad: Connector_Generic:Conn_01x02
    aliases:
      - placeholder
    metadata:
      note: replace with a real footprint mapping
""",
        encoding="utf-8",
    )
    (root / "physical_libraries" / "libraries.yaml").write_text(
        f"""schema: pardal.physical_library/v1

libraries:
  default:
    footprints:
      - {identifier}:placeholder
    netclasses:
      - signal
    metadata:
      note: starter physical library
""",
        encoding="utf-8",
    )
    (root / "routing" / "policies.yaml").write_text(
        """schema: pardal.route_policy/v1

policies:
  default:
    backend: pardal-routing-dsl
    layer_stack: two_layer
    rules:
      signal_width_mm: 0.15
      clearance_mm: 0.15
""",
        encoding="utf-8",
    )
    (root / "templates.yaml").write_text(
        """schema: pardal.templates/v1

templates:
  starter:
    description: Starter board project for this package
    path: templates/starter
""",
        encoding="utf-8",
    )
    (root / "examples.yaml").write_text(
        """schema: pardal.examples/v1

examples:
  starter:
    description: Starter example for this package
    mode: documentation_only
    path: templates/starter
""",
        encoding="utf-8",
    )
    (root / "templates" / "starter" / "pardal.yaml").write_text(
        f"""schema: pardal.project/v1
requires-pardal: "^0.1.0"

project:
  type: board
  name: {name}_starter

builds:
  default:
    entry: boards/{name}_starter.pardal.yaml
    profiles:
      - {identifier}:default
""",
        encoding="utf-8",
    )
    (root / "templates" / "starter" / "boards").mkdir()
    (root / "templates" / "starter" / "boards" / f"{name}_starter.pardal.yaml").write_text(
        f"""source:
  note: starter board for {identifier}
""",
        encoding="utf-8",
    )
    return CreateResult(root=root, manifest_path=root / "pardal.yaml")


def create_board_project(
    name: str,
    output_dir: Path | str | None = None,
    *,
    template: str | None = None,
    package_root: Path | str | None = None,
    package_install_root: Path | str | None = None,
) -> CreateResult:
    if not NAME_RE.match(name):
        raise ProjectConfigError(
            "create.board_name_invalid",
            "board name must match [a-z0-9][a-z0-9_-]*",
        )
    root = Path(output_dir) if output_dir is not None else Path(name)
    _ensure_new_directory(root)
    if template is None:
        (root / "boards").mkdir(parents=True)
        (root / "boards" / f"{name}.pardal.yaml").write_text(
            "source:\n  note: new board placeholder\n",
            encoding="utf-8",
        )
        (root / "pardal.yaml").write_text(
            f"""schema: pardal.project/v1
requires-pardal: "^0.1.0"

project:
  type: board
  name: {name}

builds:
  default:
    entry: boards/{name}.pardal.yaml
""",
            encoding="utf-8",
        )
        return CreateResult(root=root, manifest_path=root / "pardal.yaml")
    package_path, dependency_mode = _resolve_template_package_root(
        template,
        package_root=Path(package_root) if package_root is not None else None,
        package_install_root=(
            Path(package_install_root)
            if package_install_root is not None
            else Path(".pardal/packages")
        ),
    )
    _copy_template_project(
        root,
        template=template,
        package_root=package_path,
        dependency_mode=dependency_mode,
    )
    return CreateResult(root=root, manifest_path=root / "pardal.yaml")


def _copy_template_project(
    destination: Path,
    *,
    template: str,
    package_root: Path,
    dependency_mode: str,
) -> None:
    if ":" not in template:
        raise ProjectConfigError(
            "create.template_id_invalid",
            "template must be OWNER/NAME:TEMPLATE",
        )
    package_id, template_id = template.split(":", 1)
    package_manifest = load_project_manifest(package_root / "pardal.yaml")
    if package_manifest.project.identifier != package_id:
        raise ProjectConfigError(
            "create.template_package_mismatch",
            "template package id does not match package root manifest",
            path=package_manifest.path,
            field="project.identifier",
    )
    template_def = _find_template_definition(package_manifest, template_id)
    source = (package_manifest.root / template_def.template_path).resolve()
    if not _is_inside(source, package_manifest.root.resolve()):
        raise ProjectConfigError(
            "create.template_path_outside",
            "template path must stay inside package root",
            path=package_manifest.path,
        )
    if not (source / "pardal.yaml").exists():
        raise ProjectConfigError(
            "create.template_manifest_missing",
            "template directory must contain pardal.yaml",
            path=source,
        )
    check_package_source_members(source, code="create.template_source_unsafe")
    shutil.copytree(source, destination, dirs_exist_ok=True)
    _ensure_template_dependency(
        destination / "pardal.yaml",
        package_manifest,
        dependency_mode=dependency_mode,
        default_dependencies=template_def.default_dependencies,
    )


def _resolve_template_package_root(
    template: str,
    *,
    package_root: Path | None,
    package_install_root: Path,
) -> tuple[Path, str]:
    if ":" not in template:
        raise ProjectConfigError(
            "create.template_id_invalid",
            "template must be OWNER/NAME:TEMPLATE",
        )
    package_id, _template_id = template.split(":", 1)
    if package_root is not None:
        return package_root, "file"
    installed = package_install_root / package_id / "pardal.yaml"
    if not installed.exists():
        raise ProjectConfigError(
            "create.template_package_missing",
            "template package is not installed; run pardal sync or pass --package-root",
            path=installed,
        )
    return installed.parent, "registry"


def _find_template_definition(
    package_manifest,
    template_id: str,
) -> BoardTemplateDefinition:
    for export in scan_package_exports(package_manifest):
        if export.kind != "board_templates" or not export.id.endswith(f":{template_id}"):
            continue
        template = load_board_template_export(export).get(f"{export.package_id}:{template_id}")
        if template is not None:
            return template
    raise ProjectConfigError(
        "create.template_unknown",
        f"unknown template {template_id!r}",
        path=package_manifest.path,
        field="exports.board_templates",
    )


def _ensure_template_dependency(
    manifest_path: Path,
    package_manifest,
    *,
    dependency_mode: str,
    default_dependencies: tuple[str, ...],
) -> None:
    raw = load_yaml_file(
        manifest_path,
        code="manifest.yaml_invalid",
        message="manifest file must be valid YAML",
    )
    if not isinstance(raw, dict):
        raise ProjectConfigError("manifest.invalid", "manifest must be a mapping", path=manifest_path)
    dependencies = list(raw.get("dependencies") or [])
    if dependency_mode == "file":
        relative_package_path = os.path.relpath(
            package_manifest.root,
            start=manifest_path.parent,
        )
        entry = {"type": "file", "path": relative_package_path}
    else:
        entry = {
            "type": "registry",
            "identifier": package_manifest.project.identifier,
        }
    required_dependencies = [entry]
    for dependency in default_dependencies:
        if dependency == package_manifest.project.identifier:
            continue
        required_dependencies.append({"type": "registry", "identifier": dependency})
    dependencies = [
        *[
            required
            for required in required_dependencies
            if not _dependency_present(dependencies, required)
        ],
        *dependencies,
    ]
    raw["dependencies"] = dependencies
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _dependency_present(dependencies: list[Any], entry: dict[str, str]) -> bool:
    if entry.get("type") == "file":
        return any(
            isinstance(existing, dict)
            and existing.get("type", "file") == "file"
            and existing.get("path") == entry["path"]
            for existing in dependencies
        )
    return any(
        isinstance(existing, dict)
        and existing.get("type") == "registry"
        and existing.get("identifier") == entry["identifier"]
        for existing in dependencies
    )


def _ensure_new_directory(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        raise ProjectConfigError(
            "create.destination_exists",
            "destination exists and is not empty",
            path=root,
        )
    root.mkdir(parents=True, exist_ok=True)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
