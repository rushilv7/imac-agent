#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/knowledge"
APP="$HOME/projects/imac-agent/apps/knowledge"
VENV="$APP/.venv"

mkdir -p \
  "$ROOT/incoming" \
  "$ROOT/library/documents" \
  "$ROOT/library/data" \
  "$ROOT/library/images" \
  "$ROOT/library/other" \
  "$ROOT/artifacts" \
  "$ROOT/archive" \
  "$ROOT/index" \
  "$ROOT/tmp" \
  "$ROOT/workflows"

python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install openpyxl pypdf pillow python-magic

chmod 700 "$ROOT" "$ROOT/index" "$ROOT/tmp"

echo "Knowledge Phase 1 directories created under: $ROOT"
echo "Virtual environment created at: $VENV"
echo "Installed: openpyxl, pypdf, pillow, python-magic"
