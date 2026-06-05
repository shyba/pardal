from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LOCK_SCHEMA = "pardal.lock/v1"
PACKAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*$")
PACKAGE_TYPES = {"file", "registry", "git"}


@dataclass(frozen=True, slots=True)
class LockedPackage:
    identifier: str
    type: str
    release: str | None = None
    repo: str | None = None
    ref: str | None = None
    commit: str | None = None
    path_within_repo: str | None = None
    source: str | None = None
    manifest_hash: str = ""
    content_hash: str = ""
    export_hashes: dict[str, tuple[dict[str, str], ...]] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LockFile:
    schema: str
    packages: dict[str, LockedPackage]
    project_hash: str = ""
    manifest: str = "pardal.yaml"


def write_lock_file(lock: LockFile, path: Path) -> None:
    path.write_text(
        yaml.safe_dump(lock_to_dict(lock), sort_keys=True),
        encoding="utf-8",
    )


def lock_to_dict(lock: LockFile) -> dict[str, Any]:
    return {
        "schema": lock.schema,
        "root": {
            key: value
            for key, value in {
                "project_hash": lock.project_hash,
                "manifest": lock.manifest,
            }.items()
            if value not in ("", None)
        },
        "packages": {
            identifier: {
                key: value
                for key, value in {
                    "type": package.type,
                    "release": package.release,
                    "repo": package.repo,
                    "ref": package.ref,
                    "commit": package.commit,
                    "path": package.path_within_repo,
                    "source": package.source,
                    "manifest_hash": package.manifest_hash,
                    "content_hash": package.content_hash,
                    "export_hashes": _export_hashes_to_dict(package.export_hashes),
                    "dependencies": list(package.dependencies),
                }.items()
                if value not in (None, "", [], {})
            }
            for identifier, package in sorted(lock.packages.items())
        },
    }


def load_lock_file(path: Path) -> LockFile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: lock file must be valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: lock file must be a mapping")
    schema = _optional_string(raw.get("schema"), path, "schema")
    if schema != LOCK_SCHEMA:
        raise ValueError(f"{path}: schema must be {LOCK_SCHEMA}")
    packages_raw = raw.get("packages") or {}
    if not isinstance(packages_raw, dict):
        raise ValueError(f"{path}: packages must be a mapping")
    root_raw = raw.get("root") or {}
    if not isinstance(root_raw, dict):
        raise ValueError(f"{path}: root must be a mapping")
    packages: dict[str, LockedPackage] = {}
    for identifier, value in packages_raw.items():
        if not isinstance(identifier, str) or not isinstance(value, dict):
            raise ValueError(f"{path}: invalid package entry")
        if PACKAGE_ID_RE.fullmatch(identifier) is None:
            raise ValueError(f"{path}: packages.{identifier} must be a package ID")
        package_type = _required_string(value.get("type"), path, f"packages.{identifier}.type")
        if package_type not in PACKAGE_TYPES:
            raise ValueError(f"{path}: packages.{identifier}.type must be file, registry, or git")
        dependencies = _string_list(value.get("dependencies") or [], path, f"packages.{identifier}.dependencies")
        package = LockedPackage(
            identifier=identifier,
            type=package_type,
            release=_optional_string(value.get("release"), path, f"packages.{identifier}.release"),
            repo=_optional_string(value.get("repo"), path, f"packages.{identifier}.repo"),
            ref=_optional_string(value.get("ref"), path, f"packages.{identifier}.ref"),
            commit=_optional_string(value.get("commit"), path, f"packages.{identifier}.commit"),
            path_within_repo=_optional_string(value.get("path"), path, f"packages.{identifier}.path"),
            source=_optional_string(value.get("source"), path, f"packages.{identifier}.source"),
            manifest_hash=_required_string(value.get("manifest_hash"), path, f"packages.{identifier}.manifest_hash"),
            content_hash=_required_string(value.get("content_hash"), path, f"packages.{identifier}.content_hash"),
            export_hashes=_export_hashes_from_dict(value.get("export_hashes") or {}),
            dependencies=tuple(dependencies),
        )
        _validate_locked_package_source_fields(package, path)
        packages[identifier] = package
    return LockFile(
        schema=schema,
        packages=packages,
        project_hash=_optional_string(root_raw.get("project_hash"), path, "root.project_hash") or "",
        manifest=_optional_string(root_raw.get("manifest"), path, "root.manifest") or "pardal.yaml",
    )


def _required_string(value: Any, path: Path, field: str) -> str:
    result = _optional_string(value, path, field)
    if not result:
        raise ValueError(f"{path}: {field} must be a non-empty string")
    return result


def _optional_string(value: Any, path: Path, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{path}: {field} must be a string")
    return value


def _validate_locked_package_source_fields(package: LockedPackage, path: Path) -> None:
    field_prefix = f"packages.{package.identifier}"
    if not package.source:
        raise ValueError(f"{path}: {field_prefix}.source must be a non-empty string")
    if package.type == "registry" and not package.release:
        raise ValueError(f"{path}: {field_prefix}.release must be a non-empty string")
    if package.type == "git":
        if not package.repo:
            raise ValueError(f"{path}: {field_prefix}.repo must be a non-empty string")
        if not package.commit:
            raise ValueError(f"{path}: {field_prefix}.commit must be a non-empty string")


def _string_list(value: Any, path: Path, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{path}: {field} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{path}: {field}[{index}] must be a string")
        result.append(item)
    return result


def package_content_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if _is_ignored_package_hash_path(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_mode_tag(path))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _is_ignored_package_hash_path(path: Path, root: Path) -> bool:
    return is_ignored_package_generated_path(path, root)


def is_ignored_package_generated_path(path: Path, root: Path) -> bool:
    ignored_dirs = {".git", ".pardal", "dist", "build", "__pycache__"}
    ignored_suffixes = {".pyc", ".pyo"}
    ignored_name_suffixes = (".egg-info",)
    ignored_names = {
        "package-resolution.json",
        "profile-resolution.json",
        "production-checks.json",
        "drc-report.json",
        "build-summary.json",
        "validation-results.json",
        "manufacturing-package.zip",
    }
    ignored_report_suffixes = (
        "-drc.rpt",
        "-drc.json",
        ".kicad_pcb.bak",
        ".kicad_pcb-bak",
    )
    rel_parts = path.relative_to(root).parts
    if set(rel_parts) & ignored_dirs:
        return True
    if path.suffix in ignored_suffixes:
        return True
    if path.name in ignored_names:
        return True
    if path.name.endswith(ignored_report_suffixes):
        return True
    return any(part.endswith(ignored_name_suffixes) for part in rel_parts)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def _mode_tag(path: Path) -> bytes:
    return b"x" if path.stat().st_mode & 0o111 else b"f"


def _export_hashes_to_dict(
    export_hashes: dict[str, tuple[dict[str, str], ...]],
) -> dict[str, list[dict[str, str]]]:
    return {
        kind: [dict(item) for item in entries]
        for kind, entries in sorted(export_hashes.items())
    }


def _export_hashes_from_dict(value: Any) -> dict[str, tuple[dict[str, str], ...]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, tuple[dict[str, str], ...]] = {}
    for kind, entries in value.items():
        if not isinstance(kind, str) or not isinstance(entries, list):
            continue
        parsed_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            parsed_entries.append(
                {str(key): str(raw_value) for key, raw_value in entry.items()}
            )
        result[kind] = tuple(
            sorted(
                parsed_entries,
                key=lambda entry: (
                    entry.get("id", ""),
                    entry.get("path", ""),
                    entry.get("hash", ""),
                ),
            )
        )
    return result
