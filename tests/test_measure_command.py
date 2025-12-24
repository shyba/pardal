"""
Tests for MEASURE commands (MEASURE DISTANCE and MEASURE NET LENGTH).
"""

import math
import pytest
from pcb_tool.commands import MeasureDistanceCommand, MeasureNetLengthCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component, Net, TraceSegment, Via


class TestMeasureDistanceCommandCreation:
    """Test MeasureDistanceCommand instantiation"""

    def test_create_with_coordinates(self):
        """Test creating command with coordinate tuples"""
        cmd = MeasureDistanceCommand((10.0, 20.0), (30.0, 40.0))
        assert cmd.start == (10.0, 20.0)
        assert cmd.end == (30.0, 40.0)

    def test_create_with_component_refs(self):
        """Test creating command with component references"""
        cmd = MeasureDistanceCommand("R1", "C1")
        assert cmd.start == "R1"
        assert cmd.end == "C1"

    def test_create_with_mixed_types(self):
        """Test creating command with mixed coordinate and ref"""
        cmd = MeasureDistanceCommand((10.0, 20.0), "R1")
        assert cmd.start == (10.0, 20.0)
        assert cmd.end == "R1"


class TestMeasureDistanceValidation:
    """Test MeasureDistanceCommand validation"""

    def test_validate_coords_always_valid(self):
        """Test that coordinate-based distance is always valid"""
        board = Board()
        cmd = MeasureDistanceCommand((0.0, 0.0), (10.0, 10.0))
        # Query commands should always return None (no undo needed)
        assert cmd.validate(board) is None

    def test_validate_component_not_found_start(self):
        """Test validation error when start component not found"""
        board = Board()
        cmd = MeasureDistanceCommand("R1", "C1")
        result = cmd.validate(board)
        assert result is not None
        assert 'Component "R1" not found' in result

    def test_validate_component_not_found_end(self):
        """Test validation error when end component not found"""
        board = Board()
        r1 = Component("R1", "10k", "R_0805", (0.0, 0.0), 0.0)
        board.add_component(r1)
        cmd = MeasureDistanceCommand("R1", "C1")
        result = cmd.validate(board)
        assert result is not None
        assert 'Component "C1" not found' in result

    def test_validate_both_components_exist(self):
        """Test validation succeeds when both components exist"""
        board = Board()
        r1 = Component("R1", "10k", "R_0805", (0.0, 0.0), 0.0)
        c1 = Component("C1", "100nF", "C_0805", (10.0, 10.0), 0.0)
        board.add_component(r1)
        board.add_component(c1)
        cmd = MeasureDistanceCommand("R1", "C1")
        # Query commands should always return None (no undo needed)
        assert cmd.validate(board) is None


class TestMeasureDistanceExecution:
    """Test MeasureDistanceCommand execution"""

    def test_execute_between_points(self):
        """Test distance calculation between two points"""
        board = Board()
        # Distance from (0, 0) to (3, 4) should be 5.0
        cmd = MeasureDistanceCommand((0.0, 0.0), (3.0, 4.0))
        result = cmd.execute(board)
        assert "DISTANCE: 5.0mm" in result

    def test_execute_between_components(self):
        """Test distance calculation between component centers"""
        board = Board()
        r1 = Component("R1", "10k", "R_0805", (0.0, 0.0), 0.0)
        c1 = Component("C1", "100nF", "C_0805", (3.0, 4.0), 0.0)
        board.add_component(r1)
        board.add_component(c1)
        cmd = MeasureDistanceCommand("R1", "C1")
        result = cmd.execute(board)
        assert "DISTANCE: 5.0mm" in result

    def test_execute_mixed_coord_and_ref(self):
        """Test distance between coordinate and component"""
        board = Board()
        c1 = Component("C1", "100nF", "C_0805", (10.0, 20.0), 0.0)
        board.add_component(c1)
        cmd = MeasureDistanceCommand((0.0, 0.0), "C1")
        result = cmd.execute(board)
        # Distance from (0,0) to (10,20) = sqrt(100 + 400) = sqrt(500) ≈ 22.4
        expected = math.sqrt(500)
        assert f"DISTANCE: {expected:.1f}mm" in result

    def test_execute_formatting_one_decimal(self):
        """Test that distance is formatted to 1 decimal place"""
        board = Board()
        # sqrt(2) ≈ 1.414...
        cmd = MeasureDistanceCommand((0.0, 0.0), (1.0, 1.0))
        result = cmd.execute(board)
        assert "DISTANCE: 1.4mm" in result

    def test_undo_returns_empty(self):
        """Test that undo returns empty string for query command"""
        board = Board()
        cmd = MeasureDistanceCommand((0.0, 0.0), (10.0, 10.0))
        result = cmd.undo(board)
        assert result == ""


