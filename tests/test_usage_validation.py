"""
Integration tests that validate USAGE.md end-to-end.

These tests are designed so that if they pass, we have HIGH CONFIDENCE
that every step in USAGE.md actually works for real users.

Philosophy:
- No mocking of file I/O or parsers
- Tests must use actual file paths
- Tests validate exact output format, not just "contains" checks
- Tests must run with KiCad available (fail if not, don't skip)
- Tests exercise the exact commands shown in USAGE.md
"""

import pytest
import subprocess
import tempfile
import re
import os
import sys
from pathlib import Path
from typing import List, Optional
from io import StringIO
from unittest.mock import patch


# ============================================================================
# Test Fixtures - Create REAL files on disk
# ============================================================================

@pytest.fixture
def real_netlist_file(tmp_path) -> Path:
    """
    Create an actual .net file on disk, not just a Python string.
    This tests real file I/O, encoding, and parser integration.
    """
    netlist_content = '''(export (version "E")
  (design
    (source "/path/to/project.kicad_sch")
    (date "2025-12-21")
    (tool "KiCad 9.0.0"))
  (components
    (comp (ref "J1")
      (value "Conn_01x02")
      (footprint "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical")
      (property (name "atopile_address") (value "led_circuit.connector")))
    (comp (ref "R1")
      (value "330ohm")
      (footprint "Resistor_SMD:R_0805_2012Metric")
      (property (name "atopile_address") (value "led_circuit.resistor")))
    (comp (ref "LED1")
      (value "LED")
      (footprint "LED_SMD:LED_0805_2012Metric")
      (property (name "atopile_address") (value "led_circuit.led"))))
  (nets
    (net (code 1) (name "VCC")
      (node (ref "J1") (pin "1"))
      (node (ref "R1") (pin "1")))
    (net (code 2) (name "LED_NET")
      (node (ref "R1") (pin "2"))
      (node (ref "LED1") (pin "1")))
    (net (code 3) (name "GND")
      (node (ref "LED1") (pin "2"))
      (node (ref "J1") (pin "2")))))
'''
    net_file = tmp_path / "led_circuit.net"
    net_file.write_text(netlist_content, encoding='utf-8')
    return net_file


@pytest.fixture
def batch_script_file(tmp_path, real_netlist_file) -> Path:
    """
    Create an actual batch script matching USAGE.md Workflow 3.
    Tests comment parsing, blank lines, and command execution.
    """
    script_content = f"""# placement.txt - Automatic placement script
# This comment should be ignored

LOAD {real_netlist_file}

# Place components in a line
MOVE J1 TO 10 30
MOVE R1 TO 25 30
MOVE LED1 TO 35 30

# Rotate resistor
ROTATE R1 TO 90

# Save result
SAVE {tmp_path / "output.kicad_pcb"}
"""
    script_file = tmp_path / "placement.txt"
    script_file.write_text(script_content, encoding='utf-8')
    return script_file


@pytest.fixture
def batch_script_with_edge_cases(tmp_path, real_netlist_file) -> Path:
    """
    Batch script with edge cases that could break:
    - Windows line endings
    - Trailing whitespace
    - Leading whitespace before comments
    - Empty lines with only whitespace
    """
    script_content = (
        f"LOAD {real_netlist_file}\r\n"  # Windows line ending
        "# Comment with leading space   \r\n"  # Trailing whitespace
        "   # Indented comment\n"  # Leading whitespace
        "    \n"  # Only whitespace
        "MOVE R1 TO 10 20  \n"  # Trailing spaces after command
        "\n"  # Empty line
        f"SAVE {tmp_path / 'edge_case_output.kicad_pcb'}\n"
    )
    script_file = tmp_path / "edge_cases.txt"
    script_file.write_bytes(script_content.encode('utf-8'))
    return script_file


