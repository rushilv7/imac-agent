from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

# Allow importing Phase 1/2 knowledge modules without packaging.
import sys

REPO_ROOT = Path("/home/rushil/projects/imac-agent")
KNOWLEDGE_DIR = REPO_ROOT / "apps" / "knowledge"
if str(KNOWLEDGE_DIR) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_DIR))

try:
    from config import ARCHIVE_DIR, KNOWLEDGE_ROOT as KNOWLEDGE_ROOT_PATH  # type: ignore
    from artifacts import get_artifact as knowledge_get_artifact  # type: ignore
    from registry import get as knowledge_get_item  # type: ignore
    from registry import list_newest as knowledge_list_newest  # type: ignore
    from registry import search_ranked as knowledge_search_ranked  # type: ignore
except Exception:  # pragma: no cover
    ARCHIVE_DIR = None
    KNOWLEDGE_ROOT_PATH = None
    knowledge_get_artifact = None
    knowledge_get_item = None
    knowledge_list_newest = None
    knowledge_search_ranked = None

from state_store import (
    approve_newest_pending_action,
    get_chat_context,
    list_uploads,
    reject_newest_pending_action,
    upsert_chat_context,
)


ALLOWED_ACTIONS: set[str] = {
    "find",
    "inspect",
    "summarize",
    "profile",
    "organize",
    "clean",
    "send_original",
    "send_result",
    "archive",
    "list_recent",
}

DEFAULT_CLEAN_OPERATIONS = [
    "trim_strings",
    "standardize_column_names",
    "normalize_booleans",
    "normalize_dates",
    "remove_exact_duplicates",
]


@dataclass(frozen=True)
class TargetSpec:
    type: str  # latest | item_id | search
    item_id: int | None
    query: str | None


@dataclass(frozen=True)
class Intent:
    target: TargetSpec
    actions: list[str]
    explanation: str
    gold_requested: bool = False


_CONFIRM_WORDS = {
    "yes",
    "confirm",
    "go ahead",
    "do it",
}

_REJECT_WORDS = {
    "no",
    "cancel",
    "stop",
    "never mind",
}


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def is_confirmation(text: str) -> bool:
    lowered = _normalize_text(text).lower()
    return lowered in _CONFIRM_WORDS


def is_rejection(text: str) -> bool:
    lowered = _normalize_text(text).lower()
    return lowered in _REJECT_WORDS


def _safe_filename(value: str) -> str:
    # Never show full paths back to Telegram.
    return Path(value).name


def _validated_under_knowledge_root(path: str | Path) -> Path:
    if KNOWLEDGE_ROOT_PATH is None:
        raise RuntimeError("Knowledge platform is unavailable.")
    resolved = Path(path).expanduser().resolve()
    root = Path(KNOWLEDGE_ROOT_PATH).expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("Refused to access path outside the knowledge root.") from exc
    if not resolved.is_file():
        raise RuntimeError("Requested file is missing.")
    return resolved


