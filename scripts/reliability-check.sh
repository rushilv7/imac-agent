#!/usr/bin/env bash

echo "===== BOOT ====="
uptime
echo

echo "===== FAILED SYSTEMD UNITS ====="
systemctl --failed --no-pager
echo

echo "===== SSH ====="
systemctl is-active ssh
systemctl is-enabled ssh
echo

echo "===== TAILSCALE ====="
systemctl is-active tailscaled
systemctl is-enabled tailscaled
tailscale status
echo

echo "===== FIREWALL ====="
sudo -n ufw status verbose 2>/dev/null || echo "UFW status requires sudo"
echo

echo "===== AUTOMATIC UPDATES ====="
systemctl is-active unattended-upgrades
systemctl is-enabled unattended-upgrades
echo

echo "===== TIME SYNCHRONIZATION ====="
timedatectl
echo

echo "===== DISK ====="
df -h /
echo

echo "===== MEMORY ====="
free -h
echo

echo "===== RECENT BOOT ERRORS ====="
journalctl -b --priority=err --no-pager -n 50
