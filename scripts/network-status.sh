#!/usr/bin/env bash

echo "===== HOSTNAME ====="
hostname
echo

echo "===== IP ADDRESSES ====="
hostname -I
echo

echo "===== DEFAULT ROUTE ====="
ip route | grep default
echo

echo "===== SSH ====="
systemctl is-active ssh
echo

echo "===== TAILSCALE ====="
systemctl is-active tailscaled
tailscale status
