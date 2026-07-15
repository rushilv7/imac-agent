#!/usr/bin/env bash
set -euo pipefail

echo "===== SERVICE ====="
systemctl --user status imac-ops.service --no-pager

echo
echo "===== API HEALTH ====="
curl --fail --silent http://127.0.0.1:8787/health
echo
