# Doprinasyane — become a volunteer transcriber

This project distributes the hard part of ballot-counting-video analysis
across many volunteer computers. **Your job, if you run this on your
Mac/Linux/Windows box, is to transcribe one polling-station video at a
time.** Claude analysis runs elsewhere — you don't need a Claude account.

## What you need

- A computer that can stay on for a few hours on election night
- ~10 GB free disk
- Python 3.11+
- `ffmpeg` and `yt-dlp` (`brew install ffmpeg yt-dlp` on macOS)
- Chrome browser (used once to pass Cloudflare and provide cookies)
- A GitHub account + `gh` CLI (`brew install gh && gh auth login`)

## Setup (one time)

```bash
# 1. Fork https://github.com/bulgariamitko/bg-izbori-monitor on GitHub,
#    then clone YOUR fork:
gh repo fork bulgariamitko/bg-izbori-monitor --clone
cd bg-izbori-monitor

# 2. Python deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Open https://evideo.bg/le20260420/ in Chrome once so Cloudflare
#    hands your browser a cookie. yt-dlp will reuse it.
```

## Running

```bash
source venv/bin/activate

# one section
python contribute.py --gh-handle yourhandle

# keep going until you stop it (recommended on election night)
python contribute.py --gh-handle yourhandle --loop
```

Each section takes ~45 min on a modern Mac (download + transcription).
When `contribute.py` starts / finishes a section it, for you, automatically:

1. Picks the next unclaimed SIK (ordering is seeded by your GitHub
   handle, so two volunteers naturally start on different sections).
2. Writes a tiny `claims/<SIK>_tour1.json` and opens a fast PR →
   other volunteers see your claim and skip this SIK.
3. Downloads the mp4 and runs faster-whisper.
4. Writes `transcripts/<SIK>_tour1.json`, deletes the claim file in the
   same commit, pushes a second PR.
5. The `validate-contribution` workflow runs, auto-merges if everything
   passes.
6. The script switches back to main, pulls, and picks the next section.

You never have to click anything on GitHub after `gh auth login`. If
your machine crashes mid-transcription, a scheduled workflow
(`sweep-stale-claims`) removes claims older than 4 hours every 30 min so
somebody else can pick up the section.

## What NOT to do

- Do not run `analyze.py` — that's the expensive-Claude step, owners only.
- Do not upload videos themselves, only the transcript JSON.
- Do not edit an existing `transcripts/<SIK>_tour*.json` that you didn't
  produce. If you think one is wrong, open an issue.
- Do not manually write transcripts — always run `contribute.py` so the
  JSON matches the schema the auto-merger expects.

## FAQ

**"I don't have a good computer"** — even 1 section/day helps. The goal
is breadth; every village covered is a win.

**"I transcribed but push was rejected"** — pull and try again:
`git pull --rebase origin main && git push`.

**"Which sections should I pick?"** — `contribute.py` picks for you,
villages first (small stations, under-monitored), then towns, then cities.

**"Will this use my bandwidth?"** — yes, ~800 MB downloaded per section
from `archive.evideo.bg`, plus a small JSON pushed to GitHub.

## Thank you

Every transcript someone else doesn't have to produce. Appreciated.
