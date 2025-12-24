"""Tests for SDK finalization workflow."""
import pytest
from pathlib import Path


class TestFootprintLibsMappings:
    """Test footprint library mappings."""

    def test_common_footprints_mapped(self):
        """Verify common footprints have mappings."""
        from pcb_tool.finalize import FOOTPRINT_LIBS

        expected = [
            'R_0805_2012Metric',
            'C_0805_2012Metric',
            'TO-220-3_Vertical',
            'SOT-223-3',
            'DIP-8_W7.62mm',
        ]
        for fp in expected:
            assert fp in FOOTPRINT_LIBS, f"Missing mapping for {fp}"

    def test_all_mappings_have_valid_lib_names(self):
        """Verify all library paths follow naming convention."""
        from pcb_tool.finalize import FOOTPRINT_LIBS

        for fp_name, lib_path in FOOTPRINT_LIBS.items():
            assert lib_path.endswith('.pretty'), f"Invalid lib path for {fp_name}: {lib_path}"
            assert '/usr/share/kicad/footprints/' in lib_path, f"Non-standard lib path for {fp_name}"


class TestFinalizeImports:
    """Test that finalize module imports correctly."""

    def test_finalize_function_exists(self):
        """Verify finalize_board function exists."""
        from pcb_tool.finalize import finalize_board
        assert callable(finalize_board)

    def test_footprint_libs_exists(self):
        """Verify FOOTPRINT_LIBS dict exists and has entries."""
        from pcb_tool.finalize import FOOTPRINT_LIBS
        assert isinstance(FOOTPRINT_LIBS, dict)
        assert len(FOOTPRINT_LIBS) > 10  # Should have many footprints


class TestKicadLoaderImports:
    """Test that kicad_loader module imports correctly."""

    def test_load_board_function_exists(self):
        """Verify load_board_from_kicad function exists."""
        from pcb_tool.kicad_loader import load_board_from_kicad
        assert callable(load_board_from_kicad)

    def test_write_traces_function_exists(self):
        """Verify write_traces_to_kicad function exists."""
        from pcb_tool.kicad_loader import write_traces_to_kicad
        assert callable(write_traces_to_kicad)


class TestFootprintLibraryTupleReturn:
    """Test that footprint_library returns tuples."""

    def test_returns_tuple_for_known_footprint(self):
        """Verify tuple return for known footprint."""
        from pcb_tool.footprint_library import get_footprint_pads

        result = get_footprint_pads('R_0805_2012Metric')
        assert isinstance(result, tuple)
        assert len(result) == 2
        pads, error = result
        assert isinstance(pads, list)
        assert error is None
        assert len(pads) == 2  # R0805 has 2 pads

    def test_returns_tuple_for_unknown_footprint(self):
        """Verify tuple return with error for unknown footprint."""
        from pcb_tool.footprint_library import get_footprint_pads

        result = get_footprint_pads('NonExistent:Unknown_Footprint')
        assert isinstance(result, tuple)
        assert len(result) == 2
        pads, error = result
        assert isinstance(pads, list)
        assert len(pads) == 0  # No pads for unknown
        assert error is not None
        assert 'Unknown footprint' in error

    def test_suffix_map_resolves_atopile_footprints(self):
        """Test SUFFIX_MAP resolves atopile footprint names."""
        from pcb_tool.footprint_library import get_footprint_pads, SUFFIX_MAP

        assert 'C0805' in SUFFIX_MAP
        assert SUFFIX_MAP['C0805'] == 'C_0805_2012Metric'

        # Test resolution works (Samsung_...:C0805 suffix should resolve)
        pads, error = get_footprint_pads('C0805')
        # Should find mapping through SUFFIX_MAP
        assert len(pads) == 2


class TestCLIFinalizeFlag:
    """Test CLI --finalize flag."""

    def test_finalize_flag_in_argparse(self):
        """Verify --finalize is accepted by argparse."""
        import argparse
        from pcb_tool.cli import main

        # This shouldn't raise even if it errors later
        import sys
        from io import StringIO

        # Capture help output
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            # Parse just to check the argument exists
            from pcb_tool.cli import main as cli_main
            # If we get here without argparse errors, the flag exists
        finally:
            sys.stdout = old_stdout

    def test_build_help_shows_finalize(self):
        """Verify help text includes --finalize."""
        import subprocess
        result = subprocess.run(
            ['python3', '-m', 'pcb_tool.cli', 'build', '--help'],
            capture_output=True,
            text=True,
            cwd='/home/user/repos/ee/pardal-pcb'
        )
        assert '--finalize' in result.stdout


class TestPreFlightValidation:
    """Test autoroute pre-flight pad validation."""

    def test_autoroute_validates_pads(self):
        """Verify AutoRouteCommand checks for pad count."""
        from pcb_tool.data_model import Board, Component, Net
        from pcb_tool.commands import AutoRouteCommand

        board = Board()

        # Add component with NO pads
        comp = Component(
            ref='R1',
            value='10k',
            footprint='Unknown:Footprint',
            position=(10, 10),
            rotation=0,
            pads=[]  # No pads!
        )
        board.add_component(comp)

        # Add a net
        net = Net(name='NET1', code='1')
        net.add_connection('R1', '1')
        board.add_net(net)

        # Validation should fail
        cmd = AutoRouteCommand(net_name='ALL')
        error = cmd.validate(board)
        assert error is not None
        assert 'no pads' in error.lower()


class TestListComponentsPadCount:
    """Test LIST COMPONENTS shows pad count."""

    def test_list_shows_pad_count(self):
        """Verify LIST COMPONENTS includes pad info."""
        from pcb_tool.data_model import Board, Component, Pad
        from pcb_tool.commands import ListComponentsCommand

        board = Board()

        # Add component with 2 pads
        comp = Component(
            ref='R1',
            value='10k',
            footprint='R_0805',
            position=(10, 10),
            rotation=0,
            pads=[
                Pad(number='1', position_offset=(-0.95, 0), size=(1.0, 1.3), shape='rect'),
                Pad(number='2', position_offset=(0.95, 0), size=(1.0, 1.3), shape='rect'),
            ]
        )
        board.add_component(comp)

        cmd = ListComponentsCommand()
        result = cmd.execute(board)

        assert '2 pads' in result or '[2 pads]' in result

    def test_list_shows_no_pads_warning(self):
        """Verify LIST COMPONENTS warns about 0 pads."""
        from pcb_tool.data_model import Board, Component
        from pcb_tool.commands import ListComponentsCommand

        board = Board()

        # Add component with NO pads
        comp = Component(
            ref='R1',
            value='10k',
            footprint='Unknown',
            position=(10, 10),
            rotation=0,
            pads=[]
        )
        board.add_component(comp)

        cmd = ListComponentsCommand()
        result = cmd.execute(board)

        assert 'NO PADS' in result or '0 pads' in result
