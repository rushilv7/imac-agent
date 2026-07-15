#!/usr/bin/env bash
set -euo pipefail

echo "===== FIREWALL ====="
sudo ufw status verbose

echo
echo "===== FIREWALL RULES ====="
sudo ufw status numbered

echo
echo "===== POWER TARGETS ====="
for unit in \
  sleep.target \
  suspend.target \
  hibernate.target \
  hybrid-sleep.target \
  suspend-then-hibernate.target
do
  echo "$unit: $(systemctl is-enabled "$unit" 2>/dev/null || true)"
done

echo
echo "===== AUTOMATIC REBOOT ====="
apt-config dump | grep -i 'Unattended-Upgrade::Automatic-Reboot'
