"""Tests for pardal CLI."""

import pytest
import subprocess
import tempfile
from pathlib import Path

from pcb_tool.cli import main, cmd_build, cmd_drc, cmd_place
from pcb_tool.drc import run_drc, check_kicad_cli, DrcResult


class TestDrcModule:
    """Tests for DRC module."""

    def test_check_kicad_cli_available(self):
        """Test kicad-cli availability check."""
        # This should return True on systems with KiCad installed
        result = check_kicad_cli()
        assert isinstance(result, bool)

    def test_run_drc_file_not_found(self):
        """Test DRC with non-existent file."""
        with pytest.raises(FileNotFoundError):
            run_drc(Path("/nonexistent/file.kicad_pcb"))

    def test_run_drc_returns_result(self, tmp_path):
        """Test DRC returns proper result structure."""
        # Create a minimal PCB file
        pcb_file = tmp_path / "test.kicad_pcb"
        pcb_file.write_text("""(kicad_pcb (version 20240108) (generator "test")
  (general (thickness 1.6) (legacy_teardrops no))
  (paper "A4")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
  (setup (pad_to_mask_clearance 0))
  (net 0 "")
)
""")

        if not check_kicad_cli():
            pytest.skip("kicad-cli not available")

        result = run_drc(pcb_file)

        assert isinstance(result, DrcResult)
        assert isinstance(result.errors, int)
        assert isinstance(result.warnings, int)
        assert isinstance(result.violations, list)


class TestCliHelp:
    """Test CLI help output."""

    def test_pardal_help(self):
        """Test pardal --help shows subcommands."""
        result = subprocess.run(
            ['./venv/bin/pardal', '--help'],
            capture_output=True,
            text=True,
            cwd='/home/user/repos/ee/pardal-pcb'
        )
        assert result.returncode == 0
        assert 'build' in result.stdout
        assert 'drc' in result.stdout
        assert 'place' in result.stdout
        assert 'route' in result.stdout
        assert 'repl' in result.stdout

    def test_pardal_build_help(self):
        """Test pardal build --help shows options."""
        result = subprocess.run(
            ['./venv/bin/pardal', 'build', '--help'],
            capture_output=True,
            text=True,
            cwd='/home/user/repos/ee/pardal-pcb'
        )
        assert result.returncode == 0
        assert '--placement' in result.stdout
        assert '--output' in result.stdout
        assert '--route' in result.stdout
        assert '--no-drc' in result.stdout

    def test_pardal_drc_help(self):
        """Test pardal drc --help shows options."""
        result = subprocess.run(
            ['./venv/bin/pardal', 'drc', '--help'],
            capture_output=True,
            text=True,
            cwd='/home/user/repos/ee/pardal-pcb'
        )
        assert result.returncode == 0
        assert '--format' in result.stdout
        assert 'json' in result.stdout


class TestCliBuild:
    """Test pardal build command."""

    @pytest.fixture
    def netlist_path(self):
        """Path to test netlist."""
        path = Path('/home/user/repos/ee/pardal-pcb/tests/fixtures/injector_2ch.net')
        if not path.exists():
            pytest.skip("Test netlist not found")
        return path

    def test_build_with_no_drc(self, netlist_path, tmp_path):
        """Test build command with --no-drc flag."""
        output = tmp_path / "test.kicad_pcb"

        result = subprocess.run(
            ['./venv/bin/pardal', 'build', str(netlist_path),
             '-o', str(output), '--no-drc'],
            capture_output=True,
            text=True,
            cwd='/home/user/repos/ee/pardal-pcb'
        )

        assert result.returncode == 0
        assert output.exists()
        assert 'OK: Loaded' in result.stdout
        assert 'OK: Saved' in result.stdout

    def test_build_missing_netlist(self, tmp_path):
        """Test build fails with missing netlist."""
        output = tmp_path / "test.kicad_pcb"

        result = subprocess.run(
            ['./venv/bin/pardal', 'build', '/nonexistent.net',
             '-o', str(output), '--no-drc'],
            capture_output=True,
            text=True,
            cwd='/home/user/repos/ee/pardal-pcb'
        )

        assert result.returncode != 0


class TestCliDrc:
    """Test pardal drc command."""

    def test_drc_missing_file(self):
        """Test DRC fails with missing file."""
        result = subprocess.run(
            ['./venv/bin/pardal', 'drc', '/nonexistent.kicad_pcb'],
            capture_output=True,
            text=True,
            cwd='/home/user/repos/ee/pardal-pcb'
        )

        assert result.returncode != 0
        assert 'not found' in result.stderr.lower() or 'error' in result.stderr.lower()


class TestCliPlace:
    """Test pardal place command."""

    @pytest.fixture
    def netlist_path(self):
        """Path to test netlist."""
        path = Path('/home/user/repos/ee/pardal-pcb/tests/fixtures/injector_2ch.net')
        if not path.exists():
            pytest.skip("Test netlist not found")
        return path

    def test_place_without_placement_script(self, netlist_path, tmp_path):
        """Test place command without placement script."""
        output = tmp_path / "test.kicad_pcb"

        result = subprocess.run(
            ['./venv/bin/pardal', 'place', str(netlist_path),
             '-o', str(output)],
            capture_output=True,
            text=True,
            cwd='/home/user/repos/ee/pardal-pcb'
        )

        assert result.returncode == 0
        assert output.exists()
        assert 'OK: Loaded' in result.stdout
        assert 'OK: Saved' in result.stdout