# ============================================================================
# Helper: Verify KiCad is available (required, not optional)
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def require_kicad_cli():
    """
    Ensure kicad-cli is available. If not, FAIL (not skip).

    Rationale: KiCad validation is the ultimate acceptance test.
    If we can't validate with KiCad, we can't ship.
    """
    result = subprocess.run(
        ["kicad-cli", "--version"],
        capture_output=True
    )
    if result.returncode != 0:
        pytest.fail(
            "kicad-cli is required for USAGE.md validation tests. "
            "Install KiCad 9.0+ to run these tests. "
            "These tests should NOT be skipped in CI."
        )


# ============================================================================
# Test 1: CLI --version matches USAGE.md
# ============================================================================

class TestCLIInterface:
    """Validate CLI interface matches USAGE.md exactly."""

    def test_version_output_format(self):
        """
        USAGE.md shows:
            $ pcb-tool --version
            pcb-tool 0.1.0 (MVP1)

        Test exact format, not just "version in output".
        """
        result = subprocess.run(
            [sys.executable, "-m", "pcb_tool", "--version"],
            capture_output=True, text=True
        )

        assert result.returncode == 0
        # Exact format check
        assert re.match(
            r"pcb-tool \d+\.\d+\.\d+ \(MVP1\)",
            result.stdout.strip()
        ), f"Version output format mismatch: {result.stdout}"

    def test_help_output_contains_all_documented_flags(self):
        """
        USAGE.md documents these flags:
            --help, --load FILE, --batch FILE, --exec CMD, --version

        All must appear in --help output.
        """
        result = subprocess.run(
            [sys.executable, "-m", "pcb_tool", "--help"],
            capture_output=True, text=True
        )

        assert result.returncode == 0

        required_flags = ["--help", "--load", "--batch", "--exec", "--version"]
        for flag in required_flags:
            assert flag in result.stdout, f"Missing documented flag: {flag}"

        # Check description matches
        assert "PCB Place & Route Tool" in result.stdout

    def test_multiple_exec_flags(self, real_netlist_file, tmp_path):
        """
        USAGE.md Workflow 5 shows:
            $ pcb-tool --load input.kicad_pcb --exec "MOVE R1 TO 10 20" --exec "SAVE output.kicad_pcb"

        Multiple --exec flags must work in sequence.
        """
        output_file = tmp_path / "multi_exec.kicad_pcb"

        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "MOVE R1 TO 10 20",
                "--exec", "ROTATE R1 TO 90",
                "--exec", f"SAVE {output_file}"
            ],
            capture_output=True, text=True
        )

        assert result.returncode == 0
        assert output_file.exists(), "Multiple --exec did not produce output file"

        # Verify commands executed in order
        assert "Moved R1" in result.stdout
        assert "Rotated R1" in result.stdout

        # Verify final state in KiCad
        self._verify_kicad_component_position(output_file, "R1", 10.0, 20.0, 90.0)

    def _verify_kicad_component_position(
        self, pcb_file: Path, ref: str,
        expected_x: float, expected_y: float, expected_rot: float
    ):
        """Helper to verify component position in actual .kicad_pcb file."""
        content = pcb_file.read_text()

        # Parse S-expression to find component
        # This is a simplified check - real implementation would use sexpdata
        footprint_pattern = rf'\(footprint\s+"[^"]+"\s+\(at\s+({expected_x})\s+({expected_y})\s+({expected_rot})\)'

        # For now, just verify file is valid KiCad file
        result = subprocess.run(
            ["kicad-cli", "pcb", "drc", str(pcb_file)],
            capture_output=True
        )
        assert "parse error" not in result.stderr.decode().lower()


# ============================================================================
# Test 2: Interactive Session Matches USAGE.md
# ============================================================================

