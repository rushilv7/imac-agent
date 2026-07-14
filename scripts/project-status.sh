#!/usr/bin/env bash
set -euo pipefail

echo "===== IMAC-AGENT REPOSITORY ====="
cd "$HOME/projects/imac-agent"

echo
echo "===== BRANCH ====="
git branch --show-current

echo
echo "===== STATUS ====="
git status --short

echo
echo "===== REMOTE ====="
git remote -v

echo
echo "===== LATEST COMMIT ====="
git log -1 --oneline

echo
echo "===== SYNC STATUS ====="
git fetch --quiet origin
git status -sb
