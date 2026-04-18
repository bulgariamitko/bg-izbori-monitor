#!/usr/bin/env bash
# Owner-side watcher. Keeps pulling volunteer transcripts and running
# Claude Sonnet analysis on anything new. Commits + pushes findings.
#
#   ./watch.sh                 # default 60s poll
#   INTERVAL=30 ./watch.sh     # poll every 30 seconds
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate
exec python analyze.py --watch --interval "${INTERVAL:-60}"
