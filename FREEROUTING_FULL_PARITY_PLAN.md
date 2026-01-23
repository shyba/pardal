# FreeRouting → `pardal-pcb` Full Parity Plan (Lockstep Port, “1000% confidence”)

This document **replaces all prior parity plans**. It is intentionally heavy and mechanical: the only way to reach “no surprises” parity on dense boards is to treat FreeRouting (Java) as the spec and port the relevant code paths line‑by‑line with oracle gates.

Scope:
- Target backend: `pardal-pcb/pardal_router_mojo/` (Mojo AOT binary `build/pardal-router-mojo`).
- Oracles:
  - FreeRouting (this repo’s `freerouting/`) is the behavioral oracle.
  - KiCad DRC (`kicad-cli pcb drc` in docker) is the legality oracle for any fixture that has a `.kicad_pcb`.

Non‑goals:
- Do **not** modify KiCad.
- Do not “tune around” missing primitives with heuristic hacks. If something is missing, port it.

---

## 0) What just happened (PRM fallback) and why it didn’t fix Issue283

We recently added a PRM‑style “maze fallback” (`pardal_router_mojo/maze.mojo`) that tries to route around obstacles when grid A* returns no path. It works on a toy obstacle test, but it does not materially improve `Issue283-UnconnectedTracesUnderPads`.

Root causes (structural, not “parameter tuning”):
- The PRM fallback is **single‑layer**, while the hard fixtures require multi‑layer negotiation and via decisions.
- It operates on **approximate obstacle geometry** (circles/polygons extracted into `problem.json`) rather than FreeRouting’s exact shape expansion + incremental search tree collision checks.
- It does not implement FreeRouting’s completion mechanisms:
  - **Negotiation routing** (history‑based ripup/reroute over many passes).
  - **Shove routing** (geometric push of existing traces/vias to open channels).

This plan therefore stops spending time on partial fixes. If we want parity on dense fixtures, we must port the FreeRouting core.

---

## 1) “1000% confidence” definition (what “done” means)

We are done only when all are true:

1. **Fixture parity (behavior)**  
   For every fixture in Appendix A, `pardal` matches FreeRouting on:
   - completion status (all nets routed vs remaining incompletes)
   - (for seeded runs) determinism: same seed ⇒ same result

2. **Legality parity (KiCad)**  
   For any fixture with a `.kicad_pcb`, the routed output passes KiCad DRC:
   - 0 violations, 0 unconnected

3. **Behavioral parity (FreeRouting internal DRC/stats)**  
   For DSN‑only fixtures (no `.kicad_pcb`), we match FreeRouting’s:
   - board statistics (incomplete count, clearance violations, drill item count, etc.)
   - board hash (or a normalized equivalent if we must explicitly document a deviation)

4. **No hidden approximations**  
   Where FreeRouting uses exact integer geometry, we implement the same geometry and the same queries.

The only practical path to that level of certainty is a **lockstep port**:
- FreeRouting code is the spec.
- We port the relevant Java packages into Mojo with minimal semantic changes.
- We port/translate the JUnit tests and create per‑fixture oracle comparisons.

---

## 2) Hard constraints and oracles

Hard constraints:
- No KiCad modifications.
- Keep existing fast python unit test suite green (`pytest -m "not slow and not parity"`).

Oracles:
- **FreeRouting**: run in this repo, headless, from DSN.
- **KiCad DRC**: run via docker `kicad-cli pcb drc` on `.kicad_pcb`.

Canonical routing input:
- **Specctra DSN** (`.dsn`) is the canonical input semantics.
  - `.kicad_pcb` fixtures are exported to DSN via KiCad (harness already does this).
  - `.dsn` fixtures route directly.

Canonical outputs:
- For pcbnew application and KiCad DRC: `routes.json` + routed `.kicad_pcb`.
- For FreeRouting baseline comparison and debugging: routed DSN + SES.

---

## 3) Repo layout / code placement

Existing grid router (kept during transition):
- `pardal-pcb/pardal_router_mojo/pardal_router_mojo/router.mojo` + grid/A* helpers

New FreeRouting‑compatible port (new backend):
- Create `pardal-pcb/pardal_router_mojo/pardal_router_mojo/fr/`
- Mirror FreeRouting package structure (as far as Mojo ergonomics allow):
  - `fr/geometry/planar/*`
  - `fr/rules/*`
  - `fr/board/*`
  - `fr/designforms/specctra/*`
  - `fr/drc/*`
  - `fr/autoroute/*`
  - `fr/core/*` (only what the above needs)

Python harness (already exists; extend, don’t replace):
- `pardal-pcb/pcb_tool/tools/run_parity_fixture.py`
- `pardal-pcb/pcb_tool/tools/run_parity_suite.py`

Test strategy:
- Fast unit tests stay green: `cd pardal-pcb && ./venv/bin/python -m pytest -m "not slow and not parity"`
- Slow oracle tests are explicit: `--run-slow -m slow` and `-m parity`

