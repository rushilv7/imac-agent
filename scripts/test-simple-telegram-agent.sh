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

TMP_HOME=$(mktemp -d)
trap 'rm -rf "$TMP_HOME"' EXIT
export HOME="$TMP_HOME"

# Keep python from writing bytecode outside the temp HOME.
export PYTHONDONTWRITEBYTECODE=1

INCOMING="$HOME/knowledge/incoming"
TEST_DIR="$INCOMING/test-simple-telegram-agent"
TELEGRAM_INBOX="$INCOMING/telegram"

mkdir -p "$TEST_DIR" "$TELEGRAM_INBOX"

CSV_PATH="$TEST_DIR/monthly_report.csv"
XLSX_PATH="$TEST_DIR/monthly_report.xlsx"
TXT_PATH="$TEST_DIR/warner_note.txt"
NON_TAB="$TEST_DIR/not_tabular.txt"

cat > "$CSV_PATH" <<'EOF'
Name, Age , Active , Date
 alice , 30 , YES , 2026/07/16
bob, , no , 07/16/2026
 alice , 30 , YES , 2026/07/16
EOF

cat > "$TXT_PATH" <<'EOF'
Warner Music appears in this file.
This is a test note.
EOF

cat > "$NON_TAB" <<'EOF'
Just some text that is not a spreadsheet.
EOF

# Create a tiny XLSX.
"$PY" - <<PY
import sys
from pathlib import Path
sys.path.insert(0, "$REPO_ROOT/apps/knowledge")
import openpyxl

p = Path("$XLSX_PATH")
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "sheet1"
ws.append(["Name", "Active", "Date"])
ws.append([" alice ", "YES", "2026/07/16"])
ws.append([" alice ", "YES", "2026/07/16"])
ws.append(["bob", "no", "07/16/2026"])
wb.save(p)
print("ok")
PY

# Initialize imac-bot state DB.
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import initialize
initialize()
print("ok")
PY

# Initialize knowledge registry DB.
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/knowledge")
from registry import initialize
initialize()
print("ok")
PY

# Ingest files -> knowledge items.
CSV_JSON=$("$PY" - <<PY
import json, sys
sys.path.insert(0, "$REPO_ROOT/apps/knowledge")
from ingest import ingest
print(json.dumps(ingest("$CSV_PATH")))
PY
)
CSV_ID=$(IMAC_JSON="$CSV_JSON" "$PY" - <<'PY'
import json, os
data = json.loads(os.environ["IMAC_JSON"])
print(data["knowledge_item_id"])
PY
)

XLSX_JSON=$("$PY" - <<PY
import json, sys
sys.path.insert(0, "$REPO_ROOT/apps/knowledge")
from ingest import ingest
print(json.dumps(ingest("$XLSX_PATH")))
PY
)
XLSX_ID=$(IMAC_JSON="$XLSX_JSON" "$PY" - <<'PY'
import json, os
data = json.loads(os.environ["IMAC_JSON"])
print(data["knowledge_item_id"])
PY
)

NOTE_JSON=$("$PY" - <<PY
import json, sys
sys.path.insert(0, "$REPO_ROOT/apps/knowledge")
from ingest import ingest
print(json.dumps(ingest("$TXT_PATH")))
PY
)
NOTE_ID=$(IMAC_JSON="$NOTE_JSON" "$PY" - <<'PY'
import json, os
data = json.loads(os.environ["IMAC_JSON"])
print(data["knowledge_item_id"])
PY
)

NON_TAB_JSON=$("$PY" - <<PY
import json, sys
sys.path.insert(0, "$REPO_ROOT/apps/knowledge")
from ingest import ingest
print(json.dumps(ingest("$NON_TAB")))
PY
)
NON_TAB_ID=$(IMAC_JSON="$NON_TAB_JSON" "$PY" - <<'PY'
import json, os
data = json.loads(os.environ["IMAC_JSON"])
print(data["knowledge_item_id"])
PY
)

CHAT_ID=123
USER_ID=999

# Create chat context.
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import upsert_chat_context
upsert_chat_context(chat_id=$CHAT_ID, user_id=$USER_ID)
print("ok")
PY

# Helper to run a natural message and print captured events as JSON.
run_nl() {
  local text="$1"
  "$PY" - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from natural_language import handle_natural_message

messages=[]
docs=[]

def send_message(chat_id:int, text:str)->None:
    messages.append({"chat_id": chat_id, "text": text})

def send_document(chat_id:int, path:Path, caption:str|None)->None:
    docs.append({"chat_id": chat_id, "path": str(path), "caption": caption})

ok = handle_natural_message(chat_id=$CHAT_ID, user_id=$USER_ID, text=${text@Q}, send_message=send_message, send_document=send_document)
print(json.dumps({"handled": ok, "messages": messages, "docs": docs}, ensure_ascii=False))
PY
}

# [1] latest file resolution
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import upsert_chat_context
upsert_chat_context(chat_id=$CHAT_ID, user_id=$USER_ID, latest_knowledge_item_id=int($NOTE_ID))
print("ok")
PY

OUT=$(run_nl "Summarize the latest file.")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
assert x["handled"] is True
assert x["messages"], x
print("ok")
PY

# [2] knowledge search (limit to 5)
OUT=$(run_nl "What files mention Warner Music?")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'Matches' in msg
print('ok')
PY

# [3] send-original request
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import upsert_chat_context
upsert_chat_context(chat_id=$CHAT_ID, user_id=$USER_ID, latest_knowledge_item_id=int($CSV_ID))
print("ok")
PY

OUT=$(run_nl "Send me the spreadsheet I uploaded.")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
from pathlib import Path
x=json.loads(os.environ["IMAC_OUT"])
assert x['docs'], x
p=Path(x['docs'][0]['path']).resolve()
home=Path.home().resolve()
assert str(p).startswith(str(home/"knowledge")), p
print('ok')
PY

