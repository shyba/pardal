#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PIXI="${PIXI:-$HOME/.pixi/bin/pixi}"
OUT_DIR="${OUT_DIR:-$ROOT/build}"
OUT_BIN="${OUT_BIN:-$OUT_DIR/pardal-router-mojo}"

mkdir -p "$OUT_DIR"
exec "$PIXI" run mojo build -o "$OUT_BIN" "$ROOT/main.mojo"

