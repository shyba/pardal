from __future__ import annotations

from pathlib import Path

from pardal.project.diagnostics import ProjectConfigError
from pardal.project.manifest import PACKAGE_ID_RE, DependencySpec


def parse_dependency_spec(spec: str) -> DependencySpec:
    if not spec:
        raise ProjectConfigError("dependency.spec_empty", "dependency spec is empty")
    if "://" not in spec:
        return _parse_registry(spec)
    scheme, rest = spec.split("://", 1)
    if scheme == "file":
        if not rest:
            raise ProjectConfigError("dependency.file_path_missing", "file dependency requires a path")
        return DependencySpec(type="file", path=Path(rest))
    if scheme == "git":
        return _parse_git(rest)
    if scheme == "registry":
        return _parse_registry(rest)
    raise ProjectConfigError(
        "dependency.scheme_invalid",
        "dependency scheme must be registry, file, or git",
    )


def _parse_registry(rest: str) -> DependencySpec:
    identifier, release = _split_once(rest, "@")
    _validate_identifier(identifier)
    return DependencySpec(type="registry", identifier=identifier, release=release)


def _parse_git(rest: str) -> DependencySpec:
    repo_and_ref, path_within_repo = _split_once(rest, ":")
    repo, ref = _split_once(repo_and_ref, "#")
    if not repo:
        raise ProjectConfigError("dependency.git_repo_missing", "git dependency requires a repository")
    if path_within_repo is not None:
        _validate_git_path_within_repo(path_within_repo)
    identifier = None if path_within_repo else _identifier_from_repo(repo)
    return DependencySpec(
        type="git",
        identifier=identifier,
        repo=repo,
        ref=ref,
        path_within_repo=path_within_repo,
    )


def _validate_git_path_within_repo(path: str) -> None:
    parsed = Path(path)
    if parsed.is_absolute() or any(part == ".." for part in parsed.parts):
        raise ProjectConfigError(
            "dependency.git_path_invalid",
            "git dependency path must be relative and stay inside the repository",
        )


def _identifier_from_repo(repo: str) -> str:
    trimmed = repo.rstrip("/")
    if trimmed.endswith(".git"):
        trimmed = trimmed[:-4]
    parts = [part for part in trimmed.split("/") if part]
    if len(parts) < 2:
        raise ProjectConfigError(
            "dependency.git_identifier_invalid",
            "git dependency repository must end in owner/name",
        )
    owner = parts[-2].lower()
    name = parts[-1].lower()
    identifier = f"{owner}/{name}"
    _validate_identifier(identifier)
    return identifier


def _split_once(value: str, separator: str) -> tuple[str, str | None]:
    if separator not in value:
        return value, None
    left, right = value.split(separator, 1)
    return left, right or None


def _validate_identifier(identifier: str) -> None:
    if not PACKAGE_ID_RE.match(identifier):
        raise ProjectConfigError(
            "dependency.identifier_invalid",
            "package identifier must match owner/name",
        )