---

## 4) Porting rules (to avoid drift and blockers)

Non‑negotiable workflow rules:

1. **Port in dependency order**
   - geometry → rules → board/search trees → DRC/stats/hash → autoroute

2. **One Java file → one Mojo module**
   - Preserve names, constants, coordinate systems.
   - If Mojo cannot represent something directly, add a compatibility wrapper and a test proving equivalence on corpus inputs.

3. **Test-first for primitives**
   - If a port step needs a missing primitive, add a *minimal* unit test that isolates it.
   - Implement the primitive.
   - Add it to Appendix C (“Primitive checklist”) and mark it “Done”.

4. **No heuristic workarounds**
   - Do not add more grid heuristics (PRM, random sampling, etc.) as substitutes for missing FreeRouting primitives.
   - The only acceptable “fallback” is: “use the ported FreeRouting behavior”.

### 4.1 Mojo porting constraints (encode these up-front to avoid repeat blockers)

This is a short list of Mojo realities that repeatedly cause “surprise blockers” if we don’t plan for them:

- `List[T]` requires `T: Copyable`. If you need a container of non‑`Copyable` values:
  - store **indices** (`List[Int]`) into parallel arrays, or
  - store `PythonObject` records (slower, but acceptable for non-hot paths), or
  - refactor the type to be `Copyable, Movable` (often by making it fieldwise-initializable and avoiding owning pointers).
- Moves vs copies:
  - use `^` to transfer ownership when required,
  - use `.copy()` explicitly where needed.
- Raising contexts:
  - iterating Python objects (`for x in py_obj`) is typically `raises`; mark helpers as `raises` or wrap with `try`.

**Rule:** when a port step hits any of the above, the fix is not “work around it in algorithm land”; the fix is to introduce a stable representation (indices + arrays) and add a unit test for the representation invariants.

### 4.2 Lockstep oracle contract (baseline schema; no debates later)

For each fixture, we record a baseline and we never reinterpret it. `baseline.json` MUST include:
- identity: fixture path, seed, max passes, router settings used
- completion: incomplete net/item count, failed nets list if available
- stats: FreeRouting `BoardStatistics` fields we can extract deterministically
- DRC:
  - FreeRouting DRC JSON (for DSN fixtures)
  - KiCad DRC JSON + summary counts (for KiCad fixtures)
- hash:
  - FreeRouting `board.get_hash()` (always)
  - a “normalized hash” only if we explicitly document normalization rules and prove they preserve parity intent
- outputs:
  - routed DSN + SES locations
  - routed KiCad PCB location (if applicable)

**Rule:** every ported phase that claims parity must compare against these baseline fields, not against ad-hoc “looks good” checks.

---

# Multi‑phase plan (mechanical, no decisions in-between)

Each phase below has:
- **Inputs**: what must already exist
- **Port list**: explicit files/packages to port
- **Tests**: what tests must be added/ported
- **DoD**: what must be true before moving on

## Phase gates (fixture sets; fixed seeds; no “which test should we use?” later)

Use these exact gates in addition to each phase’s own DoD. Seeds are fixed to match upstream tests where possible.

| Phase | Gate fixtures | Seed(s) | Must match |
|---:|---|---|---|
| 0 | **All** Appendix A fixtures | 12345 (default) | baseline generation is deterministic |
| 2 | `empty_board.dsn`, `Issue026-J2_reference.dsn`, `Issue229-display-8-digit-hc595.dsn`, `Issue558-dev-board.dsn` | 12345 | pre-route parse stats |
| 4 | `rules/ClearanceMatrixTest` port | n/a | 1:1 unit semantics |
| 6 | `BBD_Mars-64.dsn` | 12345 | DRC JSON structure + stats |
| 7 | `Issue026-J2_reference.dsn` | 12345 | single-connection maze routing hash/stats |
| 8 | `Issue269-NoViasOnPowerPlanes/Issue269-NoViasOnPowerPlanes.dsn` | 12345 | via/layer restriction behavior |
| 9 | `Issue026-J2_reference.dsn` | 12345 + unseeded | determinism + pass semantics |
| 10 | `Issue283-UnconnectedTracesUnderPads/Test.kicad_pcb` | 12345 | completion + KiCad DRC deltas converge to baseline |
| 12 | `pardal-pcb/fpga/*`, `pardal-pcb/fpga_large/*` | fixed | KiCad DRC 0/0 |

## Phase 0 — Baselines for every fixture (freeze the spec)

Goal: eliminate guesswork by capturing FreeRouting’s behavior on the entire corpus.

Inputs:
- Working `freerouting/` build.
- Working parity harness (already present).

