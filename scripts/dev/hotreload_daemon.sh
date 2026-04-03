#!/usr/bin/env bash
set -euo pipefail

if ! command -v watchmedo >/dev/null 2>&1; then
  echo "watchmedo not found. Install with: pip install watchdog" >&2
  exit 1
fi

# Restart daemon (foreground) on Python source changes.
watchmedo auto-restart \
  --directory src/cccc \
  --patterns "*.py" \
  --recursive \
  --signal SIGTERM \
  -- python -m cccc.daemon_main run

