from __future__ import annotations

from pardal.production_checks.models import CheckFunction, RegisteredCheck


class CheckRegistry:
    def __init__(self) -> None:
        self._checks: dict[str, RegisteredCheck] = {}

    def register(
        self,
        check_id: str,
        *,
        default_severity: str,
        stage: str = "",
        general: bool = False,
        globally_waivable: bool = False,
    ):
        def decorator(func: CheckFunction) -> CheckFunction:
            self._checks[check_id] = RegisteredCheck(
                check_id=check_id,
                default_severity=default_severity,
                func=func,
                stage=stage,
                general=general,
                globally_waivable=globally_waivable,
            )
            return func

        return decorator

    def get(self, check_id: str) -> RegisteredCheck | None:
        return self._checks.get(check_id)

    def general_check_ids(self) -> set[str]:
        return {check_id for check_id, check in self._checks.items() if check.general}

    def registered_ids(self) -> set[str]:
        return set(self._checks)


registry = CheckRegistry()
