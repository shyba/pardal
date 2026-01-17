from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RustRouteResult:
    routes_json: Path
    out_pcb: Path
    problem_json: Path


def _repo_root() -> Path:
    # pcb_tool/api/ -> pcb_tool/ -> pardal-pcb/
    return Path(__file__).resolve().parents[2]


def _default_router_bin() -> Path:
    return _repo_root() / "pardal_router_cli" / "target" / "release" / "pardal-router"


def ensure_router_binary() -> Path:
    env = os.getenv("PARDAL_ROUTER_BIN")
    if env:
        p = Path(env).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(p)
        return p

    router = _default_router_bin()
    if router.exists():
        return router

    crate_dir = _repo_root() / "pardal_router_cli"
    subprocess.run(["cargo", "build", "--release"], cwd=crate_dir, check=True)
    if not router.exists():
        raise FileNotFoundError(router)
    return router


def _run(cmd: list[str], *, cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def rust_route_kicad_via_docker(
    *,
    in_pcb: Path,
    out_pcb: Path,
    docker_image: str = "kicad/kicad:9.0.6-full",
    resolution_mm: float = 0.2,
    inflate_mm: float | None = None,
    cfg_json: Path | None = None,
    routes_json: Path | None = None,
    problem_json: Path | None = None,
) -> RustRouteResult:
    """Route a KiCad PCB via: pcbnew extractor (docker) -> Rust router (host) -> pcbnew apply (docker).

    This is currently targeted at the `fpga_large` fixture and the Rust backend prototype.
    """
    mount_root = _repo_root().parent.resolve()
    in_pcb_abs = in_pcb.resolve()
    out_pcb_abs = out_pcb.resolve()

    if routes_json is None:
        routes_json = out_pcb_abs.with_suffix(".routes.json")
    if problem_json is None:
        problem_json = out_pcb_abs.with_suffix(".problem.json")

    try:
        in_pcb_rel = in_pcb_abs.relative_to(mount_root)
        out_pcb_rel = out_pcb_abs.relative_to(mount_root)
        routes_json_rel = routes_json.resolve().relative_to(mount_root)
        problem_json_rel = problem_json.resolve().relative_to(mount_root)
    except ValueError as e:
        raise ValueError(f"Paths must be within {mount_root}") from e

    tool_dir = _repo_root() / "pcb_tool" / "tools"
    extract_script = tool_dir / "extract_routing_problem_pcbnew.py"
    apply_script = tool_dir / "apply_routes_pcbnew.py"
    if not extract_script.exists():
        raise FileNotFoundError(extract_script)
    if not apply_script.exists():
        raise FileNotFoundError(apply_script)

    extract_rel = extract_script.relative_to(_repo_root())
    apply_rel = apply_script.relative_to(_repo_root())

    # 1) Extract routing problem via pcbnew in docker.
    extract_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{mount_root}:/work",
        "-w",
        "/work",
        "-e",
        "PYTHONPATH=/work/pardal-pcb",
        docker_image,
        "python3",
        f"/work/pardal-pcb/{extract_rel.as_posix()}",
        "--pcb",
        f"/work/{in_pcb_rel.as_posix()}",
        "--out",
        f"/work/{problem_json_rel.as_posix()}",
        "--resolution",
        str(float(resolution_mm)),
    ]
    if inflate_mm is not None:
        extract_cmd.extend(["--inflate", str(float(inflate_mm))])
    _run(
        extract_cmd,
        cwd=mount_root,
    )

    # 2) Route on the host using the Rust binary.
    router_bin = ensure_router_binary()
    cmd = [str(router_bin), str(problem_json.resolve()), str(routes_json.resolve())]
    if cfg_json is not None:
        cmd.append(str(cfg_json.resolve()))
    _run(cmd, cwd=mount_root)

    # 3) Apply routes using pcbnew in docker.
    _run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{mount_root}:/work",
            "-w",
            "/work",
            "-e",
            "PYTHONPATH=/work/pardal-pcb",
            docker_image,
            "python3",
            f"/work/pardal-pcb/{apply_rel.as_posix()}",
            "--in",
            f"/work/{in_pcb_rel.as_posix()}",
            "--out",
            f"/work/{out_pcb_rel.as_posix()}",
            "--routes",
            f"/work/{routes_json_rel.as_posix()}",
        ],
        cwd=mount_root,
    )

    # Basic sanity check: the Rust router records failures.
    try:
        payload = json.loads(routes_json.read_text(encoding="utf-8", errors="replace"))
        failed = payload.get("failed_nets", []) or []
        if failed:
            print(f"Rust router: {len(failed)} net(s) failed to route")
    except Exception:
        pass

    return RustRouteResult(routes_json=routes_json, out_pcb=out_pcb_abs, problem_json=problem_json)
