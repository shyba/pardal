"""Port of `app.freerouting.geometry.planar.RegularTileShape` (incremental).

In FreeRouting, `RegularTileShape` is an abstract subclass of `TileShape`.
For the Mojo port we expose concrete wrappers for the currently supported
regular shapes:
- `TileShapeBox` (IntBox-backed)
- `TileShapeOctagon` (IntOctagon-backed)

This keeps call sites explicit while preserving a path to later introduce a
single discriminated-union `RegularTileShape` if needed.
"""

from .tile_shape import TileShapeBox, TileShapeOctagon

__all__ = [
    "TileShapeBox",
    "TileShapeOctagon",
]
