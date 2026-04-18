# BG Izbori monitor

> **Distributed, volunteer-run video monitoring of Bulgarian polling
> stations** (видеоизлъчване от СИК на evideo.bg).
>
> Volunteers transcribe counting recordings on their own machines.
> Transcripts are committed to this repo. A separate step runs Claude
> Sonnet over the transcripts and commits findings. The dashboard at
> <https://bulgariamitko.github.io/bg-izbori-monitor/> is rebuilt
> automatically after each push.

## Why this exists

`evideo.bg` publishes live video of every polling station's ballot count
and protocol filling. Bulgaria has roughly 12 000 stations. No single
computer can transcribe all of them in a night. This project splits the
work: **many volunteers transcribe, the repo aggregates, one owner runs
the paid analysis step.**

## Two roles

### Transcriber (you, probably)

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the quick start.
Short version:

```bash
gh repo fork bulgariamitko/bg-izbori-monitor --clone
cd bg-izbori-monitor
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python contribute.py --gh-handle your-gh --loop
```

One section ≈ 45 min on a Mac. Your pushes auto-merge once the JSON
passes the schema check.

### Owner / analyst

The owner (has Claude Code / API access) runs:

```bash
source venv/bin/activate
python analyze.py --max 50          # Claude-analyse 50 un-reviewed transcripts
python dashboard.py                  # rebuild dashboard.html
```

`analyze.py` walks `transcripts/*.json` that don't have a matching
`findings/<SIK>_tour<N>.json`, sends each to Claude Sonnet via `claude -p`
(tools disabled to save tokens), writes the findings JSON, commits + pushes.
GitHub Pages republishes the dashboard automatically.

## File layout

```
sections.json            master list of SIKs + video URLs
transcripts/             one JSON per section (volunteer-written)
  └─ 013300088_tour1.json
findings/                one JSON per analysed section (owner-written)
  └─ 013300088_tour1.json
.github/workflows/       validate-transcripts + publish-pages
scrape.py                rebuild sections.json from evideo.bg
contribute.py            volunteer entry point (Whisper)
analyze.py               owner entry point (Claude)
dashboard.py             rebuild dashboard.html from the JSON files
prompt.md                the Sonnet analysis prompt
config.py                SLUG, WHISPER_MODEL, CLAUDE_MODEL
store.py                 thin filesystem helpers
```

## Election-day flow

For `le20260420`:

```bash
# 0. open https://evideo.bg/le20260420/ in Chrome once (CF cookie)
# 1. owner rebuilds section list and pushes sections.json:
python scrape.py --slug le20260420
git add sections.json && git commit -m "sections: le20260420" && git push

# 2. volunteers run:
python contribute.py --gh-handle your-gh --loop

# 3. owner keeps claude running:
python analyze.py
```

## What Claude flags

See `prompt.md`. Seven categories: ballot tampering, miscounting,
protocol irregularities, intimidation, unauthorized persons, procedure
violations, explicit disputes. Conservative by design — a
medium/high/critical finding is meant to be worth waking a human for.

## Disclaimer

This is **not** an official monitoring tool. The pipeline surfaces
*candidate* irregularities from audio transcripts that are themselves
imperfect. Every high / critical finding must be verified by a human
watching the actual video before anyone acts on it.

## License

MIT — see [LICENSE](LICENSE).

## Author

[@bulgariamitko](https://github.com/bulgariamitko). PRs welcome.