class TestMeasureNetLengthCommandCreation:
    """Test MeasureNetLengthCommand instantiation"""

    def test_create_with_net_name(self):
        """Test creating command with net name"""
        cmd = MeasureNetLengthCommand("GND")
        assert cmd.net_name == "GND"


class TestMeasureNetLengthValidation:
    """Test MeasureNetLengthCommand validation"""

    def test_validate_net_not_found(self):
        """Test validation error when net not found"""
        board = Board()
        cmd = MeasureNetLengthCommand("GND")
        result = cmd.validate(board)
        assert result is not None
        assert 'Net "GND" not found' in result

    def test_validate_net_exists(self):
        """Test validation succeeds when net exists"""
        board = Board()
        net = Net("GND", "1")
        board.add_net(net)
        cmd = MeasureNetLengthCommand("GND")
        # Query commands should always return None (no undo needed)
        assert cmd.validate(board) is None


class TestMeasureNetLengthExecution:
    """Test MeasureNetLengthCommand execution"""

    def test_execute_no_segments(self):
        """Test execution with net that has no segments"""
        board = Board()
        net = Net("GND", "1")
        board.add_net(net)
        cmd = MeasureNetLengthCommand("GND")
        result = cmd.execute(board)
        assert 'NET "GND" has no routed segments' in result

    def test_execute_single_segment(self):
        """Test execution with single segment"""
        board = Board()
        net = Net("GND", "1")
        # Segment from (0, 0) to (3, 4), length = 5.0
        seg = TraceSegment("GND", (0.0, 0.0), (3.0, 4.0), "F.Cu", 0.25)
        net.add_segment(seg)
        board.add_net(net)
        cmd = MeasureNetLengthCommand("GND")
        result = cmd.execute(board)
        assert 'NET "GND" total length: 5.0mm (1 segments, 0 vias)' in result

    def test_execute_multiple_segments(self):
        """Test execution with multiple segments"""
        board = Board()
        net = Net("VCC", "2")
        # Segment 1: (0, 0) to (3, 4), length = 5.0
        seg1 = TraceSegment("VCC", (0.0, 0.0), (3.0, 4.0), "F.Cu", 0.25)
        # Segment 2: (0, 0) to (6, 8), length = 10.0
        seg2 = TraceSegment("VCC", (0.0, 0.0), (6.0, 8.0), "F.Cu", 0.25)
        net.add_segment(seg1)
        net.add_segment(seg2)
        board.add_net(net)
        cmd = MeasureNetLengthCommand("VCC")
        result = cmd.execute(board)
        assert 'NET "VCC" total length: 15.0mm (2 segments, 0 vias)' in result

    def test_execute_with_vias(self):
        """Test execution counts vias correctly"""
        board = Board()
        net = Net("GND", "1")
        # Segment: (0, 0) to (3, 4), length = 5.0
        seg = TraceSegment("GND", (0.0, 0.0), (3.0, 4.0), "F.Cu", 0.25)
        net.add_segment(seg)
        # Add two vias
        via1 = Via("GND", (10.0, 10.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        via2 = Via("GND", (20.0, 20.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        net.add_via(via1)
        net.add_via(via2)
        board.add_net(net)
        cmd = MeasureNetLengthCommand("GND")
        result = cmd.execute(board)
        assert 'NET "GND" total length: 5.0mm (1 segments, 2 vias)' in result

    def test_undo_returns_empty(self):
        """Test that undo returns empty string for query command"""
        board = Board()
        net = Net("GND", "1")
        board.add_net(net)
        cmd = MeasureNetLengthCommand("GND")
        result = cmd.undo(board)
        assert result == ""


class TestMeasureDistanceParser:
    """Test parsing MEASURE DISTANCE commands"""

    def test_parse_distance_coords(self):
        """Test parsing MEASURE DISTANCE with coordinates"""
        parser = CommandParser()
        cmd = parser.parse("MEASURE DISTANCE FROM 10 20 TO 30 40")
        assert isinstance(cmd, MeasureDistanceCommand)
        assert cmd.start == (10.0, 20.0)
        assert cmd.end == (30.0, 40.0)

    def test_parse_distance_refs(self):
        """Test parsing MEASURE DISTANCE with component refs"""
        parser = CommandParser()
        cmd = parser.parse("MEASURE DISTANCE FROM R1 TO C1")
        assert isinstance(cmd, MeasureDistanceCommand)
        assert cmd.start == "R1"
        assert cmd.end == "C1"

    def test_parse_distance_mixed(self):
        """Test parsing MEASURE DISTANCE with mixed coordinate and ref"""
        parser = CommandParser()
        cmd = parser.parse("MEASURE DISTANCE FROM 10 20 TO R1")
        assert isinstance(cmd, MeasureDistanceCommand)
        assert cmd.start == (10.0, 20.0)
        assert cmd.end == "R1"

    def test_parse_distance_case_insensitive(self):
        """Test parsing is case insensitive"""
        parser = CommandParser()
        cmd = parser.parse("measure distance from 0 0 to 10 10")
        assert isinstance(cmd, MeasureDistanceCommand)
        assert cmd.start == (0.0, 0.0)
        assert cmd.end == (10.0, 10.0)


class TestMeasureNetLengthParser:
    """Test parsing MEASURE NET LENGTH commands"""

    def test_parse_net_length(self):
        """Test parsing MEASURE NET LENGTH"""
        parser = CommandParser()
        cmd = parser.parse("MEASURE NET GND LENGTH")
        assert isinstance(cmd, MeasureNetLengthCommand)
        assert cmd.net_name == "GND"

    def test_parse_net_length_complex_name(self):
        """Test parsing with complex net name"""
        parser = CommandParser()
        cmd = parser.parse("MEASURE NET /LED1 LENGTH")
        assert isinstance(cmd, MeasureNetLengthCommand)
        assert cmd.net_name == "/LED1"

    def test_parse_net_length_case_insensitive(self):
        """Test parsing is case insensitive"""
        parser = CommandParser()
        cmd = parser.parse("measure net VCC length")
        assert isinstance(cmd, MeasureNetLengthCommand)
        assert cmd.net_name == "VCC"


class TestMeasureIntegration:
    """Integration tests for MEASURE commands"""

    def test_measure_workflow(self):
        """Test complete workflow with both MEASURE commands"""
        board = Board()
        parser = CommandParser()

        # Create components
        r1 = Component("R1", "10k", "R_0805", (0.0, 0.0), 0.0)
        r2 = Component("R2", "10k", "R_0805", (30.0, 40.0), 0.0)
        board.add_component(r1)
        board.add_component(r2)

        # Create net with segments
        net = Net("GND", "1")
        seg1 = TraceSegment("GND", (0.0, 0.0), (10.0, 0.0), "F.Cu", 0.25)
        seg2 = TraceSegment("GND", (10.0, 0.0), (10.0, 10.0), "F.Cu", 0.25)
        net.add_segment(seg1)
        net.add_segment(seg2)
        board.add_net(net)

        # Test MEASURE DISTANCE
        cmd1 = parser.parse("MEASURE DISTANCE FROM R1 TO R2")
        assert cmd1.validate(board) is None
        result1 = cmd1.execute(board)
        assert "DISTANCE: 50.0mm" in result1  # sqrt(30^2 + 40^2) = 50

        # Test MEASURE NET LENGTH
        cmd2 = parser.parse("MEASURE NET GND LENGTH")
        assert cmd2.validate(board) is None
        result2 = cmd2.execute(board)
        assert 'NET "GND" total length: 20.0mm (2 segments, 0 vias)' in result2
