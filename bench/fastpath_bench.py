import argparse
import random
import time

from pardal.fastpath import astar_path
from pardal.fastpath import _py_astar
import pardal.fastpath as fastpath_mod


def build_cost_grid(width, height, obstacle_ratio, seed):
    rng = random.Random(seed)
    grid = [[1.0 for _ in range(width)] for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if rng.random() < obstacle_ratio:
                grid[y][x] = 0.0
    grid[0][0] = 1.0
    grid[height - 1][width - 1] = 1.0
    return grid


def py_astar_path(cost_grid, start, goal, diagonal):
    sx, sy = start
    gx, gy = goal
    return _py_astar._astar_path(cost_grid, sx, sy, gx, gy, diagonal)


def run_bench(label, func, cost_grid, start, goal, diagonal, runs):
    func(cost_grid, start, goal, diagonal=diagonal)
    times = []
    last_path = None
    for _ in range(runs):
        t0 = time.perf_counter()
        last_path = func(cost_grid, start, goal, diagonal=diagonal)
        times.append(time.perf_counter() - t0)
    total = sum(times)
    avg = total / runs if runs else 0.0
    print(f"{label}: total={total:.4f}s avg={avg:.6f}s path_len={len(last_path) if last_path else 0}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark fastpath A* implementations.")
    parser.add_argument("--size", type=int, default=200, help="Grid width/height.")
    parser.add_argument("--obstacle", type=float, default=0.2, help="Obstacle ratio [0-1].")
    parser.add_argument("--runs", type=int, default=5, help="Number of benchmark iterations.")
    parser.add_argument("--seed", type=int, default=1337, help="Random seed.")
    parser.add_argument("--diagonal", action="store_true", help="Allow diagonal moves.")
    args = parser.parse_args()

    width = height = args.size
    cost_grid = build_cost_grid(width, height, args.obstacle, args.seed)
    start = (0, 0)
    goal = (width - 1, height - 1)

    backend = "cython" if fastpath_mod._USE_MEMORYVIEW_2D else "python"
    print(f"fastpath backend: {backend}")
    run_bench("fastpath.astar_path", astar_path, cost_grid, start, goal, args.diagonal, args.runs)
    run_bench("py_astar._astar_path", py_astar_path, cost_grid, start, goal, args.diagonal, args.runs)


if __name__ == "__main__":
    main()