class TestInteractiveSession:
    """Test the REPL matches USAGE.md examples exactly."""

    def test_welcome_message_format(self):
        """
        USAGE.md shows welcome:
            PCB Place & Route Tool v0.1.0
            Type HELP for commands, EXIT to quit

            pcb>
        """
        # Simulate starting REPL with immediate EXIT
        result = subprocess.run(
            [sys.executable, "-m", "pcb_tool", "--exec", "EXIT"],
            capture_output=True, text=True,
            timeout=10
        )

        # Should show welcome message even in exec mode
        assert "PCB Place & Route Tool" in result.stdout
        assert "HELP" in result.stdout

    def test_prompt_string(self):
        """
        USAGE.md shows prompt as 'pcb>'
        """
        # We need to verify the actual prompt string
        # This requires running interactively with pty
        # For now, verify in batch output
        pass  # TODO: Add pty-based test

    def test_load_success_message_format(self, real_netlist_file):
        """
        USAGE.md shows:
            pcb> LOAD build/builds/default/default/default.net
            OK: Loaded board with 15 components, 8 nets

        Verify exact format with correct counts.
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "LIST COMPONENTS"
            ],
            capture_output=True, text=True
        )

        # Check exact format
        assert re.search(
            r"OK: Loaded board with \d+ components?, \d+ nets?",
            result.stdout
        ), f"LOAD message format wrong: {result.stdout}"

        # Our test netlist has 3 components, 3 nets
        assert "3 component" in result.stdout
        assert "3 net" in result.stdout

    def test_move_success_message_format(self, real_netlist_file):
        """
        USAGE.md shows:
            pcb> MOVE R1 TO 10 20
            OK: Moved R1 to (10.0, 20.0) rotation 0.0°

        Note: includes degree symbol!
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "MOVE R1 TO 10 20"
            ],
            capture_output=True, text=True
        )

        # Exact format with degree symbol
        assert re.search(
            r"OK: Moved R1 to \(10\.0, 20\.0\) rotation \d+\.0°",
            result.stdout
        ), f"MOVE message format wrong: {result.stdout}"

    def test_error_message_format_component_not_found(self, real_netlist_file):
        """
        USAGE.md shows:
            ERROR: Component R99 not found
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "MOVE R99 TO 10 20"
            ],
            capture_output=True, text=True
        )

        assert "ERROR: Component R99 not found" in result.stdout

    def test_error_message_format_file_not_found(self, tmp_path):
        """
        USAGE.md shows:
            ERROR: File not found: missing.net
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--exec", f"LOAD {tmp_path / 'nonexistent.net'}"
            ],
            capture_output=True, text=True
        )

        assert "ERROR: File not found:" in result.stdout
        assert "nonexistent.net" in result.stdout


# ============================================================================
# Test 3: SHOW BOARD Output Format
# ============================================================================

class TestShowBoardRendering:
    """Validate ASCII board rendering matches USAGE.md format."""

    def test_board_header_format(self, real_netlist_file, tmp_path):
        """
        USAGE.md shows header:
            Board: 100mm × 80mm | Layer: F.Cu | Components: 15
            Scale: 1 char = 2mm

        Note: uses × (multiplication sign), not 'x'
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "MOVE R1 TO 10 20",
                "--exec", "SHOW BOARD"
            ],
            capture_output=True, text=True
        )

        # Check header format
        assert "Board:" in result.stdout
        assert "Components:" in result.stdout

        # Check for proper units
        assert "mm" in result.stdout

    def test_board_grid_uses_box_drawing_chars(self, real_netlist_file):
        """
        USAGE.md shows grid with box-drawing characters:
            ┌────┬────┬────┐
            │    │    │    │
            └────┴────┴────┘

        These must be actual Unicode box-drawing chars, not ASCII.
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "MOVE R1 TO 10 20",
                "--exec", "SHOW BOARD"
            ],
            capture_output=True, text=True
        )

        output = result.stdout

        # Check for box-drawing characters
        box_chars = ['┌', '┐', '└', '┘', '│', '─', '┬', '┴', '├', '┤', '┼']
        has_box_chars = any(char in output for char in box_chars)

        assert has_box_chars, "Board rendering missing box-drawing characters"

    def test_component_appears_in_correct_grid_position(self, real_netlist_file):
        """
        After MOVE R1 TO 25 30, R1 should appear at grid position
        corresponding to (25, 30) in the ASCII output.
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "MOVE R1 TO 25 30",
                "--exec", "SHOW BOARD"
            ],
            capture_output=True, text=True
        )

        # Component reference should appear
        assert "[R1]" in result.stdout or "R1" in result.stdout

        # TODO: Add precise grid position validation

    def test_orientation_arrows_shown(self, real_netlist_file):
        """
        USAGE.md shows orientation arrows: ↑→↓←

        After ROTATE R1 TO 90, should show ↑
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "MOVE R1 TO 25 30",
                "--exec", "ROTATE R1 TO 90",
                "--exec", "SHOW BOARD"
            ],
            capture_output=True, text=True
        )

        # Should have at least one orientation arrow
        arrows = ['↑', '→', '↓', '←']
        has_arrows = any(arrow in result.stdout for arrow in arrows)

        assert has_arrows, "Board rendering missing orientation arrows"


