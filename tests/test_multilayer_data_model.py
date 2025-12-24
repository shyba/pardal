# tests/test_multilayer_data_model.py
"""Tests for multi-layer and net class data model extensions."""

import pytest
from pcb_tool.data_model import (
    LayerConfig, NetClass, Board, Net, TraceSegment, Via,
    STANDARD_LAYER_STACKS, VALID_COPPER_LAYERS
)


class TestLayerConfig:
    """Tests for LayerConfig dataclass."""

    def test_layer_config_creation(self):
        """Test creating a layer config with valid data."""
        config = LayerConfig(name="F.Cu", layer_type="signal", index=0)
        assert config.name == "F.Cu"
        assert config.layer_type == "signal"
        assert config.index == 0

    def test_layer_config_power(self):
        """Test creating a power layer config."""
        config = LayerConfig(name="In1.Cu", layer_type="power", index=1)
        assert config.layer_type == "power"

    def test_layer_config_invalid_name(self):
        """Test that invalid layer name raises ValueError."""
        with pytest.raises(ValueError, match="Invalid layer name"):
            LayerConfig(name="Invalid.Layer")

    def test_layer_config_invalid_type(self):
        """Test that invalid layer type raises ValueError."""
        with pytest.raises(ValueError, match="Layer type must be"):
            LayerConfig(name="F.Cu", layer_type="mixed")


class TestNetClass:
    """Tests for NetClass dataclass."""

    def test_net_class_creation(self):
        """Test creating a net class with valid data."""
        nc = NetClass(name="Power", track_width=0.5, clearance=0.3)
        assert nc.name == "Power"
        assert nc.track_width == 0.5
        assert nc.clearance == 0.3

    def test_net_class_defaults(self):
        """Test net class default values."""
        nc = NetClass(name="Default")
        assert nc.track_width == 0.25
        assert nc.clearance == 0.2
        assert nc.via_size == 0.8
        assert nc.via_drill == 0.4
        assert nc.nets == []

    def test_net_class_with_nets(self):
        """Test net class with assigned nets."""
        nc = NetClass(name="Power", track_width=0.5, nets=["VCC", "GND"])
        assert "VCC" in nc.nets
        assert "GND" in nc.nets

    def test_net_class_invalid_track_width(self):
        """Test that non-positive track width raises ValueError."""
        with pytest.raises(ValueError, match="track_width must be positive"):
            NetClass(name="Bad", track_width=0)

    def test_net_class_invalid_clearance(self):
        """Test that negative clearance raises ValueError."""
        with pytest.raises(ValueError, match="clearance must be non-negative"):
            NetClass(name="Bad", clearance=-0.1)

    def test_net_class_invalid_via_drill(self):
        """Test that via_drill >= via_size raises ValueError."""
        with pytest.raises(ValueError, match="via_drill must be smaller than via_size"):
            NetClass(name="Bad", via_size=0.4, via_drill=0.5)


class TestStandardLayerStacks:
    """Tests for standard layer stack definitions."""

    def test_2_layer_stack(self):
        """Test 2-layer stack definition."""
        stack = STANDARD_LAYER_STACKS[2]
        assert stack == ["F.Cu", "B.Cu"]

    def test_4_layer_stack(self):
        """Test 4-layer stack definition."""
        stack = STANDARD_LAYER_STACKS[4]
        assert stack == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        assert len(stack) == 4

    def test_6_layer_stack(self):
        """Test 6-layer stack definition."""
        stack = STANDARD_LAYER_STACKS[6]
        assert stack[0] == "F.Cu"
        assert stack[-1] == "B.Cu"
        assert len(stack) == 6

    def test_8_layer_stack(self):
        """Test 8-layer stack definition."""
        stack = STANDARD_LAYER_STACKS[8]
        assert stack[0] == "F.Cu"
        assert stack[-1] == "B.Cu"
        assert len(stack) == 8


class TestValidCopperLayers:
    """Tests for valid copper layer set."""

    def test_outer_layers_valid(self):
        """Test outer layers are valid."""
        assert "F.Cu" in VALID_COPPER_LAYERS
        assert "B.Cu" in VALID_COPPER_LAYERS

    def test_inner_layers_valid(self):
        """Test inner layers are valid."""
        for i in range(1, 31):
            assert f"In{i}.Cu" in VALID_COPPER_LAYERS


