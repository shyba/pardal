# FPGA Example (4-layer)

This folder is an end-to-end example for “production-style” multi-layer routing: create a small FPGA-like board, autoroute it headlessly, run KiCad 9 DRC, and export a `.kicad_pcb`.

## Current status

- `fpga_unrouted.freerouted.kicad_pcb` is routed via FreeRouting (Specctra DSN/SES) and passes KiCad 9 DRC with **0 errors, 0 warnings** (docker-backed).
- `fpga_routed_with_widths.kicad_pcb` is produced by the pure-Python router and is useful for development, but is not guaranteed to match KiCad DRC yet.

## Workflow (DRC-clean)

Requires docker (used to run KiCad 9 + Java headlessly).

- Generate the unrouted board: `./fpga/route_fpga_with_widths.py` (writes `fpga_unrouted.kicad_pcb` too)
- Route with FreeRouting: `python -c "from pathlib import Path; from pcb_tool.freerouting_backend import freeroute_kicad_pcb; freeroute_kicad_pcb(Path('fpga_unrouted.kicad_pcb'), Path('fpga_unrouted.freerouted.kicad_pcb'))"`
- Run KiCad 9 DRC: `PARDAL_KICAD_DOCKER=1 pardal drc fpga_unrouted.freerouted.kicad_pcb`

## Notes / gotchas

The original FPGA example exposed a few “gotchas” that made the workflow harder than it needed to be:

- **Unconnected pads still matter.** Even if a pad has no net assignment, it’s still copper and must act as an obstacle/keepout for routing and DRC.
- **Keepout must not create “holes” near dense pinfields.** Keepout logic must not accidentally unblock overlap regions between adjacent pads.
- **Avoid via-in-pad by default.** The router can select a layer transition at a pad center; the simplified DRC treats this as an error.
- **No diagonal corner-cutting.** Allowing diagonals that cut between two blocked orthogonal cells can clip pads and show up as clearance/short issues.

Some of these are now handled in the routing core; others are addressed by delegating to KiCad 9 + FreeRouting for a high-confidence routed result.

## Recommended workflow (simple / dev)

- Generate the in-memory board
- Route with the built-in FPGA strategy + per-net layer overrides
- Run internal DRC for fast feedback (not a substitute for KiCad DRC)
- Write `.kicad_pcb`

Run:
- `./fpga/route_fpga_with_widths.py`

## Strategy knobs that make this easy

`pcb_tool/routing_strategies.py` provides `FourLayerFPGA`, which supports:
- `net_layer_overrides`: keep JTAG on `F.Cu`, route dense nets on inner layers, etc.
- `net_via_costs`: pass `{"*": 2.0}` to set a global via cost (mm-equivalent).
- `verbose`: control routing output.

The FPGA example uses these to keep the script small and deterministic.
