#!/usr/bin/env bash
set -euo pipefail

mkdir -p "$HOME/.config/systemd/user"

cp "$HOME/projects/imac-agent/systemd/user/"*.service \
   "$HOME/.config/systemd/user/"

systemctl --user daemon-reload
systemctl --user enable --now imac-demo.service

echo "Installed user services."
