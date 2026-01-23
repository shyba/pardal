# Feedback on pardal.md

Review date: 2025-12-25

## Issues Found

### 1. Wrong path for routing_strategies.py (Line 78)

The document lists `routing_strategies.py` under the "Routing engine (pcb_tool/routing/*)" section, implying it's inside the `routing/` subdirectory.

**Actual location:** `pcb_tool/routing_strategies.py` (top-level in pcb_tool, not inside routing/)

### 2. DRC section is outdated (Lines 189-194)

Missing recent enhancements:

- **`run_sdk_drc()`** function in `pcb_tool/drc.py` - runs DRC via pcbnew SDK (`pcbnew.WriteDRCReport`) with automatic fallback to kicad-cli if pcbnew unavailable
- **`--force`** CLI flag - continue build despite DRC errors
- **`--warnerr`** CLI flag - treat DRC warnings as errors
- Internal DRC (`CheckDrcCommand`) now includes:
  - Track-to-pad clearance checking
  - Pad-to-pad clearance checking (detects overlapping pads in footprints)

Current text:
```
- **Internal (REPL)**: `CHECK DRC` is a simplified checker (clearance, crossings, etc.).
```

Should mention the enhanced checks and SDK integration.

### 3. CLI build command missing flags (Lines 87-91)

The build command description doesn't mention:
- `--force` - Continue build even if DRC has errors
- `--warnerr` - Treat DRC warnings as errors
- `--finalize` - Replace simplified footprints with KiCad library versions

Current help output:
```
options:
  --route               Run autorouter after placement
  --no-drc              Skip DRC check after save
  --force               Continue build even if DRC has errors
  --warnerr             Treat DRC warnings as errors
  --finalize            Replace simplified footprints with KiCad library versions
```

## Verified Correct

- Architecture description
- Data model (Board, Component, Pad, Net, etc.)
- KiCad integration paths (KicadWriter, kicad_loader, finalize)
- BoardBuilder API example
- Entry points in pyproject.toml
- Routing module files (all exist as listed)
- Atopile integration workflow
- Footprint handling description
- Two-process requirement explanation
