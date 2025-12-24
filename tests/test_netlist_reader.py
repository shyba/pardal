# tests/test_netlist_reader.py
import pytest
from pathlib import Path
from pcb_tool.netlist_reader import NetlistReader
from pcb_tool.data_model import Board

# Sample KiCad netlist content for testing
SAMPLE_NETLIST = '''(export (version D)
  (design
    (source /path/to/test.sch)
    (date "2024-01-01 12:00:00")
    (tool "Eeschema 7.0.0"))
  (components
    (comp (ref U1)
      (value ATmega328P)
      (footprint Package_DIP:DIP-28_W7.62mm)
      (libsource (lib MCU_Microchip_ATmega) (part ATmega328P) (description ""))
      (sheetpath (names /) (tstamps /))
      (tstamp 5F3E1A2B))
    (comp (ref R1)
      (value 10k)
      (footprint Resistor_SMD:R_0805_2012Metric)
      (libsource (lib Device) (part R) (description "Resistor"))
      (sheetpath (names /) (tstamps /))
      (tstamp 5F3E1A2C))
    (comp (ref C1)
      (value 100n)
      (footprint Capacitor_SMD:C_0805_2012Metric)
      (libsource (lib Device) (part C) (description "Capacitor"))
      (sheetpath (names /) (tstamps /))
      (tstamp 5F3E1A2D)))
  (nets
    (net (code 1) (name GND)
      (node (ref U1) (pin 8))
      (node (ref R1) (pin 2))
      (node (ref C1) (pin 2)))
    (net (code 2) (name VCC)
      (node (ref U1) (pin 7))
      (node (ref R1) (pin 1))
      (node (ref C1) (pin 1)))
    (net (code 3) (name /LED)
      (node (ref U1) (pin 19)))))
'''

@pytest.fixture
def sample_netlist_file(tmp_path):
    """Create a temporary netlist file for testing"""
    netlist_path = tmp_path / "test.net"
    netlist_path.write_text(SAMPLE_NETLIST)
    return netlist_path

def test_netlist_reader_instantiation():
    """Test NetlistReader can be instantiated"""
    reader = NetlistReader()
    assert reader is not None

def test_read_nonexistent_file():
    """Test reading nonexistent file raises FileNotFoundError"""
    reader = NetlistReader()
    with pytest.raises(FileNotFoundError):
        reader.read(Path("/nonexistent/path/file.net"))

def test_read_netlist_returns_board(sample_netlist_file):
    """Test reading netlist returns Board object"""
    reader = NetlistReader()
    board = reader.read(sample_netlist_file)

    assert isinstance(board, Board)
    assert board.source_file == sample_netlist_file

def test_read_components(sample_netlist_file):
    """Test reading components from netlist"""
    reader = NetlistReader()
    board = reader.read(sample_netlist_file)

    assert len(board.components) == 3
    assert "U1" in board.components
    assert "R1" in board.components
    assert "C1" in board.components

def test_component_properties(sample_netlist_file):
    """Test component properties are parsed correctly"""
    reader = NetlistReader()
    board = reader.read(sample_netlist_file)

    u1 = board.get_component("U1")
    assert u1 is not None
    assert u1.ref == "U1"
    assert u1.value == "ATmega328P"
    assert u1.footprint == "Package_DIP:DIP-28_W7.62mm"

    r1 = board.get_component("R1")
    assert r1 is not None
    assert r1.ref == "R1"
    assert r1.value == "10k"
    assert r1.footprint == "Resistor_SMD:R_0805_2012Metric"

def test_component_default_position_rotation(sample_netlist_file):
    """Test components have default position and rotation"""
    reader = NetlistReader()
    board = reader.read(sample_netlist_file)

    u1 = board.get_component("U1")
    assert u1.position == (0.0, 0.0)  # Default position
    assert u1.rotation == 0.0         # Default rotation
    assert u1.locked is False         # Default unlocked

def test_read_nets(sample_netlist_file):
    """Test reading nets from netlist"""
    reader = NetlistReader()
    board = reader.read(sample_netlist_file)

    assert len(board.nets) == 3
    assert "GND" in board.nets
    assert "VCC" in board.nets
    assert "/LED" in board.nets

def test_net_properties(sample_netlist_file):
    """Test net properties are parsed correctly"""
    reader = NetlistReader()
    board = reader.read(sample_netlist_file)

    gnd = board.nets["GND"]
    assert gnd.name == "GND"
    assert gnd.code == "1"
    assert len(gnd.connections) == 3
    assert ("U1", "8") in gnd.connections
    assert ("R1", "2") in gnd.connections
    assert ("C1", "2") in gnd.connections

def test_net_with_single_connection(sample_netlist_file):
    """Test net with single connection"""
    reader = NetlistReader()
    board = reader.read(sample_netlist_file)

    led_net = board.nets["/LED"]
    assert led_net.name == "/LED"
    assert led_net.code == "3"
    assert len(led_net.connections) == 1
    assert ("U1", "19") in led_net.connections

def test_empty_netlist():
    """Test reading netlist with no components or nets"""
    empty_netlist = '''(export (version D)
  (design
    (source /test.sch)
    (tool "Eeschema"))
  (components)
  (nets))
'''
    reader = NetlistReader()
    # Create temp file
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(mode='w', suffix='.net', delete=False) as f:
        f.write(empty_netlist)
        temp_path = Path(f.name)

    try:
        board = reader.read(temp_path)
        assert len(board.components) == 0
        assert len(board.nets) == 0
    finally:
        temp_path.unlink()
