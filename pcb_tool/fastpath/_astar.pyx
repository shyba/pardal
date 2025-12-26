# cython: language_level=3

import heapq
from libc.stdlib cimport malloc, realloc, free


cdef double _heuristic(int x, int y, int gx, int gy, bint diagonal):
    cdef int dx = gx - x
    cdef int dy = gy - y
    if dx < 0:
        dx = -dx
    if dy < 0:
        dy = -dy
    if diagonal:
        return dx if dx >= dy else dy
    return dx + dy


cdef struct _Heap3D:
    int size
    int cap
    double* f
    double* g
    int* x
    int* y
    int* z


cdef int _heap3d_init(_Heap3D* h, int cap):
    h.size = 0
    h.cap = cap
    h.f = <double*>malloc(cap * sizeof(double))
    h.g = <double*>malloc(cap * sizeof(double))
    h.x = <int*>malloc(cap * sizeof(int))
    h.y = <int*>malloc(cap * sizeof(int))
    h.z = <int*>malloc(cap * sizeof(int))
    if h.f == NULL or h.g == NULL or h.x == NULL or h.y == NULL or h.z == NULL:
        return -1
    return 0


cdef void _heap3d_free(_Heap3D* h):
    if h.f != NULL:
        free(h.f)
        h.f = NULL
    if h.g != NULL:
        free(h.g)
        h.g = NULL
    if h.x != NULL:
        free(h.x)
        h.x = NULL
    if h.y != NULL:
        free(h.y)
        h.y = NULL
    if h.z != NULL:
        free(h.z)
        h.z = NULL
    h.size = 0
    h.cap = 0


cdef int _heap3d_grow(_Heap3D* h):
    cdef int new_cap = h.cap * 2
    cdef double* nf = <double*>realloc(h.f, new_cap * sizeof(double))
    cdef double* ng = <double*>realloc(h.g, new_cap * sizeof(double))
    cdef int* nx = <int*>realloc(h.x, new_cap * sizeof(int))
    cdef int* ny = <int*>realloc(h.y, new_cap * sizeof(int))
    cdef int* nz = <int*>realloc(h.z, new_cap * sizeof(int))
    if nf == NULL or ng == NULL or nx == NULL or ny == NULL or nz == NULL:
        return -1
    h.f = nf
    h.g = ng
    h.x = nx
    h.y = ny
    h.z = nz
    h.cap = new_cap
    return 0


cdef int _heap3d_push(_Heap3D* h, double f, double g, int x, int y, int z):
    cdef int j, parent
    if h.size >= h.cap:
        if _heap3d_grow(h) != 0:
            return -1

    j = h.size
    h.size += 1
    while j > 0:
        parent = (j - 1) // 2
        if h.f[parent] <= f:
            break
        h.f[j] = h.f[parent]
        h.g[j] = h.g[parent]
        h.x[j] = h.x[parent]
        h.y[j] = h.y[parent]
        h.z[j] = h.z[parent]
        j = parent

    h.f[j] = f
    h.g[j] = g
    h.x[j] = x
    h.y[j] = y
    h.z[j] = z
    return 0


cdef int _heap3d_pop(_Heap3D* h, double* out_f, double* out_g, int* out_x, int* out_y, int* out_z):
    cdef int j, left, right, smallest
    cdef double f_last, g_last
    cdef int x_last, y_last, z_last

    if h.size == 0:
        return 0

    out_f[0] = h.f[0]
    out_g[0] = h.g[0]
    out_x[0] = h.x[0]
    out_y[0] = h.y[0]
    out_z[0] = h.z[0]

    h.size -= 1
    if h.size == 0:
        return 1

    f_last = h.f[h.size]
    g_last = h.g[h.size]
    x_last = h.x[h.size]
    y_last = h.y[h.size]
    z_last = h.z[h.size]

    j = 0
    while True:
        left = 2 * j + 1
        if left >= h.size:
            break
        right = left + 1
        if right < h.size and h.f[right] < h.f[left]:
            smallest = right
        else:
            smallest = left
        if h.f[smallest] >= f_last:
            break
        h.f[j] = h.f[smallest]
        h.g[j] = h.g[smallest]
        h.x[j] = h.x[smallest]
        h.y[j] = h.y[smallest]
        h.z[j] = h.z[smallest]
        j = smallest

    h.f[j] = f_last
    h.g[j] = g_last
    h.x[j] = x_last
    h.y[j] = y_last
    h.z[j] = z_last
    return 1


