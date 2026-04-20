"""Volunteer entry point. Picks one section nobody has transcribed yet,
runs faster-whisper on the recording, and pushes the JSON transcript back.

Run:
    python contribute.py              # one section, auto-push
    python contribute.py --no-push    # don't git-push (just commit locally)
    python contribute.py --loop       # keep going forever
    python contribute.py --gh-handle myname  # tag your contributions
"""
from __future__ import annotations
import argparse, hashlib, json, os, random, subprocess, sys, time
from pathlib import Path

import config, store

# Lazy import — only when we need to fetch fresh video URLs
def _fetch_section_videos(section: dict) -> list[dict]:
    """Re-fetch the OIK page for this section and parse out current video
    URLs. Needed because sections.json stores only chunk_count to stay
    small; the real URLs are fetched on demand."""
    import scrape as _sc
    from curl_cffi import requests
    s = requests.Session(impersonate=config.IMPERSONATE)
    s.headers.update(config.HEADERS)
    s.get(f"https://evideo.bg/{section['slug']}/index.html")
    r = s.get(section["oik_page"]); r.raise_for_status()
    rows = _sc.parse_oik_page(section["slug"], section["oik_page"], r.text)
    for row in rows:
        if row["sik"] == section["sik"]:
            return row.get("videos", [])
    return []

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

def _user_hash(sik: str, gh_handle: str) -> int:
    """Stable 64-bit hash so each volunteer walks the section list in a
    different order — halves the collision probability before claim files
    even come into play."""
    h = hashlib.sha256(f"{gh_handle}:{sik}".encode()).digest()
    return int.from_bytes(h[:8], "big")

def _chunk_sort_key(url: str) -> str:
    """Sort by the YYYYMMDDHHMMSS timestamp embedded in the filename."""
    name = url.rsplit("/",1)[-1]
    return name[:14]   # first 14 chars are the timestamp prefix

def pick_section(slug: str, gh_handle: str) -> tuple[dict, dict] | None:
    """Return (section, chosen_video_group).

    chosen_video_group = {"tour": int, "type": "device"|"live_hls"|"live",
                          "urls": [url, …]}  — one URL for device/HLS,
                          many chunks sorted chronologically for 'live'.

    Priority: high-risk → mid-risk → villages → towns → cities.
    Deterministic per-volunteer ordering within a tier.
    """
    sections = [s for s in store.load_sections() if s.get("slug") == slug]
    risk = load_risk_tiers()
    def key(s):
        r = risk.get(s["sik"])
        tier = RISK_RANK[r] if r in RISK_RANK else 2 + s.get("priority", 9)
        return (tier, _user_hash(s["sik"], gh_handle or "anon"))
    sections.sort(key=key)

    me = gh_handle or ""
    PREF = ("device", "live_hls", "live")
    for s in sections:
        vids = s.get("videos", [])
        # Compact stored form has {tour, type, chunk_count}; full form has
        # {tour, type, url}. Pick the preferred (tour, type) either way.
        chosen = None
        for kind in PREF:
            for v in vids:
                if v["type"] == kind: chosen = v; break
            if chosen: break
        if not chosen: continue
        tour = chosen["tour"]
        if store.has_transcript(s["sik"], tour): continue
        claim = store.load_claim(s["sik"], tour)
        if store.claim_is_active(claim, me): continue
        # Fetch actual URLs lazily if needed
        if "url" in chosen:  # legacy full form
            urls = [v["url"] for v in vids if v["tour"] == tour and v["type"] == chosen["type"]]
            urls.sort(key=_chunk_sort_key)
        else:
            fresh = _fetch_section_videos(s)
            urls = [v["url"] for v in fresh if v["tour"] == tour and v["type"] == chosen["type"]]
            urls.sort(key=_chunk_sort_key)
            if not urls:
                print(f"[pick] no URLs found after refetch for {s['sik']} — skipping",
                      file=sys.stderr)
                continue
        return s, {"tour": tour, "type": chosen["type"], "urls": urls}
    return None

# ----- pipeline steps ----------------------------------------------------

def _yt_dlp(url: str, out: Path, hls: bool):
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", config.COOKIES_FROM_BROWSER,
        "--referer", "https://evideo.bg/",
        "--no-part", "--no-progress", "--quiet", "--no-warnings",
    ]
    if hls:
        cmd += ["--live-from-start","--hls-use-mpegts","--merge-output-format","mp4"]
    cmd += ["-o", str(out), url]
    r = run_cmd(cmd)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"yt-dlp failed for {url}: {r.stderr.strip()[:300]}")

def download(urls: list[str], out: Path, tmpdir: Path):
    """Download a video or a chain of chunks and concatenate to `out`.

    - Single URL (device mp4 or HLS playlist) → one yt-dlp call.
    - Many URLs (pe-archive live chunks) → download sequentially,
      ffmpeg-concat into one mp4, delete chunks.
    """
    tmpdir.mkdir(parents=True, exist_ok=True)
    if out.exists(): out.unlink()
    if len(urls) == 1:
        print(f"[download] {urls[0].rsplit('/',1)[-1]} …", flush=True)
        t0 = time.time()
        _yt_dlp(urls[0], out, hls=urls[0].endswith(".m3u8"))
        print(f"[download] {out.stat().st_size/1e6:.1f} MB in {time.time()-t0:.1f}s", flush=True)
        return
    print(f"[download] {len(urls)} chunks …", flush=True)
    t0 = time.time()
    parts: list[Path] = []
    for i, u in enumerate(urls, 1):
        p = tmpdir / f"chunk_{i:05d}.mp4"
        _yt_dlp(u, p, hls=False)
        parts.append(p)
        if i % 10 == 0 or i == len(urls):
            print(f"  [{i}/{len(urls)}] chunks downloaded", flush=True)
    # ffmpeg concat via list file
    list_file = tmpdir / "concat.txt"
    list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    cmd = ["ffmpeg","-hide_banner","-v","error","-f","concat","-safe","0",
           "-i", str(list_file), "-c","copy","-y", str(out)]
    r = run_cmd(cmd)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"ffmpeg concat failed: {r.stderr.strip()[:400]}")
    for p in parts: p.unlink(missing_ok=True)
    list_file.unlink(missing_ok=True)
    print(f"[download] concat -> {out.stat().st_size/1e6:.1f} MB, "
          f"total {time.time()-t0:.1f}s", flush=True)

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