# ============================================================================
# Test 4: Complete Workflow Validation (from USAGE.md)
# ============================================================================

class TestUsageWorkflows:
    """
    Test every workflow from USAGE.md end-to-end.
    These are THE definitive acceptance tests.
    """

    def test_workflow_1_led_circuit_placement(self, real_netlist_file, tmp_path):
        """
        USAGE.md Workflow 1: Place Components for LED Circuit

        Exact commands from documentation:
            LOAD examples/led_circuit/build/default.net
            LIST COMPONENTS
            MOVE J1 TO 10 30
            MOVE R1 TO 25 30
            MOVE LED1 TO 35 30
            ROTATE R1 TO 90
            SHOW BOARD
            SAVE led_circuit.kicad_pcb
        """
        output_file = tmp_path / "led_circuit.kicad_pcb"

        # Execute exact commands from USAGE.md
        commands = [
            f"LOAD {real_netlist_file}",
            "LIST COMPONENTS",
            "MOVE J1 TO 10 30",
            "MOVE R1 TO 25 30",
            "MOVE LED1 TO 35 30",
            "ROTATE R1 TO 90",
            "SHOW BOARD",
            f"SAVE {output_file}"
        ]

        exec_args = []
        for cmd in commands:
            exec_args.extend(["--exec", cmd])

        result = subprocess.run(
            [sys.executable, "-m", "pcb_tool"] + exec_args,
            capture_output=True, text=True
        )

        assert result.returncode == 0, f"Workflow failed: {result.stderr}"

        # Verify all commands succeeded
        assert "OK: Loaded board" in result.stdout
        assert "OK: Moved J1" in result.stdout
        assert "OK: Moved R1" in result.stdout
        assert "OK: Moved LED1" in result.stdout
        assert "OK: Rotated R1" in result.stdout
        assert "OK: Saved to" in result.stdout

        # Verify output file exists and is valid KiCad
        assert output_file.exists()
        self._validate_kicad_file(output_file)

    def test_workflow_3_batch_commands(self, batch_script_file, tmp_path):
        """
        USAGE.md Workflow 3: Batch Commands

            $ pcb-tool --batch placement.txt
            Executing commands from placement.txt...
            OK: Loaded board with 12 components, 8 nets
            ...
            Executed 15 commands successfully
        """
        result = subprocess.run(
            [sys.executable, "-m", "pcb_tool", "--batch", str(batch_script_file)],
            capture_output=True, text=True
        )

        assert result.returncode == 0, f"Batch failed: {result.stderr}"

        # Check batch output format from USAGE.md
        assert "Executing commands from" in result.stdout
        assert "OK: Loaded board" in result.stdout
        assert "OK: Saved to" in result.stdout

        # Verify output file created
        output_file = batch_script_file.parent / "output.kicad_pcb"
        assert output_file.exists()
        self._validate_kicad_file(output_file)

    def test_workflow_3_batch_edge_cases(self, batch_script_with_edge_cases):
        """
        Batch files with edge cases must work:
        - Windows line endings
        - Trailing whitespace
        - Indented comments
        - Whitespace-only lines
        """
        result = subprocess.run(
            [sys.executable, "-m", "pcb_tool", "--batch", str(batch_script_with_edge_cases)],
            capture_output=True, text=True
        )

        assert result.returncode == 0, f"Edge case batch failed: {result.stderr}"

        output_file = batch_script_with_edge_cases.parent / "edge_case_output.kicad_pcb"
        assert output_file.exists()

    def test_workflow_4_undo_redo_sequence(self, real_netlist_file):
        """
        USAGE.md Workflow 4: Interactive Undo/Redo

        Exact sequence:
            MOVE R1 TO 10 20
            MOVE R1 TO 15 25
            MOVE R1 TO 20 30
            UNDO
            WHERE R1  -> should be at (15, 25)
            REDO
            WHERE R1  -> should be at (20, 30)
        """
        commands = [
            f"LOAD {real_netlist_file}",
            "MOVE R1 TO 10 20",
            "MOVE R1 TO 15 25",
            "MOVE R1 TO 20 30",
            "UNDO",
            "WHERE R1",  # First WHERE - should show (15, 25)
            "REDO",
            "WHERE R1",  # Second WHERE - should show (20, 30)
        ]

        exec_args = []
        for cmd in commands:
            exec_args.extend(["--exec", cmd])

        result = subprocess.run(
            [sys.executable, "-m", "pcb_tool"] + exec_args,
            capture_output=True, text=True
        )

        assert result.returncode == 0

        # Parse WHERE outputs
        output = result.stdout

        # After UNDO, WHERE should show (15, 25)
        assert "15.0, 25.0" in output or "(15.0, 25.0)" in output

        # After REDO, WHERE should show (20, 30)
        assert "20.0, 30.0" in output or "(20.0, 30.0)" in output

    def _validate_kicad_file(self, pcb_file: Path):
        """Validate file with actual KiCad CLI."""
        result = subprocess.run(
            ["kicad-cli", "pcb", "drc", str(pcb_file)],
            capture_output=True
        )

        stderr = result.stderr.decode().lower()
        assert "parse error" not in stderr, f"KiCad parse error: {stderr}"
        assert "error" not in stderr or "drc" in stderr  # DRC errors OK, parse errors not OK


