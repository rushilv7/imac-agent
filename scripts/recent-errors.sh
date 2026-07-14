#!/usr/bin/env bash

echo "===== RECENT HIGH-PRIORITY SYSTEM ERRORS ====="
journalctl \
  --priority=err \
  --since "24 hours ago" \
  --no-pager \
  -n 100