Tasks:
1. Add a baseline generator (python tool) that for each DSN fixture:
   - runs FreeRouting headless with fixed seed and pass settings
   - saves:
     - routed DSN
     - routed SES
     - board hash
     - `BoardStatistics` (incomplete count, clearance violations, drill counts, etc.)
     - FreeRouting DRC JSON (same schema style as FreeRouting unit test)
2. For `.kicad_pcb` fixtures:
   - export DSN via KiCad
   - run FreeRouting baseline from that DSN
   - apply the routed output back into KiCad PCB (existing harness path)
   - run KiCad DRC and store the KiCad DRC JSON + summary counts
3. Store all baselines under:
   - `pardal-pcb/build/freerouting_baselines/<fixture_id>/...`
   - (never hand-edit baseline files; regenerate)

Tests to add/port:
- Port FreeRouting JUnit determinism expectations as python tests:
  - fixed seed ⇒ same hash
  - unseeded ⇒ different hash (probabilistic; implement with “eventually different” threshold like upstream)

DoD:
- For every fixture in Appendix A:
  - A baseline folder exists with a `baseline.json` containing at least:
    - completion status
    - hash
    - stats summary
    - DRC summary
  - Regenerating baselines with same seed yields identical baseline outputs.

## Phase 1 — Generate a port manifest and enforce “no missing files”

Goal: prevent “we forgot to port X” class of blockers.

Tasks:
1. Create a **port manifest** (generated file, committed or regenerated as needed) that enumerates all Java files in scope:
   - autoroute, board, rules, geometry/planar, drc, designforms/specctra, datastructures, core (subset)
2. For each manifest entry:
   - create a corresponding Mojo module path under `pardal_router_mojo/pardal_router_mojo/fr/...`
   - add a status row in a “Port Status” table (Appendix D)

DoD:
- Manifest lists every Java file in the scoped packages (Appendix D).
- There is an explicit tracking mechanism (table or generated report) showing each file as:
  - not started / compiling / tested / parity‑gated

## Phase 2 — DSN parsing parity (Specctra DSN → internal board model)

Goal: our internal board must represent the exact same constraints FreeRouting sees.

Port list (FreeRouting anchors):
- `freerouting/src/main/java/app/freerouting/designforms/specctra/*` (DSN/SES parsing + serialization)
- `freerouting/src/main/java/app/freerouting/board/Layer*.java`
- `freerouting/src/main/java/app/freerouting/rules/*` (enough to attach rule semantics during parse)
- `freerouting/src/main/java/app/freerouting/core/Padstack*.java`, `core/Padstacks.java`
- `freerouting/src/main/java/app/freerouting/board/Pin.java`, `board/Via.java`, `board/Trace.java`

Tests to add/port:
1. “Golden parse” tests:
   - DSN in → serialize → parse again ⇒ stable normalized representation
2. “Baseline stats” tests:
   - for each DSN fixture: parse DSN and compute pre‑route stats
   - compare to FreeRouting baseline pre‑route stats (Phase 0 output)

DoD:
- For Tier A DSNs (start with the JUnit DSNs):
  - parse succeeds
  - pre‑route board statistics match baseline exactly (or with documented allowed tolerances)

## Phase 3 — Planar geometry parity (exact integer geometry)

Goal: implement the same geometric operations FreeRouting uses for collision/clearance and shape expansion.

Port list:
- `freerouting/src/main/java/app/freerouting/geometry/planar/*` (entire package, 34 files)
- `freerouting/src/main/java/app/freerouting/datastructures/BigIntAux.java` (if needed by planar math)

Tests to add/port:
- Direct unit translations where possible (small geometry invariants).
- Property tests on corpus-derived coordinate ranges:
  - intersection/containment equivalence
  - bounding boxes
  - polygon/segment distance checks

DoD:
- All geometry modules compile in Mojo.
- Geometry unit tests pass.
- Geometry operations do not overflow on any fixture coordinate range (explicit test).

## Phase 4 — Rules parity (clearances, classes, vias)

Goal: match FreeRouting’s clearance matrix and netclass semantics.

Port list:
- `freerouting/src/main/java/app/freerouting/rules/*` (10 files)

Tests to add/port:
- Port `freerouting/src/test/java/app/freerouting/rules/ClearanceMatrixTest.java`.

DoD:
- Clearance matrix semantics match FreeRouting exactly (test passes).
- DSN parse attaches the same clearance class IDs and via rules as baseline.

## Phase 5 — Search tree parity (incremental spatial queries)

Goal: incremental geometry collision queries must behave like FreeRouting.

Port list:
- `freerouting/src/main/java/app/freerouting/board/ShapeSearchTree*.java`
- `freerouting/src/main/java/app/freerouting/board/SearchTreeManager.java`
- `freerouting/src/main/java/app/freerouting/board/ItemSearchTreesInfo.java`
- `freerouting/src/main/java/app/freerouting/datastructures/ShapeTree.java` (and dependencies)

