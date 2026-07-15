#!/usr/bin/env bash
set -euo pipefail

echo "Restarting approved service: imac-bot.service"

systemctl --user restart imac-bot.service
sleep 3

echo
echo "===== SERVICE STATE ====="
systemctl --user is-active imac-bot.service

echo
echo "===== RECENT LOGS ====="
journalctl --user -u imac-bot.service -n 20 --no-pager
