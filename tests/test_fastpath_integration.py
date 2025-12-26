from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.pathfinder import PathFinder


def test_fastpath_used_for_forced_single_layer():
    grid = RoutingGrid(width_mm=5.0, height_mm=5.0, resolution_mm=1.0)
    finder = PathFinder(grid, use_fastpath=True)

    path = finder.find_path(
        (0.0, 0.0),
        (4.0, 4.0),
        layer="F.Cu",
        allow_diagonals=False,
        force_single_layer=True,
    )

    assert path
    assert finder.last_backend == "fastpath"


def test_fastpath_skipped_when_vias_allowed():
    grid = RoutingGrid(width_mm=5.0, height_mm=5.0, resolution_mm=1.0)
    finder = PathFinder(grid, use_fastpath=True)

    path = finder.find_path(
        (0.0, 0.0),
        (4.0, 4.0),
        layer="F.Cu",
        allow_diagonals=False,
        force_single_layer=False,
    )

    assert path
    assert finder.last_backend == "fastpath3d"


def test_fastpath_skipped_for_multi_layer_targets():
    grid = RoutingGrid(
        width_mm=5.0,
        height_mm=5.0,
        resolution_mm=1.0,
        layers=["F.Cu", "In1.Cu", "B.Cu"],
    )
    finder = PathFinder(grid, use_fastpath=True)

    path = finder.find_path(
        (0.0, 0.0),
        (4.0, 4.0),
        layer="F.Cu",
        target_layer="B.Cu",
        allow_diagonals=False,
    )

    assert path
    assert finder.last_backend == "fastpath3d"
