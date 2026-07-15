from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_ID_RAW = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
OPS_BASE_URL = "http://127.0.0.1:8787"

if not BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN is not configured")

if not ALLOWED_USER_ID_RAW.isdigit():
    raise SystemExit(
        "TELEGRAM_ALLOWED_USER_ID must be a numeric Telegram user ID"
    )

ALLOWED_USER_ID = int(ALLOWED_USER_ID_RAW)
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


class BotError(RuntimeError):
    """Expected bot/API error."""


def telegram_request(
    method: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 15,
) -> Any:
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
        try:
            error_data = json.loads(
                exc.read().decode("utf-8", errors="replace")
            )
            description = error_data.get(
                "description", "Unknown Telegram API error"
            )
        except Exception:
            description = "Unknown Telegram API error"
        raise BotError(
            f"Telegram HTTP {exc.code}: {description}"
        ) from None
    except urllib.error.URLError as exc:
        raise BotError(
            f"Telegram network error: {exc.reason}"
        ) from None

    if not data.get("ok"):
        raise BotError(
            data.get("description", "Telegram API request failed")
        )

    return data.get("result")


def ops_get(path: str) -> dict[str, Any]:
    request = urllib.request.Request(
        OPS_BASE_URL + path,
        headers={"Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise BotError(
            f"iMac Ops returned HTTP {exc.code}"
        ) from None
    except urllib.error.URLError as exc:
        raise BotError(
            f"iMac Ops unavailable: {exc.reason}"
        ) from None


def send_message(chat_id: int, text: str) -> None:
    chunks = [
        text[index:index + 3900]
        for index in range(0, len(text), 3900)
    ] or [""]

    for chunk in chunks:
        telegram_request(
            "sendMessage",
            {"chat_id": chat_id, "text": chunk},
        )


def human_bytes(value: int | float) -> str:
    size = float(value)

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
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
        "Available commands:\n"
        "/health - Check bot and operations API\n"
        "/status - Show server resource status\n"
        "/services - Show managed services\n"
        "/repo - Show imac-agent Git status\n"
        "/help - Show available commands\n\n"
        "This bot is currently read-only."
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
        return (
            "Health: DEGRADED\n"
            "Telegram bot: online\n"
            "iMac Ops: unavailable\n"
            f"Reason: {exc}"
        )


def command_status() -> str:
    data = ops_get("/status")
    memory = data.get("memory", {})
    disk = data.get("disk", {})

    disk_total = float(disk.get("total", 0) or 0)
    disk_used = float(disk.get("used", 0) or 0)
    disk_percent = (
        (disk_used / disk_total) * 100
        if disk_total > 0
        else 0
    )

    return (
        "Server Status\n\n"
        f"Hostname: {data.get('hostname', 'unknown')}\n"
        f"Uptime: {human_uptime(data.get('uptime_seconds', 0))}\n"
        f"CPU: {data.get('cpu_percent', 'unknown')}%\n"
        f"Memory used: {memory.get('percent', 'unknown')}%\n"
        f"Memory available: {human_bytes(memory.get('available', 0))}\n"
        f"Disk used: {disk_percent:.1f}%\n"
        f"Disk free: {human_bytes(disk.get('free', 0))}"
    )


def command_services() -> str:
    services = ops_get("/services")
    lines = ["Managed Services", ""]
    for name, state in sorted(services.items()):
        lines.append(f"{name}: {state}")
    return "\n".join(lines)


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

    text = message.get("text")
    if not isinstance(text, str):
        send_message(
            chat_id,
            "Only text commands are supported. Use /help.",
        )
        return

    command = text.strip().split(maxsplit=1)[0].lower()
    command = command.split("@", maxsplit=1)[0]

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
        else:
            response = (
                "Unknown command.\n\n"
                "Use /help to see available commands."
            )
    except BotError as exc:
        response = f"Operation failed:\n{exc}"

    send_message(chat_id, response)


def main() -> None:
    telegram_request(
        "deleteWebhook",
        {"drop_pending_updates": False},
    )

    bot = telegram_request("getMe")
    print(
        "Connected to Telegram as "
        f"@{bot.get('username', 'unknown')}",
        flush=True,
    )

    offset: int | None = None

    while True:
        try:
            payload: dict[str, Any] = {
                "timeout": 50,
                "allowed_updates": ["message"],
            }

            if offset is not None:
                payload["offset"] = offset

            updates = telegram_request(
                "getUpdates",
                payload,
                timeout=60,
            )

            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1

                message = update.get("message")
                if isinstance(message, dict):
                    handle_message(message)

        except BotError as exc:
            print(
                f"Bot error: {exc}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(5)
        except Exception as exc:
            print(
                f"Unexpected error: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(5)


if __name__ == "__main__":
    main()
