from __future__ import annotations

import re

from pardal import __version__
from pardal.project.diagnostics import ProjectConfigError

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def validate_requires_pardal(
    requirement: str,
    *,
    path=None,
    field: str = "requires-pardal",
) -> None:
    if _satisfies_requirement(__version__, requirement, path=path, field=field):
        return
    raise ProjectConfigError(
        "manifest.requires_pardal_incompatible",
        f"Pardal {__version__} does not satisfy {requirement!r}",
        path=path,
        field=field,
    )


def _satisfies_requirement(
    version: str,
    requirement: str,
    *,
    path=None,
    field: str = "requires-pardal",
) -> bool:
    if requirement.startswith("^"):
        return _satisfies_caret(version, requirement[1:], path=path, field=field)
    return _parse_semver(version, path=path, field=field) == _parse_semver(
        requirement,
        path=path,
        field=field,
    )


def _satisfies_caret(
    version: str,
    minimum: str,
    *,
    path=None,
    field: str = "requires-pardal",
) -> bool:
    current = _parse_semver(version, path=path, field=field)
    floor = _parse_semver(minimum, path=path, field=field)
    if current < floor:
        return False
    if floor[0] > 0:
        return current[0] == floor[0]
    if floor[1] > 0:
        return current[0] == 0 and current[1] == floor[1]
    return current[0] == 0 and current[1] == 0 and current[2] == floor[2]


def _parse_semver(value: str, *, path=None, field: str = "requires-pardal") -> tuple[int, int, int]:
    match = SEMVER_RE.match(value)
    if match is None:
        raise ProjectConfigError(
            "manifest.requires_pardal_invalid",
            "requires-pardal must be an exact SemVer or caret SemVer range",
            path=path,
            field=field,
        )
    return tuple(int(part) for part in match.groups())
