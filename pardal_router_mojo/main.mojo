from collections import List
import sys

from python import Python, PythonObject

from pardal_router_mojo import route_problem
from pardal_router_mojo.dsn_dump import dsn_dump, dsn_ir
from pardal_router_mojo.fr.board.shape_search_tree_box import ShapeSearchTreeBox
from pardal_router_mojo.fr.board.search_tree_object import SearchTreeObject
from pardal_router_mojo.fr.board.layer import Layer
from pardal_router_mojo.fr.board.layer_structure import LayerStructure
from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint
from pardal_router_mojo.fr.rules.clearance_matrix import ClearanceMatrix
from pardal_router_mojo.fr.geometry.planar.tile_shape import TileShapeBox
from pardal_router_mojo.fr.autoroute.complete_free_space_expansion_room import (
    CompleteFreeSpaceExpansionRoomBox,
)
from pardal_router_mojo.fr.autoroute.expansion_door import ExpansionDoorBox
from pardal_router_mojo.fr.autoroute.maze_search_algo import find_room_path, find_room_door_path
from pardal_router_mojo.fr.autoroute.room_graph import RoomGraph
from pardal_router_mojo.fr.autoroute.room_graph_build import build_doors_for_all_overlaps
from pardal_router_mojo.fr.autoroute.grid_room_graph import build_rooms_from_grid
from pardal_router_mojo.fr.autoroute.grid_room_graph import build_rooms_from_grid_with_keepouts
from pardal_router_mojo.fr.board.routing_board import routing_board_from_dsn_path
from pardal_router_mojo.grid import Grid
from pardal_router_mojo.cli_astar import astar_direct
from pardal_router_mojo.router import _prepend_ko_unstick_candidates
from pardal_router_mojo.router import RouteConfig
from pardal_router_mojo.astar import idx_to_coords
from pardal_router_mojo.dsn_problem import dsn_problem_from_path


