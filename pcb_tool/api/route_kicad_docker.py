from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2


@dataclass(frozen=True)
class RouteViaDockerResult:
    routes_json: Path
    out_pcb: Path
    problem_json: Path


def _repo_root() -> Path:
    # pcb_tool/api/ -> pcb_tool/ -> pardal-pcb/
    return Path(__file__).resolve().parents[2]


def _default_mojo_router_bin() -> Path:
    return _repo_root() / "pardal_router_mojo" / "build" / "pardal-router-mojo"


def _build_mojo_router_bin() -> Path:
    build_script = _repo_root() / "pardal_router_mojo" / "build.sh"
    if not build_script.exists():
        raise FileNotFoundError(build_script)
    subprocess.run([str(build_script)], cwd=build_script.parent, check=True)
    out_bin = _default_mojo_router_bin()
    if not out_bin.exists():
        raise FileNotFoundError(out_bin)
    return out_bin


def _router_backend() -> str:
    # Values: auto|mojo
    v = (os.getenv("PARDAL_ROUTER_BACKEND") or "auto").strip().lower()
    if v in {"", "auto"}:
        return "auto"
    if v in {"mojo"}:
        return v
    raise ValueError(f"Invalid PARDAL_ROUTER_BACKEND={v!r} (expected auto|mojo)")


def ensure_router_binary() -> Path:
    """Return a router binary for `problem.json -> routes.json`.

    Selection order:
    1) `PARDAL_ROUTER_BIN=/path/to/router` (absolute override)
    2) `PARDAL_ROUTER_BACKEND=auto|mojo`:
       - auto (default): prefer Mojo
       - mojo: require Mojo
    """
    env = os.getenv("PARDAL_ROUTER_BIN")
    if env:
        p = Path(env).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(p)
        return p

    backend = _router_backend()
    if backend in {"auto", "mojo"}:
        mojo = _default_mojo_router_bin()
        if mojo.exists():
            return mojo
        try:
            return _build_mojo_router_bin()
        except Exception:
            if backend == "mojo":
                raise

    raise FileNotFoundError(
        _default_mojo_router_bin(),
        "Mojo router binary missing. Build it with: pardal-pcb/pardal_router_mojo/build.sh",
    )


def _run(cmd: list[str], *, cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _ensure_under_mount(
    *,
    mount_root: Path,
    in_pcb_abs: Path,
    out_pcb_abs: Path,
    routes_json_abs: Path,
    problem_json_abs: Path,
) -> tuple[Path | None, Path, Path, Path, Path]:
    """Ensure docker-visible paths under `mount_root`.

    Docker runs mount `mount_root` at `/work`, so any path not under `mount_root`
    is not accessible. For such paths, we stage IO in a repo-local temp folder
    and copy results back at the end.

    Returns:
      stage_dir, in_pcb_docker, out_pcb_docker, routes_json_docker, problem_json_docker
    """
    def under(p: Path) -> bool:
        try:
            p.relative_to(mount_root)
            return True
        except ValueError:
            return False

    if (
        under(in_pcb_abs)
        and under(out_pcb_abs)
        and under(routes_json_abs)
        and under(problem_json_abs)
    ):
        return None, in_pcb_abs, out_pcb_abs, routes_json_abs, problem_json_abs

    stage_dir = (_repo_root() / "build" / "docker_io" / uuid.uuid4().hex).resolve()
    stage_dir.mkdir(parents=True, exist_ok=True)

    staged_in = stage_dir / in_pcb_abs.name
    staged_out = stage_dir / out_pcb_abs.name
    staged_routes = stage_dir / routes_json_abs.name
    staged_problem = stage_dir / problem_json_abs.name

    copy2(in_pcb_abs, staged_in)

    return stage_dir, staged_in, staged_out, staged_routes, staged_problem


def route_kicad_via_docker(
    *,
    in_pcb: Path,
    out_pcb: Path,
    docker_image: str = "kicad/kicad:9.0.6-full",
    resolution_mm: float = 0.2,
    inflate_mm: float | None = None,
    cfg_json: Path | None = None,
    routes_json: Path | None = None,
    problem_json: Path | None = None,
) -> RouteViaDockerResult:
    """Route a KiCad PCB via: pcbnew extractor (docker) -> router (host) -> pcbnew apply (docker).

    This is currently targeted at the `fpga_large` fixture and the Mojo router backend.
    """
    mount_root = _repo_root().parent.resolve()
    in_pcb_abs = in_pcb.resolve()
    out_pcb_abs = out_pcb.resolve()

    if routes_json is None:
        routes_json = out_pcb_abs.with_suffix(".routes.json")
    if problem_json is None:
        problem_json = out_pcb_abs.with_suffix(".problem.json")

    stage_dir, in_pcb_docker, out_pcb_docker, routes_json_docker, problem_json_docker = _ensure_under_mount(
        mount_root=mount_root,
        in_pcb_abs=in_pcb_abs,
        out_pcb_abs=out_pcb_abs,
        routes_json_abs=routes_json.resolve(),
        problem_json_abs=problem_json.resolve(),
    )

    try:
        in_pcb_rel = in_pcb_docker.relative_to(mount_root)
        out_pcb_rel = out_pcb_docker.relative_to(mount_root)
        routes_json_rel = routes_json_docker.relative_to(mount_root)
        problem_json_rel = problem_json_docker.relative_to(mount_root)
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

    # 2) Route on the host using the selected router binary.
    router_bin = ensure_router_binary()
    cmd = [str(router_bin), str(problem_json_docker), str(routes_json_docker)]
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

    # Basic sanity check: the router records failures.
    try:
        payload = json.loads(routes_json_docker.read_text(encoding="utf-8", errors="replace"))
        failed = payload.get("failed_nets", []) or []
        if failed:
            print(f"Router: {len(failed)} net(s) failed to route")
    except Exception:
        pass

    # Copy staged artifacts back to caller paths if we had to stage.
    if stage_dir is not None:
        out_pcb_abs.parent.mkdir(parents=True, exist_ok=True)
        routes_json.resolve().parent.mkdir(parents=True, exist_ok=True)
        problem_json.resolve().parent.mkdir(parents=True, exist_ok=True)

        if out_pcb_docker != out_pcb_abs:
            copy2(out_pcb_docker, out_pcb_abs)
        if routes_json_docker != routes_json.resolve():
            copy2(routes_json_docker, routes_json.resolve())
        if problem_json_docker != problem_json.resolve():
            copy2(problem_json_docker, problem_json.resolve())

    return RouteViaDockerResult(routes_json=routes_json, out_pcb=out_pcb_abs, problem_json=problem_json)
