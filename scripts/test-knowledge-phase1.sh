#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/home/rushil/projects/imac-agent"
VENV="$REPO_ROOT/apps/knowledge/.venv"
PY="$VENV/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "Knowledge venv not found at $PY"
  echo "Run: scripts/bootstrap-knowledge-phase1.sh"
  exit 1
fi

INCOMING="$HOME/knowledge/incoming"
TEST_DIR="$INCOMING/test-phase1"

mkdir -p "$TEST_DIR"

TXT_PATH="$TEST_DIR/test_note.txt"
CSV_PATH="$TEST_DIR/test_table.csv"

cleanup() {
  rm -f "$TXT_PATH" "$CSV_PATH" 2>/dev/null || true
  rmdir "$TEST_DIR" 2>/dev/null || true
}
trap cleanup EXIT

cat > "$TXT_PATH" <<'EOF'
Hello knowledge platform.
This is a phase 1 test.
EOF

cat > "$CSV_PATH" <<'EOF'
name,age
alice,30
bob,
alice,30
EOF

echo "[1/6] Initialize registry"
"$PY" -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from registry import initialize; initialize(); print('ok')"

echo "[2/6] Ingest TXT (expect new)"
TXT_RESULT=$("$PY" -c "import json, sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from ingest import ingest; print(json.dumps(ingest('$TXT_PATH')))" )
echo "$TXT_RESULT" | grep -q '"duplicate": false'
TXT_ID=$(echo "$TXT_RESULT" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['knowledge_item_id'])")

echo "[3/6] Ingest TXT again (expect duplicate)"
TXT_DUP=$("$PY" -c "import json, sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from ingest import ingest; print(json.dumps(ingest('$TXT_PATH')))" )
echo "$TXT_DUP" | grep -q '"duplicate": true'

echo "[4/6] Ingest CSV (expect new)"
CSV_RESULT=$("$PY" -c "import json, sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from ingest import ingest; print(json.dumps(ingest('$CSV_PATH')))" )
echo "$CSV_RESULT" | grep -q '"duplicate": false'
CSV_ID=$(echo "$CSV_RESULT" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['knowledge_item_id'])")

echo "[5/6] Search and retrieval"
"$PY" -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from registry import search, get; assert get(int('$TXT_ID')); hits = search('test_note', 10); assert hits; print('ok')"

echo "[6/6] Organization copies without deleting source"
"$PY" -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from organizer import organize; from pathlib import Path; item_id=int('$TXT_ID'); res=organize(item_id, 'documents:general'); dest=Path(res['destination']); assert dest.is_file(); assert Path('$TXT_PATH').is_file(); dest.unlink(); print('ok')"

echo "PASS"
