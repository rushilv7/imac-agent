#!/usr/bin/env bash
set -euo pipefail

ALLOWED_SERVICES=(
  "hermes-agent"
  "telegram-bot"
  "portfolio-api"
)

if [ $# -ne 1 ]; then
  echo "Usage: $0 <service-name>"
  exit 1
fi

SERVICE="$1"

for allowed in "${ALLOWED_SERVICES[@]}"; do
  if [ "$SERVICE" = "$allowed" ]; then
    echo "Restarting approved service: $SERVICE"
    sudo systemctl restart "$SERVICE"
    systemctl status "$SERVICE" --no-pager
    exit 0
  fi
done

echo "ERROR: Service '$SERVICE' is not approved."
exit 1
