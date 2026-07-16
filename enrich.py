from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = REPO_ROOT / "apps" / "knowledge"
if str(KNOWLEDGE_DIR) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_DIR))

from enrichment import EnrichmentError, enrich_item, enrich_pending, status  # type: ignore
from registry import update_fields  # type: ignore


def _usage() -> str:
    return (
        "Usage:\n"
        "  python enrich.py pending\n"
        "  python enrich.py item <id>\n"
        "  python enrich.py status\n"
        "  python enrich.py retry <id>\n"
    )


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(_usage())

    command = argv[1]

    try:
        if command == "pending":
            result = enrich_pending(10)
            print(json.dumps(result, indent=2, sort_keys=True))
            return

        if command == "item":
            if len(argv) < 3 or not argv[2].lstrip("#").isdigit():
                raise SystemExit(_usage())
            result = enrich_item(int(argv[2].lstrip("#")))
            print(json.dumps(result, indent=2, sort_keys=True))
            return

        if command == "status":
            print(json.dumps(status(), indent=2, sort_keys=True))
            return

        if command == "retry":
            if len(argv) < 3 or not argv[2].lstrip("#").isdigit():
                raise SystemExit(_usage())
            item_id = int(argv[2].lstrip("#"))
            update_fields(item_id, enrichment_status="pending", enrichment_error=None)
            result = enrich_item(item_id)
            print(json.dumps(result, indent=2, sort_keys=True))
            return

        raise SystemExit(_usage())

    except EnrichmentError as exc:
        raise SystemExit(f"Enrichment failed: {exc}")


if __name__ == "__main__":
    main(sys.argv)
