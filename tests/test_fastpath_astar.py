import pytest

from pardal.fastpath import astar_path, astar_path_3d


def _assert_path_valid(path, grid):
    assert path, "expected non-empty path"
    height = len(grid)
    width = len(grid[0])
    for x, y in path:
        assert 0 <= x < width
        assert 0 <= y < height
        assert grid[y][x] > 0


def test_astar_basic_no_diagonal():
    grid = [
        [1, 1, 1, 1, 1],
        [1, 0, 0, 0, 1],
        [1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1],
        [1, 1, 1, 0, 1],
    ]
    path = astar_path(grid, (0, 0), (4, 4), diagonal=False)
    _assert_path_valid(path, grid)
    assert path[0] == (0, 0)
    assert path[-1] == (4, 4)
    # Ensure only orthogonal moves.
    for (x1, y1), (x2, y2) in zip(path, path[1:]):
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        assert dx + dy == 1


def test_astar_diagonal_required():
    grid = [
        [1, 0, 1],
        [0, 1, 1],
        [1, 1, 1],
    ]
    path_diag = astar_path(grid, (0, 0), (2, 2), diagonal=True)
    # We disallow diagonal "corner cutting" between two blocked orthogonal cells
    # because it produces geometries that can clip obstacles/pads.
    assert path_diag == []

    path_no_diag = astar_path(grid, (0, 0), (2, 2), diagonal=False)
    assert path_no_diag == []


def test_astar_avoids_high_cost_cell():
    grid = [
        [1, 1, 1],
        [1, 10, 1],
        [1, 1, 1],
    ]
    path = astar_path(grid, (0, 1), (2, 1), diagonal=False)
    _assert_path_valid(path, grid)
    assert (1, 1) not in path


def test_astar_rejects_invalid_start_or_goal():
    grid = [
        [1, 1],
        [1, 1],
    ]
    assert astar_path(grid, (-1, 0), (1, 1), diagonal=True) == []
    assert astar_path(grid, (0, 0), (2, 1), diagonal=True) == []

    grid_blocked = [
        [0, 1],
        [1, 1],
    ]
    assert astar_path(grid_blocked, (0, 0), (1, 1), diagonal=True) == []


def test_astar_3d_via_required():
    cost = [
        [
            [1, 0, 1],
            [1, 0, 1],
            [1, 0, 1],
        ],
        [
            [1, 1, 1],
            [1, 1, 1],
            [1, 1, 1],
        ],
    ]
    path = astar_path_3d(cost, (0, 1, 0), (2, 1, 0), diagonal=False, via_cost=2.0)
    assert path
    assert path[0] == (0, 1, 0)
    assert path[-1] == (2, 1, 0)
    assert any(step[2] == 1 for step in path)


def test_astar_3d_no_via_needed():
    cost = [
        [
            [1, 1, 1],
            [1, 1, 1],
            [1, 1, 1],
        ],
        [
            [1, 1, 1],
            [1, 1, 1],
            [1, 1, 1],
        ],
    ]
    path = astar_path_3d(cost, (0, 0, 0), (2, 2, 0), diagonal=True, via_cost=2.0)
    assert path
    assert all(step[2] == 0 for step in path)
