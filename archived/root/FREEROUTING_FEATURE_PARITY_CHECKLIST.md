# FreeRouting Feature Parity Checklist (Pardal Mojo backend)

Purpose: turn “match FreeRouting” into a checklist that can be driven by fixtures and tests.  
Scope: routing backend (`pardal-pcb/pardal_router_mojo/`) + parity harness (`pardal-pcb/pcb_tool/tools/*parity*`).

Legend:
- **FR refs** = where the behavior lives in FreeRouting (`freerouting/src/main/java/app/freerouting/...`)
- **Fixtures** = directories under `freerouting/tests/` that exercise the feature
- **DoD** = measurable “done” signal (usually: fixture parity improves and stays improved)

## A) Core semantics + geometry model

| Area | Feature / primitive | FR refs (entry points) | Pardal status | Fixtures | Tests to add/port | DoD | Done |
|---|---|---|---|---|---|---|---|
| DSN IO | Parse padstacks + pins into obstacles/connectables | `designforms/specctra/*`, `core/Padstack.java`, `board/Pin.java` | **Incomplete** (DSN dump lacks pads/pins for fixture DSNs) | most DSN-only fixtures | unit: `dsn_parse_padstacks_*` | `dsn-dump` includes pads/pins for fixture DSNs | ☐ |
| DSN IO | Parse keepouts / boundaries / layer rules | `designforms/specctra/*`, `board/BoardOutline*` | Unknown | Issue180, 367 | unit: keepout parse + dump | parsed keepouts match DSN | ☐ |
| Rules | Clearance matrix (class vs class) | `rules/ClearanceMatrix.java` | Partial (router uses simplified spacing knobs) | Issue283, fpga | parity: clearance types converge | KiCad DRC clearance deltas shrink | ☐ |
| Geometry | Exact shape expansion (trace/via/pad with clearance) | `board/Item.calculate_tree_shapes`, `board/Trace`, `board/Via`, `geometry/planar/*` | Approx (grid + local DRC kernels) | Issue283 | unit: expanded shape intersection | no “0.0000mm” clearances from snapping | ☐ |
| Index | Spatial index w/ incremental updates | `board/ShapeSearchTree*` | Partial (`SpatialSegmentIndex` on segments) | Issue283 | unit: index update invariants | precommit checks match KiCad more often | ☐ |

## B) Routing algorithms (why FreeRouting reaches 0/0 where Pardal doesn’t)

| Area | Feature / primitive | FR refs (entry points) | Pardal status | Fixtures | Tests to add/port | DoD | Done |
|---|---|---|---|---|---|---|---|
| Maze router | Expansion rooms + doors (continuous free space) | `autoroute/MazeSearchAlgo.java`, `autoroute/*ExpansionRoom*`, `autoroute/*Door*` | Not implemented (grid A*) | Issue283, 367 | parity tier B adds | completes dense fixtures without resolution hacks | ☐ |
| Negotiation | Ripup + reroute with history costs | `autoroute/AutorouteEngine.java` (search: `ripup`, `history`) | Partial (ripup heuristics exist, not FR-equivalent) | Issue283, fpga | property tests around determinism | completion parity with oracle | ☐ |
| Shove routing | True geometric shove / push / recursion | `autoroute/MazeShoveTraceAlgo.java`, `board/ShoveTraceAlgo.java` | Approx (“local rip + reroute window”) | Issue283, 367 | unit: shove microcases | shorts/crossings drop without failing nets | ☐ |
| Pull-tight | Geometric post-processing (shorten, smooth, reduce vias) | `board/PullTightAlgo.java` | Partial / heuristic | fpga, 367 | snapshot compare | via count + length converge | ☐ |
| Fanout | BGA/bus fanout planner w/ constraints | `autoroute/BatchFanout.java` | Present but not parity-checked | Issue269, fpga | fanout fixture suite | fpga_small reaches 0/0 | ☐ |

## C) KiCad DRC parity categories

These are the categories that dominate deltas (example: Issue283 Mojo vs FreeRouting).

| DRC category | Typical root cause in Pardal | FR behavior that avoids it | Likely fix area | Fixtures | DoD | Done |
|---|---|---|---|---|---|---|
| `clearance` | grid snapping + insufficient inflation | continuous geometry + shove + exact clearance | geometry + router | Issue283 | clearance errors converge toward oracle | ☐ |
| `shorting_items` / `tracks_crossing` | intersections created by coarse legalization | shove/push + shape search prevents illegal crossings | shove + legalization | Issue283 | crossing/short counts drop, not replaced by failed nets | ☐ |
| `solder_mask_bridge` | mask not modeled during routing | FR routes with adequate spacing per rule set | rule extraction + inflation | Issue283 | mask bridge counts <= oracle | ☐ |
| `hole_clearance` / `hole_to_hole` | drills not treated with full constraints | exact drill shapes in geometry engine | geometry kernels + extraction | Issue283 | hole-related errors <= oracle | ☐ |
| `unconnected` | incomplete nets from route failure | negotiation + ripup to completion | routing strategy | Issue283, fpga | failed nets = 0 where oracle completes | ☐ |

### Notable parity win: pad/no-net clearance seeding

KiCad DRC deltas on small boards were dominated by clearance/shorts against *pads* and *no-net copper*, not just against already-routed tracks/vias.  
FreeRouting accounts for these as first-class board items; in Pardal/Mojo the practical equivalent is enabling:

- `seed_circle_keepouts: true` (commits pad/no-net circles into the dynamic keepout fields)
- `enforce_spacing: true` with `ncr_allow_overlaps: false` (treat clearance as a hard constraint)
- `resolution_mm: 0.1` on `fpga_small` for enough geometric freedom

Evidence:
- `pardal-pcb/build/parity_suites/fpga_small_seed_circles_hard_spacing_0p1/fpga_small_seed_circles_hard_spacing_0p1.summary.json` reaches KiCad DRC `0/0` for Mojo, matching the oracle.

## D) Fixture inventory (FreeRouting corpus)

| Fixture dir | Primary stressors (expected) | Oracle reaches 0/0? | Pardal target tier | Notes |
|---|---|---:|---|---|
| `Issue069-TestSensel` | small 2L, basic autoroute | ? | A | |
| `Issue180-Test` | KiCad PCB fixture (no DSN) | ? | A/B | |
| `Issue184-motorizedopener` | medium 2L | ? | B | |
| `Issue191-processor.Z80` | huge 2L, many nets | ? | C | |
| `Issue199-StackOverflow` | repro for algorithm edge case | ? | A | |
| `Issue230-CNH_Functional_Tester` | DSN parse/planes/keepouts likely | ? | B/C | DSN parsing currently fails here |
| `Issue269-min_fr_test` | 4L, tiny, negotiation core | ? | A | |
| `Issue269-NoViasOnPowerPlanes` | 4L, via policy/planes | ? | A/B | |
| `Issue269-NoWiresOnPowerLayers` | 4L, layer restrictions | ? | A/B | |
| `Issue283-UnconnectedTracesUnderPads` | pad clearance + shove + completion | No (oracle still nonzero) | A/B | Biggest delta driver today |
| `Issue367-UltraFlactyl` | many nets + geometry + completion | ? | C | |
| `Issue368-CorneyIslandWireless` | small, DSN parsing edge | ? | A | |
| `Issue558-dev-board-autoroute-demo` | demo board | ? | B | |

## Workflow rule (avoid blockers)

If a row is blocked because a required primitive is missing:
1. Add a minimal unit test that isolates the primitive.
2. Implement the primitive in Mojo (or harness) until the unit test passes.
3. Mark the row **Done** and re-run Tier A suite.