class TestBoardLayers:
    """Tests for Board multi-layer support."""

    def test_board_default_layers(self):
        """Test default board has 2 layers."""
        board = Board()
        assert board.layers == ["F.Cu", "B.Cu"]
        assert board.layer_count == 2

    def test_board_4_layer(self):
        """Test 4-layer board creation."""
        board = Board(layers=STANDARD_LAYER_STACKS[4])
        assert board.layer_count == 4
        assert board.layers[0] == "F.Cu"
        assert board.layers[-1] == "B.Cu"

    def test_board_is_valid_layer(self):
        """Test is_valid_layer method."""
        board = Board(layers=STANDARD_LAYER_STACKS[4])
        assert board.is_valid_layer("F.Cu") is True
        assert board.is_valid_layer("In1.Cu") is True
        assert board.is_valid_layer("In2.Cu") is True
        assert board.is_valid_layer("B.Cu") is True
        assert board.is_valid_layer("In3.Cu") is False

    def test_board_get_layer_index(self):
        """Test get_layer_index method."""
        board = Board(layers=STANDARD_LAYER_STACKS[4])
        assert board.get_layer_index("F.Cu") == 0
        assert board.get_layer_index("In1.Cu") == 1
        assert board.get_layer_index("In2.Cu") == 2
        assert board.get_layer_index("B.Cu") == 3

    def test_board_get_layer_index_invalid(self):
        """Test get_layer_index raises for invalid layer."""
        board = Board()  # 2-layer
        with pytest.raises(ValueError, match="not in board's layer stack"):
            board.get_layer_index("In1.Cu")

    def test_board_get_adjacent_layers(self):
        """Test get_adjacent_layers method."""
        board = Board(layers=STANDARD_LAYER_STACKS[4])
        # Top layer has only one adjacent
        assert board.get_adjacent_layers("F.Cu") == ["In1.Cu"]
        # Middle layers have two adjacent
        assert board.get_adjacent_layers("In1.Cu") == ["F.Cu", "In2.Cu"]
        assert board.get_adjacent_layers("In2.Cu") == ["In1.Cu", "B.Cu"]
        # Bottom layer has only one adjacent
        assert board.get_adjacent_layers("B.Cu") == ["In2.Cu"]

    def test_board_get_inner_layers(self):
        """Test get_inner_layers method."""
        board = Board(layers=STANDARD_LAYER_STACKS[4])
        inner = board.get_inner_layers()
        assert inner == ["In1.Cu", "In2.Cu"]

    def test_board_get_inner_layers_2_layer(self):
        """Test get_inner_layers for 2-layer board."""
        board = Board()
        inner = board.get_inner_layers()
        assert inner == []

    def test_board_invalid_layer_order(self):
        """Test that F.Cu not first raises ValueError."""
        with pytest.raises(ValueError, match="F.Cu must be the first layer"):
            Board(layers=["In1.Cu", "F.Cu", "B.Cu"])

    def test_board_invalid_layer_order_bcu(self):
        """Test that B.Cu not last raises ValueError."""
        with pytest.raises(ValueError, match="B.Cu must be the last layer"):
            Board(layers=["F.Cu", "B.Cu", "In1.Cu"])

    def test_board_invalid_layer_name(self):
        """Test that invalid layer name raises ValueError."""
        with pytest.raises(ValueError, match="Invalid copper layer"):
            Board(layers=["F.Cu", "Invalid.Cu", "B.Cu"])


class TestBoardNetClasses:
    """Tests for Board net class support."""

    def test_board_default_net_classes(self):
        """Test default board has empty net classes."""
        board = Board()
        assert board.net_classes == {}

    def test_board_add_net_class(self):
        """Test adding a net class to board."""
        board = Board()
        nc = NetClass(name="Power", track_width=0.5)
        board.add_net_class(nc)
        assert "Power" in board.net_classes
        assert board.net_classes["Power"].track_width == 0.5

    def test_board_get_net_width(self):
        """Test getting net width from class."""
        board = Board()
        board.add_net(Net(name="VCC", code="1"))
        board.add_net_class(NetClass(name="Power", track_width=0.5))
        board.assign_net_to_class("VCC", "Power")

        assert board.get_net_width("VCC") == 0.5

    def test_board_get_net_width_no_class(self):
        """Test getting net width when no class assigned."""
        board = Board()
        board.add_net(Net(name="SIG", code="1", track_width=0.3))

        assert board.get_net_width("SIG") == 0.3

    def test_board_get_net_width_unknown_net(self):
        """Test getting net width for unknown net returns default."""
        board = Board()
        assert board.get_net_width("UNKNOWN") == 0.25

    def test_board_assign_net_to_class(self):
        """Test assigning net to class."""
        board = Board()
        board.add_net(Net(name="GND", code="1"))
        board.add_net_class(NetClass(name="Power", track_width=0.5))
        board.assign_net_to_class("GND", "Power")

        assert board.nets["GND"].net_class == "Power"
        assert "GND" in board.net_classes["Power"].nets

    def test_board_assign_net_to_class_net_not_found(self):
        """Test assigning non-existent net raises ValueError."""
        board = Board()
        board.add_net_class(NetClass(name="Power"))

        with pytest.raises(ValueError, match="Net not found"):
            board.assign_net_to_class("MISSING", "Power")

    def test_board_assign_net_to_class_class_not_found(self):
        """Test assigning to non-existent class raises ValueError."""
        board = Board()
        board.add_net(Net(name="VCC", code="1"))

        with pytest.raises(ValueError, match="Net class not found"):
            board.assign_net_to_class("VCC", "MISSING")

    def test_board_get_net_clearance(self):
        """Test getting net clearance from class."""
        board = Board()
        board.add_net(Net(name="VCC", code="1"))
        board.add_net_class(NetClass(name="Power", clearance=0.4))
        board.assign_net_to_class("VCC", "Power")

        assert board.get_net_clearance("VCC") == 0.4

    def test_board_get_net_clearance_default(self):
        """Test getting net clearance default."""
        board = Board()
        assert board.get_net_clearance("UNKNOWN") == 0.2


class TestNetNetClass:
    """Tests for Net net_class attribute."""

    def test_net_default_no_class(self):
        """Test net has no class by default."""
        net = Net(name="GND", code="1")
        assert net.net_class is None

    def test_net_with_class(self):
        """Test net with class assigned."""
        net = Net(name="GND", code="1", net_class="Power")
        assert net.net_class == "Power"
