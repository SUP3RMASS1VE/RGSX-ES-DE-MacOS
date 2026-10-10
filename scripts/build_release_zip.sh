#!/bin/bash
# Build RGSX_macos_arm64.zip (single top-level "ports/" folder) from a clean checkout.
# Usage: scripts/build_release_zip.sh [output_dir]   (default: <repo>/dist)
# Needs macOS (ditto, shasum). Uses a staging copy so the working tree is never modified.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/dist}"
ASSET="RGSX_macos_arm64.zip"

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

rsync -a \
	--exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='*.log' \
	--exclude='.venv' --exclude='.venv-*' --exclude='.agents' --exclude='.git' \
	--exclude='tests' --exclude='logs' \
	"$ROOT/ports" "$STAGE/"

chmod +x "$STAGE/ports/RGSX/RGSX.sh" "$STAGE/ports/RGSX/macos/rgsx-macos"

rm -f "$OUT_DIR/$ASSET" "$OUT_DIR/$ASSET.sha256"
# --norsrc: no AppleDouble/__MACOSX entries. ditto keeps the executable bits.
(cd "$STAGE" && ditto -c -k --norsrc --keepParent ports "$OUT_DIR/$ASSET")
(cd "$OUT_DIR" && shasum -a 256 "$ASSET" >"$ASSET.sha256")

echo "Built $OUT_DIR/$ASSET"
cat "$OUT_DIR/$ASSET.sha256"
