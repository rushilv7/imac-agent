#!/usr/bin/env bash

SERVICES=(
  ssh
  tailscaled
)

echo "===== SERVICE STATUS ====="

for service in "${SERVICES[@]}"; do
  echo
  echo "--- $service ---"
  systemctl is-active "$service"
  systemctl is-enabled "$service"
done

echo
echo "===== FAILED SERVICES ====="
systemctl --failed --no-pager
