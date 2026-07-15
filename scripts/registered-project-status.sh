#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-}"
REGISTRY="$HOME/projects/imac-agent/config/projects.json"

if [ -z "$PROJECT" ]; then
  echo "Usage: $0 <project-name>"
  exit 1
fi

PROJECT_DIR=$(jq -r --arg project "$PROJECT" '.[$project].path // empty' "$REGISTRY")

if [ -z "$PROJECT_DIR" ]; then
  echo "ERROR: Project '$PROJECT' is not registered."
  exit 1
fi

if [ ! -d "$PROJECT_DIR/.git" ]; then
  echo "ERROR: $PROJECT_DIR is not a Git repository."
  exit 1
fi

echo "===== PROJECT ====="
echo "$PROJECT"

echo
echo "===== PATH ====="
echo "$PROJECT_DIR"

echo
echo "===== BRANCH ====="
git -C "$PROJECT_DIR" branch --show-current

echo
echo "===== STATUS ====="
git -C "$PROJECT_DIR" status --short

echo
echo "===== LATEST COMMIT ====="
git -C "$PROJECT_DIR" log -1 --oneline

echo
echo "===== REMOTE ====="
git -C "$PROJECT_DIR" remote -v
