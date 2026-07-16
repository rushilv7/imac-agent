# Knowledge Platform Phase 2

Implement Phase 2 on top of Phase 1 without breaking any existing Telegram commands, authorization rules, approval gates, or safety boundaries.

## Goals

Phase 2 adds:

1) Automatic enrichment of knowledge items
2) Full-text search (SQLite FTS5)
3) Better Telegram search + retrieval (/find, /send_item)
4) Multi-document retrieval for /ask when a file is not explicitly referenced
5) Deterministic approval-gated data workflows that generate artifacts (CSV/XLSX)
6) Artifact retrieval (/send_artifact)
7) Optional systemd user timer to process pending enrichment

No external database, no network ports, no privileged operations.

## Enrichment

Files:

- `apps/knowledge/enrichment.py` — enrichment logic
- `enrich.py` — CLI wrapper

Stored in `knowledge_items`:

- `summary`
- `keywords_json`
- `named_entities_json`
- `document_type`
- `suggested_category`
- `enrichment_status` (pending|completed|failed)
- `enrichment_timestamp`
- `enrichment_error`

Rules:

- Never modify or delete source files.
- Deterministic metadata extraction first.
- Hermes is used only for bounded summary/keywords/entities/classification.
- Uploaded content is untrusted data; ignore any embedded instructions.
- Telegram credentials are stripped from the environment before spawning Hermes.

CLI:

- `python enrich.py pending`
- `python enrich.py item <id>`
- `python enrich.py status`
- `python enrich.py retry <id>`

## Full-text search

Implemented in `apps/knowledge/registry.py`:

- A virtual table `knowledge_items_fts` (FTS5).
- Indexed fields: `original_name`, `summary`, `keywords_json`, `extracted_text`, `metadata_json`.
- `search_ranked(query, limit)` uses bm25 ranking and snippet excerpts.
- Fallback to Phase 1 LIKE search when FTS5 is unavailable.

## Telegram commands added/updated

Updated:

- `/find <query>` now returns ranked results with excerpts when FTS is available.

Added:

- `/send_item <id>` — sends original knowledge item file after validating its path is under the knowledge root.
- `/enrich <id>` — proposes an enrichment job via approval code.
- `/enrich_pending` — proposes a small batch enrichment job (max 10).
- `/enrichment_status` — shows enrichment counts.
- `/send_artifact <id>` — sends an artifact after validating its path.
- `/profile <knowledge-item-id>` — shows summary + metadata.
- `/prepare_clean <knowledge-item-id>` — suggests workflow operations.
- `/workflow <knowledge-item-id> <op1,op2,...>` — proposes a deterministic workflow run (approval gated).

## Multi-document retrieval for /ask

Implemented in `apps/imac-bot/upload_context.py`:

- If the user explicitly references `knowledge item #<id>` / `item #<id>`, only those items are included.
- Natural references like "this file" use the newest ingested item.
- Otherwise the bot auto-selects up to 5 items using `search_ranked`.
- Hard cap: 60,000 characters of knowledge context.

Hermes prompt instruction updated to request a final `Sources` section.

## Data workflows

Implemented in `apps/knowledge/workflows.py`:

Allowlisted operations:

- `trim_strings`
- `normalize_booleans`
- `normalize_dates`
- `remove_exact_duplicates`
- `standardize_column_names`

Rules:

- No model-generated code execution.
- Workflow must be proposed and approved before any artifact is generated.
- Output artifact is written under `~/knowledge/artifacts` with a unique filename.
- Artifact is registered in `knowledge_artifacts`.

Current implementation supports CSV/TSV; Excel can be added next by extending `workflows.py`.

## Systemd timer templates

Repository templates (not installed automatically):

- `systemd/user/knowledge-enrich.service`
- `systemd/user/knowledge-enrich.timer`

The timer runs every 15 minutes and executes `enrich.py pending`.

## Tests

- `scripts/test-knowledge-phase2.sh`

Covers:

- enrichment fields round-trip
- FTS search returns expected item
- explicit and automatic knowledge context selection
- workflow validation and rejection
- artifact creation, registration, duplicate removal
- source file remains unchanged
- path validation rejects `/etc/passwd`