def _astar_path(const double[:, :] cost, int sx, int sy, int gx, int gy, bint diagonal):
    """Cython-backed A* on a 2D cost grid.

    cost: 2D grid of node costs (0 blocks).
    start/goal: grid coordinates (x, y).
    """
    cdef int height = cost.shape[0]
    cdef int width = cost.shape[1]
    if sx < 0 or sy < 0 or gx < 0 or gy < 0:
        return []
    if sx >= width or gx >= width or sy >= height or gy >= height:
        return []
    if cost[sy, sx] <= 0 or cost[gy, gx] <= 0:
        return []

    cdef int total = width * height
    cdef list gscore = [1e300] * total
    cdef list came_from = [-1] * total
    cdef list open_heap = []

    cdef int start_idx = sy * width + sx
    cdef int goal_idx = gy * width + gx

    gscore[start_idx] = 0.0
    heapq.heappush(open_heap, (0.0, 0.0, sx, sy))

    cdef int x, y, nx, ny, idx, nidx
    cdef double g, ng, f
    cdef double step_cost

    while open_heap:
        f, g, x, y = heapq.heappop(open_heap)
        idx = y * width + x
        if g > gscore[idx]:
            continue
        if idx == goal_idx:
            break

        # Orthogonal neighbors
        nx = x + 1
        ny = y
        if nx < width and cost[ny, nx] > 0:
            nidx = ny * width + nx
            step_cost = cost[ny, nx]
            ng = g + step_cost
            if ng < gscore[nidx]:
                gscore[nidx] = ng
                came_from[nidx] = idx
                heapq.heappush(open_heap, (ng + _heuristic(nx, ny, gx, gy, diagonal), ng, nx, ny))

        nx = x - 1
        if nx >= 0 and cost[ny, nx] > 0:
            nidx = ny * width + nx
            step_cost = cost[ny, nx]
            ng = g + step_cost
            if ng < gscore[nidx]:
                gscore[nidx] = ng
                came_from[nidx] = idx
                heapq.heappush(open_heap, (ng + _heuristic(nx, ny, gx, gy, diagonal), ng, nx, ny))

        nx = x
        ny = y + 1
        if ny < height and cost[ny, nx] > 0:
            nidx = ny * width + nx
            step_cost = cost[ny, nx]
            ng = g + step_cost
            if ng < gscore[nidx]:
                gscore[nidx] = ng
                came_from[nidx] = idx
                heapq.heappush(open_heap, (ng + _heuristic(nx, ny, gx, gy, diagonal), ng, nx, ny))

        ny = y - 1
        if ny >= 0 and cost[ny, nx] > 0:
            nidx = ny * width + nx
            step_cost = cost[ny, nx]
            ng = g + step_cost
            if ng < gscore[nidx]:
                gscore[nidx] = ng
                came_from[nidx] = idx
                heapq.heappush(open_heap, (ng + _heuristic(nx, ny, gx, gy, diagonal), ng, nx, ny))

        if diagonal:
            nx = x + 1
            ny = y + 1
            if (
                nx < width and ny < height
                and cost[ny, nx] > 0
                and cost[y, nx] > 0
                and cost[ny, x] > 0
            ):
                nidx = ny * width + nx
                step_cost = cost[ny, nx] * 1.41421356237
                ng = g + step_cost
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = idx
                    heapq.heappush(open_heap, (ng + _heuristic(nx, ny, gx, gy, diagonal), ng, nx, ny))

            nx = x - 1
            ny = y + 1
            if (
                nx >= 0 and ny < height
                and cost[ny, nx] > 0
                and cost[y, nx] > 0
                and cost[ny, x] > 0
            ):
                nidx = ny * width + nx
                step_cost = cost[ny, nx] * 1.41421356237
                ng = g + step_cost
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = idx
                    heapq.heappush(open_heap, (ng + _heuristic(nx, ny, gx, gy, diagonal), ng, nx, ny))

            nx = x + 1
            ny = y - 1
            if (
                nx < width and ny >= 0
                and cost[ny, nx] > 0
                and cost[y, nx] > 0
                and cost[ny, x] > 0
            ):
                nidx = ny * width + nx
                step_cost = cost[ny, nx] * 1.41421356237
                ng = g + step_cost
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = idx
                    heapq.heappush(open_heap, (ng + _heuristic(nx, ny, gx, gy, diagonal), ng, nx, ny))

            nx = x - 1
            ny = y - 1
            if (
                nx >= 0 and ny >= 0
                and cost[ny, nx] > 0
                and cost[y, nx] > 0
                and cost[ny, x] > 0
            ):
                nidx = ny * width + nx
                step_cost = cost[ny, nx] * 1.41421356237
                ng = g + step_cost
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = idx
                    heapq.heappush(open_heap, (ng + _heuristic(nx, ny, gx, gy, diagonal), ng, nx, ny))

    if gscore[goal_idx] >= 1e300:
        return []

    # Reconstruct path
    cdef list path = []
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


