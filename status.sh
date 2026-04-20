#!/usr/bin/env bash
# Peek at what the owner runner is doing right now. Safe to run in a
# second terminal while `run.sh` is going.
cd "$(dirname "$0")"

echo "=== running processes ==="
pgrep -fl 'owner\.py|contribute\.py|analyze\.py|yt-dlp|faster[-_]whisper|whisper' || echo "(none)"
echo
echo "=== video working files (should be growing while downloading) ==="
ls -lh videos/ 2>/dev/null | tail -20
echo
for d in videos/*.chunks; do
  [ -d "$d" ] || continue
  n=$(ls "$d" 2>/dev/null | wc -l | tr -d ' ')
  sz=$(du -sh "$d" 2>/dev/null | awk '{print $1}')
  last=$(ls -t "$d" 2>/dev/null | head -1)
  last_age=$(stat -f '%Sm' -t '%H:%M:%S' "$d/$last" 2>/dev/null || echo "-")
  echo "  $d  chunks=$n  size=$sz  last=$last @ $last_age"
done
echo
echo "=== last 20 lines of the owner loop output ==="
if [ -t 1 ]; then
  # If a TTY, try to read the terminal where run.sh is running — otherwise nothing helpful.
  :
fi
echo
echo "=== DB counts ==="
printf "  sections in sections.json: "; python3 -c "import json;print(len(json.load(open('sections.json'))))" 2>/dev/null || echo "?"
printf "  transcripts committed:     "; ls transcripts/*.json 2>/dev/null | wc -l | tr -d ' '
printf "  findings committed:        "; ls findings/*.json 2>/dev/null | wc -l | tr -d ' '
printf "  active claims:             "; ls claims/*.json 2>/dev/null | wc -l | tr -d ' '
echo
echo "=== latest finding ==="
latest=$(ls -t findings/*.json 2>/dev/null | head -1)
if [ -n "$latest" ]; then
  python3 -c "
import json,sys
d=json.load(open('$latest'))
print(f\"  {d['sik']} · {d.get('region_name','')} · {d.get('town','')} — overall: {d.get('overall')}\")
print(f\"  {len(d.get('findings',[]))} signals\")
for f in d.get('findings',[])[:3]:
    print(f\"   - [{f.get('severity')}] {f.get('summary','')[:100]}\")
"
fi
