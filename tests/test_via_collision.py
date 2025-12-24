"""
Tests for via collision detection in ViaCommand and CheckDrcCommand.
"""

import pytest
from pcb_tool.data_model import Board, Net, Component, Pad
from pcb_tool.commands import ViaCommand


def test_via_command_rejects_via_on_pad_exact_position():
    """ViaCommand should reject via placed exactly on a component pad."""
    board = Board()

    # Create a net
    board.add_net(Net(name="TEST_NET", code="1"))

    # Create a component with a pad at (10, 20)
    comp = Component(ref="R1", value="10k", footprint="RES-0805", position=(10, 20), rotation=0)
    comp.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="TEST_NET"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5))
    ]
    board.add_component(comp)

    # Try to place via exactly on pad 1 position (10 - 0.95 = 9.05, 20)
    via_cmd = ViaCommand("TEST_NET", (9.05, 20.0), size=0.8, drill=0.4)

    error = via_cmd.validate(board)
    assert error is not None
    assert "collides" in error.lower()
    assert "drill holes would overlap" in error.lower()


def test_via_command_rejects_via_near_different_net_pad():
    """ViaCommand should reject via too close to a pad on different net."""
    board = Board()

    # Create two nets
    board.add_net(Net(name="NET1", code="1"))
    board.add_net(Net(name="NET2", code="2"))

    # Create a component with pads
    comp = Component(ref="R1", value="10k", footprint="RES-0805", position=(10, 20), rotation=0)
    comp.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="NET1"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5), net_name="NET2")
    ]
    board.add_component(comp)

    # Try to place via on NET1 very close to pad 2 (which is on NET2)
    # Pad 2 is at (10.95, 20), try placing via at (11.0, 20) - only 0.05mm away
    via_cmd = ViaCommand("NET1", (11.0, 20.0), size=0.8, drill=0.4)

    error = via_cmd.validate(board)
    assert error is not None
    assert "too close" in error.lower()


def test_via_command_allows_via_on_same_net_pad_if_not_exact():
    """ViaCommand should allow via near a pad on the same net (but not exact position)."""
    board = Board()

    # Create a net
    board.add_net(Net(name="TEST_NET", code="1"))

    # Create a component with pads
    comp = Component(ref="R1", value="10k", footprint="RES-0805", position=(10, 20), rotation=0)
    comp.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="TEST_NET"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5))
    ]
    board.add_component(comp)

    # Place via on TEST_NET, close to pad 1 (also TEST_NET) but not exact
    # Pad 1 is at (9.05, 20), place via at (8.0, 20) - about 1mm away
    via_cmd = ViaCommand("TEST_NET", (8.0, 20.0), size=0.8, drill=0.4)

    error = via_cmd.validate(board)
    assert error is None  # Should pass validation


def test_via_command_rejects_via_on_existing_via():
    """ViaCommand should reject via placed on existing via at exact position."""
    board = Board()

    # Create two nets
    board.add_net(Net(name="NET1", code="1"))
    board.add_net(Net(name="NET2", code="2"))

    # Add an existing via on NET1
    via1_cmd = ViaCommand("NET1", (30.0, 40.0), size=0.8, drill=0.4)
    assert via1_cmd.validate(board) is None
    via1_cmd.execute(board)

    # Try to add another via on NET2 at the same position
    via2_cmd = ViaCommand("NET2", (30.0, 40.0), size=0.8, drill=0.4)

    error = via2_cmd.validate(board)
    assert error is not None
    assert "overlaps with existing via" in error.lower()


def test_via_command_rejects_via_near_different_net_via():
    """ViaCommand should reject via too close to existing via on different net."""
    board = Board()

    # Create two nets
    board.add_net(Net(name="NET1", code="1"))
    board.add_net(Net(name="NET2", code="2"))

    # Add an existing via on NET1
    via1_cmd = ViaCommand("NET1", (30.0, 40.0), size=0.8, drill=0.4)
    assert via1_cmd.validate(board) is None
    via1_cmd.execute(board)

    # Try to add another via on NET2 very close (0.05mm away)
    via2_cmd = ViaCommand("NET2", (30.05, 40.0), size=0.8, drill=0.4)

    error = via2_cmd.validate(board)
    assert error is not None
    assert "too close" in error.lower()


