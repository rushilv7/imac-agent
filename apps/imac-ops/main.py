from __future__ import annotations

import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import FastAPI, HTTPException

app = FastAPI(
    title="iMac Ops",
    version="0.1.0",
)

REPO = Path.home() / "projects" / "imac-agent"

ALLOWED_USER_SERVICES = [
    "imac-demo.service",
    "imac-ops.service",
    "imac-bot.service",
]


def run_command(command: list[str]) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Command failed")

    return result.stdout.strip()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "hostname": socket.gethostname(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/status")
def status() -> dict:
    disk = shutil.disk_usage("/")

    return {
        "hostname": socket.gethostname(),
        "uptime_seconds": int(
            datetime.now().timestamp() - psutil.boot_time()
        ),
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "memory": {
            "total": psutil.virtual_memory().total,
            "available": psutil.virtual_memory().available,
            "percent": psutil.virtual_memory().percent,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
        },
    }


@app.get("/services")
def services() -> dict:
    results = {}

    for service in ALLOWED_USER_SERVICES:
        try:
            state = run_command(
                ["systemctl", "--user", "is-active", service]
            )
        except RuntimeError:
            state = "inactive"

        results[service] = state

    return results


@app.get("/projects/imac-agent")
def project_status() -> dict:
    if not (REPO / ".git").exists():
        raise HTTPException(
            status_code=500,
            detail="imac-agent repository not found",
        )

    try:
        branch = run_command(
            ["git", "-C", str(REPO), "branch", "--show-current"]
        )
        commit = run_command(
            ["git", "-C", str(REPO), "log", "-1", "--oneline"]
        )
        changes = run_command(
            ["git", "-C", str(REPO), "status", "--short"]
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "branch": branch,
        "latest_commit": commit,
        "clean": changes == "",
        "changes": changes.splitlines() if changes else [],
    }
