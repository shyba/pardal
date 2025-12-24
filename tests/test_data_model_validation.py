"""Tests for data model validation."""

import pytest
from pcb_tool.data_model import Component, Net, Board


class TestComponentValidation:
    """Test Component validation in __post_init__."""

    def test_valid_component_creation(self):
        """Test creating a valid component."""
        comp = Component(
            ref="R1",
            value="10k",
            footprint="R_0805",
            position=(10.0, 20.0),
            rotation=90.0
        )
        assert comp.ref == "R1"
        assert comp.rotation == 90.0

    def test_component_rotation_range_valid(self):
        """Test valid rotation values."""
        comp = Component(
            ref="R1",
            value="10k",
            footprint="R_0805",
            position=(0.0, 0.0),
            rotation=0.0
        )
        assert comp.rotation == 0.0

        comp2 = Component(
            ref="R2",
            value="10k",
            footprint="R_0805",
            position=(0.0, 0.0),
            rotation=359.9
        )
        assert comp2.rotation == 359.9

    def test_component_empty_ref_raises_error(self):
        """Test that empty ref raises ValueError."""
        with pytest.raises(ValueError, match="ref must be non-empty string"):
            Component(
                ref="",
                value="10k",
                footprint="R_0805",
                position=(0.0, 0.0),
                rotation=0.0
            )

    def test_component_invalid_rotation_below_range(self):
        """Test rotation below 0 raises ValueError."""
        with pytest.raises(ValueError, match="Rotation must be in \\[0, 360\\)"):
            Component(
                ref="R1",
                value="10k",
                footprint="R_0805",
                position=(0.0, 0.0),
                rotation=-1.0
            )

    def test_component_invalid_rotation_above_range(self):
        """Test rotation >= 360 raises ValueError."""
        with pytest.raises(ValueError, match="Rotation must be in \\[0, 360\\)"):
            Component(
                ref="R1",
                value="10k",
                footprint="R_0805",
                position=(0.0, 0.0),
                rotation=360.0
            )

    def test_component_invalid_rotation_way_above(self):
        """Test rotation >> 360 raises ValueError."""
        with pytest.raises(ValueError, match="Rotation must be in \\[0, 360\\)"):
            Component(
                ref="R1",
                value="10k",
                footprint="R_0805",
                position=(0.0, 0.0),
                rotation=450.0
            )

    def test_component_invalid_position_not_tuple(self):
        """Test non-tuple position raises ValueError."""
        with pytest.raises(ValueError, match="Position must be tuple of 2 elements"):
            Component(
                ref="R1",
                value="10k",
                footprint="R_0805",
                position=[0.0, 0.0],  # List, not tuple
                rotation=0.0
            )

    def test_component_invalid_position_wrong_length(self):
        """Test position with wrong length raises ValueError."""
        with pytest.raises(ValueError, match="Position must be tuple of 2 elements"):
            Component(
                ref="R1",
                value="10k",
                footprint="R_0805",
                position=(0.0, 0.0, 0.0),  # 3 elements
                rotation=0.0
            )

    def test_component_invalid_position_non_numeric(self):
        """Test position with non-numeric values raises ValueError."""
        with pytest.raises(ValueError, match="Position coordinates must be numeric"):
            Component(
                ref="R1",
                value="10k",
                footprint="R_0805",
                position=("x", "y"),
                rotation=0.0
            )

    def test_component_empty_footprint_raises_error(self):
        """Test that empty footprint raises ValueError."""
        with pytest.raises(ValueError, match="footprint must be non-empty string"):
            Component(
                ref="R1",
                value="10k",
                footprint="",
                position=(0.0, 0.0),
                rotation=0.0
            )

    def test_component_rotation_non_numeric(self):
        """Test non-numeric rotation raises ValueError."""
        with pytest.raises(ValueError, match="Rotation must be numeric"):
            Component(
                ref="R1",
                value="10k",
                footprint="R_0805",
                position=(0.0, 0.0),
                rotation="90"  # String, not number
            )


class TestNetCreation:
    """Test Net creation (no validation changes)."""

    def test_net_creation(self):
        """Test basic net creation still works."""
        net = Net(name="VCC", code="1")
        assert net.name == "VCC"
        assert net.code == "1"


class TestBoardCreation:
    """Test Board creation (no validation changes)."""

    def test_board_creation(self):
        """Test basic board creation still works."""
        board = Board()
        assert len(board.components) == 0
        assert len(board.nets) == 0