def test_via_command_allows_via_on_same_net():
    """ViaCommand should allow multiple vias on the same net if not too close."""
    board = Board()

    # Create a net
    board.add_net(Net(name="TEST_NET", code="1"))

    # Add first via
    via1_cmd = ViaCommand("TEST_NET", (30.0, 40.0), size=0.8, drill=0.4)
    assert via1_cmd.validate(board) is None
    via1_cmd.execute(board)

    # Add second via on same net, 5mm away
    via2_cmd = ViaCommand("TEST_NET", (35.0, 40.0), size=0.8, drill=0.4)

    error = via2_cmd.validate(board)
    assert error is None  # Should pass


def test_check_drc_detects_via_pad_collision():
    """CheckDrcCommand should detect via-pad collisions."""
    from pcb_tool.commands import CheckDrcCommand

    board = Board()

    # Create nets
    board.add_net(Net(name="TEST_NET", code="1"))

    # Create a component with a pad
    comp = Component(ref="R1", value="10k", footprint="RES-0805", position=(10, 20), rotation=0)
    comp.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="TEST_NET")
    ]
    board.add_component(comp)

    # Manually add a via at the exact pad position (bypassing validation)
    # This simulates a board that was created before collision detection was added
    from pcb_tool.data_model import Via
    board.nets["TEST_NET"].vias.append(
        Via(net_name="TEST_NET", position=(9.05, 20.0), size=0.8, drill=0.4, layers=("F.Cu", "B.Cu"))
    )

    # Run DRC
    drc = CheckDrcCommand()
    result = drc.execute(board)

    assert "1 error" in result or "errors" in result.lower()
    assert "drill holes co-located" in result.lower() or "overlaps" in result.lower()


def test_check_drc_detects_via_via_collision():
    """CheckDrcCommand should detect via-via collisions."""
    from pcb_tool.commands import CheckDrcCommand

    board = Board()

    # Create two nets
    board.add_net(Net(name="NET1", code="1"))
    board.add_net(Net(name="NET2", code="2"))

    # Manually add two vias at the same position (bypassing validation)
    from pcb_tool.data_model import Via
    board.nets["NET1"].vias.append(
        Via(net_name="NET1", position=(30.0, 40.0), size=0.8, drill=0.4, layers=("F.Cu", "B.Cu"))
    )
    board.nets["NET2"].vias.append(
        Via(net_name="NET2", position=(30.0, 40.0), size=0.8, drill=0.4, layers=("F.Cu", "B.Cu"))
    )

    # Run DRC
    drc = CheckDrcCommand()
    result = drc.execute(board)

    assert "1 error" in result or "errors" in result.lower()
    assert "overlap" in result.lower()


def test_check_drc_passes_with_no_collisions():
    """CheckDrcCommand should pass when there are no via collisions."""
    from pcb_tool.commands import CheckDrcCommand

    board = Board()

    # Create nets
    board.add_net(Net(name="NET1", code="1"))
    board.add_net(Net(name="NET2", code="2"))

    # Create components with pads
    comp1 = Component(ref="R1", value="10k", footprint="RES-0805", position=(10, 20), rotation=0)
    comp1.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="NET1")
    ]
    board.add_component(comp1)

    # Add vias that don't collide
    via1 = ViaCommand("NET1", (20.0, 20.0), size=0.8, drill=0.4)
    via1.execute(board)

    via2 = ViaCommand("NET2", (30.0, 20.0), size=0.8, drill=0.4)
    via2.execute(board)

    # Run DRC
    drc = CheckDrcCommand()
    result = drc.execute(board)

    assert "0 errors" in result
