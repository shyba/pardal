# FreeRouting → Rust Parity Matrix (Class-Level)

This is a class-level parity checklist mapping FreeRouting’s Java implementation to the intended Rust equivalents in `pardal_router_core`.

Status legend:
- `done`: implemented + has tests
- `partial`: exists but incomplete / not wired through
- `missing`: not implemented

## Autoroute (batch router)

| FreeRouting (Java) | Responsibilities | Rust target | Status |
|---|---|---|---|
| `autoroute/BatchAutorouter.java` | pass loop, item ordering, stop criteria, best-of-N restore | `autoroute/batch.rs` | missing |
| `autoroute/BatchAutorouterThread.java` | per-thread pass attempt | `autoroute/batch_mt.rs` | missing |
| `autoroute/BoardUpdateStrategy.java` | routing strategy enum (greedy/global/hybrid) | `autoroute/settings.rs` | missing |
| `autoroute/AutorouteEngine.java` | per-connection route entry; owns autoroute search tree + drill pages | `autoroute/engine.rs` | missing |
| `autoroute/AutorouteControl.java` | per-net derived routing params (widths, clearances, via rules/costs, layer prefs, shove limits) | `rules/autoroute_control.rs` (or under `rules/`) | missing |
| `autoroute/Connection.java` | “connect components until one remains” model | `autoroute/connection.rs` | missing |
| `autoroute/ItemAutorouteInfo.java` | per-item autoroute cache (start/dest flags, obstacle rooms, precalculated connections) | `autoroute/item_cache.rs` | missing |
| `autoroute/ItemRouteResult.java` | local improvement scoring (vias/length/incomplete) | `autoroute/metrics.rs` | missing |
| `autoroute/DestinationDistance.java` | admissible lower bound heuristic | `autoroute/heuristics.rs` | missing |
| `autoroute/MazeSearchAlgo.java` | free-space expansion routing | `autoroute/maze.rs` | missing |
| `autoroute/MazeListElement.java` | PQ node state for maze search | `autoroute/maze.rs` | missing |
| `autoroute/MazeSearchElement.java` | per-door section state + backtrack pointers | `autoroute/maze.rs` | missing |
| `autoroute/ExpandableObject.java` | door abstraction with “other_room” + section count | `autoroute/maze_graph.rs` | missing |
| `autoroute/ExpansionDoor.java` | adjacency between rooms (door sections) | `autoroute/maze_graph.rs` | missing |
| `autoroute/TargetItemExpansionDoor.java` | doors attached to connectable items | `autoroute/maze_graph.rs` | missing |
| `autoroute/ExpansionRoom.java` | room interface | `autoroute/rooms.rs` | missing |
| `autoroute/FreeSpaceExpansionRoom.java` | room representing free space | `autoroute/rooms.rs` | missing |
| `autoroute/IncompleteFreeSpaceExpansionRoom.java` | temporary room during expansion | `autoroute/rooms.rs` | missing |
| `autoroute/CompleteFreeSpaceExpansionRoom.java` | cached room in search tree; invalidated by board changes | `autoroute/rooms.rs` | missing |
| `autoroute/ObstacleExpansionRoom.java` | obstacle room for ripup bookkeeping | `autoroute/rooms.rs` | missing |
| `autoroute/ExpansionDrill.java` | via transition door across layers | `autoroute/drills.rs` | missing |
| `autoroute/DrillPage.java` / `DrillPageArray.java` | paging optimization for drills | `autoroute/drills.rs` | missing |
| `autoroute/LocateFoundConnectionAlgo*.java` | convert backtrack door chain into 45/90 (or any-angle) polylines | `autoroute/locate.rs` | missing |
| `autoroute/InsertFoundConnectionAlgo.java` | insert located traces/vias; uses forced insertion + shove | `autoroute/insert.rs` | missing |
| `autoroute/MazeShoveTraceAlgo.java` | shove helpers for maze routing | `autoroute/shove.rs` | missing |
| `autoroute/BoardHistory.java` / `BoardHistoryEntry.java` | keep best boards by score, restore best | `autoroute/history.rs` | missing |
| `autoroute/BatchFanout.java` | escape/fanout primitives | `autoroute/fanout.rs` | missing |
| `autoroute/BatchOptimizer*.java` | pull-tight, via optimize, cleanup | `autoroute/optimize.rs` | missing |
| `autoroute/NamedAlgorithm*.java` + `autoroute/events/*` | task lifecycle + progress events | `tools/` (optional; not required for parity) | missing |

