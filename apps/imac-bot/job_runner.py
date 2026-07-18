from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from hermes_bridge import HermesBridgeError, ask_hermes
from state_store import (
    complete_job,
    fail_job,
    get_chat_context,
    get_job,
    list_queued_job_ids,
    mark_action_finished,
    mark_job_running,
    upsert_chat_context,
)

REPO_ROOT = Path("/home/rushil/projects/imac-agent")
POLL_SECONDS = 1.0

ACTION_SCRIPTS = {
    "restart:imac-demo": REPO_ROOT / "scripts" / "imac-demo-restart.sh",
    "restart:imac-ops": REPO_ROOT / "scripts" / "imac-ops-restart.sh",
    "restart:imac-bot": REPO_ROOT / "scripts" / "imac-bot-restart.sh",
}

# Allow importing the Phase 1 knowledge modules without packaging.
import sys

KNOWLEDGE_DIR = REPO_ROOT / "apps" / "knowledge"
if str(KNOWLEDGE_DIR) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_DIR))

try:
    from config import KNOWLEDGE_ROOT as KNOWLEDGE_ROOT_PATH  # type: ignore
    from artifacts import get_artifact as knowledge_get_artifact  # type: ignore
    from registry import get as knowledge_get_item  # type: ignore
    from organizer import allowed_destination_keys as knowledge_allowed_destinations  # type: ignore
    from organizer import organize as knowledge_organize  # type: ignore
    from organizer import suggest_destination as knowledge_suggest_destination  # type: ignore
    from enrichment import enrich_item as knowledge_enrich_item  # type: ignore
    from enrichment import enrich_pending as knowledge_enrich_pending  # type: ignore
    from workflows import parse_operations as workflow_parse_operations  # type: ignore
    from workflows import run_workflow as workflow_run  # type: ignore
    from workflows import validate_operations as workflow_validate_operations  # type: ignore
except Exception:
    KNOWLEDGE_ROOT_PATH = None
    knowledge_get_artifact = None
    knowledge_get_item = None
    knowledge_allowed_destinations = None
    knowledge_organize = None
    knowledge_suggest_destination = None
    knowledge_enrich_item = None
    knowledge_enrich_pending = None
    workflow_parse_operations = None
    workflow_run = None
    workflow_validate_operations = None


