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

echo "Fetching registered project: $PROJECT"

git -C "$PROJECT_DIR" fetch --all --prune

echo
echo "===== LOCAL VS REMOTE ====="
git -C "$PROJECT_DIR" status -sb
