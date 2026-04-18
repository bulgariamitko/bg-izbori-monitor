# BG Izbori — polling-station video monitor

> **Distributed, volunteer-run analysis of the live video broadcasts from
> Bulgarian Sectional Election Commissions (СИК) on evideo.bg.**
> Every person who runs this on their own Mac processes sections nobody
> else has touched. The more people who run it, the more of the country
> gets covered.

## What this does

For each polling station `evideo.bg` publishes a video of the ballot count
and protocol filling. This pipeline:

1. Scrapes the full section list.
2. Randomly picks a section nobody on your machine has done
   (villages first, then towns, then cities).
3. Downloads the counting video.
4. Transcribes the Bulgarian audio with **faster-whisper large-v3**.
5. Sends the transcript to **Claude Sonnet** (via `claude -p` headless
   mode, tools disabled to save tokens) to flag possible irregularities.
6. Stores everything in a local SQLite DB and rebuilds `dashboard.html`.
7. Deletes the mp4 to save disk.

The prompt asks Claude to flag **ballot tampering, miscounting,
protocol irregularities, intimidation, unauthorized persons, procedure
violations, and explicit disputes** — and only those. See `prompt.md`.

## Why distributed

Bulgaria has ~12 000 polling sections. Each recording is ~60 min and
takes ~45 min on a single Mac (download + large-v3 transcribe + Claude).
One machine can't cover the country. Ten can make a real dent. Everyone
runs the same code against the same list of sections, and the pipeline
picks random unseen ones — so two machines don't duplicate work.

(Coordination is currently *per-machine* only — see the Roadmap for a
shared ledger so multiple machines can skip what's already been done
by anyone.)



End-to-end pipeline for **evideo.bg**:

1. **scrape** sections → SQLite
2. **discover** recordings for every section
3. **download** (yt-dlp + Chrome cookie to bypass Cloudflare)
4. **transcribe** Bulgarian audio (`faster-whisper large-v3`, local)
5. **analyse** the transcript with Claude Sonnet via `claude -p`
6. **dashboard** regenerated after each section; `open dashboard.html`

Videos are deleted immediately after transcription succeeds.

## Prereqs

- macOS / Apple Silicon (or any box with ffmpeg + python 3.11+)
- Chrome installed, visit `https://evideo.bg/<slug>/` once so it passes
  the Cloudflare challenge — yt-dlp reuses that cookie.
- `brew install ffmpeg yt-dlp`
- `claude` CLI authenticated (`claude` opens once to set up, uses sonnet).

### Whisper model quality

`config.py` defaults to `medium` (~1.5 GB). Bulgarian transcription is
usable but noisy. For the real election **upgrade to `large-v3`**:

```python
# config.py
WHISPER_MODEL = "large-v3"
```

First run downloads ~3 GB. If HF hangs (it did for us), pre-fetch:

```bash
huggingface-cli download Systran/faster-whisper-large-v3
```

## Setup

```bash
cd "$(pwd)"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python db.py                   # creates bg_izbori.db
```

## Running

```bash
source venv/bin/activate

# 1. scrape the section list (one-shot)
python scrape_sections.py --slug le20260222

# 2. discover videos for every section
python discover_videos.py --slug le20260222

# 3. run the pipeline
python run_pipeline.py              # loops until no pending left
python run_pipeline.py --once       # one video and exit
python run_pipeline.py --max 10     # ten then exit

# dashboard is regenerated after each video; also manual:
python dashboard.py
open dashboard.html
```

## On election day (20 April 2026)

1. Open `https://evideo.bg/le20260420/index.html` in Chrome (passes CF)
2. Edit `config.py` — set `SLUG = "le20260420"`
3. Re-run `scrape_sections.py`, then `discover_videos.py`, then `run_pipeline.py`

The pipeline **picks villages first**, then towns, then cities, random
inside each tier — by the end every section is covered.

## Files

```
config.py            slug, paths, models
schema.sql           sections / videos / transcripts / findings
db.py                thin SQLite wrapper
scrape_sections.py   evideo.bg → sections table
discover_videos.py   sections → videos rows
process_video.py     one section: download → transcribe → analyse → delete
run_pipeline.py      loop process_video
dashboard.py         writes dashboard.html from DB
prompt.md            the Sonnet analysis prompt
election_day.sh     one-shot switch slug + scrape + discover + run
```

## Roadmap / contributions welcome

- [ ] Shared ledger (a public-read/volunteer-write bucket) so multiple
      machines don't re-do the same section.
- [ ] Groq / OpenAI Whisper API fallback for volunteers who want speed
      over cost.
- [ ] Windows / Linux setup notes.
- [ ] Parallel-worker wrapper (`run_pipeline.py` is single-worker today).
- [ ] Second-opinion reviewer — have a cheaper model pre-filter, so Sonnet
      only analyses transcripts that flag keywords.

PRs welcome. Open an issue first for anything bigger than a bug fix.

## Disclaimer

This is **not** an official monitoring tool. It surfaces *candidates* for
human review — findings can be wrong. Every "high" / "critical" finding
must be verified by a person watching the actual video at the flagged
timestamp before anyone acts on it. Do not publish findings without
watching the video first.


## What Claude flags

See `prompt.md`. Categories: tampering, miscounting, protocol,
intimidation, unauthorized persons, procedure violations, disputes.
Conservative — medium/high/critical are meant to wake a human.
