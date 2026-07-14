#!/usr/bin/env bash

echo "===== HOST ====="
hostname
date
echo

echo "===== UPTIME ====="
uptime
echo

echo "===== MEMORY ====="
free -h
echo

echo "===== DISK ====="
df -h
echo

echo "===== FAILED SERVICES ====="
systemctl --failed --no-pager
echo

echo "===== SSH ====="
systemctl is-active ssh
echo

echo "===== TAILSCALE ====="
systemctl is-active tailscaled
tailscale status
echo

echo "===== TOP MEMORY PROCESSES ====="
ps aux --sort=-%mem | head -10
