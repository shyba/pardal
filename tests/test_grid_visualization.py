"""
Integration test for routing grid visualization in SHOW BOARD command.

Tests that routing grid statistics are properly displayed when
the SHOW BOARD command is executed on a board with routing.
"""

import pytest
from pcb_tool.data_model import Board, Component, Net, TraceSegment, Via
from pcb_tool.commands import ShowBoardCommand


class TestGridVisualization:
    """Test grid visualization integration with SHOW BOARD command."""

    def test_show_board_with_routing_displays_grid_stats(self):
        """Test that SHOW BOARD displays grid statistics when routing exists."""
        # Create a simple board with components and routing
        board = Board()

        # Add components
        board.components["R1"] = Component(
            ref="R1",
            value="1k",
            footprint="R_0805",
            position=(10.0, 20.0),
            rotation=0.0
        )
        board.components["R2"] = Component(
            ref="R2",
            value="1k",
            footprint="R_0805",
            position=(30.0, 20.0),
            rotation=0.0
        )

        # Add a net with routing
        net = Net(name="NET1", code="1")
        net.segments.append(TraceSegment(
            net_name="NET1",
            start=(10.0, 20.0),
            end=(30.0, 20.0),
            layer="F.Cu",
            width=0.5
        ))
        board.nets["NET1"] = net

        # Execute SHOW BOARD command
        cmd = ShowBoardCommand()
        output = cmd.execute(board)

        # Verify output contains grid statistics
        assert "Routing Grid Statistics:" in output
        assert "Grid:" in output
        assert "Total cells:" in output
        assert "F.Cu:" in output
        assert "B.Cu:" in output
        assert "routable" in output

    def test_show_board_with_vias_displays_via_stats(self):
        """Test that grid statistics include via information."""
        board = Board()

        # Add components
        board.components["J1"] = Component(
            ref="J1",
            value="Conn",
            footprint="Conn_01x02",
            position=(10.0, 20.0),
            rotation=0.0
        )

        # Add net with via
        net = Net(name="GND", code="1")
        net.segments.append(TraceSegment(
            net_name="GND",
            start=(10.0, 20.0),
            end=(15.0, 20.0),
            layer="F.Cu",
            width=0.8
        ))
        net.vias.append(Via(
            net_name="GND",
            position=(15.0, 20.0),
            size=0.8,
            drill=0.4,
            layers=("F.Cu", "B.Cu")
        ))
        board.nets["GND"] = net

        # Execute SHOW BOARD command
        cmd = ShowBoardCommand()
        output = cmd.execute(board)

        # Verify via statistics are included
        assert "Routing Grid Statistics:" in output
        assert "Vias:" in output or "vias" in output

    def test_show_board_without_routing_no_grid_stats(self):
        """Test that grid statistics are not shown when no routing exists."""
        board = Board()

        # Add components only (no routing)
        board.components["R1"] = Component(
            ref="R1",
            value="1k",
            footprint="R_0805",
            position=(10.0, 20.0),
            rotation=0.0
        )

        # Execute SHOW BOARD command
        cmd = ShowBoardCommand()
        output = cmd.execute(board)

        # Verify no grid statistics (since no routing)
        assert "Routing Grid Statistics:" not in output

    def test_show_board_grid_stats_format(self):
        """Test that grid statistics are properly formatted."""
        board = Board()

        # Add components
        for i in range(3):
            board.components[f"R{i+1}"] = Component(
                ref=f"R{i+1}",
                value="1k",
                footprint="R_0805",
                position=(10.0 + i * 10.0, 20.0),
                rotation=0.0
            )

        # Add multiple nets with routing
        for i in range(2):
            net = Net(name=f"NET{i+1}", code=str(i+1))
            net.segments.append(TraceSegment(
                net_name=f"NET{i+1}",
                start=(10.0 + i * 10.0, 20.0),
                end=(20.0 + i * 10.0, 20.0),
                layer="F.Cu",
                width=0.5
            ))
            board.nets[f"NET{i+1}"] = net

        # Execute SHOW BOARD command
        cmd = ShowBoardCommand()
        output = cmd.execute(board)

        # Verify statistics format
        assert "Routing Grid Statistics:" in output
        assert "×" in output or "x" in output  # Grid dimensions separator
        assert "mm resolution" in output
        assert "obstacles" in output
        assert "%" in output  # Percentage of routable cells

    def test_show_board_grid_stats_accuracy(self):
        """Test that grid statistics reflect actual board state."""
        board = Board()

        # Add a single component
        board.components["R1"] = Component(
            ref="R1",
            value="1k",
            footprint="R_0805",
            position=(50.0, 50.0),
            rotation=0.0
        )

        # Add a single trace
        net = Net(name="NET1", code="1")
        net.segments.append(TraceSegment(
            net_name="NET1",
            start=(40.0, 50.0),
            end=(60.0, 50.0),
            layer="F.Cu",
            width=0.5
        ))
        board.nets["NET1"] = net

        # Execute SHOW BOARD command
        cmd = ShowBoardCommand()
        output = cmd.execute(board)

        # Verify statistics are present
        assert "Routing Grid Statistics:" in output

        # Both layers should have obstacles (component marked on both)
        assert "F.Cu:" in output
        assert "B.Cu:" in output

        # Routable percentage should be high (most of board is free)
        # Not checking exact value as it depends on board dimensions
        lines = output.split("\n")
        stats_section = [l for l in lines if "routable" in l]
        assert len(stats_section) >= 2  # At least F.Cu and B.Cu stats

    def test_show_board_empty_board_no_grid_stats(self):
        """Test that empty board doesn't show grid statistics."""
        board = Board()

        # Empty board
        cmd = ShowBoardCommand()
        output = cmd.execute(board)

        # Should show message about empty board
        assert "No components" in output or "empty board" in output
        assert "Routing Grid Statistics:" not in output
