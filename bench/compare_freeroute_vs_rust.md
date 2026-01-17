# FreeRouting vs Rust router (BGA breakout benchmark)

This document is generated/updated by running routing and DRC on synthetic BGA breakout fixtures.

## How to run

Generate boards (inside KiCad 9 docker):

```bash
docker run --rm -v "$PWD:/work" -w /work kicad/kicad:9.0.6-full \
  python3 /work/pardal-pcb/bench/generate_bga_breakout.py \
    --bga BGA-324_15.0x15.0mm_Layout18x18_P0.8mm_Ball0.5mm_Pad0.4mm_NSMD \
    --out /work/pardal-pcb/bench/bga324/bga324_breakout.kicad_pcb

docker run --rm -v "$PWD:/work" -w /work kicad/kicad:9.0.6-full \
  python3 /work/pardal-pcb/bench/generate_bga_breakout.py \
    --bga BGA-676_27.0x27.0mm_Layout26x26_P1.0mm_Ball0.6mm_Pad0.5mm_NSMD \
    --out /work/pardal-pcb/bench/bga676/bga676_breakout.kicad_pcb
```

Route (FreeRouting, 5 minutes):

```bash
./pardal-pcb/venv/bin/python -m pcb_tool.cli freeroute \
  pardal-pcb/bench/bga324/bga324_breakout.kicad_pcb \
  -o pardal-pcb/bench/bga324/bga324_freeroute_5m.kicad_pcb \
  --router-job-timeout 00:05:00 \
  --drc-json pardal-pcb/bench/bga324/bga324_freeroute_5m-drc.json
```

Route (Rust backend, extracted grid):

```bash
./pardal-pcb/venv/bin/python -m pcb_tool.cli rust-route \
  pardal-pcb/bench/bga324/bga324_breakout.kicad_pcb \
  -o pardal-pcb/bench/bga324/bga324_rust.kicad_pcb \
  --resolution 0.2
```

## Results

### BGA-100 (100 nets)

- FreeRouting (2m job timeout): `pardal-pcb/bench/bga100/bga100_freeroute_2m.kicad_pcb`
  - Unconnected items: 49
  - DRC violations: 7 (`track_dangling:6`, `via_dangling:1`)
- FreeRouting (10m job timeout): `pardal-pcb/bench/bga100/bga100_freeroute_10m.kicad_pcb`
  - Unconnected items: 51
  - DRC violations: 7 (`track_dangling:7`)
- Rust router (strict, DRC-clean): `pardal-pcb/bench/bga100/bga100_breakout2_rust_strict_res0p1_ceil_existingvias.kicad_pcb`
  - Resolution: 0.1mm
  - Failed nets: 0
  - Unconnected items: 0
  - DRC violations: 0

### BGA-324 (324 nets)

- FreeRouting (5m job timeout): `pardal-pcb/bench/bga324/bga324_breakout2_freeroute_5m.kicad_pcb`
  - Unconnected items: 209
  - DRC violations: 22 (`track_dangling:20`, `via_dangling:2`)
- Rust router (NCR+escape, completes): `pardal-pcb/bench/bga324/bga324_breakout2_rust_ncr6_escape.kicad_pcb`
  - Failed nets: 0
  - Unconnected items: 0
  - DRC violations: 1384 (`clearance:499`, `tracks_crossing:425`, `shorting_items:199`, `hole_clearance:199`)
- Rust router (keepout-stamped, manhattan, completes): `pardal-pcb/bench/bga324/bga324_breakout2_rust_keepout_noescape_manh.kicad_pcb`
  - Failed nets: 0
  - Unconnected items: 0
  - DRC violations: 813 (`clearance:499`, `tracks_crossing:193`, `shorting_items:111`)

### BGA-676 (676 nets)

- FreeRouting (10m job timeout): `pardal-pcb/bench/bga676/bga676_breakout2_freeroute_10m.kicad_pcb`
  - Unconnected items: 499
  - DRC violations: 200 (`track_dangling:199`, `via_dangling:1`)
- Rust router (NCR+escape, incomplete): `pardal-pcb/bench/bga676/bga676_breakout2_rust_ncr6_escape.kicad_pcb`
  - Failed nets: 173
  - Unconnected items: (not computed; expect >0)
  - DRC not run (not worth evaluating until completion)
- Rust router (keepout-stamped, manhattan, completes): `pardal-pcb/bench/bga676/bga676_breakout2_rust_keepout_noescape_manh.kicad_pcb`
  - Failed nets: 0
  - Unconnected items: 0
  - DRC violations: 1309 (`clearance:499`, `shorting_items:199`, `hole_clearance:199`, `solder_mask_bridge:199`)

### Notes

- In this benchmark setup, FreeRouting consistently leaves many nets unconnected (even with higher pass counts/timeouts), but the nets it does route tend to have minimal DRC errors (mostly dangling items).
- The Rust router now supports extracting and honoring *pre-existing vias* (e.g. microvias-in-pad) as fixed obstacles/resources, and uses conservative (ceil) radius quantization in the extractor. This is necessary to avoid “grid says OK, KiCad DRC says no”.
- BGA-100 can reach 0-DRC under strict spacing constraints at 0.1mm resolution, but larger fixtures still require significant performance + planning improvements to do the same within a few minutes.
