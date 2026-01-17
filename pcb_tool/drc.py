"""DRC integration via kicad-cli.

Provides programmatic DRC checking by calling kicad-cli and parsing JSON output.
"""

import subprocess
import json
import tempfile
import os
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from json import JSONDecodeError


@dataclass
class DrcViolation:
    """A single DRC violation."""

    type: str
    severity: str
    description: str
    items: list = field(default_factory=list)


@dataclass
class DrcResult:
    """Result of a DRC check."""

    errors: int
    warnings: int
    violations: list[DrcViolation]
    unconnected: int
    report_path: Path | None
    success: bool


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _kicad_cli_supports_pcb_drc() -> bool:
    try:
        result = subprocess.run(
            ["kicad-cli", "pcb", "drc", "--help"], capture_output=True, text=True
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def _parse_drc_json(output_path: Path, *, stderr_fallback: str | None = None) -> tuple[int, int, list[DrcViolation], int]:
    errors = 0
    warnings = 0
    violations: list[DrcViolation] = []
    unconnected = 0

    data = None
    if output_path.exists() and output_path.stat().st_size > 0:
        try:
            with open(output_path) as f:
                data = json.load(f)
        except JSONDecodeError:
            data = None

    if isinstance(data, dict):
        unconnected = len(data.get("unconnected_items", []))

        for v in data.get("violations", []):
            severity = v.get("severity", "warning")
            if severity == "error":
                errors += 1
            else:
                warnings += 1

            violations.append(
                DrcViolation(
                    type=v.get("type", "unknown"),
                    severity=severity,
                    description=v.get("description", ""),
                    items=v.get("items", []),
                )
            )
        return errors, warnings, violations, unconnected

    if stderr_fallback:
        violations.append(
            DrcViolation(
                type="kicad-cli",
                severity="error",
                description=stderr_fallback.strip(),
                items=[],
            )
        )
        return 1, 0, violations, 0

    return errors, warnings, violations, unconnected


def run_drc_docker(
    pcb_path: Path,
    output_path: Path | None = None,
    *,
    image: str | None = None,
) -> DrcResult:
    """Run KiCad DRC via `kicad-cli` inside a docker image (opt-in).

    Enable by setting `PARDAL_KICAD_DOCKER=1`.
    """
    from pcb_tool.kicad_docker import DEFAULT_IMAGE, run_kicad_cli_in_docker

    pcb_path = Path(pcb_path)
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")

    if output_path is None:
        fd, tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        output_path = Path(tmp_path)
    else:
        output_path = Path(output_path)

    image = image or os.environ.get("PARDAL_KICAD_DOCKER_IMAGE") or DEFAULT_IMAGE

    with tempfile.TemporaryDirectory(prefix="pardal-kicad-drc-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        board_name = "board.kicad_pcb"
        report_name = "drc.json"
        (tmpdir_path / board_name).write_bytes(pcb_path.read_bytes())

        result = run_kicad_cli_in_docker(
            image=image,
            workdir_host=tmpdir_path,
            args=[
                "pcb",
                "drc",
                "--output",
                report_name,
                "--format",
                "json",
                "--severity-all",
                board_name,
            ],
        )

        report_src = tmpdir_path / report_name
        if report_src.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(report_src.read_bytes())

    errors, warnings, violations, unconnected = _parse_drc_json(
        output_path,
        stderr_fallback=(
            result.stderr or result.stdout or "kicad-cli pcb drc (docker) failed"
        )
        if result.returncode != 0
        else None,
    )

    return DrcResult(
        errors=errors,
        warnings=warnings,
        violations=violations,
        unconnected=unconnected,
        report_path=output_path,
        success=(errors == 0),
    )


def run_drc(pcb_path: Path, output_path: Path | None = None) -> DrcResult:
    """Run KiCad DRC via kicad-cli.

    Args:
        pcb_path: Path to .kicad_pcb file
        output_path: Optional path for JSON report (default: temp file)

    Returns:
        DrcResult with error/warning counts and violations
    """
    pcb_path = Path(pcb_path)
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")

    if not _kicad_cli_supports_pcb_drc():
        if _env_truthy("PARDAL_KICAD_DOCKER"):
            return run_drc_docker(pcb_path, output_path)

        return DrcResult(
            errors=1,
            warnings=0,
            violations=[
                DrcViolation(
                    type="kicad-cli",
                    severity="error",
                    description=(
                        "Local kicad-cli does not support `pcb drc` (KiCad 8+ required). "
                        "Set PARDAL_KICAD_DOCKER=1 to run KiCad 9 in docker, or use "
                        "`run_sdk_drc()` from a Python environment that provides `pcbnew`."
                    ),
                    items=[],
                )
            ],
            unconnected=0,
            report_path=None,
            success=False,
        )

    if output_path is None:
        fd, tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        output_path = Path(tmp_path)
    else:
        output_path = Path(output_path)

    cmd = [
        "kicad-cli",
        "pcb",
        "drc",
        "--output",
        str(output_path),
        "--format",
        "json",
        "--severity-all",
        str(pcb_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    errors, warnings, violations, unconnected = _parse_drc_json(
        output_path,
        stderr_fallback=(
            result.stderr or result.stdout or "kicad-cli pcb drc failed"
        )
        if result.returncode != 0
        else None,
    )

    return DrcResult(
        errors=errors,
        warnings=warnings,
        violations=violations,
        unconnected=unconnected,
        report_path=output_path,
        success=(errors == 0),
    )


def run_sdk_drc(pcb_path: Path, output_path: Path | None = None) -> DrcResult:
    """Run KiCad DRC via pcbnew SDK.

    Uses the pcbnew Python module directly instead of kicad-cli.
    Falls back to kicad-cli if pcbnew is not available.

    Args:
        pcb_path: Path to .kicad_pcb file
        output_path: Optional path for report (default: temp file)

    Returns:
        DrcResult with error/warning counts and violations
    """
    try:
        import pcbnew
    except ImportError:
        # Fall back to kicad-cli
        return run_drc(pcb_path, output_path)

    import re

    pcb_path = Path(pcb_path)
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")

    if output_path is None:
        fd, tmp_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        output_path = Path(tmp_path)
    else:
        output_path = Path(output_path)

    # Load board and run DRC
    board = pcbnew.LoadBoard(str(pcb_path))
    pcbnew.WriteDRCReport(board, str(output_path), pcbnew.EDA_UNITS_MM, True)

    # Parse the text report
    errors = 0
    warnings = 0
    violations = []
    unconnected = 0

    if output_path.exists():
        with open(output_path) as f:
            content = f.read()

        # Parse violation count
        match = re.search(r"\*\* Found (\d+) DRC violations \*\*", content)
        total_violations = int(match.group(1)) if match else 0

        # Parse unconnected items
        match = re.search(r"\*\* Found (\d+) unconnected pads \*\*", content)
        unconnected = int(match.group(1)) if match else 0

        # Parse individual violations
        # Format: [type]: Description\n    severity; qualifier\n    @(x, y): details
        violation_pattern = re.compile(
            r"\[(\w+)\]:\s*([^\n]+)\n\s+([\w\s]+);\s*(\w+)", re.MULTILINE
        )

        for match in violation_pattern.finditer(content):
            vtype = match.group(1)
            desc = match.group(2).strip()
            severity_text = match.group(4).lower()

            # Map severity
            if severity_text == "error":
                severity = "error"
                errors += 1
            else:
                severity = "warning"
                warnings += 1

            violations.append(
                DrcViolation(type=vtype, severity=severity, description=desc, items=[])
            )

        # If we didn't parse individual violations, estimate from total
        if not violations and total_violations > 0:
            errors = total_violations
            warnings = 0

    return DrcResult(
        errors=errors,
        warnings=warnings,
        violations=violations,
        unconnected=unconnected,
        report_path=output_path,
        success=(errors == 0),
    )


def format_drc_report(result: DrcResult, verbose: bool = False) -> str:
    """Format DRC result as human-readable text.

    Args:
        result: DrcResult from run_drc()
        verbose: If True, list all violations

    Returns:
        Formatted report string
    """
    lines = []

    if result.success:
        lines.append(f"✓ DRC PASSED: 0 errors, {result.warnings} warnings")
    else:
        lines.append(
            f"✗ DRC FAILED: {result.errors} errors, {result.warnings} warnings"
        )

    if result.unconnected > 0:
        lines.append(f"  Unconnected items: {result.unconnected}")

    if verbose and result.violations:
        lines.append("")
        lines.append("Violations:")
        for v in result.violations:
            marker = "ERROR" if v.severity == "error" else "WARN"
            lines.append(f"  [{marker}] {v.type}: {v.description}")

    if result.report_path:
        lines.append(f"\nFull report: {result.report_path}")

    return "\n".join(lines)


def check_kicad_cli() -> bool:
    """Check if KiCad DRC is available.

    Returns:
        True if `kicad-cli pcb drc` is available locally (KiCad 8+), or if docker
        fallback is enabled via `PARDAL_KICAD_DOCKER=1` and `docker` is available.
    """
    if _kicad_cli_supports_pcb_drc():
        return True
    if _env_truthy("PARDAL_KICAD_DOCKER"):
        return shutil.which("docker") is not None
    return False
