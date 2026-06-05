from __future__ import annotations

import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import urlopen

from pardal.project.diagnostics import ProjectConfigError
from pardal.project.manifest import PACKAGE_ID_RE
from pardal.project.yaml import load_yaml_file

REGISTRY_SCHEMA = "pardal.registry/v1"
SHA256_RE = re.compile(r"^(sha256:)?[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True)
class RegistryRelease:
    identifier: str
    version: str
    url: str
    sha256: str
    yanked: bool = False
    requires_pardal: str | None = None


class StaticRegistryClient:
    def __init__(self, index_path: Path | str) -> None:
        self.index_path = Path(index_path)
        raw = load_yaml_file(
            self.index_path,
            code="registry.yaml_invalid",
            message="registry index must be valid YAML",
        )
        if not isinstance(raw, dict):
            raise ProjectConfigError(
                "registry.index_invalid",
                "registry index must be a mapping",
                path=self.index_path,
            )
        if raw.get("schema") != REGISTRY_SCHEMA:
            raise ProjectConfigError(
                "registry.schema_invalid",
                "expected schema pardal.registry/v1",
                path=self.index_path,
                field="schema",
            )
        packages = raw.get("packages")
        if not isinstance(packages, dict):
            raise ProjectConfigError(
                "registry.packages_invalid",
                "packages must be a mapping",
                path=self.index_path,
                field="packages",
            )
        for package_id in packages:
            if not isinstance(package_id, str) or not PACKAGE_ID_RE.fullmatch(package_id):
                raise ProjectConfigError(
                    "registry.package_id_invalid",
                    "registry package keys must be package IDs in owner/name form",
                    path=self.index_path,
                    field=f"packages.{package_id}",
                )
        self._packages = packages

    def get_release(
        self,
        identifier: str,
        version: str | None,
        *,
        allow_yanked: bool = False,
    ) -> RegistryRelease:
        package = self._packages.get(identifier)
        if not isinstance(package, dict):
            raise ProjectConfigError(
                "registry.package_unknown",
                f"unknown registry package {identifier!r}",
                path=self.index_path,
                field=f"packages.{identifier}",
            )
        versions = package.get("versions")
        if not isinstance(versions, dict) or not versions:
            raise ProjectConfigError(
                "registry.versions_invalid",
                f"package {identifier!r} has no versions",
                path=self.index_path,
                field=f"packages.{identifier}.versions",
            )
        parsed_versions = _parse_semver_versions(
            versions,
            identifier=identifier,
            index_path=self.index_path,
        )
        selected_version = version or _latest_available_version(
            versions,
            parsed_versions,
            identifier=identifier,
            index_path=self.index_path,
            allow_yanked=allow_yanked,
        )
        release = versions.get(selected_version)
        if not isinstance(release, dict):
            raise ProjectConfigError(
                "registry.release_unknown",
                f"unknown release {identifier}@{selected_version}",
                path=self.index_path,
                field=f"packages.{identifier}.versions.{selected_version}",
            )
        raw_yanked = release.get("yanked", False)
        if not isinstance(raw_yanked, bool):
            raise ProjectConfigError(
                "registry.release_yanked_invalid",
                "release yanked must be a boolean",
                path=self.index_path,
                field=f"packages.{identifier}.versions.{selected_version}.yanked",
            )
        yanked = raw_yanked
        if yanked and not allow_yanked:
            raise ProjectConfigError(
                "registry.release_yanked",
                f"release {identifier}@{selected_version} is yanked",
                path=self.index_path,
                field=f"packages.{identifier}.versions.{selected_version}",
            )
        url = release.get("url")
        sha256 = release.get("sha256")
        if not isinstance(url, str) or not isinstance(sha256, str):
            raise ProjectConfigError(
                "registry.release_invalid",
                "release requires url and sha256",
                path=self.index_path,
                field=f"packages.{identifier}.versions.{selected_version}",
            )
        if SHA256_RE.fullmatch(sha256) is None:
            raise ProjectConfigError(
                "registry.release_sha256_invalid",
                "release sha256 must be a sha256-prefixed or raw 64-character hex digest",
                path=self.index_path,
                field=f"packages.{identifier}.versions.{selected_version}.sha256",
            )
        requires_pardal = release.get("requires_pardal")
        if requires_pardal is not None and not isinstance(requires_pardal, str):
            raise ProjectConfigError(
                "registry.release_requires_pardal_invalid",
                "release requires_pardal must be a string",
                path=self.index_path,
                field=f"packages.{identifier}.versions.{selected_version}.requires_pardal",
            )
        return RegistryRelease(
            identifier=identifier,
            version=selected_version,
            url=url,
            sha256=sha256,
            yanked=yanked,
            requires_pardal=requires_pardal,
        )

    def fetch_release_archive(self, release: RegistryRelease, cache_dir: Path) -> Path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        destination = cache_dir / f"{release.identifier.replace('/', '-')}-{release.version}.tar.gz"
        _fetch_registry_url(release.url, self.index_path.parent, destination)
        actual = _sha256(destination)
        expected = _normalize_sha256(release.sha256)
        if actual != expected:
            raise ProjectConfigError(
                "registry.hash_mismatch",
                f"registry archive hash mismatch for {release.identifier}@{release.version}",
                path=destination,
            )
        return destination


def extract_archive(archive_path: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        with tarfile.open(archive_path, "r:gz") as archive:
            _reject_unsafe_archive_members(archive, archive_path)
            archive.extractall(temp_path, filter="data")
        _reject_unsafe_extracted_archive(temp_path, archive_path)
        if (temp_path / "pardal.yaml").exists():
            shutil.copytree(temp_path, destination)
            return
        children = [child for child in temp_path.iterdir() if child.is_dir()]
        if len(children) == 1 and (children[0] / "pardal.yaml").exists():
            shutil.copytree(children[0], destination)
            return
        raise ProjectConfigError(
            "registry.archive_invalid",
            "registry archive must contain pardal.yaml at root",
            path=archive_path,
        )


def _reject_unsafe_archive_members(archive: tarfile.TarFile, archive_path: Path) -> None:
    for member in archive.getmembers():
        if member.isdir() or member.isfile():
            continue
        if member.issym():
            message = "registry archive must not contain symlinks"
        elif member.islnk():
            message = "registry archive must not contain hardlinks"
        else:
            message = "registry archive must contain only files and directories"
        raise ProjectConfigError(
            "registry.archive_unsafe",
            message,
            path=archive_path,
            field=member.name,
        )


def _reject_unsafe_extracted_archive(root: Path, archive_path: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ProjectConfigError(
                "registry.archive_unsafe",
                "registry archive must not contain symlinks",
                path=archive_path,
                field=path.relative_to(root).as_posix(),
            )
        if not path.is_file() and not path.is_dir():
            raise ProjectConfigError(
                "registry.archive_unsafe",
                "registry archive must contain only files and directories",
                path=archive_path,
                field=path.relative_to(root).as_posix(),
            )


def _fetch_registry_url(url: str, base_dir: Path, destination: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme in {"", "file"}:
        raw_path = parsed.path if parsed.scheme == "file" else url
        path = Path(raw_path)
        source = path if path.is_absolute() else base_dir / path
        if not source.exists():
            raise ProjectConfigError(
                "registry.archive_missing",
                "registry archive does not exist",
                path=source,
            )
        shutil.copyfile(source, destination)
        return
    if parsed.scheme in {"http", "https"}:
        try:
            with urlopen(url, timeout=30) as response, destination.open("wb") as output:
                shutil.copyfileobj(response, output)
        except OSError as exc:
            raise ProjectConfigError(
                "registry.archive_fetch_failed",
                f"registry archive fetch failed: {exc}",
                path=base_dir,
                field=url,
            ) from exc
        return
    raise ProjectConfigError(
        "registry.url_unsupported",
        "only local file and HTTP(S) registry URLs are supported",
        path=base_dir,
    )


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _normalize_sha256(value: str) -> str:
    return value.removeprefix("sha256:")


def _parse_semver_versions(
    versions: dict[object, object],
    *,
    identifier: str,
    index_path: Path,
) -> list[tuple[tuple[int, int, int], str]]:
    parsed: list[tuple[tuple[int, int, int], str]] = []
    for raw_version in versions:
        if not isinstance(raw_version, str):
            raise ProjectConfigError(
                "registry.version_invalid",
                "registry version keys must be strings",
                path=index_path,
                field=f"packages.{identifier}.versions",
            )
        parts = raw_version.split(".")
        if len(parts) != 3 or any(not part.isdigit() for part in parts):
            raise ProjectConfigError(
                "registry.version_invalid",
                "registry version keys must be SemVer major.minor.patch strings",
                path=index_path,
                field=f"packages.{identifier}.versions.{raw_version}",
            )
        parsed.append(((int(parts[0]), int(parts[1]), int(parts[2])), raw_version))
    return parsed


def _latest_available_version(
    versions: dict[object, object],
    parsed_versions: list[tuple[tuple[int, int, int], str]],
    *,
    identifier: str,
    index_path: Path,
    allow_yanked: bool,
) -> str:
    latest_yanked: str | None = None
    for _parsed, version in sorted(parsed_versions, reverse=True):
        release = versions.get(version)
        if not isinstance(release, dict):
            raise ProjectConfigError(
                "registry.release_invalid",
                "release must be a mapping",
                path=index_path,
                field=f"packages.{identifier}.versions.{version}",
            )
        raw_yanked = release.get("yanked", False)
        if not isinstance(raw_yanked, bool):
            raise ProjectConfigError(
                "registry.release_yanked_invalid",
                "release yanked must be a boolean",
                path=index_path,
                field=f"packages.{identifier}.versions.{version}.yanked",
            )
        if raw_yanked:
            latest_yanked = latest_yanked or version
            if not allow_yanked:
                continue
        return version
    assert latest_yanked is not None
    raise ProjectConfigError(
        "registry.release_yanked",
        f"release {identifier}@{latest_yanked} is yanked",
        path=index_path,
        field=f"packages.{identifier}.versions.{latest_yanked}",
    )