Tests to add/port:
- Deterministic query tests:
  - same sequence of inserts/removals yields identical query results
  - compare query results to FreeRouting on fixed random seeds (golden)

DoD:
- On Tier A fixtures, for a fixed set of seeded random queries, our search tree answers match FreeRouting.

## Phase 6 — DRC + board statistics parity (oracle inside the port)

Goal: we must be able to evaluate legality and completion without relying on KiCad for DSN-only fixtures.

Port list:
- `freerouting/src/main/java/app/freerouting/drc/*`
- `freerouting/src/main/java/app/freerouting/core/scoring/*`
- supporting board stats:
  - `freerouting/src/main/java/app/freerouting/board/RoutingBoard.java` (stats, hash)

Tests to add/port:
- Port `freerouting/src/test/java/app/freerouting/drc/DesignRulesCheckerTest.java` (structure + JSON validity).
- Port the issue JUnit tests that assert `incompleteCount == 0` and `clearanceViolations == 0`:
  - Issue026, Issue159, Issue229, Issue558.

DoD:
- For the DSNs referenced by FreeRouting JUnit tests:
  - post-route stats match FreeRouting baseline exactly.
- DRC JSON output matches the schema structure FreeRouting produces.

## Phase 7 — Maze router parity (expansion rooms + doors, continuous routing)

Goal: implement FreeRouting’s maze router exactly (this is the core missing piece for dense routing).

Port list (explicit, no omissions):
- `freerouting/src/main/java/app/freerouting/autoroute/MazeSearchAlgo.java`
- `freerouting/src/main/java/app/freerouting/autoroute/MazeSearchElement.java`
- `freerouting/src/main/java/app/freerouting/autoroute/MazeListElement.java`
- `freerouting/src/main/java/app/freerouting/autoroute/ExpansionRoom.java`
- `freerouting/src/main/java/app/freerouting/autoroute/FreeSpaceExpansionRoom.java`
- `freerouting/src/main/java/app/freerouting/autoroute/IncompleteFreeSpaceExpansionRoom.java`
- `freerouting/src/main/java/app/freerouting/autoroute/CompleteExpansionRoom.java`
- `freerouting/src/main/java/app/freerouting/autoroute/CompleteFreeSpaceExpansionRoom.java`
- `freerouting/src/main/java/app/freerouting/autoroute/ObstacleExpansionRoom.java`
- `freerouting/src/main/java/app/freerouting/autoroute/ExpansionDoor.java`
- `freerouting/src/main/java/app/freerouting/autoroute/TargetItemExpansionDoor.java`
- `freerouting/src/main/java/app/freerouting/autoroute/SortedRoomNeighbours.java`
- `freerouting/src/main/java/app/freerouting/autoroute/Sorted45DegreeRoomNeighbours.java`
- `freerouting/src/main/java/app/freerouting/autoroute/SortedOrthogonalRoomNeighbours.java`
- `freerouting/src/main/java/app/freerouting/autoroute/DestinationDistance.java`
- `freerouting/src/main/java/app/freerouting/autoroute/Connection.java`
- `freerouting/src/main/java/app/freerouting/autoroute/LocateFoundConnectionAlgo*.java`
- `freerouting/src/main/java/app/freerouting/autoroute/InsertFoundConnectionAlgo.java`

Tests to add/port:
- Golden “single connection” tests:
  - pick Tier A DSN (Issue026) and route one connection with fixed seed
  - compare produced board hash + stats to FreeRouting baseline

DoD:
- For Issue026 DSN (and at least one additional DSN):
  - routed result hash matches FreeRouting for the same seed (or a documented, justified normalization).

## Phase 8 — Multi-layer + via parity

Goal: match FreeRouting’s via insertion, layer restrictions, and drill obstacles.

Port list:
- `freerouting/src/main/java/app/freerouting/board/Via.java`, `board/DrillItem.java`, `board/ViaObstacleArea.java`
- `freerouting/src/main/java/app/freerouting/autoroute/ExpansionDrill.java`
- `freerouting/src/main/java/app/freerouting/autoroute/DrillPage*.java`

Tests to add/port:
- Route on multi-layer DSNs:
  - `Issue558-dev-board.dsn` (edge clearance)
  - `Issue269-NoViasOnPowerPlanes/Issue269-NoViasOnPowerPlanes.dsn` (via restrictions)

DoD:
- Multi-layer routed outputs match FreeRouting baseline stats and DRC categories.

## Phase 9 — Negotiation routing parity (history, ripup, passes)

Goal: match FreeRouting’s multi-pass negotiation loop (completion is impossible without it).

Port list:
- `freerouting/src/main/java/app/freerouting/autoroute/AutorouteEngine.java`
- `freerouting/src/main/java/app/freerouting/autoroute/AutorouteControl.java`
- `freerouting/src/main/java/app/freerouting/autoroute/AutorouteAttempt*.java`
- `freerouting/src/main/java/app/freerouting/autoroute/BoardHistory*.java`
- `freerouting/src/main/java/app/freerouting/autoroute/BatchAutorouter*.java`

