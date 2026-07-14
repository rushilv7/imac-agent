#!/usr/bin/env bash
set -euo pipefail

echo "=== Updating Ubuntu ==="
sudo apt update
sudo apt full-upgrade -y

echo "=== Installing base packages ==="
sudo apt install -y \
  openssh-server \
  curl \
  git \
  rsync \
  tmux \
  htop \
  jq \
  unzip \
  ca-certificates \
  ufw \
  unattended-upgrades \
  python3 \
  python3-venv \
  python3-pip \
  build-essential

echo "=== Enabling SSH ==="
sudo systemctl enable --now ssh

echo "=== Preventing sleep/suspend ==="
sudo systemctl mask \
  sleep.target \
  suspend.target \
  hibernate.target \
  hybrid-sleep.target

echo "=== Creating server directories ==="
mkdir -p \
  "$HOME/agents" \
  "$HOME/projects" \
  "$HOME/services" \
  "$HOME/logs" \
  "$HOME/backups"

echo
echo "Bootstrap complete."
echo
echo "Manual steps still required:"
echo "1. Install/authenticate Tailscale if necessary."
echo "2. Install/configure Hermes."
echo "3. Restore API keys and secrets manually."
echo "4. Test SSH over Tailscale."
