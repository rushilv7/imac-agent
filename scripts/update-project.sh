#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <project-name>"
  exit 1
fi

PROJECT="$1"
PROJECT_DIR="$HOME/projects/$PROJECT"

if [ ! -d "$PROJECT_DIR/.git" ]; then
  echo "ERROR: $PROJECT_DIR is not a Git repository."
  exit 1
fi

cd "$PROJECT_DIR"

echo "===== PROJECT ====="
pwd

echo
echo "===== CURRENT STATUS ====="
git status --short

echo
echo "===== FETCHING ====="
git fetch --all --prune

echo
echo "===== PULLING ====="
git pull --ff-only

echo
echo "===== FINAL COMMIT ====="
git log -1 --oneline
