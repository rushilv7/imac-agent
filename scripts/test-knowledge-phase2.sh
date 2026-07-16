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
TEST_DIR="$INCOMING/test-phase2"

mkdir -p "$TEST_DIR"

TXT_PATH="$TEST_DIR/test_note_phase2.txt"
CSV_PATH="$TEST_DIR/test_table_phase2.csv"

cleanup() {
  rm -f "$TXT_PATH" "$CSV_PATH" 2>/dev/null || true
  rmdir "$TEST_DIR" 2>/dev/null || true
}
trap cleanup EXIT

cat > "$TXT_PATH" <<'EOF'
This is a Phase 2 test note about Toronto and Canada.
It mentions Rushil and OpenAI.
EOF

cat > "$CSV_PATH" <<'EOF'
Name, Age , Active , Date
 alice , 30 , YES , 2026/07/16
bob, , no , 07/16/2026
 alice , 30 , YES , 2026/07/16
EOF

echo "[1/10] Initialize registry"
"$PY" -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from registry import initialize; initialize(); print('ok')"

echo "[2/10] Ingest TXT and CSV"
TXT_RESULT=$("$PY" -c "import json, sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from ingest import ingest; print(json.dumps(ingest('$TXT_PATH')))" )
CSV_RESULT=$("$PY" -c "import json, sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from ingest import ingest; print(json.dumps(ingest('$CSV_PATH')))" )
TXT_ID=$(echo "$TXT_RESULT" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['knowledge_item_id'])")
CSV_ID=$(echo "$CSV_RESULT" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['knowledge_item_id'])")

echo "[3/10] Enrichment fields can be stored and retrieved (no Hermes call in test)"
"$PY" -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from registry import update_fields, get; update_fields(int('$TXT_ID'), enrichment_status='completed', enrichment_timestamp='now', enrichment_error=None, document_type='text', suggested_category='documents:general', named_entities=['Toronto']); item=get(int('$TXT_ID')); assert item and item.get('document_type')=='text' and item.get('enrichment_status')=='completed'; print('ok')"

echo "[4/10] FTS search returns expected items"
"$PY" -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from registry import search_ranked; hits=search_ranked('Toronto', 5); assert any(int(h['id'])==int('$TXT_ID') for h in hits); print('ok')"

echo "[5/10] Explicit knowledge-item context works (build_knowledge_context includes requested id)"
python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/imac-bot'); from upload_context import build_knowledge_context; ctx=build_knowledge_context('knowledge item #'+str('$TXT_ID'), chat_id=123); assert ('Knowledge Item ID: #'+str('$TXT_ID')) in ctx; print('ok')"

echo "[6/10] Automatic retrieval selects relevant items (no explicit id)"
python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/imac-bot'); from upload_context import build_knowledge_context; ctx=build_knowledge_context('What does the Toronto note say?', chat_id=123); assert 'KNOWLEDGE ITEM CONTEXT' in ctx and str('$TXT_ID') in ctx; print('ok')"

echo "[7/10] CSV workflow proposal validation"
python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from workflows import parse_operations, validate_operations; ops=parse_operations('trim_strings,remove_exact_duplicates'); validate_operations(ops); print('ok')"

echo "[8/10] Unsupported workflow operations are rejected"
set +e
python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from workflows import parse_operations, validate_operations; ops=parse_operations('drop_tables'); validate_operations(ops)" >/dev/null 2>&1
RC=$?
set -e
if [[ $RC -eq 0 ]]; then
  echo "Expected unsupported op to be rejected"
  exit 1
fi

echo "[9/10] CSV transformation artifact creation + source remains unchanged + duplicates removed"
SRC_HASH_BEFORE=$(sha256sum "$CSV_PATH" | awk '{print $1}')
WF_OUT=$(python3 -c "import json, sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from workflows import run_workflow; rep=run_workflow(knowledge_item_id=int('$CSV_ID'), operations=['trim_strings','standardize_column_names','normalize_booleans','normalize_dates','remove_exact_duplicates']); print(json.dumps(rep.__dict__))")
ART_ID=$(echo "$WF_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['artifact_id'])")
ART_PATH=$(echo "$WF_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['artifact_path'])")
SRC_HASH_AFTER=$(sha256sum "$CSV_PATH" | awk '{print $1}')
[[ "$SRC_HASH_BEFORE" == "$SRC_HASH_AFTER" ]]
python3 -c "import csv; from pathlib import Path; p=Path('$ART_PATH'); rows=list(csv.reader(p.read_text('utf-8').splitlines())); assert len(rows)==3; print('ok')"  # header + 2 unique rows

DUPS_REMOVED=$(echo "$WF_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['duplicate_rows_removed'])")
[[ "$DUPS_REMOVED" == "1" ]]

COLUMNS_AFTER=$(echo "$WF_OUT" | python3 -c "import json,sys; print(','.join(json.load(sys.stdin)['columns_after']))")
echo "$COLUMNS_AFTER" | grep -q "name,age,active,date"

echo "[10/10] Artifact registration and retrieval + path validation rejects outside root"
"$PY" -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/knowledge'); from artifacts import get_artifact; a=get_artifact(int('$ART_ID')); assert a and a.get('stored_path')=='$ART_PATH'; print('ok')"

set +e
python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/apps/imac-bot'); from bot import _validated_path_under_knowledge_root; _validated_path_under_knowledge_root('/etc/passwd')" >/dev/null 2>&1
RC=$?
set -e
if [[ $RC -eq 0 ]]; then
  echo "Expected outside-root path to be rejected"
  exit 1
fi

echo "PASS"
