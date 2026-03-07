"""Port scaffold for `app.freerouting.autoroute.MazeSearchAlgo` (minimal).

FreeRouting's maze router expands through a graph of "rooms" connected by
"doors", maintaining per-door section costs + backpointers.

Full parity requires the complete board model + search trees; for now we
provide a tiny, deterministic subset:
- room-to-room BFS through ExpansionDoorBox connections

This is used only as a correctness anchor for the incremental port: higher-level
code can depend on "rooms/doors form a traversable graph" without pulling in the
full router yet.
"""

from collections import List

from .room_graph import RoomGraph


@fieldwise_init
struct MazePath(Movable):
    var room_ids: List[Int]
    var door_ids: List[Int]


fn find_room_door_path(graph: RoomGraph, start_room_id: Int, goal_room_id: Int) -> MazePath:
    # Returns a room/door path with inclusive room endpoints and matching door sequence.
    # Empty lists mean "not found".
    var out = MazePath(List[Int](), List[Int]())
    var n = graph.room_count()
    if start_room_id < 0 or goal_room_id < 0 or start_room_id >= n or goal_room_id >= n:
        return out^
    if start_room_id == goal_room_id:
        out.room_ids.append(start_room_id)
        return out^

    var prev_room = List[Int]()
    var prev_door = List[Int]()
    var visited = List[Bool]()
    for _ in range(n):
        prev_room.append(-1)
        prev_door.append(-1)
        visited.append(False)

    var queue = List[Int]()
    queue.append(start_room_id)
    visited[start_room_id] = True
    var head = 0

    while head < len(queue):
        var rid = queue[head]
        head += 1
        for i in range(graph.room_doors_len(rid)):
            var did = graph.room_door_id_at(rid, i)
            if did < 0 or did >= graph.door_count():
                continue
            var other = graph.other_room_id(did, rid)
            if other < 0 or other >= n:
                continue
            if visited[other]:
                continue
            visited[other] = True
            prev_room[other] = rid
            prev_door[other] = did
            if other == goal_room_id:
                head = len(queue)
                break
            queue.append(other)

    if prev_room[goal_room_id] < 0:
        return out^

    # Reconstruct room list.
    var rev_rooms = List[Int]()
    var rev_doors = List[Int]()
    var cur = goal_room_id
    while cur >= 0:
        rev_rooms.append(cur)
        if cur == start_room_id:
            break
        rev_doors.append(prev_door[cur])
        cur = prev_room[cur]

    # reverse into forward order
    for i in range(len(rev_rooms) - 1, -1, -1):
        out.room_ids.append(rev_rooms[i])
    for i in range(len(rev_doors) - 1, -1, -1):
        out.door_ids.append(rev_doors[i])
    return out^


fn find_room_path(graph: RoomGraph, start_room_id: Int, goal_room_id: Int) -> List[Int]:
    # Backwards compatible helper for earlier ports/tests.
    var n = graph.room_count()
    if start_room_id < 0 or goal_room_id < 0 or start_room_id >= n or goal_room_id >= n:
        return List[Int]()^
    if start_room_id == goal_room_id:
        var out = List[Int]()
        out.append(start_room_id)
        return out^

    var prev = List[Int]()
    var visited = List[Bool]()
    for _ in range(n):
        prev.append(-1)
        visited.append(False)

    var queue = List[Int]()
    queue.append(start_room_id)
    visited[start_room_id] = True
    var head = 0

    while head < len(queue):
        var rid = queue[head]
        head += 1
        for i in range(graph.room_doors_len(rid)):
            var did = graph.room_door_id_at(rid, i)
            if did < 0 or did >= graph.door_count():
                continue
            var other = graph.other_room_id(did, rid)
            if other < 0 or other >= n:
                continue
            if visited[other]:
                continue
            visited[other] = True
            prev[other] = rid
            if other == goal_room_id:
                head = len(queue)
                break
            queue.append(other)

    if prev[goal_room_id] < 0:
        return List[Int]()^

    var rev = List[Int]()
    var cur = goal_room_id
    while cur >= 0:
        rev.append(cur)
        if cur == start_room_id:
            break
        cur = prev[cur]

    var out = List[Int]()
    for i in range(len(rev) - 1, -1, -1):
        out.append(rev[i])
    return out^


fn find_room_door_path_weighted(
    graph: RoomGraph,
    start_room_id: Int,
    goal_room_id: Int,
    door_costs: List[Int],
) -> MazePath:
    # Dijkstra on rooms with per-door costs. Returns empty path on failure.
    var out = MazePath(List[Int](), List[Int]())
    var n = graph.room_count()
    if start_room_id < 0 or goal_room_id < 0 or start_room_id >= n or goal_room_id >= n:
        return out^
    if len(door_costs) != graph.door_count():
        return out^
    if start_room_id == goal_room_id:
        out.room_ids.append(start_room_id)
        return out^

    var inf = 1_000_000_000
    var dist = List[Int]()
    var prev_room = List[Int]()
    var prev_door = List[Int]()
    var visited = List[Bool]()
    for _ in range(n):
        dist.append(inf)
        prev_room.append(-1)
        prev_door.append(-1)
        visited.append(False)
    dist[start_room_id] = 0

    var iter = 0
    while iter < n:
        var best = -1
        var bestd = inf
        var i = 0
        while i < n:
            if (not visited[i]) and dist[i] < bestd:
                bestd = dist[i]
                best = i
            i += 1
        if best < 0:
            break
        if best == goal_room_id:
            break
        visited[best] = True

        var di = 0
        while di < graph.room_doors_len(best):
            var did = graph.room_door_id_at(best, di)
            if did < 0 or did >= graph.door_count():
                di += 1
                continue
            var dc = door_costs[did]
            if dc >= inf:
                di += 1
                continue
            var other = graph.other_room_id(did, best)
            if other < 0 or other >= n:
                di += 1
                continue
            var nd = bestd + dc
            if nd < dist[other]:
                dist[other] = nd
                prev_room[other] = best
                prev_door[other] = did
            di += 1
        iter += 1

    if prev_room[goal_room_id] < 0:
        return out^

    var rev_rooms = List[Int]()
    var rev_doors = List[Int]()
    var cur = goal_room_id
    while cur >= 0:
        rev_rooms.append(cur)
        if cur == start_room_id:
            break
        rev_doors.append(prev_door[cur])
        cur = prev_room[cur]

    var i2 = len(rev_rooms) - 1
    while i2 >= 0:
        out.room_ids.append(rev_rooms[i2])
        i2 -= 1
    var j2 = len(rev_doors) - 1
    while j2 >= 0:
        out.door_ids.append(rev_doors[j2])
        j2 -= 1
    return out^