# [4] CSV clean request requires confirmation
SRC_HASH_BEFORE=$(sha256sum "$CSV_PATH" | awk '{print $1}')
OUT=$(run_nl "Check the recent file, clean it, organize it, and send me the final version.")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'Reply yes to continue' in msg
print('ok')
PY

# Approve with yes (newest pending action)
OUT=$(run_nl "yes")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'Approved' in msg
print('ok')
PY

# Run the queued job synchronously (no background thread).
"$PY" - <<PY
import sys
from pathlib import Path
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from job_runner import JobRunner
from state_store import list_queued_job_ids

notes=[]
docs=[]

def notify(chat_id:int, text:str)->None:
    notes.append(text)

def send_document(chat_id:int, path:Path, caption:str|None)->None:
    docs.append((str(path), caption))

runner=JobRunner(notify, send_document)
job_ids=list_queued_job_ids()
assert job_ids, 'no queued jobs'
runner._run(job_ids[0])
print('OK')
PY

SRC_HASH_AFTER=$(sha256sum "$CSV_PATH" | awk '{print $1}')
[[ "$SRC_HASH_BEFORE" == "$SRC_HASH_AFTER" ]]

# Cleaned artifact registered
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/knowledge")
from artifacts import list_artifacts
arts=list_artifacts(5)
assert arts, 'no artifacts'
print('ok')
PY

# [5] Excel clean request
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import upsert_chat_context
upsert_chat_context(chat_id=$CHAT_ID, user_id=$USER_ID, latest_knowledge_item_id=int($XLSX_ID))
print('ok')
PY

OUT=$(run_nl "Clean the latest spreadsheet and send me the result.")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'Reply yes to continue' in msg
print('ok')
PY

# [6] non-tabular clean rejection
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import upsert_chat_context
upsert_chat_context(chat_id=$CHAT_ID, user_id=$USER_ID, latest_knowledge_item_id=int($NON_TAB_ID))
print('ok')
PY

OUT=$(run_nl "Clean the latest file.")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'only clean CSV and Excel' in msg
print('ok')
PY

# [7] organize request
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import upsert_chat_context
upsert_chat_context(chat_id=$CHAT_ID, user_id=$USER_ID, latest_knowledge_item_id=int($NOTE_ID))
print('ok')
PY

OUT=$(run_nl "Archive the old report.")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'Reply yes to continue' in msg
print('ok')
PY

# [8] yes/no approves/rejects newest pending action
"$PY" - <<PY
import sys, secrets
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import create_action, list_pending_actions

chat_id=$CHAT_ID
for label in ('first','second'):
    create_action(code=secrets.token_hex(3).upper(), action_key='restart:imac-demo', description=label, chat_id=chat_id, ttl_minutes=10)

pending=list_pending_actions(chat_id)
assert len(pending)>=2
print('ok')
PY

OUT=$(run_nl "confirm")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'Approved' in msg
print('ok')
PY

"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import list_pending_actions
pending=list_pending_actions($CHAT_ID)
# The older one should still be pending.
assert pending, 'expected at least one pending action remaining'
print('ok')
PY

"$PY" - <<PY
import sys, secrets
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import create_action
create_action(code=secrets.token_hex(3).upper(), action_key='restart:imac-demo', description='third', chat_id=$CHAT_ID, ttl_minutes=10)
print('ok')
PY

OUT=$(run_nl "no")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'Cancelled' in msg
print('ok')
PY

# [9] paths outside ~/knowledge rejected
"$PY" - <<PY
import sys
from pathlib import Path
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from natural_language import archive_path

try:
    archive_path(Path('/etc/passwd'))
except Exception:
    print('ok')
else:
    raise SystemExit('expected rejection')
PY

# [10] malformed Hermes JSON executes nothing
COUNT_BEFORE=$("$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import list_pending_actions
print(len(list_pending_actions($CHAT_ID, 50)))
PY
)

IMAC_BOT_FORCE_INTENT_JSON='{'
OUT=$(IMAC_BOT_FORCE_INTENT_JSON="$IMAC_BOT_FORCE_INTENT_JSON" run_nl "Clean the latest spreadsheet")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'did nothing' in msg
print('ok')
PY

COUNT_AFTER=$("$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import list_pending_actions
print(len(list_pending_actions($CHAT_ID, 50)))
PY
)
[[ "$COUNT_BEFORE" == "$COUNT_AFTER" ]]

# [11] unknown actions rejected
BAD_JSON='{"target":{"type":"latest","item_id":null,"query":null},"actions":["destroy_world"],"explanation":"no"}'
OUT=$(IMAC_BOT_FORCE_INTENT_JSON="$BAD_JSON" run_nl "Anything")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'did nothing' in msg
print('ok')
PY

# [12] existing slash command helpers still callable
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from bot import help_text, list_uploads_text
assert '/find' in help_text()
_ = list_uploads_text($CHAT_ID)
print('ok')
PY

# [13] Gold wording
"$PY" - <<PY
import sys
sys.path.insert(0, "$REPO_ROOT/apps/imac-bot")
from state_store import upsert_chat_context
upsert_chat_context(chat_id=$CHAT_ID, user_id=$USER_ID, latest_knowledge_item_id=int($CSV_ID))
print('ok')
PY

OUT=$(run_nl "Push this spreadsheet all the way to Gold.")
IMAC_OUT="$OUT" "$PY" - <<'PY'
import json, os
x=json.loads(os.environ["IMAC_OUT"])
msg='\n'.join(m['text'] for m in x['messages'])
assert 'medallion data lake is not installed' in msg
print('ok')
PY

echo "PASS"
