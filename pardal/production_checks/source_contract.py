from __future__ import annotations

from pathlib import Path
from typing import Any

from pardal.production_checks.models import SourceContract, Waiver


def load_source_contract(path: Path | None) -> SourceContract:
    if path is None:
        return SourceContract()
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load source contracts") from exc

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("source contract must be a mapping")
    schema = data.get("schema")
    if schema is not None and schema != "pardal.source_contract/v1":
        raise ValueError("source contract schema must be pardal.source_contract/v1")
    raw = data.get("source_contract", data)
    if not isinstance(raw, dict):
        raise ValueError("source_contract must be a mapping")

    raw_waivers = _waive_checks(_raw_waivers(raw))
    return SourceContract(
        path=path,
        profiles=_string_map(raw.get("profiles") or {}, "profiles"),
        enable_checks=tuple(
            _string_list(raw.get("enable_checks") or [], "enable_checks")
        ),
        disable_checks=tuple(
            _string_list(raw.get("disable_checks") or [], "disable_checks")
        ),
        waive_checks=raw_waivers,
        waivers=_typed_waivers(raw_waivers),
        rails=_mapping(_first_mapping(raw, "rails", "supply_rails"), "rails"),
        inputs=_mapping(raw.get("inputs") or {}, "inputs"),
        adc_filters=_mapping(_first_mapping(raw, "adc_filters", "adc_frontends"), "adc_filters"),
        validation=_plain_mapping(raw.get("validation") or {}, "validation"),
        components=_component_mapping(raw.get("components") or {}),
        part_aliases=_string_map(raw.get("part_aliases") or {}, "part_aliases"),
    )


def _first_mapping(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value:
            return value
    return {}


def _mapping(value: Any, field_name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping")
    result: dict[str, dict[str, Any]] = {}
    for key, item in value.items():
        if not isinstance(item, dict):
            raise ValueError(f"{field_name}.{key} must be a mapping")
        result[str(key)] = dict(item)
    return result


def _component_mapping(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("components must be a mapping")
    result: dict[str, dict[str, Any]] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError("components keys must be non-empty strings")
        if not isinstance(item, dict):
            raise ValueError(f"components.{key} must be a mapping")
        copied = dict(item)
        for field in ("part_id", "footprint_id", "footprint", "lcsc"):
            field_value = copied.get(field)
            if field_value is not None and (
                not isinstance(field_value, str) or not field_value
            ):
                raise ValueError(f"components.{key}.{field} must be a non-empty string")
        result[key] = copied
    return result


def _waive_checks(value: Any) -> dict[str, dict[str, Any]]:
    waivers = _mapping(value, "waive_checks")
    for check_id, waiver in waivers.items():
        reason = str(waiver.get("reason") or "").strip()
        if not reason:
            raise ValueError(f"waive_checks.{check_id}.reason must be non-empty")
        match = waiver.get("match")
        if match is not None and not isinstance(match, dict):
            raise ValueError(f"waive_checks.{check_id}.match must be a mapping")
        refs = waiver.get("refs")
        if refs is not None:
            _string_list(refs, f"waive_checks.{check_id}.refs")
        expires = waiver.get("expires")
        if expires is not None:
            import datetime as _dt

            try:
                _dt.date.fromisoformat(str(expires))
            except ValueError as exc:
                raise ValueError(
                    f"waive_checks.{check_id}.expires must be YYYY-MM-DD"
                ) from exc
    return waivers


def _typed_waivers(waivers: dict[str, dict[str, Any]]) -> tuple[Waiver, ...]:
    return tuple(
        Waiver(
            id=check_id,
            reason=str(waiver.get("reason") or "").strip(),
            stage=str(waiver.get("stage") or "").strip(),
            match=dict(waiver.get("match") or {}),
            refs=tuple(str(ref) for ref in waiver.get("refs") or ()),
            owner=str(waiver.get("owner") or "").strip(),
            expires=str(waiver.get("expires") or "").strip(),
        )
        for check_id, waiver in sorted(waivers.items())
    )


def _raw_waivers(raw: dict[str, Any]) -> Any:
    if raw.get("waive_checks") is not None:
        return raw.get("waive_checks") or {}
    value = raw.get("waivers") or []
    if not isinstance(value, list):
        raise ValueError("waivers must be a list")
    waivers: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"waivers[{index}] must be a mapping")
        check_id = item.get("id")
        if not check_id:
            raise ValueError(f"waivers[{index}].id must be non-empty")
        stage = str(item.get("stage") or "").strip()
        if not stage:
            raise ValueError(f"waivers[{index}].stage must be non-empty")
        copied = dict(item)
        copied.pop("id", None)
        waivers[str(check_id)] = copied
    return waivers


def _plain_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping")
    return dict(value)


def _string_map(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{field_name} keys must be non-empty strings")
        if not isinstance(item, str) or not item:
            raise ValueError(f"{field_name}.{key} must be a non-empty string")
        result[key] = item
    return result


def _string_list(value: Any, field_name: str = "check lists") -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ValueError(f"{field_name}[{index}] must be a non-empty string")
        result.append(item)
    return result
