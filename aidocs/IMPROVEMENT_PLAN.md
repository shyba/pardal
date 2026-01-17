# Plan: Pardal CLI Redesign + DRC Integration

## Summary

Redesign pcb_tool as `pardal` CLI with discoverable subcommands, integrate kicad-cli DRC, and update documentation for AI model awareness.

```
pardal --help
pardal build netlist.net -p placement.txt -o board.kicad_pcb
pardal drc board.kicad_pcb
pardal place netlist.net -p placement.txt -o board.kicad_pcb
pardal route board.kicad_pcb -o routed.kicad_pcb
pardal repl  # interactive mode
```

---

## Phase 1: CLI Restructure + DRC

### 1.1 Create `pardal` CLI entry point

**File:** `pcb_tool/cli.py` (NEW)

```python
#!/usr/bin/env python3
"""Pardal PCB Tool - CLI entry point."""

import argparse
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(
        prog='pardal',
        description='PCB layout tool with autorouting and DRC'
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # pardal build
    build_parser = subparsers.add_parser('build', help='Build PCB from netlist')
    build_parser.add_argument('netlist', type=Path, help='Input netlist (.net)')
    build_parser.add_argument('-p', '--placement', type=Path, help='Placement script')
    build_parser.add_argument('-o', '--output', type=Path, required=True, help='Output .kicad_pcb')
    build_parser.add_argument('--no-drc', action='store_true', help='Skip DRC check')
    build_parser.add_argument('--route', action='store_true', help='Run autorouter')

    # pardal drc
    drc_parser = subparsers.add_parser('drc', help='Run DRC on PCB file')
    drc_parser.add_argument('pcb', type=Path, help='Input .kicad_pcb file')
    drc_parser.add_argument('-o', '--output', type=Path, help='Output report file')
    drc_parser.add_argument('--format', choices=['text', 'json'], default='text')

    # pardal place
    place_parser = subparsers.add_parser('place', help='Place components from netlist')
    place_parser.add_argument('netlist', type=Path, help='Input netlist (.net)')
    place_parser.add_argument('-p', '--placement', type=Path, help='Placement script')
    place_parser.add_argument('-o', '--output', type=Path, required=True, help='Output .kicad_pcb')

    # pardal route
    route_parser = subparsers.add_parser('route', help='Autoroute existing PCB')
    route_parser.add_argument('pcb', type=Path, help='Input .kicad_pcb file')
    route_parser.add_argument('-o', '--output', type=Path, help='Output .kicad_pcb')
    route_parser.add_argument('--net', help='Route specific net (default: ALL)')

    # pardal repl
    repl_parser = subparsers.add_parser('repl', help='Interactive REPL mode')
    repl_parser.add_argument('--batch', type=Path, help='Run batch script')

    args = parser.parse_args()

    if args.command == 'build':
        return cmd_build(args)
    elif args.command == 'drc':
        return cmd_drc(args)
    elif args.command == 'place':
        return cmd_place(args)
    elif args.command == 'route':
        return cmd_route(args)
    elif args.command == 'repl':
        return cmd_repl(args)
    else:
        parser.print_help()
        return 1
```

### 1.2 Add kicad-cli DRC wrapper

**File:** `pcb_tool/drc.py` (NEW)

```python
"""DRC integration via kicad-cli."""

import subprocess
import json
import tempfile
from pathlib import Path
from dataclasses import dataclass

@dataclass
class DrcResult:
    errors: int
    warnings: int
    violations: list
    report_path: Path | None

def run_drc(pcb_path: Path, output_path: Path | None = None) -> DrcResult:
    """Run KiCad DRC via kicad-cli.

    Args:
        pcb_path: Path to .kicad_pcb file
        output_path: Optional path for report (default: temp file)

    Returns:
        DrcResult with error/warning counts and violations
    """
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix='.json')

    result = subprocess.run([
        'kicad-cli', 'pcb', 'drc',
        '--output', str(output_path),
        '--format', 'json',
        '--severity-all',
        str(pcb_path)
    ], capture_output=True, text=True)

    errors = 0
    warnings = 0
    violations = []

    if Path(output_path).exists():
        with open(output_path) as f:
            data = json.load(f)

        for violation in data.get('violations', []):
            severity = violation.get('severity', 'warning')
            if severity == 'error':
                errors += 1
            else:
                warnings += 1
            violations.append(violation)

    return DrcResult(
        errors=errors,
        warnings=warnings,
        violations=violations,
        report_path=Path(output_path)
    )
```

### 1.3 Update pyproject.toml entry point

```toml
[project.scripts]
pardal = "pcb_tool.cli:main"
```

---

## Phase 2: Documentation for AI Models

### 2.1 Update CLAUDE.md

Add pardal CLI documentation so AI models know capabilities:

```markdown
## Pardal PCB Tool

Command-line PCB tool with placement, autorouting, and DRC.

### Quick Start
```bash
# Build PCB from atopile netlist
pardal build project.net -p placement.txt -o board.kicad_pcb

# Check DRC
pardal drc board.kicad_pcb

# Route existing PCB
pardal route board.kicad_pcb -o routed.kicad_pcb
```

### Commands
- `pardal build` - One-shot: load netlist → place → optionally route → save → DRC
- `pardal drc` - Run KiCad DRC check
- `pardal place` - Place components only
- `pardal route` - Autoroute existing PCB
- `pardal repl` - Interactive mode
```

---

## Implementation Tasks

| # | Task | File | Depends |
|---|------|------|---------|
| 1 | Create CLI entry point | `pcb_tool/cli.py` | - |
| 2 | Create DRC module | `pcb_tool/drc.py` | - |
| 3 | Implement cmd_build() | `pcb_tool/cli.py` | 1, 2 |
| 4 | Implement cmd_drc() | `pcb_tool/cli.py` | 1, 2 |
| 5 | Implement cmd_place() | `pcb_tool/cli.py` | 1 |
| 6 | Implement cmd_route() | `pcb_tool/cli.py` | 1 |
| 7 | Update pyproject.toml | `pyproject.toml` | - |
| 8 | Update CLAUDE.md | `../CLAUDE.md` | - |
| 9 | Add tests | `tests/test_cli.py` | 1-6 |
| 10 | Update README | `README.md` | 1-6 |

### Parallel Execution Groups

**Group A (independent, run in parallel):**
- Task 2: Create DRC module
- Task 7: Update pyproject.toml
- Task 8: Update CLAUDE.md

**Group B (after Group A):**
- Task 1: Create CLI entry point (needs pyproject.toml ready)

**Group C (after Task 1):**
- Tasks 3-6: Implement subcommands (can be parallel)

**Group D (after Group C):**
- Tasks 9-10: Tests and docs

---

## Success Criteria

```bash
# These commands should work after implementation:
pardal --help                          # Shows all subcommands
pardal build --help                    # Shows build options
pardal drc board.kicad_pcb             # Runs DRC, prints report
pardal build net.net -o out.kicad_pcb  # Builds and runs DRC
```