## Rules (constraints model)

| FreeRouting (Java) | Responsibilities | Rust target | Status |
|---|---|---|---|
| `rules/BoardRules.java` | canonical rule source (width/clearance/via, angle restriction) | `rules/` | missing |
| `rules/ClearanceMatrix.java` | clearance matrix + compensation values | `rules/clearance_matrix.rs` | missing |
| `rules/NetClasses.java` / `NetClass.java` | netclass model, active layers, via_rule, clearance_class | `rules/netclasses.rs` | missing |
| `rules/ViaRule.java` | via candidates per netclass | `rules/via_rules.rs` | missing |
| `rules/ViaInfo.java` / `ViaInfos.java` | via geometry, clearance class, attach_smd | `rules/via_rules.rs` | missing |
| `rules/Net.java` / `Nets.java` | net registry and class assignment | `rules/netclasses.rs` | missing |
| DSN parsing (`dsn/net_rules.rs`, `dsn/autoroute_settings.rs`) | extract DSN rules/settings | `rules/` extraction layer | partial |
| `rules::RulesDb` (current) | thin wrapper over DSN rules (width/clearance/via padstack) | `rules/rules_db.rs` | partial |

## Board database + geometry

| FreeRouting (Java) | Responsibilities | Rust target | Status |
|---|---|---|---|
| `board/RoutingBoard.java` | authoritative board model; route/insert/remove/normalize; DRC queries | `board/board_db.rs` | missing |
| `board/SearchTreeManager.java` | manages default + autoroute trees | `board/search_trees.rs` | missing |
| `board/ShapeSearchTree*.java` | spatial index for collision queries | `board/search_trees.rs` | missing |
| `board/ShoveTraceAlgo.java` | shove implementation | `autoroute/shove.rs` | missing |
| `board/PullTightAlgo*.java` | pull-tight optimizers | `autoroute/optimize.rs` | missing |
| `board/ForcedViaAlgo.java` / `board/ForcedPadAlgo.java` | forced insertion primitives (shove surface) | `autoroute/forced_insert.rs` | missing |
| `board/OptViaAlgo.java` | via optimization primitive | `autoroute/optimize.rs` | missing |
| `datastructures/UndoableObjects.java` | snapshot/undo for failed attempts | `board/undo.rs` (or transactional BoardDb) | missing |
| `datastructures/MinAreaTree.java` + `ShapeTree.java` | geometric indexing foundation | `board/search_trees.rs` (implementation detail) | missing |
| `geometry/planar/*` | robust planar geometry primitives | `geom_nm.rs` + new `geom_planar.rs` | partial |
| `drc/*` (in FreeRouting) | rule-consistent DRC | Rust nm DRC (`drc_nm.rs`, etc.) | partial (comparison harness exists) |

## Current Rust router core reality (for context)

| Area | Rust status |
|---|---|
| DSN parsing | strong (model, wiring, net rules, autoroute_settings) |
| DRC | strong (nm-level DRC + indices) |
| Routing | grid-based A*; minimal ripup loop exists (supports multi-request nets + transactional commits); no shove; pads are modeled via `RoutingIr.pad_owner`; approximates rules via brush dilation |
| Oracle harness | done (Dockerized FreeRouting runner + smoke report + JSON normalization) |
