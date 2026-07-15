#!/usr/bin/env bash
set -euo pipefail

journalctl --user -u imac-bot.service -n 100 --no-pager
