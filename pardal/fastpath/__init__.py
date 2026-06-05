"""Fastpath routing helpers (Cython-backed).

This module is intentionally narrow to keep a stable, FFI-friendly API
that can be reimplemented in Rust later.
"""

from __future__ import annotations

from array import array
from typing import Sequence

try:
    from ._astar import _astar_path as _cy_astar_path  # type: ignore
    from ._astar import _astar_path_3d as _cy_astar_path_3d  # type: ignore
except Exception:
    _cy_astar_path = None
    _cy_astar_path_3d = None

from ._py_astar import _astar_path as _py_astar_path
from ._py_astar import _astar_path_3d as _py_astar_path_3d

_USE_MEMORYVIEW_2D = _cy_astar_path is not None
_USE_MEMORYVIEW_3D = _cy_astar_path_3d is not None
_astar_path = _cy_astar_path or _py_astar_path
_astar_path_3d = _cy_astar_path_3d or _py_astar_path_3d


def _as_cost_grid(cost_grid: object) -> memoryview:
    """Normalize cost grid input to a 2D memoryview of floats.

    Accepts:
    - 2D buffer-compatible objects (e.g., numpy arrays)
    - nested lists/tuples (converted to a contiguous array)
    """
    try:
        mv = memoryview(cost_grid)  # type: ignore[arg-type]
        if mv.ndim == 2:
            return mv
    except TypeError:
        mv = None

    if isinstance(cost_grid, Sequence):
        rows = list(cost_grid)  # type: ignore[arg-type]
        if not rows:
            raise ValueError("cost_grid must be non-empty")
        width = len(rows[0])
        if width == 0:
            raise ValueError("cost_grid rows must be non-empty")
        flat = array("d")
        for row in rows:
            if len(row) != width:
                raise ValueError("cost_grid rows must be equal length")
            flat.extend(float(x) for x in row)  # type: ignore[arg-type]
        mv_flat = memoryview(flat).cast("B")
        return mv_flat.cast("d", shape=(len(rows), width))

    raise TypeError("cost_grid must be a 2D buffer or sequence")


def _as_cost_list(cost_grid: object) -> list[list[float]]:
    """Normalize cost grid input to a list of float rows."""
    if not isinstance(cost_grid, Sequence):
        raise TypeError("cost_grid must be a 2D sequence")
    rows = list(cost_grid)  # type: ignore[arg-type]
    if not rows:
        raise ValueError("cost_grid must be non-empty")
    width = len(rows[0])
    if width == 0:
        raise ValueError("cost_grid rows must be non-empty")
    out = []
    for row in rows:
        if len(row) != width:
            raise ValueError("cost_grid rows must be equal length")
        out.append([float(x) for x in row])  # type: ignore[arg-type]
    return out


def _as_cost_grid_3d_mv(cost_grid: object) -> memoryview:
    """Normalize 3D cost grid to a (layers, height, width) memoryview of doubles."""
    try:
        mv = memoryview(cost_grid)  # type: ignore[arg-type]
        if mv.ndim == 3:
            return mv
    except TypeError:
        mv = None

    if not isinstance(cost_grid, Sequence):
        raise TypeError("cost_grid must be a 3D buffer or sequence")

    layers = list(cost_grid)  # type: ignore[arg-type]
    if not layers:
        raise ValueError("cost_grid must be non-empty")
    height = len(layers[0])
    if height == 0:
        raise ValueError("cost_grid layers must be non-empty")
    width = len(layers[0][0])
    if width == 0:
        raise ValueError("cost_grid rows must be non-empty")

    flat = array("d")
    for layer in layers:
        if len(layer) != height:
            raise ValueError("cost_grid layers must be equal height")
        for row in layer:
            if len(row) != width:
                raise ValueError("cost_grid rows must be equal length")
            flat.extend(float(x) for x in row)  # type: ignore[arg-type]

    mv_flat = memoryview(flat).cast("B")
    return mv_flat.cast("d", shape=(len(layers), height, width))


def _as_cost_grid_3d_list(cost_grid: object) -> list[list[list[float]]]:
    if not isinstance(cost_grid, Sequence):
        raise TypeError("cost_grid must be a 3D sequence")
    layers = list(cost_grid)  # type: ignore[arg-type]
    if not layers:
        raise ValueError("cost_grid must be non-empty")
    height = len(layers[0])
    if height == 0:
        raise ValueError("cost_grid layers must be non-empty")
    width = len(layers[0][0])
    if width == 0:
        raise ValueError("cost_grid rows must be non-empty")
    out = []
    for layer in layers:
        if len(layer) != height:
            raise ValueError("cost_grid layers must be equal height")
        layer_out = []
        for row in layer:
            if len(row) != width:
                raise ValueError("cost_grid rows must be equal length")
            layer_out.append([float(x) for x in row])  # type: ignore[arg-type]
        out.append(layer_out)
    return out


def astar_path(
    cost_grid: object,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    diagonal: bool = True,
) -> list[tuple[int, int]]:
    """Compute a shortest path on a 2D cost grid.

    cost_grid: 2D array-like (0 blocks, positive cost allows traversal).
    start/goal: (x, y) grid coordinates.
    diagonal: allow diagonal moves.
    """
    if _USE_MEMORYVIEW_2D:
        mv = _as_cost_grid(cost_grid)
    else:
        mv = _as_cost_list(cost_grid)
    sx, sy = start
    gx, gy = goal
    return _astar_path(mv, sx, sy, gx, gy, diagonal)


def astar_path_3d(
    cost_grid: object,
    start: tuple[int, int, int],
    goal: tuple[int, int, int],
    *,
    diagonal: bool = True,
    via_cost: float = 1.0,
) -> list[tuple[int, int, int]]:
    """Compute a shortest path on a 3D cost grid (layers, y, x).

    cost_grid: 3D array-like (0 blocks, positive cost allows traversal).
    start/goal: (x, y, layer) grid coordinates.
    """
    if _USE_MEMORYVIEW_3D:
        cost = _as_cost_grid_3d_mv(cost_grid)
    else:
        cost = _as_cost_grid_3d_list(cost_grid)
    sx, sy, sz = start
    gx, gy, gz = goal
    return _astar_path_3d(cost, sx, sy, sz, gx, gy, gz, diagonal, float(via_cost))


__all__ = ["astar_path", "astar_path_3d"]
