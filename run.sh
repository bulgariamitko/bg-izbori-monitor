#!/usr/bin/env bash
# Owner one-command runner.
#
#   ./run.sh              # loop forever: pick → transcribe → claude → push → report
#   ./run.sh --once       # one section and exit
#   ./run.sh --max 10     # stop after 10 sections
#   ./run.sh --sik 093500013   # re-process / force one specific SIK
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate
exec python owner.py "$@"