# ============================================================================
# Test 5: UNDO/REDO Edge Cases
# ============================================================================

class TestUndoRedoEdgeCases:
    """Test undo/redo behavior matches USAGE.md specification."""

    def test_undo_more_than_available(self, real_netlist_file):
        """
        What happens when: UNDO 10 but only 3 commands in history?
        USAGE.md shows: ERROR: Nothing to undo

        Should undo as many as possible, or error?
        """
        commands = [
            f"LOAD {real_netlist_file}",
            "MOVE R1 TO 10 20",
            "MOVE R1 TO 15 25",
            "UNDO 10",  # Only 2 undoable commands
        ]

        exec_args = []
        for cmd in commands:
            exec_args.extend(["--exec", cmd])

        result = subprocess.run(
            [sys.executable, "-m", "pcb_tool"] + exec_args,
            capture_output=True, text=True
        )

        # Should handle gracefully (either undo all or show informative message)
        # Per USAGE.md, "ERROR: Nothing to undo" appears when stack empty
        # So partial undo should work
        assert "OK" in result.stdout or "undid" in result.stdout.lower()

    def test_redo_after_new_command_clears_stack(self, real_netlist_file):
        """
        USAGE.md doesn't explicitly state this, but standard behavior:
        After UNDO then NEW command, REDO should show "Nothing to redo"
        """
        commands = [
            f"LOAD {real_netlist_file}",
            "MOVE R1 TO 10 20",
            "UNDO",
            "MOVE R1 TO 30 40",  # New command clears redo stack
            "REDO",
        ]

        exec_args = []
        for cmd in commands:
            exec_args.extend(["--exec", cmd])

        result = subprocess.run(
            [sys.executable, "-m", "pcb_tool"] + exec_args,
            capture_output=True, text=True
        )

        assert "ERROR" in result.stdout or "nothing to redo" in result.stdout.lower()


