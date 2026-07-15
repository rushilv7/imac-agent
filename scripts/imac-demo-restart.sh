#!/usr/bin/env bash
set -euo pipefail

echo "Restarting approved service: imac-demo.service"

systemctl --user restart imac-demo.service

sleep 2

systemctl --user status imac-demo.service --no-pager