class JobRunner:
    def __init__(
        self,
        notify: Callable[[int, str], None],
        send_document: Callable[[int, Path, str | None], None],
    ) -> None:
        self.notify = notify
        self.send_document = send_document
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            name="imac-bot-job-runner",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            processed = False
            for job_id in list_queued_job_ids():
                if self._stop.is_set():
                    break
                if not mark_job_running(job_id):
                    continue
                processed = True
                self._run(job_id)
            if not processed:
                self._stop.wait(POLL_SECONDS)

    def _run(self, job_id: int) -> None:
        job = get_job(job_id)
        if not job:
            return

        chat_id = int(job["chat_id"])
        kind = str(job["kind"])

        try:
            if kind == "hermes":
                result = ask_hermes(str(job["payload"]), chat_id=chat_id)
            elif kind == "action":
                result = self._run_action(str(job["payload"]), chat_id=chat_id)
            else:
                raise RuntimeError(f"Unsupported job kind: {kind}")

            complete_job(job_id, result)
            self.notify(chat_id, f"Job #{job_id} completed.\n\n{result}")
        except (HermesBridgeError, RuntimeError) as exc:
            fail_job(job_id, str(exc))
            self._maybe_mark_action(job, succeeded=False)
            self.notify(chat_id, f"Job #{job_id} failed.\n\n{exc}")
        except Exception as exc:
            fail_job(job_id, f"{type(exc).__name__}: {exc}")
            self._maybe_mark_action(job, succeeded=False)
            self.notify(chat_id, f"Job #{job_id} failed unexpectedly.")

    def _run_action(self, payload: str, *, chat_id: int) -> str:
        data = json.loads(payload)
        action_key = str(data["action_key"])
        action_id = int(data["action_id"])

        if action_key.startswith("bundle:"):
            try:
                result = self._run_bundle_action(action_id=action_id, chat_id=chat_id, action_key=action_key)
            except Exception:
                mark_action_finished(action_id, succeeded=False)
                raise
            mark_action_finished(action_id, succeeded=True)
            return result

        if action_key.startswith("organize:"):
            if knowledge_organize is None or knowledge_allowed_destinations is None:
                raise RuntimeError("Knowledge organizer is unavailable.")
            parts = action_key.split(":", 2)
            if len(parts) != 3:
                raise RuntimeError("Invalid organize action key.")
            _, item_id_raw, destination_key = parts
            if not item_id_raw.isdigit():
                raise RuntimeError("Invalid knowledge item id.")
            if destination_key not in set(knowledge_allowed_destinations()):
                raise RuntimeError("Destination key is not allowlisted.")

            result = knowledge_organize(int(item_id_raw), destination_key)
            mark_action_finished(action_id, succeeded=True)
            return json.dumps(result, indent=2, sort_keys=True)[:8000]

        if action_key.startswith("enrich:"):
            if knowledge_enrich_item is None:
                raise RuntimeError("Knowledge enrichment is unavailable.")
            parts = action_key.split(":", 1)
            if len(parts) != 2:
                raise RuntimeError("Invalid enrich action key.")
            item_id_raw = parts[1]
            if not item_id_raw.isdigit():
                raise RuntimeError("Invalid knowledge item id.")
            result = knowledge_enrich_item(int(item_id_raw))
            mark_action_finished(action_id, succeeded=True)
            return json.dumps(result, indent=2, sort_keys=True)[:8000]

        if action_key.startswith("enrich_pending:"):
            if knowledge_enrich_pending is None:
                raise RuntimeError("Knowledge enrichment is unavailable.")
            parts = action_key.split(":", 1)
            batch_raw = parts[1] if len(parts) == 2 else "10"
            batch = int(batch_raw) if batch_raw.isdigit() else 10
            batch = max(1, min(batch, 20))
            result = knowledge_enrich_pending(batch)
            mark_action_finished(action_id, succeeded=True)
            return json.dumps(result, indent=2, sort_keys=True)[:8000]

        if action_key.startswith("workflow:"):
            if workflow_run is None or workflow_parse_operations is None or workflow_validate_operations is None:
                raise RuntimeError("Workflow engine is unavailable.")
            # workflow:<item_id>:<op1,op2,...>
            parts = action_key.split(":", 2)
            if len(parts) != 3:
                raise RuntimeError("Invalid workflow action key.")
            _, item_id_raw, ops_raw = parts
            if not item_id_raw.isdigit():
                raise RuntimeError("Invalid knowledge item id.")
            ops = workflow_parse_operations(ops_raw)
            workflow_validate_operations(ops)
            report = workflow_run(knowledge_item_id=int(item_id_raw), operations=ops)
            mark_action_finished(action_id, succeeded=True)
            return json.dumps(report.__dict__, indent=2, sort_keys=True)[:8000]

        script = ACTION_SCRIPTS.get(action_key)
        if script is None:
            raise RuntimeError("Action is not allowlisted.")
        if not script.is_file():
            raise RuntimeError(f"Approved script is missing: {script.name}")

        result = subprocess.run(
            [str(script)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        output = (result.stdout or "").strip()
        if result.returncode != 0:
            error = (result.stderr or output or "approved script failed").strip()
            mark_action_finished(action_id, succeeded=False)
            raise RuntimeError(error[:3000])

        mark_action_finished(action_id, succeeded=True)
        return output[:8000] or "Approved action completed successfully."

    def _run_bundle_action(self, *, action_id: int, chat_id: int, action_key: str) -> str:
        if knowledge_get_item is None:
            raise RuntimeError("Knowledge registry is unavailable.")

        ctx = get_chat_context(chat_id)
        user_id = int(ctx.get("user_id") or 0) if ctx else 0

        try:
            bundle = json.loads(action_key[len("bundle:") :])
        except Exception as exc:
            raise RuntimeError("Invalid bundled action payload.") from exc

        if not isinstance(bundle, dict) or int(bundle.get("version") or 0) != 1:
            raise RuntimeError("Invalid bundled action payload.")

        item_id = bundle.get("knowledge_item_id")
        if not isinstance(item_id, int) or item_id <= 0:
            raise RuntimeError("Invalid knowledge item id.")

        item = knowledge_get_item(int(item_id))
        if not item:
            raise RuntimeError("Knowledge item not found.")

        name = str(item.get("original_name") or "(unnamed)")
        ext = str(item.get("extension") or "").lower().lstrip(".")

        do_organize = bool(bundle.get("do_organize"))
        do_clean = bool(bundle.get("do_clean"))
        do_archive = bool(bundle.get("do_archive"))
        send_original = bool(bundle.get("send_original"))
        send_result = bool(bundle.get("send_result"))
        gold_requested = bool(bundle.get("gold_requested"))

        milestones: list[str] = []

        # 1) Organize copy
        if do_organize:
            if knowledge_organize is None or knowledge_allowed_destinations is None:
                raise RuntimeError("Knowledge organizer is unavailable.")
            dest_key = str(bundle.get("destination_key") or "").strip()
            if not dest_key:
                if knowledge_suggest_destination is None:
                    raise RuntimeError("Knowledge organizer is unavailable.")
                dest_key = str(knowledge_suggest_destination(item))
            if dest_key not in set(knowledge_allowed_destinations()):
                raise RuntimeError("Destination key is not allowlisted.")
            _ = knowledge_organize(int(item_id), dest_key)
            milestones.append("organized")

        artifact_id: int | None = None
        workflow_report: dict[str, Any] | None = None

        # 2) Clean into artifact
        if do_clean:
            if workflow_run is None or workflow_validate_operations is None:
                raise RuntimeError("Workflow engine is unavailable.")
            if ext not in {"csv", "tsv", "xlsx", "xls", "xlsm"}:
                raise RuntimeError("Cleaning is supported only for CSV and Excel files.")
            ops = bundle.get("clean_operations")
            if not isinstance(ops, list) or not all(isinstance(x, str) for x in ops):
                raise RuntimeError("Invalid workflow operations.")
            operations = [str(x) for x in ops]
            workflow_validate_operations(operations)
            report = workflow_run(knowledge_item_id=int(item_id), operations=operations)
            artifact_id = int(getattr(report, "artifact_id"))
            workflow_report = getattr(report, "__dict__", {})
            upsert_chat_context(chat_id=int(chat_id), user_id=user_id, latest_artifact_id=artifact_id)
            milestones.append("cleaned")

        # 3) Send original
        if send_original:
            path = Path(str(item.get("stored_path") or "")).expanduser().resolve()
            self._validated_under_knowledge_root(path)
            self.send_document(chat_id, path, f"Original: {Path(name).name}")
            milestones.append("sent_original")

        # 4) Send result
        if send_result:
            if artifact_id is None:
                raise RuntimeError("No cleaned artifact is available to send.")
            if knowledge_get_artifact is None:
                raise RuntimeError("Artifact registry is unavailable.")
            artifact = knowledge_get_artifact(int(artifact_id))
            if not artifact:
                raise RuntimeError("Artifact not found.")
            a_path = Path(str(artifact.get("stored_path") or "")).expanduser().resolve()
            self._validated_under_knowledge_root(a_path)
            self.send_document(chat_id, a_path, f"Cleaned: {Path(str(artifact.get('filename') or a_path.name)).name}")
            milestones.append("sent_result")

        # 5) Archive
        if do_archive:
            from natural_language import archive_path  # local import

            src = Path(str(item.get("stored_path") or "")).expanduser().resolve()
            self._validated_under_knowledge_root(src)
            archive_path(src)
            milestones.append("archived")

        lines: list[str] = []
        lines.append(f"Finished processing {Path(name).name}.")
        lines.append("")
        if gold_requested:
            lines.append("The medallion data lake is not installed, so I created the final cleaned artifact instead.")
            lines.append("")
        lines.append("- Original preserved")
        if "organized" in milestones:
            lines.append("- Organized copy created")
        if workflow_report:
            removed = workflow_report.get("duplicate_rows_removed")
            if isinstance(removed, int):
                lines.append(f"- {removed} duplicate rows removed")
            ops_used = workflow_report.get("operations")
            if isinstance(ops_used, list) and ops_used:
                lines.append("- Operations: " + ", ".join(str(x) for x in ops_used))
        if artifact_id is not None:
            lines.append(f"- Cleaned artifact registered as #{artifact_id}")
        if "sent_result" in milestones:
            lines.append("\nI sent the cleaned file.")
        elif "sent_original" in milestones:
            lines.append("\nI sent the original file.")

        return "\n".join(lines)[:8000]

    @staticmethod
    def _validated_under_knowledge_root(path: Path) -> None:
        if KNOWLEDGE_ROOT_PATH is None:
            raise RuntimeError("Knowledge platform is unavailable.")
        resolved = path.expanduser().resolve()
        root = Path(KNOWLEDGE_ROOT_PATH).expanduser().resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("Refused to access path outside the knowledge root.") from exc
        if not resolved.is_file():
            raise RuntimeError("Requested file is missing.")

    @staticmethod
    def _maybe_mark_action(job: dict, *, succeeded: bool) -> None:
        if job.get("kind") != "action":
            return
        try:
            payload = json.loads(str(job["payload"]))
            mark_action_finished(int(payload["action_id"]), succeeded=succeeded)
        except Exception:
            pass
