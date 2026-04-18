#!/usr/bin/env bash
# One-shot election-day script. Run on 20 April 2026 once evideo.bg/le20260420/ is live.
#
# Prereq: open https://evideo.bg/le20260420/ in Chrome once (CF cookie).
#
#   ./election_day.sh             # defaults to le20260420
#   ./election_day.sh le20260420
set -euo pipefail
SLUG="${1:-le20260420}"
cd "$(dirname "$0")"
source venv/bin/activate

echo ">>> [1/4] flipping SLUG -> $SLUG"
python -c "
import re, pathlib
p = pathlib.Path('config.py')
t = p.read_text()
t = re.sub(r'^SLUG\s*=\s*\".*\"', 'SLUG = \"$SLUG\"', t, count=1, flags=re.M)
p.write_text(t)
print([l for l in t.splitlines() if l.startswith('SLUG')][0])
"

echo ">>> [2/4] scraping sections"
python scrape_sections.py --slug "$SLUG"

echo ">>> [3/4] discovering videos"
python discover_videos.py --slug "$SLUG"

echo ">>> [4/4] starting pipeline (ctrl-C to stop)"
python run_pipeline.py
