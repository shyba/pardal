from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from pardal.api.io import load_kicad_pcb
from pardal.api.routing import autoroute
from pardal.data_model import Board


@dataclass(frozen=True)
class RouteTrackPayload:
    net: str
    layer: str
    width_mm: float
    start_mm: tuple[float, float]
    end_mm: tuple[float, float]


@dataclass(frozen=True)
class RouteViaPayload:
    net: str
    pos_mm: tuple[float, float]
    size_mm: float
    drill_mm: float
    layers: tuple[str, ...]
    via_type: str


def _iter_tracks(board: Board) -> Iterable[RouteTrackPayload]:
    for net_name, net in board.nets.items():
        for seg in net.segments:
            yield RouteTrackPayload(
                net=net_name,
                layer=seg.layer,
                width_mm=seg.width,
                start_mm=seg.start,
                end_mm=seg.end,
            )


def _iter_vias(board: Board) -> Iterable[RouteViaPayload]:
    for net_name, net in board.nets.items():
        for via in net.vias:
            yield RouteViaPayload(
                net=net_name,
                pos_mm=via.position,
                size_mm=via.size,
                drill_mm=via.drill,
                layers=tuple(via.layers),
                via_type=via.via_type,
            )


def _write_routes_json(board: Board, out_json: Path) -> None:
    payload: dict[str, Any] = {
        "tracks": [asdict(t) for t in _iter_tracks(board)],
        "vias": [asdict(v) for v in _iter_vias(board)],
    }
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def autoroute_kicad_via_docker(
    *,
    in_pcb: Path,
    out_pcb: Path,
    routes_json: Path,
    docker_image: str,
    drc_json: Path | None,
) -> None:
    cwd = Path.cwd().resolve()
    in_pcb_abs = in_pcb.resolve()
    out_pcb_abs = out_pcb.resolve()
    routes_json_abs = routes_json.resolve()

    try:
        in_pcb_rel = in_pcb_abs.relative_to(cwd)
        out_pcb_rel = out_pcb_abs.relative_to(cwd)
        routes_json_rel = routes_json_abs.relative_to(cwd)
    except ValueError as e:
        raise ValueError("Paths must be within the current working directory") from e

    # 1) Route on the host (fastpath accelerator may be available).
    summary = load_kicad_pcb(in_pcb_abs, prefer_pcbnew=False)
    autoroute(summary.board, net_name="ALL", verbose=True)
    _write_routes_json(summary.board, routes_json_abs)

    # 2) Apply routes with pcbnew in docker (preserves stackup/settings).
    apply_script = Path(__file__).resolve().parents[1] / "tools" / "apply_routes_pcbnew.py"
    if not apply_script.exists():
        raise FileNotFoundError(apply_script)
    apply_script_rel = apply_script.resolve().relative_to(cwd)

    _run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{cwd}:/work",
            "-w",
            "/work",
            "-e",
            "PYTHONPATH=/work/pardal-pcb",
            docker_image,
            "python3",
            f"/work/{apply_script_rel.as_posix()}",
            "--in",
            f"/work/{in_pcb_rel.as_posix()}",
            "--out",
            f"/work/{out_pcb_rel.as_posix()}",
            "--routes",
            f"/work/{routes_json_rel.as_posix()}",
        ]
    )

    # 3) Optional authoritative KiCad DRC in the same image.
    if drc_json is not None:
        drc_json_abs = drc_json.resolve()
        drc_json_rel = drc_json_abs.relative_to(cwd)
        _run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{cwd}:/work",
                "-w",
                "/work",
                docker_image,
                "kicad-cli",
                "pcb",
                "drc",
                "--format",
                "json",
                "-o",
                f"/work/{drc_json_rel.as_posix()}",
                f"/work/{out_pcb_rel.as_posix()}",
            ]
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Autoroute a KiCad PCB on the host, then apply routes via pcbnew in docker."
    )
    ap.add_argument("--in", dest="in_pcb", type=Path, required=True)
    ap.add_argument("--out", dest="out_pcb", type=Path, required=True)
    ap.add_argument("--routes-json", dest="routes_json", type=Path, required=True)
    ap.add_argument(
        "--docker-image",
        default="kicad/kicad:9.0.6-full",
        help="KiCad docker image to use for pcbnew + DRC",
    )
    ap.add_argument("--drc-json", dest="drc_json", type=Path, default=None)
    args = ap.parse_args(argv)

    autoroute_kicad_via_docker(
        in_pcb=args.in_pcb,
        out_pcb=args.out_pcb,
        routes_json=args.routes_json,
        docker_image=str(args.docker_image),
        drc_json=args.drc_json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
