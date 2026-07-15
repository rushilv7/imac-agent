from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


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
        )

    discovered = shutil.which("hermes")
    if discovered:
        return discovered

    common_candidates = (
        Path.home() / ".local" / "bin" / "hermes",
        Path.home() / "bin" / "hermes",
    )
    for path in common_candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)

    raise HermesBridgeError(
        "Hermes executable was not found. Set HERMES_BIN in "
        "/home/rushil/.config/imac-bot/env to the output of `command -v hermes`."
    )


def _ops_get(path: str) -> dict[str, Any]:
    request = urllib.request.Request(
        OPS_BASE_URL + path,
        headers={"Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        return {"error": f"Could not read {path}: {type(exc).__name__}"}


def _run_read_only_script(path: Path) -> str:
    if not path.is_file():
        return f"ERROR: approved script not found: {path.name}"

    try:
        result = subprocess.run(
            [str(path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: {path.name} timed out"
    except OSError as exc:
        return f"ERROR: could not run {path.name}: {type(exc).__name__}"

    output = result.stdout.strip()
    if result.returncode != 0:
        return (
            f"ERROR: {path.name} exited with code {result.returncode}\n"
            f"{output[:4000]}"
        )

    return output[:6000]


def build_server_snapshot() -> str:
    sections: list[str] = []

    endpoints = (
        ("HEALTH", "/health"),
        ("STATUS", "/status"),
        ("SERVICES", "/services"),
        ("IMAC-AGENT REPOSITORY", "/projects/imac-agent"),
    )

    for title, path in endpoints:
        data = _ops_get(path)
        sections.append(
            f"===== {title} =====\n"
            + json.dumps(data, indent=2, sort_keys=True)
        )

    for script in READ_ONLY_SCRIPTS:
        sections.append(
            f"===== APPROVED SCRIPT: {script.name} =====\n"
            + _run_read_only_script(script)
        )

    return "\n\n".join(sections)


def ask_hermes(question: str) -> str:
    clean_question = question.strip()
    if not clean_question:
        raise HermesBridgeError("Ask a question after /ask.")
    if len(clean_question) > MAX_QUESTION_CHARS:
        raise HermesBridgeError(
            f"Question is too long. Maximum: {MAX_QUESTION_CHARS} characters."
        )

    hermes_bin = _resolve_hermes_bin()
    snapshot = build_server_snapshot()

    prompt = f"""You are Hermes answering Rushil through his private Telegram operations bot.

This invocation is READ-ONLY consultation mode.

Rules:
- Do not modify files, services, Git state, configuration, networking, firewall rules, packages, or system state.
- Do not request or reveal secrets, tokens, keys, passwords, or environment-file contents.
- Treat the server snapshot below as the authoritative local context for this request.
- You may use only the tools provided by the Hermes `safe` toolset.
- If the snapshot is insufficient, state the exact additional read-only check that would be useful.
- Be concise, practical, and explicit about uncertainty.
- Do not claim that you changed anything.

Rushil's question:
{clean_question}

Current read-only server snapshot:
{snapshot}
"""

    # Do not pass Telegram credentials into the Hermes child process.
    child_env = os.environ.copy()
    child_env.pop("TELEGRAM_BOT_TOKEN", None)
    child_env.pop("TELEGRAM_ALLOWED_USER_ID", None)

    try:
        result = subprocess.run(
            [
                hermes_bin,
                "chat",
                "-q",
                prompt,
                "-Q",
                "--toolsets",
                "safe",
            ],
            cwd=REPO_ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=HERMES_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HermesBridgeError(
            f"Hermes timed out after {HERMES_TIMEOUT_SECONDS} seconds."
        ) from exc
    except OSError as exc:
        raise HermesBridgeError(
            f"Could not start Hermes: {type(exc).__name__}"
        ) from exc

    if result.returncode != 0:
        local_error = result.stderr.strip() or result.stdout.strip()
        raise HermesBridgeError(
            f"Hermes exited with code {result.returncode}. "
            f"{local_error[:800]}"
        )

    lines = result.stdout.strip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].startswith("session_id:"):
        lines.pop()

    response = "\n".join(lines).strip()
    if not response:
        raise HermesBridgeError("Hermes returned an empty response.")

    if len(response) > MAX_RESPONSE_CHARS:
        response = (
            response[:MAX_RESPONSE_CHARS]
            + "\n\n[Response truncated by the Telegram bridge.]"
        )

    return response
