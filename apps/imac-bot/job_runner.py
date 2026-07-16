from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Callable

from hermes_bridge import HermesBridgeError, ask_hermes
from state_store import (
    complete_job,
    fail_job,
    get_job,
    list_queued_job_ids,
    mark_action_finished,
    mark_job_running,
)

REPO_ROOT = Path("/home/rushil/projects/imac-agent")
POLL_SECONDS = 1.0

ACTION_SCRIPTS = {
    "restart:imac-demo": REPO_ROOT / "scripts" / "imac-demo-restart.sh",
    "restart:imac-ops": REPO_ROOT / "scripts" / "imac-ops-restart.sh",
}


class JobRunner:
    def __init__(self, notify: Callable[[int, str], None]) -> None:
        self.notify = notify
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
                result = self._run_action(str(job["payload"]))
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

    def _run_action(self, payload: str) -> str:
        data = json.loads(payload)
        action_key = str(data["action_key"])
        action_id = int(data["action_id"])
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

    @staticmethod
    def _maybe_mark_action(job: dict, *, succeeded: bool) -> None:
        if job.get("kind") != "action":
            return
        try:
            payload = json.loads(str(job["payload"]))
            mark_action_finished(int(payload["action_id"]), succeeded=succeeded)
        except Exception:
            pass
