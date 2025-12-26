"""Tests for CLI DRC flags: --force and --warnerr."""

import subprocess
import pytest
from pathlib import Path


class TestBuildDrcFlags:
    """Tests for build command DRC flag handling."""

    @pytest.fixture
    def simple_netlist(self, tmp_path):
        """Create a simple netlist file."""
        netlist_content = """(export (version "E")
  (design
    (source "test.kicad_sch")
    (date "2024-01-01")
    (tool "Test"))
  (components
    (comp (ref "R1")
      (value "10k")
      (footprint "Resistor_SMD:R_0805_2012Metric")
      (libsource (lib "") (part "") (description ""))
      (property (name "Reference") (value "R1"))
      (sheetpath (names "/") (tstamps "/"))
      (tstamps "00000001")))
  (nets
    (net (code "1") (name "GND")
      (node (ref "R1") (pin "1")))))
"""
        netlist_path = tmp_path / "test.net"
        netlist_path.write_text(netlist_content)
        return netlist_path

    def test_build_help_shows_force_flag(self):
        """Verify --force flag appears in help text."""
        result = subprocess.run(
            ["./venv/bin/pardal", "build", "--help"],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )
        assert result.returncode == 0
        assert "--force" in result.stdout
        assert "Continue build even if DRC has errors" in result.stdout

    def test_build_help_shows_warnerr_flag(self):
        """Verify --warnerr flag appears in help text."""
        result = subprocess.run(
            ["./venv/bin/pardal", "build", "--help"],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )
        assert result.returncode == 0
        assert "--warnerr" in result.stdout
        assert "Treat DRC warnings as errors" in result.stdout

    def test_build_with_no_drc(self, simple_netlist, tmp_path):
        """Test build with --no-drc skips DRC entirely."""
        output_path = tmp_path / "output.kicad_pcb"

        result = subprocess.run(
            [
                "./venv/bin/pardal",
                "build",
                str(simple_netlist),
                "-o",
                str(output_path),
                "--no-drc",
            ],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )

        # Should succeed without running DRC
        assert result.returncode == 0
        assert output_path.exists()
        # Should not mention DRC running
        assert "Running DRC" not in result.stdout

    def test_build_with_force_continues_on_errors(self, simple_netlist, tmp_path):
        """Test build with --force continues even if DRC has errors."""
        output_path = tmp_path / "output.kicad_pcb"

        result = subprocess.run(
            [
                "./venv/bin/pardal",
                "build",
                str(simple_netlist),
                "-o",
                str(output_path),
                "--force",
            ],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )

        # Should succeed (force overrides errors)
        assert result.returncode == 0
        assert output_path.exists()
        # Should show force message if there were DRC issues
        # (The simple board may or may not have DRC issues depending on kicad-cli availability)

    def test_build_force_and_no_drc_together(self, simple_netlist, tmp_path):
        """Test that --force and --no-drc can be used together."""
        output_path = tmp_path / "output.kicad_pcb"

        result = subprocess.run(
            [
                "./venv/bin/pardal",
                "build",
                str(simple_netlist),
                "-o",
                str(output_path),
                "--force",
                "--no-drc",
            ],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )

        # Should succeed
        assert result.returncode == 0
        assert output_path.exists()


class TestDrcCommand:
    """Tests for standalone drc command."""

    @pytest.fixture
    def simple_pcb(self, tmp_path):
        """Create a simple PCB file for testing."""
        from pcb_tool.data_model import Board, Component, Pad
        from pcb_tool.kicad_writer import KicadWriter

        board = Board()
        board.width = 20.0
        board.height = 20.0

        comp = Component(
            ref="R1",
            value="10k",
            footprint="R_0805",
            position=(10.0, 10.0),
            rotation=0.0,
            layer="F.Cu",
        )
        comp.pads = [
            Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0), shape="rect"),
            Pad(number=2, position_offset=(2.0, 0.0), size=(1.0, 1.0), shape="rect"),
        ]
        board.add_component(comp)

        pcb_path = tmp_path / "test.kicad_pcb"
        KicadWriter().write(board, pcb_path)
        return pcb_path

    def test_drc_command_exists(self):
        """Verify drc command is available."""
        result = subprocess.run(
            ["./venv/bin/pardal", "drc", "--help"],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )
        assert result.returncode == 0
        assert "DRC" in result.stdout or "drc" in result.stdout.lower()

    def test_drc_on_valid_pcb(self, simple_pcb):
        """Test DRC command on a valid PCB file."""
        result = subprocess.run(
            ["./venv/bin/pardal", "drc", str(simple_pcb)],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )

        # May pass or fail depending on kicad-cli availability and board content
        # Just verify it runs
        assert "Error: PCB file not found" not in result.stderr


class TestFlagCombinations:
    """Test various flag combinations."""

    def test_warnerr_without_force_description(self):
        """Verify --warnerr description in help."""
        result = subprocess.run(
            ["./venv/bin/pardal", "build", "--help"],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )
        assert "--warnerr" in result.stdout

    def test_all_drc_flags_documented(self):
        """Verify all DRC-related flags are documented."""
        result = subprocess.run(
            ["./venv/bin/pardal", "build", "--help"],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )

        # Check all DRC flags
        assert "--no-drc" in result.stdout
        assert "--force" in result.stdout
        assert "--warnerr" in result.stdout


class TestCliReturnCodes:
    """Test CLI return codes for various scenarios."""

    @pytest.fixture
    def simple_netlist(self, tmp_path):
        """Create a simple netlist file."""
        netlist_content = """(export (version "E")
  (design
    (source "test.kicad_sch")
    (date "2024-01-01")
    (tool "Test"))
  (components
    (comp (ref "R1")
      (value "10k")
      (footprint "Resistor_SMD:R_0805_2012Metric")
      (libsource (lib "") (part "") (description ""))
      (property (name "Reference") (value "R1"))
      (sheetpath (names "/") (tstamps "/"))
      (tstamps "00000001")))
  (nets))
"""
        netlist_path = tmp_path / "test.net"
        netlist_path.write_text(netlist_content)
        return netlist_path

    def test_missing_netlist_returns_error(self, tmp_path):
        """Missing netlist should return error code."""
        output_path = tmp_path / "output.kicad_pcb"

        result = subprocess.run(
            [
                "./venv/bin/pardal",
                "build",
                "/nonexistent/file.net",
                "-o",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )

        assert result.returncode != 0

    def test_missing_output_arg_returns_error(self, simple_netlist):
        """Missing -o argument should return error."""
        result = subprocess.run(
            ["./venv/bin/pardal", "build", str(simple_netlist)],
            capture_output=True,
            text=True,
            cwd="/home/user/repos/ee/pardal-pcb",
        )

        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "error" in result.stderr.lower()
