"""Volunteer entry point. Picks one section nobody has transcribed yet,
runs faster-whisper on the recording, and pushes the JSON transcript back.

Run:
    python contribute.py              # one section, auto-push
    python contribute.py --no-push    # don't git-push (just commit locally)
    python contribute.py --loop       # keep going forever
    python contribute.py --gh-handle myname  # tag your contributions
"""
from __future__ import annotations
import argparse, json, os, random, subprocess, sys, time
from pathlib import Path

import config, store

RISK_FILE = config.BASE / "risk_tiers.json"
RISK_RANK = {"high": 0, "mid": 1}   # smaller = picked first

def load_risk_tiers() -> dict:
    if not RISK_FILE.exists(): return {}
    try: return json.loads(RISK_FILE.read_text()).get("tiers", {})
    except Exception: return {}

def run_cmd(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, text=True, capture_output=True, **kw)

# ----- load whisper lazily ------------------------------------------------

_whisper = None
def whisper():
    global _whisper
    if _whisper is None:
        print(f"[whisper] loading {config.WHISPER_MODEL} …", flush=True)
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE,
        )
    return _whisper

# ----- section picking ---------------------------------------------------

def pick_section(slug: str) -> tuple[dict, dict] | None:
    """Return (section, video) for something unprocessed.
    Priority order:
      1. high-risk sections (per tibroish.bg)
      2. mid-risk sections
      3. villages
      4. towns
      5. cities
      6. unknown
    Random within each tier.
    """
    sections = [s for s in store.load_sections() if s.get("slug") == slug]
    random.shuffle(sections)
    risk = load_risk_tiers()
    def rank(s):
        r = risk.get(s["sik"])
        if r in RISK_RANK: return RISK_RANK[r]          # 0, 1
        return 2 + s.get("priority", 9)                 # 2=village, 3=town, 4=city, 11=unknown
    sections.sort(key=rank)
    for s in sections:
        for v in s.get("videos", []):
            if v["type"] != "device":
                continue
            if store.has_transcript(s["sik"], v["tour"]):
                continue
            return s, v
    return None

# ----- pipeline steps ----------------------------------------------------

def download(video_url: str, out: Path):
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", config.COOKIES_FROM_BROWSER,
        "--referer", "https://evideo.bg/",
        "--no-part", "--no-progress", "--quiet",
        "--no-warnings",
        "-o", str(out), video_url,
    ]
    print(f"[download] {video_url.rsplit('/',1)[-1]} …", flush=True)
    t0 = time.time()
    r = run_cmd(cmd)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"yt-dlp failed: {r.stderr.strip()[:400]}")
    print(f"[download] {out.stat().st_size/1e6:.1f} MB in {time.time()-t0:.1f}s",
          flush=True)

def transcribe(path: Path) -> dict:
    print(f"[whisper] transcribing {path.name}", flush=True)
    t0 = time.time()
    segments, info = whisper().transcribe(
        str(path), language="bg",
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        beam_size=1,
    )
    segs = [{"start": round(s.start,2), "end": round(s.end,2), "text": s.text.strip()}
            for s in segments]
    full = "\n".join(
        f"[{int(s['start'])//60:02d}:{int(s['start'])%60:02d}] {s['text']}" for s in segs)
    print(f"[whisper] {len(segs)} segments in {time.time()-t0:.1f}s", flush=True)
    return {"segments": segs, "full_text": full, "duration_sec": info.duration}

def git(*args, check=True):
    r = run_cmd(["git", *args])
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:400]}")
    return r

UPSTREAM = "upstream"       # added during install as bulgariamitko/bg-izbori-monitor

def _upstream_exists() -> bool:
    return run_cmd(["git","remote","get-url",UPSTREAM]).returncode == 0

def _origin_is_upstream() -> bool:
    """If the user runs directly on the origin repo (owner), not a fork."""
    origin = run_cmd(["git","remote","get-url","origin"]).stdout.strip()
    return "bulgariamitko/bg-izbori-monitor" in origin

