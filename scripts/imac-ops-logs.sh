#!/usr/bin/env bash
set -euo pipefail

journalctl \
  --user \
  -u imac-ops.service \
  -n 100 \
  --no-pager
