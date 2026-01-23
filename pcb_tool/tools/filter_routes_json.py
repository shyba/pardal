from __future__ import annotations

import argparse
import json
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Filter a routes.json file by net name.")
    ap.add_argument("--in", dest="in_path", type=Path, required=True, help="Input routes.json")
    ap.add_argument("--out", dest="out_path", type=Path, required=True, help="Output routes.json")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--drop-nets", nargs="+", default=None, help="Net names to drop")
    g.add_argument("--keep-nets", nargs="+", default=None, help="Net names to keep")
    return ap.parse_args()


def main() -> int:
    args = _parse_args()
    payload = json.loads(args.in_path.read_text(encoding="utf-8"))

    drop = set(args.drop_nets or [])
    keep = set(args.keep_nets or [])

    def want(net: str) -> bool:
        if keep:
            return net in keep
        return net not in drop

    tracks = [t for t in payload.get("tracks", []) if want(str(t.get("net", "")))]
    vias = [v for v in payload.get("vias", []) if want(str(v.get("net", "")))]

    payload["tracks"] = tracks
    payload["vias"] = vias
    # Keep `failed_nets` as metadata only; for downstream steps, set it to the nets we dropped.
    if keep:
        payload["failed_nets"] = [n for n in payload.get("failed_nets", []) if n not in keep]
    else:
        payload["failed_nets"] = sorted(drop)

    args.out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