def git_publish(paths: list[Path], sik: str, tour: int, push: bool):
    """Per-transcript branch → push to fork → open PR → auto-merger handles it.

    Owner (origin == upstream repo) pushes directly to main and skips the PR.
    """
    if not push: return
    direct_to_main = _origin_is_upstream() or not _upstream_exists()

    # make sure main is up-to-date
    if _upstream_exists():
        git("fetch", UPSTREAM, "main", check=False)
        git("checkout", "main", check=False)
        git("reset", "--hard", f"{UPSTREAM}/main", check=False)
    else:
        git("pull", "--rebase", "--autostash", check=False)

    if direct_to_main:
        for p in paths: git("add", str(p))
        git("commit","-m", f"transcript: СИК {sik} (tour {tour})", check=False)
        r = git("push", check=False)
        if r.returncode == 0:
            print(f"[git] pushed transcript directly to main")
        else:
            print(f"[git] push failed:\n{r.stderr}", file=sys.stderr)
        return

    # Fork + PR flow
    branch = f"transcript/{sik}-tour{tour}"
    git("checkout", "-B", branch)
    for p in paths: git("add", str(p))
    msg = f"transcript: СИК {sik} (tour {tour})"
    git("commit","-m", msg, check=False)
    r = git("push", "--set-upstream", "origin", branch, "--force", check=False)
    if r.returncode != 0:
        print(f"[git] push failed:\n{r.stderr}", file=sys.stderr); return

    # open PR via gh (also auto-enables auto-merge)
    pr = run_cmd([
        "gh","pr","create",
        "--repo","bulgariamitko/bg-izbori-monitor",
        "--base","main","--head", f"{_gh_user()}:{branch}",
        "--title", msg,
        "--body", f"Auto-generated transcript for СИК {sik}, tour {tour}.\n\n"
                  f"Produced by `contribute.py` using faster-whisper "
                  f"`{config.WHISPER_MODEL}`. Will auto-merge after the "
                  f"`validate-transcripts` workflow passes.",
    ])
    if pr.returncode != 0 and "already exists" not in (pr.stderr or ""):
        print(f"[gh] pr create: {pr.stderr.strip()[:300]}", file=sys.stderr)
    else:
        print(f"[gh] PR opened / updated for {branch}")

    # back to main, ready for next section
    git("checkout","main", check=False)

def _gh_user() -> str:
    r = run_cmd(["gh","api","user","--jq",".login"])
    return r.stdout.strip() if r.returncode == 0 else ""

# ----- main orchestration ------------------------------------------------

def contribute_one(slug: str, gh_handle: str | None, push: bool) -> bool:
    pick = pick_section(slug)
    if not pick:
        print("[contribute] nothing to do — all sections have a transcript!")
        return False
    section, video = pick
    sik, tour = section["sik"], video["tour"]
    risk = load_risk_tiers().get(sik)
    risk_tag = f" [риск:{risk}]" if risk else ""
    print(f"\n=== СИК {sik}{risk_tag}  {section.get('region_name')}  "
          f"{section.get('town','')} ({section.get('town_type','?')}) — tour {tour} ===")

    mp4 = config.VIDEOS_DIR / f"{sik}_tour{tour}.mp4"
    if mp4.exists(): mp4.unlink()
    try:
        download(video["url"], mp4)
        t = transcribe(mp4)
        payload = {
            "schema": "bg-izbori-transcript/1",
            "sik": sik, "slug": slug, "tour": tour,
            "video_url": video["url"], "video_type": video["type"],
            "duration_sec": t["duration_sec"],
            "region_name": section.get("region_name"),
            "address": section.get("address"),
            "town": section.get("town"), "town_type": section.get("town_type"),
            "risk_level": load_risk_tiers().get(sik),  # high | mid | null
            "whisper": {
                "model": config.WHISPER_MODEL,
                "language": "bg",
                "compute_type": config.WHISPER_COMPUTE,
            },
            "contributed_by": gh_handle or "",
            "transcribed_at": store.utcnow(),
            "segments": t["segments"],
            "full_text": t["full_text"],
        }
        p = store.save_transcript(payload)
        print(f"[store] wrote {p.relative_to(config.BASE)}")
        git_publish([p], sik, tour, push=push)
        return True
    finally:
        if mp4.exists(): mp4.unlink()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=config.SLUG)
    ap.add_argument("--gh-handle", default=os.environ.get("GH_HANDLE",""))
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--loop", action="store_true", help="keep going until no work left")
    args = ap.parse_args()
    while True:
        ok = contribute_one(args.slug, args.gh_handle, push=not args.no_push)
        if not ok: break
        if not args.loop: break

if __name__ == "__main__":
    main()