def _publish_claim(path: Path, sik: str, tour: int) -> bool:
    """Publish a claim file via a tiny PR that auto-merges in ~20 s. Returns
    False if the push failed (likely because someone else already claimed
    this SIK in the race window)."""
    direct_to_main = _origin_is_upstream() or not _upstream_exists()
    if _upstream_exists():
        git("fetch", UPSTREAM, "main", check=False)
        git("checkout", "main", check=False)
        git("reset","--hard", f"{UPSTREAM}/main", check=False)
    else:
        git("pull","--rebase","--autostash", check=False)
    # If another volunteer's claim already landed for this SIK, their file
    # now exists on main — skip.
    if path.exists() and path.stat().st_size and (config.BASE / "claims" / path.name).exists():
        pass  # either fresh from upstream (then it's their claim) or ours
    # re-write our claim (upstream might have wiped it during reset)
    if not path.exists():
        # upstream had someone else's claim for same SIK → bail out
        return False
    if direct_to_main:
        git("add", str(path))
        git("commit","-m", f"claim: СИК {sik} (tour {tour})", check=False)
        return git("push", check=False).returncode == 0

    branch = f"claim/{sik}-tour{tour}"
    git("checkout", "-B", branch)
    git("add", str(path))
    git("commit","-m", f"claim: СИК {sik} (tour {tour})", check=False)
    r = git("push","--set-upstream","origin",branch,"--force", check=False)
    if r.returncode != 0:
        print(f"[claim] push failed:\n{r.stderr}", file=sys.stderr)
        git("checkout","main", check=False); return False
    pr = run_cmd([
        "gh","pr","create",
        "--repo","bulgariamitko/bg-izbori-monitor",
        "--base","main","--head", f"{_gh_user()}:{branch}",
        "--title", f"claim: СИК {sik} (tour {tour})",
        "--body", f"Volunteer `{_gh_user()}` is claiming SIK {sik} tour {tour} "
                  f"for the next {store.CLAIM_TTL_HOURS} hours to avoid duplicate work.",
    ])
    git("checkout","main", check=False)
    if pr.returncode != 0 and "already exists" not in (pr.stderr or ""):
        print(f"[claim] pr create: {pr.stderr.strip()[:300]}", file=sys.stderr)
        return False
    print(f"[claim] claim PR opened for {sik}")
    return True

# ----- main orchestration ------------------------------------------------

def contribute_one(slug: str, gh_handle: str | None, push: bool) -> bool:
    pick = pick_section(slug, gh_handle or "")
    if not pick:
        print("[contribute] nothing to do — all sections have a transcript!")
        return False
    section, group = pick
    sik, tour = section["sik"], group["tour"]
    risk = load_risk_tiers().get(sik)
    risk_tag = f" [риск:{risk}]" if risk else ""
    n_urls = len(group["urls"])
    chunks_tag = f" · {n_urls} chunks" if n_urls > 1 else ""
    print(f"\n=== СИК {sik}{risk_tag}  {section.get('region_name')}  "
          f"{section.get('town','')} ({section.get('town_type','?')}) — "
          f"tour {tour}{chunks_tag} ===")

    # Place a claim FIRST so concurrent volunteers see we're working on this
    # SIK. Push it to GitHub ASAP via a small PR that auto-merges.
    if push:
        claim_path = store.write_claim(sik, tour, gh_handle or "anon")
        if not _publish_claim(claim_path, sik, tour):
            store.delete_claim(sik, tour)
            print("[contribute] claim push failed, trying next section", file=sys.stderr)
            return True

    mp4 = config.VIDEOS_DIR / f"{sik}_tour{tour}.mp4"
    tmpdir = config.VIDEOS_DIR / f"{sik}_tour{tour}.chunks"
    if mp4.exists(): mp4.unlink()
    try:
        download(group["urls"], mp4, tmpdir)
        t = transcribe(mp4)
        payload = {
            "schema": "bg-izbori-transcript/1",
            "sik": sik, "slug": slug, "tour": tour,
            "video_url": group["urls"][0],
            "video_type": group["type"],
            "chunk_count": n_urls,
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
        # Release the claim as part of the same commit
        claim_file = store._path("claim", sik, tour)
        extra_paths = [p]
        if claim_file.exists():
            claim_file.unlink()  # local delete
            extra_paths.append(claim_file)
        git_publish(extra_paths, sik, tour, push=push)
        return True
    finally:
        if mp4.exists(): mp4.unlink()
        # clean up chunk tmpdir
        if tmpdir.exists():
            for p in tmpdir.iterdir():
                try: p.unlink()
                except Exception: pass
            try: tmpdir.rmdir()
            except Exception: pass

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