fn _main_impl() raises:
    var argv = List[String]()
    for a in sys.argv():
        argv.append(String(a))

    if len(argv) >= 2 and argv[1] == "dsn-dump":
        if len(argv) < 4:
            print("Usage: pardal-router-mojo dsn-dump <in.dsn> <out.json>")
            return
        dsn_dump(argv[2], argv[3])
        return
    if len(argv) >= 2 and argv[1] == "dsn-ir":
        if len(argv) < 4:
            print("Usage: pardal-router-mojo dsn-ir <in.dsn> <out.json>")
            return
        dsn_ir(argv[2], argv[3])
        return
    if len(argv) >= 2 and argv[1] == "route-problem":
        if len(argv) < 4:
            print("Usage: pardal-router-mojo route-problem <in.problem.json|in.dsn> <out.routes.json> [cfg.json]")
            return
        var cfg = String("")
        if len(argv) >= 5:
            cfg = argv[4]
        route_problem(argv[2], argv[3], cfg)
        return
    if len(argv) >= 2 and argv[1] == "dsn-problem":
        if len(argv) < 4:
            print("Usage: pardal-router-mojo dsn-problem <in.dsn> <out.problem.json>")
            return
        var prob = dsn_problem_from_path(argv[2], resolution_mm_override=Float64(0.0), keepout_inflate_mm_override=Float64(0.0), net_limit=0)
        var json = Python.import_module("json")
        var txt = json.dumps(prob)
        var pathlib = Python.import_module("pathlib")
        _ = pathlib.Path(PythonObject(argv[3])).write_text(txt)
        return
    if len(argv) >= 2 and argv[1] == "fr-smoke":
        # Minimal internal smoke tests for the FreeRouting parity ports.
        # Keep this fast and deterministic so it can be invoked from Python tests.
        # Basic overlap smoke.
        var tree = ShapeSearchTreeBox()
        var a = SearchTreeObject(
            IntBox(IntPoint(0, 0), IntPoint(10, 10)),
            0,
            1,
            0,
            True,
            True,
            False,
        )
        _ = tree.insert_object(a)
        var hits = tree.overlapping_tree_entries(IntBox(IntPoint(5, 5), IntPoint(6, 6)))
        if len(hits) != 1:
            raise Error("fr-smoke: expected 1 overlap, got " + String(len(hits)))
        var lh = tree.overlapping_tree_entries_on_layer(IntBox(IntPoint(5, 5), IntPoint(6, 6)), 0)
        if len(lh) != 1:
            raise Error("fr-smoke: expected 1 overlap on layer 0, got " + String(len(lh)))
        var nhits = tree.overlapping_tree_entries(IntBox(IntPoint(20, 20), IntPoint(21, 21)))
        if len(nhits) != 0:
            raise Error("fr-smoke: expected 0 overlaps, got " + String(len(nhits)))
        # Obstacle filter: same-net trace obstacle should not block.
        var oh = tree.overlapping_tree_entries_obstacles(IntBox(IntPoint(5, 5), IntPoint(6, 6)), 0, 1)
        if len(oh) != 0:
            raise Error("fr-smoke: expected 0 obstacles for own net, got " + String(len(oh)))
        var oh2 = tree.overlapping_tree_entries_obstacles(IntBox(IntPoint(5, 5), IntPoint(6, 6)), 0, 2)
        if len(oh2) != 1:
            raise Error("fr-smoke: expected 1 obstacle for other net, got " + String(len(oh2)))
        var oh3 = tree.overlapping_tree_entries_filtered(
            IntBox(IntPoint(5, 5), IntPoint(6, 6)),
            0,
            2,
            True,
            False,
        )
        if len(oh3) != 1:
            raise Error("fr-smoke: expected 1 filtered obstacle for other net, got " + String(len(oh3)))

        # Clearance compensation smoke: class(1,1)=20 on layer0 => compensation=10.
        var ls = LayerStructure([Layer("L0", True)])
        var cm = ClearanceMatrix(2, ls, ["c0", "c1"])
        cm.set_value(1, 1, 0, 20)
        var ctree = ShapeSearchTreeBox.with_clearance(cm, 1)
        var b = SearchTreeObject(
            IntBox(IntPoint(0, 0), IntPoint(10, 10)),
            0,
            2,
            1,
            False,
            True,
            False,
        )
        _ = ctree.insert_object(b)
        # Query shape outside original but inside compensated offset (+10).
        var chits = ctree.overlapping_tree_entries(IntBox(IntPoint(15, 0), IntPoint(16, 1)))
        if len(chits) != 1:
            raise Error("fr-smoke: expected 1 compensated overlap, got " + String(len(chits)))
        print("ok")
        return

    if len(argv) >= 2 and argv[1] == "fr-board-dsn":
        if len(argv) < 3:
            print("Usage: pardal-router-mojo fr-board-dsn <in.dsn>")
            return
        var rb = routing_board_from_dsn_path(argv[2])
        print(
            "layers",
            rb.layer_structure.layer_count(),
            "nets",
            rb.net_count(),
            "pins",
            rb.pin_count(),
            "wires",
            rb.wire_count(),
            "vias",
            rb.via_count(),
        )
        return

    if len(argv) >= 2 and argv[1] == "fr-maze-smoke":
        # Minimal traversal smoke for rooms/doors graph.
        var g = RoomGraph()
        _ = g.add_room(0, IntBox(IntPoint(0, 0), IntPoint(10, 10)))
        _ = g.add_room(0, IntBox(IntPoint(10, 0), IntPoint(20, 10)))
        _ = g.add_room(0, IntBox(IntPoint(20, 0), IntPoint(30, 10)))
        _ = g.add_door(0, 1, 1, IntBox(IntPoint(9, 0), IntPoint(11, 10)))
        _ = g.add_door(1, 2, 1, IntBox(IntPoint(19, 0), IntPoint(21, 10)))
        g.finalize_adjacency()

        var full = find_room_door_path(g, 0, 2)
        if len(full.room_ids) != 3 or full.room_ids[0] != 0 or full.room_ids[1] != 1 or full.room_ids[2] != 2:
            raise Error("fr-maze-smoke: unexpected room path len=" + String(len(full.room_ids)))
        if len(full.door_ids) != 2:
            raise Error("fr-maze-smoke: unexpected door path len=" + String(len(full.door_ids)))
        var path = find_room_path(g, 0, 2)
        if len(path) != 3:
            raise Error("fr-maze-smoke: find_room_path mismatch")
        print("ok")
        return

    if len(argv) >= 2 and argv[1] == "fr-door-smoke":
        var g = RoomGraph()
        _ = g.add_room(0, IntBox(IntPoint(0, 0), IntPoint(10, 10)))
        _ = g.add_room(0, IntBox(IntPoint(10, 0), IntPoint(20, 10)))
        var did = g.add_intersection_door(0, 1)
        if did < 0:
            raise Error("fr-door-smoke: expected door")
        g.finalize_adjacency()
        if g.door_dimension[did] != 1:
            raise Error("fr-door-smoke: expected dimension 1, got " + String(g.door_dimension[did]))
        var path = find_room_path(g, 0, 1)
        if len(path) != 2:
            raise Error("fr-door-smoke: expected path len 2")
        print("ok")
        return

    if len(argv) >= 2 and argv[1] == "fr-roomtree-smoke":
        var g = RoomGraph()
        _ = g.add_room(0, IntBox(IntPoint(0, 0), IntPoint(10, 10)))
        _ = g.add_room(0, IntBox(IntPoint(9, 0), IntPoint(19, 10)))
        _ = g.add_room(0, IntBox(IntPoint(18, 0), IntPoint(28, 10)))
        var doors = build_doors_for_all_overlaps(g)
        if doors != 2:
            raise Error("fr-roomtree-smoke: expected 2 doors, got " + String(doors))
        var path = find_room_path(g, 0, 2)
        if len(path) != 3:
            raise Error("fr-roomtree-smoke: expected path len 3, got " + String(len(path)))
        print("ok")
        return

    if len(argv) >= 2 and argv[1] == "fr-grid-rooms-smoke":
        # Build a small 1-layer grid with a vertical obstacle column, then ensure
        # the free space is split into left/right rooms with a path absent.
        var g0 = Grid(1, 6, 4)
        # Block x=3 entirely.
        for y in range(4):
            g0.base_set(g0.idx(0, 3, y), g0.blocked_value)
        var rg = build_rooms_from_grid(g0, UInt32(1))
        # Expect 2 rooms (left 0..3, right 4..6) each spanning full height.
        if rg.room_count() != 2:
            raise Error("fr-grid-rooms-smoke: expected 2 rooms, got " + String(rg.room_count()))
        var path = find_room_path(rg, 0, 1)
        if len(path) != 0:
            raise Error("fr-grid-rooms-smoke: expected no path between rooms")
        print("ok")
        return

    if len(argv) >= 2 and argv[1] == "fr-grid-rooms-keepout-smoke":
        # Like fr-grid-rooms-smoke, but ensure KO fields carve free space.
        var g0 = Grid(1, 6, 4)
        # Block x=3 entirely.
        for y in range(4):
            g0.base_set(g0.idx(0, 3, y), g0.blocked_value)
        # Add a KO stripe at x=1..2 on y=2 (simulating already-routed copper).
        for x in range(1, 3):
            var idx = g0.idx(0, x, 2)
            g0.stamp_ko_track_at(idx, UInt32(99), 1)
        var rg = build_rooms_from_grid_with_keepouts(g0, UInt32(1), False, True)
        # Expect at least 3 rooms now (left split by KO + right side).
        if rg.room_count() < 3:
            raise Error("fr-grid-rooms-keepout-smoke: expected >=3 rooms, got " + String(rg.room_count()))
        print("ok")
        return

    if len(argv) >= 2 and argv[1] == "astar-direct":
        if len(argv) < 3:
            print("Usage: pardal-router-mojo astar-direct <in.json>")
            return
        var rc = astar_direct(argv[2])
        sys.exit(rc)
        return

    if len(argv) >= 2 and argv[1] == "ko-unstick-smoke":
        # Minimal smoke to ensure KO unstick candidate selection works.
        # Build a 1-layer grid, mark net A routed, and stamp KO from A around
        # net B's start cell; verify A is selected as a candidate for ripping.
        var g = Grid(1, 20, 20)
        var net_ids = List[UInt32]()
        net_ids.append(UInt32(10))  # A
        net_ids.append(UInt32(20))  # B (failed)
        var routed_state = List[Int]()
        routed_state.append(1)
        routed_state.append(0)
        var start_idxs = List[Int]()
        var goal_idxs = List[Int]()
        # B start at (10,10), goal at (15,15)
        start_idxs.append(0)
        goal_idxs.append(0)
        start_idxs.append(g.idx(0, 10, 10))
        goal_idxs.append(g.idx(0, 15, 15))
        # Stamp KO from net A around B start.
        var idx = g.idx(0, 10, 10)
        g.stamp_ko_track_at(idx, UInt32(10), 1)
        var candidates = List[Int]()
        var scores = List[Int]()
        var cfg = RouteConfig()
        cfg.ko_unstick_enable = True
        cfg.ko_unstick_radius_cells = 1
        cfg.ko_unstick_max_rips = 4
        _prepend_ko_unstick_candidates(
            candidates,
            scores,
            1,
            g,
            net_ids,
            start_idxs,
            goal_idxs,
            routed_state,
            20,
            20,
            cfg,
        )
        if len(candidates) == 0 or candidates[0] != 0:
            raise Error("ko-unstick-smoke: expected candidate 0, got " + String(len(candidates)))
        print("ok")
        return

    if len(argv) < 3:
        print("Usage: pardal-router-mojo <problem.json> <routes.json> [cfg.json]")
        print("       pardal-router-mojo dsn-dump <in.dsn> <out.json>")
        print("       pardal-router-mojo dsn-ir <in.dsn> <out.json>")
        print("       pardal-router-mojo fr-smoke")
        print("       pardal-router-mojo fr-maze-smoke")
        print("       pardal-router-mojo fr-door-smoke")
        print("       pardal-router-mojo fr-roomtree-smoke")
        print("       pardal-router-mojo fr-grid-rooms-smoke")
        print("       pardal-router-mojo fr-grid-rooms-keepout-smoke")
        print("       pardal-router-mojo astar-direct <in.json>")
        print("       pardal-router-mojo ko-unstick-smoke")
        return

    var problem = argv[1]
    var routes = argv[2]
    var cfg = argv[3] if len(argv) >= 4 else ""
    route_problem(problem, routes, cfg)


fn main() raises:
    try:
        _main_impl()
    except e:
        try:
            var tb = Python.import_module("traceback")
            _ = tb.print_exc()
        except _:
            pass
        raise e^
