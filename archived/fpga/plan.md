# FPGA example plan (current)

This file is intentionally short. Historical brainstorming notes were moved to `pardal-pcb/archived/fpga_plan_old.md`.

## Goal
Keep the FPGA example “boring”:
- `route_fpga_with_widths.py` stays short and readable.
- Running it reliably produces a DRC-clean board (internal DRC) and passes KiCad DRC in CI when enabled.
- Any special-case behavior is fixed in the routing core, not in the example script.

## Routing strategy defaults
- Use the `FourLayerFPGA` routing strategy.
- Use `net_layer_overrides` for nets that have a strong preferred layer (e.g. JTAG on `F.Cu`, dense buses on inner layers).
- Use a global via cost via `net_via_costs={"*": ...}` (per-net override; not a via-type table).

## Verification
- Internal: `pcb_tool.api.check_internal_drc()` (no log parsing in scripts).
- External (optional): `kicad-cli pcb drc` via `pcb_tool.drc.run_drc()` and store the report artifacts.