def _unique_destination(dest_dir: Path, filename: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = Path(filename).stem
    suffix = Path(filename).suffix

    candidate = dest_dir / f"{base}{suffix}"
    if not candidate.exists():
        return candidate

    for index in range(2, 1000):
        candidate = dest_dir / f"{base}_{index}{suffix}"
        if not candidate.exists():
            return candidate

    raise RuntimeError("Could not find a unique archive filename")


def archive_path(source: Path) -> dict[str, Any]:
    """Archive a file already under ~/knowledge.

    Safety rules:
    - Refuse paths outside ~/knowledge.
    - Never overwrite.
    - Never delete permanently.
    - If the source is under ~/knowledge/incoming, COPY instead of move.
      (Incoming files are treated as immutable in this system.)
    """

    if ARCHIVE_DIR is None:
        raise RuntimeError("Knowledge archive directory is unavailable.")

    src = _validated_under_knowledge_root(source)
    archive_root = Path(ARCHIVE_DIR).expanduser().resolve()
    archive_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    dest = _unique_destination(archive_root, src.name)

    incoming_root = (Path(KNOWLEDGE_ROOT_PATH).expanduser().resolve() / "incoming") if KNOWLEDGE_ROOT_PATH else None

    copied = False
    if incoming_root is not None:
        try:
            src.relative_to(incoming_root)
        except ValueError:
            copied = False
        else:
            copied = True

    import shutil

    if copied:
        shutil.copy2(src, dest)
        return {"ok": True, "mode": "copied", "source": str(src), "destination": str(dest)}

    shutil.move(str(src), str(dest))
    return {"ok": True, "mode": "moved", "source": str(src), "destination": str(dest)}


def _forced_intent_json() -> str | None:
    forced = os.environ.get("IMAC_BOT_FORCE_INTENT_JSON", "").strip()
    return forced if forced else None


def _heuristic_intent_json(message: str) -> str:
    """Deterministic fallback intent parser.

    This is used when Hermes is unavailable. It returns strict JSON with the
    required schema.
    """

    text = _normalize_text(message)
    lowered = text.lower()

    gold_requested = any(word in lowered for word in ("bronze", "silver", "gold"))

    actions: list[str] = []

    if any(token in lowered for token in ("what files did i recently upload", "recent uploads", "list recent", "recent files")):
        actions.append("list_recent")

    if any(token in lowered for token in ("summarize", "summary")):
        actions.append("summarize")

    if any(token in lowered for token in ("profile", "metadata")):
        actions.append("profile")

    if any(token in lowered for token in ("inspect", "check", "look at", "review")):
        actions.append("inspect")

    if any(token in lowered for token in ("organize", "file it", "put it in")):
        actions.append("organize")

    if any(token in lowered for token in ("clean", "cleanup", "dedupe", "deduplicate", "normalize")):
        actions.append("clean")

    if any(token in lowered for token in ("archive", "archive the", "archive my")):
        actions.append("archive")

    if any(token in lowered for token in ("find", "search", "mention", "mentions", "about", "files about", "what files")):
        actions.append("find")

    # Sending.
    if any(token in lowered for token in ("send", "give me", "share")):
        if any(token in lowered for token in ("cleaned", "result", "final")):
            actions.append("send_result")
        else:
            actions.append("send_original")

    if gold_requested and "clean" not in actions:
        # "Push to Gold" means final cleaned artifact.
        actions.append("clean")
        if "send_result" not in actions:
            actions.append("send_result")

    # Default to something safe.
    if not actions:
        actions = ["find"]

    # Target selection.
    target_type = "latest"
    item_id: int | None = None
    query: str | None = None

    m = re.search(r"\b(?:item|knowledge\s+item)\s*#?(\d+)\b", lowered)
    if m:
        target_type = "item_id"
        item_id = int(m.group(1))

    if target_type != "item_id" and "find" in actions:
        # Extract naive query after 'about'/'mention' or last quoted string.
        quoted = re.findall(r"\"([^\"]{2,120})\"", text)
        if quoted:
            query = quoted[-1].strip()
        else:
            m2 = re.search(r"\babout\s+(.+)$", text, flags=re.IGNORECASE)
            if m2:
                query = m2.group(1).strip().rstrip(".?")
            else:
                m3 = re.search(r"\bmention\s+(.+)$", text, flags=re.IGNORECASE)
                if m3:
                    query = m3.group(1).strip().rstrip(".?")

        if query:
            target_type = "search"

    # Archiving requests often omit explicit file references; default to latest.
    if "archive" in actions and target_type == "search":
        target_type = "latest"

    explanation = "I will help manage your files safely." 
    if gold_requested:
        explanation = (
            "The medallion data lake is not installed, so I will create the final cleaned artifact instead."
        )

    payload = {
        "target": {"type": target_type, "item_id": item_id, "query": query},
        "actions": actions,
        "explanation": explanation,
    }
    return json.dumps(payload, ensure_ascii=False)


def hermes_intent_json(message: str) -> str:
    """Return strict JSON intent.

    In production this can be wired to a Hermes model call. For now we use a
    deterministic parser.

    Test hooks:
      - IMAC_BOT_FORCE_INTENT_JSON: literal string returned verbatim
    """

    forced = _forced_intent_json()
    if forced is not None:
        return forced
    return _heuristic_intent_json(message)


def parse_intent(message: str) -> Intent | None:
    raw = hermes_intent_json(message)

    try:
        data = json.loads(raw)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    target = data.get("target")
    actions = data.get("actions")
    explanation = data.get("explanation")

    if not isinstance(target, dict) or not isinstance(actions, list) or not isinstance(explanation, str):
        return None

    t_type = str(target.get("type") or "").strip()
    if t_type not in {"latest", "item_id", "search"}:
        return None

    item_id: int | None = None
    query: str | None = None

    if t_type == "item_id":
        raw_id = target.get("item_id")
        if isinstance(raw_id, int):
            item_id = raw_id
        elif isinstance(raw_id, str) and raw_id.lstrip("#").isdigit():
            item_id = int(raw_id.lstrip("#"))
        else:
            return None

    if t_type == "search":
        raw_query = target.get("query")
        if not isinstance(raw_query, str) or not raw_query.strip():
            return None
        query = raw_query.strip()[:200]

    cleaned_actions: list[str] = []
    for value in actions:
        if not isinstance(value, str):
            return None
        action = value.strip()
        if action not in ALLOWED_ACTIONS:
            return None
        if action not in cleaned_actions:
            cleaned_actions.append(action)

    if not cleaned_actions:
        return None

    gold_requested = any(word in _normalize_text(message).lower() for word in ("bronze", "silver", "gold"))

    return Intent(
        target=TargetSpec(type=t_type, item_id=item_id, query=query),
        actions=cleaned_actions,
        explanation=explanation.strip()[:240],
        gold_requested=gold_requested,
    )


def _format_search_hits(hits: Iterable[dict[str, Any]], limit: int = 5) -> str:
    lines: list[str] = []
    for idx, item in enumerate(list(hits)[:limit], start=1):
        try:
            item_id = int(item.get("id") or 0)
        except Exception:
            continue
        name = str(item.get("original_name") or "")
        category = str(item.get("category") or "")
        lines.append(f"{idx}.  #{item_id} {category} {_safe_filename(name)}".strip())
    return "\n".join(lines)


def _summarize_item(item: dict[str, Any]) -> str:
    summary = str(item.get("summary") or "").strip()
    if summary:
        return summary[:1200]

    extracted = str(item.get("extracted_text") or "").strip()
    if extracted:
        excerpt = " ".join(extracted.split())
        return (excerpt[:900] + ("…" if len(excerpt) > 900 else ""))

    meta_json = str(item.get("metadata_json") or "")
    if meta_json:
        return "No summary is available yet. Metadata is present." 

    return "No extracted text is available to summarize." 


def _profile_item_text(item: dict[str, Any]) -> str:
    item_id = int(item.get("id") or 0)
    name = _safe_filename(str(item.get("original_name") or ""))
    mime = str(item.get("mime_type") or "")
    ext = str(item.get("extension") or "")
    category = str(item.get("category") or "")
    status = str(item.get("status") or "")
    doc_type = str(item.get("document_type") or "")
    suggested = str(item.get("suggested_category") or "")
    return (
        f"File: {name}\n"
        f"Knowledge item: #{item_id}\n"
        f"Type: {doc_type or ext or mime or 'unknown'}\n"
        f"Category: {category or 'unknown'}\n"
        f"Status: {status or 'unknown'}\n"
        + (f"Suggested category: {suggested}\n" if suggested else "")
    ).strip()


def _resolve_latest_knowledge_item_id(chat_id: int) -> int | None:
    ctx = get_chat_context(chat_id)
    if not ctx:
        return None
    value = ctx.get("latest_knowledge_item_id")
    return int(value) if value is not None else None


def _resolve_latest_artifact_id(chat_id: int) -> int | None:
    ctx = get_chat_context(chat_id)
    if not ctx:
        return None
    value = ctx.get("latest_artifact_id")
    return int(value) if value is not None else None


def _resolve_target_item_id(intent: Intent, *, chat_id: int, prefer_artifact: bool) -> tuple[int | None, int | None, str | None]:
    """Return (knowledge_item_id, artifact_id, error)."""

    if intent.target.type == "item_id":
        return int(intent.target.item_id or 0), None, None

    if intent.target.type == "latest":
        if prefer_artifact:
            artifact_id = _resolve_latest_artifact_id(chat_id)
            if artifact_id is not None:
                return None, artifact_id, None

        item_id = _resolve_latest_knowledge_item_id(chat_id)
        if item_id is None:
            return None, None, "I couldn't find a recent knowledge item for this chat yet. Upload a file first."
        return item_id, None, None

    if intent.target.type == "search":
        return None, None, None

    return None, None, "Unsupported target type."


def handle_natural_message(
    *,
    chat_id: int,
    user_id: int,
    text: str,
    send_message: Callable[[int, str], None],
    send_document: Callable[[int, Path, str | None], None],
) -> bool:
    """Handle a non-slash private message.

    Returns True if handled (even if no action was executed).
    Returns False if this handler declines to handle the message (caller may
    fall back to other conversational modes).
    """

    raw = (text or "").strip()
    if not raw:
        return False

    ctx = get_chat_context(chat_id)
    if ctx is None:
        # Ensure chat context exists so natural confirmations can queue jobs safely.
        upsert_chat_context(chat_id=chat_id, user_id=user_id)

    # Confirmation handling.
    if is_confirmation(raw):
        result = approve_newest_pending_action(chat_id=chat_id, user_id=user_id)
        if not result.get("ok"):
            send_message(chat_id, result.get("message") or "Nothing to approve.")
        else:
            send_message(chat_id, result.get("message") or "Approved.")
        return True

    if is_rejection(raw):
        result = reject_newest_pending_action(chat_id=chat_id, user_id=user_id)
        if not result.get("ok"):
            send_message(chat_id, result.get("message") or "Nothing to cancel.")
        else:
            send_message(chat_id, result.get("message") or "Cancelled.")
        return True

    intent = parse_intent(raw)
    if intent is None:
        # Malformed JSON or invalid actions => execute nothing.
        send_message(chat_id, "I couldn't understand that request safely, so I did nothing.")
        return True

    if knowledge_get_item is None or knowledge_search_ranked is None or knowledge_list_newest is None:
        send_message(chat_id, "Knowledge platform is not available.")
        return True

    # list_recent is always read-only.
    if intent.actions == ["list_recent"]:
        uploads = list_uploads(5, chat_id=chat_id)
        items = knowledge_list_newest(5)
        lines: list[str] = []
        if uploads:
            lines.append("Recent uploads:")
            for row in uploads[:5]:
                lines.append(f"- upload #{row['id']}: {_safe_filename(str(row.get('original_name') or ''))}")
        if items:
            if lines:
                lines.append("")
            lines.append("Newest knowledge items:")
            for item in items[:5]:
                lines.append(f"- #{item['id']}: {_safe_filename(str(item.get('original_name') or ''))}")
        if not lines:
            lines.append("No recent uploads or knowledge items yet.")
        send_message(chat_id, "\n".join(lines))
        return True

    # Search.
    hits: list[dict[str, Any]] = []
    if intent.target.type == "search":
        query = str(intent.target.query or "").strip()
        if not query:
            send_message(chat_id, "What should I search for?")
            return True
        hits = knowledge_search_ranked(query, 10)
        if not hits:
            send_message(chat_id, "No matches.")
            return True

        # Limit visible output.
        send_message(chat_id, "Matches\n\n" + _format_search_hits(hits, 5))

        # Heuristic: update latest context to the most recent matching item.
        best = sorted(hits, key=lambda r: int(r.get("id") or 0), reverse=True)[0]
        upsert_chat_context(chat_id=chat_id, user_id=user_id, latest_knowledge_item_id=int(best["id"]))

        # If the only requested action was find, we're done.
        remaining = [a for a in intent.actions if a != "find"]
        if not remaining:
            return True

        # For follow-on actions like send_original/summarize, operate on best match.
        intent = Intent(
            target=TargetSpec(type="item_id", item_id=int(best["id"]), query=None),
            actions=remaining,
            explanation=intent.explanation,
            gold_requested=intent.gold_requested,
        )

    # Determine whether the user likely refers to an existing result artifact.
    # Only allow read-only "send_result" to resolve to the last artifact.
    # If the user is asking us to clean/organize/archive, we must operate on the
    # knowledge item and require confirmation.
    mutating_requested = any(a in intent.actions for a in ("organize", "clean", "archive"))
    prefer_artifact = ("send_result" in intent.actions) and (not mutating_requested)
    item_id, artifact_id, error = _resolve_target_item_id(intent, chat_id=chat_id, prefer_artifact=prefer_artifact)
    if error:
        send_message(chat_id, error)
        return True

    # Handle read-only send_result when artifact already exists.
    if artifact_id is not None:
        if knowledge_get_artifact is None:
            send_message(chat_id, "Knowledge artifacts are unavailable.")
            return True
        artifact = knowledge_get_artifact(int(artifact_id))
        if not artifact:
            send_message(chat_id, "Artifact not found.")
            return True
        stored = str(artifact.get("stored_path") or "")
        try:
            path = _validated_under_knowledge_root(stored)
        except Exception:
            send_message(chat_id, "Refused to access that artifact path.")
            return True

        if "send_result" in intent.actions:
            send_document(chat_id, path, f"Artifact #{artifact_id}: {_safe_filename(str(artifact.get('filename') or path.name))}")
            send_message(chat_id, "Sent.")
            return True

    # From here, we operate on a knowledge item.
    if item_id is None:
        send_message(chat_id, "I couldn't determine which file you meant.")
        return True

    item = knowledge_get_item(int(item_id))
    if not item:
        send_message(chat_id, "Knowledge item not found.")
        return True

    # Read-only operations.
    if any(a in intent.actions for a in ("inspect", "profile", "summarize", "send_original")) and not any(
        a in intent.actions for a in ("organize", "clean", "archive")
    ):
        # Track this as the latest item for future "this file" references.
        upsert_chat_context(chat_id=chat_id, user_id=user_id, latest_knowledge_item_id=int(item_id))

        # inspect/profile/summarize
        if "profile" in intent.actions:
            send_message(chat_id, _profile_item_text(item))
        if "inspect" in intent.actions:
            meta = str(item.get("metadata_json") or "")
            if meta:
                send_message(chat_id, f"Metadata (truncated):\n{meta[:2800]}")
            else:
                send_message(chat_id, "No metadata is available for this item yet.")
        if "summarize" in intent.actions:
            send_message(chat_id, _summarize_item(item))
        if "send_original" in intent.actions:
            try:
                path = _validated_under_knowledge_root(str(item.get("stored_path") or ""))
            except Exception:
                send_message(chat_id, "Refused to access that file path.")
                return True
            send_document(chat_id, path, f"Knowledge item #{item_id}: {_safe_filename(str(item.get('original_name') or path.name))}")
            send_message(chat_id, "Sent.")
        return True

    # Mutating actions require confirmation.
    requires = [a for a in intent.actions if a in {"organize", "clean", "archive"}]
    if not requires:
        # Nothing actionable.
        return False

    ext = str(item.get("extension") or "").lower().lstrip(".")
    can_clean = ext in {"csv", "tsv", "xlsx", "xls", "xlsm"}

    if "clean" in requires and not can_clean:
        send_message(chat_id, "I can only clean CSV and Excel files.")
        return True

    # For mutating actions, treat this item as the latest context.
    upsert_chat_context(chat_id=chat_id, user_id=user_id, latest_knowledge_item_id=int(item_id))

    # Build a single bundled action for the whole request.
    from organizer import suggest_destination  # type: ignore

    destination_key = suggest_destination(item) if "organize" in requires else None

    bundle = {
        "version": 1,
        "knowledge_item_id": int(item_id),
        "do_organize": "organize" in requires,
        "destination_key": destination_key,
        "do_clean": "clean" in requires,
        "clean_operations": DEFAULT_CLEAN_OPERATIONS if "clean" in requires else [],
        "do_archive": "archive" in requires,
        "send_original": "send_original" in intent.actions,
        "send_result": "send_result" in intent.actions or ("clean" in requires),
        "gold_requested": bool(intent.gold_requested),
    }

    action_key = "bundle:" + json.dumps(bundle, sort_keys=True, ensure_ascii=False)

    steps: list[str] = []
    if bundle["do_organize"]:
        steps.append("Organize a copy")
    if bundle["do_clean"]:
        steps.append("Clean the spreadsheet")
        steps.append("Save the cleaned artifact")
    if bundle["do_archive"]:
        steps.append("Archive the original")
    if bundle["send_original"]:
        steps.append("Send the original")
    if bundle["send_result"]:
        steps.append("Send the result")

    name = _safe_filename(str(item.get("original_name") or ""))

    explanation_lines: list[str] = []
    if bundle["gold_requested"]:
        explanation_lines.append("The medallion data lake is not installed, so I will create the final cleaned artifact instead.")

    plan_lines = [f"I found {name}.", "", "I will:"]
    for idx, step in enumerate(steps, start=1):
        plan_lines.append(f"{idx}. {step}")
    if explanation_lines:
        plan_lines.append("")
        plan_lines.extend(explanation_lines)
    plan_lines.append("")
    plan_lines.append("Reply yes to continue or no to cancel.")

    # Store as a standard pending action, but don't show the approval code.
    from state_store import create_action  # local import to avoid cycles

    code = secrets.token_hex(3).upper()
    create_action(
        code=code,
        action_key=action_key,
        description=f"Natural-language request for knowledge item #{item_id}: {', '.join(requires)}",
        chat_id=chat_id,
        ttl_minutes=10,
    )

    # If multiple pending actions exist, the newest will be approved/rejected.
    send_message(chat_id, "\n".join(plan_lines))
    return True
