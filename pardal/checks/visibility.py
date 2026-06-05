from __future__ import annotations

from typing import Any

from pardal.checks.api import CheckDefinition, registered_checks


def project_registered_checks(project_context: Any | None) -> dict[str, CheckDefinition]:
    checks = registered_checks()
    if project_context is None:
        return checks
    package_index = getattr(project_context, "package_index", None)
    packages_by_id = getattr(package_index, "packages_by_id", None)
    if packages_by_id is None:
        return checks
    active_packages = set(packages_by_id)
    return {
        check_id: check
        for check_id, check in checks.items()
        if check.package in active_packages
    }
