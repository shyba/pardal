import json
import sys
from argparse import Namespace
from pathlib import Path

from pardal.cli import cmd_verify_validation_results, main


def _write_file(path: Path, contents: str | dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contents, (dict, list)):
        path.write_text(json.dumps(contents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        path.write_text(contents, encoding="utf-8")


def _build_summary(tmp_path: Path, *, names: list[str] | None = None, count: int | None = None) -> Path:
    names = ["power_on_3v3", "clock_stable", "gpio_sanity"] if names is None else names
    if count is None:
        count = len(names)
    payload = {
        "validation": {
            "count": count,
            "kinds": ["power", "clock", "io"],
            "names": names,
        }
    }
    summary_path = tmp_path / "build-summary.json"
    _write_file(summary_path, payload)
    return summary_path


def _write_results(path: Path, entries: list[dict[str, str]]) -> None:
    _write_file(path, {"results": entries})


def _validate_summary_and_results(summary_path: Path, result_entries: list[dict[str, str]]) -> int:
    tmp_dir = summary_path.parent
    results_path = tmp_dir / "validation-results.json"
    _write_results(results_path, result_entries)
    return cmd_verify_validation_results(
        Namespace(summary_json=summary_path, validation_results_json=results_path)
    )


def test_verify_validation_results_passes(tmp_path, capsys):
    summary_path = _build_summary(tmp_path)
    result_entries = [
        {"name": "power_on_3v3", "status": "pass", "measured": "3.31V", "notes": "Good"},
        {"name": "clock_stable", "status": "pass", "measured": "7.3728MHz", "notes": "Stable"},
        {"name": "gpio_sanity", "status": "pass", "measured": "1,1,0,1,1"},
    ]
    tmp_path / "validation-results.json"

    results_path = tmp_path / "validation-results.json"
    _write_results(results_path, result_entries)
    result = cmd_verify_validation_results(
        Namespace(summary_json=summary_path, validation_results_json=results_path)
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "PASS: captured validation results verified" in captured.out
    assert captured.err == ""


def test_verify_validation_results_rejects_missing_declared(tmp_path, capsys):
    summary_path = _build_summary(tmp_path)
    result_entries = [
        {"name": "power_on_3v3", "status": "pass", "measured": "3.31V"},
    ]

    result = _validate_summary_and_results(summary_path, result_entries)

    captured = capsys.readouterr()
    assert result == 1
    assert "missing validation results" in captured.err


def test_verify_validation_results_rejects_unknown_name(tmp_path, capsys):
    summary_path = _build_summary(tmp_path)
    result_entries = [
        {"name": "power_on_3v3", "status": "pass"},
        {"name": "clock_stable", "status": "pass"},
        {"name": "uart_bounce", "status": "pass"},
    ]

    result = _validate_summary_and_results(summary_path, result_entries)

    captured = capsys.readouterr()
    assert result == 1
    assert "unknown validation results" in captured.err


def test_verify_validation_results_rejects_duplicate_name(tmp_path, capsys):
    summary_path = _build_summary(tmp_path)
    result_entries = [
        {"name": "power_on_3v3", "status": "pass"},
        {"name": "power_on_3v3", "status": "pass"},
        {"name": "clock_stable", "status": "pass"},
        {"name": "gpio_sanity", "status": "pass"},
    ]

    result = _validate_summary_and_results(summary_path, result_entries)

    captured = capsys.readouterr()
    assert result == 1
    assert "duplicate validation result names" in captured.err


def test_verify_validation_results_rejects_fail_or_skip_status(tmp_path, capsys):
    summary_path = _build_summary(tmp_path)
    result_entries = [
        {"name": "power_on_3v3", "status": "fail", "measured": "3.14V"},
        {"name": "clock_stable", "status": "skip", "measured": "7.37MHz"},
        {"name": "gpio_sanity", "status": "pass", "measured": "1,0,1"},
    ]

    result = _validate_summary_and_results(summary_path, result_entries)

    captured = capsys.readouterr()
    assert result == 1
    assert "validation result did not pass: power_on_3v3 -> fail" in captured.err
    assert "validation result did not pass: clock_stable -> skip" in captured.err


def test_verify_validation_results_rejects_invalid_file_shapes(tmp_path, capsys):
    summary_path = _build_summary(tmp_path)
    results_path = tmp_path / "validation-results.json"
    _write_file(results_path, "not-json")

    result = cmd_verify_validation_results(
        Namespace(summary_json=summary_path, validation_results_json=results_path)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "malformed JSON in results file" in captured.err


def test_verify_validation_results_rejects_template_payload(tmp_path, capsys):
    summary_path = _build_summary(tmp_path)
    results_path = tmp_path / "validation-results.template.json"
    _write_file(
        results_path,
        {
            "status": "template",
            "results": [
                {"name": "power_on_3v3", "status": "not_run"},
                {"name": "clock_stable", "status": "not_run"},
                {"name": "gpio_sanity", "status": "not_run"},
            ],
        },
    )

    result = cmd_verify_validation_results(
        Namespace(summary_json=summary_path, validation_results_json=results_path)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "template, not completed evidence" in captured.err


def test_verify_validation_results_rejects_missing_validation_summary(tmp_path, capsys):
    summary_path = tmp_path / "build-summary.json"
    _write_file(summary_path, {"pass": True})
    result_path = tmp_path / "validation-results.json"
    _write_results(result_path, [
        {"name": "power_on_3v3", "status": "pass"},
        {"name": "clock_stable", "status": "pass"},
        {"name": "gpio_sanity", "status": "pass"},
    ])

    result = cmd_verify_validation_results(
        Namespace(summary_json=summary_path, validation_results_json=result_path)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "summary validation section missing" in captured.err


def test_verify_validation_results_dispatches_from_main(monkeypatch, tmp_path):
    summary_path = _build_summary(tmp_path)
    results_path = tmp_path / "validation-results.json"
    _write_results(results_path, [
        {"name": "power_on_3v3", "status": "pass"},
        {"name": "clock_stable", "status": "pass"},
        {"name": "gpio_sanity", "status": "pass"},
    ])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pardal",
            "verify-validation-results",
            str(summary_path),
            str(results_path),
        ],
    )

    result = main()
    assert result == 0
