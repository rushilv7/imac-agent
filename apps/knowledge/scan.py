from __future__ import annotations

import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from config import INCOMING_DIR, ensure_directories
from ingest import IngestError, ingest
from registry import get, initialize, list_newest, search


def _usage() -> str:
    return (
        "Usage:\n"
        "  python scan.py scan\n"
        "  python scan.py list\n"
        "  python scan.py show <id>\n"
        "  python scan.py find <query>\n"
    )


def command_scan() -> dict:
    ensure_directories()
    initialize()

    scanned = 0
    new_items = 0
    duplicates = 0
    failures = 0

    for path in sorted(INCOMING_DIR.rglob("*")):
        if not path.is_file():
            continue
        scanned += 1
        try:
            result = ingest(path)
        except IngestError:
            failures += 1
            continue
        except Exception:
            failures += 1
            continue

        if result.get("duplicate"):
            duplicates += 1
        else:
            new_items += 1

    return {
        "scanned": scanned,
        "new": new_items,
        "duplicates": duplicates,
        "failures": failures,
    }


def command_list() -> list[dict]:
    initialize()
    return list_newest(20)


def command_show(item_id: str) -> dict:
    initialize()
    if not item_id.isdigit():
        raise SystemExit("id must be numeric")
    item = get(int(item_id))
    if not item:
        raise SystemExit("not found")
    return item


def command_find(query: str) -> list[dict]:
    initialize()
    return search(query, 20)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(_usage())

    command = argv[1]
    if command == "scan":
        data = command_scan()
        print(
            f"scanned={data['scanned']} new={data['new']} "
            f"duplicates={data['duplicates']} failures={data['failures']}"
        )
        return

    if command == "list":
        rows = command_list()
        for row in rows:
            print(f"#{row['id']} {row.get('category') or 'unknown'} {row.get('original_name')}")
        return

    if command == "show":
        if len(argv) < 3:
            raise SystemExit(_usage())
        print(json.dumps(command_show(argv[2]), indent=2, sort_keys=True))
        return

    if command == "find":
        if len(argv) < 3:
            raise SystemExit(_usage())
        rows = command_find(" ".join(argv[2:]))
        for row in rows:
            print(f"#{row['id']} {row.get('category') or 'unknown'} {row.get('original_name')}")
        return

    raise SystemExit(_usage())


if __name__ == "__main__":
    main(sys.argv)