Tests to add/port:
- Port `Issue522Test` (max passes respected).
- Port `RandomSeedTest` (determinism expectations).

DoD:
- For Tier A DSNs:
  - seeded runs are deterministic and match FreeRouting.
  - pass count semantics match FreeRouting.

## Phase 10 — Shove routing parity (geometric push)

Goal: match FreeRouting’s ability to “make space” in dense areas.

Port list:
- `freerouting/src/main/java/app/freerouting/autoroute/MazeShoveTraceAlgo.java`
- `freerouting/src/main/java/app/freerouting/board/ShoveTraceAlgo.java`
- `freerouting/src/main/java/app/freerouting/board/ForcedViaAlgo.java`
- `freerouting/src/main/java/app/freerouting/board/ForcedPadAlgo.java`
- `freerouting/src/main/java/app/freerouting/interactive/MakeSpaceState.java` (only the headless shove logic it depends on; no GUI)

Tests to add/port:
- Micro shove fixtures (minimal DSNs) generated from FreeRouting’s internal test patterns (or extracted from real fixture hotspots).
- Tier A/B parity gate:
  - `Issue283-UnconnectedTracesUnderPads/Test.dsn` and `Test.kicad_pcb`

DoD:
- `Issue283-UnconnectedTracesUnderPads` matches FreeRouting baseline completion + DRC categories.

## Phase 11 — Pull-tight + optimization parity

Goal: match FreeRouting post-processing that reduces length/vias and resolves minor violations.

Port list:
- `freerouting/src/main/java/app/freerouting/board/PullTightAlgo*.java`
- `freerouting/src/main/java/app/freerouting/autoroute/BatchOptimizer*.java`

Tests to add/port:
- Golden compare:
  - route → optimize → hash/stats match FreeRouting baseline on at least 2 fixtures

DoD:
- Post-optimization stats converge (vias/length) to FreeRouting baseline.

## Phase 12 — Fanout parity (BGA breakout / production targets)

Goal: match FreeRouting fanout planning for BGA-style boards and reach KiCad DRC clean on project boards.

Port list:
- `freerouting/src/main/java/app/freerouting/autoroute/BatchFanout.java`
- any dependencies it pulls (manifest ensures none missed)

Targets (non‑FreeRouting fixtures):
- `pardal-pcb/fpga/*` (fpga_small)
- `pardal-pcb/fpga_large/*` (fpga_large)

DoD:
- `fpga_small` routes to KiCad DRC 0/0 with the FreeRouting‑port backend.
- `fpga_large` routes to KiCad DRC 0/0 within the agreed runtime budget.

---

# Appendix A — Full fixture corpus (must be covered)

## A1) DSN corpus (`freerouting/tests/**/*.dsn`)

**Rule**: every row here must have a FreeRouting baseline and a parity gate.

