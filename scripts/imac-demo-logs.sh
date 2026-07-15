#!/usr/bin/env bash
set -euo pipefail

journalctl --user \
  -u imac-demo.service \
  -n 100 \
  --no-pager
