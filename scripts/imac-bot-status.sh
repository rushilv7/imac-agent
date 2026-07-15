#!/usr/bin/env bash
set -euo pipefail

echo "===== SERVICE ====="
systemctl --user status imac-bot.service --no-pager

echo
echo "===== RECENT LOGS ====="
journalctl --user -u imac-bot.service -n 20 --no-pager
