from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from file_inbox import save_document
from job_runner import JobRunner
from state_store import (
    approve_action,
    add_active_upload,
    attach_action_job,
    cancel_job,
    clear_active_uploads,
    create_action,
    create_job,
    get_upload,
    get_job,
    initialize,
    list_active_uploads,
    list_jobs,
    list_pending_actions,
    list_uploads,
    reject_action,
    set_active_uploads,
)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_ID_RAW = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
OPS_BASE_URL = "http://127.0.0.1:8787"

if not BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN is not configured")
if not ALLOWED_USER_ID_RAW.isdigit():
    raise SystemExit("TELEGRAM_ALLOWED_USER_ID must be a numeric Telegram user ID")

ALLOWED_USER_ID = int(ALLOWED_USER_ID_RAW)
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

ALLOWED_RESTARTS = {
    "imac-demo": "restart:imac-demo",
    "imac-ops": "restart:imac-ops",
    "imac-bot": "restart:imac-bot",
}


class BotError(RuntimeError):
    pass


def telegram_request(method: str, payload: dict[str, Any] | None = None, *, timeout: int = 15) -> Any:
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        f"{TELEGRAM_API}/{method}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise BotError(f"Telegram returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise BotError(f"Telegram network error: {exc.reason}") from None
    if not data.get("ok"):
        raise BotError(data.get("description", "Telegram API request failed"))
    return data.get("result")