| ID | Path | Type | FR JUnit ref? | FR baseline (complete?) | FR baseline (violations/unconnected) | Pardal baseline | Phase gate | Notes |
|---:|---|---|---|---|---|---|---|---|
| 1 | `BBD_Mars-64.dsn` | DSN | yes | TBD | TBD | TBD | TBD | |
| 2 | `Issue006-LPC18XX_43XX_SCH.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 3 | `Issue015-StackOverflow.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 4 | `Issue022-AutoRouter_interrupted.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 5 | `Issue026-J2_reference.dsn` | DSN | yes | TBD | TBD | TBD | TBD | |
| 6 | `Issue027-zMRETestFixture.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 7 | `Issue029-hw48na.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 8 | `Issue034-Green14SegLED.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 9 | `Issue035-ReadPlaceScope.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 10 | `Issue039-bug-design.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 11 | `Issue054-tairakb.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 12 | `Issue066-Project_GP8B.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 13 | `Issue069-TestSensel/TestSensel-KiCad6.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 14 | `Issue069-TestSensel/TestSensel.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 15 | `Issue070-Autorouter_FQ101_PCB_2022-05-13.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 16 | `Issue093-interf_u.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 17 | `Issue102-Mars-64-revE-rot00.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 18 | `Issue103-Board-Routed.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 19 | `Issue103-Board-Unrouted.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 20 | `Issue107-freq_teiler_200kHz_kicad.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 21 | `Issue107-freq_teiler_200kHz_kicad_bad.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 22 | `Issue110-Pajalnaja_stancija.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 23 | `Issue110-RelayModule.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 24 | `Issue110-testPCBSpecctraFile.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 25 | `Issue110-testProjectFromFreeroutingBugTest.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 26 | `Issue110-testProjectFromFreeroutingBugTest01.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 27 | `Issue110-Паяльная станция.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 28 | `Issue113-Protein.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 29 | `Issue143-rpi_splitter.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 30 | `Issue143-rpi_splitter_mod.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 31 | `Issue145-smoothieboard.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 32 | `Issue153-wavefolder.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 33 | `Issue155-CH376_MCP795_Module.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 34 | `Issue157-TeamAdapt-LinePCB.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 35 | `Issue159-setonix_2hp-pcb.dsn` | DSN | yes | TBD | TBD | TBD | TBD | |
| 36 | `Issue163-pic_programmer.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 37 | `Issue178-KeebMaker_Sofle_Choc.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 38 | `Issue179-Autorouter_PCB1_2023-3-24.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 39 | `Issue187-processor.Z80.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 40 | `Issue190-processor.Z80.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 41 | `Issue191-processor.Z80/processor.Z80.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 42 | `Issue199-StackOverflow/Signale_Vor+Block.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 43 | `Issue208-freerouting.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 44 | `Issue209-split05.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 45 | `Issue209-split10.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 46 | `Issue214-freerouting.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 47 | `Issue217-8088sbc.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 48 | `Issue219-LogicBoard_smt.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 49 | `Issue229-display-8-digit-hc595.dsn` | DSN | yes | TBD | TBD | TBD | TBD | |
| 50 | `Issue230-CNH_Functional_Tester/CNH_Functional_Tester_1.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 51 | `Issue269-NoViasOnPowerPlanes/Issue269-NoViasOnPowerPlanes.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 52 | `Issue269-caniot-tiny-arm.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 53 | `Issue269-min_fr_test/min_fr_test.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 54 | `Issue269-min_fr_test/min_fr_test_no_quotes.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 55 | `Issue269-z10_module.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 56 | `Issue270-non-ansi_bracket.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 57 | `Issue283-UnconnectedTracesUnderPads/Test.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 58 | `Issue289-Autorouter_PCB_FHT-8086_2024-03-08.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 59 | `Issue289-Autorouter_PCB_FHT-VGA_2024-03-25.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 60 | `Issue297-myboard.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 61 | `Issue313-FastTest.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 62 | `Issue326-Mars-64-revE.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 63 | `Issue367-Charger.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 64 | `Issue367-UltraFlactyl/UltraFlactyl.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 65 | `Issue368-CorneyIslandWireless/corney_island_wireless.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 66 | `Issue413-test.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 67 | `Issue420-contribution-board.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 68 | `Issue433-my-board.dsn` | DSN |  | TBD | TBD | TBD | TBD | |
| 69 | `Issue555-BBD_Mars-64.dsn` | DSN | yes | TBD | TBD | TBD | TBD | |
| 70 | `Issue555-CNH_Functional_Tester_1.dsn` | DSN | yes | TBD | TBD | TBD | TBD | |
| 71 | `Issue558-dev-board.dsn` | DSN | yes | TBD | TBD | TBD | TBD | |
| 72 | `Issue575-drc_BBD_Mars-64_6_track_1_hole_clearance_violations.dsn` | DSN | yes | TBD | TBD | TBD | TBD | upstream JUnit is disabled |
| 73 | `Issue575-drc_Natural_Tone_Preamp_7_unconnected_items.dsn` | DSN | yes | TBD | TBD | TBD | TBD | upstream JUnit is disabled |
| 74 | `Issue575-drc_dev-board_4_hole_clearance_violations.dsn` | DSN | yes | TBD | TBD | TBD | TBD | upstream JUnit is disabled |
| 75 | `empty_board.dsn` | DSN | yes | TBD | TBD | TBD | TBD | |

## A2) KiCad PCB corpus (`freerouting/tests/**/*.kicad_pcb`)

| ID | Path | Type | Has DSN sibling? | FR baseline (complete?) | KiCad DRC baseline (0/0?) | Pardal baseline | Phase gate | Notes |
|---:|---|---|---|---|---|---|---|---|
| 1 | `Issue069-TestSensel/TestSensel.kicad_pcb` | KiCad PCB | yes | TBD | TBD | TBD | TBD | |
| 2 | `Issue180-Test/Test.kicad_pcb` | KiCad PCB |  | TBD | TBD | TBD | TBD | |
| 3 | `Issue184-motorizedopener/motorizedopener.kicad_pcb` | KiCad PCB |  | TBD | TBD | TBD | TBD | |
| 4 | `Issue191-processor.Z80/processor.Z80.kicad_pcb` | KiCad PCB | yes | TBD | TBD | TBD | TBD | |
| 5 | `Issue230-CNH_Functional_Tester/CNH_Functional_Tester_1.kicad_pcb` | KiCad PCB | yes | TBD | TBD | TBD | TBD | |
| 6 | `Issue269-NoViasOnPowerPlanes/Issue269-NoViasOnPowerPlanes.kicad_pcb` | KiCad PCB | yes | TBD | TBD | TBD | TBD | |
| 7 | `Issue269-NoWiresOnPowerLayers/proba.kicad_pcb` | KiCad PCB |  | TBD | TBD | TBD | TBD | |
| 8 | `Issue269-min_fr_test/min_fr_test.kicad_pcb` | KiCad PCB | yes | TBD | TBD | TBD | TBD | |
| 9 | `Issue283-UnconnectedTracesUnderPads/Test.kicad_pcb` | KiCad PCB | yes | TBD | TBD | TBD | TBD | |
| 10 | `Issue367-UltraFlactyl/UltraFlactyl.kicad_pcb` | KiCad PCB | yes | TBD | TBD | TBD | TBD | |
| 11 | `Issue368-CorneyIslandWireless/corney_island_wireless.kicad_pcb` | KiCad PCB | yes | TBD | TBD | TBD | TBD | |
| 12 | `Issue558-dev-board-autoroute-demo/dev-board.kicad_pcb` | KiCad PCB |  | TBD | TBD | TBD | TBD | |

---

# Appendix B — FreeRouting JUnit test inventory (must be covered)

These tests encode “what FreeRouting guarantees”. We port them (or their intent) into `pardal-pcb/tests/` and treat them as gates.

| ID | FR test | Focus | Fixtures referenced | Port target (pardal-pcb/tests) | Phase gate | DoD |
|---:|---|---|---|---|---|---|
| 1 | `app/freerouting/autoroute/BoardHistoryTest.java` | board snapshot/restore + scoring | `empty_board.dsn`, `Issue159-setonix_2hp-pcb.dsn` | TBD | Phase 9 | passes 1:1 |
| 2 | `app/freerouting/core/StoppableThreadTest.java` | stoppable thread | none | TBD | Phase 9 | passes 1:1 |
| 3 | `app/freerouting/datastructures/IdentifierTypeTest.java` | identifier parsing | none | TBD | Phase 2 | passes 1:1 |
| 4 | `app/freerouting/drc/DesignRulesCheckerTest.java` | DRC JSON report structure | `BBD_Mars-64.dsn` | TBD | Phase 6 | schema + fields match |
| 5 | `app/freerouting/logger/LogEntriesTest.java` | logging | none | TBD | Phase 0/1 | passes (or documented N/A) |
| 6 | `app/freerouting/management/RoutingJobSchedulerTest.java` | job scheduler | none | TBD | Phase 9 | passes (or documented N/A) |
| 7 | `app/freerouting/management/SessionManagerTest.java` | session management | none | TBD | Phase 0/1 | passes (or documented N/A) |
| 8 | `app/freerouting/rules/ClearanceMatrixTest.java` | clearance matrix semantics | none | TBD | Phase 4 | passes 1:1 |
| 9 | `app/freerouting/tests/Issue026Test.java` | completion + clearance + drill count | `Issue026-J2_reference.dsn` | TBD | Phase 6/7 | matches stats |
| 10 | `app/freerouting/tests/Issue159Test.java` | completion + memory regression | `Issue159-setonix_2hp-pcb.dsn` | TBD | Phase 9 | matches stats |
| 11 | `app/freerouting/tests/Issue229Test.java` | keepout export correctness | `Issue229-display-8-digit-hc595.dsn` | TBD | Phase 6/7 | matches stats |
| 12 | `app/freerouting/tests/Issue522Test.java` | max passes respected | `Issue026-J2_reference.dsn` | TBD | Phase 9 | matches pass behavior |
| 13 | `app/freerouting/tests/Issue555Test.java` | performance (disabled upstream) | `Issue555-*` | TBD | Phase 12 (optional) | target runtime |
| 14 | `app/freerouting/tests/Issue558Test.java` | edge clearance | `Issue558-dev-board.dsn` | TBD | Phase 8 | matches stats |
| 15 | `app/freerouting/tests/Issue575Test.java` | DRC invariants (disabled upstream) | `Issue575-*` | TBD | optional | matches counts if enabled |
| 16 | `app/freerouting/tests/RandomSeedTest.java` | determinism / RNG | `Issue026-J2_reference.dsn` | TBD | Phase 9 | matches determinism |
| 17 | `app/freerouting/tests/TestBasedOnAnIssue.java` | test harness | n/a | n/a | Phase 0 | n/a |

---

# Appendix C — Primitive checklist (“if blocked, implement the primitive”)

This is the “no blockers” table. Any time work stalls due to a missing primitive, it gets added here with a test and a DoD.

| ID | Primitive | FR anchor | Needed for | Test to add | DoD | Done |
|---:|---|---|---|---|---|---|
| 1 | Exact shape expansion with clearance | `board/Item.calculate_tree_shapes`, `rules/ClearanceMatrix` | DRC + routing legality | geometry unit tests | identical overlaps vs FR | ☐ |
| 2 | Incremental spatial search tree | `board/ShapeSearchTree*`, `board/SearchTreeManager` | shove + maze legality | query golden tests | query parity vs FR | ☐ |
| 3 | Clearance matrix semantics | `rules/ClearanceMatrix` | correct constraints | port JUnit | JUnit parity | ☐ |
| 4 | Board hash + statistics | `board/RoutingBoard.get_hash`, `core/scoring/*` | determinism + baseline compare | port JUnit + golden | hash/stats parity | ☐ |
| 5 | Expansion rooms + doors graph | `autoroute/*ExpansionRoom*`, `*Door*` | dense routing | golden on Issue026 | identical pathing | ☐ |
| 6 | Negotiation router history costs | `autoroute/AutorouteEngine` | completion | seeded parity runs | completion parity | ☐ |
| 7 | Shove routing | `autoroute/MazeShoveTraceAlgo`, `board/ShoveTraceAlgo` | Issue283 | Issue283 gate | parity vs FR | ☐ |
| 8 | DSN identifier handling (quotes/unicode) | `designforms/specctra/Parser`, `datastructures/IdentifierType` | parse the full corpus | port JUnit `IdentifierTypeTest` + DSN parse tests | no DSN parse failures in Appendix A | ☐ |
| 9 | Board outline + edge clearance semantics | `board/BoardOutline`, `rules/ClearanceMatrix`, `autoroute/*` | edge DRC, routing legality | Issue558 baseline compare | edge violations match baseline | ☐ |
| 10 | Planes / conduction areas semantics | `board/ConductionArea`, `designforms/specctra/Plane` | power layers + keepouts | Issue269 NoViasOnPowerPlanes gate | plane rules match baseline | ☐ |
| 11 | Drill/hole modeling (padstacks, vias) | `core/Padstack`, `board/DrillItem`, `board/Via` | hole clearance DRC | Issue575 fixtures (optional) | hole clearance counts match baseline | ☐ |
| 12 | Layer stack + via span rules | `board/LayerStructure`, `rules/ViaRule`, `board/Via` | multi-layer routing | Issue269 gate | via span parity | ☐ |
| 13 | Incomplete connectivity computation | `interactive/NetIncompletes`, `interactive/RatsNest` | completion reporting | Issue026/159 stats compare | incompleteCount parity | ☐ |
| 14 | RouterSettings seed/pass semantics | `settings/RouterSettings`, `tests/RandomSeedTest` | determinism and iteration control | port `RandomSeedTest`, `Issue522Test` | deterministic seeded behavior | ☐ |

---

# Appendix D — Java package scope (port manifest root)

This table defines what must be ported for “no surprises” parity. The manifest generated in Phase 1 must include every file in each “IN SCOPE” package.

| Package | Java path | Java files | IN SCOPE | Reason | Phase(s) |
|---|---|---:|:---:|---|---|
| autoroute | `freerouting/src/main/java/app/freerouting/autoroute/` | 50 | ✅ | routing core | 7–12 |
| board | `freerouting/src/main/java/app/freerouting/board/` | 51 | ✅ | board model + search trees | 2–6 |
| geometry/planar | `freerouting/src/main/java/app/freerouting/geometry/planar/` | 34 | ✅ | exact geometry | 3 |
| rules | `freerouting/src/main/java/app/freerouting/rules/` | 10 | ✅ | clearance + classes | 4 |
| drc | `freerouting/src/main/java/app/freerouting/drc/` | 7 | ✅ | internal DRC oracle | 6 |
| designforms/specctra | `freerouting/src/main/java/app/freerouting/designforms/specctra/` | 40 | ✅ | DSN/SES IO | 2 |
| datastructures | `freerouting/src/main/java/app/freerouting/datastructures/` | 14 | ✅ | needed by geometry/board | 2–5 |
| core | `freerouting/src/main/java/app/freerouting/core/` | 35 | ✅* | padstacks + scoring + job state | 2,6,9 |
| interactive | `freerouting/src/main/java/app/freerouting/interactive/` | 43 | ✅* | headless board manager + make-space logic | 2,10 |
| settings | `freerouting/src/main/java/app/freerouting/settings/` | 13 | ✅* | router settings parity | 0,9 |
| management | `freerouting/src/main/java/app/freerouting/management/` | 20 | optional | only if needed for tests | 0/9 |
| logger | `freerouting/src/main/java/app/freerouting/logger/` | 4 | optional | only if needed for tests | 0 |
| gui | `freerouting/src/main/java/app/freerouting/gui/` | 71 | ❌ | UI only | n/a |
| api | `freerouting/src/main/java/app/freerouting/api/` | 14 | ❌ | UI/service layer | n/a |
| boardgraphics | `freerouting/src/main/java/app/freerouting/boardgraphics/` | 8 | ❌ | UI rendering | n/a |

`✅*` means “subset only, but treat the subset as manifest-tracked”. Start with the dependency closure required by the in-scope packages and the JUnit tests in Appendix B.
