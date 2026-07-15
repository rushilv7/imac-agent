#!/usr/bin/env bash
set -euo pipefail

echo "Restarting approved service: imac-ops.service"

systemctl --user restart imac-ops.service
sleep 2

echo
echo "===== SERVICE STATE ====="
systemctl --user is-active imac-ops.service

echo
echo "===== API HEALTH ====="
curl --fail --silent http://127.0.0.1:8787/health
echo
