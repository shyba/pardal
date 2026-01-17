# FPGA Routing Issues (route_fpga_with_widths.py)

## Run context
- Script: `pardal-pcb/fpga/route_fpga_with_widths.py`
- Result: 9/9 nets routed, 163 segments, 2 vias, layers used: F.Cu, B.Cu, In1.Cu, In2.Cu
- Internal DRC: 0 errors, 0 warnings

## Status
Resolved: the generated board now runs `CHECK DRC` clean.

## What was wrong (root causes)
- Pad keepout only considered pads with assigned nets. Unconnected pads were marked as obstacles only on their component layer, but the simplified DRC checks pad clearance against tracks on inner layers too, so routes could “duck under” unconnected pads and fail DRC.
- Pad keepout exemption for the current net was implemented as “subtract my keepout from the global keepout”, which accidentally unblocked overlap regions near dense pinfields (TQFP/QFN), allowing traces to run too close to adjacent pins.
- 3D routing could place a via exactly at a pad center (via-in-pad). The simplified DRC flags “drill holes co-located” at pad centers as an error.
- Diagonal moves could “corner cut” between obstacles, producing geometries that clip pads.

## Fixes applied
- `AutoRouteCommand._create_routing_grid` now records pad ownership for *all* pads (including unconnected) and tracks `grid.pad_centers` for via placement avoidance.
- `PathFinder` pad keepout is now generated from *other* nets’ pads (no “punch holes” from overlapping keepouts near adjacent pins).
- 3D paths are post-processed to nudge layer transitions off pad centers when possible (avoids via-in-pad under the simplified DRC).
- Diagonal neighbor expansion now disallows “corner cutting” (implemented in both the Python and Cython A* backends).
