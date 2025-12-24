import pytest
from pcb_tool.commands import ListNetsCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component, Net

@pytest.fixture
def sample_board():
    board = Board()

    board.add_component(Component(ref="U1", value="IC", footprint="DIP-8", position=(0, 0), rotation=0))
    board.add_component(Component(ref="R1", value="10k", footprint="R_0805", position=(10, 10), rotation=0))
    board.add_component(Component(ref="C1", value="100n", footprint="C_0805", position=(20, 20), rotation=0))

    gnd = Net(name="GND", code="1")
    gnd.add_connection("U1", "8")
    gnd.add_connection("R1", "2")
    gnd.add_connection("C1", "2")
    board.add_net(gnd)

    vcc = Net(name="VCC", code="2")
    vcc.add_connection("U1", "7")
    vcc.add_connection("R1", "1")
    vcc.add_connection("C1", "1")
    board.add_net(vcc)

    return board

def test_list_nets_command_creation():
    cmd = ListNetsCommand()
    assert cmd is not None

def test_list_nets_validate_always_succeeds():
    cmd = ListNetsCommand()
    board = Board()
    assert cmd.validate(board) is None

def test_list_nets_execute_empty_board():
    cmd = ListNetsCommand()
    board = Board()
    result = cmd.execute(board)
    assert "0 nets" in result.lower() or "no nets" in result.lower()

def test_list_nets_execute_shows_all_nets(sample_board):
    cmd = ListNetsCommand()
    result = cmd.execute(sample_board)

    assert "GND" in result
    assert "VCC" in result

def test_list_nets_shows_connections(sample_board):
    cmd = ListNetsCommand()
    result = cmd.execute(sample_board)

    assert "U1" in result
    assert "R1" in result
    assert "C1" in result

def test_parser_can_parse_list_nets():
    parser = CommandParser()
    cmd = parser.parse("LIST NETS")
    assert isinstance(cmd, ListNetsCommand)