def _astar_path_3d(
    const double[:, :, :] cost,
    int sx,
    int sy,
    int sz,
    int gx,
    int gy,
    int gz,
    bint diagonal,
    double via_cost,
):
    """Cython-backed A* on a 3D cost grid.

    cost: 3D grid of node costs (0 blocks), indexed as (layer, y, x).
    start/goal: grid coordinates (x, y, layer_index).
    """
    cdef int layers = cost.shape[0]
    cdef int height = cost.shape[1]
    cdef int width = cost.shape[2]

    if width <= 0 or height <= 0 or layers <= 0:
        return []
    if sx < 0 or sy < 0 or sz < 0 or gx < 0 or gy < 0 or gz < 0:
        return []
    if sx >= width or gx >= width or sy >= height or gy >= height or sz >= layers or gz >= layers:
        return []
    if cost[sz, sy, sx] <= 0 or cost[gz, gy, gx] <= 0:
        return []

    cdef int plane = width * height
    cdef int total = plane * layers

    cdef double* gscore = <double*>malloc(total * sizeof(double))
    cdef int* came_from = <int*>malloc(total * sizeof(int))
    cdef _Heap3D heap
    heap.f = NULL
    heap.g = NULL
    heap.x = NULL
    heap.y = NULL
    heap.z = NULL

    if gscore == NULL or came_from == NULL:
        if gscore != NULL:
            free(gscore)
        if came_from != NULL:
            free(came_from)
        raise MemoryError()

    cdef int i
    for i in range(total):
        gscore[i] = 1e300
        came_from[i] = -1

    if _heap3d_init(&heap, 4096) != 0:
        free(gscore)
        free(came_from)
        _heap3d_free(&heap)
        raise MemoryError()

    cdef int start_idx = (sz * height + sy) * width + sx
    cdef int goal_idx = (gz * height + gy) * width + gx

    gscore[start_idx] = 0.0
    if _heap3d_push(&heap, 0.0, 0.0, sx, sy, sz) != 0:
        free(gscore)
        free(came_from)
        _heap3d_free(&heap)
        raise MemoryError()

    cdef int x, y, z, nx, ny, nz, idx, nidx, rem
    cdef double g, ng, step_cost, h
    cdef double pop_f, pop_g
    cdef int pop_x, pop_y, pop_z

    while _heap3d_pop(&heap, &pop_f, &pop_g, &pop_x, &pop_y, &pop_z):
        g = pop_g
        x = pop_x
        y = pop_y
        z = pop_z
        idx = (z * height + y) * width + x
        if g > gscore[idx]:
            continue
        if idx == goal_idx:
            break

        # Orthogonal neighbors on same layer
        nx = x + 1
        ny = y
        if nx < width and cost[z, ny, nx] > 0:
            nidx = (z * height + ny) * width + nx
            step_cost = cost[z, ny, nx]
            ng = g + step_cost
            if ng < gscore[nidx]:
                gscore[nidx] = ng
                came_from[nidx] = idx
                h = _heuristic(nx, ny, gx, gy, diagonal)
                if z != gz:
                    h += via_cost
                if _heap3d_push(&heap, ng + h, ng, nx, ny, z) != 0:
                    free(gscore)
                    free(came_from)
                    _heap3d_free(&heap)
                    raise MemoryError()

        nx = x - 1
        if nx >= 0 and cost[z, ny, nx] > 0:
            nidx = (z * height + ny) * width + nx
            step_cost = cost[z, ny, nx]
            ng = g + step_cost
            if ng < gscore[nidx]:
                gscore[nidx] = ng
                came_from[nidx] = idx
                h = _heuristic(nx, ny, gx, gy, diagonal)
                if z != gz:
                    h += via_cost
                if _heap3d_push(&heap, ng + h, ng, nx, ny, z) != 0:
                    free(gscore)
                    free(came_from)
                    _heap3d_free(&heap)
                    raise MemoryError()

        nx = x
        ny = y + 1
        if ny < height and cost[z, ny, nx] > 0:
            nidx = (z * height + ny) * width + nx
            step_cost = cost[z, ny, nx]
            ng = g + step_cost
            if ng < gscore[nidx]:
                gscore[nidx] = ng
                came_from[nidx] = idx
                h = _heuristic(nx, ny, gx, gy, diagonal)
                if z != gz:
                    h += via_cost
                if _heap3d_push(&heap, ng + h, ng, nx, ny, z) != 0:
                    free(gscore)
                    free(came_from)
                    _heap3d_free(&heap)
                    raise MemoryError()

        ny = y - 1
        if ny >= 0 and cost[z, ny, nx] > 0:
            nidx = (z * height + ny) * width + nx
            step_cost = cost[z, ny, nx]
            ng = g + step_cost
            if ng < gscore[nidx]:
                gscore[nidx] = ng
                came_from[nidx] = idx
                h = _heuristic(nx, ny, gx, gy, diagonal)
                if z != gz:
                    h += via_cost
                if _heap3d_push(&heap, ng + h, ng, nx, ny, z) != 0:
                    free(gscore)
                    free(came_from)
                    _heap3d_free(&heap)
                    raise MemoryError()

        if diagonal:
            nx = x + 1
            ny = y + 1
            if (
                nx < width and ny < height
                and cost[z, ny, nx] > 0
                and cost[z, y, nx] > 0
                and cost[z, ny, x] > 0
            ):
                nidx = (z * height + ny) * width + nx
                step_cost = cost[z, ny, nx] * 1.41421356237
                ng = g + step_cost
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = idx
                    h = _heuristic(nx, ny, gx, gy, diagonal)
                    if z != gz:
                        h += via_cost
                    if _heap3d_push(&heap, ng + h, ng, nx, ny, z) != 0:
                        free(gscore)
                        free(came_from)
                        _heap3d_free(&heap)
                        raise MemoryError()

            nx = x - 1
            ny = y + 1
            if (
                nx >= 0 and ny < height
                and cost[z, ny, nx] > 0
                and cost[z, y, nx] > 0
                and cost[z, ny, x] > 0
            ):
                nidx = (z * height + ny) * width + nx
                step_cost = cost[z, ny, nx] * 1.41421356237
                ng = g + step_cost
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = idx
                    h = _heuristic(nx, ny, gx, gy, diagonal)
                    if z != gz:
                        h += via_cost
                    if _heap3d_push(&heap, ng + h, ng, nx, ny, z) != 0:
                        free(gscore)
                        free(came_from)
                        _heap3d_free(&heap)
                        raise MemoryError()

            nx = x + 1
            ny = y - 1
            if (
                nx < width and ny >= 0
                and cost[z, ny, nx] > 0
                and cost[z, y, nx] > 0
                and cost[z, ny, x] > 0
            ):
                nidx = (z * height + ny) * width + nx
                step_cost = cost[z, ny, nx] * 1.41421356237
                ng = g + step_cost
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = idx
                    h = _heuristic(nx, ny, gx, gy, diagonal)
                    if z != gz:
                        h += via_cost
                    if _heap3d_push(&heap, ng + h, ng, nx, ny, z) != 0:
                        free(gscore)
                        free(came_from)
                        _heap3d_free(&heap)
                        raise MemoryError()

            nx = x - 1
            ny = y - 1
            if (
                nx >= 0 and ny >= 0
                and cost[z, ny, nx] > 0
                and cost[z, y, nx] > 0
                and cost[z, ny, x] > 0
            ):
                nidx = (z * height + ny) * width + nx
                step_cost = cost[z, ny, nx] * 1.41421356237
                ng = g + step_cost
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = idx
                    h = _heuristic(nx, ny, gx, gy, diagonal)
                    if z != gz:
                        h += via_cost
                    if _heap3d_push(&heap, ng + h, ng, nx, ny, z) != 0:
                        free(gscore)
                        free(came_from)
                        _heap3d_free(&heap)
                        raise MemoryError()

        # Via transitions (through-via model: can jump to any other layer)
        if layers > 1:
            for nz in range(layers):
                if nz == z:
                    continue
                if cost[nz, y, x] <= 0:
                    continue
                nidx = (nz * height + y) * width + x
                ng = g + via_cost + cost[nz, y, x]
                if ng < gscore[nidx]:
                    gscore[nidx] = ng
                    came_from[nidx] = idx
                    h = _heuristic(x, y, gx, gy, diagonal)
                    if nz != gz:
                        h += via_cost
                    if _heap3d_push(&heap, ng + h, ng, x, y, nz) != 0:
                        free(gscore)
                        free(came_from)
                        _heap3d_free(&heap)
                        raise MemoryError()

    _heap3d_free(&heap)

    if gscore[goal_idx] >= 1e300:
        free(gscore)
        free(came_from)
        return []

    # Reconstruct path
    cdef list path = []
    idx = goal_idx
    while idx != -1:
        nz = idx // plane
        rem = idx - nz * plane
        y = rem // width
        x = rem - y * width
        path.append((x, y, nz))
        if idx == start_idx:
            break
        idx = came_from[idx]

    path.reverse()
    free(gscore)
    free(came_from)
    return path
