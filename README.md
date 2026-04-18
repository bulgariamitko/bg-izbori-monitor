# BG Izbori monitor

> **Distributed, volunteer-run video monitoring of Bulgarian polling
> stations** (видеоизлъчване от СИК на evideo.bg).
>
> Volunteers transcribe counting recordings on their own machines.
> Transcripts are committed to this repo. A separate step runs Claude
> Sonnet over the transcripts and commits findings.
>
> 📊 **Live dashboard:** <https://bulgariamitko.github.io/bg-izbori-monitor/>

## 🚀 Run in one command

**macOS / Linux:**
```bash
bash <(curl -sSL https://raw.githubusercontent.com/bulgariamitko/bg-izbori-monitor/main/install.sh)
```

**Windows (PowerShell):**
```powershell
iwr -useb https://raw.githubusercontent.com/bulgariamitko/bg-izbori-monitor/main/install.ps1 | iex
```

The installer pulls every dependency (git, python, ffmpeg, yt-dlp, gh),
prompts you to sign into GitHub (the login page has a **Sign up** link if
you don't have an account yet), forks this repo to your account, sets up
a Python venv, and starts transcribing — **high-risk polling stations
first**, then mid-risk, then villages, then towns and cities.

Every transcript you produce is `git push`ed to your fork automatically;
the auto-merger on this repo accepts it within a minute if the JSON
schema checks out.

💸 **Completely free.** No subscriptions, no API keys, no paid services
from you. All you contribute is your computer's CPU time (and a bit of
electricity). Every dependency — faster-whisper, yt-dlp, GitHub CLI — is
open source. The one paid step (Claude Sonnet analysis) runs on the
maintainer's machine, not yours.

## Which sections get picked first

`contribute.py` uses this priority, smallest first:

| Tier | Source |
|---|---|
| 1. Високорискови (high-risk) | `api.tibroish.bg` — statistical anomalies by the Anti-Corruption Fund (~781 sections) |
| 2. Средно-рискови (mid-risk) | `api.tibroish.bg` (~2 170 sections) |
| 3. Села (villages) | address starts with `С.` |
| 4. Малки градове (small towns) | address starts with `ГР.`, not a big city |
| 5. Големи градове (cities) | София, Пловдив, Варна, Бургас, Русе, Стара Загора |

Everything is randomised within a tier so two volunteers don't collide.

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

The owner (has Claude Code / API access) runs the watcher and walks away:

```bash
./watch.sh                           # pull → analyse new → push → sleep 60s, loop
# or a one-shot
python analyze.py --max 50
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