def ops_get(path: str) -> dict[str, Any]:
    request = urllib.request.Request(OPS_BASE_URL + path, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise BotError(f"iMac Ops returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise BotError(f"iMac Ops unavailable: {exc.reason}") from None


def send_message(chat_id: int, text: str) -> None:
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
    for chunk in chunks:
        telegram_request("sendMessage", {"chat_id": chat_id, "text": chunk})


def human_bytes(value: int | float) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def human_uptime(seconds: int | float) -> str:
    seconds = int(seconds)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def help_text() -> str:
    return (
        "Rushil iMac Ops\n\n"
        "Read-only:\n"
        "/health\n/status\n/services\n/repo\n\n"
        "Hermes background jobs:\n"
        "/ask <question>\n/jobs\n/job <id>\n/cancel <id>\n\n"
        "Confirmation-gated actions:\n"
        "/propose_restart <imac-demo|imac-ops|imac-bot>\n"
        "/actions\n/approve <code>\n/reject <code>\n\n"
        "Telegram file inbox:\n"
        "Send a document directly to this private chat.\n"
        "/uploads\n/file\n/files\n/use_file <id>\n/add_file <id>\n/forget_file\n\n"
        "Hermes remains read-only. Only allowlisted action scripts run after explicit approval."
    )


def command_health() -> str:
    try:
        data = ops_get("/health")
        return (
            "Health: OK\n"
            "Telegram bot: online\n"
            f"iMac Ops: {data.get('status', 'unknown')}\n"
            f"Hostname: {data.get('hostname', 'unknown')}"
        )
    except BotError as exc:
        return f"Health: DEGRADED\nTelegram bot: online\niMac Ops: unavailable\nReason: {exc}"


def command_status() -> str:
    data = ops_get("/status")
    memory = data.get("memory", {})
    disk = data.get("disk", {})
    total = float(disk.get("total", 0) or 0)
    used = float(disk.get("used", 0) or 0)
    percent = (used / total * 100) if total else 0
    return (
        "Server Status\n\n"
        f"Hostname: {data.get('hostname', 'unknown')}\n"
        f"Uptime: {human_uptime(data.get('uptime_seconds', 0))}\n"
        f"CPU: {data.get('cpu_percent', 'unknown')}%\n"
        f"Memory used: {memory.get('percent', 'unknown')}%\n"
        f"Memory available: {human_bytes(memory.get('available', 0))}\n"
        f"Disk used: {percent:.1f}%\n"
        f"Disk free: {human_bytes(disk.get('free', 0))}"
    )


def command_services() -> str:
    services = ops_get("/services")
    return "Managed Services\n\n" + "\n".join(
        f"{name}: {state}" for name, state in sorted(services.items())
    )


def command_repo() -> str:
    data = ops_get("/projects/imac-agent")
    lines = [
        "imac-agent Repository",
        "",
        f"Branch: {data.get('branch', 'unknown')}",
        f"Clean: {'yes' if data.get('clean') else 'no'}",
        f"Latest: {data.get('latest_commit', 'unknown')}",
    ]
    changes = data.get("changes", [])
    if changes:
        lines.extend(["", "Changes:"])
        lines.extend(str(change) for change in changes[:20])
    return "\n".join(lines)


def format_job(job: dict[str, Any]) -> str:
    lines = [
        f"Job #{job['id']}",
        f"Type: {job['kind']}",
        f"Status: {job['status']}",
        f"Created: {job['created_at']}",
    ]
    if job.get("result"):
        lines.extend(["", str(job["result"])[:3000]])
    if job.get("error"):
        lines.extend(["", f"Error: {job['error']}"])
    return "\n".join(lines)


def queue_hermes(chat_id: int, question: str) -> str:
    if not question.strip():
        return "Usage: /ask <question>"
    job_id = create_job("hermes", chat_id, question.strip())
    return f"Hermes job #{job_id} queued.\nUse /job {job_id} or /jobs to check it."


def list_job_text() -> str:
    jobs = list_jobs(10)
    if not jobs:
        return "No jobs yet."
    return "Recent jobs\n\n" + "\n".join(
        f"#{job['id']}  {job['kind']}  {job['status']}" for job in jobs
    )


def propose_restart(chat_id: int, service_name: str) -> str:
    normalized = service_name.strip().removesuffix(".service")
    action_key = ALLOWED_RESTARTS.get(normalized)
    if not action_key:
        allowed = ", ".join(ALLOWED_RESTARTS)
        return f"Not allowlisted. Allowed services: {allowed}"
    code = secrets.token_hex(3).upper()
    description = f"Restart {normalized}.service using its approved repository script."
    create_action(
        code=code,
        action_key=action_key,
        description=description,
        chat_id=chat_id,
        ttl_minutes=10,
    )
    return (
        "Action proposed. No change has been made.\n\n"
        f"{description}\n"
        f"Approval code: {code}\n"
        "Expires in 10 minutes.\n\n"
        f"Run /approve {code} to execute or /reject {code} to reject."
    )


def approve_code(chat_id: int, code: str) -> str:
    result = approve_action(code, chat_id)
    if not result.get("ok"):
        return f"Approval failed: {result.get('reason', 'unknown')}"
    action = result["action"]
    payload = json.dumps({"action_id": action["id"], "action_key": action["action_key"]})
    job_id = create_job("action", chat_id, payload)
    attach_action_job(int(action["id"]), job_id)
    return f"Approved. Action queued as job #{job_id}."


def list_actions_text(chat_id: int) -> str:
    actions = list_pending_actions(chat_id)
    if not actions:
        return "No pending actions."
    return "Pending actions\n\n" + "\n".join(
        f"{a['code']} — {a['description']}" for a in actions
    )


def list_uploads_text() -> str:
    uploads = list_uploads(10)
    if not uploads:
        return "No Telegram uploads yet."
    return "Recent uploads\n\n" + "\n".join(
        f"#{u['id']} {u['original_name']} ({human_bytes(u['size_bytes'])})"
        for u in uploads
    )


def list_active_files_text(chat_id: int) -> str:
    active = list_active_uploads(chat_id, 10)
    if not active:
        return "No active files for this chat.\n\nUse /use_file <id> or /add_file <id>."
    lines = ["Active files (sent to Hermes automatically)\n"]
    for row in active:
        lines.append(
            f"{row['position']}.  #{row['upload_id']} {row['original_name']} ({human_bytes(row['size_bytes'])})"
        )
    lines.append("\nUse /forget_file to clear.")
    return "\n".join(lines)


def set_active_file(chat_id: int, argument: str) -> str:
    if not argument or not argument.lstrip("#").isdigit():
        return "Usage: /use_file <id>"
    upload_id = int(argument.lstrip("#"))
    upload = get_upload(upload_id)
    if not upload:
        return "Upload not found. Use /uploads to list."
    set_active_uploads(chat_id, [upload_id])
    return f"Active file set to upload #{upload_id}: {upload['original_name']}"


def add_active_file(chat_id: int, argument: str) -> str:
    if not argument or not argument.lstrip("#").isdigit():
        return "Usage: /add_file <id>"
    upload_id = int(argument.lstrip("#"))
    upload = get_upload(upload_id)
    if not upload:
        return "Upload not found. Use /uploads to list."
    if not add_active_upload(chat_id, upload_id):
        return f"Upload #{upload_id} is already active."
    return f"Added active file upload #{upload_id}: {upload['original_name']}"


def forget_active_files(chat_id: int) -> str:
    clear_active_uploads(chat_id)
    return "Cleared active file context for this chat."


def handle_document(message: dict[str, Any], chat_id: int) -> None:
    document = message.get("document")
    if not isinstance(document, dict):
        return
    try:
        saved = save_document(
            document,
            chat_id=chat_id,
            telegram_request=telegram_request,
            bot_token=BOT_TOKEN,
        )
        send_message(
            chat_id,
            "File saved to the private Telegram inbox.\n\n"
            f"Upload ID: #{saved['upload_id']}\n"
            f"Name: {saved['original_name']}\n"
            f"Size: {human_bytes(saved['size_bytes'])}\n"
            f"Type: {saved['mime_type']}\n\n"
            "This upload is now the active file for this chat.\n"
            "Use /file to confirm or /add_file <id> to add more.",
        )
    except Exception as exc:
        send_message(chat_id, f"File upload failed: {exc}")


def handle_message(message: dict[str, Any]) -> None:
    sender = message.get("from", {})
    chat = message.get("chat", {})
    sender_id = sender.get("id")
    chat_id = chat.get("id")
    chat_type = chat.get("type")

    if sender_id != ALLOWED_USER_ID:
        print("Ignored unauthorized Telegram user", flush=True)
        return
    if chat_type != "private":
        print("Ignored non-private Telegram chat", flush=True)
        return
    if not isinstance(chat_id, int):
        return

    if isinstance(message.get("document"), dict):
        handle_document(message, chat_id)
        return

    text = message.get("text")
    if not isinstance(text, str):
        send_message(chat_id, "Send a text command or a document. Use /help.")
        return

    parts = text.strip().split(maxsplit=1)
    raw_command = parts[0].lower() if parts else ""
    command = raw_command.split("@", maxsplit=1)[0]
    argument = parts[1].strip() if len(parts) > 1 else ""

    try:
        if command in {"/start", "/help"}:
            response = help_text()
        elif command == "/health":
            response = command_health()
        elif command == "/status":
            response = command_status()
        elif command == "/services":
            response = command_services()
        elif command == "/repo":
            response = command_repo()
        elif command == "/ask":
            response = queue_hermes(chat_id, argument)
        elif command == "/jobs":
            response = list_job_text()
        elif command == "/job":
            response = "Usage: /job <id>"
            if argument.isdigit():
                job = get_job(int(argument))
                response = format_job(job) if job else "Job not found."
        elif command == "/cancel":
            response = "Usage: /cancel <queued-job-id>"
            if argument.isdigit():
                response = "Queued job cancelled." if cancel_job(int(argument)) else "Job was not queued or was not found."
        elif command == "/propose_restart":
            response = propose_restart(chat_id, argument)
        elif command == "/actions":
            response = list_actions_text(chat_id)
        elif command == "/approve":
            response = approve_code(chat_id, argument) if argument else "Usage: /approve <code>"
        elif command == "/reject":
            if not argument:
                response = "Usage: /reject <code>"
            else:
                result = reject_action(argument, chat_id)
                response = "Action rejected." if result.get("ok") else f"Reject failed: {result.get('reason', 'unknown')}"
        elif command == "/uploads":
            response = list_uploads_text()
        elif command in {"/file", "/files"}:
            response = list_active_files_text(chat_id)
        elif command == "/use_file":
            response = set_active_file(chat_id, argument)
        elif command == "/add_file":
            response = add_active_file(chat_id, argument)
        elif command == "/forget_file":
            response = forget_active_files(chat_id)
        else:
            response = "Unknown command.\n\nUse /help to see available commands."
    except BotError as exc:
        response = f"Operation failed:\n{exc}"
    except Exception as exc:
        response = f"Request failed: {type(exc).__name__}: {exc}"

    send_message(chat_id, response)


def main() -> None:
    initialize()
    telegram_request("deleteWebhook", {"drop_pending_updates": False})
    bot = telegram_request("getMe")
    print(f"Connected to Telegram as @{bot.get('username', 'unknown')}", flush=True)

    runner = JobRunner(send_message)
    runner.start()

    offset: int | None = None
    while True:
        try:
            payload: dict[str, Any] = {"timeout": 50, "allowed_updates": ["message"]}
            if offset is not None:
                payload["offset"] = offset
            updates = telegram_request("getUpdates", payload, timeout=60)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                message = update.get("message")
                if isinstance(message, dict):
                    handle_message(message)
        except BotError as exc:
            print(f"Bot error: {exc}", file=sys.stderr, flush=True)
            time.sleep(5)
        except Exception as exc:
            print(f"Unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
