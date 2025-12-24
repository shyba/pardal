# tests/test_kicad_writer.py
import pytest
from pathlib import Path
from pcb_tool.kicad_writer import KicadWriter
from pcb_tool.data_model import Board, Component, Net

@pytest.fixture
def sample_board():
    """Create a sample board with components for testing"""
    board = Board()

    # Add components
    u1 = Component(
        ref="U1",
        value="ATmega328P",
        footprint="Package_DIP:DIP-28_W7.62mm",
        position=(50.0, 40.0),
        rotation=0.0,
        pins=["1", "2", "7", "8"]
    )
    board.add_component(u1)

    r1 = Component(
        ref="R1",
        value="10k",
        footprint="Resistor_SMD:R_0805_2012Metric",
        position=(60.0, 50.0),
        rotation=90.0,
        pins=["1", "2"]
    )
    board.add_component(r1)

    # Add nets
    gnd = Net(name="GND", code="1")
    gnd.add_connection("U1", "8")
    gnd.add_connection("R1", "2")
    board.add_net(gnd)

    vcc = Net(name="VCC", code="2")
    vcc.add_connection("U1", "7")
    vcc.add_connection("R1", "1")
    board.add_net(vcc)

    return board

def test_kicad_writer_instantiation():
    """Test KicadWriter can be instantiated"""
    writer = KicadWriter()
    assert writer is not None

def test_write_creates_file(sample_board, tmp_path):
    """Test writing creates a .kicad_pcb file"""
    writer = KicadWriter()
    output_path = tmp_path / "output.kicad_pcb"

    writer.write(sample_board, output_path)

    assert output_path.exists()
    assert output_path.is_file()

def test_write_file_has_content(sample_board, tmp_path):
    """Test written file has content"""
    writer = KicadWriter()
    output_path = tmp_path / "output.kicad_pcb"

    writer.write(sample_board, output_path)

    content = output_path.read_text()
    assert len(content) > 0

def test_write_has_kicad_pcb_header(sample_board, tmp_path):
    """Test file starts with kicad_pcb header"""
    writer = KicadWriter()
    output_path = tmp_path / "output.kicad_pcb"

    writer.write(sample_board, output_path)

    content = output_path.read_text()
    assert content.startswith("(kicad_pcb")
    assert "(version" in content

def test_write_contains_components(sample_board, tmp_path):
    """Test file contains component footprints"""
    writer = KicadWriter()
    output_path = tmp_path / "output.kicad_pcb"

    writer.write(sample_board, output_path)

    content = output_path.read_text()
    assert "(footprint" in content or "(module" in content
    assert "U1" in content
    assert "R1" in content
    assert "ATmega328P" in content
    assert "10k" in content

def test_write_contains_positions(sample_board, tmp_path):
    """Test file contains component positions"""
    writer = KicadWriter()
    output_path = tmp_path / "output.kicad_pcb"

    writer.write(sample_board, output_path)

    content = output_path.read_text()
    # Positions should be in the file (50.0, 40.0) and (60.0, 50.0)
    assert "50" in content and "40" in content
    assert "60" in content and "50" in content

def test_write_contains_rotations(sample_board, tmp_path):
    """Test file contains component rotations"""
    writer = KicadWriter()
    output_path = tmp_path / "output.kicad_pcb"

    writer.write(sample_board, output_path)

    content = output_path.read_text()
    # R1 has 90 degree rotation
    assert "90" in content

def test_write_contains_footprint_references(sample_board, tmp_path):
    """Test file contains footprint library references"""
    writer = KicadWriter()
    output_path = tmp_path / "output.kicad_pcb"

    writer.write(sample_board, output_path)

    content = output_path.read_text()
    assert "Package_DIP:DIP-28_W7.62mm" in content
    assert "Resistor_SMD:R_0805_2012Metric" in content

def test_write_empty_board(tmp_path):
    """Test writing empty board creates valid file"""
    writer = KicadWriter()
    board = Board()
    output_path = tmp_path / "empty.kicad_pcb"

    writer.write(board, output_path)

    assert output_path.exists()
    content = output_path.read_text()
    assert content.startswith("(kicad_pcb")

def test_write_board_with_nets(sample_board, tmp_path):
    """Test file contains net information"""
    writer = KicadWriter()
    output_path = tmp_path / "output.kicad_pcb"

    writer.write(sample_board, output_path)

    content = output_path.read_text()
    # Should contain net definitions
    assert "(net " in content
    assert "GND" in content
    assert "VCC" in content

def test_write_overwrites_existing_file(sample_board, tmp_path):
    """Test writing overwrites existing file"""
    writer = KicadWriter()
    output_path = tmp_path / "output.kicad_pcb"

    # Write first time
    output_path.write_text("old content")

    # Write board
    writer.write(sample_board, output_path)

    content = output_path.read_text()
    assert "old content" not in content
    assert content.startswith("(kicad_pcb")
