#!/usr/bin/env bash
# Single entry point for everyone.
#
# Volunteer (default — just transcribe, open a PR from your fork):
#   ./run.sh                     # loop: pick → transcribe → push, forever
#   ./run.sh --no-push           # don't git-push (just commit locally)
#   ./run.sh --gh-handle myname  # tag your contributions (also GH_HANDLE env)
#
# Owner (pushes to main, runs Claude analysis too):
#   ./run.sh --owner             # loop: pick → transcribe → claude → push
#   ./run.sh --owner --once      # one section and exit
#   ./run.sh --owner --max 10    # stop after 10 sections
#   ./run.sh --owner --sik 093500013   # re-process one specific SIK
#
# --analyze is an alias for --owner.
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate

if [[ "${1:-}" == "--owner" || "${1:-}" == "--analyze" ]]; then
  shift
  exec python owner.py "$@"
else
  exec python contribute.py --loop "$@"
fi
