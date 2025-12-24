"""DRC integration via kicad-cli.

Provides programmatic DRC checking by calling kicad-cli and parsing JSON output.
"""

import subprocess
import json
import tempfile
import os
from pathlib import Path
from dataclasses import dataclass, field


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

    if output_path is None:
        fd, tmp_path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        output_path = Path(tmp_path)
    else:
        output_path = Path(output_path)

    cmd = [
        'kicad-cli', 'pcb', 'drc',
        '--output', str(output_path),
        '--format', 'json',
        '--severity-all',
        str(pcb_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    errors = 0
    warnings = 0
    violations = []
    unconnected = 0

    if output_path.exists():
        with open(output_path) as f:
            data = json.load(f)

        unconnected = len(data.get('unconnected_items', []))

        for v in data.get('violations', []):
            severity = v.get('severity', 'warning')
            if severity == 'error':
                errors += 1
            else:
                warnings += 1

            violations.append(DrcViolation(
                type=v.get('type', 'unknown'),
                severity=severity,
                description=v.get('description', ''),
                items=v.get('items', [])
            ))

    return DrcResult(
        errors=errors,
        warnings=warnings,
        violations=violations,
        unconnected=unconnected,
        report_path=output_path,
        success=(errors == 0)
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
        lines.append(f"✗ DRC FAILED: {result.errors} errors, {result.warnings} warnings")

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

    return '\n'.join(lines)


def check_kicad_cli() -> bool:
    """Check if kicad-cli is available.

    Returns:
        True if kicad-cli is available, False otherwise
    """
    try:
        result = subprocess.run(['kicad-cli', '--version'],
                                capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False
