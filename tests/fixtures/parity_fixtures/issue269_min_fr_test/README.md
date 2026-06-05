# issue269_min_fr_test

Source: `freerouting/tests/Issue269-min_fr_test/` (vendored FreeRouting fixture).

This fixture is intended as the **smallest end-to-end parity smoke**:

- KiCad → Specctra DSN export (pcbnew)
- FreeRouting oracle → Specctra SES
- pcbnew SES import → routed KiCad PCB
- KiCad DRC JSON

Artifacts are produced under `out/` by `pardal/tools/run_parity_fixture.py`.

