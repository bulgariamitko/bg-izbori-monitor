"""Central config. Change SLUG on election day."""
from pathlib import Path

BASE = Path(__file__).resolve().parent

# ---- election -----------------------------------------------------------
# Tomorrow's real election: change to 'pe202604'
# Testing with the 22 Feb 2026 archive (videos online, 8 OIKs)
SLUG        = "pe202604"     # Parliamentary Elections, April 2026 (evideo.bg pe202604).
BASE_URL    = f"https://evideo.bg/{SLUG}"
ARCHIVE_URL = f"https://archive.evideo.bg/{SLUG}"

# Single-round elections (like pe202604) only have tour 1.
# The 22-Feb archive has both tours; we default to tour 1.
TOURS = [1]

# ---- paths --------------------------------------------------------------
DB_PATH        = BASE / "bg_izbori.db"
VIDEOS_DIR     = BASE / "videos"
TRANSCRIPTS    = BASE / "transcripts"
DASHBOARD_HTML = BASE / "dashboard.html"
SECTIONS_JSON  = BASE / "sections_cache.json"
PROMPT_PATH    = BASE / "prompt.md"

for d in (VIDEOS_DIR, TRANSCRIPTS):
    d.mkdir(parents=True, exist_ok=True)

# ---- transcription ------------------------------------------------------
WHISPER_MODEL   = "large-v3"   # Best Bulgarian quality. ~3GB first download.
WHISPER_DEVICE  = "auto"       # faster-whisper picks cpu/metal
WHISPER_COMPUTE = "int8"       # small enough to run on Mac mini-class CPUs

# ---- analysis -----------------------------------------------------------
CLAUDE_MODEL = "claude-sonnet-4-6"

# ---- scraping -----------------------------------------------------------
# curl_cffi with Chrome impersonation bypasses the Cloudflare "Just a moment" page.
IMPERSONATE = "chrome131"
HEADERS = {
    "Referer": "https://evideo.bg/",
    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
}
# yt-dlp pulls the CF cookie from Chrome to download the mp4 itself.
COOKIES_FROM_BROWSER = "chrome"
