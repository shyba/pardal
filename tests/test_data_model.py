# tests/test_data_model.py
import pytest
from pathlib import Path
from pcb_tool.data_model import Board, Component, Net

def test_component_creation():
    """Test creating a component with basic properties"""
    comp = Component(
        ref="U1",
        value="ATmega328P",
        footprint="DIP-28",
        position=(50.0, 40.0),
        rotation=0.0
    )
    assert comp.ref == "U1"
    assert comp.value == "ATmega328P"
    assert comp.footprint == "DIP-28"
    assert comp.position == (50.0, 40.0)
    assert comp.rotation == 0.0
    assert comp.locked is False  # Default value

def test_component_with_pins():
    """Test component with pin list"""
    comp = Component(
        ref="R1",
        value="10k",
        footprint="R_0805",
        position=(10.0, 20.0),
        rotation=90.0,
        pins=["1", "2"]
    )
    assert len(comp.pins) == 2
    assert "1" in comp.pins
    assert "2" in comp.pins

def test_net_creation():
    """Test creating a net with connections"""
    net = Net(name="GND", code="1")
    assert net.name == "GND"
    assert net.code == "1"
    assert net.connections == []  # Default empty list

def test_net_add_connection():
    """Test adding connections to a net"""
    net = Net(name="VCC", code="2")
    net.add_connection("U1", "8")
    net.add_connection("C1", "1")

    assert len(net.connections) == 2
    assert ("U1", "8") in net.connections
    assert ("C1", "1") in net.connections

def test_board_creation():
    """Test creating an empty board"""
    board = Board()
    assert board.components == {}
    assert board.nets == {}
    assert board.source_file is None

def test_board_add_component():
    """Test adding component to board"""
    board = Board()
    comp = Component(ref="U1", value="IC", footprint="DIP-8",
                     position=(0, 0), rotation=0)
    board.add_component(comp)

    assert "U1" in board.components
    assert board.components["U1"] == comp
    assert board.get_component("U1") == comp

def test_board_get_nonexistent_component():
    """Test getting component that doesn't exist returns None"""
    board = Board()
    assert board.get_component("NONEXISTENT") is None

def test_board_add_net():
    """Test adding net to board"""
    board = Board()
    net = Net(name="GND", code="1")
    board.add_net(net)

    assert "GND" in board.nets
    assert board.nets["GND"] == net

def test_component_locked_state():
    """Test locking/unlocking components"""
    comp = Component(ref="U1", value="IC", footprint="DIP-8",
                     position=(0, 0), rotation=0)
    assert comp.locked is False

    comp.locked = True
    assert comp.locked is True

    comp.locked = False
    assert comp.locked is False
