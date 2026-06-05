# GD32F310C8T6 routing DSL example

This example exercises a 100 mm x 100 mm, 4-layer GD32F310C8T6 LQFP48 source lane from modular source intent into Pardal routing DSL and strict fab-oriented physical artifacts.

The pin table is generated from `generate.py`, using GigaDevice GD32F310xx Datasheet Rev2.2, Table 2-4, for the GD32F310Cx LQFP48 package. ADC coverage is explicit for `PA0..PA7` and `PB0..PB1` as `ADC_IN0..ADC_IN9`.

The generated design includes:

- GD32F310C8T6 LQFP48 MCU core.
- Ten ADC input filters, each with source-side test pad, 1 kOhm 0603 series resistor, and 100 nF 0603 shunt capacitor.
- 12V input terminal, SS14 reverse-protection diode, AMS1117-3.3 SOT-89 regulator, 10 uF input/output bulk capacitors, and 100 nF output decoupler.
- JLC/LCSC catalog-backed BOM mapping from `../../../jlcpcb-parts-database/db_build/jlcpcb-components.sqlite3`.

## Generate

```sh
python3 generate.py
```

## Routing DSL smoke

```sh
pardal route-dsl board-ir board_source.json -o artifacts/board.ir.json
pardal route-dsl plan routes.pdl.yaml artifacts/board.ir.json backend_manifest.json --route-plan-output artifacts/route-plan.ir.json --artifact-output artifacts/capability-report.json
pardal route-dsl candidates artifacts/board.ir.json artifacts/route-plan.ir.json backend_manifest.json --problem problem.json -o artifacts/route-candidates.json
pardal route-dsl check board-ir artifacts/board.ir.json
pardal route-dsl check route-plan artifacts/route-plan.ir.json
pardal route-dsl check candidates artifacts/route-candidates.json
```

## Strict physical/fab verification

```sh
pardal compile-physical board.pdl.yaml --output artifacts/gd32f310c8t6.kicad_pcb --strict --production-check --drc-report artifacts/drc-report.json --drc-diagnostics-report artifacts/drc-diagnostics.json --drc-diagnostics-format json --route-diagnostics-report artifacts/route-diagnostics.json --diagnostics-dashboard artifacts/diagnostics-dashboard.json --build-summary-output artifacts/build-summary-strict.json --production-report artifacts/production-checks.json --production-report-format json --manufacturing-archive-output artifacts/manufacturing-package.zip --jlc-bom-output artifacts/gd32f310c8t6.jlc.bom.csv --jlc-pnp-output artifacts/gd32f310c8t6.jlc.pnp.csv
pardal verify-production-summary artifacts/build-summary-strict.json
```

Run physical verification with system Python when `pcbnew` is not available in the venv:

```sh
PYTHONPATH=../.. /usr/bin/python3 -m pardal.cli compile-physical board.pdl.yaml --output artifacts/gd32f310c8t6.kicad_pcb --strict --production-check --drc-report artifacts/drc-report.json --drc-diagnostics-report artifacts/drc-diagnostics.json --drc-diagnostics-format json --route-diagnostics-report artifacts/route-diagnostics.json --diagnostics-dashboard artifacts/diagnostics-dashboard.json --build-summary-output artifacts/build-summary-strict.json --production-report artifacts/production-checks.json --production-report-format json --manufacturing-archive-output artifacts/manufacturing-package.zip --jlc-bom-output artifacts/gd32f310c8t6.jlc.bom.csv --jlc-pnp-output artifacts/gd32f310c8t6.jlc.pnp.csv
PYTHONPATH=../.. /usr/bin/python3 -m pardal.cli verify-production-summary artifacts/build-summary-strict.json
```

Current strict verification for the generated physical board is DRC-clean: 54/54 manual routes committed, 0 KiCad DRC violations, 0 unconnected items, production error count 0, and all selected LCSC codes present in the local catalog DB.
