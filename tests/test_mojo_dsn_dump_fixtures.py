from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_mojo_dsn_dump_handles_issue230_decimal_tokens(tmp_path: Path) -> None:
    """Regression: Issue230 DSN contains tokens like '304.8' in via-name decoding paths."""
    repo_root = Path(__file__).resolve().parents[1]
    router = repo_root / "routing" / "mojo_router" / "build" / "pardal-router-mojo"
    if not router.exists():
        # Keep unit suite usable even if Mojo binary isn't built in this environment.
        return

    dsn = (
        repo_root.parents[0]
        / "freerouting"
        / "tests"
        / "Issue230-CNH_Functional_Tester"
        / "CNH_Functional_Tester_1.dsn"
    )
    if not dsn.exists():
        raise AssertionError(f"missing fixture DSN: {dsn}")

    out_json = tmp_path / "dump.json"
    subprocess.run([str(router), "dsn-dump", str(dsn), str(out_json)], check=True)
    payload = json.loads(out_json.read_text(encoding="utf-8", errors="replace"))
    assert "layers" in payload
    assert "nets" in payload


def test_mojo_dsn_dump_includes_placement_and_library(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    router = repo_root / "routing" / "mojo_router" / "build" / "pardal-router-mojo"
    if not router.exists():
        return

    dsn = (
        repo_root.parents[0]
        / "freerouting"
        / "tests"
        / "Issue069-TestSensel"
        / "TestSensel.dsn"
    )
    if not dsn.exists():
        raise AssertionError(f"missing fixture DSN: {dsn}")

    out_json = tmp_path / "dump.json"
    subprocess.run([str(router), "dsn-dump", str(dsn), str(out_json)], check=True)
    payload = json.loads(out_json.read_text(encoding="utf-8", errors="replace"))
    placement = payload.get("placement") or {}
    library_pins = payload.get("library_pins") or {}
    assert isinstance(placement, dict)
    assert isinstance(library_pins, dict)
    assert len(placement) > 0
    assert len(library_pins) > 0