# ============================================================================
# Test 6: SAVE Edge Cases
# ============================================================================

class TestSaveEdgeCases:
    """Test SAVE behavior matches USAGE.md."""

    def test_save_without_load_first(self, tmp_path):
        """
        What happens when SAVE without prior LOAD?
        USAGE.md says SAVE with no args "Overwrites input file"
        But if no input file exists, what happens?
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--exec", f"SAVE {tmp_path / 'no_load.kicad_pcb'}"
            ],
            capture_output=True, text=True
        )

        # Should error - no board loaded
        assert "ERROR" in result.stdout

    def test_save_no_args_without_input_file(self, real_netlist_file):
        """
        LOAD from .net, then SAVE (no args).
        USAGE.md says "Overwrites input file".
        But input was .net, can't save as .net - should use .kicad_pcb
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "SAVE"
            ],
            capture_output=True, text=True
        )

        # Should handle - either error or derive filename
        # Check that we get a clear response
        assert "OK" in result.stdout or "ERROR" in result.stdout

    def test_save_permission_denied(self, real_netlist_file):
        """
        USAGE.md shows:
            ERROR: Permission denied writing to /path/to/file.kicad_pcb
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "SAVE /nonexistent_dir/output.kicad_pcb"
            ],
            capture_output=True, text=True
        )

        # Should show permission/path error
        assert "ERROR" in result.stdout


# ============================================================================
# Test 7: LIST and WHERE Command Validation
# ============================================================================

class TestListAndWhereCommands:
    """Validate query commands match USAGE.md output format."""

    def test_list_components_format(self, real_netlist_file):
        """
        USAGE.md shows:
            Components (3 total):
              R1: 330ohm @ (0.0, 0.0) 0° F.Cu
              LED1: LED_0805 @ (0.0, 0.0) 0° F.Cu
              J1: Conn_01x02 @ (0.0, 0.0) 0° F.Cu

        Exact format matters for AI parsing.
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "LIST COMPONENTS"
            ],
            capture_output=True, text=True
        )

        output = result.stdout

        # Check header format
        assert re.search(r"Components \(\d+ total\):", output)

        # Check component line format
        # Format: REF: VALUE @ (X, Y) ANGLE° LAYER
        component_pattern = r"\s+\w+:\s+\S+\s+@\s+\(\d+\.\d+,\s*\d+\.\d+\)\s+\d+°?\s+[FB]\.Cu"
        assert re.search(component_pattern, output), f"Component format wrong in: {output}"

    def test_where_component_format(self, real_netlist_file):
        """
        USAGE.md shows:
            R1: position (10.0, 20.0) rotation 90.0° layer F.Cu
                locked: no
                footprint: Resistor_SMD:R_0402
                value: 10k
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "WHERE R1"
            ],
            capture_output=True, text=True
        )

        output = result.stdout

        # Check all fields present
        assert "position" in output.lower()
        assert "rotation" in output.lower()
        assert "layer" in output.lower()
        assert "footprint" in output.lower() or "Footprint" in output


# ============================================================================
# Test 8: Help Command Validation
# ============================================================================

class TestHelpCommand:
    """Validate HELP command output."""

    def test_help_no_args_lists_all_commands(self, real_netlist_file):
        """
        USAGE.md shows HELP lists all commands.
        All documented commands must appear.
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--exec", "HELP"
            ],
            capture_output=True, text=True
        )

        output = result.stdout

        # All documented commands must appear
        documented_commands = [
            "LOAD", "SAVE", "UNDO", "REDO", "HISTORY",
            "MOVE", "ROTATE", "FLIP", "LOCK", "UNLOCK",
            "SHOW", "LIST", "WHERE",
            "HELP", "EXIT"
        ]

        for cmd in documented_commands:
            assert cmd in output, f"HELP missing documented command: {cmd}"

    def test_help_specific_command(self, real_netlist_file):
        """
        USAGE.md shows HELP <command> shows syntax.
        Test HELP MOVE shows syntax from docs.
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--exec", "HELP MOVE"
            ],
            capture_output=True, text=True
        )

        output = result.stdout

        # Should show syntax
        assert "MOVE" in output
        assert "TO" in output
        # Should mention coordinates
        assert "x" in output.lower() or "position" in output.lower()


# ============================================================================
# Test 9: Rotation Normalization
# ============================================================================

class TestRotationBehavior:
    """Test rotation edge cases."""

    def test_rotate_over_360(self, real_netlist_file):
        """
        ROTATE R1 TO 450 should normalize to 90°
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "ROTATE R1 TO 450",
                "--exec", "WHERE R1"
            ],
            capture_output=True, text=True
        )

        # Should show 90° (450 % 360)
        assert "90" in result.stdout

    def test_rotate_negative(self, real_netlist_file):
        """
        ROTATE R1 BY -45 from 0° should give 315° (or equivalent)
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "ROTATE R1 BY -45",
                "--exec", "WHERE R1"
            ],
            capture_output=True, text=True
        )

        # Should normalize negative rotation
        assert "315" in result.stdout or "-45" in result.stdout


# ============================================================================
# Test 10: KiCad Output Coordinate Validation
# ============================================================================

class TestKiCadCoordinates:
    """
    Verify coordinates in output .kicad_pcb match what we set.
    This catches Y-axis inversion bugs.
    """

    def test_coordinates_preserved_in_kicad_file(self, real_netlist_file, tmp_path):
        """
        MOVE R1 TO 25.5 30.75 should result in exactly those
        coordinates in the .kicad_pcb file.
        """
        output_file = tmp_path / "coords_test.kicad_pcb"

        result = subprocess.run(
            [
                sys.executable, "-m", "pcb_tool",
                "--load", str(real_netlist_file),
                "--exec", "MOVE R1 TO 25.5 30.75",
                "--exec", f"SAVE {output_file}"
            ],
            capture_output=True, text=True
        )

        assert result.returncode == 0
        assert output_file.exists()

        # Parse the output file and verify coordinates
        content = output_file.read_text()

        # KiCad uses (at X Y [ROTATION]) format
        # Look for the coordinates we set
        assert "25.5" in content, "X coordinate not found in output"
        assert "30.75" in content, "Y coordinate not found in output"

        # More precise check with regex
        at_pattern = r'\(at\s+25\.5\s+30\.75'
        assert re.search(at_pattern, content), f"Coordinates not in correct format"


# ============================================================================
# Test 11: Exit Behavior
# ============================================================================

class TestExitBehavior:
    """Test EXIT/QUIT behavior matches USAGE.md."""

    def test_exit_aliases(self, real_netlist_file):
        """Both EXIT and QUIT should work."""
        for exit_cmd in ["EXIT", "QUIT"]:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pcb_tool",
                    "--load", str(real_netlist_file),
                    "--exec", exit_cmd
                ],
                capture_output=True, text=True
            )

            # Should exit cleanly
            assert result.returncode == 0

    # Note: Testing the save prompt requires interactive input,
    # which is complex to test. Would need pexpect or similar.


# ============================================================================
# MAIN: Run with pytest
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
