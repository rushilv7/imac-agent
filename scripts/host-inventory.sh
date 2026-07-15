#!/usr/bin/env bash
set -u

section() {
  echo
  echo "===== $1 ====="
}

section "IDENTITY"
hostnamectl 2>/dev/null || hostname
id

section "OS"
cat /etc/os-release

section "TIME"
timedatectl

section "HARDWARE"
uname -a
free -h

section "DISKS"
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL

section "MOUNTS"
findmnt -rno TARGET,SOURCE,FSTYPE,OPTIONS

section "NETWORK"
ip -br addr
echo
ip route

section "LISTENING PORTS"
ss -tulpn

section "CORE SERVICES"
for service in ssh tailscaled unattended-upgrades; do
  echo "--- $service ---"
  printf "active: "
  systemctl is-active "$service" 2>/dev/null || true
  printf "enabled: "
  systemctl is-enabled "$service" 2>/dev/null || true
done

section "FAILED SERVICES"
systemctl --failed --no-pager

section "USER SERVICES"
systemctl --user list-unit-files --state=enabled --no-pager

section "LINGER"
loginctl show-user "$USER" -p Linger

section "TAILSCALE"
tailscale status 2>/dev/null || echo "Tailscale unavailable"

section "FIREWALL"
sudo -n ufw status verbose 2>/dev/null || \
  echo "UFW status requires sudo"

section "AUTOMATIC REBOOT CONFIG"
grep -R "Automatic-Reboot" \
  /etc/apt/apt.conf.d/50unattended-upgrades 2>/dev/null || true

section "RECENT ERRORS"
journalctl -b --priority=err --no-pager -n 50
