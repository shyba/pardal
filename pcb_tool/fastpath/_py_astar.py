import heapq


def _heuristic(x, y, gx, gy, diagonal):
    dx = abs(gx - x)
    dy = abs(gy - y)
    return max(dx, dy) if diagonal else dx + dy


def _astar_path(cost, sx, sy, gx, gy, diagonal):
    height = len(cost)
    width = len(cost[0]) if height else 0
    if width == 0:
        return []
    if sx < 0 or sy < 0 or gx < 0 or gy < 0:
        return []
    if sx >= width or gx >= width or sy >= height or gy >= height:
        return []
    if cost[sy][sx] <= 0 or cost[gy][gx] <= 0:
        return []

    total = width * height
    gscore = [1e300] * total
    came_from = [-1] * total
    open_heap = []

    start_idx = sy * width + sx
    goal_idx = gy * width + gx
    gscore[start_idx] = 0.0
    heapq.heappush(open_heap, (0.0, 0.0, sx, sy))

    while open_heap:
        _, g, x, y = heapq.heappop(open_heap)
        idx = y * width + x
        if g > gscore[idx]:
            continue
        if idx == goal_idx:
            break

        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx = x + dx
            ny = y + dy
            if 0 <= nx < width and 0 <= ny < height and cost[ny][nx] > 0:
                nidx = ny * width + nx
                ng = g + cost[ny][nx]
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = idx
                    f = ng + _heuristic(nx, ny, gx, gy, diagonal)
                    heapq.heappush(open_heap, (f, ng, nx, ny))

        if diagonal:
            for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                nx = x + dx
                ny = y + dy
                if 0 <= nx < width and 0 <= ny < height and cost[ny][nx] > 0:
                    nidx = ny * width + nx
                    ng = g + cost[ny][nx] * 1.41421356237
                    if ng < gscore[nidx]:
                        gscore[nidx] = ng
                        came_from[nidx] = idx
                        f = ng + _heuristic(nx, ny, gx, gy, diagonal)
                        heapq.heappush(open_heap, (f, ng, nx, ny))

    if gscore[goal_idx] >= 1e300:
        return []

    path = []
    idx = goal_idx
    while idx != -1:
        y = idx // width
        x = idx - y * width
        path.append((x, y))
        if idx == start_idx:
            break
        idx = came_from[idx]

    path.reverse()
    return path


def _astar_path_3d(cost, sx, sy, sz, gx, gy, gz, diagonal, via_cost):
    layers = len(cost)
    height = len(cost[0]) if layers else 0
    width = len(cost[0][0]) if height else 0
    if width == 0:
        return []
    if sx < 0 or sy < 0 or sz < 0 or gx < 0 or gy < 0 or gz < 0:
        return []
    if (
        sx >= width
        or gx >= width
        or sy >= height
        or gy >= height
        or sz >= layers
        or gz >= layers
    ):
        return []
    if cost[sz][sy][sx] <= 0 or cost[gz][gy][gx] <= 0:
        return []

    def idx(x, y, z):
        return (z * height + y) * width + x

    total = width * height * layers
    gscore = [1e300] * total
    came_from = [-1] * total
    open_heap = []

    start_idx = idx(sx, sy, sz)
    goal_idx = idx(gx, gy, gz)
    gscore[start_idx] = 0.0
    open_heap.append((0.0, 0.0, sx, sy, sz))

    while open_heap:
        _, g, x, y, z = heapq.heappop(open_heap)
        cur_idx = idx(x, y, z)
        if g > gscore[cur_idx]:
            continue
        if cur_idx == goal_idx:
            break

        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx = x + dx
            ny = y + dy
            if 0 <= nx < width and 0 <= ny < height and cost[z][ny][nx] > 0:
                nidx = idx(nx, ny, z)
                ng = g + cost[z][ny][nx]
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = cur_idx
                    h = _heuristic(nx, ny, gx, gy, diagonal) + via_cost * abs(z - gz)
                    heapq.heappush(open_heap, (ng + h, ng, nx, ny, z))

        if diagonal:
            for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                nx = x + dx
                ny = y + dy
                if 0 <= nx < width and 0 <= ny < height and cost[z][ny][nx] > 0:
                    nidx = idx(nx, ny, z)
                    ng = g + cost[z][ny][nx] * 1.41421356237
                    if ng < gscore[nidx]:
                        gscore[nidx] = ng
                        came_from[nidx] = cur_idx
                        h = _heuristic(nx, ny, gx, gy, diagonal) + via_cost * abs(
                            z - gz
                        )
                        heapq.heappush(open_heap, (ng + h, ng, nx, ny, z))

        for nz in (z - 1, z + 1):
            if 0 <= nz < layers and cost[nz][y][x] > 0:
                nidx = idx(x, y, nz)
                ng = g + via_cost + cost[nz][y][x]
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = cur_idx
                    h = _heuristic(x, y, gx, gy, diagonal) + via_cost * abs(nz - gz)
                    heapq.heappush(open_heap, (ng + h, ng, x, y, nz))

    if gscore[goal_idx] >= 1e300:
        return []

    path = []
    cur = goal_idx
    while cur != -1:
        z = cur // (width * height)
        rem = cur - z * width * height
        y = rem // width
        x = rem - y * width
        path.append((x, y, z))
        if cur == start_idx:
            break
        cur = came_from[cur]

    path.reverse()
    return path
