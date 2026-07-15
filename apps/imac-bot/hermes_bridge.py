from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from upload_context import build_upload_context


REPO_ROOT = Path("/home/rushil/projects/imac-agent")
OPS_BASE_URL = "http://127.0.0.1:8787"
MAX_QUESTION_CHARS = 2000
MAX_RESPONSE_CHARS = 12000
HERMES_TIMEOUT_SECONDS = 300

# Only scripts already designated as read-only in AGENTS.md.
READ_ONLY_SCRIPTS = (
    REPO_ROOT / "scripts" / "server-status.sh",
    REPO_ROOT / "scripts" / "check-services.sh",
)


class HermesBridgeError(RuntimeError):
    """Expected failure while collecting context or invoking Hermes."""


def _resolve_hermes_bin() -> str:
    configured = os.environ.get("HERMES_BIN", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        raise HermesBridgeError(
            "HERMES_BIN is configured but is not an executable file."
